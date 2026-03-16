"""Tests for V12.4 stepwise confidence monitor.

Verifies per-phase confidence tracking, trajectory analysis,
abort recommendations, and trend detection for the HiveMind pipeline.
"""

from core.intelligence.hive_mind.confidence_monitor import (
    DEPTH_FLOOR,
    AbortRecommendation,
    PhaseConfidence,
    StepwiseConfidenceMonitor,
)


class TestPhaseConfidenceRecording:
    """Test basic confidence recording."""

    def test_record_single_phase(self):
        monitor = StepwiseConfidenceMonitor()
        entry = monitor.record("analysis", 0.85)
        assert entry.phase == "analysis"
        assert entry.confidence == 0.85
        assert entry.depth == 0
        assert monitor.phase_count == 1

    def test_record_multiple_phases(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85)
        monitor.record("debate", 0.72)
        monitor.record("architecture", 0.80)
        assert monitor.phase_count == 3

    def test_depth_increments(self):
        monitor = StepwiseConfidenceMonitor()
        e1 = monitor.record("analysis", 0.85)
        e2 = monitor.record("debate", 0.72)
        e3 = monitor.record("architecture", 0.80)
        assert e1.depth == 0
        assert e2.depth == 1
        assert e3.depth == 2

    def test_confidence_clamped_to_0_1(self):
        monitor = StepwiseConfidenceMonitor()
        e1 = monitor.record("over", 1.5)
        e2 = monitor.record("under", -0.3)
        assert e1.confidence == 1.0
        assert e2.confidence == 0.0

    def test_metadata_stored(self):
        monitor = StepwiseConfidenceMonitor()
        entry = monitor.record("analysis", 0.85, agreement_score=0.9, agents=2)
        assert entry.metadata["agreement_score"] == 0.9
        assert entry.metadata["agents"] == 2

    def test_latest_confidence(self):
        monitor = StepwiseConfidenceMonitor()
        assert monitor.latest_confidence == 1.0  # Default before any recording
        monitor.record("analysis", 0.85)
        assert monitor.latest_confidence == 0.85
        monitor.record("debate", 0.72)
        assert monitor.latest_confidence == 0.72

    def test_reset_clears_entries(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85)
        monitor.record("debate", 0.72)
        monitor.reset()
        assert monitor.phase_count == 0
        assert monitor.latest_confidence == 1.0


class TestAbortRecommendation:
    """Test abort decision logic."""

    def test_no_data_no_abort(self):
        monitor = StepwiseConfidenceMonitor()
        rec = monitor.should_abort()
        assert not rec.should_abort
        assert "No confidence data" in rec.reason

    def test_high_confidence_no_abort(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85)
        monitor.record("debate", 0.80)
        rec = monitor.should_abort()
        assert not rec.should_abort

    def test_below_depth_floor_aborts(self):
        monitor = StepwiseConfidenceMonitor()
        # Depth 0 floor is 0.40
        monitor.record("analysis", 0.20)
        rec = monitor.should_abort()
        assert rec.should_abort
        assert "below floor" in rec.reason

    def test_sharp_drop_aborts(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.90)
        monitor.record("debate", 0.50)  # Drop of 0.40 > 0.25 threshold
        rec = monitor.should_abort()
        assert rec.should_abort
        assert "Sharp confidence drop" in rec.reason

    def test_gradual_decline_no_abort(self):
        """Small decline within threshold should not abort."""
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.80)
        monitor.record("debate", 0.70)  # Drop of 0.10 < 0.25
        rec = monitor.should_abort()
        assert not rec.should_abort

    def test_low_average_aborts(self):
        # To test average path, we need values that are individually above their
        # depth floors and don't have sharp drops, but average below AVERAGE_FLOOR.
        # Depth floors: 0=0.40, 1=0.35, 2=0.30, 3=0.25, 4=0.20, 5=0.15
        # Use values just above floors but averaging below 0.30
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.42)  # depth 0, floor 0.40 -> OK
        monitor.record("debate", 0.36)  # depth 1, floor 0.35 -> OK, drop 0.06
        monitor.record("architecture", 0.31)  # depth 2, floor 0.30 -> OK, drop 0.05
        monitor.record("execution", 0.26)  # depth 3, floor 0.25 -> OK, drop 0.05
        monitor.record("diagnosis", 0.21)  # depth 4, floor 0.20 -> OK, drop 0.05
        # Average = (0.42 + 0.36 + 0.31 + 0.26 + 0.21) / 5 = 0.312
        # Still above 0.30, add one more
        monitor.record("retry", 0.16)  # depth 5, floor 0.15 -> OK, drop 0.05
        # Average = (0.42+0.36+0.31+0.26+0.21+0.16)/6 = 0.287, below 0.30
        rec = monitor.should_abort()
        assert rec.should_abort
        assert "Average confidence" in rec.reason

    def test_depth_floor_decreases_with_depth(self):
        """Later phases have lower floors since we've invested more."""
        assert DEPTH_FLOOR[0] > DEPTH_FLOOR[3]
        assert DEPTH_FLOOR[3] > DEPTH_FLOOR[6]

    def test_custom_abort_threshold(self):
        monitor = StepwiseConfidenceMonitor(abort_threshold=0.50)
        monitor.record("analysis", 0.60)
        monitor.record("debate", 0.40)
        # Average = 0.50, not below 0.50
        rec = monitor.should_abort()
        # The sharp drop check: 0.60 -> 0.40 = 0.20, not > 0.25
        # The average check: 0.50 not < 0.50
        # The depth floor check: 0.40 at depth 1, floor = 0.35
        assert not rec.should_abort


class TestTrajectoryAnalysis:
    """Test trajectory computation."""

    def test_empty_trajectory(self):
        monitor = StepwiseConfidenceMonitor()
        traj = monitor.get_trajectory()
        assert traj.trend == "insufficient_data"
        assert traj.average == 0.0
        assert not traj.drop_detected

    def test_single_entry_insufficient(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85)
        traj = monitor.get_trajectory()
        assert traj.trend == "insufficient_data"
        assert traj.latest == 0.85

    def test_improving_trend(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.50)
        monitor.record("debate", 0.65)
        monitor.record("architecture", 0.80)
        traj = monitor.get_trajectory()
        assert traj.trend == "improving"

    def test_declining_trend(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.90)
        monitor.record("debate", 0.70)
        monitor.record("architecture", 0.50)
        traj = monitor.get_trajectory()
        assert traj.trend == "declining"

    def test_stable_trend(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.80)
        monitor.record("debate", 0.79)
        monitor.record("architecture", 0.81)
        traj = monitor.get_trajectory()
        assert traj.trend == "stable"

    def test_drop_detected(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.90)
        monitor.record("debate", 0.60)  # Drop of 0.30
        traj = monitor.get_trajectory()
        assert traj.drop_detected

    def test_no_drop_detected(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.80)
        monitor.record("debate", 0.75)
        traj = monitor.get_trajectory()
        assert not traj.drop_detected

    def test_trajectory_stats(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.90)
        monitor.record("debate", 0.70)
        monitor.record("architecture", 0.80)
        traj = monitor.get_trajectory()
        assert traj.minimum == 0.70
        assert traj.maximum == 0.90
        assert abs(traj.average - 0.80) < 0.01
        assert traj.latest == 0.80


class TestSerialization:
    """Test to_dict serialization."""

    def test_phase_confidence_to_dict(self):
        entry = PhaseConfidence(phase="analysis", confidence=0.85, depth=0, metadata={"k": "v"})
        d = entry.to_dict()
        assert d["phase"] == "analysis"
        assert d["confidence"] == 0.85
        assert d["depth"] == 0
        assert d["metadata"]["k"] == "v"

    def test_monitor_to_dict(self):
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85)
        monitor.record("debate", 0.72)
        d = monitor.to_dict()
        assert "trend" in d
        assert "phases" in d
        assert len(d["phases"]) == 2

    def test_abort_recommendation_to_dict(self):
        rec = AbortRecommendation(should_abort=True, reason="test", confidence=0.2, threshold=0.4)
        d = rec.to_dict()
        assert d["should_abort"] is True
        assert d["reason"] == "test"


class TestPipelineScenarios:
    """Integration-style tests for realistic pipeline scenarios."""

    def test_healthy_pipeline(self):
        """A normal successful pipeline run."""
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85, agreement_score=0.9)
        assert not monitor.should_abort().should_abort

        monitor.record("debate", 0.80, consensus=0.85)
        assert not monitor.should_abort().should_abort

        monitor.record("architecture", 0.82)
        assert not monitor.should_abort().should_abort

        monitor.record("execution", 0.90, success=True)
        assert not monitor.should_abort().should_abort

        traj = monitor.get_trajectory()
        assert traj.trend in ("stable", "improving")
        assert traj.minimum >= 0.80

    def test_struggling_pipeline_early_abort(self):
        """Low analysis confidence should abort early."""
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.30)
        rec = monitor.should_abort()
        assert rec.should_abort
        assert rec.confidence == 0.30

    def test_debate_collapse(self):
        """High analysis followed by debate collapse."""
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.90)
        monitor.record("debate", 0.45)  # Sharp drop
        rec = monitor.should_abort()
        assert rec.should_abort
        assert "Sharp confidence drop" in rec.reason

    def test_recovery_after_dip(self):
        """Pipeline recovers after a moderate dip."""
        monitor = StepwiseConfidenceMonitor()
        monitor.record("analysis", 0.85)
        monitor.record("debate", 0.65)  # Moderate dip
        assert not monitor.should_abort().should_abort

        monitor.record("architecture", 0.78)  # Recovery
        assert not monitor.should_abort().should_abort

        traj = monitor.get_trajectory()
        assert traj.minimum == 0.65
        assert traj.latest == 0.78
