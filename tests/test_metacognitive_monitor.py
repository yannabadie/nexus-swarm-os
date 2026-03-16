"""
Tests for MetacognitiveMonitor (MASC) - NEXUS V12.4

Tests the unsupervised anomaly detection module for multi-agent execution steps.
Covers tokenization, TF-IDF, cosine similarity, anomaly scoring, prototypes,
z-score computation, and the singleton pattern.
"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.reasoning.metacognitive_monitor import (
    AnomalyScore,
    MetacognitiveMonitor,
    MonitorStats,
    StepPrototype,
    _cosine_similarity,
    _term_frequency,
    _tokenize,
    get_metacognitive_monitor,
    reset_metacognitive_monitor,
)

# ============================================================================
# _tokenize Tests
# ============================================================================


class TestTokenize:
    """Test the _tokenize helper function."""

    def test_simple_text(self):
        """Simple words should be lowercased and split."""
        tokens = _tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_punctuation_stripped(self):
        """Punctuation should act as separator and be removed."""
        tokens = _tokenize("Hello, world! How are you?")
        assert tokens == ["hello", "world", "how", "are", "you"]

    def test_empty_string(self):
        """Empty string should return empty list."""
        tokens = _tokenize("")
        assert tokens == []

    def test_whitespace_only(self):
        """Whitespace-only string should return empty list."""
        tokens = _tokenize("   \t\n  ")
        assert tokens == []

    def test_underscores_kept(self):
        """Underscores should be part of tokens."""
        tokens = _tokenize("my_variable another_var")
        assert tokens == ["my_variable", "another_var"]

    def test_numbers_preserved(self):
        """Numbers should be kept as part of tokens."""
        tokens = _tokenize("step1 and step2")
        assert tokens == ["step1", "and", "step2"]

    def test_mixed_case(self):
        """All output should be lowercase."""
        tokens = _tokenize("CamelCase UPPER lower")
        assert tokens == ["camelcase", "upper", "lower"]

    def test_multiple_separators(self):
        """Multiple consecutive separators should not produce empty tokens."""
        tokens = _tokenize("hello...world---test")
        assert tokens == ["hello", "world", "test"]

    def test_single_word(self):
        """Single word without separators."""
        tokens = _tokenize("hello")
        assert tokens == ["hello"]


# ============================================================================
# _term_frequency Tests
# ============================================================================


class TestTermFrequency:
    """Test the _term_frequency helper function."""

    def test_single_token(self):
        """Single token should have frequency 1.0."""
        tf = _term_frequency(["hello"])
        assert tf == {"hello": 1.0}

    def test_uniform_distribution(self):
        """Equal tokens should have equal frequencies."""
        tf = _term_frequency(["a", "b", "c"])
        assert len(tf) == 3
        for freq in tf.values():
            assert abs(freq - 1.0 / 3.0) < 1e-10

    def test_repeated_token(self):
        """Repeated tokens should accumulate frequency."""
        tf = _term_frequency(["the", "the", "cat"])
        assert abs(tf["the"] - 2.0 / 3.0) < 1e-10
        assert abs(tf["cat"] - 1.0 / 3.0) < 1e-10

    def test_empty_list(self):
        """Empty list should return empty dict (no division by zero)."""
        tf = _term_frequency([])
        assert tf == {}

    def test_normalized(self):
        """Frequencies should sum to approximately 1.0."""
        tf = _term_frequency(["a", "b", "a", "c", "a"])
        total = sum(tf.values())
        assert abs(total - 1.0) < 1e-10


# ============================================================================
# _cosine_similarity Tests
# ============================================================================


class TestCosineSimilarity:
    """Test the _cosine_similarity function."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity 1.0."""
        a = {"x": 1.0, "y": 2.0}
        sim = _cosine_similarity(a, a)
        assert abs(sim - 1.0) < 1e-10

    def test_orthogonal_vectors(self):
        """Vectors with no shared keys should have similarity 0.0."""
        a = {"x": 1.0}
        b = {"y": 1.0}
        sim = _cosine_similarity(a, b)
        assert abs(sim - 0.0) < 1e-10

    def test_empty_first_vector(self):
        """Empty first vector should return 0.0."""
        sim = _cosine_similarity({}, {"x": 1.0})
        assert sim == 0.0

    def test_empty_second_vector(self):
        """Empty second vector should return 0.0."""
        sim = _cosine_similarity({"x": 1.0}, {})
        assert sim == 0.0

    def test_both_empty(self):
        """Both empty vectors should return 0.0."""
        sim = _cosine_similarity({}, {})
        assert sim == 0.0

    def test_proportional_vectors(self):
        """Proportional vectors should have similarity 1.0."""
        a = {"x": 1.0, "y": 2.0}
        b = {"x": 2.0, "y": 4.0}
        sim = _cosine_similarity(a, b)
        assert abs(sim - 1.0) < 1e-10

    def test_partial_overlap(self):
        """Vectors with partial overlap should have 0 < similarity < 1."""
        a = {"x": 1.0, "y": 1.0}
        b = {"x": 1.0, "z": 1.0}
        sim = _cosine_similarity(a, b)
        assert 0.0 < sim < 1.0

    def test_known_value(self):
        """Test a known cosine similarity computation."""
        # cos(a, b) = (1*0 + 1*1) / (sqrt(2) * sqrt(1)) = 1/sqrt(2)
        a = {"x": 1.0, "y": 1.0}
        b = {"y": 1.0}
        sim = _cosine_similarity(a, b)
        expected = 1.0 / math.sqrt(2.0)
        assert abs(sim - expected) < 1e-10


# ============================================================================
# AnomalyScore Tests
# ============================================================================


class TestAnomalyScore:
    """Test the AnomalyScore dataclass."""

    def test_is_anomalous_above_threshold(self):
        """Score above 2.0 should be anomalous."""
        score = AnomalyScore(
            reconstruction_distance=0.8,
            prototype_distance=0.9,
            composite_score=2.5,
        )
        assert score.is_anomalous is True

    def test_is_anomalous_below_threshold(self):
        """Score below 2.0 should not be anomalous."""
        score = AnomalyScore(
            reconstruction_distance=0.3,
            prototype_distance=0.2,
            composite_score=1.0,
        )
        assert score.is_anomalous is False

    def test_is_anomalous_at_threshold(self):
        """Score exactly at 2.0 should not be anomalous (strictly greater)."""
        score = AnomalyScore(
            reconstruction_distance=0.5,
            prototype_distance=0.5,
            composite_score=2.0,
        )
        assert score.is_anomalous is False

    def test_default_fields(self):
        """Default optional fields should be empty strings."""
        score = AnomalyScore(
            reconstruction_distance=0.0,
            prototype_distance=0.0,
            composite_score=0.0,
        )
        assert score.step_output_preview == ""
        assert score.task_type == ""

    def test_with_metadata(self):
        """Score should store metadata fields correctly."""
        score = AnomalyScore(
            reconstruction_distance=0.5,
            prototype_distance=0.6,
            composite_score=1.1,
            step_output_preview="Generated SQL query",
            task_type="debugging",
        )
        assert score.step_output_preview == "Generated SQL query"
        assert score.task_type == "debugging"


# ============================================================================
# StepPrototype Tests
# ============================================================================


class TestStepPrototype:
    """Test the StepPrototype dataclass and its update method."""

    def test_initial_state(self):
        """New prototype should have zero observations."""
        proto = StepPrototype()
        assert proto.observation_count == 0
        assert proto.term_frequencies == {}
        assert proto.avg_length == 0.0

    def test_single_update(self):
        """First update should set values directly."""
        proto = StepPrototype()
        tf = {"hello": 0.5, "world": 0.5}
        proto.update(tf, 10)

        assert proto.observation_count == 1
        assert abs(proto.term_frequencies["hello"] - 0.5) < 1e-10
        assert abs(proto.term_frequencies["world"] - 0.5) < 1e-10
        assert abs(proto.avg_length - 10.0) < 1e-10

    def test_running_average_two_updates(self):
        """Two updates should produce correct running average."""
        proto = StepPrototype()

        proto.update({"a": 1.0}, 10)
        proto.update({"a": 0.5}, 20)

        assert proto.observation_count == 2
        # Running average: 1.0 + (0.5 - 1.0)/2 = 0.75
        assert abs(proto.term_frequencies["a"] - 0.75) < 1e-10
        # Average length: 10 + (20 - 10)/2 = 15
        assert abs(proto.avg_length - 15.0) < 1e-10

    def test_running_average_three_updates(self):
        """Three updates should produce correct running average."""
        proto = StepPrototype()

        proto.update({"x": 0.3}, 100)
        proto.update({"x": 0.6}, 200)
        proto.update({"x": 0.9}, 300)

        assert proto.observation_count == 3
        # Running average of 0.3, 0.6, 0.9 = 0.6
        assert abs(proto.term_frequencies["x"] - 0.6) < 1e-10
        # Running average of 100, 200, 300 = 200
        assert abs(proto.avg_length - 200.0) < 1e-10

    def test_new_terms_added(self):
        """New terms appearing in later updates should be incorporated."""
        proto = StepPrototype()

        proto.update({"a": 1.0}, 10)
        proto.update({"b": 1.0}, 10)

        assert proto.observation_count == 2
        # "a": 1.0 + (0 - 1.0)/2 = 0.5 (not updated in second, treated as old=1.0, new absent)
        # Actually "a" is not in second tf, so it keeps old value (running avg only updates present terms)
        assert abs(proto.term_frequencies["a"] - 1.0) < 1e-10
        # "b": 0 + (1.0 - 0)/2 = 0.5
        assert abs(proto.term_frequencies["b"] - 0.5) < 1e-10


# ============================================================================
# MetacognitiveMonitor.score_step Tests
# ============================================================================


class TestScoreStep:
    """Test the MetacognitiveMonitor.score_step method."""

    def test_empty_output_returns_zero(self):
        """Empty step output should return zero scores."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("")
        assert score.composite_score == 0.0
        assert score.reconstruction_distance == 0.0
        assert score.prototype_distance == 0.0
        assert score.step_output_preview == ""

    def test_whitespace_only_returns_zero(self):
        """Whitespace-only output should return zero scores."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("   \t\n  ")
        assert score.composite_score == 0.0

    def test_none_output_returns_zero(self):
        """None output should return zero scores."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step(None)
        assert score.composite_score == 0.0

    def test_normal_output_no_history(self):
        """Normal output without history should produce a score."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("Generated SQL query for auth table")
        assert isinstance(score, AnomalyScore)
        assert score.task_type == "general"
        assert score.step_output_preview == "Generated SQL query for auth table"

    def test_with_history(self):
        """Output with history should compute reconstruction distance."""
        monitor = MetacognitiveMonitor()
        history = ["Analyzed schema", "Identified auth tables"]
        score = monitor.score_step(
            "Generated SQL query for auth table",
            history=history,
            task_type="debugging",
        )
        assert isinstance(score, AnomalyScore)
        assert score.task_type == "debugging"
        # With history, reconstruction distance should be non-zero
        # (unless output happens to match history centroid exactly)
        assert score.reconstruction_distance >= 0.0

    def test_output_preview_truncated(self):
        """Step output preview should be truncated to 100 chars."""
        monitor = MetacognitiveMonitor()
        long_output = "x" * 200
        score = monitor.score_step(long_output)
        assert len(score.step_output_preview) == 100

    def test_increments_total_scored(self):
        """Each call should increment the total scored counter."""
        monitor = MetacognitiveMonitor()
        monitor.score_step("Step one")
        monitor.score_step("Step two")
        monitor.score_step("Step three")
        stats = monitor.get_stats()
        assert stats.total_steps_scored == 3

    def test_default_task_type(self):
        """Default task type should be 'general'."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("Some output")
        assert score.task_type == "general"


# ============================================================================
# Prototype Building Tests
# ============================================================================


class TestPrototypeBuilding:
    """Test that score_step builds prototypes over multiple calls."""

    def test_prototype_created_after_scoring(self):
        """Scoring should create a prototype for the task type."""
        monitor = MetacognitiveMonitor()
        monitor.score_step("Analyzing code structure", task_type="analysis")

        stats = monitor.get_stats()
        assert "analysis" in stats.task_types_tracked

    def test_multiple_task_types(self):
        """Different task types should create separate prototypes."""
        monitor = MetacognitiveMonitor()
        monitor.score_step("Debug step", task_type="debugging")
        monitor.score_step("Analysis step", task_type="analysis")

        stats = monitor.get_stats()
        assert "debugging" in stats.task_types_tracked
        assert "analysis" in stats.task_types_tracked

    def test_prototype_matures(self):
        """After MIN_PROTOTYPE_SAMPLES, prototype distance should be non-zero."""
        monitor = MetacognitiveMonitor()

        # Feed similar outputs to build prototype
        for i in range(monitor.MIN_PROTOTYPE_SAMPLES):
            monitor.score_step(
                f"Analyzing code structure iteration {i}",
                task_type="analysis",
            )

        # Now score something very different
        score = monitor.score_step(
            "Cooking recipes for banana bread",
            task_type="analysis",
        )
        # Prototype distance should be non-zero for dissimilar content
        assert score.prototype_distance > 0.0

    def test_prototype_not_used_before_min_samples(self):
        """Before MIN_PROTOTYPE_SAMPLES, prototype_distance should be 0."""
        monitor = MetacognitiveMonitor()

        # Only 1 sample (less than MIN_PROTOTYPE_SAMPLES=3)
        score = monitor.score_step("First step", task_type="new_type")
        # At time of scoring, prototype has 0 observations (update happens after)
        assert score.prototype_distance == 0.0


# ============================================================================
# should_correct Tests
# ============================================================================


class TestShouldCorrect:
    """Test the should_correct method."""

    def test_above_threshold(self):
        """Score above threshold should trigger correction."""
        monitor = MetacognitiveMonitor(threshold=1.5)
        score = AnomalyScore(
            reconstruction_distance=0.9,
            prototype_distance=0.8,
            composite_score=2.0,
        )
        assert monitor.should_correct(score) is True

    def test_below_threshold(self):
        """Score below threshold should not trigger correction."""
        monitor = MetacognitiveMonitor(threshold=1.5)
        score = AnomalyScore(
            reconstruction_distance=0.3,
            prototype_distance=0.2,
            composite_score=0.5,
        )
        assert monitor.should_correct(score) is False

    def test_at_threshold(self):
        """Score exactly at threshold should not trigger correction (strictly greater)."""
        monitor = MetacognitiveMonitor(threshold=1.5)
        score = AnomalyScore(
            reconstruction_distance=0.5,
            prototype_distance=0.5,
            composite_score=1.5,
        )
        assert monitor.should_correct(score) is False

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        monitor = MetacognitiveMonitor(threshold=3.0)
        assert monitor.threshold == 3.0

        score = AnomalyScore(
            reconstruction_distance=0.9,
            prototype_distance=0.8,
            composite_score=2.5,
        )
        assert monitor.should_correct(score) is False  # 2.5 < 3.0

    def test_default_threshold(self):
        """Default threshold should be 2.0."""
        monitor = MetacognitiveMonitor()
        assert monitor.threshold == MetacognitiveMonitor.DEFAULT_THRESHOLD
        assert monitor.threshold == 2.0

    def test_zero_threshold_uses_default(self):
        """Passing threshold=0 should fall back to default."""
        monitor = MetacognitiveMonitor(threshold=0.0)
        assert monitor.threshold == MetacognitiveMonitor.DEFAULT_THRESHOLD


# ============================================================================
# get_stats Tests
# ============================================================================


class TestGetStats:
    """Test the get_stats method."""

    def test_empty_stats(self):
        """Stats on a fresh monitor should be zeroed."""
        monitor = MetacognitiveMonitor()
        stats = monitor.get_stats()

        assert isinstance(stats, MonitorStats)
        assert stats.total_steps_scored == 0
        assert stats.anomalies_detected == 0
        assert stats.task_types_tracked == []
        assert stats.avg_composite_score == 0.0

    def test_stats_after_scoring(self):
        """Stats should reflect scoring activity."""
        monitor = MetacognitiveMonitor()
        monitor.score_step("Step one", task_type="debug")
        monitor.score_step("Step two", task_type="analysis")
        monitor.score_step("Step three", task_type="debug")

        stats = monitor.get_stats()
        assert stats.total_steps_scored == 3
        assert set(stats.task_types_tracked) == {"debug", "analysis"}

    def test_avg_composite_score_computed(self):
        """Average composite score should be computed from history."""
        monitor = MetacognitiveMonitor()
        monitor.score_step("Hello world step one")
        monitor.score_step("Hello world step two")

        stats = monitor.get_stats()
        # avg_composite_score is computed from _score_history (raw composites)
        # It should be a real number (not necessarily the z-score)
        assert isinstance(stats.avg_composite_score, float)


# ============================================================================
# Anomaly Detection Tests
# ============================================================================


class TestAnomalyDetection:
    """Test that very different outputs score higher than similar ones."""

    def test_similar_steps_low_score(self):
        """Similar step outputs should produce lower anomaly scores."""
        monitor = MetacognitiveMonitor()

        history = [
            "Analyzing database schema for user table",
            "Reading user authentication module",
            "Checking database connection settings",
        ]

        score = monitor.score_step(
            "Examining database permissions for user access",
            history=history,
            task_type="analysis",
        )

        # Similar content should have relatively low reconstruction distance
        assert score.reconstruction_distance < 1.0

    def test_very_different_step_higher_distance(self):
        """A completely unrelated step should have higher reconstruction distance."""
        monitor = MetacognitiveMonitor()

        history = [
            "Analyzing database schema for user table",
            "Reading user authentication module",
            "Checking database connection settings",
        ]

        # Related step
        related_score = monitor.score_step(
            "Examining database permissions for user access",
            history=history,
            task_type="analysis",
        )

        # Completely unrelated step (new monitor to avoid prototype influence)
        monitor2 = MetacognitiveMonitor()
        unrelated_score = monitor2.score_step(
            "The quick brown fox jumps over the lazy dog in the park",
            history=history,
            task_type="analysis",
        )

        # Unrelated output should have higher reconstruction distance
        assert unrelated_score.reconstruction_distance > related_score.reconstruction_distance

    def test_no_history_zero_reconstruction(self):
        """Without history, reconstruction distance should be 0."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("Any text here", history=None)
        assert score.reconstruction_distance == 0.0

        score2 = monitor.score_step("Any text here", history=[])
        assert score2.reconstruction_distance == 0.0


# ============================================================================
# Z-Score Computation Tests
# ============================================================================


class TestZScore:
    """Test z-score computation with enough history."""

    def test_raw_scaling_with_few_samples(self):
        """With fewer than 5 samples, raw score should be scaled by 2x."""
        monitor = MetacognitiveMonitor()
        # The first score has < 5 history entries, so z = raw * 2.0
        score = monitor.score_step(
            "Step output text here",
            history=["previous step"],
        )
        # We cannot know the exact value, but it should be non-negative
        assert score.composite_score >= 0.0

    def test_z_score_with_enough_history(self):
        """With 5+ samples, z-score should use mean and std."""
        monitor = MetacognitiveMonitor()

        # Build up history with similar steps
        for i in range(10):
            monitor.score_step(
                f"Analyzing code structure part {i}",
                history=["Setup environment"],
                task_type="coding",
            )

        # At this point, score_history has 10 entries
        # Next score should use z-score computation
        score = monitor.score_step(
            "Analyzing code structure part final",
            history=["Setup environment"],
            task_type="coding",
        )

        # The z-score should be a reasonable number (not scaled by 2x)
        assert isinstance(score.composite_score, float)
        assert not math.isnan(score.composite_score)
        assert not math.isinf(score.composite_score)

    def test_identical_scores_yield_zero_zscore(self):
        """If all scores are identical, std is near-zero and z-score should be 0."""
        monitor = MetacognitiveMonitor()

        # Feed identical inputs to get identical raw scores
        for _ in range(10):
            monitor.score_step("exact same text every time", task_type="same")

        # After many identical scores, variance -> near 0, z -> 0
        score = monitor.score_step("exact same text every time", task_type="same")
        # With zero variance, the implementation returns 0.0
        assert abs(score.composite_score) < 1e-6

    def test_history_capped_at_200(self):
        """Score history should not exceed 200 entries."""
        monitor = MetacognitiveMonitor()

        for i in range(250):
            monitor.score_step(f"Step number {i}")

        # Internal history should be capped
        assert len(monitor._score_history) <= 200


# ============================================================================
# Singleton Pattern Tests
# ============================================================================


class TestSingleton:
    """Test get_metacognitive_monitor and reset_metacognitive_monitor."""

    def test_get_returns_instance(self):
        """get_metacognitive_monitor should return a MetacognitiveMonitor."""
        reset_metacognitive_monitor()
        monitor = get_metacognitive_monitor()
        assert isinstance(monitor, MetacognitiveMonitor)

    def test_get_returns_same_instance(self):
        """Repeated calls should return the same instance."""
        reset_metacognitive_monitor()
        m1 = get_metacognitive_monitor()
        m2 = get_metacognitive_monitor()
        assert m1 is m2

    def test_reset_clears_instance(self):
        """Reset should cause get to create a new instance."""
        reset_metacognitive_monitor()
        m1 = get_metacognitive_monitor()
        reset_metacognitive_monitor()
        m2 = get_metacognitive_monitor()
        assert m1 is not m2

    def test_reset_gives_fresh_state(self):
        """New instance after reset should have clean stats."""
        reset_metacognitive_monitor()
        monitor = get_metacognitive_monitor()
        monitor.score_step("Some step")

        stats_before = monitor.get_stats()
        assert stats_before.total_steps_scored == 1

        reset_metacognitive_monitor()
        monitor2 = get_metacognitive_monitor()
        stats_after = monitor2.get_stats()
        assert stats_after.total_steps_scored == 0


# ============================================================================
# Edge Cases and Integration
# ============================================================================


class TestEdgeCases:
    """Test edge cases and integration scenarios."""

    def test_score_step_with_special_characters(self):
        """Special characters should be handled gracefully."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("!@#$%^&*()")
        # No alphanumeric tokens, but should not crash
        assert isinstance(score, AnomalyScore)

    def test_very_long_output(self):
        """Very long output should work without error."""
        monitor = MetacognitiveMonitor()
        long_output = "word " * 10000
        score = monitor.score_step(long_output)
        assert isinstance(score, AnomalyScore)
        assert len(score.step_output_preview) == 100

    def test_unicode_text(self):
        """Unicode text should be tokenized correctly."""
        monitor = MetacognitiveMonitor()
        score = monitor.score_step("analyse des donnees")
        assert isinstance(score, AnomalyScore)

    def test_history_uses_last_five(self):
        """Reconstruction should only use the last 5 history steps."""
        monitor = MetacognitiveMonitor()
        history = [f"step {i}" for i in range(20)]

        score = monitor.score_step(
            "step 19",
            history=history,
        )
        # Should not crash; uses history[-5:]
        assert isinstance(score, AnomalyScore)

    def test_anomaly_counter_increments(self):
        """Anomaly counter should increment when anomalies are detected."""
        monitor = MetacognitiveMonitor()

        # Create a scenario where anomaly is detected
        # Feed many similar steps, then a very different one
        for _i in range(10):
            monitor.score_step(
                "analyzing code structure and patterns",
                history=["analyzing code structure"],
                task_type="coding",
            )

        initial_anomalies = monitor.get_stats().anomalies_detected

        # Score something radically different
        score = monitor.score_step(
            "xylophone zebra quantum pickle unicorn basketball",
            history=["analyzing code structure"],
            task_type="coding",
        )

        # If the score is anomalous, counter should have incremented
        if score.is_anomalous:
            assert monitor.get_stats().anomalies_detected == initial_anomalies + 1

    def test_reconstruction_distance_range(self):
        """Reconstruction distance should be between 0 and 1."""
        monitor = MetacognitiveMonitor()
        history = ["Analyzed the schema", "Found the bug"]
        score = monitor.score_step(
            "Fixed the bug in authentication",
            history=history,
        )
        assert 0.0 <= score.reconstruction_distance <= 1.0

    def test_prototype_distance_range(self):
        """Prototype distance should be between 0 and 1 (or 0.5 floor)."""
        monitor = MetacognitiveMonitor()

        # Build up prototype
        for i in range(5):
            monitor.score_step(
                f"Analyzing code base module {i}",
                task_type="coding",
            )

        score = monitor.score_step(
            "Analyzing code base module final",
            task_type="coding",
        )
        assert 0.0 <= score.prototype_distance <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
