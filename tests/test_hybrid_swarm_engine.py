"""
Tests for HybridSwarmEngine - Comprehensive test suite.

Tests the main swarm orchestration engine that coordinates:
- Task analysis
- Mode selection (DyLAN-based)
- Agent negotiation
- Mode execution
- Result merging and metrics update

Coverage targets:
- SwarmPhase enum
- SwarmResult dataclass
- HybridSwarmEngine constructor and process_task() flow
- Phase transitions
- Auto-routing and forced mode logic
- Negotiation consensus/fallback
- Execution delegation
- Error handling and recovery
- Session tracking
- DyLAN metrics updates
- Edge cases
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.agent_metrics import (
    AgentPool,
    AgentProfile,
    create_default_pool,
)
from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.intelligence.swarm.hybrid_swarm_engine import (
    HybridSwarmEngine,
    SwarmPhase,
    SwarmResult,
)
from core.intelligence.swarm.mode_executors import (
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
)
from core.intelligence.swarm.mode_selector import (
    AgentAssignment,
    ModeProposal,
)
from core.intelligence.swarm.negotiation_protocol import (
    NegotiationResult,
    NegotiationStatus,
)
from core.intelligence.swarm.task_analyzer import (
    TaskAnalysis,
    TaskComplexity,
    TaskDomain,
)

# ---------------------------------------------------------------------------
# Helpers: reusable fixtures and factory functions
# ---------------------------------------------------------------------------


def _make_analysis(
    complexity: TaskComplexity = TaskComplexity.MODERATE,
    domains: list = None,
    primary_domain: TaskDomain = TaskDomain.CODING,
    raw_input: str = "Fix the auth bug",
) -> TaskAnalysis:
    """Create a TaskAnalysis with sensible defaults."""
    return TaskAnalysis(
        complexity=complexity,
        domains=domains or [primary_domain],
        primary_domain=primary_domain,
        raw_input=raw_input,
        gemini_fit_score=0.7,
        claude_fit_score=0.8,
        confidence=0.75,
    )


def _make_proposal(
    mode: CollaborationMode = CollaborationMode.PING_PONG,
    confidence: float = 0.8,
) -> ModeProposal:
    """Create a ModeProposal with sensible defaults."""
    return ModeProposal(
        mode=mode,
        confidence=confidence,
        agent_assignments=[
            AgentAssignment(agent_id="gemini_primary", role="equal", confidence=0.8),
            AgentAssignment(agent_id="claude_opus", role="equal", confidence=0.8),
        ],
        reasoning="Test proposal",
    )


def _make_execution_result(
    mode: CollaborationMode = CollaborationMode.PING_PONG,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    final_output: str = "Task completed successfully.",
) -> ExecutionResult:
    """Create an ExecutionResult with sensible defaults."""
    return ExecutionResult(
        mode=mode,
        status=status,
        final_output=final_output,
        agent_outputs=[
            AgentResponse(agent_id="gemini_primary", content="Gemini output", status="success"),
            AgentResponse(agent_id="claude_opus", content="Claude output", status="success"),
        ],
        total_rounds=3,
        total_tokens=500,
        total_time_seconds=5.0,
    )


def _make_negotiation_result(
    status: NegotiationStatus = NegotiationStatus.CONSENSUS,
    mode: CollaborationMode = CollaborationMode.LEAD_SUPPORT,
) -> NegotiationResult:
    """Create a NegotiationResult with sensible defaults."""
    return NegotiationResult(
        status=status,
        selected_mode=mode,
        agent_assignments=[
            AgentAssignment(agent_id="gemini_primary", role="lead", confidence=0.9),
            AgentAssignment(agent_id="claude_opus", role="support", confidence=0.7),
        ],
        negotiation_history=[],
        total_turns=2,
        consensus_confidence=0.85,
    )


# ---------------------------------------------------------------------------
# Telemetry bridge mock applied to all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_telemetry():
    """Mock the telemetry bridge for all tests to avoid Redis dependency."""
    mock_bridge = MagicMock()
    mock_bridge.emit_sync = MagicMock()
    with (
        patch(
            "core.intelligence.swarm.hybrid_swarm_engine.get_telemetry_bridge",
            return_value=mock_bridge,
        ),
        patch(
            "core.intelligence.swarm.hybrid_swarm_engine.emit_agent_exchange",
        ),
        patch(
            "core.intelligence.swarm.hybrid_swarm_engine.emit_agent_speak",
        ),
    ):
        yield mock_bridge


# ============================================================================
# Section 1: SwarmPhase enum
# ============================================================================


class TestSwarmPhase:
    """Tests for SwarmPhase enum values and ordering."""

    def test_all_phases_exist(self):
        """All 7 SwarmPhase values must be present."""
        expected = {"idle", "analyzing", "selecting", "negotiating", "executing", "completed", "failed"}
        actual = {phase.value for phase in SwarmPhase}
        assert actual == expected

    def test_phase_values_are_strings(self):
        for phase in SwarmPhase:
            assert isinstance(phase.value, str)

    def test_idle_is_default_initial_phase(self):
        assert SwarmPhase.IDLE.value == "idle"

    def test_completed_and_failed_are_terminal(self):
        assert SwarmPhase.COMPLETED.value == "completed"
        assert SwarmPhase.FAILED.value == "failed"

    def test_phases_are_distinct(self):
        values = [p.value for p in SwarmPhase]
        assert len(values) == len(set(values))


# ============================================================================
# Section 2: SwarmResult dataclass and to_dict
# ============================================================================


class TestSwarmResult:
    """Tests for SwarmResult creation and serialization."""

    def _make_result(self, **overrides) -> SwarmResult:
        defaults = dict(
            status=SwarmPhase.COMPLETED,
            final_output="Done",
            selected_mode=CollaborationMode.PING_PONG,
            task_analysis=_make_analysis(),
            mode_proposal=_make_proposal(),
            negotiation_result=None,
            execution_result=_make_execution_result(),
            total_time_seconds=1.5,
        )
        defaults.update(overrides)
        return SwarmResult(**defaults)

    def test_creation_basic(self):
        result = self._make_result()
        assert result.status == SwarmPhase.COMPLETED
        assert result.final_output == "Done"
        assert result.total_time_seconds == 1.5

    def test_timestamp_auto_set(self):
        result = self._make_result()
        assert isinstance(result.timestamp, datetime)

    def test_to_dict_keys(self):
        d = self._make_result().to_dict()
        required_keys = {
            "status",
            "final_output",
            "selected_mode",
            "task_analysis",
            "mode_proposal",
            "negotiation_result",
            "execution_result",
            "total_time_seconds",
            "timestamp",
        }
        assert required_keys.issubset(d.keys())

    def test_to_dict_status_is_string(self):
        d = self._make_result().to_dict()
        assert d["status"] == "completed"

    def test_to_dict_selected_mode_is_string(self):
        d = self._make_result().to_dict()
        assert d["selected_mode"] == "ping_pong"

    def test_to_dict_negotiation_result_none(self):
        d = self._make_result(negotiation_result=None).to_dict()
        assert d["negotiation_result"] is None

    def test_to_dict_negotiation_result_present(self):
        neg = _make_negotiation_result()
        d = self._make_result(negotiation_result=neg).to_dict()
        assert d["negotiation_result"] is not None
        assert d["negotiation_result"]["status"] == "consensus"

    def test_to_dict_total_time_rounded(self):
        d = self._make_result(total_time_seconds=1.23456789).to_dict()
        assert d["total_time_seconds"] == 1.23

    def test_to_dict_timestamp_iso(self):
        d = self._make_result().to_dict()
        # ISO format can be parsed back
        datetime.fromisoformat(d["timestamp"])

    def test_to_dict_task_analysis_is_dict(self):
        d = self._make_result().to_dict()
        assert isinstance(d["task_analysis"], dict)
        assert "complexity" in d["task_analysis"]

    def test_to_dict_mode_proposal_is_dict(self):
        d = self._make_result().to_dict()
        assert isinstance(d["mode_proposal"], dict)
        assert "mode" in d["mode_proposal"]


# ============================================================================
# Section 3: HybridSwarmEngine constructor
# ============================================================================


class TestHybridSwarmEngineConstructor:
    """Tests for HybridSwarmEngine initialization."""

    def test_default_construction(self):
        engine = HybridSwarmEngine()
        assert engine.current_phase == SwarmPhase.IDLE
        assert engine.agent_pool is not None
        assert engine.model_router is None
        assert engine.config is None
        assert engine.invoke_agent is None
        assert engine.workspace_path is None
        assert engine.session_manager is None
        assert engine.processing_history == []

    def test_creates_default_pool_when_none(self):
        engine = HybridSwarmEngine(agent_pool=None)
        assert len(engine.agent_pool.agents) >= 2

    def test_custom_agent_pool(self):
        pool = AgentPool()
        pool.register(AgentProfile(agent_id="test_agent", provider="test", model="test-model"))
        engine = HybridSwarmEngine(agent_pool=pool)
        assert "test_agent" in engine.agent_pool.agents

    def test_model_router_stored(self):
        router = MagicMock()
        engine = HybridSwarmEngine(model_router=router)
        assert engine.model_router is router

    def test_invoke_agent_stored(self):
        fn = MagicMock()
        engine = HybridSwarmEngine(invoke_agent=fn)
        assert engine.invoke_agent is fn

    def test_workspace_path_enables_session_manager(self, tmp_path):
        engine = HybridSwarmEngine(workspace_path=tmp_path)
        assert engine.session_manager is not None

    def test_no_workspace_path_disables_session_manager(self):
        engine = HybridSwarmEngine(workspace_path=None)
        assert engine.session_manager is None

    def test_config_values_used(self):
        config = MagicMock()
        config.swarm_negotiation_max_turns = 8
        config.swarm_skip_trivial = False
        engine = HybridSwarmEngine(config=config)
        assert engine.negotiation.base_max_turns == 8
        assert engine.negotiation.skip_trivial is False

    def test_internal_state_reset(self):
        engine = HybridSwarmEngine()
        assert engine._current_analysis is None
        assert engine._current_proposal is None
        assert engine._negotiation_result is None
        assert engine._current_task_id is None


# ============================================================================
# Section 4: _get_config helper
# ============================================================================


class TestGetConfig:
    """Tests for the _get_config helper method."""

    def test_returns_default_when_config_is_none(self):
        engine = HybridSwarmEngine(config=None)
        assert engine._get_config("anything", 42) == 42

    def test_returns_attr_when_present(self):
        config = MagicMock()
        config.my_key = "my_value"
        engine = HybridSwarmEngine(config=config)
        assert engine._get_config("my_key", "default") == "my_value"

    def test_returns_default_when_attr_missing(self):
        config = MagicMock(spec=[])
        engine = HybridSwarmEngine(config=config)
        assert engine._get_config("nonexistent", 99) == 99


# ============================================================================
# Section 5: process_task() full flow with mocked components
# ============================================================================


class TestProcessTaskFullFlow:
    """Tests for the process_task() pipeline with mocked internals."""

    def _build_engine_with_mocks(self, **overrides):
        """Build engine and patch internal components."""
        engine = HybridSwarmEngine()

        analysis = overrides.get("analysis", _make_analysis())
        proposal = overrides.get("proposal", _make_proposal())
        exec_result = overrides.get("exec_result", _make_execution_result())

        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = analysis

        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = proposal

        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        return engine, analysis, proposal, exec_result

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_successful_pipeline(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()

        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        result = engine.process_task("Fix the auth bug")

        assert result.status == SwarmPhase.COMPLETED
        assert result.final_output == "Task completed successfully."
        assert engine.current_phase == SwarmPhase.COMPLETED

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_task_analyzer_called(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something")
        engine.task_analyzer.analyze.assert_called_once_with("Do something")

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_mode_selector_called(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something")
        engine.mode_selector.select_mode.assert_called_once_with(analysis)

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_negotiation_called_when_enabled(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        # Default config enables negotiation
        engine.config = None
        engine.process_task("Do something")
        engine.negotiation.run_negotiation.assert_called_once()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_negotiation_skipped_when_disabled(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something", skip_negotiation=True)
        engine.negotiation.run_negotiation.assert_not_called()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_negotiation_skipped_with_force_mode(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something", force_mode=CollaborationMode.SPECIALIST)
        engine.negotiation.run_negotiation.assert_not_called()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_blackboard_populated(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("Do something", blackboard={"key": "value"})

        # Verify the ExecutionContext passed to executor has blackboard data
        call_args = mock_executor.execute_with_fallback.call_args
        ctx = call_args[0][0]
        assert isinstance(ctx, ExecutionContext)
        assert "task_analysis" in ctx.blackboard
        assert "key" in ctx.blackboard

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_result_includes_all_fields(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Do something", skip_negotiation=True)

        assert result.task_analysis is not None
        assert result.mode_proposal is not None
        assert result.execution_result is not None
        assert result.total_time_seconds >= 0

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_processing_history_recorded(self, mock_get_exec):
        engine, analysis, proposal, exec_result = self._build_engine_with_mocks()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something", skip_negotiation=True)
        assert len(engine.processing_history) == 1
        record = engine.processing_history[0]
        assert "mode" in record
        assert "complexity" in record
        assert "status" in record
        assert record["status"] == "completed"


# ============================================================================
# Section 6: Phase transitions
# ============================================================================


class TestPhaseTransitions:
    """Tests that phases progress correctly through the pipeline."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_phases_progress_through_pipeline(self, mock_get_exec):
        """Verify engine traverses ANALYZING -> SELECTING -> NEGOTIATING -> EXECUTING -> COMPLETED."""
        phases_seen = []

        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        # Track phase changes via the telemetry bridge emit_sync calls
        def emit_sync_tracker(event_type, data):
            if "phase" in data:
                phases_seen.append(data["phase"])

        mock_bridge = MagicMock()
        mock_bridge.emit_sync = emit_sync_tracker

        with (
            patch(
                "core.intelligence.swarm.hybrid_swarm_engine.get_telemetry_bridge",
                return_value=mock_bridge,
            ),
            patch(
                "core.intelligence.swarm.hybrid_swarm_engine.emit_agent_exchange",
            ),
            patch(
                "core.intelligence.swarm.hybrid_swarm_engine.emit_agent_speak",
            ),
        ):
            engine.process_task("Test task")

        assert "analyzing" in phases_seen
        assert "selecting" in phases_seen
        assert "negotiating" in phases_seen
        assert "executing" in phases_seen
        assert "completed" in phases_seen

    def test_start_analysis_sets_analyzing(self):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()

        engine.start_analysis("test")
        assert engine.current_phase == SwarmPhase.ANALYZING

    def test_start_selection_sets_selecting(self):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()

        engine.start_analysis("test")
        engine.start_selection()
        assert engine.current_phase == SwarmPhase.SELECTING

    def test_start_selection_without_analysis_raises(self):
        engine = HybridSwarmEngine()
        with pytest.raises(ValueError, match="Analysis must be run"):
            engine.start_selection()

    def test_start_negotiation_sets_negotiating(self):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        engine.start_analysis("test")
        engine.start_selection()
        engine.start_negotiation()
        assert engine.current_phase == SwarmPhase.NEGOTIATING

    def test_execute_turn_sets_executing(self):
        engine = HybridSwarmEngine()
        engine._current_proposal = _make_proposal()

        with patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor") as mock_get:
            mock_get.return_value.execute.return_value = _make_execution_result()
            engine.execute_turn("test")

        assert engine.current_phase == SwarmPhase.EXECUTING


# ============================================================================
# Section 7: Auto-routing and forced mode logic
# ============================================================================


class TestAutoRouting:
    """Tests for auto-routing (swarm vs skip) and forced mode."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_force_mode_uses_specified_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal(mode=CollaborationMode.SEQUENTIAL)

        exec_result = _make_execution_result(mode=CollaborationMode.SPECIALIST)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Do something", force_mode=CollaborationMode.SPECIALIST, skip_negotiation=True)
        assert result.selected_mode == CollaborationMode.SPECIALIST

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_forced_proposal_overrides_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        analysis = _make_analysis()
        engine.task_analyzer.analyze.return_value = analysis
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal(mode=CollaborationMode.PING_PONG)

        exec_result = _make_execution_result(mode=CollaborationMode.RED_BLUE)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Security review", force_mode=CollaborationMode.RED_BLUE)
        # The forced proposal should have confidence=1.0
        assert result.mode_proposal.confidence == 1.0
        assert result.mode_proposal.reasoning == "User forced mode"

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_consensus_mode_overrides_proposal(self, mock_get_exec):
        """When negotiation reaches consensus, use negotiated mode."""
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal(mode=CollaborationMode.PING_PONG)
        engine.negotiation = MagicMock()
        neg_result = _make_negotiation_result(
            status=NegotiationStatus.CONSENSUS,
            mode=CollaborationMode.LEAD_SUPPORT,
        )
        engine.negotiation.run_negotiation.return_value = neg_result

        exec_result = _make_execution_result(mode=CollaborationMode.LEAD_SUPPORT)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Do something")
        assert result.selected_mode == CollaborationMode.LEAD_SUPPORT


# ============================================================================
# Section 8: Negotiation fallback on failure/timeout
# ============================================================================


class TestNegotiationFallback:
    """Tests for mode fallback when negotiation fails or times out."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_timeout_falls_back_to_proposal_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        proposal = _make_proposal(mode=CollaborationMode.SEQUENTIAL)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = proposal
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = NegotiationResult(
            status=NegotiationStatus.TIMEOUT,
            selected_mode=CollaborationMode.SEQUENTIAL,
            agent_assignments=proposal.agent_assignments,
            negotiation_history=[],
            total_turns=4,
            consensus_confidence=0.5,
        )

        exec_result = _make_execution_result(mode=CollaborationMode.SEQUENTIAL)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Do something")
        # On timeout, the engine uses proposal.mode (not negotiation result mode)
        assert result.selected_mode == CollaborationMode.SEQUENTIAL

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_non_consensus_uses_proposal_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        proposal = _make_proposal(mode=CollaborationMode.PARALLEL)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = proposal
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = NegotiationResult(
            status=NegotiationStatus.TIMEOUT,
            selected_mode=CollaborationMode.RED_BLUE,
            agent_assignments=proposal.agent_assignments,
            negotiation_history=[],
            total_turns=4,
            consensus_confidence=0.4,
        )

        exec_result = _make_execution_result(mode=CollaborationMode.PARALLEL)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Do something")
        assert result.selected_mode == CollaborationMode.PARALLEL


# ============================================================================
# Section 9: Execution delegation
# ============================================================================


class TestExecutionDelegation:
    """Tests for executor selection and invocation."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_get_executor_called_with_final_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal(mode=CollaborationMode.SPECIALIST)
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result(
            status=NegotiationStatus.CONSENSUS,
            mode=CollaborationMode.SPECIALIST,
        )

        exec_result = _make_execution_result(mode=CollaborationMode.SPECIALIST)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something")
        mock_get_exec.assert_called_once_with(CollaborationMode.SPECIALIST, workspace_path=None)

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_self_healing_enabled_uses_execute_with_fallback(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("Do something")
        mock_executor.execute_with_fallback.assert_called_once()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_self_healing_disabled_uses_execute(self, mock_get_exec):
        config = MagicMock()
        config.swarm_self_healing = False
        config.swarm_negotiation_enabled = True
        config.swarm_negotiation_max_turns = 4
        config.swarm_skip_trivial = True
        config.swarm_max_rounds = 6
        config.swarm_max_fallbacks = 2

        engine = HybridSwarmEngine(config=config)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("Do something")
        mock_executor.execute.assert_called_once()
        mock_executor.execute_with_fallback.assert_not_called()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_execution_context_has_correct_task_input(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("My specific task")
        ctx = mock_executor.execute_with_fallback.call_args[0][0]
        assert ctx.task_input == "My specific task"


# ============================================================================
# Section 10: Error handling and recovery
# ============================================================================


class TestErrorHandling:
    """Tests for error handling and recovery paths."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_exception_during_analysis_returns_failed(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.side_effect = RuntimeError("Analyzer broke")

        result = engine.process_task("Do something")
        assert result.status == SwarmPhase.FAILED
        assert "Analyzer broke" in result.final_output

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_exception_during_execution_returns_failed(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        mock_get_exec.return_value.execute_with_fallback.side_effect = Exception("Exec failed")

        result = engine.process_task("Do something")
        assert result.status == SwarmPhase.FAILED
        assert "Exec failed" in result.final_output
        assert engine.current_phase == SwarmPhase.FAILED

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_failed_result_has_fallback_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.side_effect = ValueError("boom")

        result = engine.process_task("Do something")
        assert result.selected_mode == CollaborationMode.PING_PONG

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_failed_result_has_error_execution_result(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.side_effect = ValueError("boom")

        result = engine.process_task("Do something")
        assert result.execution_result.status == ExecutionStatus.FAILED
        assert "boom" in result.execution_result.final_output

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_failed_with_force_mode_preserves_mode(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.side_effect = Exception("fail")

        result = engine.process_task("Do something", force_mode=CollaborationMode.RED_BLUE)
        assert result.selected_mode == CollaborationMode.RED_BLUE

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_exception_in_negotiation_returns_failed(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.side_effect = RuntimeError("Neg failed")

        result = engine.process_task("Do something")
        assert result.status == SwarmPhase.FAILED
        assert "Neg failed" in result.final_output


# ============================================================================
# Section 11: Session tracking
# ============================================================================


class TestSessionTracking:
    """Tests for session creation and tracking in process_task."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_task_id_generated_without_session_manager(self, mock_get_exec):
        """Without a session_manager the task_id is set but NOT cleared by the finally block."""
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something")
        # No session_manager => finally block does not execute => task_id stays set
        assert engine._current_task_id is not None
        assert engine._current_task_id.startswith("swarm_")

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_task_id_cleared_with_session_manager(self, mock_get_exec, tmp_path):
        """With a session_manager the task_id is cleared in the finally block."""
        engine = HybridSwarmEngine(workspace_path=tmp_path)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.session_manager = MagicMock()
        # Simulate get_task returning a task whose status is already completed
        engine.session_manager.get_task.return_value = None

        engine.process_task("Do something")
        # finally block executed and cleared the task_id
        assert engine._current_task_id is None

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_session_manager_create_called(self, mock_get_exec, tmp_path):
        engine = HybridSwarmEngine(workspace_path=tmp_path)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.session_manager = MagicMock()
        engine.session_manager.get_task.return_value = None

        engine.process_task("Do something")
        engine.session_manager.create_task.assert_called_once()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_session_ephemeral_for_trivial(self, mock_get_exec, tmp_path):
        engine = HybridSwarmEngine(workspace_path=tmp_path)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis(complexity=TaskComplexity.TRIVIAL)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.session_manager = MagicMock()
        engine.session_manager.get_task.return_value = None

        engine.process_task("hello")
        call_kwargs = engine.session_manager.create_task.call_args
        assert (
            call_kwargs[1].get("is_ephemeral") is True
            or (len(call_kwargs[0]) > 2 and call_kwargs[0][2] is True)
            or call_kwargs.kwargs.get("is_ephemeral") is True
        )


# ============================================================================
# Section 12: DyLAN metrics updates after task completion
# ============================================================================


class TestDyLANMetricsUpdate:
    """Tests for DyLAN metrics updates after execution."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_metrics_recorded_for_successful_agents(self, mock_get_exec):
        pool = create_default_pool()
        engine = HybridSwarmEngine(agent_pool=pool)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        # Record initial invocation count
        gemini_initial = len(pool.agents["gemini_primary"].invocation_history)
        claude_initial = len(pool.agents["claude_opus"].invocation_history)

        engine.process_task("Do something")

        # Both agents should have new invocations recorded
        assert len(pool.agents["gemini_primary"].invocation_history) > gemini_initial
        assert len(pool.agents["claude_opus"].invocation_history) > claude_initial

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_error_agent_gets_zero_quality(self, mock_get_exec):
        pool = create_default_pool()
        engine = HybridSwarmEngine(agent_pool=pool)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = ExecutionResult(
            mode=CollaborationMode.PING_PONG,
            status=ExecutionStatus.COMPLETED,
            final_output="partial",
            agent_outputs=[
                AgentResponse(agent_id="gemini_primary", content="ok", status="success"),
                AgentResponse(agent_id="claude_opus", content="error", status="error"),
            ],
            total_rounds=1,
            total_tokens=100,
            total_time_seconds=2.0,
        )
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        engine.process_task("Do something")

        # Check the last invocation for claude_opus has quality_score=0.0
        claude_last = pool.agents["claude_opus"].invocation_history[-1]
        assert claude_last.quality_score == 0.0
        assert claude_last.success is False

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_no_metrics_update_without_pool(self, mock_get_exec):
        engine = HybridSwarmEngine(agent_pool=None)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        # Should not raise even with explicit None pool for _update_metrics
        engine.agent_pool = None
        engine.process_task("Do something")


# ============================================================================
# Section 13: Edge cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases: empty input, all agents fail, etc."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_empty_task_input(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis(raw_input="")
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("")
        assert result.status == SwarmPhase.COMPLETED

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_all_agents_fail_execution(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        failed_exec = ExecutionResult(
            mode=CollaborationMode.PING_PONG,
            status=ExecutionStatus.FAILED,
            final_output="All agents failed",
            agent_outputs=[
                AgentResponse(agent_id="gemini_primary", content="err", status="error"),
                AgentResponse(agent_id="claude_opus", content="err", status="error"),
            ],
            total_rounds=0,
            total_tokens=0,
            total_time_seconds=0.0,
        )
        mock_get_exec.return_value.execute_with_fallback.return_value = failed_exec

        result = engine.process_task("Do something")
        # Engine still completes (executor returns result, not exception)
        assert result.status == SwarmPhase.COMPLETED
        assert result.execution_result.status == ExecutionStatus.FAILED

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_very_long_task_input(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        long_input = "a" * 10000
        engine.task_analyzer.analyze.return_value = _make_analysis(raw_input=long_input)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task(long_input)
        assert result.status == SwarmPhase.COMPLETED

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_none_blackboard_defaults_to_empty(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("task", blackboard=None)
        ctx = mock_executor.execute_with_fallback.call_args[0][0]
        assert isinstance(ctx.blackboard, dict)

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_multiple_tasks_accumulate_history(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        for _ in range(5):
            engine.process_task("task")

        assert len(engine.processing_history) == 5

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_history_capped_at_100(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        # Pre-fill to force capping
        engine.processing_history = [{"mock": i} for i in range(98)]
        for _ in range(5):
            engine.process_task("task")

        assert len(engine.processing_history) <= 100


# ============================================================================
# Section 14: _wrap_invoke_agent
# ============================================================================


class TestWrapInvokeAgent:
    """Tests for the _wrap_invoke_agent wrapper."""

    def test_no_invoke_returns_mock_response(self):
        engine = HybridSwarmEngine(invoke_agent=None)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("gemini", "brainstorm", "context")
        assert isinstance(response, AgentResponse)
        assert response.agent_id == "gemini"
        assert response.status == "mock"

    def test_string_response_wrapped(self):
        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            return "Hello from agent"

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("claude", "brainstorm", "ctx")
        assert isinstance(response, AgentResponse)
        assert response.content == "Hello from agent"
        assert response.status == "success"

    def test_error_string_detected(self):
        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            return "Error: connection refused"

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("gemini", "brainstorm", "ctx")
        assert response.status == "error"
        assert response.error is not None

    def test_timeout_string_detected(self):
        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            return "Agent timed out after 30 seconds"

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("gemini", "brainstorm", "ctx")
        assert response.status == "error"

    def test_dict_response_wrapped(self):
        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            return {"content": "dict result", "status": "success", "tokens_used": 100}

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("claude", "brainstorm", "ctx")
        assert response.content == "dict result"
        assert response.tokens_used == 100

    def test_agent_response_passthrough(self):
        expected = AgentResponse(agent_id="test", content="direct", status="ok")

        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            return expected

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("test", "brainstorm", "ctx")
        assert response is expected

    def test_expert_complexity_injects_cot(self):
        contexts_received = []

        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            contexts_received.append(context)
            return "done"

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        engine._current_analysis = _make_analysis(complexity=TaskComplexity.EXPERT)
        wrapper = engine._wrap_invoke_agent()
        wrapper("claude", "brainstorm", "original context")
        assert "<thinking>" in contexts_received[0]

    def test_non_expert_no_cot_injection(self):
        contexts_received = []

        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            contexts_received.append(context)
            return "done"

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        engine._current_analysis = _make_analysis(complexity=TaskComplexity.MODERATE)
        wrapper = engine._wrap_invoke_agent()
        wrapper("claude", "brainstorm", "original context")
        assert "<thinking>" not in contexts_received[0]

    def test_unknown_response_type_stringified(self):
        def fake_invoke(agent_id, task_type, context, session_uuid=None, isolated_env=None):
            return 42  # unexpected type

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        wrapper = engine._wrap_invoke_agent()
        response = wrapper("gemini", "brainstorm", "ctx")
        assert response.content == "42"
        assert response.status == "success"


# ============================================================================
# Section 15: _invoke_for_negotiation
# ============================================================================


class TestInvokeForNegotiation:
    """Tests for the _invoke_for_negotiation method."""

    def test_no_invoke_returns_mock(self):
        engine = HybridSwarmEngine(invoke_agent=None)
        result = engine._invoke_for_negotiation("gemini", "negotiation", "ctx")
        assert "Mock" in result
        assert "gemini" in result

    def test_string_response_returned_directly(self):
        def fake_invoke(agent_id, task_type, context):
            return "I agree with the proposal"

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        result = engine._invoke_for_negotiation("claude", "negotiation", "ctx")
        assert result == "I agree with the proposal"

    def test_object_with_content_attr(self):
        class FakeResponse:
            content = "content attribute response"

        def fake_invoke(agent_id, task_type, context):
            return FakeResponse()

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        result = engine._invoke_for_negotiation("gemini", "negotiation", "ctx")
        assert result == "content attribute response"

    def test_other_types_stringified(self):
        def fake_invoke(agent_id, task_type, context):
            return {"key": "value"}

        engine = HybridSwarmEngine(invoke_agent=fake_invoke)
        result = engine._invoke_for_negotiation("gemini", "negotiation", "ctx")
        assert "key" in result


# ============================================================================
# Section 16: Reset and stats
# ============================================================================


class TestResetAndStats:
    """Tests for reset() and get_stats() methods."""

    def test_reset_clears_state(self):
        engine = HybridSwarmEngine()
        engine.current_phase = SwarmPhase.EXECUTING
        engine._current_analysis = _make_analysis()
        engine._current_proposal = _make_proposal()
        engine._negotiation_result = _make_negotiation_result()

        engine.reset()
        assert engine.current_phase == SwarmPhase.IDLE
        assert engine._current_analysis is None
        assert engine._current_proposal is None
        assert engine._negotiation_result is None

    def test_get_stats_empty(self):
        engine = HybridSwarmEngine()
        stats = engine.get_stats()
        assert stats["current_phase"] == "idle"
        assert stats["total_processed"] == 0
        assert stats["mode_distribution"] == {}

    def test_get_stats_with_history(self):
        engine = HybridSwarmEngine()
        engine.processing_history = [
            {"mode": "ping_pong", "complexity": "MODERATE", "total_time": 1.0, "status": "completed"},
            {"mode": "ping_pong", "complexity": "SIMPLE", "total_time": 0.5, "status": "completed"},
            {"mode": "parallel", "complexity": "COMPLEX", "total_time": 2.0, "status": "completed"},
        ]
        stats = engine.get_stats()
        assert stats["total_processed"] == 3
        assert stats["mode_distribution"]["ping_pong"] == 2
        assert stats["mode_distribution"]["parallel"] == 1

    def test_get_stats_includes_pool_stats(self):
        pool = create_default_pool()
        engine = HybridSwarmEngine(agent_pool=pool)
        stats = engine.get_stats()
        assert "agent_pool_stats" in stats
        assert stats["agent_pool_stats"]["agents"] >= 2

    def test_get_stats_includes_spawned_count(self):
        engine = HybridSwarmEngine()
        stats = engine.get_stats()
        assert "spawned_agents_count" in stats
        assert stats["spawned_agents_count"] == 0


# ============================================================================
# Section 17: Spawned agent support
# ============================================================================


class TestSpawnedAgentSupport:
    """Tests for spawned agent discovery and suggestion logic."""

    def test_should_suggest_spawning_trivial_returns_false(self):
        engine = HybridSwarmEngine()
        analysis = _make_analysis(complexity=TaskComplexity.TRIVIAL)
        assert engine.should_suggest_spawning(analysis) is False

    def test_should_suggest_spawning_simple_returns_false(self):
        engine = HybridSwarmEngine()
        analysis = _make_analysis(complexity=TaskComplexity.SIMPLE)
        assert engine.should_suggest_spawning(analysis) is False

    def test_should_suggest_spawning_complex_no_spawned_returns_true(self):
        engine = HybridSwarmEngine()
        analysis = _make_analysis(complexity=TaskComplexity.COMPLEX)
        assert engine.should_suggest_spawning(analysis) is True

    def test_should_suggest_spawning_expert_returns_true(self):
        engine = HybridSwarmEngine()
        analysis = _make_analysis(complexity=TaskComplexity.EXPERT)
        assert engine.should_suggest_spawning(analysis) is True

    def test_should_suggest_spawning_covered_domains_returns_false(self):
        pool = AgentPool()
        pool.register(AgentProfile(agent_id="gemini_primary", provider="gemini", model="m"))
        pool.register(
            AgentProfile(agent_id="coding_specialist", provider="spawned", model="m", capabilities=["coding"])
        )
        engine = HybridSwarmEngine(agent_pool=pool)

        analysis = _make_analysis(
            complexity=TaskComplexity.COMPLEX,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
        )
        assert engine.should_suggest_spawning(analysis) is False

    def test_get_spawning_suggestion_returns_dict(self):
        engine = HybridSwarmEngine()
        analysis = _make_analysis(complexity=TaskComplexity.COMPLEX)
        suggestion = engine.get_spawning_suggestion(analysis)
        assert suggestion is not None
        assert "command" in suggestion
        assert "reason" in suggestion
        assert suggestion["suggested"] is True

    def test_get_spawning_suggestion_returns_none_for_trivial(self):
        engine = HybridSwarmEngine()
        analysis = _make_analysis(complexity=TaskComplexity.TRIVIAL)
        assert engine.get_spawning_suggestion(analysis) is None

    def test_count_spawned_agents_empty(self):
        engine = HybridSwarmEngine()
        assert engine._count_spawned_agents() == 0

    def test_count_spawned_agents_with_spawned(self):
        pool = AgentPool()
        pool.register(AgentProfile(agent_id="internal", provider="gemini", model="m"))
        pool.register(AgentProfile(agent_id="spawned1", provider="spawned", model="m"))
        pool.register(AgentProfile(agent_id="spawned2", provider="spawned", model="m"))
        engine = HybridSwarmEngine(agent_pool=pool)
        assert engine._count_spawned_agents() == 2

    def test_get_spawned_agents_filters_correctly(self):
        pool = AgentPool()
        pool.register(AgentProfile(agent_id="internal", provider="claude", model="m"))
        pool.register(AgentProfile(agent_id="spawned1", provider="spawned", model="m"))
        engine = HybridSwarmEngine(agent_pool=pool)
        spawned = engine._get_spawned_agents()
        assert len(spawned) == 1
        assert spawned[0].agent_id == "spawned1"


# ============================================================================
# Section 18: FSM integration public API
# ============================================================================


class TestFSMIntegrationAPI:
    """Tests for the public API methods used by FSM (start_analysis, etc.)."""

    def test_start_analysis_returns_analysis(self):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        expected = _make_analysis()
        engine.task_analyzer.analyze.return_value = expected

        result = engine.start_analysis("test input")
        assert result is expected
        assert engine._current_analysis is expected

    def test_get_analysis_returns_stored(self):
        engine = HybridSwarmEngine()
        engine._current_analysis = _make_analysis()
        assert engine.get_analysis() is engine._current_analysis

    def test_get_analysis_returns_none_initially(self):
        engine = HybridSwarmEngine()
        assert engine.get_analysis() is None

    def test_start_selection_returns_proposal(self):
        engine = HybridSwarmEngine()
        engine._current_analysis = _make_analysis()
        engine.mode_selector = MagicMock()
        expected = _make_proposal()
        engine.mode_selector.select_mode.return_value = expected

        result = engine.start_selection()
        assert result is expected
        assert engine._current_proposal is expected

    def test_start_negotiation_returns_none_without_proposal(self):
        engine = HybridSwarmEngine()
        engine._current_analysis = _make_analysis()
        engine._current_proposal = None

        result = engine.start_negotiation()
        assert result is None

    def test_start_negotiation_returns_none_without_analysis(self):
        engine = HybridSwarmEngine()
        engine._current_analysis = None
        engine._current_proposal = None

        result = engine.start_negotiation()
        assert result is None

    def test_process_negotiation_turn_returns_stored(self):
        engine = HybridSwarmEngine()
        neg = _make_negotiation_result()
        engine._negotiation_result = neg
        assert engine.process_negotiation_turn() is neg

    def test_process_negotiation_turn_returns_none_initially(self):
        engine = HybridSwarmEngine()
        assert engine.process_negotiation_turn() is None

    def test_execute_turn_uses_proposal_mode(self):
        engine = HybridSwarmEngine()
        engine._current_proposal = _make_proposal(mode=CollaborationMode.SEQUENTIAL)

        with patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor") as mock_get:
            mock_get.return_value.execute.return_value = _make_execution_result()
            engine.execute_turn("task")
            mock_get.assert_called_with(CollaborationMode.SEQUENTIAL)

    def test_execute_turn_prefers_negotiation_consensus(self):
        engine = HybridSwarmEngine()
        engine._current_proposal = _make_proposal(mode=CollaborationMode.SEQUENTIAL)
        engine._negotiation_result = _make_negotiation_result(
            status=NegotiationStatus.CONSENSUS,
            mode=CollaborationMode.RED_BLUE,
        )

        with patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor") as mock_get:
            mock_get.return_value.execute.return_value = _make_execution_result()
            engine.execute_turn("task")
            mock_get.assert_called_with(CollaborationMode.RED_BLUE)

    def test_execute_turn_force_cot_for_expert(self):
        engine = HybridSwarmEngine()
        engine._current_analysis = _make_analysis(complexity=TaskComplexity.EXPERT)
        engine._current_proposal = _make_proposal()

        with patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor") as mock_get:
            mock_get.return_value.execute.return_value = _make_execution_result()
            engine.execute_turn("task")
            ctx = mock_get.return_value.execute.call_args[0][0]
            assert ctx.force_cot is True


# ============================================================================
# Section 19: Callbacks
# ============================================================================


class TestCallbacks:
    """Tests for on_negotiation_turn and on_execution_round callbacks."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_on_execution_round_passed_to_context(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        callback = MagicMock()
        engine.process_task("task", on_execution_round=callback)

        ctx = mock_executor.execute_with_fallback.call_args[0][0]
        assert ctx.on_round is callback

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_on_negotiation_turn_passed_to_negotiation(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        callback = MagicMock()
        engine.process_task("task", on_negotiation_turn=callback)

        call_kwargs = engine.negotiation.run_negotiation.call_args
        assert (
            call_kwargs.kwargs.get("on_turn") is callback
            or (len(call_kwargs.args) >= 4 and call_kwargs.args[3] is callback)
            or call_kwargs[1].get("on_turn") is callback
        )


# ============================================================================
# Section 20: Success memory integration
# ============================================================================


class TestSuccessMemoryIntegration:
    """Tests for SuccessMemory recording after task completion."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_success_memory_record_called_on_completed(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result(status=ExecutionStatus.COMPLETED)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        mock_memory = MagicMock()
        engine.success_memory = mock_memory

        engine.process_task("Do something")
        mock_memory.record_success.assert_called_once()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_success_memory_not_called_on_failed(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result(status=ExecutionStatus.FAILED)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        mock_memory = MagicMock()
        engine.success_memory = mock_memory

        engine.process_task("Do something")
        mock_memory.record_success.assert_not_called()

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_success_memory_error_swallowed(self, mock_get_exec):
        """SuccessMemory errors should be logged but not crash the pipeline."""
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result(status=ExecutionStatus.COMPLETED)
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        mock_memory = MagicMock()
        mock_memory.record_success.side_effect = Exception("DB error")
        engine.success_memory = mock_memory

        result = engine.process_task("Do something")
        assert result.status == SwarmPhase.COMPLETED  # Should not fail


# ============================================================================
# Section 21: Adaptive max rounds
# ============================================================================


class TestAdaptiveMaxRounds:
    """Tests that adaptive max_rounds scales with task complexity."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_adaptive_max_rounds")
    def test_adaptive_rounds_called_when_no_config(self, mock_adaptive, mock_get_exec):
        mock_adaptive.return_value = 10

        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis(complexity=TaskComplexity.EXPERT)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("Complex task")
        mock_adaptive.assert_called_once_with(TaskComplexity.EXPERT)

        ctx = mock_executor.execute_with_fallback.call_args[0][0]
        assert ctx.max_rounds == 10

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_config_max_rounds_overrides_adaptive(self, mock_get_exec):
        config = MagicMock()
        config.swarm_max_rounds = 3
        config.swarm_negotiation_enabled = True
        config.swarm_negotiation_max_turns = 4
        config.swarm_skip_trivial = True
        config.swarm_self_healing = True
        config.swarm_max_fallbacks = 2

        engine = HybridSwarmEngine(config=config)
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis()
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_executor = MagicMock()
        mock_executor.execute_with_fallback.return_value = exec_result
        mock_get_exec.return_value = mock_executor

        engine.process_task("Task")
        ctx = mock_executor.execute_with_fallback.call_args[0][0]
        assert ctx.max_rounds == 3


# ============================================================================
# Section 22: Spawning suggestion in result metadata
# ============================================================================


class TestSpawningSuggestionInResult:
    """Tests that spawning suggestion is attached to result metadata."""

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_spawning_suggestion_added_to_metadata(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis(complexity=TaskComplexity.COMPLEX)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Complex coding task")
        assert "spawning_suggestion" in result.execution_result.metadata

    @patch("core.intelligence.swarm.hybrid_swarm_engine.get_executor")
    def test_no_spawning_suggestion_for_simple(self, mock_get_exec):
        engine = HybridSwarmEngine()
        engine.task_analyzer = MagicMock()
        engine.task_analyzer.analyze.return_value = _make_analysis(complexity=TaskComplexity.SIMPLE)
        engine.mode_selector = MagicMock()
        engine.mode_selector.select_mode.return_value = _make_proposal()
        engine.negotiation = MagicMock()
        engine.negotiation.run_negotiation.return_value = _make_negotiation_result()

        exec_result = _make_execution_result()
        mock_get_exec.return_value.execute_with_fallback.return_value = exec_result

        result = engine.process_task("Simple task")
        assert "spawning_suggestion" not in result.execution_result.metadata
