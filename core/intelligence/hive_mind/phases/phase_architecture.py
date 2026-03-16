"""
NEXUS V9.2 - Phase 3: Architecture Generation

Generates the agent architecture for task execution:
- Which existing agents to use
- Which new agents to spawn
- Execution plan (sequential/parallel/pipeline)
- RAG configuration

V9.2 Enhancement: Session Isolation + Scoped Context
- Inherits context from Phase 2 via TASK_PLUS_RESULTS scope
- Spawned agents get isolated sessions with TASK_ONLY context
- Model-change detection for architecture decisions

V12.4 Enhancement: Collaborative Architecture (Claude + Gemini)
- Phase 3a: Claude (Opus) generates initial architecture (planning strength)
- Phase 3b: Gemini validates and optimizes (speed + fresh context)
- Feature flag: COLLABORATIVE_ARCHITECTURE for rollback

Flow:
1. Check Agent Registry for existing agents
2. Generate architecture based on debate outcome (session: uuid-arch)
   2a. Claude generates initial architecture
   2b. Gemini validates/optimizes
3. User Breakpoint: BEFORE_SPAWN (if spawning agents)
4. Spawn new agents if approved (each with isolated session)
5. Return execution-ready architecture

Key Innovation:
- Auto-detects when specialized agents are needed
- Prevents duplicate spawning via Registry
- User can intervene before spawning
- V9.2: Session isolation for spawned agents
- V12.4: Dual-agent architecture for better planning
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak

from ..agent_registry import AgentRegistry
from ..context_manager import HiveMindContextManager
from ..cost_estimator import CostEstimator
from ..prompts import ARCHITECTURE_SYSTEM_PROMPT  # V12.4.1: Static prompt for caching
from ..session_integration import HiveMindSessionIntegration, generate_hivemind_task_id
from ..types import (
    AgentArchitecture,
    AgentSpec,
    DebateResult,
    ExecutionPlan,
    ExecutionStep,
    RAGConfig,
)
from ..user_interaction import UserInteractionHandler

# V12.4: Feature flag for collaborative architecture
COLLABORATIVE_ARCHITECTURE = os.environ.get("NEXUS_COLLABORATIVE_ARCHITECTURE", "true").lower() == "true"

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm.session_manager import SwarmSessionManager


logger = logging.getLogger(__name__)


# Architecture generation prompt (legacy - used when collaborative disabled)
ARCHITECTURE_PROMPT = """You are designing an agent architecture for NEXUS Hive Mind.

TASK: {task}

AGREED APPROACH: {approach}

REQUIRED CAPABILITIES: {capabilities}

AVAILABLE AGENTS:
{available_agents}

Design the optimal architecture. Consider:
1. Can existing agents handle this? (prefer reuse)
2. What specialized agents are needed?
3. How should agents collaborate (parallel, sequential, pipeline)?
4. What RAG context is needed?

Respond in JSON format:
{{
    "agents_to_use": ["agent_id1", "agent_id2", ...],
    "agents_to_spawn": [
        {{
            "role": "specialist_name",
            "mission": "What this agent does",
            "capabilities": ["cap1", "cap2"],
            "tools_priority": ["tool1", "tool2"],
            "estimated_cost": 500
        }}
    ],
    "execution_strategy": "parallel" or "sequential" or "pipeline",
    "execution_steps": [
        {{
            "name": "step_name",
            "agent_id": "agent_to_use",
            "action": "What to do",
            "expected_duration": 30,
            "depends_on": ["previous_step_name"],
            "verification_required": true
        }}
    ],
    "rag_config": {{
        "enabled": true,
        "depth": "shallow" or "standard" or "deep",
        "sources": ["codebase", "docs", "memory"],
        "max_chunks": 10
    }},
    "reasoning": "Why this architecture"
}}
"""

# V12.4: Claude architecture generation prompt (Phase 3a)
CLAUDE_ARCHITECTURE_PROMPT = """You are the ARCHITECT for NEXUS Hive Mind. Your role is to design
the optimal execution architecture for a complex task.

## TASK
{task}

## AGREED APPROACH (from debate)
{approach}

## REQUIRED CAPABILITIES
{capabilities}

## AVAILABLE AGENTS
{available_agents}

## YOUR MISSION

Design a precise, efficient architecture. You excel at:
- Breaking complex problems into clear execution steps
- Identifying dependencies between steps
- Assigning the right agent to each step
- Anticipating failure modes

## GUIDELINES

1. **Prefer existing agents** - Only spawn new agents if truly necessary
2. **Clear step boundaries** - Each step should have one clear objective
3. **Minimize dependencies** - Prefer parallel execution where possible
4. **Assign agents thoughtfully**:
   - Claude: Complex reasoning, code generation, analysis
   - Gemini: Research, summarization, creative tasks
5. **Be specific** - Actions should be concrete, not vague

Respond in JSON format:
{{
    "agents_to_use": ["agent_id1", "agent_id2"],
    "agents_to_spawn": [
        {{
            "role": "specialist_name",
            "mission": "What this agent does",
            "capabilities": ["cap1", "cap2"],
            "tools_priority": ["tool1", "tool2"],
            "estimated_cost": 500
        }}
    ],
    "execution_strategy": "parallel" | "sequential" | "pipeline",
    "execution_steps": [
        {{
            "name": "step_name",
            "agent_id": "claude" | "gemini" | "spawned_agent_id",
            "action": "Specific action to perform",
            "expected_duration": 30,
            "depends_on": ["previous_step_name"],
            "verification_required": true
        }}
    ],
    "rag_config": {{
        "enabled": true,
        "depth": "shallow" | "standard" | "deep",
        "sources": ["codebase", "docs", "memory"],
        "max_chunks": 10
    }},
    "reasoning": "Why this architecture is optimal"
}}
"""

# V12.4: Gemini validation prompt (Phase 3b)
GEMINI_VALIDATION_PROMPT = """You are validating and optimizing an architecture proposed by Claude.

## ORIGINAL TASK
{task}

## PROPOSED ARCHITECTURE
```json
{architecture_json}
```

## YOUR MISSION

Review this architecture with fresh eyes. Check for:
1. **Feasibility** - Can each step actually be executed?
2. **Efficiency** - Are there unnecessary steps? Can steps be parallelized?
3. **Agent assignment** - Is the right agent assigned to each step?
4. **Dependencies** - Are dependencies correctly identified?
5. **Completeness** - Does this cover the full task?

## OUTPUT

If the architecture is GOOD, respond:
```json
{{
    "validation": "APPROVED",
    "optimizations": ["list of minor improvements applied"],
    "architecture": {{ ... the architecture, possibly with minor tweaks ... }}
}}
```

If the architecture needs CHANGES, respond:
```json
{{
    "validation": "OPTIMIZED",
    "issues_found": ["list of issues"],
    "optimizations": ["list of changes made"],
    "architecture": {{ ... the improved architecture ... }}
}}
```

Be constructive - improve, don't reject.
"""


@dataclass
class ArchitecturePhaseResult:
    """Result of Phase 3."""

    architecture: AgentArchitecture
    agents_spawned: list[str]
    user_approved_spawn: bool
    spawn_skipped_reason: str | None = None


class ArchitectureGenerationPhase:
    """
    Phase 3: Architecture Generation

    Generates agent topology and execution plan.

    V9.2: Integrated session isolation for architecture generation.
    """

    def __init__(
        self,
        gemini_driver: "BaseAsyncDriver",
        claude_driver: "BaseAsyncDriver",
        cost_estimator: CostEstimator,
        context_manager: HiveMindContextManager,
        agent_registry: AgentRegistry,
        user_handler: UserInteractionHandler,
        workspace_path: Path,
        task_id: str | None = None,
        session_manager: Optional["SwarmSessionManager"] = None,
    ):
        """
        Initialize Phase 3.

        Args:
            gemini_driver: Gemini driver
            claude_driver: Claude driver
            cost_estimator: Cost estimator
            context_manager: Context manager
            agent_registry: Agent registry for spawn tracking
            user_handler: User interaction handler for breakpoints
            workspace_path: Workspace path for agent files
            task_id: V9.2 - Unique task identifier for session isolation
            session_manager: V9.2 - Optional session manager for persistence
        """
        self.gemini = gemini_driver
        self.claude = claude_driver
        self.cost_estimator = cost_estimator
        self.context_manager = context_manager
        self.registry = agent_registry
        self.user_handler = user_handler
        self.workspace_path = workspace_path

        # V9.2: Session isolation
        self._task_id = task_id or generate_hivemind_task_id("architecture")
        self._session_manager = session_manager
        self._session_integration: HiveMindSessionIntegration | None = None

    async def execute(self, task: str, debate_result: DebateResult) -> ArchitecturePhaseResult:
        """
        Execute Phase 3: Architecture Generation.

        V9.2: Initializes session integration with context from Phase 2.

        Args:
            task: Original task
            debate_result: Result from Phase 2

        Returns:
            ArchitecturePhaseResult with execution-ready architecture
        """
        logger.info("Phase 3: Starting Architecture Generation")

        # V9.2: Initialize session integration for this phase
        self._session_integration = HiveMindSessionIntegration(
            task_id=self._task_id,
            phase_name="architecture",
            context_manager=self.context_manager,
            session_manager=self._session_manager,
            complexity="MODERATE",
        )
        self._session_integration.set_previous_phase("debate")

        # Check budget
        if not self.cost_estimator.can_afford_multiple({"generate_architecture": 1, "check_registry": 1}):
            logger.error("Cannot afford Phase 3 operations")
            raise RuntimeError("Budget exceeded for Phase 3")

        # Get available agents from registry
        available_agents = self._format_available_agents()

        # V12.4: CascadedRouter pre-routing hints (arxiv:2502.11133)
        try:
            from core.execution_pkg.routing.cascaded_router import get_cascaded_router

            _cr = get_cascaded_router()
            _complexity = getattr(debate_result, "consensus_confidence", 0.5)
            _domains = debate_result.final_capabilities[:3] if debate_result.final_capabilities else []
            _routing = _cr.route(task[:200], complexity=_complexity, domains=_domains)
            logger.info(
                f"Phase 3: CascadedRouter suggests mode={_routing.collaboration_mode}, "
                f"cost_reduction={_routing.estimated_cost_reduction:.0%}"
            )
        except Exception:
            pass

        # Generate architecture
        architecture = await self._generate_architecture(
            task=task,
            approach=debate_result.final_approach,
            capabilities=debate_result.final_capabilities,
            available_agents=available_agents,
        )

        # Check if spawning is needed
        if architecture.agents_to_spawn:
            # Check registry for similar agents
            architecture = self._check_for_duplicates(architecture)

            # If still spawning needed, request user approval
            if architecture.agents_to_spawn:
                user_response = self.user_handler.before_spawn(
                    agents_to_spawn=[
                        {"role": spec.role, "mission": spec.mission, "capabilities": spec.capabilities}
                        for spec in architecture.agents_to_spawn
                    ],
                    estimated_cost=architecture.estimated_cost,
                )

                if user_response.chosen_option == "spawn_all":
                    # Spawn all agents
                    spawned = await self._spawn_agents(architecture.agents_to_spawn)
                    self._annotate_with_graph_of_thought(architecture)
                    return ArchitecturePhaseResult(
                        architecture=architecture, agents_spawned=spawned, user_approved_spawn=True
                    )

                elif user_response.chosen_option == "spawn_selective":
                    # TODO: Implement selective spawning UI
                    spawned = await self._spawn_agents(architecture.agents_to_spawn)
                    return ArchitecturePhaseResult(
                        architecture=architecture, agents_spawned=spawned, user_approved_spawn=True
                    )

                elif user_response.chosen_option == "skip":
                    # Skip spawning, use existing agents
                    architecture.agents_to_spawn = []
                    architecture.status = "READY"
                    return ArchitecturePhaseResult(
                        architecture=architecture,
                        agents_spawned=[],
                        user_approved_spawn=False,
                        spawn_skipped_reason="User chose to skip spawning",
                    )

                else:
                    # Cancel - but continue with existing agents
                    architecture.agents_to_spawn = []
                    return ArchitecturePhaseResult(
                        architecture=architecture,
                        agents_spawned=[],
                        user_approved_spawn=False,
                        spawn_skipped_reason="User cancelled spawning",
                    )

        # No spawning needed
        logger.info("No spawning required - using existing agents")

        # V12.4: Analyze execution plan with GraphOfThought for DAG insights
        self._annotate_with_graph_of_thought(architecture)

        return ArchitecturePhaseResult(
            architecture=architecture,
            agents_spawned=[],
            user_approved_spawn=True,  # N/A but true for flow
        )

    def _format_available_agents(self) -> str:
        """Format available agents for prompt."""
        agents = self.registry.get_active_agents()
        lines = []
        for agent in agents:
            caps = ", ".join(agent.capabilities)
            lines.append(f"- {agent.agent_id} ({agent.role}): {caps}")
        return "\n".join(lines) if lines else "No specialized agents available"

    async def _generate_architecture(
        self, task: str, approach: str, capabilities: list[str], available_agents: str
    ) -> AgentArchitecture:
        """
        Generate architecture using collaborative or legacy approach.

        V12.4: Collaborative mode (default):
        - Phase 3a: Claude generates initial architecture
        - Phase 3b: Gemini validates and optimizes

        Legacy mode (NEXUS_COLLABORATIVE_ARCHITECTURE=false):
        - Gemini generates architecture alone
        """
        if COLLABORATIVE_ARCHITECTURE:
            logger.info("Phase 3: Using COLLABORATIVE architecture (Claude -> Gemini)")
            return await self._generate_collaborative(task, approach, capabilities, available_agents)
        else:
            logger.info("Phase 3: Using LEGACY architecture (Gemini only)")
            return await self._generate_legacy(task, approach, capabilities, available_agents)

    async def _generate_collaborative(
        self, task: str, approach: str, capabilities: list[str], available_agents: str
    ) -> AgentArchitecture:
        """
        V12.4: Collaborative architecture generation.

        Phase 3a: Claude generates initial architecture (planning strength)
        Phase 3b: Gemini validates and optimizes (speed + fresh perspective)
        """
        # Phase 3a: Claude generates architecture
        logger.info("  Phase 3a: Claude generating architecture...")
        claude_arch = await self._generate_with_claude(task, approach, capabilities, available_agents)

        # V13.0 CEREBRO LIVE: Emit Claude's architecture proposal
        emit_agent_speak(
            "claude",
            f"Architecture: {claude_arch.collaboration_mode} mode, {len(claude_arch.execution_plan.steps)} steps",
            action_type="ARCHITECTURE",
        )
        emit_agent_exchange(
            "claude",
            "gemini",
            f"Proposed: {claude_arch.collaboration_mode} with {len(claude_arch.agents_to_use)} agents",
            exchange_type="architecture",
        )

        # Check budget for validation step
        if not self.cost_estimator.can_afford("validate_architecture"):
            logger.warning("  Budget insufficient for Phase 3b - using Claude architecture directly")
            return claude_arch

        # Phase 3b: Gemini validates and optimizes
        logger.info("  Phase 3b: Gemini validating architecture...")
        try:
            final_arch = await self._validate_with_gemini(claude_arch, task, capabilities)

            # V13.0 CEREBRO LIVE: Emit Gemini's validation response
            emit_agent_speak("gemini", f"Validation: {final_arch.reasoning[:100]}", action_type="VALIDATION")
            emit_agent_exchange(
                "gemini",
                "claude",
                f"Validated: {final_arch.collaboration_mode} mode approved",
                exchange_type="architecture",
            )

            return final_arch
        except Exception as e:
            logger.warning(f"  Gemini validation failed: {e} - using Claude architecture")
            return claude_arch

    async def _generate_with_claude(
        self, task: str, approach: str, capabilities: list[str], available_agents: str
    ) -> AgentArchitecture:
        """Phase 3a: Claude generates initial architecture."""
        prompt = CLAUDE_ARCHITECTURE_PROMPT.format(
            task=task, approach=approach, capabilities=", ".join(capabilities), available_agents=available_agents
        )

        # V12.4: TechniqueSelector - enhance prompt with adaptive techniques (arxiv:2510.18162)
        _selected_techniques = []
        try:
            from core.memory_pkg.prompts.technique_selector import get_technique_selector

            _tech_selector = get_technique_selector()
            _selection = _tech_selector.select(task, domains=capabilities[:3])
            _selected_techniques = _selection.techniques
            prompt = _tech_selector.compose_prompt(prompt, _selected_techniques)
            logger.debug(
                f"Phase 3a: TechniqueSelector applied {[t.value for t in _selected_techniques]} ({_selection.cluster_name})"
            )
        except Exception:
            pass

        # Get session for Claude
        session_uuid = None
        if self._session_integration:
            session_uuid = self._session_integration.get_agent_session("claude")
            logger.debug(f"Claude architecture using session {session_uuid[:8] if session_uuid else 'none'}")

        try:
            # V12.4.1: Use invoke() with static system prompt (cached)
            response = await self.claude.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=ARCHITECTURE_SYSTEM_PROMPT,
                agent_name="claude",
                agent_id="claude",
            )

            if not response.is_success:
                raise RuntimeError(f"Claude architecture generation failed: {response.error_message}")

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "generate_architecture_claude",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("generate_architecture_claude", total_tokens)

            return self._parse_architecture_response(response.content, capabilities)

        except Exception as e:
            logger.error(f"Claude architecture generation failed: {e}")
            return self._create_fallback_architecture(capabilities)

    async def _validate_with_gemini(
        self, claude_arch: AgentArchitecture, task: str, capabilities: list[str]
    ) -> AgentArchitecture:
        """Phase 3b: Gemini validates and optimizes Claude's architecture."""
        # Serialize architecture to JSON for prompt
        arch_dict = {
            "agents_to_use": claude_arch.agents_to_use,
            "agents_to_spawn": [
                {
                    "role": spec.role,
                    "mission": spec.mission,
                    "capabilities": spec.capabilities,
                    "tools_priority": spec.tools_priority,
                    "estimated_cost": spec.estimated_cost,
                }
                for spec in claude_arch.agents_to_spawn
            ],
            "execution_strategy": claude_arch.collaboration_mode,
            "execution_steps": [
                {
                    "name": step.name,
                    "agent_id": step.agent_id,
                    "action": step.action,
                    "expected_duration": step.expected_duration,
                    "depends_on": step.depends_on,
                    "verification_required": step.verification_required,
                }
                for step in claude_arch.execution_plan.steps
            ],
            "rag_config": {
                "enabled": claude_arch.rag_config.enabled,
                "depth": claude_arch.rag_config.depth,
                "sources": claude_arch.rag_config.sources,
                "max_chunks": claude_arch.rag_config.max_chunks,
            },
            "reasoning": claude_arch.reasoning,
        }

        prompt = GEMINI_VALIDATION_PROMPT.format(task=task, architecture_json=json.dumps(arch_dict, indent=2))

        # Get session for Gemini
        session_uuid = None
        if self._session_integration:
            session_uuid = self._session_integration.get_agent_session("gemini")
            logger.debug(f"Gemini validation using session {session_uuid[:8] if session_uuid else 'none'}")

        # V12.4.1: Use invoke() with system prompt
        response = await self.gemini.invoke(
            prompt,
            session_id=session_uuid,
            system_prompt=ARCHITECTURE_SYSTEM_PROMPT,
            agent_name="gemini",
            agent_id="gemini",
        )

        if not response.is_success:
            logger.warning(f"Gemini validation failed: {response.error_message}, using Claude's architecture")
            return claude_arch

        # Record actual token usage
        if hasattr(self.cost_estimator, "record_tokens"):
            self.cost_estimator.record_tokens(
                "validate_architecture_gemini",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        else:
            total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
            self.cost_estimator.record_cost("validate_architecture_gemini", total_tokens)

        # Parse validation response
        from ..json_parser import parse_json_response

        data = parse_json_response(response.content, "validation", default=None)

        if data is None:
            logger.warning("  Gemini validation parse failed - using Claude architecture")
            return claude_arch

        validation_status = data.get("validation", "APPROVED")
        optimizations = data.get("optimizations", [])

        if optimizations:
            logger.info(f"  Gemini optimizations: {', '.join(optimizations[:3])}")

        # Extract the (possibly optimized) architecture
        arch_data = data.get("architecture", arch_dict)

        # Parse the validated architecture
        validated_arch = self._parse_architecture_response(
            json.dumps(arch_data),  # Re-serialize for parser
            capabilities,
        )

        # Update reasoning to reflect collaboration
        validated_arch.reasoning = (
            f"[Collaborative V12.4] Claude designed, Gemini {validation_status.lower()}. {validated_arch.reasoning}"
        )

        return validated_arch

    async def _generate_legacy(
        self, task: str, approach: str, capabilities: list[str], available_agents: str
    ) -> AgentArchitecture:
        """Legacy architecture generation using Gemini only."""
        prompt = ARCHITECTURE_PROMPT.format(
            task=task, approach=approach, capabilities=", ".join(capabilities), available_agents=available_agents
        )

        # V9.2: Get session for architecture generation
        session_uuid = None
        if self._session_integration:
            session_uuid = self._session_integration.get_agent_session("gemini")
            logger.debug(f"Architecture generation using session {session_uuid[:8] if session_uuid else 'none'}")

        try:
            # V12.4.1: Use invoke() with system prompt
            response = await self.gemini.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=ARCHITECTURE_SYSTEM_PROMPT,
                agent_name="gemini",
                agent_id="gemini",
            )

            if not response.is_success:
                raise RuntimeError(f"Legacy architecture generation failed: {response.error_message}")

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "generate_architecture",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("generate_architecture", total_tokens)

            # Parse response
            return self._parse_architecture_response(response.content, capabilities)

        except Exception as e:
            logger.error(f"Architecture generation failed: {e}")
            return self._create_fallback_architecture(capabilities)

    def _parse_architecture_response(self, response, capabilities: list[str]) -> AgentArchitecture:
        """Parse architecture JSON from response."""
        from ..json_parser import parse_json_response

        data = parse_json_response(response, "architecture", default=None)
        if data is None:
            return self._create_fallback_architecture(capabilities)

        try:
            # Parse agents to spawn
            agents_to_spawn = []
            for spec_data in data.get("agents_to_spawn", []):
                agents_to_spawn.append(
                    AgentSpec(
                        role=spec_data.get("role", "specialist"),
                        mission=spec_data.get("mission", ""),
                        capabilities=spec_data.get("capabilities", []),
                        tools_priority=spec_data.get("tools_priority", []),
                        estimated_cost=spec_data.get("estimated_cost", 500),
                    )
                )

            # Parse execution steps
            steps = []
            for step_data in data.get("execution_steps", []):
                steps.append(
                    ExecutionStep(
                        name=step_data.get("name", "step"),
                        agent_id=step_data.get("agent_id", "claude"),
                        action=step_data.get("action", ""),
                        expected_duration=step_data.get("expected_duration", 30),
                        depends_on=step_data.get("depends_on", []),
                        verification_required=step_data.get("verification_required", False),
                    )
                )

            # Parse RAG config
            rag_data = data.get("rag_config", {})
            rag_config = RAGConfig(
                enabled=rag_data.get("enabled", True),
                depth=rag_data.get("depth", "standard"),
                sources=rag_data.get("sources", ["codebase"]),
                max_chunks=rag_data.get("max_chunks", 10),
            )

            # Calculate estimated cost
            total_cost = sum(spec.estimated_cost for spec in agents_to_spawn)
            total_cost += len(steps) * 500  # Estimate per step

            # Determine status
            status = "SPAWN_REQUIRED" if agents_to_spawn else "READY"

            return AgentArchitecture(
                status=status,
                collaboration_mode=data.get("execution_strategy", "sequential"),
                agents_to_use=data.get("agents_to_use", ["claude", "gemini"]),
                agents_to_spawn=agents_to_spawn,
                rag_config=rag_config,
                execution_plan=ExecutionPlan(
                    strategy=data.get("execution_strategy", "sequential"),
                    steps=steps,
                    estimated_total_duration=sum(s.expected_duration for s in steps),
                    estimated_total_tokens=total_cost,
                ),
                estimated_cost=total_cost,
                reasoning=data.get("reasoning", ""),
            )

        except Exception as e:
            logger.warning(f"Architecture parse error: {e}")
            return self._create_fallback_architecture(capabilities)

    def _create_fallback_architecture(self, capabilities: list[str]) -> AgentArchitecture:
        """Create fallback architecture when generation fails."""
        return AgentArchitecture(
            status="READY",
            collaboration_mode="sequential",
            agents_to_use=["claude", "gemini"],
            agents_to_spawn=[],
            rag_config=RAGConfig(),
            execution_plan=ExecutionPlan(
                strategy="sequential",
                steps=[
                    ExecutionStep(
                        name="main_execution",
                        agent_id="claude",
                        action="Execute task with available capabilities",
                        expected_duration=60,
                    )
                ],
                estimated_total_duration=60,
                estimated_total_tokens=1000,
            ),
            estimated_cost=1000,
            reasoning="Fallback architecture due to generation failure",
        )

    def _check_for_duplicates(self, architecture: AgentArchitecture) -> AgentArchitecture:
        """Check for duplicate agents and remove them."""
        self.cost_estimator.record_cost("check_registry", 100)

        remaining_spawns = []
        for spec in architecture.agents_to_spawn:
            # Check if similar agent exists
            similar = self.registry.find_similar(spec.capabilities)

            if similar:
                logger.info(f"Found similar agent '{similar.agent_id}' for '{spec.role}' - skipping spawn")
                # Add existing agent to use list
                if similar.agent_id not in architecture.agents_to_use:
                    architecture.agents_to_use.append(similar.agent_id)
            else:
                remaining_spawns.append(spec)

        architecture.agents_to_spawn = remaining_spawns

        if not remaining_spawns:
            architecture.status = "READY"
        else:
            architecture.status = "SPAWN_SUGGESTED"

        return architecture

    async def _spawn_agents(self, specs: list[AgentSpec]) -> list[str]:
        """Spawn new agents from specifications."""
        spawned = []

        for spec in specs:
            try:
                # Generate unique ID
                import hashlib

                agent_id = f"{spec.role}_{hashlib.md5(spec.mission.encode(), usedforsecurity=False).hexdigest()[:6]}"

                # Create agent file in workspace
                agent_path = self.workspace_path / "agents" / f"{agent_id}.json"
                agent_path.parent.mkdir(parents=True, exist_ok=True)

                agent_config = {
                    "id": agent_id,
                    "role": spec.role,
                    "mission": spec.mission,
                    "capabilities": spec.capabilities,
                    "tools_priority": spec.tools_priority,
                    "created_by": "hive_mind_v8",
                    # V12.4 FIX F19: Use time.time() instead of deprecated get_event_loop().time()
                    "created_at": str(time.time()),
                }

                agent_path.write_text(json.dumps(agent_config, indent=2), encoding="utf-8")

                # Register in registry
                self.registry.register_spawn(
                    agent_id=agent_id, role=spec.role, capabilities=spec.capabilities, mission=spec.mission
                )

                # Record cost
                self.cost_estimator.record_cost("spawn_agent", spec.estimated_cost)

                spawned.append(agent_id)
                logger.info(f"Spawned agent: {agent_id}")

            except Exception as e:
                logger.error(f"Failed to spawn {spec.role}: {e}")

        return spawned

    def _annotate_with_graph_of_thought(self, architecture: AgentArchitecture) -> None:
        """
        V12.4: Analyze execution plan with GraphOfThought.

        Builds a DAG from execution steps, identifies parallelizable groups,
        and annotates the architecture with:
        - Critical path length
        - Parallel execution opportunities
        - Topological execution order
        """
        try:
            from core.intelligence.reasoning.graph_of_thought import ThoughtGraph, ThoughtType

            steps = architecture.execution_plan.steps
            if not steps:
                return

            graph = ThoughtGraph(name="execution_plan_analysis")

            # Build name-to-ID mapping
            step_node_ids: dict[str, str] = {}

            for step in steps:
                deps = []
                for dep_name in step.depends_on or []:
                    if dep_name in step_node_ids:
                        deps.append(step_node_ids[dep_name])

                node = graph.create_node(
                    question=step.action[:100] if step.action else step.name,
                    name=step.name,
                    thought_type=ThoughtType.ANALYZE,
                    dependencies=deps,
                )
                step_node_ids[step.name] = node.id

            # Get execution order and identify parallelizable groups
            exec_order = graph.get_execution_order()
            root_nodes = graph.root_nodes
            leaf_nodes = graph.leaf_nodes

            # Identify parallel groups: nodes at the same depth with no mutual deps
            depth_groups: dict[int, list[str]] = {}
            for nid in exec_order:
                depth = graph._get_depth(nid)
                depth_groups.setdefault(depth, []).append(nid)

            parallel_opportunities = sum(1 for group in depth_groups.values() if len(group) > 1)

            # Annotate architecture reasoning with DAG analysis
            dag_info = (
                f" [GoT DAG: {len(steps)} nodes, "
                f"{len(root_nodes)} roots, {len(leaf_nodes)} leaves, "
                f"{parallel_opportunities} parallel opportunities, "
                f"depth={len(depth_groups)}]"
            )
            architecture.reasoning = (architecture.reasoning or "") + dag_info

            logger.info(
                f"Phase 3: GoT analysis - {len(steps)} steps, "
                f"{parallel_opportunities} parallelizable groups, "
                f"critical path depth={len(depth_groups)}"
            )

        except Exception as e:
            logger.debug(f"GraphOfThought annotation failed: {e}")

    def get_execution_ready_architecture(self, result: ArchitecturePhaseResult) -> dict[str, Any]:
        """
        Get architecture in format ready for Phase 4 execution.

        Args:
            result: Phase 3 result

        Returns:
            Execution-ready configuration
        """
        arch = result.architecture

        return {
            "mode": arch.collaboration_mode,
            "agents": arch.agents_to_use + result.agents_spawned,
            "steps": [
                {
                    "name": step.name,
                    "agent": step.agent_id,
                    "action": step.action,
                    "timeout": step.expected_duration,
                    "depends_on": step.depends_on,
                    "verify": step.verification_required,
                }
                for step in arch.execution_plan.steps
            ],
            "rag": {
                "enabled": arch.rag_config.enabled,
                "depth": arch.rag_config.depth,
                "sources": arch.rag_config.sources,
                "max_chunks": arch.rag_config.max_chunks,
            },
            "estimated_tokens": arch.estimated_cost,
            "estimated_duration": arch.execution_plan.estimated_total_duration,
        }
