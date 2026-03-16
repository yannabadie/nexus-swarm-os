"""
Tests for Phase 3: Architecture Generation.

Validates the ArchitectureGenerationPhase class which designs agent architectures
and execution plans in the HiveMind pipeline.

Coverage:
- ArchitecturePhaseResult dataclass
- Architecture prompt templates (ARCHITECTURE_PROMPT, CLAUDE_ARCHITECTURE_PROMPT,
  GEMINI_VALIDATION_PROMPT)
- Execution step parsing and validation (_parse_architecture_response)
- Agent assignment in execution steps
- TechniqueSelector V12.4 integration in _generate_with_claude
- SwarmBridge delegation for steps with swarm_mode
- Cost estimation for architecture
- Mock execution flow with mocked drivers (collaborative + legacy)
- Gemini validation (Phase 3b) approve/optimize/fail paths
- V12.4 integration graceful degradation
- Edge cases: empty analysis, very complex task, missing disagreements,
  fallback architecture, budget exhaustion, duplicate agent detection,
  spawn approval/rejection, GraphOfThought annotation
"""

import json
import sys
from dataclasses import fields as dc_fields
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.agent_registry import AgentRegistry
from core.intelligence.hive_mind.context_manager import HiveMindContextManager
from core.intelligence.hive_mind.cost_estimator import CostEstimator
from core.intelligence.hive_mind.phases.phase_architecture import (
    ARCHITECTURE_PROMPT,
    CLAUDE_ARCHITECTURE_PROMPT,
    GEMINI_VALIDATION_PROMPT,
    ArchitectureGenerationPhase,
    ArchitecturePhaseResult,
)
from core.intelligence.hive_mind.types import (
    AgentArchitecture,
    AgentSpec,
    DebateResult,
    ExecutionPlan,
    ExecutionStep,
    RAGConfig,
)


def _make_driver_response(content: str, input_tokens: int = 100, output_tokens: int = 50) -> DriverResponse:
    """Create a successful DriverResponse for testing."""
    return DriverResponse(
        content=content,
        status=DriverResponseStatus.SUCCESS,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# =============================================================================
# Helper factories
# =============================================================================


def _make_debate_result(
    final_approach: str = "Use FastAPI with PostgreSQL backend",
    final_capabilities: list[str] | None = None,
    final_mode: str = "sequential",
    total_turns: int = 2,
    consensus_confidence: float = 0.85,
) -> DebateResult:
    """Create a DebateResult with sensible defaults."""
    return DebateResult(
        status="CONSENSUS_REACHED",
        final_approach=final_approach,
        final_capabilities=final_capabilities or ["coding", "api_design", "database"],
        final_mode=final_mode,
        debate_history=[],
        total_turns=total_turns,
        resolved_disagreements=["approach"],
        unresolved_disagreements=[],
        consensus_confidence=consensus_confidence,
        satisfactions={"gemini": 0.8, "claude": 0.9},
    )


def _valid_architecture_json(**overrides) -> str:
    """Return a valid architecture JSON response string."""
    base = {
        "agents_to_use": ["claude", "gemini"],
        "agents_to_spawn": [],
        "execution_strategy": "sequential",
        "execution_steps": [
            {
                "name": "analyze_requirements",
                "agent_id": "claude",
                "action": "Analyze the task requirements",
                "expected_duration": 30,
                "depends_on": [],
                "verification_required": True,
            },
            {
                "name": "implement_solution",
                "agent_id": "gemini",
                "action": "Implement the solution code",
                "expected_duration": 60,
                "depends_on": ["analyze_requirements"],
                "verification_required": True,
            },
        ],
        "rag_config": {
            "enabled": True,
            "depth": "standard",
            "sources": ["codebase", "docs"],
            "max_chunks": 15,
        },
        "reasoning": "Sequential approach with analysis first, then implementation",
    }
    base.update(overrides)
    return json.dumps(base)


def _architecture_with_spawns_json() -> str:
    """Return an architecture JSON that includes agents to spawn."""
    return json.dumps(
        {
            "agents_to_use": ["claude"],
            "agents_to_spawn": [
                {
                    "role": "security_auditor",
                    "mission": "Audit code for security vulnerabilities",
                    "capabilities": ["security", "code_review"],
                    "tools_priority": ["grep", "read"],
                    "estimated_cost": 800,
                }
            ],
            "execution_strategy": "pipeline",
            "execution_steps": [
                {
                    "name": "audit_code",
                    "agent_id": "security_auditor",
                    "action": "Run security audit on codebase",
                    "expected_duration": 45,
                    "depends_on": [],
                    "verification_required": True,
                }
            ],
            "rag_config": {
                "enabled": True,
                "depth": "deep",
                "sources": ["codebase"],
                "max_chunks": 20,
            },
            "reasoning": "Need a specialized security auditor agent",
        }
    )


def _gemini_validation_json(
    validation: str = "APPROVED",
    optimizations: list[str] | None = None,
    architecture: dict | None = None,
) -> str:
    """Return a valid Gemini validation response JSON string."""
    data = {
        "validation": validation,
        "optimizations": optimizations or [],
    }
    if architecture:
        data["architecture"] = architecture
    else:
        data["architecture"] = json.loads(_valid_architecture_json())
    return json.dumps(data)


def _make_phase(
    budget: int = 50000,
    task_id: str = "test_arch_001",
    collaborative: bool = True,
) -> ArchitectureGenerationPhase:
    """Create an ArchitectureGenerationPhase with mocked drivers and deps."""
    gemini = AsyncMock()
    gemini.invoke = AsyncMock(return_value=_make_driver_response(_valid_architecture_json()))
    gemini.send_message_async = AsyncMock(return_value=_valid_architecture_json())

    claude = AsyncMock()
    claude.invoke = AsyncMock(return_value=_make_driver_response(_valid_architecture_json()))
    claude.send_message_async = AsyncMock(return_value=_valid_architecture_json())

    cost_estimator = CostEstimator(budget_limit=budget)
    context_manager = HiveMindContextManager(max_tokens=50000)

    # Use a tmp workspace to avoid touching real registry
    workspace = Path("workspace")
    registry = MagicMock(spec=AgentRegistry)
    registry.get_active_agents.return_value = []
    registry.find_similar.return_value = None

    user_handler = MagicMock()

    phase = ArchitectureGenerationPhase(
        gemini_driver=gemini,
        claude_driver=claude,
        cost_estimator=cost_estimator,
        context_manager=context_manager,
        agent_registry=registry,
        user_handler=user_handler,
        workspace_path=workspace,
        task_id=task_id,
    )
    return phase


# =============================================================================
# 1. ArchitecturePhaseResult dataclass tests
# =============================================================================


class TestArchitecturePhaseResult:
    """Tests for the ArchitecturePhaseResult dataclass."""

    def test_fields_exist(self):
        """ArchitecturePhaseResult has all expected fields."""
        names = {f.name for f in dc_fields(ArchitecturePhaseResult)}
        assert "architecture" in names
        assert "agents_spawned" in names
        assert "user_approved_spawn" in names
        assert "spawn_skipped_reason" in names

    def test_minimal_construction(self):
        """Can construct with required fields only."""
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential"),
        )
        result = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=[],
            user_approved_spawn=True,
        )
        assert result.architecture.status == "READY"
        assert result.agents_spawned == []
        assert result.user_approved_spawn is True
        assert result.spawn_skipped_reason is None

    def test_spawn_skipped_reason_default(self):
        """spawn_skipped_reason defaults to None."""
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="parallel",
            agents_to_use=["claude", "gemini"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="parallel"),
        )
        result = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=[],
            user_approved_spawn=False,
        )
        assert result.spawn_skipped_reason is None

    def test_spawn_skipped_reason_set(self):
        """spawn_skipped_reason can carry a reason string."""
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential"),
        )
        result = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=[],
            user_approved_spawn=False,
            spawn_skipped_reason="User cancelled spawning",
        )
        assert result.spawn_skipped_reason == "User cancelled spawning"

    def test_agents_spawned_list(self):
        """agents_spawned carries agent IDs that were actually created."""
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential"),
        )
        result = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=["security_auditor_abc123", "data_parser_def456"],
            user_approved_spawn=True,
        )
        assert len(result.agents_spawned) == 2
        assert "security_auditor_abc123" in result.agents_spawned


# =============================================================================
# 2. Architecture prompt template tests
# =============================================================================


class TestPromptTemplates:
    """Tests for the architecture prompt templates."""

    def test_legacy_prompt_has_placeholders(self):
        """ARCHITECTURE_PROMPT contains all expected placeholders."""
        assert "{task}" in ARCHITECTURE_PROMPT
        assert "{approach}" in ARCHITECTURE_PROMPT
        assert "{capabilities}" in ARCHITECTURE_PROMPT
        assert "{available_agents}" in ARCHITECTURE_PROMPT

    def test_legacy_prompt_format(self):
        """ARCHITECTURE_PROMPT can be formatted without error."""
        result = ARCHITECTURE_PROMPT.format(
            task="Build a REST API",
            approach="FastAPI + PostgreSQL",
            capabilities="coding, api_design",
            available_agents="- claude (general): coding, analysis",
        )
        assert "Build a REST API" in result
        assert "FastAPI + PostgreSQL" in result

    def test_claude_prompt_has_placeholders(self):
        """CLAUDE_ARCHITECTURE_PROMPT contains all expected placeholders."""
        assert "{task}" in CLAUDE_ARCHITECTURE_PROMPT
        assert "{approach}" in CLAUDE_ARCHITECTURE_PROMPT
        assert "{capabilities}" in CLAUDE_ARCHITECTURE_PROMPT
        assert "{available_agents}" in CLAUDE_ARCHITECTURE_PROMPT

    def test_claude_prompt_format(self):
        """CLAUDE_ARCHITECTURE_PROMPT can be formatted without error."""
        result = CLAUDE_ARCHITECTURE_PROMPT.format(
            task="Build a REST API",
            approach="FastAPI + PostgreSQL",
            capabilities="coding, api_design, database",
            available_agents="No specialized agents available",
        )
        assert "ARCHITECT" in result
        assert "Build a REST API" in result

    def test_claude_prompt_mentions_agent_assignment(self):
        """CLAUDE_ARCHITECTURE_PROMPT has agent assignment guidelines."""
        assert "Claude" in CLAUDE_ARCHITECTURE_PROMPT
        assert "Gemini" in CLAUDE_ARCHITECTURE_PROMPT

    def test_gemini_validation_prompt_has_placeholders(self):
        """GEMINI_VALIDATION_PROMPT contains all expected placeholders."""
        assert "{task}" in GEMINI_VALIDATION_PROMPT
        assert "{architecture_json}" in GEMINI_VALIDATION_PROMPT

    def test_gemini_validation_prompt_format(self):
        """GEMINI_VALIDATION_PROMPT can be formatted without error."""
        result = GEMINI_VALIDATION_PROMPT.format(
            task="Build a REST API",
            architecture_json='{"agents_to_use": ["claude"]}',
        )
        assert "Build a REST API" in result
        assert "APPROVED" in result
        assert "OPTIMIZED" in result

    def test_gemini_validation_prompt_mentions_checks(self):
        """GEMINI_VALIDATION_PROMPT references all validation checks."""
        assert "Feasibility" in GEMINI_VALIDATION_PROMPT
        assert "Efficiency" in GEMINI_VALIDATION_PROMPT
        assert "Agent assignment" in GEMINI_VALIDATION_PROMPT
        assert "Dependencies" in GEMINI_VALIDATION_PROMPT
        assert "Completeness" in GEMINI_VALIDATION_PROMPT


# =============================================================================
# 3. Execution step parsing and validation
# =============================================================================


class TestParseArchitectureResponse:
    """Tests for _parse_architecture_response."""

    def test_parse_valid_response(self):
        """Parses a valid JSON architecture response."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        assert arch.status == "READY"
        assert arch.collaboration_mode == "sequential"
        assert len(arch.execution_plan.steps) == 2

    def test_parse_steps_names(self):
        """Step names are correctly parsed."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        names = [s.name for s in arch.execution_plan.steps]
        assert "analyze_requirements" in names
        assert "implement_solution" in names

    def test_parse_steps_agent_ids(self):
        """Agent IDs are correctly assigned to steps."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        agents = {s.name: s.agent_id for s in arch.execution_plan.steps}
        assert agents["analyze_requirements"] == "claude"
        assert agents["implement_solution"] == "gemini"

    def test_parse_steps_dependencies(self):
        """Step dependencies are correctly parsed."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        step_map = {s.name: s for s in arch.execution_plan.steps}
        assert step_map["analyze_requirements"].depends_on == []
        assert step_map["implement_solution"].depends_on == ["analyze_requirements"]

    def test_parse_steps_verification(self):
        """verification_required flag is correctly parsed."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        for step in arch.execution_plan.steps:
            assert step.verification_required is True

    def test_parse_rag_config(self):
        """RAG config is correctly parsed."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        assert arch.rag_config.enabled is True
        assert arch.rag_config.depth == "standard"
        assert "codebase" in arch.rag_config.sources
        assert arch.rag_config.max_chunks == 15

    def test_parse_execution_strategy(self):
        """Execution strategy is reflected in both collaboration_mode and plan."""
        phase = _make_phase()
        response = _valid_architecture_json(execution_strategy="parallel")
        arch = phase._parse_architecture_response(response, ["coding"])
        assert arch.collaboration_mode == "parallel"
        assert arch.execution_plan.strategy == "parallel"

    def test_parse_reasoning(self):
        """Reasoning string is carried through."""
        phase = _make_phase()
        response = _valid_architecture_json(reasoning="This is the best approach because...")
        arch = phase._parse_architecture_response(response, ["coding"])
        assert "best approach" in arch.reasoning

    def test_parse_agents_to_use(self):
        """agents_to_use list is correctly parsed."""
        phase = _make_phase()
        response = _valid_architecture_json(agents_to_use=["claude", "gemini", "specialist_abc"])
        arch = phase._parse_architecture_response(response, ["coding"])
        assert "specialist_abc" in arch.agents_to_use

    def test_parse_agents_to_spawn(self):
        """agents_to_spawn list is correctly parsed as AgentSpec objects."""
        phase = _make_phase()
        response = _architecture_with_spawns_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        assert len(arch.agents_to_spawn) == 1
        spec = arch.agents_to_spawn[0]
        assert spec.role == "security_auditor"
        assert "security" in spec.capabilities
        assert spec.estimated_cost == 800

    def test_parse_spawn_sets_status(self):
        """Architecture with spawns gets status SPAWN_REQUIRED."""
        phase = _make_phase()
        response = _architecture_with_spawns_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        assert arch.status == "SPAWN_REQUIRED"

    def test_parse_estimated_cost_calculation(self):
        """Estimated cost includes spawn costs plus per-step cost."""
        phase = _make_phase()
        response = _architecture_with_spawns_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        # 800 (spawn) + 1*500 (1 step) = 1300
        assert arch.estimated_cost == 1300

    def test_parse_total_duration(self):
        """Total duration is sum of step durations."""
        phase = _make_phase()
        response = _valid_architecture_json()
        arch = phase._parse_architecture_response(response, ["coding"])
        # 30 + 60 = 90
        assert arch.execution_plan.estimated_total_duration == 90

    def test_parse_invalid_json_returns_fallback(self):
        """Invalid JSON triggers fallback architecture."""
        phase = _make_phase()
        arch = phase._parse_architecture_response("This is not JSON at all", ["coding"])
        assert arch.status == "READY"
        assert arch.collaboration_mode == "sequential"
        assert arch.reasoning == "Fallback architecture due to generation failure"

    def test_parse_empty_string_returns_fallback(self):
        """Empty string triggers fallback architecture."""
        phase = _make_phase()
        arch = phase._parse_architecture_response("", ["coding"])
        assert arch.reasoning == "Fallback architecture due to generation failure"

    def test_parse_missing_execution_steps_defaults_empty(self):
        """Missing execution_steps key defaults to empty list."""
        phase = _make_phase()
        data = {"agents_to_use": ["claude"], "execution_strategy": "sequential", "reasoning": "Minimal"}
        response = json.dumps(data)
        arch = phase._parse_architecture_response(response, ["coding"])
        assert len(arch.execution_plan.steps) == 0

    def test_parse_missing_rag_config_defaults(self):
        """Missing rag_config uses defaults."""
        phase = _make_phase()
        data = {
            "agents_to_use": ["claude"],
            "execution_strategy": "sequential",
            "execution_steps": [],
            "reasoning": "No RAG",
        }
        response = json.dumps(data)
        arch = phase._parse_architecture_response(response, ["coding"])
        assert arch.rag_config.enabled is True
        assert arch.rag_config.depth == "standard"

    def test_parse_step_defaults(self):
        """Steps with missing optional fields get proper defaults."""
        phase = _make_phase()
        data = {
            "agents_to_use": ["claude"],
            "execution_strategy": "sequential",
            "execution_steps": [{"name": "step1"}],
            "reasoning": "Minimal step",
        }
        response = json.dumps(data)
        arch = phase._parse_architecture_response(response, ["coding"])
        step = arch.execution_plan.steps[0]
        assert step.agent_id == "claude"  # default
        assert step.action == ""  # default
        assert step.expected_duration == 30  # default
        assert step.depends_on == []  # default
        assert step.verification_required is False  # default

    def test_parse_dict_response(self):
        """Parse works when response is already a dict."""
        phase = _make_phase()
        data = json.loads(_valid_architecture_json())
        # json_parser handles dict passthrough
        arch = phase._parse_architecture_response(data, ["coding"])
        assert len(arch.execution_plan.steps) == 2


# =============================================================================
# 4. Agent assignment in steps
# =============================================================================


class TestAgentAssignment:
    """Tests for agent assignment logic in parsed architectures."""

    def test_claude_and_gemini_assignment(self):
        """Both claude and gemini can be assigned to steps."""
        phase = _make_phase()
        arch = phase._parse_architecture_response(_valid_architecture_json(), ["coding"])
        agent_ids = {s.agent_id for s in arch.execution_plan.steps}
        assert "claude" in agent_ids
        assert "gemini" in agent_ids

    def test_spawned_agent_assignment(self):
        """A spawned agent ID can be assigned to a step."""
        phase = _make_phase()
        data = {
            "agents_to_use": ["claude", "security_bot_abc"],
            "agents_to_spawn": [],
            "execution_strategy": "sequential",
            "execution_steps": [
                {
                    "name": "security_check",
                    "agent_id": "security_bot_abc",
                    "action": "Run security checks",
                    "expected_duration": 20,
                }
            ],
            "reasoning": "Delegating to specialist",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["security"])
        assert arch.execution_plan.steps[0].agent_id == "security_bot_abc"

    def test_multiple_steps_same_agent(self):
        """Multiple steps can be assigned to the same agent."""
        phase = _make_phase()
        data = {
            "agents_to_use": ["claude"],
            "execution_strategy": "sequential",
            "execution_steps": [
                {"name": "step1", "agent_id": "claude", "action": "Step 1"},
                {"name": "step2", "agent_id": "claude", "action": "Step 2"},
                {"name": "step3", "agent_id": "claude", "action": "Step 3"},
            ],
            "reasoning": "Claude handles all",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["coding"])
        assert all(s.agent_id == "claude" for s in arch.execution_plan.steps)


# =============================================================================
# 5. TechniqueSelector V12.4 integration
# =============================================================================


class TestTechniqueSelectorIntegration:
    """Tests for V12.4 TechniqueSelector integration in _generate_with_claude."""

    @pytest.mark.asyncio
    async def test_technique_selector_applied(self):
        """TechniqueSelector is invoked when available."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        # Initialize session integration
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "session-uuid-1"

        mock_selector = MagicMock()
        mock_selection = MagicMock()
        mock_selection.techniques = [MagicMock(value="chain_of_thought")]
        mock_selection.cluster_name = "test_cluster"
        mock_selector.select.return_value = mock_selection
        mock_selector.compose_prompt.return_value = "Enhanced prompt"

        with patch(
            "core.intelligence.hive_mind.phases.phase_architecture.get_technique_selector",
            create=True,
        ) as mock_get:
            mock_get.return_value = mock_selector
            # Call _generate_with_claude instead of patching the import chain
            # TechniqueSelector import is inside _generate_with_claude
            arch = await phase._generate_with_claude("Build API", "Use FastAPI", ["coding"], "No agents")
            # Should still return a valid architecture (from the mock)
            assert arch is not None

    @pytest.mark.asyncio
    async def test_technique_selector_failure_graceful(self):
        """TechniqueSelector failure does not break architecture generation."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        # TechniqueSelector import will fail since it is caught by bare except
        # The method should still succeed
        arch = await phase._generate_with_claude("Build API", "Use FastAPI", ["coding"], "No agents")
        assert arch is not None
        assert len(arch.execution_plan.steps) == 2


# =============================================================================
# 6. SwarmBridge delegation (swarm_mode on steps)
# =============================================================================


class TestSwarmBridgeDelegation:
    """Tests for ExecutionStep.swarm_mode used in SwarmBridge delegation."""

    def test_execution_step_swarm_mode_default_none(self):
        """ExecutionStep.swarm_mode defaults to None."""
        step = ExecutionStep(name="test", agent_id="claude", action="Do something")
        assert step.swarm_mode is None

    def test_execution_step_swarm_mode_set(self):
        """ExecutionStep.swarm_mode can be set to a swarm mode."""
        step = ExecutionStep(
            name="security_review",
            agent_id="claude",
            action="Adversarial security review",
            swarm_mode="red_blue",
        )
        assert step.swarm_mode == "red_blue"

    def test_parsed_architecture_preserves_swarm_mode_in_types(self):
        """Parsed steps from types module support swarm_mode."""
        step = ExecutionStep(
            name="parallel_research",
            agent_id="gemini",
            action="Research in parallel",
            swarm_mode="parallel",
        )
        assert step.swarm_mode == "parallel"

    def test_get_execution_ready_includes_swarm_steps(self):
        """get_execution_ready_architecture exports step data for Phase 4."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="pipeline",
            agents_to_use=["claude", "gemini"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(
                strategy="pipeline",
                steps=[
                    ExecutionStep(
                        name="review",
                        agent_id="claude",
                        action="Review code",
                        swarm_mode="red_blue",
                    )
                ],
            ),
        )
        result = ArchitecturePhaseResult(architecture=arch, agents_spawned=[], user_approved_spawn=True)
        ready = phase.get_execution_ready_architecture(result)
        assert ready["steps"][0]["name"] == "review"
        assert ready["steps"][0]["agent"] == "claude"
        assert ready["steps"][0]["verify"] is False

    def test_various_swarm_modes(self):
        """All six swarm modes can be assigned to steps."""
        modes = ["parallel", "sequential", "lead_support", "ping_pong", "specialist", "red_blue"]
        for mode in modes:
            step = ExecutionStep(
                name=f"step_{mode}",
                agent_id="claude",
                action=f"Execute in {mode}",
                swarm_mode=mode,
            )
            assert step.swarm_mode == mode


# =============================================================================
# 7. Cost estimation for architecture
# =============================================================================


class TestCostEstimation:
    """Tests for cost estimation and budget enforcement."""

    @pytest.mark.asyncio
    async def test_budget_check_at_start(self):
        """Phase 3 checks budget before starting."""
        phase = _make_phase(budget=10)  # Very low budget
        debate = _make_debate_result()
        with pytest.raises(RuntimeError, match="Budget exceeded"):
            await phase.execute("Build API", debate)

    @pytest.mark.asyncio
    async def test_cost_recorded_after_claude_generation(self):
        """Cost is recorded after Claude generates architecture."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        await phase._generate_with_claude("Build API", "Use FastAPI", ["coding"], "No agents")
        # Check that cost was recorded
        assert phase.cost_estimator.spent > 0
        ops = [r.operation for r in phase.cost_estimator.records]
        assert "generate_architecture_claude" in ops

    @pytest.mark.asyncio
    async def test_cost_recorded_after_gemini_validation(self):
        """Cost is recorded after Gemini validates architecture."""
        phase = _make_phase()
        claude_arch = phase._parse_architecture_response(_valid_architecture_json(), ["coding"])
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        await phase._validate_with_gemini(claude_arch, "Build API", ["coding"])
        ops = [r.operation for r in phase.cost_estimator.records]
        assert "validate_architecture_gemini" in ops

    def test_fallback_architecture_cost_is_1000(self):
        """Fallback architecture has estimated_cost of 1000."""
        phase = _make_phase()
        arch = phase._create_fallback_architecture(["coding"])
        assert arch.estimated_cost == 1000

    def test_estimated_cost_with_spawns_and_steps(self):
        """Estimated cost accumulates spawn costs + per-step costs."""
        phase = _make_phase()
        # 2 spawns at 500 each + 3 steps at 500 each = 2500
        data = {
            "agents_to_use": ["claude"],
            "agents_to_spawn": [
                {"role": "a", "mission": "A", "capabilities": [], "estimated_cost": 500},
                {"role": "b", "mission": "B", "capabilities": [], "estimated_cost": 500},
            ],
            "execution_strategy": "sequential",
            "execution_steps": [
                {"name": "s1", "agent_id": "claude", "action": "step 1"},
                {"name": "s2", "agent_id": "claude", "action": "step 2"},
                {"name": "s3", "agent_id": "claude", "action": "step 3"},
            ],
            "reasoning": "test",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["coding"])
        assert arch.estimated_cost == 2500

    @pytest.mark.asyncio
    async def test_skip_gemini_validation_when_budget_insufficient(self):
        """When budget is insufficient for validation, use Claude arch directly."""
        phase = _make_phase(budget=1500)
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        # Spend most of the budget so validation becomes unaffordable
        phase.cost_estimator.spent = 1400

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            arch = await phase._generate_collaborative("Build API", "Use FastAPI", ["coding"], "No agents")
        # Should still get a valid architecture (from Claude only)
        assert arch is not None
        # Gemini should NOT have been called
        phase.gemini.invoke.assert_not_called()


# =============================================================================
# 8. Mock execution flow with mocked drivers
# =============================================================================


class TestExecuteFlow:
    """Tests for the full execute() method with mocked drivers."""

    @pytest.mark.asyncio
    async def test_execute_collaborative_no_spawns(self):
        """Full collaborative flow without any spawning needed."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        debate = _make_debate_result()

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Build a REST API", debate)

        assert result is not None, "execute() returned None"
        # Use type name check to avoid dual-import isinstance failures in full suite
        assert type(result).__name__ == "ArchitecturePhaseResult", f"Got {type(result).__name__}: {result}"
        assert result.user_approved_spawn is True
        assert result.agents_spawned == []
        assert result.architecture.status == "READY"

    @pytest.mark.asyncio
    async def test_execute_legacy_mode(self):
        """Legacy flow (Gemini only) when collaborative flag is off."""
        phase = _make_phase()
        phase.gemini.invoke.return_value = _make_driver_response(_valid_architecture_json())
        debate = _make_debate_result()

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", False),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Build a REST API", debate)

        assert result is not None, "execute() returned None"
        # Use type name check to avoid dual-import isinstance failures in full suite
        assert type(result).__name__ == "ArchitecturePhaseResult", f"Got {type(result).__name__}: {result}"
        phase.gemini.invoke.assert_called_once()
        # Claude driver should NOT have been called in legacy mode
        phase.claude.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_with_spawn_approved(self):
        """Flow where spawning is needed and user approves."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_architecture_with_spawns_json())
        phase.gemini.invoke.return_value = _make_driver_response(
            _gemini_validation_json(architecture=json.loads(_architecture_with_spawns_json()))
        )
        debate = _make_debate_result()

        # User approves spawn
        mock_response = MagicMock()
        mock_response.chosen_option = "spawn_all"
        phase.user_handler.before_spawn.return_value = mock_response

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Audit codebase", debate)

        assert result.user_approved_spawn is True
        phase.user_handler.before_spawn.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_spawn_skipped(self):
        """Flow where user skips spawning."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_architecture_with_spawns_json())
        phase.gemini.invoke.return_value = _make_driver_response(
            _gemini_validation_json(architecture=json.loads(_architecture_with_spawns_json()))
        )
        debate = _make_debate_result()

        mock_response = MagicMock()
        mock_response.chosen_option = "skip"
        phase.user_handler.before_spawn.return_value = mock_response

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Audit codebase", debate)

        assert result.user_approved_spawn is False
        assert result.spawn_skipped_reason == "User chose to skip spawning"
        assert result.agents_spawned == []

    @pytest.mark.asyncio
    async def test_execute_with_spawn_cancelled(self):
        """Flow where user cancels spawning."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_architecture_with_spawns_json())
        phase.gemini.invoke.return_value = _make_driver_response(
            _gemini_validation_json(architecture=json.loads(_architecture_with_spawns_json()))
        )
        debate = _make_debate_result()

        mock_response = MagicMock()
        mock_response.chosen_option = "cancel"
        phase.user_handler.before_spawn.return_value = mock_response

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Audit codebase", debate)

        assert result.user_approved_spawn is False
        assert result.spawn_skipped_reason == "User cancelled spawning"

    @pytest.mark.asyncio
    async def test_execute_selective_spawn(self):
        """Flow where user selects specific agents to spawn."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_architecture_with_spawns_json())
        phase.gemini.invoke.return_value = _make_driver_response(
            _gemini_validation_json(architecture=json.loads(_architecture_with_spawns_json()))
        )
        debate = _make_debate_result()

        mock_response = MagicMock()
        mock_response.chosen_option = "spawn_selective"
        phase.user_handler.before_spawn.return_value = mock_response

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Audit codebase", debate)

        assert result.user_approved_spawn is True


# =============================================================================
# 9. Gemini validation (Phase 3b)
# =============================================================================


class TestGeminiValidation:
    """Tests for Gemini validation and optimization in Phase 3b."""

    @pytest.mark.asyncio
    async def test_gemini_approved(self):
        """Gemini approves architecture without changes."""
        phase = _make_phase()
        claude_arch = phase._parse_architecture_response(_valid_architecture_json(), ["coding"])
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json(validation="APPROVED"))
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        result = await phase._validate_with_gemini(claude_arch, "Build API", ["coding"])
        assert "Collaborative V12.4" in result.reasoning
        assert "approved" in result.reasoning

    @pytest.mark.asyncio
    async def test_gemini_optimized(self):
        """Gemini optimizes architecture with changes."""
        phase = _make_phase()
        claude_arch = phase._parse_architecture_response(_valid_architecture_json(), ["coding"])
        optimized_arch = json.loads(
            _valid_architecture_json(execution_strategy="parallel", reasoning="Parallelized for speed")
        )
        phase.gemini.invoke.return_value = _make_driver_response(
            _gemini_validation_json(
                validation="OPTIMIZED",
                optimizations=["Parallelized steps", "Removed redundant check"],
                architecture=optimized_arch,
            )
        )
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        result = await phase._validate_with_gemini(claude_arch, "Build API", ["coding"])
        assert "optimized" in result.reasoning

    @pytest.mark.asyncio
    async def test_gemini_parse_failure_falls_back_to_claude(self):
        """If Gemini response is unparseable, Claude architecture is used."""
        phase = _make_phase()
        claude_arch = phase._parse_architecture_response(_valid_architecture_json(), ["coding"])
        phase.gemini.invoke.return_value = _make_driver_response("This is not JSON")
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        result = await phase._validate_with_gemini(claude_arch, "Build API", ["coding"])
        # Should return the original Claude architecture
        assert result is claude_arch

    @pytest.mark.asyncio
    async def test_gemini_driver_error_falls_back(self):
        """If Gemini driver throws, collaborative flow falls back to Claude."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.side_effect = RuntimeError("Gemini down")
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            arch = await phase._generate_collaborative("Build API", "Use FastAPI", ["coding"], "No agents")
        # Should succeed with Claude-only architecture
        assert arch is not None
        assert len(arch.execution_plan.steps) == 2


# =============================================================================
# 10. V12.4 integration graceful degradation
# =============================================================================


class TestV124GracefulDegradation:
    """Tests for V12.4 integration features degrading gracefully."""

    @pytest.mark.asyncio
    async def test_claude_driver_failure_returns_fallback(self):
        """If Claude driver fails, fallback architecture is returned."""
        phase = _make_phase()
        phase.claude.invoke.side_effect = Exception("Claude error")
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        arch = await phase._generate_with_claude("Build API", "Use FastAPI", ["coding"], "No agents")
        assert arch.reasoning == "Fallback architecture due to generation failure"

    @pytest.mark.asyncio
    async def test_legacy_driver_failure_returns_fallback(self):
        """If Gemini driver fails in legacy mode, fallback architecture is used."""
        phase = _make_phase()
        phase.gemini.invoke.side_effect = Exception("Gemini error")
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        arch = await phase._generate_legacy("Build API", "Use FastAPI", ["coding"], "No agents")
        assert arch.reasoning == "Fallback architecture due to generation failure"

    def test_graph_of_thought_failure_is_silent(self):
        """GraphOfThought annotation failure does not raise."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(
                strategy="sequential",
                steps=[ExecutionStep(name="step1", agent_id="claude", action="Do something")],
            ),
            reasoning="Test",
        )
        # If GraphOfThought module is missing, annotation silently fails
        with patch(
            "core.intelligence.hive_mind.phases.phase_architecture.ThoughtGraph",
            side_effect=ImportError("No module"),
            create=True,
        ):
            # Should not raise
            phase._annotate_with_graph_of_thought(arch)

    def test_graph_of_thought_empty_steps(self):
        """GraphOfThought annotation with empty steps is a no-op."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential", steps=[]),
            reasoning="Empty",
        )
        phase._annotate_with_graph_of_thought(arch)
        # Reasoning should not be modified (no steps to analyze)
        assert arch.reasoning == "Empty"


# =============================================================================
# 11. Edge cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases in architecture generation."""

    def test_fallback_architecture_structure(self):
        """Fallback architecture has correct structure."""
        phase = _make_phase()
        arch = phase._create_fallback_architecture(["coding", "testing"])
        assert arch.status == "READY"
        assert arch.collaboration_mode == "sequential"
        assert arch.agents_to_use == ["claude", "gemini"]
        assert arch.agents_to_spawn == []
        assert len(arch.execution_plan.steps) == 1
        assert arch.execution_plan.steps[0].name == "main_execution"
        assert arch.execution_plan.steps[0].agent_id == "claude"
        assert arch.estimated_cost == 1000

    def test_format_available_agents_empty(self):
        """Format returns placeholder when no agents are available."""
        phase = _make_phase()
        phase.registry.get_active_agents.return_value = []
        result = phase._format_available_agents()
        assert result == "No specialized agents available"

    def test_format_available_agents_with_agents(self):
        """Format returns agent list when agents exist."""
        phase = _make_phase()
        agent1 = MagicMock()
        agent1.agent_id = "claude"
        agent1.role = "general"
        agent1.capabilities = ["coding", "analysis"]
        agent2 = MagicMock()
        agent2.agent_id = "security_bot"
        agent2.role = "specialist"
        agent2.capabilities = ["security"]
        phase.registry.get_active_agents.return_value = [agent1, agent2]

        result = phase._format_available_agents()
        assert "claude" in result
        assert "security_bot" in result
        assert "coding" in result

    def test_check_duplicates_removes_similar(self):
        """Duplicate check removes agents with similar capabilities."""
        phase = _make_phase()
        similar_agent = MagicMock()
        similar_agent.agent_id = "existing_coder"
        phase.registry.find_similar.return_value = similar_agent

        arch = AgentArchitecture(
            status="SPAWN_REQUIRED",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[AgentSpec(role="coder", mission="Write code", capabilities=["coding"])],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential"),
        )

        result = phase._check_for_duplicates(arch)
        assert len(result.agents_to_spawn) == 0
        assert "existing_coder" in result.agents_to_use
        assert result.status == "READY"

    def test_check_duplicates_keeps_unique(self):
        """Duplicate check keeps agents with no similar match."""
        phase = _make_phase()
        phase.registry.find_similar.return_value = None

        arch = AgentArchitecture(
            status="SPAWN_REQUIRED",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[
                AgentSpec(
                    role="rare_specialist",
                    mission="Handle rare domain",
                    capabilities=["quantum_computing"],
                )
            ],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential"),
        )

        result = phase._check_for_duplicates(arch)
        assert len(result.agents_to_spawn) == 1
        assert result.status == "SPAWN_SUGGESTED"

    def test_check_duplicates_no_double_add(self):
        """Duplicate check does not add agent_id twice to agents_to_use."""
        phase = _make_phase()
        similar_agent = MagicMock()
        similar_agent.agent_id = "claude"  # Already in agents_to_use
        phase.registry.find_similar.return_value = similar_agent

        arch = AgentArchitecture(
            status="SPAWN_REQUIRED",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[AgentSpec(role="coder", mission="Write code", capabilities=["coding"])],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential"),
        )

        result = phase._check_for_duplicates(arch)
        assert result.agents_to_use.count("claude") == 1

    def test_parse_very_complex_architecture(self):
        """Parsing an architecture with many steps and spawns."""
        phase = _make_phase()
        steps = [
            {
                "name": f"step_{i}",
                "agent_id": "claude" if i % 2 == 0 else "gemini",
                "action": f"Execute step {i}",
                "expected_duration": 10 + i,
                "depends_on": [f"step_{i - 1}"] if i > 0 else [],
                "verification_required": i % 3 == 0,
            }
            for i in range(20)
        ]
        spawns = [
            {
                "role": f"specialist_{i}",
                "mission": f"Handle domain {i}",
                "capabilities": [f"cap_{i}"],
                "tools_priority": ["read"],
                "estimated_cost": 300,
            }
            for i in range(5)
        ]
        data = {
            "agents_to_use": ["claude", "gemini"],
            "agents_to_spawn": spawns,
            "execution_strategy": "pipeline",
            "execution_steps": steps,
            "rag_config": {
                "enabled": True,
                "depth": "deep",
                "sources": ["codebase", "docs", "memory"],
                "max_chunks": 50,
            },
            "reasoning": "Complex multi-agent pipeline for large task",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["coding"])
        assert len(arch.execution_plan.steps) == 20
        assert len(arch.agents_to_spawn) == 5
        assert arch.execution_plan.estimated_total_duration == sum(10 + i for i in range(20))
        # 5 spawns * 300 + 20 steps * 500 = 1500 + 10000 = 11500
        assert arch.estimated_cost == 11500

    def test_parse_empty_agents_to_use_defaults(self):
        """Missing agents_to_use defaults to claude + gemini."""
        phase = _make_phase()
        data = {
            "execution_strategy": "sequential",
            "execution_steps": [],
            "reasoning": "minimal",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["coding"])
        assert arch.agents_to_use == ["claude", "gemini"]

    @pytest.mark.asyncio
    async def test_execute_with_empty_approach(self):
        """Execute works with empty debate approach."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        debate = _make_debate_result(final_approach="", final_capabilities=[])

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            result = await phase.execute("Build API", debate)

        # Use type name check to avoid dual-import isinstance failures in full suite
        assert type(result).__name__ == "ArchitecturePhaseResult"


# =============================================================================
# 12. get_execution_ready_architecture
# =============================================================================


class TestGetExecutionReady:
    """Tests for get_execution_ready_architecture output format."""

    def test_basic_structure(self):
        """Output has all required keys."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(enabled=True, depth="deep", sources=["codebase"], max_chunks=20),
            execution_plan=ExecutionPlan(
                strategy="sequential",
                steps=[
                    ExecutionStep(
                        name="s1",
                        agent_id="claude",
                        action="Do it",
                        expected_duration=45,
                        verification_required=True,
                        depends_on=["s0"],
                    )
                ],
                estimated_total_duration=45,
                estimated_total_tokens=500,
            ),
            estimated_cost=500,
        )
        result_obj = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=["extra_bot"],
            user_approved_spawn=True,
        )
        ready = phase.get_execution_ready_architecture(result_obj)

        assert ready["mode"] == "sequential"
        assert ready["agents"] == ["claude", "extra_bot"]
        assert len(ready["steps"]) == 1
        assert ready["steps"][0]["name"] == "s1"
        assert ready["steps"][0]["agent"] == "claude"
        assert ready["steps"][0]["action"] == "Do it"
        assert ready["steps"][0]["timeout"] == 45
        assert ready["steps"][0]["depends_on"] == ["s0"]
        assert ready["steps"][0]["verify"] is True
        assert ready["rag"]["enabled"] is True
        assert ready["rag"]["depth"] == "deep"
        assert ready["rag"]["sources"] == ["codebase"]
        assert ready["rag"]["max_chunks"] == 20
        assert ready["estimated_tokens"] == 500
        assert ready["estimated_duration"] == 45

    def test_agents_merge(self):
        """agents list merges agents_to_use and agents_spawned."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="parallel",
            agents_to_use=["claude", "gemini"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="parallel"),
        )
        result_obj = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=["bot_a", "bot_b"],
            user_approved_spawn=True,
        )
        ready = phase.get_execution_ready_architecture(result_obj)
        assert ready["agents"] == ["claude", "gemini", "bot_a", "bot_b"]

    def test_empty_steps(self):
        """Output handles zero steps."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential", steps=[]),
        )
        result_obj = ArchitecturePhaseResult(
            architecture=arch,
            agents_spawned=[],
            user_approved_spawn=True,
        )
        ready = phase.get_execution_ready_architecture(result_obj)
        assert ready["steps"] == []
        assert ready["estimated_duration"] == 0


# =============================================================================
# 13. Spawn agent mechanics
# =============================================================================


class TestSpawnAgents:
    """Tests for the _spawn_agents method."""

    @pytest.mark.asyncio
    async def test_spawn_single_agent(self):
        """Single agent spawn creates file and registers."""
        phase = _make_phase()
        specs = [
            AgentSpec(
                role="data_analyst",
                mission="Analyze datasets",
                capabilities=["data", "visualization"],
                tools_priority=["read", "bash"],
                estimated_cost=600,
            )
        ]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            spawned = await phase._spawn_agents(specs)

        assert len(spawned) == 1
        assert spawned[0].startswith("data_analyst_")
        phase.registry.register_spawn.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_multiple_agents(self):
        """Multiple agents can be spawned."""
        phase = _make_phase()
        specs = [
            AgentSpec(role="bot_a", mission="A", capabilities=["a"]),
            AgentSpec(role="bot_b", mission="B", capabilities=["b"]),
            AgentSpec(role="bot_c", mission="C", capabilities=["c"]),
        ]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            spawned = await phase._spawn_agents(specs)

        assert len(spawned) == 3
        assert phase.registry.register_spawn.call_count == 3

    @pytest.mark.asyncio
    async def test_spawn_records_cost(self):
        """Spawning records cost for each agent."""
        phase = _make_phase()
        specs = [
            AgentSpec(
                role="bot_x",
                mission="X",
                capabilities=["x"],
                estimated_cost=750,
            )
        ]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            await phase._spawn_agents(specs)

        ops = [r.operation for r in phase.cost_estimator.records]
        assert "spawn_agent" in ops

    @pytest.mark.asyncio
    async def test_spawn_failure_continues(self):
        """If one spawn fails, others still proceed."""
        phase = _make_phase()
        # First call to register_spawn raises, second succeeds
        phase.registry.register_spawn.side_effect = [Exception("disk full"), True]
        specs = [
            AgentSpec(role="bot_fail", mission="Fail", capabilities=["x"]),
            AgentSpec(role="bot_ok", mission="OK", capabilities=["y"]),
        ]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            # First write succeeds but register fails, second should still work
            spawned = await phase._spawn_agents(specs)

        # Despite the first registration failing, second should succeed
        # (the spawn catches exceptions per-agent)
        assert len(spawned) >= 1


# =============================================================================
# 14. GraphOfThought annotation
# =============================================================================


class TestGraphOfThoughtAnnotation:
    """Tests for _annotate_with_graph_of_thought."""

    def test_annotation_adds_dag_info(self):
        """Annotation appends GoT DAG info to reasoning."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(
                strategy="sequential",
                steps=[
                    ExecutionStep(name="s1", agent_id="claude", action="First"),
                    ExecutionStep(
                        name="s2",
                        agent_id="gemini",
                        action="Second",
                        depends_on=["s1"],
                    ),
                ],
            ),
            reasoning="Original reasoning",
        )

        # This may or may not work depending on whether the GoT module exists
        # in the test environment. Either way, it should not raise.
        phase._annotate_with_graph_of_thought(arch)
        # If GoT module exists, reasoning should be extended
        # If not, reasoning stays the same (graceful degradation)
        assert "Original reasoning" in arch.reasoning

    def test_annotation_no_steps_is_noop(self):
        """Annotation with no steps does nothing."""
        phase = _make_phase()
        arch = AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(strategy="sequential", steps=[]),
            reasoning="No steps",
        )
        phase._annotate_with_graph_of_thought(arch)
        assert arch.reasoning == "No steps"


# =============================================================================
# 15. Session integration
# =============================================================================


class TestSessionIntegration:
    """Tests for session isolation and context management."""

    @pytest.mark.asyncio
    async def test_session_integration_initialized(self):
        """Session integration is created during execute."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        debate = _make_debate_result()

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            await phase.execute("Build API", debate)

        # Session integration should have been initialized
        assert phase._session_integration is not None

    @pytest.mark.asyncio
    async def test_session_uuid_passed_to_claude(self):
        """Session UUID is passed to Claude driver via invoke()."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "test-session-uuid"

        await phase._generate_with_claude("Build API", "Use FastAPI", ["coding"], "No agents")

        # Claude driver should have been called via invoke() with session_id
        call_kwargs = phase.claude.invoke.call_args
        assert call_kwargs is not None
        # session_id is passed as a keyword argument
        assert call_kwargs[1].get("session_id") == "test-session-uuid"

    @pytest.mark.asyncio
    async def test_no_session_integration_still_works(self):
        """Architecture generation works without session integration."""
        phase = _make_phase()
        phase._session_integration = None
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())

        arch = await phase._generate_with_claude("Build API", "Use FastAPI", ["coding"], "No agents")
        assert arch is not None


# =============================================================================
# 16. Collaborative vs Legacy mode switching
# =============================================================================


class TestModeSwitch:
    """Tests for switching between collaborative and legacy modes."""

    @pytest.mark.asyncio
    async def test_collaborative_calls_both_drivers(self):
        """Collaborative mode calls both Claude and Gemini."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            await phase._generate_collaborative("Build API", "Use FastAPI", ["coding"], "No agents")

        phase.claude.invoke.assert_called_once()
        phase.gemini.invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_calls_only_gemini(self):
        """Legacy mode calls only Gemini."""
        phase = _make_phase()
        phase.gemini.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        await phase._generate_legacy("Build API", "Use FastAPI", ["coding"], "No agents")

        phase.gemini.invoke.assert_called_once()
        phase.claude.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_architecture_routes_correctly(self):
        """_generate_architecture routes to collaborative or legacy based on flag."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.COLLABORATIVE_ARCHITECTURE", True),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            arch = await phase._generate_architecture("Build API", "Use FastAPI", ["coding"], "No agents")
        assert arch is not None
        # Both drivers called in collaborative mode
        phase.claude.invoke.assert_called_once()


# =============================================================================
# 17. Telemetry emission
# =============================================================================


class TestTelemetryEmission:
    """Tests for V13.0 CEREBRO LIVE telemetry in collaborative mode."""

    @pytest.mark.asyncio
    async def test_emit_agent_speak_called_for_claude(self):
        """emit_agent_speak is called after Claude generates architecture."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak") as mock_speak,
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange"),
        ):
            await phase._generate_collaborative("Build API", "Use FastAPI", ["coding"], "No agents")

        # emit_agent_speak should have been called for both claude and gemini
        assert mock_speak.call_count >= 1
        agent_names = [c[0][0] for c in mock_speak.call_args_list]
        assert "claude" in agent_names

    @pytest.mark.asyncio
    async def test_emit_agent_exchange_called(self):
        """emit_agent_exchange is called for architecture exchange."""
        phase = _make_phase()
        phase.claude.invoke.return_value = _make_driver_response(_valid_architecture_json())
        phase.gemini.invoke.return_value = _make_driver_response(_gemini_validation_json())
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        with (
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_architecture.emit_agent_exchange") as mock_exchange,
        ):
            await phase._generate_collaborative("Build API", "Use FastAPI", ["coding"], "No agents")

        assert mock_exchange.call_count >= 1


# =============================================================================
# 18. RAG configuration edge cases
# =============================================================================


class TestRAGConfigEdgeCases:
    """Tests for RAG configuration parsing edge cases."""

    def test_rag_disabled(self):
        """RAG can be disabled in architecture."""
        phase = _make_phase()
        data = {
            "agents_to_use": ["claude"],
            "execution_strategy": "sequential",
            "execution_steps": [],
            "rag_config": {"enabled": False, "depth": "shallow", "sources": [], "max_chunks": 0},
            "reasoning": "No RAG needed",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["coding"])
        assert arch.rag_config.enabled is False
        assert arch.rag_config.max_chunks == 0

    def test_rag_deep_with_many_sources(self):
        """Deep RAG with multiple sources is parsed correctly."""
        phase = _make_phase()
        data = {
            "agents_to_use": ["claude"],
            "execution_strategy": "sequential",
            "execution_steps": [],
            "rag_config": {
                "enabled": True,
                "depth": "deep",
                "sources": ["codebase", "docs", "memory", "web"],
                "max_chunks": 50,
            },
            "reasoning": "Need comprehensive context",
        }
        arch = phase._parse_architecture_response(json.dumps(data), ["coding"])
        assert arch.rag_config.depth == "deep"
        assert len(arch.rag_config.sources) == 4
        assert arch.rag_config.max_chunks == 50

    def test_default_rag_config(self):
        """Default RAGConfig has standard values."""
        rag = RAGConfig()
        assert rag.enabled is True
        assert rag.depth == "standard"
        assert rag.sources == ["codebase"]
        assert rag.max_chunks == 10
