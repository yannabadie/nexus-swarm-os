"""
Comprehensive tests for TrueHiveMind orchestrator.

Tests the 7-phase HiveMind pipeline: Analysis -> Debate -> Architecture ->
Execution -> Diagnosis -> Retry -> Consolidation.

Covers:
- HiveMindResult dataclass
- TrueHiveMind constructor and initialization
- Phase ordering and transitions
- Gating logic
- State management (HiveMindState transitions)
- Error handling per phase
- Phase skip logic (skip debate if agreement, skip retry if success)
- process_task() main flow with mocked phases
- Budget tracking across phases
- SwarmBridge delegation
- Recovery and retry logic
- Edge cases: phase failures, budget exceeded, user cancellation
"""

import logging
import sys
import time
from pathlib import Path
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

import pytest

# ---------------------------------------------------------------------------
# Project root on path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
from core.intelligence.hive_mind.adaptive_debate import TaskComplexity
from core.intelligence.hive_mind.confidence_monitor import (
    AbortRecommendation,
    ConfidenceTrajectory,
)
from core.intelligence.hive_mind.orchestrator import HiveMindResult, TrueHiveMind
from core.intelligence.hive_mind.phases.phase_analysis import AnalysisPhaseResult
from core.intelligence.hive_mind.phases.phase_architecture import ArchitecturePhaseResult
from core.intelligence.hive_mind.phases.phase_consolidation import ConsolidationPhaseResult
from core.intelligence.hive_mind.phases.phase_debate import DebatePhaseResult
from core.intelligence.hive_mind.phases.phase_diagnosis import DiagnosisPhaseResult
from core.intelligence.hive_mind.phases.phase_execution import ExecutionPhaseResult
from core.intelligence.hive_mind.phases.phase_retry import RetryPhaseResult
from core.intelligence.hive_mind.types import (
    AgentArchitecture,
    AnalysisComparison,
    DebateArgument,
    DebateResult,
    ExecutionPlan,
    FailureDiagnosis,
    FailureType,
    HiveMindState,
    IndependentAnalysis,
    KnowledgeConsolidation,
    MonitoredStepResult,
    RAGConfig,
    RetryDecision,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# Helpers / Factories
# ===========================================================================


def _make_independent_analysis(agent_id: str = "gemini", confidence: float = 0.9) -> IndependentAnalysis:
    """Create a minimal IndependentAnalysis for testing."""
    return IndependentAnalysis(
        agent_id=agent_id,
        task_understanding="Test task understanding",
        complexity_assessment="MODERATE",
        proposed_approach="Approach A",
        required_capabilities=["coding"],
        potential_risks=["risk_a"],
        confidence=confidence,
        reasoning="Test reasoning",
    )


def _make_analysis_comparison(
    agreement_score: float = 0.9,
    needs_debate: bool = False,
) -> AnalysisComparison:
    """Create a minimal AnalysisComparison."""
    gemini = _make_independent_analysis("gemini", 0.9)
    claude = _make_independent_analysis("claude", 0.88)
    return AnalysisComparison(
        gemini_analysis=gemini,
        claude_analysis=claude,
        disagreements=[],
        agreement_score=agreement_score,
        needs_debate=needs_debate,
        merged_capabilities=["coding"],
        merged_risks=["risk_a"],
    )


def _make_debate_result(
    status: str = "IMMEDIATE_CONSENSUS",
    consensus_confidence: float = 0.92,
) -> DebateResult:
    """Create a minimal DebateResult."""
    return DebateResult(
        status=status,
        final_approach="Agreed approach",
        final_capabilities=["coding"],
        final_mode="SPECIALIST",
        debate_history=[],
        total_turns=0,
        resolved_disagreements=[],
        unresolved_disagreements=[],
        consensus_confidence=consensus_confidence,
        gemini_satisfaction=0.8,
        claude_satisfaction=0.8,
    )


def _make_architecture(
    agents_to_use: list[str] | None = None,
    status: str = "READY",
) -> AgentArchitecture:
    """Create a minimal AgentArchitecture."""
    return AgentArchitecture(
        status=status,
        collaboration_mode="SPECIALIST",
        agents_to_use=agents_to_use or ["gemini", "claude"],
        agents_to_spawn=[],
        rag_config=RAGConfig(),
        execution_plan=ExecutionPlan(strategy="sequential"),
        reasoning="Test arch reasoning",
    )


def _make_step_result(
    step_name: str = "step_1",
    status: str = "success",
) -> MonitoredStepResult:
    """Create a minimal step result."""
    return MonitoredStepResult(
        step_name=step_name,
        agent_id="gemini",
        status=status,
        output="Step output",
        duration=1.0,
        expected_duration=5.0,
        tokens_used=100,
    )


def _make_knowledge_consolidation(
    confidence_in_decisions: float = 0.85,
    task_success: bool = True,
) -> KnowledgeConsolidation:
    """Create a minimal KnowledgeConsolidation."""
    return KnowledgeConsolidation(
        learned_patterns=["Pattern 1"],
        learned_antipatterns=["Antipattern 1"],
        new_capabilities_identified=[],
        agents_retention=[],
        knowledge_to_archive=[],
        tools_to_create=[],
        nexus_improvements=[],
        task_success=task_success,
        confidence_in_decisions=confidence_in_decisions,
        gemini_reflection="Gemini reflection",
        claude_reflection="Claude reflection",
    )


def _make_failure_diagnosis(
    failure_type: FailureType = FailureType.TOOL_ERROR,
    confidence: float = 0.75,
) -> FailureDiagnosis:
    """Create a minimal FailureDiagnosis."""
    return FailureDiagnosis(
        failure_type=failure_type,
        root_cause="Tool failed",
        contributing_factors=["factor_a"],
        evidence=["evidence_a"],
        recommended_changes=["fix_a"],
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Analysis phase result that indicates no debate needed
# ---------------------------------------------------------------------------
def _make_analysis_phase_result(needs_debate: bool = False) -> AnalysisPhaseResult:
    comparison = _make_analysis_comparison(
        agreement_score=0.92 if not needs_debate else 0.5,
        needs_debate=needs_debate,
    )
    return AnalysisPhaseResult(
        gemini_analysis=comparison.gemini_analysis,
        claude_analysis=comparison.claude_analysis,
        comparison=comparison,
        needs_debate=needs_debate,
        skip_reason="High agreement" if not needs_debate else None,
    )


def _make_debate_phase_result(was_skipped: bool = True) -> DebatePhaseResult:
    return DebatePhaseResult(
        debate_result=_make_debate_result(),
        final_approach="Agreed approach",
        final_capabilities=["coding"],
        final_mode="SPECIALIST",
        was_skipped=was_skipped,
        skip_reason="High agreement" if was_skipped else None,
    )


def _make_arch_phase_result(agents_spawned: list[str] | None = None) -> ArchitecturePhaseResult:
    return ArchitecturePhaseResult(
        architecture=_make_architecture(),
        agents_spawned=agents_spawned or [],
        user_approved_spawn=True,
    )


def _make_exec_phase_result(
    success: bool = True,
    needs_diagnosis: bool = False,
    failure_step: str | None = None,
) -> ExecutionPhaseResult:
    return ExecutionPhaseResult(
        success=success,
        step_results=[_make_step_result()],
        total_duration=2.0,
        total_tokens=200,
        issues=[],
        artifacts_created=["file.py"] if success else [],
        needs_diagnosis=needs_diagnosis,
        failure_step=failure_step,
    )


def _make_diagnosis_phase_result(
    user_decision: str = "retry",
) -> DiagnosisPhaseResult:
    return DiagnosisPhaseResult(
        diagnosis=_make_failure_diagnosis(),
        gemini_diagnosis="Gemini diag",
        claude_diagnosis="Claude diag",
        user_decision=user_decision,
    )


def _make_retry_phase_result(
    action: str = "RETRY",
    modified_arch: AgentArchitecture | None = None,
) -> RetryPhaseResult:
    return RetryPhaseResult(
        decision=RetryDecision(
            action=action,
            reason="Test retry reason",
        ),
        modified_architecture=modified_arch,
        retry_count=1,
        blacklisted=False,
    )


def _make_consolidation_phase_result(archived: int = 3) -> ConsolidationPhaseResult:
    return ConsolidationPhaseResult(
        consolidation=_make_knowledge_consolidation(),
        gemini_reflection="Gemini reflection",
        claude_reflection="Claude reflection",
        user_decision="accept",
        archived_to_rag=archived,
        agents_retained=[],
        agents_deleted=[],
    )


# ===========================================================================
# Fixture: fully mocked TrueHiveMind instance
# ===========================================================================


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory with required subdirs."""
    nexus_dir = tmp_path / ".nexus"
    nexus_dir.mkdir()
    sagas_dir = nexus_dir / "sagas"
    sagas_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_config():
    """Create a mock config object."""
    cfg = MagicMock()
    cfg.hive_mind_budget_limit = 50000
    cfg.hive_mind_breakpoint_timeout = 60
    return cfg


@pytest.fixture
def mock_gemini():
    return MagicMock(name="GeminiDriver")


@pytest.fixture
def mock_claude():
    return MagicMock(name="ClaudeDriver")


@pytest.fixture
def hive_mind(tmp_workspace, mock_config, mock_gemini, mock_claude):
    """Create a TrueHiveMind with all external deps mocked.

    Uses patch context managers to prevent side effects from _init_components
    reaching out to real singletons.
    """
    with (
        patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge") as mock_sync,
        patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge") as mock_telem,
        patch("core.intelligence.hive_mind.orchestrator.StagnationDetector") as mock_stag_cls,
    ):
        mock_sync_inst = MagicMock()
        mock_sync.return_value = mock_sync_inst

        mock_telem_inst = MagicMock()
        mock_telem_inst.emit = AsyncMock()
        mock_telem_inst.emit_sync = MagicMock()
        mock_telem_inst.start_trace = MagicMock(return_value="trace-001")
        mock_telem_inst.end_trace = MagicMock()
        mock_telem.return_value = mock_telem_inst

        mock_stag = MagicMock()
        mock_stag.get_swap_recommendation.return_value = {
            "should_swap": False,
            "new_lead": None,
            "reason": "No swap needed",
        }
        mock_stag.get_stats.return_value = {}
        mock_stag_cls.return_value = mock_stag

        hm = TrueHiveMind(
            workspace_path=tmp_workspace,
            config=mock_config,
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            saga_enabled=False,
        )

        # Expose mocks for assertions
        hm._mock_sync = mock_sync_inst
        hm._mock_telem = mock_telem_inst
        hm._mock_stag = mock_stag

        yield hm


# ---------------------------------------------------------------------------
# Helper to run process_task with all phases mocked
# ---------------------------------------------------------------------------


def _wire_happy_path(hm: TrueHiveMind) -> dict[str, MagicMock]:
    """Wire all phases for a successful happy-path execution.

    Returns dict of mocked phases for assertion.
    """
    analysis = _make_analysis_phase_result(needs_debate=False)
    debate_skipped = _make_debate_phase_result(was_skipped=True)
    arch = _make_arch_phase_result()
    execution = _make_exec_phase_result(success=True)
    consolidation = _make_consolidation_phase_result()

    hm.phase_analysis.execute = AsyncMock(return_value=analysis)
    hm.phase_debate._create_skipped_result = MagicMock(return_value=debate_skipped)
    hm.phase_architecture.execute = AsyncMock(return_value=arch)
    hm.phase_execution.execute = AsyncMock(return_value=execution)
    hm.phase_consolidation.execute = AsyncMock(return_value=consolidation)
    hm.phase_retry.reset_retry_count = MagicMock()
    hm.phase_retry.mark_success = MagicMock()

    # Mock cost estimator
    hm.cost_estimator.start_task = MagicMock()
    hm.cost_estimator.spent = 1000
    hm.cost_estimator.estimate_full_hive_mind = MagicMock(return_value=5000)
    hm.cost_estimator.tokens_to_usd = MagicMock(return_value=0.015)
    hm.cost_estimator.check_usd_budget = MagicMock(return_value=True)

    # Mock context manager
    hm.context_manager.clear = MagicMock()
    hm.context_manager._items = []
    hm.context_manager.archive_to_rag = MagicMock(return_value=3)

    # Mock confidence monitor
    hm.confidence_monitor.reset = MagicMock()
    hm.confidence_monitor.record = MagicMock()
    hm.confidence_monitor.should_abort = MagicMock(
        return_value=AbortRecommendation(
            should_abort=False,
            reason="OK",
            confidence=0.85,
            threshold=0.30,
        )
    )
    hm.confidence_monitor.get_trajectory = MagicMock(
        return_value=ConfidenceTrajectory(
            entries=[],
            trend="stable",
            average=0.85,
            minimum=0.80,
            maximum=0.92,
            latest=0.85,
            drop_detected=False,
        )
    )

    # Mock budget allocator
    hm.budget_allocator.reset = MagicMock()
    hm.budget_allocator.allocate = MagicMock(return_value={"execution": 17500})
    hm.budget_allocator.report_actual = MagicMock()
    hm.budget_allocator.get_stats = MagicMock(
        return_value={
            "total_spent": 1000,
            "redistributed": 0,
            "utilization": 0.02,
        }
    )

    # Mock phase audit logger
    with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_audit:
        audit_inst = MagicMock()
        audit_inst.detect_patterns.return_value = []
        mock_audit.return_value = audit_inst
        hm._phase_audit_mock = (mock_audit, audit_inst)

    return {
        "analysis": analysis,
        "debate_skipped": debate_skipped,
        "arch": arch,
        "execution": execution,
        "consolidation": consolidation,
    }


# ===========================================================================
# SECTION 1: HiveMindResult dataclass
# ===========================================================================


class TestHiveMindResult:
    """Tests for the HiveMindResult dataclass."""

    def test_create_success_result(self):
        result = HiveMindResult(
            success=True,
            output="Task completed",
            state=HiveMindState.HIVE_SUCCESS,
            phases_completed=[
                "analysis",
                "debate_skipped",
                "architecture",
                "execution_success_attempt_1",
                "consolidation",
            ],
            total_duration=10.5,
            total_tokens=5000,
            agents_used=["gemini", "claude"],
            agents_spawned=[],
            artifacts_created=["file.py"],
            knowledge_archived=3,
        )
        assert result.success is True
        assert result.error is None
        assert result.state == HiveMindState.HIVE_SUCCESS
        assert len(result.phases_completed) == 5
        assert result.total_tokens == 5000
        assert result.total_duration == 10.5

    def test_create_failed_result(self):
        result = HiveMindResult(
            success=False,
            output="Task failed: timeout",
            state=HiveMindState.HIVE_FAILED,
            phases_completed=["analysis"],
            total_duration=60.0,
            total_tokens=1000,
            agents_used=[],
            agents_spawned=[],
            artifacts_created=[],
            knowledge_archived=0,
            error="Timeout during execution",
        )
        assert result.success is False
        assert result.error == "Timeout during execution"
        assert result.state == HiveMindState.HIVE_FAILED

    def test_default_error_is_none(self):
        result = HiveMindResult(
            success=True,
            output="ok",
            state=HiveMindState.HIVE_SUCCESS,
            phases_completed=[],
            total_duration=0,
            total_tokens=0,
            agents_used=[],
            agents_spawned=[],
            artifacts_created=[],
            knowledge_archived=0,
        )
        assert result.error is None

    def test_escalated_result(self):
        result = HiveMindResult(
            success=False,
            output="Cancelled",
            state=HiveMindState.HIVE_ESCALATE,
            phases_completed=["analysis", "debate"],
            total_duration=5.0,
            total_tokens=800,
            agents_used=[],
            agents_spawned=[],
            artifacts_created=[],
            knowledge_archived=0,
            error="User cancelled",
        )
        assert result.state == HiveMindState.HIVE_ESCALATE

    def test_agents_spawned_populated(self):
        result = HiveMindResult(
            success=True,
            output="ok",
            state=HiveMindState.HIVE_SUCCESS,
            phases_completed=[],
            total_duration=0,
            total_tokens=0,
            agents_used=["gemini"],
            agents_spawned=["specialist_1"],
            artifacts_created=[],
            knowledge_archived=0,
        )
        assert result.agents_spawned == ["specialist_1"]


# ===========================================================================
# SECTION 2: TrueHiveMind construction & initialization
# ===========================================================================


class TestTrueHiveMindInit:
    """Tests for constructor and _init_components."""

    def test_initial_state_is_gating(self, hive_mind):
        assert hive_mind.state == HiveMindState.HIVE_GATING

    def test_workspace_path_stored(self, hive_mind, tmp_workspace):
        assert hive_mind.workspace_path == tmp_workspace

    def test_drivers_stored(self, hive_mind, mock_gemini, mock_claude):
        assert hive_mind.gemini is mock_gemini
        assert hive_mind.claude is mock_claude

    def test_default_lead_is_gemini(self, hive_mind):
        assert hive_mind._current_lead == "gemini"

    def test_lead_swap_count_starts_at_zero(self, hive_mind):
        assert hive_mind._lead_swap_count == 0

    def test_saga_disabled_when_requested(self, hive_mind):
        assert hive_mind.saga_enabled is False
        assert hive_mind._saga is None

    def test_all_phases_initialized(self, hive_mind):
        assert hive_mind.phase_analysis is not None
        assert hive_mind.phase_debate is not None
        assert hive_mind.phase_architecture is not None
        assert hive_mind.phase_execution is not None
        assert hive_mind.phase_diagnosis is not None
        assert hive_mind.phase_retry is not None
        assert hive_mind.phase_consolidation is not None

    def test_cost_estimator_initialized(self, hive_mind):
        assert hive_mind.cost_estimator is not None

    def test_context_manager_initialized(self, hive_mind):
        assert hive_mind.context_manager is not None

    def test_confidence_monitor_initialized(self, hive_mind):
        assert hive_mind.confidence_monitor is not None

    def test_budget_allocator_initialized(self, hive_mind):
        assert hive_mind.budget_allocator is not None

    def test_auto_breakpoints_default_true(self, tmp_workspace, mock_config, mock_gemini, mock_claude):
        with (
            patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.StagnationDetector"),
        ):
            hm = TrueHiveMind(
                workspace_path=tmp_workspace,
                config=mock_config,
                gemini_driver=mock_gemini,
                claude_driver=mock_claude,
                saga_enabled=False,
            )
            assert hm.auto_breakpoints is True

    def test_optional_params_none_by_default(self, hive_mind):
        assert hive_mind.agent_pool is None
        assert hive_mind.budget_tracker is None
        assert hive_mind.project_memory is None
        assert hive_mind.success_memory is None

    def test_swarm_engine_stored_when_provided(self, tmp_workspace, mock_config, mock_gemini, mock_claude):
        mock_swarm = MagicMock()
        mock_swarm.session_manager = MagicMock()
        with (
            patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.StagnationDetector"),
        ):
            hm = TrueHiveMind(
                workspace_path=tmp_workspace,
                config=mock_config,
                gemini_driver=mock_gemini,
                claude_driver=mock_claude,
                swarm_engine=mock_swarm,
                saga_enabled=False,
            )
            assert hm.swarm_engine is mock_swarm

    def test_on_state_change_callback_stored(self, tmp_workspace, mock_config, mock_gemini, mock_claude):
        cb = MagicMock()
        with (
            patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.StagnationDetector"),
        ):
            hm = TrueHiveMind(
                workspace_path=tmp_workspace,
                config=mock_config,
                gemini_driver=mock_gemini,
                claude_driver=mock_claude,
                on_state_change=cb,
                saga_enabled=False,
            )
            assert hm.on_state_change is cb


# ===========================================================================
# SECTION 3: State management
# ===========================================================================


class TestStateManagement:
    """Tests for _set_state and state tracking."""

    def test_set_state_updates_current_state(self, hive_mind):
        hive_mind._set_state(HiveMindState.HIVE_ANALYZING_GEMINI)
        assert hive_mind.state == HiveMindState.HIVE_ANALYZING_GEMINI

    def test_set_state_calls_callback(self, hive_mind):
        cb = MagicMock()
        hive_mind.on_state_change = cb
        old = hive_mind.state
        hive_mind._set_state(HiveMindState.HIVE_DEBATING)
        cb.assert_called_once_with(old, HiveMindState.HIVE_DEBATING)

    def test_set_state_emits_telemetry(self, hive_mind):
        hive_mind._set_state(HiveMindState.HIVE_EXECUTING)
        hive_mind._mock_telem.emit_sync.assert_called()

    def test_set_state_no_callback_when_none(self, hive_mind):
        hive_mind.on_state_change = None
        # Should not raise
        hive_mind._set_state(HiveMindState.HIVE_REFLECTING)
        assert hive_mind.state == HiveMindState.HIVE_REFLECTING

    def test_sequential_state_transitions(self, hive_mind):
        states = [
            HiveMindState.HIVE_ANALYZING_GEMINI,
            HiveMindState.HIVE_DEBATING,
            HiveMindState.HIVE_ARCHITECTING,
            HiveMindState.HIVE_EXECUTING,
            HiveMindState.HIVE_REFLECTING,
            HiveMindState.HIVE_SUCCESS,
        ]
        for s in states:
            hive_mind._set_state(s)
            assert hive_mind.state == s


# ===========================================================================
# SECTION 4: get_stats
# ===========================================================================


class TestGetStats:
    """Tests for get_stats method."""

    def test_get_stats_returns_dict(self, hive_mind):
        stats = hive_mind.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_contains_expected_keys(self, hive_mind):
        stats = hive_mind.get_stats()
        assert "current_state" in stats
        assert "cost_stats" in stats
        assert "context_stats" in stats
        assert "registry_stats" in stats
        assert "blacklist_stats" in stats
        assert "debate_stats" in stats
        assert "hot_swap_stats" in stats

    def test_get_stats_hot_swap_section(self, hive_mind):
        stats = hive_mind.get_stats()
        hs = stats["hot_swap_stats"]
        assert hs["current_lead"] == "gemini"
        assert hs["swap_count"] == 0


# ===========================================================================
# SECTION 5: Hot-Swap Lead Agent
# ===========================================================================


class TestHotSwapLead:
    """Tests for _check_and_swap_lead and force_lead_swap."""

    def test_no_swap_when_not_stagnant(self, hive_mind):
        hive_mind._mock_stag.get_swap_recommendation.return_value = {
            "should_swap": False,
            "new_lead": None,
            "reason": "OK",
        }
        result = hive_mind._check_and_swap_lead("diagnosis text", _make_architecture())
        assert result["swapped"] is False

    def test_swap_when_stagnant(self, hive_mind):
        hive_mind._mock_stag.get_swap_recommendation.return_value = {
            "should_swap": True,
            "new_lead": "claude",
            "reason": "Stagnation detected",
        }
        result = hive_mind._check_and_swap_lead("diagnosis text", _make_architecture())
        assert result["swapped"] is True
        assert result["new_lead"] == "claude"
        assert hive_mind._current_lead == "claude"
        assert hive_mind._lead_swap_count == 1

    def test_swap_increments_counter(self, hive_mind):
        hive_mind._mock_stag.get_swap_recommendation.return_value = {
            "should_swap": True,
            "new_lead": "claude",
            "reason": "Stagnation",
        }
        hive_mind._check_and_swap_lead("diag1", _make_architecture())
        hive_mind._mock_stag.get_swap_recommendation.return_value = {
            "should_swap": True,
            "new_lead": "gemini",
            "reason": "Stagnation",
        }
        hive_mind._check_and_swap_lead("diag2", _make_architecture())
        assert hive_mind._lead_swap_count == 2

    def test_force_lead_swap_to_claude(self, hive_mind):
        result = hive_mind.force_lead_swap("claude")
        assert result["swapped"] is True
        assert result["new_lead"] == "claude"
        assert hive_mind._current_lead == "claude"

    def test_force_lead_swap_to_gemini(self, hive_mind):
        hive_mind._current_lead = "claude"
        result = hive_mind.force_lead_swap("gemini")
        assert result["swapped"] is True
        assert result["new_lead"] == "gemini"

    def test_force_lead_swap_invalid_agent(self, hive_mind):
        result = hive_mind.force_lead_swap("gpt4")
        assert result["swapped"] is False
        assert "error" in result

    def test_get_current_lead(self, hive_mind):
        assert hive_mind.get_current_lead() == "gemini"
        hive_mind._current_lead = "claude"
        assert hive_mind.get_current_lead() == "claude"


# ===========================================================================
# SECTION 6: _create_cancelled_result and _create_failed_result
# ===========================================================================


class TestResultHelpers:
    """Tests for _create_cancelled_result and _create_failed_result."""

    def test_cancelled_result_fields(self, hive_mind):
        hive_mind.cost_estimator = MagicMock()
        hive_mind.cost_estimator.spent = 500
        result = hive_mind._create_cancelled_result(
            phases_completed=["analysis", "debate"],
            start_time=time.time() - 5.0,
            reason="User cancelled",
        )
        assert result.success is False
        assert result.state == HiveMindState.HIVE_ESCALATE
        assert "User cancelled" in result.output
        assert result.error == "User cancelled"
        assert result.phases_completed == ["analysis", "debate"]

    def test_failed_result_fields(self, hive_mind):
        hive_mind.cost_estimator = MagicMock()
        hive_mind.cost_estimator.spent = 700
        exec_result = _make_exec_phase_result(success=False)
        result = hive_mind._create_failed_result(
            phases_completed=["analysis", "execution_failed_attempt_1"],
            start_time=time.time() - 10.0,
            error="Max retries exceeded",
            execution_result=exec_result,
        )
        assert result.success is False
        assert result.state == HiveMindState.HIVE_FAILED
        assert result.error == "Max retries exceeded"

    def test_failed_result_without_execution_result(self, hive_mind):
        hive_mind.cost_estimator = MagicMock()
        hive_mind.cost_estimator.spent = 100
        result = hive_mind._create_failed_result(
            phases_completed=["analysis"],
            start_time=time.time(),
            error="Budget exceeded",
            execution_result=None,
        )
        assert result.artifacts_created == []


# ===========================================================================
# SECTION 7: _format_output
# ===========================================================================


class TestFormatOutput:
    """Tests for _format_output."""

    def test_format_with_successful_execution(self, hive_mind):
        exec_result = _make_exec_phase_result(success=True)
        consol_result = _make_consolidation_phase_result()
        output = hive_mind._format_output(exec_result, consol_result)
        assert "Execution Results" in output

    def test_format_with_no_execution_result(self, hive_mind):
        consol_result = _make_consolidation_phase_result()
        output = hive_mind._format_output(None, consol_result)
        # When consolidation has patterns but no exec result
        assert "Learned Patterns" in output or output == "Task completed"

    def test_format_with_artifacts(self, hive_mind):
        exec_result = _make_exec_phase_result(success=True)
        exec_result.artifacts_created = ["api.py", "test_api.py"]
        consol_result = _make_consolidation_phase_result()
        output = hive_mind._format_output(exec_result, consol_result)
        assert "Artifacts Created" in output
        assert "api.py" in output

    def test_format_with_empty_results(self, hive_mind):
        exec_result = MagicMock()
        exec_result.step_results = []
        exec_result.artifacts_created = []
        consol_result = MagicMock()
        consol_result.consolidation.learned_patterns = []
        output = hive_mind._format_output(exec_result, consol_result)
        assert isinstance(output, str)


# ===========================================================================
# SECTION 8: process_task - happy path (no debate, first-attempt success)
# ===========================================================================


class TestProcessTaskHappyPath:
    """Tests for the full happy-path execution via process_task."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_success(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            audit_inst = MagicMock()
            audit_inst.detect_patterns.return_value = []
            mock_pal.return_value = audit_inst

            result = await hive_mind.process_task("Build an API endpoint")

        assert result.success is True
        assert result.state == HiveMindState.HIVE_SUCCESS

    @pytest.mark.asyncio
    async def test_happy_path_phases_completed(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Build API")

        assert "analysis" in result.phases_completed
        assert "debate_skipped" in result.phases_completed
        assert "architecture" in result.phases_completed
        assert any("execution_success" in p for p in result.phases_completed)
        assert "consolidation" in result.phases_completed

    @pytest.mark.asyncio
    async def test_happy_path_calls_analysis_phase(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        hive_mind.phase_analysis.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_skips_debate(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        hive_mind.phase_debate._create_skipped_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_happy_path_calls_architecture(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        hive_mind.phase_architecture.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_calls_execution(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        hive_mind.phase_execution.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_calls_consolidation(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        hive_mind.phase_consolidation.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_resets_retry_count(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        hive_mind.phase_retry.reset_retry_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_happy_path_agents_used(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Build API")

        assert "gemini" in result.agents_used
        assert "claude" in result.agents_used

    @pytest.mark.asyncio
    async def test_happy_path_total_tokens_populated(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Build API")

        assert result.total_tokens == 1000  # cost_estimator.spent

    @pytest.mark.asyncio
    async def test_happy_path_artifacts_from_execution(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Build API")

        assert "file.py" in result.artifacts_created

    @pytest.mark.asyncio
    async def test_happy_path_final_state_is_success(self, hive_mind):
        _wire_happy_path(hive_mind)
        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Build API")

        assert hive_mind.state == HiveMindState.HIVE_SUCCESS


# ===========================================================================
# SECTION 9: process_task - debate path
# ===========================================================================


class TestProcessTaskWithDebate:
    """Tests where analysis requires debate."""

    @pytest.mark.asyncio
    async def test_debate_executed_when_needed(self, hive_mind):
        """When analysis shows disagreement, debate phase is invoked."""
        _wire_happy_path(hive_mind)

        # Override analysis to require debate
        analysis = _make_analysis_phase_result(needs_debate=True)
        hive_mind.phase_analysis.execute = AsyncMock(return_value=analysis)

        debate = _make_debate_phase_result(was_skipped=False)
        hive_mind.phase_debate.execute = AsyncMock(return_value=debate)

        # Disable breakpoints to avoid user interaction
        hive_mind.auto_breakpoints = False

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Complex task")

        hive_mind.phase_debate.execute.assert_awaited_once()
        assert "debate" in result.phases_completed
        assert result.success is True

    @pytest.mark.asyncio
    async def test_debate_with_user_cancel(self, hive_mind):
        """When user cancels after debate, result is cancelled."""
        _wire_happy_path(hive_mind)

        analysis = _make_analysis_phase_result(needs_debate=True)
        hive_mind.phase_analysis.execute = AsyncMock(return_value=analysis)

        debate = _make_debate_phase_result(was_skipped=False)
        debate.debate_result.debate_history = [
            DebateArgument(
                agent_id="gemini",
                turn_number=1,
                position="SUPPORT",
                target_point="approach",
                argument="I agree",
                evidence=[],
            )
        ]
        hive_mind.phase_debate.execute = AsyncMock(return_value=debate)

        # User cancels at breakpoint
        hive_mind.auto_breakpoints = True
        cancel_response = MagicMock()
        cancel_response.chosen_option = "cancel"
        hive_mind.user_handler.after_debate = MagicMock(return_value=cancel_response)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Complex task")

        assert result.success is False
        assert result.state == HiveMindState.HIVE_ESCALATE
        assert "cancelled" in result.output.lower()


# ===========================================================================
# SECTION 10: process_task - execution failure -> diagnosis -> retry
# ===========================================================================


class TestProcessTaskRetryLoop:
    """Tests for the execution failure -> diagnosis -> retry loop."""

    @pytest.mark.asyncio
    async def test_execution_failure_triggers_diagnosis(self, hive_mind):
        """When execution fails with needs_diagnosis, Phase 5 is invoked."""
        _wire_happy_path(hive_mind)

        # First execution fails, second succeeds
        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=True,
            failure_step="step_1",
        )
        success_exec = _make_exec_phase_result(success=True)
        hive_mind.phase_execution.execute = AsyncMock(side_effect=[fail_exec, success_exec])

        diagnosis = _make_diagnosis_phase_result(user_decision="retry")
        hive_mind.phase_diagnosis = MagicMock()
        hive_mind.phase_diagnosis.execute = AsyncMock(return_value=diagnosis)
        hive_mind.phase_diagnosis.get_retry_recommendations = MagicMock(return_value={"recommendations": ["fix_x"]})

        retry = _make_retry_phase_result(action="RETRY", modified_arch=_make_architecture())
        hive_mind.phase_retry.execute = MagicMock(return_value=retry)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Failing task")

        hive_mind.phase_diagnosis.execute.assert_awaited_once()
        assert result.success is True
        assert any("execution_failed" in p for p in result.phases_completed)
        assert "diagnosis" in result.phases_completed

    @pytest.mark.asyncio
    async def test_user_abort_during_diagnosis(self, hive_mind):
        """When user chooses abort during diagnosis, task fails."""
        _wire_happy_path(hive_mind)

        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=True,
            failure_step="step_1",
        )
        hive_mind.phase_execution.execute = AsyncMock(return_value=fail_exec)

        diagnosis = _make_diagnosis_phase_result(user_decision="abort")
        hive_mind.phase_diagnosis = MagicMock()
        hive_mind.phase_diagnosis.execute = AsyncMock(return_value=diagnosis)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Task with abort")

        assert result.success is False
        assert "abort" in result.error.lower()

    @pytest.mark.asyncio
    async def test_user_escalate_during_diagnosis(self, hive_mind):
        """When user chooses escalate during diagnosis, task fails."""
        _wire_happy_path(hive_mind)

        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=True,
            failure_step="step_1",
        )
        hive_mind.phase_execution.execute = AsyncMock(return_value=fail_exec)

        diagnosis = _make_diagnosis_phase_result(user_decision="escalate")
        hive_mind.phase_diagnosis = MagicMock()
        hive_mind.phase_diagnosis.execute = AsyncMock(return_value=diagnosis)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Task with escalate")

        assert result.success is False
        assert "escalate" in result.error.lower()

    @pytest.mark.asyncio
    async def test_retry_action_stop_ends_loop(self, hive_mind):
        """When retry phase decides STOP, the loop ends with failure."""
        _wire_happy_path(hive_mind)

        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=True,
            failure_step="step_1",
        )
        hive_mind.phase_execution.execute = AsyncMock(return_value=fail_exec)

        diagnosis = _make_diagnosis_phase_result(user_decision="retry")
        hive_mind.phase_diagnosis = MagicMock()
        hive_mind.phase_diagnosis.execute = AsyncMock(return_value=diagnosis)
        hive_mind.phase_diagnosis.get_retry_recommendations = MagicMock(return_value={})

        retry = _make_retry_phase_result(action="STOP")
        hive_mind.phase_retry.execute = MagicMock(return_value=retry)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Failing task")

        assert result.success is False
        assert result.state == HiveMindState.HIVE_FAILED

    @pytest.mark.asyncio
    async def test_execution_fails_no_diagnosis_needed(self, hive_mind):
        """When execution fails but needs_diagnosis is False, loop exits."""
        _wire_happy_path(hive_mind)

        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=False,
        )
        hive_mind.phase_execution.execute = AsyncMock(return_value=fail_exec)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Task without diagnosis")

        # Should still reach consolidation but with success=False
        assert result.success is False
        assert "consolidation" in result.phases_completed

    @pytest.mark.asyncio
    async def test_max_retry_attempts_respected(self, hive_mind):
        """The execution loop runs at most 4 times (max_attempts)."""
        _wire_happy_path(hive_mind)

        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=True,
            failure_step="step_1",
        )
        # All 4 attempts fail
        hive_mind.phase_execution.execute = AsyncMock(return_value=fail_exec)

        diagnosis = _make_diagnosis_phase_result(user_decision="retry")
        hive_mind.phase_diagnosis = MagicMock()
        hive_mind.phase_diagnosis.execute = AsyncMock(return_value=diagnosis)
        hive_mind.phase_diagnosis.get_retry_recommendations = MagicMock(return_value={})

        retry = _make_retry_phase_result(action="RETRY", modified_arch=_make_architecture())
        hive_mind.phase_retry.execute = MagicMock(return_value=retry)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Persistent failure")

        # 4 attempts = 4 execution calls
        assert hive_mind.phase_execution.execute.await_count == 4
        # Task fails overall
        assert result.success is False


# ===========================================================================
# SECTION 11: process_task - exception handling
# ===========================================================================


class TestProcessTaskExceptionHandling:
    """Tests for exception handling in process_task."""

    @pytest.mark.asyncio
    async def test_exception_in_analysis_returns_failed_result(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.phase_analysis.execute = AsyncMock(side_effect=RuntimeError("Analysis exploded"))

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Boom")

        assert result.success is False
        assert result.state == HiveMindState.HIVE_FAILED
        assert "Analysis exploded" in result.error

    @pytest.mark.asyncio
    async def test_exception_in_execution_returns_failed_result(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.phase_execution.execute = AsyncMock(side_effect=ValueError("Execution crashed"))

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Crash test")

        assert result.success is False
        assert "Execution crashed" in result.error

    @pytest.mark.asyncio
    async def test_exception_in_consolidation_returns_failed_result(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.phase_consolidation.execute = AsyncMock(side_effect=Exception("Consolidation error"))

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Crash in consolidation")

        assert result.success is False
        assert "Consolidation error" in result.error

    @pytest.mark.asyncio
    async def test_exception_sets_state_to_failed(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.phase_analysis.execute = AsyncMock(side_effect=Exception("Boom"))

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Error task")

        assert hive_mind.state == HiveMindState.HIVE_FAILED

    @pytest.mark.asyncio
    async def test_exception_result_has_phases_completed_so_far(self, hive_mind):
        """Phases completed before the exception should still be recorded."""
        _wire_happy_path(hive_mind)
        # Architecture phase will raise
        hive_mind.phase_architecture.execute = AsyncMock(side_effect=RuntimeError("Arch failed"))

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Partial failure")

        # Analysis completed before architecture raised
        assert "analysis" in result.phases_completed
        assert "debate_skipped" in result.phases_completed
        # Architecture did not complete
        assert "architecture" not in result.phases_completed


# ===========================================================================
# SECTION 12: Confidence monitor / abort
# ===========================================================================


class TestConfidenceAbort:
    """Tests for confidence-based abort in process_task."""

    @pytest.mark.asyncio
    async def test_abort_when_confidence_drops(self, hive_mind):
        """When confidence monitor says abort, task is cancelled."""
        _wire_happy_path(hive_mind)

        hive_mind.confidence_monitor.should_abort = MagicMock(
            return_value=AbortRecommendation(
                should_abort=True,
                reason="Confidence below threshold",
                confidence=0.20,
                threshold=0.30,
            )
        )

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Low confidence task")

        assert result.success is False
        assert result.state == HiveMindState.HIVE_ESCALATE
        assert "confidence" in result.error.lower()
        # Execution phase should NOT have been called
        hive_mind.phase_execution.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_abort_when_confidence_ok(self, hive_mind):
        """Normal flow continues when confidence is sufficient."""
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Good confidence task")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_confidence_recorded_for_analysis(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Task")

        # confidence_monitor.record called at least for analysis
        calls = hive_mind.confidence_monitor.record.call_args_list
        phase_names = [c[0][0] for c in calls]
        assert "analysis" in phase_names


# ===========================================================================
# SECTION 13: Budget tracking
# ===========================================================================


class TestBudgetTracking:
    """Tests for budget-related operations in process_task."""

    @pytest.mark.asyncio
    async def test_budget_allocator_reset_and_allocate(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Budget test")

        hive_mind.budget_allocator.reset.assert_called_once()
        hive_mind.budget_allocator.allocate.assert_called_once()

    @pytest.mark.asyncio
    async def test_budget_allocator_report_actual_called(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Budget test")

        # At minimum, analysis and consolidation report actuals
        calls = [c[0][0] for c in hive_mind.budget_allocator.report_actual.call_args_list]
        assert "analysis" in calls
        assert "consolidation" in calls

    @pytest.mark.asyncio
    async def test_cost_estimator_start_task_called(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Budget test")

        hive_mind.cost_estimator.start_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_budget_tracker_integration_logs_warning(self, hive_mind):
        """When budget_tracker is set and budget may be exceeded, logs a warning."""
        _wire_happy_path(hive_mind)
        hive_mind.budget_tracker = MagicMock()
        hive_mind.cost_estimator.check_usd_budget = MagicMock(return_value=False)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            # Should still proceed (warning only, not blocking)
            result = await hive_mind.process_task("Expensive task")

        assert result.success is True


# ===========================================================================
# SECTION 14: Phase ordering and state transitions during process_task
# ===========================================================================


class TestPhaseOrdering:
    """Verify correct state transitions happen in the right order."""

    @pytest.mark.asyncio
    async def test_state_transitions_happy_path(self, hive_mind):
        """Track all state transitions during a happy-path execution."""
        _wire_happy_path(hive_mind)
        transitions = []
        original_set_state = hive_mind._set_state

        def track_state(new_state):
            transitions.append(new_state)
            original_set_state(new_state)

        hive_mind._set_state = track_state

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Track states")

        # Expected order for happy path (no debate)
        assert transitions[0] == HiveMindState.HIVE_ANALYZING_GEMINI
        assert HiveMindState.HIVE_ARCHITECTING in transitions
        assert HiveMindState.HIVE_EXECUTING in transitions
        assert HiveMindState.HIVE_REFLECTING in transitions
        assert transitions[-1] == HiveMindState.HIVE_SUCCESS

    @pytest.mark.asyncio
    async def test_debate_state_when_debate_needed(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.auto_breakpoints = False

        analysis = _make_analysis_phase_result(needs_debate=True)
        hive_mind.phase_analysis.execute = AsyncMock(return_value=analysis)
        debate = _make_debate_phase_result(was_skipped=False)
        hive_mind.phase_debate.execute = AsyncMock(return_value=debate)

        transitions = []
        original_set_state = hive_mind._set_state

        def track_state(new_state):
            transitions.append(new_state)
            original_set_state(new_state)

        hive_mind._set_state = track_state

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Debate needed")

        assert HiveMindState.HIVE_DEBATING in transitions


# ===========================================================================
# SECTION 15: process_task with saga enabled
# ===========================================================================


class TestProcessTaskSaga:
    """Tests for saga checkpoint integration."""

    @pytest.mark.asyncio
    async def test_saga_enabled_creates_checkpoints(self, tmp_workspace, mock_config, mock_gemini, mock_claude):
        """When saga is enabled, checkpoint_phase is called after each phase."""
        with (
            patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge") as mock_sync,
            patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge") as mock_telem,
            patch("core.intelligence.hive_mind.orchestrator.StagnationDetector") as mock_stag_cls,
        ):
            mock_sync_inst = MagicMock()
            mock_sync_inst.sync_checkpoint = AsyncMock()
            mock_sync.return_value = mock_sync_inst

            mock_telem_inst = MagicMock()
            mock_telem_inst.emit = AsyncMock()
            mock_telem_inst.emit_sync = MagicMock()
            mock_telem_inst.start_trace = MagicMock(return_value="t1")
            mock_telem_inst.end_trace = MagicMock()
            mock_telem.return_value = mock_telem_inst

            mock_stag = MagicMock()
            mock_stag.get_swap_recommendation.return_value = {
                "should_swap": False,
                "new_lead": None,
                "reason": "OK",
            }
            mock_stag.get_stats.return_value = {}
            mock_stag_cls.return_value = mock_stag

            hm = TrueHiveMind(
                workspace_path=tmp_workspace,
                config=mock_config,
                gemini_driver=mock_gemini,
                claude_driver=mock_claude,
                saga_enabled=True,
            )

            _wire_happy_path(hm)

            # Mock SagaManager
            mock_saga = MagicMock()
            mock_saga.checkpoint_phase = AsyncMock()
            mock_saga.update_context = MagicMock()
            mock_saga.cleanup = MagicMock()
            mock_saga.task_id = "hive_test"

            with (
                patch("core.intelligence.hive_mind.orchestrator.SagaManager") as saga_cls,
                patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal,
                patch("core.intelligence.swarm.generate_task_id", return_value="hive_test"),
            ):
                saga_cls.resume_from = AsyncMock(return_value=None)
                saga_cls.return_value = mock_saga
                mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

                result = await hm.process_task("Saga test")

            assert result.success is True
            # Checkpoint should have been called for analysis, debate, architecture, execution
            assert mock_saga.checkpoint_phase.await_count >= 3


# ===========================================================================
# SECTION 16: SwarmBridge delegation
# ===========================================================================


class TestSwarmBridgeDelegation:
    """Tests for swarm engine integration during execution."""

    def test_swarm_engine_passed_to_execution_phase(self, tmp_workspace, mock_config, mock_gemini, mock_claude):
        mock_swarm = MagicMock()
        mock_swarm.session_manager = MagicMock()
        with (
            patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.StagnationDetector"),
        ):
            hm = TrueHiveMind(
                workspace_path=tmp_workspace,
                config=mock_config,
                gemini_driver=mock_gemini,
                claude_driver=mock_claude,
                swarm_engine=mock_swarm,
                saga_enabled=False,
            )
        # MonitoredExecutionPhase wraps swarm_engine in a SwarmBridge
        assert hm.phase_execution.swarm_bridge is not None

    def test_sync_bridge_wired_with_swarm_session_manager(self, tmp_workspace, mock_config, mock_gemini, mock_claude):
        mock_swarm = MagicMock()
        mock_swarm.session_manager = MagicMock()
        with (
            patch("core.intelligence.hive_mind.orchestrator.get_sync_bridge") as mock_sync,
            patch("core.intelligence.hive_mind.orchestrator.get_telemetry_bridge"),
            patch("core.intelligence.hive_mind.orchestrator.StagnationDetector"),
        ):
            mock_sync_inst = MagicMock()
            mock_sync.return_value = mock_sync_inst

            TrueHiveMind(
                workspace_path=tmp_workspace,
                config=mock_config,
                gemini_driver=mock_gemini,
                claude_driver=mock_claude,
                swarm_engine=mock_swarm,
                saga_enabled=False,
            )

            mock_sync_inst.set_session_manager.assert_called_once_with(mock_swarm.session_manager)


# ===========================================================================
# SECTION 17: success_memory recording
# ===========================================================================


class TestSuccessMemoryRecording:
    """Tests for SuccessMemory integration on task success."""

    @pytest.mark.asyncio
    async def test_success_memory_recorded_on_success(self, hive_mind):
        _wire_happy_path(hive_mind)

        mock_success_mem = MagicMock()
        hive_mind.success_memory = mock_success_mem

        with (
            patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal,
            patch(
                "core.intelligence.hive_mind.orchestrator.create_hive_mind_adapters",
                create=True,
                return_value=(MagicMock(), MagicMock()),
            ),
        ):
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Success memory test")

        assert result.success is True
        # success_memory.record_success should have been called
        mock_success_mem.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_memory_not_called_on_failure(self, hive_mind):
        _wire_happy_path(hive_mind)
        # Make execution fail
        hive_mind.phase_execution.execute = AsyncMock(
            return_value=_make_exec_phase_result(success=False, needs_diagnosis=False)
        )

        mock_success_mem = MagicMock()
        hive_mind.success_memory = mock_success_mem

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Failed task")

        assert result.success is False
        mock_success_mem.record_success.assert_not_called()


# ===========================================================================
# SECTION 18: project_memory RAG archival
# ===========================================================================


class TestProjectMemoryArchival:
    """Tests for RAG archival on task completion."""

    @pytest.mark.asyncio
    async def test_archive_called_when_project_memory_exists(self, hive_mind):
        _wire_happy_path(hive_mind)
        mock_pmem = MagicMock()
        hive_mind.project_memory = mock_pmem

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Archive test")

        hive_mind.context_manager.archive_to_rag.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_not_called_without_project_memory(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.project_memory = None

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("No archive test")

        hive_mind.context_manager.archive_to_rag.assert_not_called()


# ===========================================================================
# SECTION 19: complexity parameter
# ===========================================================================


class TestComplexityParameter:
    """Tests that complexity is passed correctly."""

    @pytest.mark.asyncio
    async def test_default_complexity_is_moderate(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Default complexity")

        # budget_allocator.allocate receives the complexity value
        call_args = hive_mind.budget_allocator.allocate.call_args[0][0]
        assert call_args == "moderate"

    @pytest.mark.asyncio
    async def test_expert_complexity_passed_through(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Expert task", complexity=TaskComplexity.EXPERT)

        call_args = hive_mind.budget_allocator.allocate.call_args[0][0]
        assert call_args == "expert"


# ===========================================================================
# SECTION 20: Hot-swap during retry loop
# ===========================================================================


class TestHotSwapDuringRetry:
    """Tests for hot-swap lead agent during the retry loop."""

    @pytest.mark.asyncio
    async def test_lead_swap_during_retry(self, hive_mind):
        """When stagnation is detected during retry, lead agent is swapped."""
        _wire_happy_path(hive_mind)
        hive_mind.auto_breakpoints = False

        # First execution fails, second succeeds
        fail_exec = _make_exec_phase_result(
            success=False,
            needs_diagnosis=True,
            failure_step="step_1",
        )
        success_exec = _make_exec_phase_result(success=True)
        hive_mind.phase_execution.execute = AsyncMock(side_effect=[fail_exec, success_exec])

        diagnosis = _make_diagnosis_phase_result(user_decision="retry")
        hive_mind.phase_diagnosis = MagicMock()
        hive_mind.phase_diagnosis.execute = AsyncMock(return_value=diagnosis)
        hive_mind.phase_diagnosis.get_retry_recommendations = MagicMock(return_value={})

        retry = _make_retry_phase_result(action="RETRY", modified_arch=_make_architecture())
        hive_mind.phase_retry.execute = MagicMock(return_value=retry)

        # Simulate stagnation detection
        hive_mind._mock_stag.get_swap_recommendation.return_value = {
            "should_swap": True,
            "new_lead": "claude",
            "reason": "Stagnation detected",
        }

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Swap lead task")

        assert hive_mind._current_lead == "claude"
        assert any("lead_swapped" in p for p in result.phases_completed)


# ===========================================================================
# SECTION 21: Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_empty_task_string(self, hive_mind):
        """An empty task should still go through the pipeline."""
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("")

        # Should complete without error (phases mock responses regardless)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_very_long_task_string(self, hive_mind):
        """A very long task string should not cause issues."""
        _wire_happy_path(hive_mind)

        long_task = "A" * 100000

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task(long_task)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_agents_spawned_tracked(self, hive_mind):
        """When architecture spawns agents, they appear in the result."""
        _wire_happy_path(hive_mind)

        arch = _make_arch_phase_result(agents_spawned=["specialist_x", "specialist_y"])
        hive_mind.phase_architecture.execute = AsyncMock(return_value=arch)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Spawn test")

        assert "specialist_x" in result.agents_spawned
        assert "specialist_y" in result.agents_spawned

    @pytest.mark.asyncio
    async def test_knowledge_archived_count(self, hive_mind):
        """Consolidation's archived_to_rag count propagates to result."""
        _wire_happy_path(hive_mind)
        consol = _make_consolidation_phase_result(archived=7)
        hive_mind.phase_consolidation.execute = AsyncMock(return_value=consol)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            result = await hive_mind.process_task("Knowledge test")

        assert result.knowledge_archived == 7

    @pytest.mark.asyncio
    async def test_multiple_sequential_tasks(self, hive_mind):
        """Running process_task twice resets state properly."""
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            r1 = await hive_mind.process_task("Task 1")
            assert r1.success is True

            # Re-wire for second run
            _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            r2 = await hive_mind.process_task("Task 2")
            assert r2.success is True

    def test_force_lead_swap_case_insensitive(self, hive_mind):
        result = hive_mind.force_lead_swap("CLAUDE")
        assert result["swapped"] is True
        assert hive_mind._current_lead == "claude"

    def test_force_lead_swap_gemini_case(self, hive_mind):
        hive_mind._current_lead = "claude"
        result = hive_mind.force_lead_swap("Gemini")
        assert result["swapped"] is True
        assert hive_mind._current_lead == "gemini"


# ===========================================================================
# SECTION 22: HiveMindState enum coverage
# ===========================================================================


class TestHiveMindStateEnum:
    """Verify all expected states exist in the enum."""

    def test_gating_state_exists(self):
        assert HiveMindState.HIVE_GATING.value == "hive_gating"

    def test_analysis_states_exist(self):
        assert HiveMindState.HIVE_ANALYZING_GEMINI.value == "hive_analyzing_gemini"
        assert HiveMindState.HIVE_ANALYZING_CLAUDE.value == "hive_analyzing_claude"
        assert HiveMindState.HIVE_COMPARING_ANALYSES.value == "hive_comparing_analyses"

    def test_debate_states_exist(self):
        assert HiveMindState.HIVE_DEBATING.value == "hive_debating"
        assert HiveMindState.HIVE_CHECKING_CONSENSUS.value == "hive_checking_consensus"
        assert HiveMindState.HIVE_BREAKPOINT_DEBATE.value == "hive_breakpoint_debate"

    def test_architecture_states_exist(self):
        assert HiveMindState.HIVE_ARCHITECTING.value == "hive_architecting"
        assert HiveMindState.HIVE_CHECKING_REGISTRY.value == "hive_checking_registry"

    def test_execution_states_exist(self):
        assert HiveMindState.HIVE_EXECUTING.value == "hive_executing"
        assert HiveMindState.HIVE_MONITORING.value == "hive_monitoring"

    def test_diagnosis_states_exist(self):
        assert HiveMindState.HIVE_DIAGNOSING.value == "hive_diagnosing"

    def test_retry_states_exist(self):
        assert HiveMindState.HIVE_DECIDING_RETRY.value == "hive_deciding_retry"
        assert HiveMindState.HIVE_APPLYING_CHANGES.value == "hive_applying_changes"

    def test_consolidation_states_exist(self):
        assert HiveMindState.HIVE_REFLECTING.value == "hive_reflecting"
        assert HiveMindState.HIVE_CONSOLIDATING.value == "hive_consolidating"

    def test_terminal_states_exist(self):
        assert HiveMindState.HIVE_SUCCESS.value == "hive_success"
        assert HiveMindState.HIVE_FAILED.value == "hive_failed"
        assert HiveMindState.HIVE_ESCALATE.value == "hive_escalate"

    def test_total_state_count(self):
        # 24 states as documented
        assert len(HiveMindState) == 24


# ===========================================================================
# SECTION 23: context_manager interactions
# ===========================================================================


class TestContextManagerInteractions:
    """Tests for context_manager usage during process_task."""

    @pytest.mark.asyncio
    async def test_context_cleared_at_start(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Clear test")

        hive_mind.context_manager.clear.assert_called_once_with(keep_critical=False)

    @pytest.mark.asyncio
    async def test_confidence_monitor_reset_at_start(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Reset test")

        hive_mind.confidence_monitor.reset.assert_called_once()


# ===========================================================================
# SECTION 24: telemetry emissions
# ===========================================================================


class TestTelemetryEmissions:
    """Tests that telemetry events are emitted during process_task."""

    @pytest.mark.asyncio
    async def test_telemetry_trace_started(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Telemetry test")

        hive_mind._mock_telem.start_trace.assert_called_once()

    @pytest.mark.asyncio
    async def test_telemetry_trace_ended_on_success(self, hive_mind):
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Telemetry test")

        hive_mind._mock_telem.end_trace.assert_called()

    @pytest.mark.asyncio
    async def test_telemetry_trace_ended_on_failure(self, hive_mind):
        _wire_happy_path(hive_mind)
        hive_mind.phase_analysis.execute = AsyncMock(side_effect=RuntimeError("Boom"))

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Fail telemetry")

        hive_mind._mock_telem.end_trace.assert_called()

    @pytest.mark.asyncio
    async def test_telemetry_emit_called_multiple_times(self, hive_mind):
        """Multiple telemetry events are emitted during process_task."""
        _wire_happy_path(hive_mind)

        with patch("core.intelligence.hive_mind.orchestrator.get_phase_audit_logger") as mock_pal:
            mock_pal.return_value = MagicMock(detect_patterns=MagicMock(return_value=[]))

            await hive_mind.process_task("Multi emit test")

        # At minimum: phase start, node spawns, node updates, phase end
        assert hive_mind._mock_telem.emit.await_count >= 4
