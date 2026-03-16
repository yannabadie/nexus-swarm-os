"""
Comprehensive tests for ConfidenceCalibrator module.

Tests cover:
- Enum values and dataclass construction
- CalibratedConfidence.is_significant_correction property
- record() with clamping, multiple agents, MAX_HISTORY cap
- calibrate() with insufficient data, overconfident, underconfident, well-calibrated agents
- get_agent_profile() with ECE computation, bias detection, correction factor
- get_stats() with multiple agents, best/worst calibrated
- Bin computation (10 bins, gap calculation)
- ECE computation correctness
- Singleton pattern (get/reset)
- Edge cases: empty history, single record, all successes, all failures
"""

import time

import pytest

from core.intelligence.reasoning.confidence_calibrator import (
    AgentCalibrationProfile,
    CalibratedConfidence,
    CalibrationRecord,
    CalibratorStats,
    ConfidenceBias,
    ConfidenceCalibrator,
    get_confidence_calibrator,
    reset_confidence_calibrator,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def calibrator():
    """Fresh ConfidenceCalibrator instance for each test."""
    return ConfidenceCalibrator()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton before and after each test."""
    reset_confidence_calibrator()
    yield
    reset_confidence_calibrator()


# =============================================================================
# 1. ConfidenceBias Enum
# =============================================================================


class TestConfidenceBias:
    """Tests for the ConfidenceBias enum."""

    def test_well_calibrated_value(self):
        assert ConfidenceBias.WELL_CALIBRATED.value == "well_calibrated"

    def test_overconfident_value(self):
        assert ConfidenceBias.OVERCONFIDENT.value == "overconfident"

    def test_underconfident_value(self):
        assert ConfidenceBias.UNDERCONFIDENT.value == "underconfident"

    def test_insufficient_data_value(self):
        assert ConfidenceBias.INSUFFICIENT_DATA.value == "insufficient_data"

    def test_enum_has_exactly_four_members(self):
        assert len(ConfidenceBias) == 4

    def test_enum_membership(self):
        assert ConfidenceBias("well_calibrated") is ConfidenceBias.WELL_CALIBRATED


# =============================================================================
# 2. CalibrationRecord Dataclass
# =============================================================================


class TestCalibrationRecord:
    """Tests for the CalibrationRecord dataclass."""

    def test_basic_construction(self):
        rec = CalibrationRecord(
            agent_id="claude",
            stated_confidence=0.85,
            actual_success=True,
        )
        assert rec.agent_id == "claude"
        assert rec.stated_confidence == 0.85
        assert rec.actual_success is True
        assert rec.task_type == "general"
        assert isinstance(rec.timestamp, float)

    def test_custom_task_type(self):
        rec = CalibrationRecord(
            agent_id="gemini",
            stated_confidence=0.5,
            actual_success=False,
            task_type="coding",
        )
        assert rec.task_type == "coding"

    def test_custom_timestamp(self):
        ts = 1000000.0
        rec = CalibrationRecord(
            agent_id="x",
            stated_confidence=0.1,
            actual_success=True,
            timestamp=ts,
        )
        assert rec.timestamp == ts

    def test_timestamp_auto_generated(self):
        before = time.time()
        rec = CalibrationRecord(agent_id="a", stated_confidence=0.5, actual_success=True)
        after = time.time()
        assert before <= rec.timestamp <= after


# =============================================================================
# 3. CalibratedConfidence Dataclass
# =============================================================================


class TestCalibratedConfidence:
    """Tests for the CalibratedConfidence dataclass and its property."""

    def test_basic_construction(self):
        cc = CalibratedConfidence(
            raw_confidence=0.8,
            adjusted_confidence=0.7,
            correction=-0.1,
            agent_bias=ConfidenceBias.OVERCONFIDENT,
            reliability=0.5,
        )
        assert cc.raw_confidence == 0.8
        assert cc.adjusted_confidence == 0.7
        assert cc.correction == -0.1
        assert cc.agent_bias == ConfidenceBias.OVERCONFIDENT
        assert cc.reliability == 0.5

    def test_is_significant_correction_true_positive(self):
        cc = CalibratedConfidence(
            raw_confidence=0.8,
            adjusted_confidence=0.6,
            correction=-0.2,
            agent_bias=ConfidenceBias.OVERCONFIDENT,
            reliability=1.0,
        )
        assert cc.is_significant_correction is True

    def test_is_significant_correction_true_negative(self):
        cc = CalibratedConfidence(
            raw_confidence=0.3,
            adjusted_confidence=0.5,
            correction=0.2,
            agent_bias=ConfidenceBias.UNDERCONFIDENT,
            reliability=1.0,
        )
        assert cc.is_significant_correction is True

    def test_is_significant_correction_false_small(self):
        cc = CalibratedConfidence(
            raw_confidence=0.5,
            adjusted_confidence=0.55,
            correction=0.05,
            agent_bias=ConfidenceBias.WELL_CALIBRATED,
            reliability=1.0,
        )
        assert cc.is_significant_correction is False

    def test_is_significant_correction_false_exactly_threshold(self):
        cc = CalibratedConfidence(
            raw_confidence=0.5,
            adjusted_confidence=0.6,
            correction=0.1,
            agent_bias=ConfidenceBias.WELL_CALIBRATED,
            reliability=1.0,
        )
        assert cc.is_significant_correction is False

    def test_is_significant_correction_zero(self):
        cc = CalibratedConfidence(
            raw_confidence=0.5,
            adjusted_confidence=0.5,
            correction=0.0,
            agent_bias=ConfidenceBias.WELL_CALIBRATED,
            reliability=0.0,
        )
        assert cc.is_significant_correction is False


# =============================================================================
# 4. AgentCalibrationProfile Dataclass
# =============================================================================


class TestAgentCalibrationProfile:
    """Tests for the AgentCalibrationProfile dataclass."""

    def test_basic_construction(self):
        profile = AgentCalibrationProfile(
            agent_id="claude",
            total_observations=100,
            ece=0.05,
            bias=ConfidenceBias.WELL_CALIBRATED,
            avg_stated_confidence=0.7,
            avg_actual_success_rate=0.68,
            correction_factor=0.97,
            bins={},
        )
        assert profile.agent_id == "claude"
        assert profile.total_observations == 100
        assert profile.ece == 0.05
        assert profile.bias == ConfidenceBias.WELL_CALIBRATED
        assert profile.avg_stated_confidence == 0.7
        assert profile.avg_actual_success_rate == 0.68
        assert profile.correction_factor == 0.97
        assert profile.bins == {}


# =============================================================================
# 5. CalibratorStats Dataclass
# =============================================================================


class TestCalibratorStats:
    """Tests for the CalibratorStats dataclass."""

    def test_basic_construction(self):
        stats = CalibratorStats(
            total_records=200,
            agents_tracked=["claude", "gemini"],
            avg_ece=0.12,
            best_calibrated_agent="claude",
            worst_calibrated_agent="gemini",
        )
        assert stats.total_records == 200
        assert stats.agents_tracked == ["claude", "gemini"]
        assert stats.avg_ece == 0.12
        assert stats.best_calibrated_agent == "claude"
        assert stats.worst_calibrated_agent == "gemini"


# =============================================================================
# 6. record() Method
# =============================================================================


class TestRecord:
    """Tests for ConfidenceCalibrator.record()."""

    def test_basic_recording(self, calibrator):
        calibrator.record("claude", 0.8, True)
        profile = calibrator.get_agent_profile("claude")
        assert profile.total_observations == 1

    def test_clamps_confidence_above_one(self, calibrator):
        calibrator.record("claude", 1.5, True)
        history = calibrator._records["claude"]
        assert history[0].stated_confidence == 1.0

    def test_clamps_confidence_below_zero(self, calibrator):
        calibrator.record("claude", -0.3, False)
        history = calibrator._records["claude"]
        assert history[0].stated_confidence == 0.0

    def test_records_multiple_agents(self, calibrator):
        calibrator.record("claude", 0.5, True)
        calibrator.record("gemini", 0.6, False)
        calibrator.record("claude", 0.7, True)
        assert len(calibrator._records["claude"]) == 2
        assert len(calibrator._records["gemini"]) == 1

    def test_records_task_type(self, calibrator):
        calibrator.record("claude", 0.5, True, task_type="coding")
        history = calibrator._records["claude"]
        assert history[0].task_type == "coding"

    def test_default_task_type_is_general(self, calibrator):
        calibrator.record("claude", 0.5, True)
        history = calibrator._records["claude"]
        assert history[0].task_type == "general"

    def test_max_history_cap(self, calibrator):
        for _i in range(600):
            calibrator.record("claude", 0.5, True)
        assert len(calibrator._records["claude"]) == ConfidenceCalibrator.MAX_HISTORY

    def test_max_history_keeps_recent_records(self, calibrator):
        for i in range(600):
            calibrator.record("claude", i / 600.0, True)
        # After trimming, the oldest records are dropped
        history = calibrator._records["claude"]
        assert len(history) == 500
        # The first record kept should correspond to index 100 (record 101)
        # stated_confidence = 100/600 = 0.1667 (approximately)
        assert history[0].stated_confidence == pytest.approx(100 / 600.0, abs=0.001)


# =============================================================================
# 7. calibrate() with Insufficient Data
# =============================================================================


class TestCalibrateInsufficientData:
    """Tests for calibrate() when there is insufficient history."""

    def test_no_history_returns_raw(self, calibrator):
        result = calibrator.calibrate("unknown_agent", 0.75)
        assert result.raw_confidence == 0.75
        assert result.adjusted_confidence == 0.75
        assert result.correction == 0.0
        assert result.agent_bias == ConfidenceBias.INSUFFICIENT_DATA
        assert result.reliability == 0.0

    def test_few_records_returns_raw(self, calibrator):
        for _ in range(4):  # Below MIN_OBSERVATIONS=5
            calibrator.record("claude", 0.8, True)
        result = calibrator.calibrate("claude", 0.9)
        assert result.adjusted_confidence == 0.9
        assert result.agent_bias == ConfidenceBias.INSUFFICIENT_DATA

    def test_exactly_min_observations_calibrates(self, calibrator):
        for _ in range(5):
            calibrator.record("claude", 0.8, True)
        result = calibrator.calibrate("claude", 0.8)
        assert result.agent_bias != ConfidenceBias.INSUFFICIENT_DATA

    def test_clamps_raw_input(self, calibrator):
        result = calibrator.calibrate("agent", 1.5)
        assert result.raw_confidence == 1.0
        result2 = calibrator.calibrate("agent", -0.5)
        assert result2.raw_confidence == 0.0


# =============================================================================
# 8. calibrate() with Overconfident Agent
# =============================================================================


class TestCalibrateOverconfident:
    """Tests for calibrate() with an overconfident agent."""

    def test_overconfident_agent_adjusted_down(self, calibrator):
        # Agent states 0.9 confidence but only succeeds 50% of the time
        for i in range(20):
            calibrator.record("claude", 0.9, i % 2 == 0)
        result = calibrator.calibrate("claude", 0.9)
        assert result.adjusted_confidence < result.raw_confidence
        assert result.correction < 0
        assert result.agent_bias == ConfidenceBias.OVERCONFIDENT

    def test_highly_overconfident_large_correction(self, calibrator):
        # Agent always states 0.95 but only succeeds 20% of the time
        for i in range(50):
            calibrator.record("claude", 0.95, i < 10)
        result = calibrator.calibrate("claude", 0.95)
        assert result.adjusted_confidence < 0.85  # Significant downward correction
        assert result.is_significant_correction is True


# =============================================================================
# 9. calibrate() with Underconfident Agent
# =============================================================================


class TestCalibrateUnderconfident:
    """Tests for calibrate() with an underconfident agent."""

    def test_underconfident_agent_adjusted_up(self, calibrator):
        # Agent states 0.3 confidence but succeeds 80% of the time
        for i in range(20):
            calibrator.record("gemini", 0.3, i < 16)
        result = calibrator.calibrate("gemini", 0.3)
        assert result.adjusted_confidence > result.raw_confidence
        assert result.correction > 0
        assert result.agent_bias == ConfidenceBias.UNDERCONFIDENT

    def test_very_underconfident_large_correction(self, calibrator):
        # Agent states 0.1 but succeeds 90% of the time
        for i in range(50):
            calibrator.record("gemini", 0.1, i < 45)
        result = calibrator.calibrate("gemini", 0.1)
        assert result.adjusted_confidence > 0.2
        assert result.is_significant_correction is True


# =============================================================================
# 10. calibrate() with Well-Calibrated Agent
# =============================================================================


class TestCalibrateWellCalibrated:
    """Tests for calibrate() with a well-calibrated agent."""

    def test_well_calibrated_minimal_correction(self, calibrator):
        # Agent states ~0.7 and succeeds ~70% of the time
        for i in range(20):
            calibrator.record("claude", 0.7, i < 14)
        result = calibrator.calibrate("claude", 0.7)
        assert abs(result.correction) < 0.15
        assert result.agent_bias == ConfidenceBias.WELL_CALIBRATED

    def test_perfectly_calibrated_agent(self, calibrator):
        # Agent states confidence that closely matches actual success rate
        # 0.5 confidence, 50% success
        for i in range(50):
            calibrator.record("perfect", 0.5, i < 25)
        result = calibrator.calibrate("perfect", 0.5)
        # Well calibrated, so bias should not be overconfident/underconfident
        assert result.agent_bias == ConfidenceBias.WELL_CALIBRATED
        assert abs(result.correction) < 0.15


# =============================================================================
# 11. get_agent_profile()
# =============================================================================


class TestGetAgentProfile:
    """Tests for get_agent_profile()."""

    def test_empty_profile(self, calibrator):
        profile = calibrator.get_agent_profile("nonexistent")
        assert profile.agent_id == "nonexistent"
        assert profile.total_observations == 0
        assert profile.ece == 0.0
        assert profile.bias == ConfidenceBias.INSUFFICIENT_DATA
        assert profile.avg_stated_confidence == 0.0
        assert profile.avg_actual_success_rate == 0.0
        assert profile.correction_factor == 1.0
        assert profile.bins == {}

    def test_profile_with_data(self, calibrator):
        for i in range(10):
            calibrator.record("claude", 0.8, i < 6)
        profile = calibrator.get_agent_profile("claude")
        assert profile.agent_id == "claude"
        assert profile.total_observations == 10
        assert profile.avg_stated_confidence == pytest.approx(0.8, abs=0.01)
        assert profile.avg_actual_success_rate == pytest.approx(0.6, abs=0.01)

    def test_profile_ece_is_nonnegative(self, calibrator):
        for _i in range(20):
            calibrator.record("claude", 0.5, True)
        profile = calibrator.get_agent_profile("claude")
        assert profile.ece >= 0.0

    def test_profile_overconfident_bias(self, calibrator):
        for i in range(10):
            calibrator.record("claude", 0.9, i < 4)  # 0.9 conf, 0.4 success
        profile = calibrator.get_agent_profile("claude")
        assert profile.bias == ConfidenceBias.OVERCONFIDENT

    def test_profile_underconfident_bias(self, calibrator):
        for i in range(10):
            calibrator.record("claude", 0.2, i < 8)  # 0.2 conf, 0.8 success
        profile = calibrator.get_agent_profile("claude")
        assert profile.bias == ConfidenceBias.UNDERCONFIDENT

    def test_profile_correction_factor_overconfident(self, calibrator):
        for i in range(10):
            calibrator.record("claude", 0.8, i < 4)  # success_rate=0.4, conf=0.8
        profile = calibrator.get_agent_profile("claude")
        # correction_factor = avg_success / avg_confidence = 0.4 / 0.8 = 0.5
        assert profile.correction_factor == pytest.approx(0.5, abs=0.01)

    def test_profile_correction_factor_underconfident(self, calibrator):
        for i in range(10):
            calibrator.record("claude", 0.3, i < 9)  # success_rate=0.9, conf=0.3
        profile = calibrator.get_agent_profile("claude")
        # correction_factor = 0.9 / 0.3 = 3.0
        assert profile.correction_factor == pytest.approx(3.0, abs=0.01)

    def test_profile_bins_has_ten_entries(self, calibrator):
        for _i in range(20):
            calibrator.record("claude", 0.5, True)
        profile = calibrator.get_agent_profile("claude")
        assert len(profile.bins) == 10

    def test_profile_bins_keys_format(self, calibrator):
        for _i in range(10):
            calibrator.record("claude", 0.55, True)
        profile = calibrator.get_agent_profile("claude")
        expected_keys = [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)]
        assert sorted(profile.bins.keys()) == sorted(expected_keys)


# =============================================================================
# 12. get_stats()
# =============================================================================


class TestGetStats:
    """Tests for get_stats()."""

    def test_empty_stats(self, calibrator):
        stats = calibrator.get_stats()
        assert stats.total_records == 0
        assert stats.agents_tracked == []
        assert stats.avg_ece == 0.0
        assert stats.best_calibrated_agent == ""
        assert stats.worst_calibrated_agent == ""

    def test_stats_with_single_agent_below_min_observations(self, calibrator):
        for _ in range(3):
            calibrator.record("claude", 0.5, True)
        stats = calibrator.get_stats()
        assert stats.total_records == 3
        assert "claude" in stats.agents_tracked
        assert stats.avg_ece == 0.0  # Not enough observations to compute ECE

    def test_stats_with_single_agent(self, calibrator):
        for i in range(10):
            calibrator.record("claude", 0.7, i < 7)
        stats = calibrator.get_stats()
        assert stats.total_records == 10
        assert stats.agents_tracked == ["claude"]
        assert stats.best_calibrated_agent == "claude"
        assert stats.worst_calibrated_agent == "claude"

    def test_stats_with_multiple_agents_best_worst(self, calibrator):
        # Well-calibrated agent: states 0.7, succeeds 70%
        for i in range(20):
            calibrator.record("good_agent", 0.7, i < 14)
        # Overconfident agent: states 0.9, succeeds 30%
        for i in range(20):
            calibrator.record("bad_agent", 0.9, i < 6)
        stats = calibrator.get_stats()
        assert stats.total_records == 40
        assert len(stats.agents_tracked) == 2
        assert stats.best_calibrated_agent == "good_agent"
        assert stats.worst_calibrated_agent == "bad_agent"

    def test_stats_avg_ece_computed(self, calibrator):
        for i in range(20):
            calibrator.record("a1", 0.7, i < 14)
        for i in range(20):
            calibrator.record("a2", 0.9, i < 6)
        stats = calibrator.get_stats()
        assert stats.avg_ece > 0.0


# =============================================================================
# 13. MAX_HISTORY Cap
# =============================================================================


class TestMaxHistoryCap:
    """Tests for the MAX_HISTORY trimming behavior."""

    def test_history_capped_at_500(self, calibrator):
        for _ in range(550):
            calibrator.record("agent", 0.5, True)
        assert len(calibrator._records["agent"]) == 500

    def test_history_exactly_500_not_trimmed(self, calibrator):
        for _ in range(500):
            calibrator.record("agent", 0.5, True)
        assert len(calibrator._records["agent"]) == 500

    def test_history_below_max_not_trimmed(self, calibrator):
        for _ in range(499):
            calibrator.record("agent", 0.5, True)
        assert len(calibrator._records["agent"]) == 499


# =============================================================================
# 14. Bin Computation
# =============================================================================


class TestBinComputation:
    """Tests for internal _compute_bins() method."""

    def test_ten_bins_always_returned(self, calibrator):
        records = [
            CalibrationRecord("a", 0.55, True),
        ]
        bins = calibrator._compute_bins(records)
        assert len(bins) == 10

    def test_empty_bins_have_zero_count(self, calibrator):
        records = [
            CalibrationRecord("a", 0.55, True),
        ]
        bins = calibrator._compute_bins(records)
        # Only bin "0.5-0.6" should have count > 0
        for key, data in bins.items():
            if key == "0.5-0.6":
                assert data["count"] == 1
            else:
                assert data["count"] == 0

    def test_gap_is_confidence_minus_accuracy(self, calibrator):
        # Put all records in same bin (0.8-0.9), confidence=0.85, all fail
        records = [
            CalibrationRecord("a", 0.85, False),
            CalibrationRecord("a", 0.85, False),
            CalibrationRecord("a", 0.85, False),
        ]
        bins = calibrator._compute_bins(records)
        bin_data = bins["0.8-0.9"]
        assert bin_data["avg_confidence"] == pytest.approx(0.85, abs=0.01)
        assert bin_data["avg_accuracy"] == pytest.approx(0.0, abs=0.01)
        assert bin_data["gap"] == pytest.approx(0.85, abs=0.01)

    def test_gap_negative_when_underconfident(self, calibrator):
        # confidence=0.25, all succeed
        records = [
            CalibrationRecord("a", 0.25, True),
            CalibrationRecord("a", 0.25, True),
        ]
        bins = calibrator._compute_bins(records)
        bin_data = bins["0.2-0.3"]
        assert bin_data["gap"] < 0  # confidence < accuracy

    def test_confidence_1_0_goes_to_last_bin(self, calibrator):
        records = [
            CalibrationRecord("a", 1.0, True),
        ]
        bins = calibrator._compute_bins(records)
        last_bin = bins["0.9-1.0"]
        assert last_bin["count"] == 1

    def test_confidence_0_0_goes_to_first_bin(self, calibrator):
        records = [
            CalibrationRecord("a", 0.0, False),
        ]
        bins = calibrator._compute_bins(records)
        first_bin = bins["0.0-0.1"]
        assert first_bin["count"] == 1


# =============================================================================
# 15. ECE Computation
# =============================================================================


class TestECEComputation:
    """Tests for Expected Calibration Error computation."""

    def test_ece_zero_for_empty_bins(self, calibrator):
        bins = calibrator._compute_bins([])
        ece = calibrator._compute_ece(bins)
        assert ece == 0.0

    def test_ece_zero_for_perfectly_calibrated(self, calibrator):
        # confidence=0.55, accuracy=0.55 (gap=0)
        records = []
        for i in range(20):
            records.append(CalibrationRecord("a", 0.55, i < 11))
        bins = calibrator._compute_bins(records)
        ece = calibrator._compute_ece(bins)
        # With discrete bins and counts, gap should be close to 0
        assert ece < 0.1

    def test_ece_high_for_miscalibrated(self, calibrator):
        # Agent always says 0.95 but always fails
        records = [CalibrationRecord("a", 0.95, False) for _ in range(20)]
        bins = calibrator._compute_bins(records)
        ece = calibrator._compute_ece(bins)
        assert ece > 0.5  # Very high ECE

    def test_ece_is_weighted_average_of_gaps(self, calibrator):
        # All records in one bin: confidence=0.75, 50% accuracy
        records = [CalibrationRecord("a", 0.75, i < 5) for i in range(10)]
        bins = calibrator._compute_bins(records)
        ece = calibrator._compute_ece(bins)
        # Gap = 0.75 - 0.5 = 0.25, weighted by 10/10 = 1.0 => ECE = 0.25
        assert ece == pytest.approx(0.25, abs=0.01)


# =============================================================================
# 16. Singleton Pattern
# =============================================================================


class TestSingleton:
    """Tests for the singleton pattern."""

    def test_get_returns_instance(self):
        cal = get_confidence_calibrator()
        assert isinstance(cal, ConfidenceCalibrator)

    def test_get_returns_same_instance(self):
        cal1 = get_confidence_calibrator()
        cal2 = get_confidence_calibrator()
        assert cal1 is cal2

    def test_reset_creates_new_instance(self):
        cal1 = get_confidence_calibrator()
        reset_confidence_calibrator()
        cal2 = get_confidence_calibrator()
        assert cal1 is not cal2

    def test_reset_clears_data(self):
        cal = get_confidence_calibrator()
        cal.record("claude", 0.8, True)
        reset_confidence_calibrator()
        cal2 = get_confidence_calibrator()
        profile = cal2.get_agent_profile("claude")
        assert profile.total_observations == 0


# =============================================================================
# 17. Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_single_record_insufficient_for_calibration(self, calibrator):
        calibrator.record("claude", 0.8, True)
        result = calibrator.calibrate("claude", 0.8)
        assert result.agent_bias == ConfidenceBias.INSUFFICIENT_DATA

    def test_all_successes(self, calibrator):
        for _ in range(20):
            calibrator.record("claude", 0.7, True)
        profile = calibrator.get_agent_profile("claude")
        assert profile.avg_actual_success_rate == 1.0
        assert profile.bias == ConfidenceBias.UNDERCONFIDENT

    def test_all_failures(self, calibrator):
        for _ in range(20):
            calibrator.record("claude", 0.7, False)
        profile = calibrator.get_agent_profile("claude")
        assert profile.avg_actual_success_rate == 0.0
        assert profile.bias == ConfidenceBias.OVERCONFIDENT

    def test_calibrate_confidence_zero(self, calibrator):
        for _ in range(10):
            calibrator.record("claude", 0.5, True)
        result = calibrator.calibrate("claude", 0.0)
        assert result.adjusted_confidence >= 0.0

    def test_calibrate_confidence_one(self, calibrator):
        for _ in range(10):
            calibrator.record("claude", 0.5, True)
        result = calibrator.calibrate("claude", 1.0)
        assert result.adjusted_confidence <= 1.0

    def test_adjusted_confidence_always_clamped_0_to_1(self, calibrator):
        # Extremely overconfident agent
        for _ in range(50):
            calibrator.record("claude", 0.99, False)
        result = calibrator.calibrate("claude", 0.99)
        assert 0.0 <= result.adjusted_confidence <= 1.0

    def test_adjusted_confidence_clamped_underconfident(self, calibrator):
        # Extremely underconfident agent
        for _ in range(50):
            calibrator.record("claude", 0.01, True)
        result = calibrator.calibrate("claude", 0.01)
        assert 0.0 <= result.adjusted_confidence <= 1.0

    def test_reliability_scales_with_history_size(self, calibrator):
        # Reliability = min(1.0, len(history) / 50.0)
        for _i in range(10):
            calibrator.record("claude", 0.5, True)
        result = calibrator.calibrate("claude", 0.5)
        assert result.reliability == pytest.approx(10 / 50.0, abs=0.01)

    def test_reliability_caps_at_1(self, calibrator):
        for _ in range(100):
            calibrator.record("claude", 0.5, True)
        result = calibrator.calibrate("claude", 0.5)
        assert result.reliability == 1.0

    def test_correction_factor_with_near_zero_confidence(self, calibrator):
        # If avg_confidence < 0.01, correction_factor = 1.0
        for _ in range(10):
            calibrator.record("claude", 0.005, True)
        profile = calibrator.get_agent_profile("claude")
        assert profile.correction_factor == 1.0

    def test_profile_with_insufficient_data_but_some_records(self, calibrator):
        for _ in range(3):
            calibrator.record("claude", 0.5, True)
        profile = calibrator.get_agent_profile("claude")
        assert profile.total_observations == 3
        assert profile.bias == ConfidenceBias.INSUFFICIENT_DATA

    def test_multiple_agents_independent_calibration(self, calibrator):
        # Agent A: overconfident
        for i in range(10):
            calibrator.record("agent_a", 0.9, i < 3)
        # Agent B: underconfident
        for i in range(10):
            calibrator.record("agent_b", 0.2, i < 8)

        result_a = calibrator.calibrate("agent_a", 0.9)
        result_b = calibrator.calibrate("agent_b", 0.2)

        assert result_a.agent_bias == ConfidenceBias.OVERCONFIDENT
        assert result_b.agent_bias == ConfidenceBias.UNDERCONFIDENT

    def test_bias_threshold_boundary_well_calibrated(self, calibrator):
        # avg_confidence - avg_success <= BIAS_THRESHOLD = 0.05
        # conf=0.54, 10/20 success => gap = 0.54 - 0.5 = 0.04 <= 0.05
        for i in range(20):
            calibrator.record("claude", 0.54, i < 10)
        profile = calibrator.get_agent_profile("claude")
        assert profile.bias == ConfidenceBias.WELL_CALIBRATED

    def test_bias_threshold_boundary_just_overconfident(self, calibrator):
        # avg_confidence - avg_success > 0.05
        # conf=0.56, 10/20 success => gap = 0.56 - 0.5 = 0.06 > 0.05
        for i in range(20):
            calibrator.record("claude", 0.56, i < 10)
        profile = calibrator.get_agent_profile("claude")
        assert profile.bias == ConfidenceBias.OVERCONFIDENT


# =============================================================================
# Additional: _apply_correction internals
# =============================================================================


class TestApplyCorrection:
    """Tests for the internal _apply_correction behavior."""

    def test_bin_level_correction_used_when_enough_samples(self, calibrator):
        # Put 5 records in the 0.8-0.9 bin, all failing
        for _ in range(5):
            calibrator.record("claude", 0.85, False)
        # The bin has count=5 >= 3, so bin-level correction is used
        # gap = 0.85 - 0.0 = 0.85, correction = raw - gap*0.7
        result = calibrator.calibrate("claude", 0.85)
        expected_adjusted = 0.85 - 0.85 * 0.7  # = 0.255
        assert result.adjusted_confidence == pytest.approx(expected_adjusted, abs=0.05)

    def test_global_correction_used_when_few_bin_samples(self, calibrator):
        # Spread records across bins so no bin has >= 3
        calibrator.record("claude", 0.15, True)
        calibrator.record("claude", 0.35, True)
        calibrator.record("claude", 0.55, False)
        calibrator.record("claude", 0.75, True)
        calibrator.record("claude", 0.95, False)
        # Each bin has 1 record, so global correction factor is used
        # avg_conf = (0.15+0.35+0.55+0.75+0.95)/5 = 0.55
        # avg_success = 3/5 = 0.6
        # correction_factor = 0.6 / 0.55 = 1.0909...
        # For raw=0.55: adjusted = 0.55 * 1.0909 = 0.6
        result = calibrator.calibrate("claude", 0.55)
        assert result.adjusted_confidence == pytest.approx(0.55 * (0.6 / 0.55), abs=0.05)


# =============================================================================
# Constants
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_num_bins(self):
        assert ConfidenceCalibrator.NUM_BINS == 10

    def test_min_observations(self):
        assert ConfidenceCalibrator.MIN_OBSERVATIONS == 5

    def test_max_history(self):
        assert ConfidenceCalibrator.MAX_HISTORY == 500

    def test_ece_good_threshold(self):
        assert ConfidenceCalibrator.ECE_GOOD_THRESHOLD == 0.1

    def test_bias_threshold(self):
        assert ConfidenceCalibrator.BIAS_THRESHOLD == 0.05
