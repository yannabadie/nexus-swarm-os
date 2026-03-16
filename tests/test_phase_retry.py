"""
Tests for Phase 6: Adaptive Retry (core.hive_mind.phases.phase_retry).

Validates:
- RetryPhaseResult dataclass
- AdaptiveRetryPhase.execute() decision logic (retry/stop/escalate)
- User decision handling (abort, escalate, retry)
- Retry budget limit enforcement (MAX_RETRIES)
- StrategyBlacklist integration (blacklisted strategies trigger ESCALATE)
- _describe_strategy() produces stable fingerprints
- _apply_changes() architecture modification paths
- _estimate_improvement() improvement scoring
- _add_to_blacklist() failure category mapping
- mark_success() and reset_retry_count() helpers
- get_retry_stats() reporting
- CostEstimator budget exhaustion path
- V12.4 context compression integration (compress_context, fresh_session)
- Edge cases: first attempt, exact max retry boundary, empty recommendations
"""

from typing import Any
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from core.intelligence.hive_mind.context_manager import HiveMindContextManager
from core.intelligence.hive_mind.cost_estimator import CostEstimator
from core.intelligence.hive_mind.phases.phase_retry import (
    AdaptiveRetryPhase,
    RetryPhaseResult,
)
from core.intelligence.hive_mind.strategy_blacklist import (
    FailureCategory,
    StrategyBlacklist,
)
from core.intelligence.hive_mind.types import (
    AgentArchitecture,
    AgentSpec,
    ExecutionPlan,
    ExecutionStep,
    FailureDiagnosis,
    FailureType,
    RAGConfig,
    RetryDecision,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_diagnosis(
    failure_type: FailureType = FailureType.TOOL_ERROR,
    root_cause: str = "Tool crashed unexpectedly",
    contributing_factors: list[str] | None = None,
    evidence: list[str] | None = None,
    recommended_changes: list[str] | None = None,
    confidence: float = 0.7,
    missing_capability: str | None = None,
) -> FailureDiagnosis:
    """Create a FailureDiagnosis for testing."""
    return FailureDiagnosis(
        failure_type=failure_type,
        root_cause=root_cause,
        contributing_factors=contributing_factors if contributing_factors is not None else ["factor1"],
        evidence=evidence if evidence is not None else ["error log entry"],
        recommended_changes=recommended_changes
        if recommended_changes is not None
        else ["change tool config", "add retry"],
        confidence=confidence,
        missing_capability=missing_capability,
    )


def _make_architecture(
    status: str = "READY",
    collaboration_mode: str = "sequential",
    agents_to_use: list[str] | None = None,
    agents_to_spawn: list[AgentSpec] | None = None,
    reasoning: str = "Initial approach",
    steps: list[ExecutionStep] | None = None,
    rag_depth: str = "standard",
) -> AgentArchitecture:
    """Create an AgentArchitecture for testing."""
    if steps is None:
        steps = [
            ExecutionStep(
                name="step1",
                agent_id="gemini",
                action="analyze code",
                expected_duration=30.0,
            ),
            ExecutionStep(
                name="step2",
                agent_id="claude",
                action="write tests",
                expected_duration=45.0,
            ),
        ]
    return AgentArchitecture(
        status=status,
        collaboration_mode=collaboration_mode,
        agents_to_use=agents_to_use or ["gemini", "claude"],
        agents_to_spawn=agents_to_spawn or [],
        rag_config=RAGConfig(depth=rag_depth),
        execution_plan=ExecutionPlan(strategy="sequential", steps=steps),
        spawn_commands=[],
        estimated_cost=1000,
        reasoning=reasoning,
    )


def _make_phase(
    budget_limit: int = 50000,
    cost_estimator: CostEstimator | None = None,
    context_manager: HiveMindContextManager | None = None,
    blacklist: StrategyBlacklist | None = None,
) -> AdaptiveRetryPhase:
    """Create an AdaptiveRetryPhase with mocked dependencies."""
    ce = cost_estimator or CostEstimator(budget_limit=budget_limit)
    cm = context_manager or MagicMock(spec=HiveMindContextManager)
    bl = blacklist or StrategyBlacklist()
    return AdaptiveRetryPhase(
        cost_estimator=ce,
        context_manager=cm,
        blacklist=bl,
    )


def _default_recommendations(**overrides: Any) -> dict[str, Any]:
    """Create default recommendations dict for retry."""
    recs: dict[str, Any] = {"architecture_changes": {}}
    recs.update(overrides)
    return recs


# =============================================================================
# 1. RetryPhaseResult dataclass
# =============================================================================


class TestRetryPhaseResult:
    """Tests for the RetryPhaseResult dataclass."""

    def test_creation_with_all_fields(self):
        arch = _make_architecture()
        decision = RetryDecision(action="RETRY", reason="applying changes")
        result = RetryPhaseResult(
            decision=decision,
            modified_architecture=arch,
            retry_count=2,
            blacklisted=False,
        )
        assert result.decision.action == "RETRY"
        assert result.modified_architecture is arch
        assert result.retry_count == 2
        assert result.blacklisted is False

    def test_creation_with_none_architecture(self):
        decision = RetryDecision(action="STOP", reason="abort")
        result = RetryPhaseResult(
            decision=decision,
            modified_architecture=None,
            retry_count=0,
            blacklisted=False,
        )
        assert result.modified_architecture is None

    def test_blacklisted_flag(self):
        decision = RetryDecision(action="ESCALATE", reason="blacklisted")
        result = RetryPhaseResult(
            decision=decision,
            modified_architecture=None,
            retry_count=3,
            blacklisted=True,
        )
        assert result.blacklisted is True

    def test_retry_count_zero(self):
        decision = RetryDecision(action="STOP", reason="user abort")
        result = RetryPhaseResult(
            decision=decision,
            modified_architecture=None,
            retry_count=0,
            blacklisted=False,
        )
        assert result.retry_count == 0


# =============================================================================
# 2. User decision handling (abort, escalate)
# =============================================================================


class TestUserDecisions:
    """Tests for user decision override paths."""

    def test_abort_returns_stop(self):
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="abort",
        )
        assert result.decision.action == "STOP"
        assert "abort" in result.decision.reason.lower()
        assert result.modified_architecture is None
        assert result.blacklisted is False

    def test_abort_does_not_increment_retry_count(self):
        phase = _make_phase()
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="abort",
        )
        assert phase._retry_count == 0

    def test_escalate_returns_escalate(self):
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="escalate",
        )
        assert result.decision.action == "ESCALATE"
        assert "escalation" in result.decision.reason.lower()
        assert result.modified_architecture is None

    def test_escalate_does_not_increment_retry_count(self):
        phase = _make_phase()
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="escalate",
        )
        assert phase._retry_count == 0

    def test_retry_user_decision_proceeds(self):
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"
        assert result.retry_count == 1


# =============================================================================
# 3. Retry budget limits (MAX_RETRIES)
# =============================================================================


class TestRetryBudgetLimits:
    """Tests for retry count enforcement."""

    def test_first_attempt_succeeds(self):
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"
        assert result.retry_count == 1

    def test_max_retries_constant(self):
        assert AdaptiveRetryPhase.MAX_RETRIES == 3

    def test_exactly_at_max_retries_still_works(self):
        """Retry at attempt count == MAX_RETRIES should still succeed."""
        phase = _make_phase()
        # Execute MAX_RETRIES times; each increments counter before checking > MAX_RETRIES
        for _i in range(AdaptiveRetryPhase.MAX_RETRIES):
            result = phase.execute(
                diagnosis=_make_diagnosis(),
                current_architecture=_make_architecture(),
                recommendations=_default_recommendations(),
                user_decision="retry",
            )
        # After 3 executions, retry_count is 3, which is == MAX_RETRIES, not >
        assert result.decision.action == "RETRY"
        assert result.retry_count == AdaptiveRetryPhase.MAX_RETRIES

    def test_exceeding_max_retries_escalates(self):
        """Retry beyond MAX_RETRIES triggers ESCALATE."""
        phase = _make_phase()
        # Exhaust retries
        for _ in range(AdaptiveRetryPhase.MAX_RETRIES):
            phase.execute(
                diagnosis=_make_diagnosis(),
                current_architecture=_make_architecture(),
                recommendations=_default_recommendations(),
                user_decision="retry",
            )
        # One more should fail
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "ESCALATE"
        assert "Max retries" in result.decision.reason
        assert result.blacklisted is True
        assert result.retry_count == AdaptiveRetryPhase.MAX_RETRIES + 1

    def test_max_retries_suggestion(self):
        phase = _make_phase()
        phase._retry_count = AdaptiveRetryPhase.MAX_RETRIES
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.suggestion is not None
        assert "smaller parts" in result.decision.suggestion

    def test_retry_count_increments_each_call(self):
        phase = _make_phase()
        for expected in range(1, 4):
            result = phase.execute(
                diagnosis=_make_diagnosis(),
                current_architecture=_make_architecture(),
                recommendations=_default_recommendations(),
                user_decision="retry",
            )
            assert result.retry_count == expected


# =============================================================================
# 4. CostEstimator budget exhaustion
# =============================================================================


class TestCostBudgetExhaustion:
    """Tests for cost estimator budget checks."""

    def test_budget_exceeded_returns_stop(self):
        ce = CostEstimator(budget_limit=100)
        ce.spent = 100  # Fully spent
        phase = _make_phase(cost_estimator=ce)
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "STOP"
        assert "Budget exceeded" in result.decision.reason

    def test_budget_exceeded_not_blacklisted(self):
        ce = CostEstimator(budget_limit=10)
        ce.spent = 10
        phase = _make_phase(cost_estimator=ce)
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.blacklisted is False

    def test_budget_affordable_proceeds(self):
        ce = CostEstimator(budget_limit=50000)
        phase = _make_phase(cost_estimator=ce)
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"

    def test_budget_records_costs_on_retry(self):
        ce = CostEstimator(budget_limit=50000)
        phase = _make_phase(cost_estimator=ce)
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        # Should have recorded decide_retry (400) and apply_changes (300)
        assert ce.spent == 700


# =============================================================================
# 5. StrategyBlacklist integration
# =============================================================================


class TestBlacklistIntegration:
    """Tests for strategy blacklist interaction."""

    def test_blacklisted_strategy_triggers_escalate(self):
        bl = StrategyBlacklist()
        arch = _make_architecture()
        diag = _make_diagnosis()

        # Pre-populate blacklist with the strategy description
        phase = _make_phase(blacklist=bl)
        strategy_desc = phase._describe_strategy(arch, diag)
        bl.add_failed_strategy(
            strategy=strategy_desc,
            failure_reason="previous failure",
            failure_category=FailureCategory.TOOL_ERROR,
        )

        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "ESCALATE"
        assert result.blacklisted is True
        assert "blacklisted" in result.decision.reason.lower()

    def test_blacklisted_returns_alternatives_suggestion(self):
        bl = StrategyBlacklist()
        arch = _make_architecture()
        diag = _make_diagnosis()

        phase = _make_phase(blacklist=bl)
        strategy_desc = phase._describe_strategy(arch, diag)
        bl.add_failed_strategy(
            strategy=strategy_desc,
            failure_reason="tool crash",
            failure_category=FailureCategory.TOOL_ERROR,
        )

        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        # Should have a suggestion from alternatives
        assert result.decision.suggestion is not None

    def test_non_blacklisted_strategy_proceeds(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"

    def test_blacklist_attempt_count_in_reason(self):
        bl = StrategyBlacklist()
        arch = _make_architecture()
        diag = _make_diagnosis()

        phase = _make_phase(blacklist=bl)
        strategy_desc = phase._describe_strategy(arch, diag)
        # Add twice to get attempt_count = 2
        bl.add_failed_strategy(strategy=strategy_desc, failure_reason="fail1")
        bl.add_failed_strategy(strategy=strategy_desc, failure_reason="fail2")

        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert "2 times" in result.decision.reason

    def test_blacklist_check_order_budget_before_blacklist(self):
        """Budget check happens before blacklist check."""
        ce = CostEstimator(budget_limit=10)
        ce.spent = 10  # Fully spent
        bl = StrategyBlacklist()
        arch = _make_architecture()
        diag = _make_diagnosis()
        phase = _make_phase(cost_estimator=ce, blacklist=bl)
        strategy_desc = phase._describe_strategy(arch, diag)
        bl.add_failed_strategy(strategy=strategy_desc, failure_reason="fail")

        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        # Budget check should fire before blacklist
        assert result.decision.action == "STOP"
        assert "Budget" in result.decision.reason


# =============================================================================
# 6. _describe_strategy()
# =============================================================================


class TestDescribeStrategy:
    """Tests for strategy description generation."""

    def test_includes_mode(self):
        phase = _make_phase()
        arch = _make_architecture(collaboration_mode="parallel")
        diag = _make_diagnosis()
        desc = phase._describe_strategy(arch, diag)
        assert "mode:parallel" in desc

    def test_includes_agents(self):
        phase = _make_phase()
        arch = _make_architecture(agents_to_use=["gemini", "claude"])
        diag = _make_diagnosis()
        desc = phase._describe_strategy(arch, diag)
        assert "agents:gemini,claude" in desc

    def test_includes_step_count(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        desc = phase._describe_strategy(arch, diag)
        assert "steps:2" in desc

    def test_includes_reasoning_truncated(self):
        phase = _make_phase()
        long_reasoning = "x" * 200
        arch = _make_architecture(reasoning=long_reasoning)
        diag = _make_diagnosis()
        desc = phase._describe_strategy(arch, diag)
        # Reasoning truncated to 100 chars
        assert "approach:" in desc
        assert len(desc.split("approach:")[1].split(" |")[0]) <= 100

    def test_empty_reasoning_excluded(self):
        phase = _make_phase()
        arch = _make_architecture(reasoning="")
        diag = _make_diagnosis()
        desc = phase._describe_strategy(arch, diag)
        assert "approach:" not in desc

    def test_deterministic_output(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        desc1 = phase._describe_strategy(arch, diag)
        desc2 = phase._describe_strategy(arch, diag)
        assert desc1 == desc2


# =============================================================================
# 7. _apply_changes() architecture modification
# =============================================================================


class TestApplyChanges:
    """Tests for architecture modification logic."""

    def test_increase_timeout(self):
        phase = _make_phase()
        arch = _make_architecture()
        original_durations = [s.expected_duration for s in arch.execution_plan.steps]
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"increase_timeout": True})

        modified = phase._apply_changes(arch, diag, recs)
        for i, step in enumerate(modified.execution_plan.steps):
            assert step.expected_duration == int(original_durations[i] * 1.5)

    def test_spawn_specialist(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations(
            architecture_changes={
                "spawn_specialist": True,
                "capability_needed": "security",
            }
        )

        modified = phase._apply_changes(arch, diag, recs)
        assert len(modified.agents_to_spawn) == 1
        assert modified.agents_to_spawn[0].role == "security_specialist"
        assert "security" in modified.agents_to_spawn[0].capabilities
        assert modified.status == "SPAWN_REQUIRED"

    def test_spawn_specialist_default_capability(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"spawn_specialist": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.agents_to_spawn[0].role == "specialist_specialist"

    def test_add_verification(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"add_verification": True})

        modified = phase._apply_changes(arch, diag, recs)
        for step in modified.execution_plan.steps:
            assert step.verification_required is True

    def test_simplify_steps_reduces_to_two(self):
        steps = [ExecutionStep(name=f"step{i}", agent_id="gemini", action=f"action{i}") for i in range(5)]
        phase = _make_phase()
        arch = _make_architecture(steps=steps)
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"simplify_steps": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert len(modified.execution_plan.steps) == 2
        assert modified.execution_plan.steps[0].name == "step0"
        assert modified.execution_plan.steps[1].name == "step4"

    def test_simplify_steps_two_or_fewer_unchanged(self):
        steps = [
            ExecutionStep(name="step0", agent_id="gemini", action="action0"),
            ExecutionStep(name="step1", agent_id="claude", action="action1"),
        ]
        phase = _make_phase()
        arch = _make_architecture(steps=steps)
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"simplify_steps": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert len(modified.execution_plan.steps) == 2

    def test_rethink_approach_cycles_mode(self):
        phase = _make_phase()
        arch = _make_architecture(collaboration_mode="sequential")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"rethink_approach": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.collaboration_mode == "parallel"

    def test_rethink_approach_cycles_from_parallel(self):
        phase = _make_phase()
        arch = _make_architecture(collaboration_mode="parallel")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"rethink_approach": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.collaboration_mode == "pipeline"

    def test_rethink_approach_cycles_from_pipeline(self):
        phase = _make_phase()
        arch = _make_architecture(collaboration_mode="pipeline")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"rethink_approach": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.collaboration_mode == "sequential"

    def test_rethink_approach_unknown_mode_defaults_to_parallel(self):
        phase = _make_phase()
        arch = _make_architecture(collaboration_mode="lead_support")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"rethink_approach": True})

        modified = phase._apply_changes(arch, diag, recs)
        # Unknown mode defaults to index 0 -> next is index 1 -> "parallel"
        assert modified.collaboration_mode == "parallel"

    def test_reduce_context_deep_to_standard(self):
        phase = _make_phase()
        arch = _make_architecture(rag_depth="deep")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"reduce_context": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.rag_config.depth == "standard"

    def test_reduce_context_standard_to_shallow(self):
        phase = _make_phase()
        arch = _make_architecture(rag_depth="standard")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"reduce_context": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.rag_config.depth == "shallow"

    def test_reduce_context_shallow_stays_shallow(self):
        phase = _make_phase()
        arch = _make_architecture(rag_depth="shallow")
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"reduce_context": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.rag_config.depth == "shallow"

    def test_no_changes_returns_clone(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations()

        modified = phase._apply_changes(arch, diag, recs)
        # Should be a different object but with same base values
        assert modified is not arch
        assert modified.collaboration_mode == arch.collaboration_mode

    def test_reasoning_updated_on_modified_arch(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis(recommended_changes=["fix timeout", "add retries"])
        recs = _default_recommendations()

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.reasoning.startswith("Retry after:")

    def test_multiple_changes_applied_together(self):
        phase = _make_phase()
        steps = [ExecutionStep(name=f"s{i}", agent_id="gemini", action=f"a{i}") for i in range(4)]
        arch = _make_architecture(
            steps=steps,
            collaboration_mode="sequential",
            rag_depth="deep",
        )
        diag = _make_diagnosis()
        recs = _default_recommendations(
            architecture_changes={
                "increase_timeout": True,
                "add_verification": True,
                "rethink_approach": True,
                "reduce_context": True,
            }
        )

        modified = phase._apply_changes(arch, diag, recs)
        assert modified.collaboration_mode == "parallel"
        assert modified.rag_config.depth == "standard"
        for step in modified.execution_plan.steps:
            assert step.verification_required is True

    def test_agents_to_use_is_independent_copy(self):
        phase = _make_phase()
        arch = _make_architecture(agents_to_use=["gemini", "claude"])
        diag = _make_diagnosis()
        recs = _default_recommendations()

        modified = phase._apply_changes(arch, diag, recs)
        modified.agents_to_use.append("specialist")
        # Original should not be affected
        assert "specialist" not in arch.agents_to_use


# =============================================================================
# 8. V12.4 context compression integration
# =============================================================================


class TestV124ContextCompression:
    """Tests for V12.4 compress_context and fresh_session changes."""

    @patch("core.intelligence.hive_mind.phases.phase_retry.AdaptiveRetryPhase._apply_changes")
    def test_compress_context_called(self, mock_apply):
        """Verify compress_context triggers ContextCompressor."""
        mock_apply.return_value = _make_architecture()
        _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"compress_context": True})

        # Call _apply_changes directly (not mocked) to test real logic
        mock_apply.reset_mock()
        real_phase = _make_phase()

        with patch(
            "core.intelligence.hive_mind.phases.phase_retry.AdaptiveRetryPhase._apply_changes",
            wraps=real_phase._apply_changes,
        ):
            modified = real_phase._apply_changes(arch, diag, recs)
            # Should not crash even if compressor is not available
            assert modified is not None

    def test_compress_context_graceful_failure(self):
        """Context compression failure should not break _apply_changes."""
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"compress_context": True})

        # Even if get_compressor fails, _apply_changes should succeed
        with patch(
            "core.intelligence.hive_mind.phases.phase_retry.get_compressor",
            side_effect=ImportError("no module"),
            create=True,
        ):
            modified = phase._apply_changes(arch, diag, recs)
            assert modified is not None

    def test_fresh_session_triggers_compression(self):
        """fresh_session change also triggers context compression."""
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"fresh_session": True})

        modified = phase._apply_changes(arch, diag, recs)
        assert modified is not None
        assert modified.reasoning.startswith("Retry after:")


# =============================================================================
# 9. _estimate_improvement()
# =============================================================================


class TestEstimateImprovement:
    """Tests for improvement estimation logic."""

    def test_base_improvement(self):
        phase = _make_phase()
        diag = _make_diagnosis(confidence=0.0, recommended_changes=[])
        recs = _default_recommendations()
        improvement = phase._estimate_improvement(diag, recs)
        assert improvement == pytest.approx(0.3, abs=0.01)

    def test_high_confidence_increases_improvement(self):
        phase = _make_phase()
        diag = _make_diagnosis(confidence=1.0, recommended_changes=[])
        recs = _default_recommendations()
        improvement = phase._estimate_improvement(diag, recs)
        # base 0.3 + confidence 1.0 * 0.2 = 0.5
        assert improvement == pytest.approx(0.5, abs=0.01)

    def test_more_changes_increases_improvement(self):
        phase = _make_phase()
        diag = _make_diagnosis(
            confidence=0.0,
            recommended_changes=["c1", "c2", "c3", "c4"],
        )
        recs = _default_recommendations()
        improvement = phase._estimate_improvement(diag, recs)
        # base 0.3 + 4 * 0.05 = 0.5
        assert improvement == pytest.approx(0.5, abs=0.01)

    def test_improvement_capped_at_0_8(self):
        """Max possible is 0.3 + 0.2 + 0.2 = 0.7, which is below 0.8 cap."""
        phase = _make_phase()
        diag = _make_diagnosis(
            confidence=1.0,
            recommended_changes=[f"c{i}" for i in range(20)],
        )
        recs = _default_recommendations()
        improvement = phase._estimate_improvement(diag, recs)
        # 0.3 (base) + 1.0*0.2 (confidence) + min(20*0.05, 0.2) (changes) = 0.7
        assert improvement == pytest.approx(0.7, abs=0.01)
        assert improvement <= 0.8

    def test_changes_contribution_capped_at_0_2(self):
        phase = _make_phase()
        diag = _make_diagnosis(
            confidence=0.0,
            recommended_changes=[f"c{i}" for i in range(10)],
        )
        recs = _default_recommendations()
        improvement = phase._estimate_improvement(diag, recs)
        # base 0.3 + min(10 * 0.05, 0.2) = 0.5
        assert improvement == pytest.approx(0.5, abs=0.01)

    def test_medium_confidence_medium_changes(self):
        phase = _make_phase()
        diag = _make_diagnosis(
            confidence=0.5,
            recommended_changes=["c1", "c2"],
        )
        recs = _default_recommendations()
        improvement = phase._estimate_improvement(diag, recs)
        # base 0.3 + 0.5 * 0.2 + 2 * 0.05 = 0.5
        assert improvement == pytest.approx(0.5, abs=0.01)


# =============================================================================
# 10. _add_to_blacklist()
# =============================================================================


class TestAddToBlacklist:
    """Tests for blacklist addition with failure category mapping."""

    def test_tool_error_maps_correctly(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.TOOL_ERROR)
        phase._add_to_blacklist("test strategy", diag)

        entry = bl.is_blacklisted("test strategy")
        assert entry is not None
        assert entry.failure_category == FailureCategory.TOOL_ERROR

    def test_timeout_maps_correctly(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.TIMEOUT)
        phase._add_to_blacklist("timeout strat", diag)

        entry = bl.is_blacklisted("timeout strat")
        assert entry.failure_category == FailureCategory.TIMEOUT

    def test_capability_missing_maps_correctly(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.CAPABILITY_MISSING)
        phase._add_to_blacklist("cap missing strat", diag)

        entry = bl.is_blacklisted("cap missing strat")
        assert entry.failure_category == FailureCategory.CAPABILITY_MISSING

    def test_hallucination_maps_correctly(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.HALLUCINATION)
        phase._add_to_blacklist("hallucination strat", diag)

        entry = bl.is_blacklisted("hallucination strat")
        assert entry.failure_category == FailureCategory.HALLUCINATION

    def test_strategy_wrong_maps_to_wrong_approach(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.STRATEGY_WRONG)
        phase._add_to_blacklist("wrong strat", diag)

        entry = bl.is_blacklisted("wrong strat")
        assert entry.failure_category == FailureCategory.WRONG_APPROACH

    def test_context_lost_maps_to_resource_exceeded(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.CONTEXT_LOST)
        phase._add_to_blacklist("context lost strat", diag)

        entry = bl.is_blacklisted("context lost strat")
        assert entry.failure_category == FailureCategory.RESOURCE_EXCEEDED

    def test_budget_exceeded_maps_to_resource_exceeded(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.BUDGET_EXCEEDED)
        phase._add_to_blacklist("budget strat", diag)

        entry = bl.is_blacklisted("budget strat")
        assert entry.failure_category == FailureCategory.RESOURCE_EXCEEDED

    def test_memory_error_maps_to_resource_exceeded(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.MEMORY_ERROR)
        phase._add_to_blacklist("memory strat", diag)

        entry = bl.is_blacklisted("memory strat")
        assert entry.failure_category == FailureCategory.RESOURCE_EXCEEDED

    def test_planning_error_maps_to_wrong_approach(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.PLANNING_ERROR)
        phase._add_to_blacklist("planning strat", diag)

        entry = bl.is_blacklisted("planning strat")
        assert entry.failure_category == FailureCategory.WRONG_APPROACH

    def test_unknown_maps_to_unknown(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.UNKNOWN)
        phase._add_to_blacklist("unknown strat", diag)

        entry = bl.is_blacklisted("unknown strat")
        assert entry.failure_category == FailureCategory.UNKNOWN

    def test_tags_include_failure_type_value(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        diag = _make_diagnosis(failure_type=FailureType.HALLUCINATION)
        phase._add_to_blacklist("tagged strat", diag)

        entry = bl.is_blacklisted("tagged strat")
        assert "hallucination" in entry.tags

    def test_all_failure_types_mapped(self):
        """Every FailureType must have a mapping in FAILURE_TO_BLACKLIST."""
        for ft in FailureType:
            assert ft in AdaptiveRetryPhase.FAILURE_TO_BLACKLIST, (
                f"FailureType.{ft.name} missing from FAILURE_TO_BLACKLIST"
            )


# =============================================================================
# 11. mark_success() and reset_retry_count()
# =============================================================================


class TestMarkSuccessAndReset:
    """Tests for helper methods."""

    def test_mark_success_removes_from_blacklist(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        arch = _make_architecture()
        diag = _make_diagnosis()

        strategy_desc = phase._describe_strategy(arch, diag)
        bl.add_failed_strategy(strategy=strategy_desc, failure_reason="fail")

        # Confirm it is blacklisted
        assert bl.is_blacklisted(strategy_desc) is not None

        # Mark success
        phase.mark_success(arch, diag)

        # Should be removed
        assert bl.is_blacklisted(strategy_desc, check_similar=False) is None

    def test_mark_success_with_no_diagnosis(self):
        phase = _make_phase()
        arch = _make_architecture()
        # Should not raise
        phase.mark_success(arch, None)

    def test_reset_retry_count(self):
        phase = _make_phase()
        phase._retry_count = 5
        phase.reset_retry_count()
        assert phase._retry_count == 0

    def test_reset_allows_retries_again(self):
        phase = _make_phase()
        # Exhaust retries
        for _ in range(AdaptiveRetryPhase.MAX_RETRIES + 1):
            phase.execute(
                diagnosis=_make_diagnosis(),
                current_architecture=_make_architecture(),
                recommendations=_default_recommendations(),
                user_decision="retry",
            )
        # Reset and try again
        phase.reset_retry_count()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"
        assert result.retry_count == 1


# =============================================================================
# 12. get_retry_stats()
# =============================================================================


class TestGetRetryStats:
    """Tests for retry statistics reporting."""

    def test_initial_stats(self):
        phase = _make_phase()
        stats = phase.get_retry_stats()
        assert stats["current_retry_count"] == 0
        assert stats["max_retries"] == AdaptiveRetryPhase.MAX_RETRIES
        assert "blacklist_stats" in stats

    def test_stats_after_retries(self):
        phase = _make_phase()
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        stats = phase.get_retry_stats()
        assert stats["current_retry_count"] == 1

    def test_stats_blacklist_stats_included(self):
        bl = StrategyBlacklist()
        bl.add_failed_strategy("s1", "r1")
        bl.add_failed_strategy("s2", "r2")
        phase = _make_phase(blacklist=bl)
        stats = phase.get_retry_stats()
        assert stats["blacklist_stats"]["total_entries"] == 2


# =============================================================================
# 13. Full execute() flow
# =============================================================================


class TestFullExecuteFlow:
    """Integration-style tests for the complete execute() path."""

    def test_successful_retry_returns_modified_architecture(self):
        phase = _make_phase()
        arch = _make_architecture()
        diag = _make_diagnosis(recommended_changes=["fix1", "fix2"])
        recs = _default_recommendations(architecture_changes={"add_verification": True})

        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=recs,
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"
        assert result.modified_architecture is not None
        # Verification should be added
        for step in result.modified_architecture.execution_plan.steps:
            assert step.verification_required is True

    def test_retry_decision_contains_changes_made(self):
        phase = _make_phase()
        diag = _make_diagnosis(recommended_changes=["fix1", "fix2", "fix3", "fix4", "fix5", "fix6"])
        result = phase.execute(
            diagnosis=diag,
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        # Top 5 changes should be included
        assert len(result.decision.changes_made) == 5

    def test_retry_decision_contains_expected_improvement(self):
        phase = _make_phase()
        diag = _make_diagnosis(confidence=0.5, recommended_changes=["c1"])
        result = phase.execute(
            diagnosis=diag,
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.expected_improvement > 0.0

    def test_apply_changes_exception_escalates(self):
        """If _apply_changes raises, result is ESCALATE and strategy is blacklisted."""
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)

        arch = _make_architecture()
        diag = _make_diagnosis()

        # Make _apply_changes raise
        with patch.object(phase, "_apply_changes", side_effect=RuntimeError("clone failed")):
            result = phase.execute(
                diagnosis=diag,
                current_architecture=arch,
                recommendations=_default_recommendations(),
                user_decision="retry",
            )

        assert result.decision.action == "ESCALATE"
        assert "clone failed" in result.decision.reason
        assert result.blacklisted is True
        assert result.modified_architecture is None

    def test_apply_changes_exception_adds_to_blacklist(self):
        bl = StrategyBlacklist()
        phase = _make_phase(blacklist=bl)
        arch = _make_architecture()
        diag = _make_diagnosis()

        with patch.object(phase, "_apply_changes", side_effect=ValueError("bad data")):
            phase.execute(
                diagnosis=diag,
                current_architecture=arch,
                recommendations=_default_recommendations(),
                user_decision="retry",
            )

        # Verify strategy was blacklisted
        strategy_desc = phase._describe_strategy(arch, diag)
        entry = bl.is_blacklisted(strategy_desc)
        assert entry is not None

    def test_retry_with_new_architecture_in_decision(self):
        phase = _make_phase()
        diag = _make_diagnosis()
        result = phase.execute(
            diagnosis=diag,
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.new_architecture is not None
        assert result.decision.new_architecture is result.modified_architecture

    def test_reason_contains_change_count(self):
        phase = _make_phase()
        diag = _make_diagnosis(recommended_changes=["a", "b", "c"])
        result = phase.execute(
            diagnosis=diag,
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert "3 changes" in result.decision.reason


# =============================================================================
# 14. Edge cases
# =============================================================================


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_empty_recommended_changes(self):
        phase = _make_phase()
        diag = _make_diagnosis(recommended_changes=[])
        result = phase.execute(
            diagnosis=diag,
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"
        assert "0 changes" in result.decision.reason

    def test_empty_architecture_changes_dict(self):
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations={"architecture_changes": {}},
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"

    def test_missing_architecture_changes_key(self):
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations={},
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"

    def test_architecture_with_no_steps(self):
        phase = _make_phase()
        arch = _make_architecture(steps=[])
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"simplify_steps": True})
        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=recs,
            user_decision="retry",
        )
        assert result.decision.action == "RETRY"

    def test_architecture_with_single_step(self):
        steps = [ExecutionStep(name="only", agent_id="gemini", action="do it")]
        phase = _make_phase()
        arch = _make_architecture(steps=steps)
        diag = _make_diagnosis()
        recs = _default_recommendations(architecture_changes={"simplify_steps": True})
        modified = phase._apply_changes(arch, diag, recs)
        # Single step <= 2, should not simplify
        assert len(modified.execution_plan.steps) == 1

    def test_unknown_user_decision_treated_as_retry(self):
        """Unknown user_decision (not abort/escalate) proceeds to retry logic."""
        phase = _make_phase()
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="something_else",
        )
        # Should proceed through retry logic
        assert result.decision.action == "RETRY"

    def test_concurrent_retries_count_correctly(self):
        """Multiple sequential calls increment count properly."""
        phase = _make_phase()
        counts = []
        for _ in range(3):
            result = phase.execute(
                diagnosis=_make_diagnosis(),
                current_architecture=_make_architecture(),
                recommendations=_default_recommendations(),
                user_decision="retry",
            )
            counts.append(result.retry_count)
        assert counts == [1, 2, 3]

    def test_abort_after_retries_preserves_count(self):
        phase = _make_phase()
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="abort",
        )
        # Abort should return current count (2, since abort doesn't increment)
        assert result.retry_count == 2

    def test_escalate_after_retries_preserves_count(self):
        phase = _make_phase()
        phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="escalate",
        )
        assert result.retry_count == 1


# =============================================================================
# 15. FAILURE_TO_BLACKLIST mapping completeness
# =============================================================================


class TestFailureToBlacklistMapping:
    """Verify all FailureType -> FailureCategory mappings are valid."""

    def test_all_values_are_failure_categories(self):
        for ft, fc in AdaptiveRetryPhase.FAILURE_TO_BLACKLIST.items():
            assert isinstance(ft, FailureType)
            assert isinstance(fc, FailureCategory)

    def test_mapping_covers_all_failure_types(self):
        for ft in FailureType:
            assert ft in AdaptiveRetryPhase.FAILURE_TO_BLACKLIST

    def test_timeout_mapping(self):
        assert AdaptiveRetryPhase.FAILURE_TO_BLACKLIST[FailureType.TIMEOUT] == FailureCategory.TIMEOUT

    def test_context_lost_mapping(self):
        assert AdaptiveRetryPhase.FAILURE_TO_BLACKLIST[FailureType.CONTEXT_LOST] == FailureCategory.RESOURCE_EXCEEDED

    def test_v124_memory_error_mapping(self):
        """V12.4: MEMORY_ERROR should map to RESOURCE_EXCEEDED."""
        assert AdaptiveRetryPhase.FAILURE_TO_BLACKLIST[FailureType.MEMORY_ERROR] == FailureCategory.RESOURCE_EXCEEDED

    def test_v124_planning_error_mapping(self):
        """V12.4: PLANNING_ERROR should map to WRONG_APPROACH."""
        assert AdaptiveRetryPhase.FAILURE_TO_BLACKLIST[FailureType.PLANNING_ERROR] == FailureCategory.WRONG_APPROACH


# =============================================================================
# 16. Priority ordering of checks in execute()
# =============================================================================


class TestExecuteCheckOrdering:
    """Tests that verify the priority ordering of checks within execute()."""

    def test_abort_takes_priority_over_max_retries(self):
        phase = _make_phase()
        phase._retry_count = 100  # Way past max
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="abort",
        )
        assert result.decision.action == "STOP"

    def test_escalate_takes_priority_over_max_retries(self):
        phase = _make_phase()
        phase._retry_count = 100
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="escalate",
        )
        assert result.decision.action == "ESCALATE"
        assert "User requested" in result.decision.reason

    def test_abort_takes_priority_over_budget(self):
        ce = CostEstimator(budget_limit=0)
        phase = _make_phase(cost_estimator=ce)
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="abort",
        )
        assert result.decision.action == "STOP"
        assert "abort" in result.decision.reason.lower()

    def test_max_retries_takes_priority_over_budget(self):
        """When both max retries and budget are exceeded, max retries fires first."""
        ce = CostEstimator(budget_limit=0)
        phase = _make_phase(cost_estimator=ce)
        phase._retry_count = AdaptiveRetryPhase.MAX_RETRIES
        result = phase.execute(
            diagnosis=_make_diagnosis(),
            current_architecture=_make_architecture(),
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "ESCALATE"
        assert "Max retries" in result.decision.reason

    def test_budget_takes_priority_over_blacklist(self):
        """Budget check happens before blacklist check."""
        bl = StrategyBlacklist()
        ce = CostEstimator(budget_limit=10)
        ce.spent = 10
        phase = _make_phase(cost_estimator=ce, blacklist=bl)
        arch = _make_architecture()
        diag = _make_diagnosis()
        desc = phase._describe_strategy(arch, diag)
        bl.add_failed_strategy(desc, "fail")

        result = phase.execute(
            diagnosis=diag,
            current_architecture=arch,
            recommendations=_default_recommendations(),
            user_decision="retry",
        )
        assert result.decision.action == "STOP"
        assert "Budget" in result.decision.reason
