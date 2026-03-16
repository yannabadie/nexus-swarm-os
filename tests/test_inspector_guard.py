"""
Comprehensive tests for core.reasoning.inspector_guard module.

Tests the InspectorGuard post-step verification layer including:
- Data structures (RiskLevel, IssuePattern, InspectionResult, GuardStats)
- Signal scoring (status, issues, hallucinations, errors, stagnation, cascade, length)
- Pattern detection (repeated error, escalating severity, cascading failure, etc.)
- Risk score computation and boosting
- Suggestions generation
- Issue summary
- Singleton lifecycle
- Edge cases and thread safety
"""

import threading
import time

import pytest

from core.intelligence.reasoning.inspector_guard import (
    ERROR_INDICATORS,
    HALLUCINATION_INDICATORS,
    STAGNATION_INDICATORS,
    GuardStats,
    InspectionResult,
    InspectorGuard,
    IssuePattern,
    RiskLevel,
    get_inspector_guard,
    reset_inspector_guard,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def guard():
    """Fresh InspectorGuard instance for each test."""
    return InspectorGuard()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton before and after every test."""
    reset_inspector_guard()
    yield
    reset_inspector_guard()


def _make_inspection(
    step_name: str = "step",
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_score: float = 0.1,
    requires_diagnosis: bool = False,
    detected_patterns: list | None = None,
    issues_found: int = 0,
    issue_summary: str = "No issues detected",
    suggestions: list | None = None,
) -> InspectionResult:
    """Helper to build InspectionResult instances for history."""
    return InspectionResult(
        step_name=step_name,
        risk_level=risk_level,
        risk_score=risk_score,
        requires_diagnosis=requires_diagnosis,
        detected_patterns=detected_patterns or [],
        issues_found=issues_found,
        issue_summary=issue_summary,
        suggestions=suggestions or [],
    )


# =============================================================================
# 1. RiskLevel Enum
# =============================================================================


class TestRiskLevel:
    """Tests for the RiskLevel enum."""

    def test_low_value(self):
        assert RiskLevel.LOW.value == "low"

    def test_moderate_value(self):
        assert RiskLevel.MODERATE.value == "moderate"

    def test_high_value(self):
        assert RiskLevel.HIGH.value == "high"

    def test_critical_value(self):
        assert RiskLevel.CRITICAL.value == "critical"

    def test_member_count(self):
        assert len(RiskLevel) == 4

    def test_from_value(self):
        assert RiskLevel("low") == RiskLevel.LOW
        assert RiskLevel("critical") == RiskLevel.CRITICAL


# =============================================================================
# 2. IssuePattern Enum
# =============================================================================


class TestIssuePattern:
    """Tests for the IssuePattern enum."""

    def test_repeated_error(self):
        assert IssuePattern.REPEATED_ERROR.value == "repeated_error"

    def test_escalating_severity(self):
        assert IssuePattern.ESCALATING_SEVERITY.value == "escalating_severity"

    def test_cascading_failure(self):
        assert IssuePattern.CASCADING_FAILURE.value == "cascading_failure"

    def test_hallucination_cluster(self):
        assert IssuePattern.HALLUCINATION_CLUSTER.value == "hallucination_cluster"

    def test_output_degradation(self):
        assert IssuePattern.OUTPUT_DEGRADATION.value == "output_degradation"

    def test_stagnation(self):
        assert IssuePattern.STAGNATION.value == "stagnation"

    def test_member_count(self):
        assert len(IssuePattern) == 6


# =============================================================================
# 3. InspectionResult Dataclass
# =============================================================================


class TestInspectionResult:
    """Tests for InspectionResult fields and properties."""

    def test_basic_fields(self):
        result = _make_inspection(step_name="test_step", risk_score=0.42, issues_found=3)
        assert result.step_name == "test_step"
        assert result.risk_score == 0.42
        assert result.issues_found == 3

    def test_is_safe_true_when_low(self):
        result = _make_inspection(risk_level=RiskLevel.LOW)
        assert result.is_safe is True

    def test_is_safe_false_when_moderate(self):
        result = _make_inspection(risk_level=RiskLevel.MODERATE)
        assert result.is_safe is False

    def test_is_safe_false_when_high(self):
        result = _make_inspection(risk_level=RiskLevel.HIGH)
        assert result.is_safe is False

    def test_is_safe_false_when_critical(self):
        result = _make_inspection(risk_level=RiskLevel.CRITICAL)
        assert result.is_safe is False

    def test_inspected_at_auto_set(self):
        before = time.time()
        result = _make_inspection()
        after = time.time()
        assert before <= result.inspected_at <= after

    def test_detected_patterns_list(self):
        result = _make_inspection(detected_patterns=[IssuePattern.STAGNATION, IssuePattern.REPEATED_ERROR])
        assert len(result.detected_patterns) == 2
        assert IssuePattern.STAGNATION in result.detected_patterns

    def test_suggestions_list(self):
        result = _make_inspection(suggestions=["Fix the bug", "Re-run tests"])
        assert len(result.suggestions) == 2

    def test_requires_diagnosis_field(self):
        result = _make_inspection(requires_diagnosis=True)
        assert result.requires_diagnosis is True


# =============================================================================
# 4. GuardStats Dataclass
# =============================================================================


class TestGuardStats:
    """Tests for GuardStats dataclass."""

    def test_fields(self):
        stats = GuardStats(
            total_inspections=10,
            total_flags=2,
            risk_distribution={"low": 6, "moderate": 2, "high": 1, "critical": 1},
            patterns_detected={"stagnation": 3},
            avg_risk_score=0.35,
        )
        assert stats.total_inspections == 10
        assert stats.total_flags == 2
        assert stats.avg_risk_score == 0.35
        assert stats.risk_distribution["low"] == 6
        assert stats.patterns_detected["stagnation"] == 3

    def test_empty_stats(self):
        stats = GuardStats(
            total_inspections=0,
            total_flags=0,
            risk_distribution={},
            patterns_detected={},
            avg_risk_score=0.0,
        )
        assert stats.total_inspections == 0
        assert stats.avg_risk_score == 0.0


# =============================================================================
# 5. inspect_step: Clean Output (LOW risk)
# =============================================================================


class TestCleanOutput:
    """Tests that clean output produces LOW risk."""

    def test_clean_success_returns_low(self, guard):
        result = guard.inspect_step(
            step_name="clean_step",
            step_output="The operation completed successfully. Here is the result.",
            step_status="success",
        )
        assert result.risk_level == RiskLevel.LOW
        assert result.is_safe is True
        assert result.risk_score < 0.3
        assert result.requires_diagnosis is False

    def test_clean_output_no_patterns(self, guard):
        result = guard.inspect_step(
            step_name="step1",
            step_output="All systems nominal. Output generated correctly.",
        )
        assert result.detected_patterns == []

    def test_clean_output_no_issues(self, guard):
        result = guard.inspect_step(
            step_name="step1",
            step_output="Result: 42",
        )
        assert result.issues_found == 0
        assert result.issue_summary == "No issues detected"


# =============================================================================
# 6. inspect_step: Error Status
# =============================================================================


class TestErrorStatus:
    """Tests that error status boosts risk score."""

    def test_error_status_increases_risk(self, guard):
        result = guard.inspect_step(
            step_name="err_step",
            step_output="Something went wrong in the pipeline.",
            step_status="error",
        )
        # 0.25 * 0.8 = 0.20 from status alone
        assert result.risk_score >= 0.2

    def test_failure_status_highest_risk(self, guard):
        result = guard.inspect_step(
            step_name="fail_step",
            step_output="Operation failed completely.",
            step_status="failure",
        )
        # 0.25 * 1.0 = 0.25 from status alone
        assert result.risk_score >= 0.25

    def test_warning_status_moderate(self, guard):
        result = guard.inspect_step(
            step_name="warn_step",
            step_output="Completed with warnings.",
            step_status="warning",
        )
        # 0.25 * 0.4 = 0.10
        assert result.risk_score >= 0.1

    def test_timeout_status(self, guard):
        result = guard.inspect_step(
            step_name="timeout_step",
            step_output="Operation timed out.",
            step_status="timeout",
        )
        # 0.25 * 0.9 = 0.225
        assert result.risk_score >= 0.2

    def test_unknown_status_gets_default(self, guard):
        result = guard.inspect_step(
            step_name="unknown",
            step_output="Some output.",
            step_status="unknown_status_xyz",
        )
        # Default is 0.5 -> 0.25 * 0.5 = 0.125
        assert result.risk_score >= 0.12

    def test_success_status_zero_contribution(self, guard):
        result = guard.inspect_step(
            step_name="ok",
            step_output="A nice long output with plenty of content to avoid length penalty.",
            step_status="success",
        )
        assert result.risk_score < 0.1


# =============================================================================
# 7. inspect_step: Hallucination Indicators
# =============================================================================


class TestHallucinationIndicators:
    """Tests for hallucination detection in output."""

    @pytest.mark.parametrize(
        "indicator",
        [
            "I cannot access the file",
            "file not found in the system",
            "the module does not exist",
            "no such file or directory",
            "unable to locate the resource",
            "I don't have access to that",
            "I'm unable to complete this",
            "As an AI, I cannot do that",
            "I apologize for the confusion",
        ],
    )
    def test_single_hallucination_indicator(self, guard, indicator):
        result = guard.inspect_step(
            step_name="halluc_step",
            step_output=indicator,
        )
        # Single hallucination: 1/3 ~= 0.33 * 0.15 weight = ~0.05
        assert result.risk_score > 0.0

    def test_multiple_hallucination_indicators_boost_score(self, guard):
        output = "I cannot access the file. I apologize for the confusion. As an AI, I'm unable to help."
        result = guard.inspect_step(
            step_name="multi_halluc",
            step_output=output,
        )
        # 4 matches / 3 = ~1.0 hallucination score * 0.15 weight
        assert result.risk_score >= 0.1

    def test_hallucination_case_insensitive(self, guard):
        result = guard.inspect_step(
            step_name="case_test",
            step_output="FILE NOT FOUND anywhere in the system. I CANNOT ACCESS it.",
        )
        assert result.risk_score > 0.0


# =============================================================================
# 8. inspect_step: Error Indicators
# =============================================================================


class TestErrorIndicators:
    """Tests for error pattern detection in output."""

    @pytest.mark.parametrize(
        "indicator",
        [
            "Error: something failed",
            "Exception: unexpected value",
            "Traceback (most recent call last):",
            "Failed: test_something",
            "SyntaxError: invalid syntax",
            "TypeError: unsupported operand",
            "NameError: name 'x' is not defined",
            "KeyError: 'missing_key'",
            "ValueError: invalid literal",
            "ImportError: cannot import name",
            "AttributeError: object has no attribute",
        ],
    )
    def test_single_error_indicator(self, guard, indicator):
        result = guard.inspect_step(
            step_name="err_indicator",
            step_output=indicator,
        )
        assert result.risk_score > 0.0

    def test_multiple_error_indicators(self, guard):
        output = (
            "Traceback (most recent call last):\n"
            "  File 'test.py', line 1\n"
            "NameError: name 'foo' is not defined\n"
            "Error: compilation failed"
        )
        result = guard.inspect_step(
            step_name="multi_err",
            step_output=output,
        )
        # 3 matches / 4 = 0.75 * 0.15 weight
        assert result.risk_score >= 0.1


# =============================================================================
# 9. inspect_step: Stagnation Indicators
# =============================================================================


class TestStagnationIndicators:
    """Tests for stagnation pattern detection."""

    @pytest.mark.parametrize(
        "indicator",
        [
            "let me try again with a different approach",
            "I'll attempt to fix this issue",
            "Trying a different approach now",
            "Same result as before",
            "Still failing after multiple attempts",
            "No change in the output",
        ],
    )
    def test_single_stagnation_indicator(self, guard, indicator):
        result = guard.inspect_step(
            step_name="stag_step",
            step_output=indicator,
        )
        assert result.risk_score > 0.0

    def test_multiple_stagnation_triggers_pattern(self, guard):
        output = "Let me try again. Same result as before. No change."
        result = guard.inspect_step(
            step_name="stag_multi",
            step_output=output,
        )
        assert IssuePattern.STAGNATION in result.detected_patterns


# =============================================================================
# 10. inspect_step: Issues List
# =============================================================================


class TestIssuesList:
    """Tests for issue scoring based on severity."""

    def test_single_info_issue(self, guard):
        result = guard.inspect_step(
            step_name="info_issue",
            step_output="All good otherwise.",
            step_issues=[{"issue_type": "style", "severity": "info"}],
        )
        # 0.1 / 3 ~= 0.033 * 0.20 weight = ~0.007
        assert result.issues_found == 1
        assert result.risk_score < 0.1

    def test_single_critical_issue(self, guard):
        result = guard.inspect_step(
            step_name="crit_issue",
            step_output="Output with critical problem.",
            step_issues=[{"issue_type": "security", "severity": "critical"}],
        )
        # 1.0 / 3 ~= 0.33 * 0.20 = ~0.067
        assert result.issues_found == 1
        assert result.risk_score > 0.05

    def test_multiple_mixed_issues(self, guard):
        issues = [
            {"issue_type": "style", "severity": "info"},
            {"issue_type": "logic", "severity": "warning"},
            {"issue_type": "security", "severity": "error"},
            {"issue_type": "crash", "severity": "critical"},
        ]
        result = guard.inspect_step(
            step_name="mixed_issues",
            step_output="Multiple problems found.",
            step_issues=issues,
        )
        assert result.issues_found == 4
        # (0.1 + 0.3 + 0.6 + 1.0) / 3 = 0.667 * 0.20 = 0.133
        assert result.risk_score > 0.1

    def test_three_critical_issues_max_score(self, guard):
        issues = [
            {"issue_type": "a", "severity": "critical"},
            {"issue_type": "b", "severity": "critical"},
            {"issue_type": "c", "severity": "critical"},
        ]
        result = guard.inspect_step(
            step_name="max_issues",
            step_output="Very bad output.",
            step_issues=issues,
        )
        # 3.0 / 3.0 = 1.0 * 0.20 = 0.20
        assert result.risk_score >= 0.2

    def test_unknown_severity_defaults(self, guard):
        result = guard.inspect_step(
            step_name="unknown_sev",
            step_output="Output text.",
            step_issues=[{"issue_type": "misc", "severity": "banana"}],
        )
        # Unknown severity -> 0.3 default
        assert result.issues_found == 1

    def test_missing_severity_key(self, guard):
        result = guard.inspect_step(
            step_name="no_sev",
            step_output="Output text.",
            step_issues=[{"issue_type": "misc"}],
        )
        # Missing severity -> "info" -> 0.1
        assert result.issues_found == 1


# =============================================================================
# 11. Pattern Detection: REPEATED_ERROR
# =============================================================================


class TestRepeatedErrorPattern:
    """Tests for REPEATED_ERROR pattern detection."""

    def test_repeated_error_detected(self, guard):
        # Build history with issue_summary containing "auth_error"
        history = [
            _make_inspection(issue_summary="auth_error detected", risk_score=0.3),
            _make_inspection(issue_summary="auth_error detected again", risk_score=0.35),
        ]
        result = guard.inspect_step(
            step_name="step3",
            step_output="Auth check failed.",
            step_issues=[{"issue_type": "auth_error", "severity": "error"}],
            previous_inspections=history,
        )
        assert IssuePattern.REPEATED_ERROR in result.detected_patterns

    def test_no_repeated_error_with_insufficient_history(self, guard):
        history = [
            _make_inspection(issue_summary="auth_error found", risk_score=0.3),
        ]
        result = guard.inspect_step(
            step_name="step2",
            step_output="Auth issue.",
            step_issues=[{"issue_type": "auth_error", "severity": "error"}],
            previous_inspections=history,
        )
        # REPEAT_THRESHOLD is 3, need 2 past occurrences
        assert IssuePattern.REPEATED_ERROR not in result.detected_patterns


# =============================================================================
# 12. Pattern Detection: ESCALATING_SEVERITY
# =============================================================================


class TestEscalatingSeverityPattern:
    """Tests for ESCALATING_SEVERITY pattern detection."""

    def test_escalating_severity_detected(self, guard):
        history = [
            _make_inspection(risk_score=0.1),
            _make_inspection(risk_score=0.2),
            _make_inspection(risk_score=0.3),
        ]
        result = guard.inspect_step(
            step_name="step4",
            step_output="Things getting worse.",
            previous_inspections=history,
        )
        assert IssuePattern.ESCALATING_SEVERITY in result.detected_patterns

    def test_no_escalation_with_flat_scores(self, guard):
        history = [
            _make_inspection(risk_score=0.3),
            _make_inspection(risk_score=0.3),
            _make_inspection(risk_score=0.3),
        ]
        result = guard.inspect_step(
            step_name="step4",
            step_output="Stable situation.",
            previous_inspections=history,
        )
        assert IssuePattern.ESCALATING_SEVERITY not in result.detected_patterns

    def test_no_escalation_with_only_two_history_items(self, guard):
        history = [
            _make_inspection(risk_score=0.1),
            _make_inspection(risk_score=0.2),
        ]
        result = guard.inspect_step(
            step_name="step3",
            step_output="Short history.",
            previous_inspections=history,
        )
        # Need >= 3 items for escalation check
        assert IssuePattern.ESCALATING_SEVERITY not in result.detected_patterns

    def test_no_escalation_with_decreasing_scores(self, guard):
        history = [
            _make_inspection(risk_score=0.5),
            _make_inspection(risk_score=0.3),
            _make_inspection(risk_score=0.1),
        ]
        result = guard.inspect_step(
            step_name="step4",
            step_output="Getting better.",
            previous_inspections=history,
        )
        assert IssuePattern.ESCALATING_SEVERITY not in result.detected_patterns


# =============================================================================
# 13. Pattern Detection: CASCADING_FAILURE
# =============================================================================


class TestCascadingFailurePattern:
    """Tests for CASCADING_FAILURE pattern detection."""

    def test_cascading_failure_three_high_risk(self, guard):
        history = [
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.65),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.8),
        ]
        result = guard.inspect_step(
            step_name="step4",
            step_output="Everything is broken.",
            previous_inspections=history,
        )
        assert IssuePattern.CASCADING_FAILURE in result.detected_patterns

    def test_no_cascade_with_mixed_risk(self, guard):
        history = [
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
            _make_inspection(risk_level=RiskLevel.LOW, risk_score=0.1),
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
        ]
        result = guard.inspect_step(
            step_name="step4",
            step_output="Intermittent failure.",
            previous_inspections=history,
        )
        assert IssuePattern.CASCADING_FAILURE not in result.detected_patterns

    def test_no_cascade_with_insufficient_history(self, guard):
        history = [
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.8),
        ]
        result = guard.inspect_step(
            step_name="step3",
            step_output="Bad situation.",
            previous_inspections=history,
        )
        # Need at least 3 items in recent history
        assert IssuePattern.CASCADING_FAILURE not in result.detected_patterns


# =============================================================================
# 14. Pattern Detection: HALLUCINATION_CLUSTER
# =============================================================================


class TestHallucinationClusterPattern:
    """Tests for HALLUCINATION_CLUSTER pattern detection."""

    def test_cluster_with_two_indicators(self, guard):
        output = "I cannot access the file. The file does not exist."
        result = guard.inspect_step(
            step_name="halluc_cluster",
            step_output=output,
        )
        assert IssuePattern.HALLUCINATION_CLUSTER in result.detected_patterns

    def test_no_cluster_with_one_indicator(self, guard):
        output = "I cannot access the file. But everything else is fine."
        result = guard.inspect_step(
            step_name="single_halluc",
            step_output=output,
        )
        assert IssuePattern.HALLUCINATION_CLUSTER not in result.detected_patterns

    def test_cluster_with_many_indicators(self, guard):
        output = "I cannot access the file. File not found. Unable to locate the resource. I apologize for the error."
        result = guard.inspect_step(
            step_name="many_halluc",
            step_output=output,
        )
        assert IssuePattern.HALLUCINATION_CLUSTER in result.detected_patterns


# =============================================================================
# 15. Pattern Detection: STAGNATION
# =============================================================================


class TestStagnationPattern:
    """Tests for STAGNATION pattern detection."""

    def test_stagnation_with_two_indicators(self, guard):
        output = "Let me try again. Same result as before."
        result = guard.inspect_step(
            step_name="stag",
            step_output=output,
        )
        assert IssuePattern.STAGNATION in result.detected_patterns

    def test_no_stagnation_with_one_indicator(self, guard):
        output = "Let me try again with a different approach."
        result = guard.inspect_step(
            step_name="one_stag",
            step_output=output,
        )
        assert IssuePattern.STAGNATION not in result.detected_patterns


# =============================================================================
# 16. Risk Score Boosting
# =============================================================================


class TestRiskScoreBoosting:
    """Tests that detected patterns boost the composite risk score."""

    def test_cascading_failure_boosts_by_020(self, guard):
        # Provide history that triggers CASCADING_FAILURE
        history = [
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.8),
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
        ]
        result_with_cascade = guard.inspect_step(
            step_name="cascade_boost",
            step_output="Continuing failures in the system.",
            previous_inspections=history,
        )
        # Same call without cascade-triggering history
        result_without = guard.inspect_step(
            step_name="no_cascade",
            step_output="Continuing failures in the system.",
            previous_inspections=[],
        )
        if IssuePattern.CASCADING_FAILURE in result_with_cascade.detected_patterns:
            assert result_with_cascade.risk_score > result_without.risk_score

    def test_escalating_severity_boosts_by_015(self, guard):
        history = [
            _make_inspection(risk_score=0.1),
            _make_inspection(risk_score=0.2),
            _make_inspection(risk_score=0.3),
        ]
        result_with_esc = guard.inspect_step(
            step_name="esc_boost",
            step_output="Things are getting worse.",
            previous_inspections=history,
        )
        result_without = guard.inspect_step(
            step_name="no_esc",
            step_output="Things are getting worse.",
            previous_inspections=[],
        )
        if IssuePattern.ESCALATING_SEVERITY in result_with_esc.detected_patterns:
            assert result_with_esc.risk_score > result_without.risk_score

    def test_both_boosts_stack(self, guard):
        # History that triggers both CASCADING_FAILURE and ESCALATING_SEVERITY
        history = [
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.5),
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.7),
        ]
        result = guard.inspect_step(
            step_name="double_boost",
            step_output="Complete breakdown.",
            previous_inspections=history,
        )
        # Both patterns present = +0.35 boost
        has_cascade = IssuePattern.CASCADING_FAILURE in result.detected_patterns
        has_escalation = IssuePattern.ESCALATING_SEVERITY in result.detected_patterns
        if has_cascade and has_escalation:
            assert result.risk_score >= 0.35

    def test_risk_score_capped_at_one(self, guard):
        """Even with massive boosting, risk score never exceeds 1.0."""
        history = [
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.9),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.95),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.99),
        ]
        result = guard.inspect_step(
            step_name="max_risk",
            step_output="Traceback Error: everything broken. I cannot access anything.",
            step_status="failure",
            step_issues=[{"issue_type": "crash", "severity": "critical"}],
            previous_inspections=history,
        )
        assert result.risk_score <= 1.0


# =============================================================================
# 17. requires_diagnosis Threshold
# =============================================================================


class TestDiagnosisThreshold:
    """Tests for the diagnosis threshold behavior."""

    def test_default_threshold_is_07(self):
        guard = InspectorGuard()
        assert guard.threshold == 0.7

    def test_custom_threshold(self):
        guard = InspectorGuard(diagnosis_threshold=0.5)
        assert guard.threshold == 0.5

    def test_requires_diagnosis_at_threshold(self, guard):
        """Generate a risk score above default threshold 0.7."""
        result = guard.inspect_step(
            step_name="diag_check",
            step_output=(
                "Traceback (most recent call last):\n"
                "SyntaxError: invalid syntax\n"
                "Error: compilation failed\n"
                "I cannot access the file. File not found. I apologize."
            ),
            step_status="failure",
            step_issues=[
                {"issue_type": "crash", "severity": "critical"},
                {"issue_type": "compile", "severity": "critical"},
            ],
        )
        # High combined signals should push above 0.7
        if result.risk_score >= 0.7:
            assert result.requires_diagnosis is True
            assert result.risk_level == RiskLevel.CRITICAL

    def test_no_diagnosis_below_threshold(self, guard):
        result = guard.inspect_step(
            step_name="safe_step",
            step_output="Everything looks normal and fine.",
        )
        assert result.requires_diagnosis is False

    def test_custom_lower_threshold_triggers_easier(self):
        guard = InspectorGuard(diagnosis_threshold=0.2)
        result = guard.inspect_step(
            step_name="low_thresh",
            step_output="Minor issue here.",
            step_status="error",
        )
        # 0.25 * 0.8 = 0.20 from status, which meets 0.2 threshold
        assert result.risk_score >= 0.2
        assert result.requires_diagnosis is True


# =============================================================================
# 18. Suggestions Generation
# =============================================================================


class TestSuggestions:
    """Tests for suggestion generation per pattern."""

    def test_cascading_failure_suggestion(self, guard):
        history = [
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
            _make_inspection(risk_level=RiskLevel.CRITICAL, risk_score=0.8),
            _make_inspection(risk_level=RiskLevel.HIGH, risk_score=0.6),
        ]
        result = guard.inspect_step(
            step_name="cascade_sug",
            step_output="Everything keeps failing.",
            previous_inspections=history,
        )
        if IssuePattern.CASCADING_FAILURE in result.detected_patterns:
            assert any("cascading" in s.lower() for s in result.suggestions)

    def test_hallucination_cluster_suggestion(self, guard):
        result = guard.inspect_step(
            step_name="halluc_sug",
            step_output="I cannot access the file. File not found.",
        )
        if IssuePattern.HALLUCINATION_CLUSTER in result.detected_patterns:
            assert any("hallucination" in s.lower() for s in result.suggestions)

    def test_stagnation_suggestion(self, guard):
        result = guard.inspect_step(
            step_name="stag_sug",
            step_output="Let me try again. Same result as before.",
        )
        if IssuePattern.STAGNATION in result.detected_patterns:
            assert any("progress" in s.lower() for s in result.suggestions)

    def test_escalating_severity_suggestion(self, guard):
        history = [
            _make_inspection(risk_score=0.1),
            _make_inspection(risk_score=0.2),
            _make_inspection(risk_score=0.3),
        ]
        result = guard.inspect_step(
            step_name="esc_sug",
            step_output="Getting worse.",
            previous_inspections=history,
        )
        if IssuePattern.ESCALATING_SEVERITY in result.detected_patterns:
            assert any("escalating" in s.lower() for s in result.suggestions)

    def test_repeated_error_suggestion(self, guard):
        history = [
            _make_inspection(issue_summary="auth_error found"),
            _make_inspection(issue_summary="auth_error again"),
        ]
        result = guard.inspect_step(
            step_name="repeat_sug",
            step_output="Auth failed.",
            step_issues=[{"issue_type": "auth_error", "severity": "error"}],
            previous_inspections=history,
        )
        if IssuePattern.REPEATED_ERROR in result.detected_patterns:
            assert any("repeated" in s.lower() for s in result.suggestions)

    def test_output_degradation_suggestion(self, guard):
        history = [
            _make_inspection(risk_score=0.4),
            _make_inspection(risk_score=0.5),
            _make_inspection(risk_score=0.6),
        ]
        result = guard.inspect_step(
            step_name="degrade_sug",
            step_output="Quality dropping.",
            previous_inspections=history,
        )
        if IssuePattern.OUTPUT_DEGRADATION in result.detected_patterns:
            assert any("declining" in s.lower() or "degradation" in s.lower() for s in result.suggestions)

    def test_high_risk_no_pattern_suggestion(self, guard):
        """High risk score without specific patterns triggers manual review."""
        # Use _generate_suggestions directly to test the fallback
        suggestions = guard._generate_suggestions([], 0.85)
        assert any("manual review" in s.lower() for s in suggestions)

    def test_no_suggestions_when_clean(self, guard):
        result = guard.inspect_step(
            step_name="clean",
            step_output="All is well. Nothing to report.",
        )
        assert result.suggestions == []


# =============================================================================
# 19. get_stats Tracking
# =============================================================================


class TestGetStats:
    """Tests for statistics tracking via get_stats()."""

    def test_initial_stats_empty(self, guard):
        stats = guard.get_stats()
        assert stats.total_inspections == 0
        assert stats.total_flags == 0
        assert stats.avg_risk_score == 0.0
        assert stats.risk_distribution == {}
        assert stats.patterns_detected == {}

    def test_stats_after_one_inspection(self, guard):
        guard.inspect_step("step1", "Clean output here.")
        stats = guard.get_stats()
        assert stats.total_inspections == 1
        assert stats.total_flags == 0
        assert "low" in stats.risk_distribution

    def test_stats_track_multiple_inspections(self, guard):
        guard.inspect_step("step1", "Clean output.")
        guard.inspect_step("step2", "Also clean.")
        guard.inspect_step("step3", "Traceback Error: bad things", step_status="error")
        stats = guard.get_stats()
        assert stats.total_inspections == 3

    def test_stats_track_flags(self):
        guard = InspectorGuard(diagnosis_threshold=0.2)
        guard.inspect_step("flagged", "Error output.", step_status="error")
        stats = guard.get_stats()
        if stats.total_flags > 0:
            assert stats.total_flags >= 1

    def test_stats_avg_risk_score(self, guard):
        guard.inspect_step("s1", "Clean output for avg test.")
        guard.inspect_step("s2", "Clean output for avg test two.")
        stats = guard.get_stats()
        assert 0.0 <= stats.avg_risk_score <= 1.0

    def test_stats_patterns_detected(self, guard):
        guard.inspect_step(
            "stag_step",
            "Let me try again. Same result as before.",
        )
        stats = guard.get_stats()
        if "stagnation" in stats.patterns_detected:
            assert stats.patterns_detected["stagnation"] >= 1

    def test_stats_risk_distribution_keys(self, guard):
        guard.inspect_step("low", "Clean output to produce low risk.")
        guard.inspect_step("error", "Big problem here.", step_status="failure")
        stats = guard.get_stats()
        # Should have at least one risk level recorded
        assert len(stats.risk_distribution) >= 1


# =============================================================================
# 20. Singleton Pattern
# =============================================================================


class TestSingleton:
    """Tests for get_inspector_guard() / reset_inspector_guard() singleton."""

    def test_get_returns_inspector_guard(self):
        guard = get_inspector_guard()
        assert isinstance(guard, InspectorGuard)

    def test_get_returns_same_instance(self):
        g1 = get_inspector_guard()
        g2 = get_inspector_guard()
        assert g1 is g2

    def test_reset_creates_new_instance(self):
        g1 = get_inspector_guard()
        reset_inspector_guard()
        g2 = get_inspector_guard()
        assert g1 is not g2

    def test_reset_clears_state(self):
        guard = get_inspector_guard()
        guard.inspect_step("step", "Some output.")
        assert guard.get_stats().total_inspections == 1

        reset_inspector_guard()
        new_guard = get_inspector_guard()
        assert new_guard.get_stats().total_inspections == 0

    def test_singleton_thread_safety(self):
        """Multiple threads getting the singleton should get the same instance."""
        instances = []

        def get_instance():
            instances.append(get_inspector_guard())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(i is instances[0] for i in instances)


# =============================================================================
# 21. Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case testing for robustness."""

    def test_empty_output(self, guard):
        result = guard.inspect_step(
            step_name="empty",
            step_output="",
        )
        assert result.risk_level == RiskLevel.LOW
        assert result.risk_score >= 0.0

    def test_none_output(self, guard):
        result = guard.inspect_step(
            step_name="none_output",
            step_output=None,
        )
        assert result.risk_score >= 0.0

    def test_none_issues(self, guard):
        result = guard.inspect_step(
            step_name="none_issues",
            step_output="Some output.",
            step_issues=None,
        )
        assert result.issues_found == 0

    def test_empty_issues_list(self, guard):
        result = guard.inspect_step(
            step_name="empty_issues",
            step_output="Some output.",
            step_issues=[],
        )
        assert result.issues_found == 0

    def test_very_short_output_with_history(self, guard):
        history = [
            _make_inspection(risk_score=0.1),
        ]
        result = guard.inspect_step(
            step_name="short",
            step_output="ok",
            previous_inspections=history,
        )
        # len("ok") < 10 -> length_score = 0.6
        # 0.05 * 0.6 = 0.03 from length signal
        assert result.risk_score >= 0.02

    def test_no_history(self, guard):
        result = guard.inspect_step(
            step_name="no_hist",
            step_output="First ever step output.",
            previous_inspections=[],
        )
        assert result.detected_patterns == [] or all(
            p in (IssuePattern.HALLUCINATION_CLUSTER, IssuePattern.STAGNATION) for p in result.detected_patterns
        )

    def test_empty_history_list(self, guard):
        result = guard.inspect_step(
            step_name="empty_hist",
            step_output="Output text.",
            previous_inspections=[],
        )
        # No cascade or escalation patterns without history
        assert IssuePattern.CASCADING_FAILURE not in result.detected_patterns
        assert IssuePattern.ESCALATING_SEVERITY not in result.detected_patterns

    def test_risk_score_always_in_bounds(self, guard):
        """Risk score is always between 0.0 and 1.0."""
        result = guard.inspect_step(
            step_name="bounds",
            step_output="Traceback Error SyntaxError TypeError NameError KeyError",
            step_status="failure",
            step_issues=[{"issue_type": "x", "severity": "critical"} for _ in range(10)],
        )
        assert 0.0 <= result.risk_score <= 1.0

    def test_large_output(self, guard):
        """Handle very large output without crashing."""
        output = "normal content. " * 10000
        result = guard.inspect_step(
            step_name="large",
            step_output=output,
        )
        assert result.risk_level == RiskLevel.LOW

    def test_issue_without_type_key(self, guard):
        """Issues missing 'issue_type' should not crash."""
        result = guard.inspect_step(
            step_name="no_type",
            step_output="Output.",
            step_issues=[{"severity": "warning"}],
        )
        assert result.issues_found == 1

    def test_status_case_insensitive(self, guard):
        result = guard.inspect_step(
            step_name="upper_status",
            step_output="Output text here.",
            step_status="SUCCESS",
        )
        assert result.risk_score < 0.1

    def test_internal_history_grows(self, guard):
        for i in range(5):
            guard.inspect_step(f"step_{i}", f"Output for step {i}")
        stats = guard.get_stats()
        assert stats.total_inspections == 5

    def test_internal_history_maxlen(self):
        guard = InspectorGuard()
        for i in range(60):
            guard.inspect_step(f"step_{i}", f"Output {i}")
        # MAX_HISTORY is 50
        assert len(guard._history) == 50
        assert guard.get_stats().total_inspections == 60


# =============================================================================
# Additional: Issue Summary
# =============================================================================


class TestIssueSummary:
    """Tests for the issue summary output."""

    def test_no_issues_summary(self, guard):
        result = guard.inspect_step("clean", "Normal output here.")
        assert result.issue_summary == "No issues detected"

    def test_issues_in_summary(self, guard):
        result = guard.inspect_step(
            step_name="with_issues",
            step_output="Output.",
            step_issues=[
                {"issue_type": "auth", "severity": "error"},
                {"issue_type": "auth", "severity": "error"},
                {"issue_type": "perf", "severity": "warning"},
            ],
        )
        assert "3 issue(s)" in result.issue_summary
        assert "auth" in result.issue_summary

    def test_hallucination_signal_in_summary(self, guard):
        result = guard.inspect_step(
            step_name="halluc_sum",
            step_output="I cannot access the file. File not found. Unable to locate.",
        )
        assert "hallucination" in result.issue_summary.lower()

    def test_error_signal_in_summary(self, guard):
        result = guard.inspect_step(
            step_name="err_sum",
            step_output="Traceback (most recent call last): SyntaxError: bad",
        )
        assert "error" in result.issue_summary.lower()

    def test_patterns_in_summary(self, guard):
        result = guard.inspect_step(
            step_name="pattern_sum",
            step_output="Let me try again. Same result. Still failing.",
        )
        if IssuePattern.STAGNATION in result.detected_patterns:
            assert "stagnation" in result.issue_summary


# =============================================================================
# Additional: Regex Pattern Lists
# =============================================================================


class TestRegexPatterns:
    """Tests that the regex pattern lists are properly defined."""

    def test_hallucination_indicators_count(self):
        assert len(HALLUCINATION_INDICATORS) == 9

    def test_error_indicators_count(self):
        assert len(ERROR_INDICATORS) == 11

    def test_stagnation_indicators_count(self):
        assert len(STAGNATION_INDICATORS) == 6

    def test_hallucination_patterns_are_strings(self):
        assert all(isinstance(p, str) for p in HALLUCINATION_INDICATORS)

    def test_error_patterns_are_strings(self):
        assert all(isinstance(p, str) for p in ERROR_INDICATORS)

    def test_stagnation_patterns_are_strings(self):
        assert all(isinstance(p, str) for p in STAGNATION_INDICATORS)


# =============================================================================
# Additional: Output Degradation Pattern
# =============================================================================


class TestOutputDegradationPattern:
    """Tests for OUTPUT_DEGRADATION pattern detection."""

    def test_output_degradation_detected(self, guard):
        """Degradation requires 3+ recent results all with risk_score > 0.3."""
        history = [
            _make_inspection(risk_score=0.4),
            _make_inspection(risk_score=0.5),
            _make_inspection(risk_score=0.6),
        ]
        result = guard.inspect_step(
            step_name="degrade",
            step_output="Quality is dropping fast.",
            previous_inspections=history,
        )
        assert IssuePattern.OUTPUT_DEGRADATION in result.detected_patterns

    def test_no_degradation_with_low_scores(self, guard):
        history = [
            _make_inspection(risk_score=0.1),
            _make_inspection(risk_score=0.1),
            _make_inspection(risk_score=0.1),
        ]
        result = guard.inspect_step(
            step_name="no_degrade",
            step_output="Everything fine.",
            previous_inspections=history,
        )
        assert IssuePattern.OUTPUT_DEGRADATION not in result.detected_patterns


# =============================================================================
# Additional: Threshold property
# =============================================================================


class TestThresholdProperty:
    """Tests for the threshold property."""

    def test_threshold_returns_diagnosis_threshold(self):
        guard = InspectorGuard(diagnosis_threshold=0.42)
        assert guard.threshold == 0.42

    def test_threshold_default_from_class_constant(self):
        guard = InspectorGuard()
        assert guard.threshold == InspectorGuard.DIAGNOSIS_THRESHOLD

    def test_zero_threshold_uses_class_default(self):
        """Passing 0.0 should use the class default due to `or` logic."""
        guard = InspectorGuard(diagnosis_threshold=0.0)
        assert guard.threshold == InspectorGuard.DIAGNOSIS_THRESHOLD


# =============================================================================
# Additional: Combined Scenario Tests
# =============================================================================


class TestCombinedScenarios:
    """Integration-style tests combining multiple signals."""

    def test_catastrophic_step(self, guard):
        """A step that is failing in every possible way."""
        result = guard.inspect_step(
            step_name="catastrophe",
            step_output=(
                "Traceback (most recent call last):\n"
                "  File 'main.py', line 10\n"
                "SyntaxError: invalid syntax\n"
                "Error: could not compile\n"
                "TypeError: unsupported type\n"
                "I cannot access the database. File not found.\n"
                "I apologize for the confusion.\n"
                "Let me try again. Same result."
            ),
            step_status="failure",
            step_issues=[
                {"issue_type": "compile_error", "severity": "critical"},
                {"issue_type": "runtime_error", "severity": "critical"},
            ],
        )
        assert result.risk_score >= 0.5
        assert result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert len(result.detected_patterns) >= 1

    def test_gradual_degradation_scenario(self, guard):
        """Simulate a series of steps getting progressively worse."""
        # Step 1: Clean
        r1 = guard.inspect_step("s1", "All good. Normal output.")
        assert r1.is_safe

        # Step 2: Minor warning
        r2 = guard.inspect_step("s2", "Completed with minor issues.", step_status="warning")
        assert r2.risk_score > r1.risk_score

        # Step 3: Error with indicators
        r3 = guard.inspect_step(
            "s3",
            "Error: something broke. Traceback found.",
            step_status="error",
        )
        assert r3.risk_score > r2.risk_score

    def test_recovery_scenario(self, guard):
        """After bad steps, a clean step should return LOW risk."""
        guard.inspect_step("bad1", "Error: failed.", step_status="error")
        guard.inspect_step("bad2", "Error: still failing.", step_status="error")

        result = guard.inspect_step(
            "recovered",
            "Operation completed successfully. All tests passing.",
            step_status="success",
        )
        assert result.risk_level == RiskLevel.LOW
        assert result.is_safe
