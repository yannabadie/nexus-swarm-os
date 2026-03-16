"""Tests for CognitiveDegradationDetector."""

import pytest

from core.intelligence.reasoning.cognitive_degradation import (
    CognitiveDegradationDetector,
    DegradationReason,
    DegradationSignal,
    DetectorStats,
    Mitigation,
    get_degradation_detector,
    reset_degradation_detector,
)
from core.intelligence.reasoning.reasoning_quality_scorer import (
    get_quality_scorer,
    reset_quality_scorer,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset singletons before each test."""
    reset_quality_scorer()
    reset_degradation_detector()
    yield
    reset_quality_scorer()
    reset_degradation_detector()


def _feed_evaluations(agent_id: str, composites: list[float], confidence: float = 0.8):
    """Feed evaluations with specified composite scores (depth=coherence=completeness=composite)."""
    scorer = get_quality_scorer()
    for c in composites:
        scorer.record_evaluation(
            agent_id=agent_id,
            task_domain="coding",
            depth_score=c,
            coherence_score=c,
            completeness_score=c,
            confidence=confidence,
            actual_outcome_quality=c,
        )


class TestDegradationSignal:
    """Tests for the DegradationSignal dataclass."""

    def test_defaults(self):
        s = DegradationSignal()
        assert not s.degraded
        assert s.reason == DegradationReason.STABLE
        assert s.mitigation == Mitigation.NONE
        assert s.current_composite == 0.0

    def test_to_dict(self):
        s = DegradationSignal(
            agent_id="claude",
            degraded=True,
            reason=DegradationReason.TREND_DECLINE,
            mitigation=Mitigation.REDUCE_LOAD,
            current_composite=0.5,
            trend_slope=-0.03,
            window_size=10,
            details="test",
        )
        d = s.to_dict()
        assert d["agent_id"] == "claude"
        assert d["degraded"] is True
        assert d["reason"] == "trend_decline"
        assert d["mitigation"] == "reduce_load"


class TestDetectorStats:
    """Tests for DetectorStats."""

    def test_to_dict(self):
        stats = DetectorStats(
            checks_performed=5,
            degradations_detected=2,
            agents_monitored=1,
            mitigations_issued={"context_reset": 1, "agent_switch": 1},
        )
        d = stats.to_dict()
        assert d["checks_performed"] == 5
        assert d["mitigations_issued"]["context_reset"] == 1


class TestInsufficientData:
    """Tests for edge case: not enough evaluations."""

    def test_no_evaluations(self):
        detector = CognitiveDegradationDetector()
        signal = detector.check_agent("claude")
        assert not signal.degraded
        assert signal.window_size == 0
        assert "Insufficient" in signal.details

    def test_one_evaluation(self):
        _feed_evaluations("claude", [0.8])
        detector = CognitiveDegradationDetector()
        signal = detector.check_agent("claude")
        assert not signal.degraded
        assert signal.window_size == 1


class TestStableQuality:
    """Tests for detecting stable quality (no degradation)."""

    def test_consistent_high(self):
        _feed_evaluations("claude", [0.85, 0.88, 0.82, 0.87, 0.84])
        detector = CognitiveDegradationDetector()
        signal = detector.check_agent("claude")
        assert not signal.degraded
        assert signal.reason == DegradationReason.STABLE
        assert "stable" in signal.details.lower()

    def test_improving_trend(self):
        _feed_evaluations("claude", [0.5, 0.55, 0.6, 0.65, 0.7])
        detector = CognitiveDegradationDetector()
        signal = detector.check_agent("claude")
        assert not signal.degraded
        assert signal.trend_slope > 0


class TestSuddenCollapse:
    """Tests for sudden quality collapse detection."""

    def test_large_drop(self):
        _feed_evaluations("claude", [0.85, 0.88, 0.82, 0.87, 0.50])
        detector = CognitiveDegradationDetector(collapse_drop=0.3)
        signal = detector.check_agent("claude")
        assert signal.degraded
        assert signal.reason == DegradationReason.SUDDEN_COLLAPSE
        assert signal.mitigation == Mitigation.CONTEXT_RESET

    def test_small_drop_not_collapse(self):
        _feed_evaluations("claude", [0.85, 0.88, 0.82, 0.87, 0.80])
        detector = CognitiveDegradationDetector(collapse_drop=0.3)
        signal = detector.check_agent("claude")
        assert signal.reason != DegradationReason.SUDDEN_COLLAPSE


class TestSustainedLow:
    """Tests for sustained low quality detection."""

    def test_three_consecutive_low(self):
        _feed_evaluations("claude", [0.8, 0.7, 0.35, 0.30, 0.25])
        detector = CognitiveDegradationDetector(
            low_quality_threshold=0.4,
            sustained_low_count=3,
        )
        signal = detector.check_agent("claude")
        assert signal.degraded
        assert signal.reason == DegradationReason.SUSTAINED_LOW
        assert signal.mitigation == Mitigation.AGENT_SWITCH

    def test_two_consecutive_low_not_enough(self):
        _feed_evaluations("claude", [0.8, 0.7, 0.5, 0.30, 0.25])
        detector = CognitiveDegradationDetector(
            low_quality_threshold=0.4,
            sustained_low_count=3,
        )
        # Last 3: [0.5, 0.30, 0.25] — 0.5 >= 0.4, so not all below
        signal = detector.check_agent("claude")
        # This won't trigger sustained_low since 0.5 >= 0.4
        assert signal.reason != DegradationReason.SUSTAINED_LOW or not signal.degraded


class TestTrendDecline:
    """Tests for declining trend detection."""

    def test_clear_declining_trend(self):
        _feed_evaluations("claude", [0.9, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45])
        detector = CognitiveDegradationDetector(trend_threshold=-0.02)
        signal = detector.check_agent("claude")
        assert signal.degraded
        assert signal.reason == DegradationReason.TREND_DECLINE
        assert signal.mitigation == Mitigation.REDUCE_LOAD
        assert signal.trend_slope < 0

    def test_slight_decline_not_triggered(self):
        _feed_evaluations("claude", [0.82, 0.81, 0.80, 0.79, 0.80])
        detector = CognitiveDegradationDetector(trend_threshold=-0.02)
        signal = detector.check_agent("claude")
        assert not signal.degraded


class TestCalibrationDrift:
    """Tests for confidence calibration drift detection."""

    def test_overconfident_agent(self):
        scorer = get_quality_scorer()
        for _ in range(5):
            scorer.record_evaluation(
                agent_id="gemini",
                task_domain="coding",
                depth_score=0.6,
                coherence_score=0.6,
                completeness_score=0.6,
                confidence=0.95,  # Very confident
                actual_outcome_quality=0.3,  # But poor outcomes
            )
        detector = CognitiveDegradationDetector(
            calibration_drift_threshold=0.5,
        )
        signal = detector.check_agent("gemini")
        assert signal.degraded
        assert signal.reason == DegradationReason.CALIBRATION_DRIFT

    def test_well_calibrated(self):
        scorer = get_quality_scorer()
        for _ in range(5):
            scorer.record_evaluation(
                agent_id="gemini",
                task_domain="coding",
                depth_score=0.8,
                coherence_score=0.8,
                completeness_score=0.8,
                confidence=0.8,
                actual_outcome_quality=0.8,
            )
        detector = CognitiveDegradationDetector(
            calibration_drift_threshold=0.5,
        )
        signal = detector.check_agent("gemini")
        assert not signal.degraded


class TestPriorityOrder:
    """Tests that patterns are checked in severity order."""

    def test_collapse_takes_priority_over_sustained(self):
        """Sudden collapse should be detected even if sustained_low also matches."""
        _feed_evaluations("claude", [0.3, 0.35, 0.85, 0.80, 0.10])
        detector = CognitiveDegradationDetector(
            collapse_drop=0.3,
            sustained_low_count=2,
            low_quality_threshold=0.4,
        )
        signal = detector.check_agent("claude")
        assert signal.degraded
        # Collapse (0.80 -> 0.10 = 0.70 drop) should be first
        assert signal.reason == DegradationReason.SUDDEN_COLLAPSE


class TestMultipleAgents:
    """Tests for monitoring multiple agents independently."""

    def test_independent_agents(self):
        _feed_evaluations("claude", [0.9, 0.85, 0.80, 0.75, 0.70])
        _feed_evaluations("gemini", [0.5, 0.55, 0.60, 0.65, 0.70])

        detector = CognitiveDegradationDetector(
            trend_threshold=-0.02,
        )
        claude_signal = detector.check_agent("claude")
        gemini_signal = detector.check_agent("gemini")

        # Claude declining, Gemini improving
        assert claude_signal.trend_slope < 0
        assert gemini_signal.trend_slope > 0


class TestComputeSlope:
    """Tests for the linear regression slope computation."""

    def test_flat(self):
        slope = CognitiveDegradationDetector._compute_slope([0.5, 0.5, 0.5])
        assert abs(slope) < 1e-10

    def test_increasing(self):
        slope = CognitiveDegradationDetector._compute_slope([0.1, 0.2, 0.3, 0.4])
        assert slope > 0
        assert abs(slope - 0.1) < 1e-10

    def test_decreasing(self):
        slope = CognitiveDegradationDetector._compute_slope([0.4, 0.3, 0.2, 0.1])
        assert slope < 0
        assert abs(slope - (-0.1)) < 1e-10

    def test_empty(self):
        slope = CognitiveDegradationDetector._compute_slope([])
        assert slope == 0.0

    def test_single(self):
        slope = CognitiveDegradationDetector._compute_slope([0.5])
        assert slope == 0.0


class TestDetectorStatsTracking:
    """Tests for detector statistics tracking."""

    def test_stats_after_checks(self):
        _feed_evaluations("claude", [0.9, 0.85, 0.80, 0.10])
        detector = CognitiveDegradationDetector(collapse_drop=0.3)

        detector.check_agent("claude")
        stats = detector.get_stats()

        assert stats.checks_performed == 1
        assert stats.degradations_detected == 1
        assert stats.agents_monitored == 1
        assert stats.mitigations_issued.get("context_reset", 0) == 1

    def test_clear(self):
        _feed_evaluations("claude", [0.9, 0.10])
        detector = CognitiveDegradationDetector(collapse_drop=0.3)
        detector.check_agent("claude")

        detector.clear()
        stats = detector.get_stats()
        assert stats.checks_performed == 0
        assert stats.degradations_detected == 0


class TestSingleton:
    """Tests for global singleton pattern."""

    def test_get_returns_same_instance(self):
        d1 = get_degradation_detector()
        d2 = get_degradation_detector()
        assert d1 is d2

    def test_reset_creates_new_instance(self):
        d1 = get_degradation_detector()
        reset_degradation_detector()
        d2 = get_degradation_detector()
        assert d1 is not d2
