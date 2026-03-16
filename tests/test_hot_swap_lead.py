"""
Tests for V8.0.1 Hot-Swap Lead Agent feature.

Tests the StagnationDetector's ability to detect stagnation
and recommend lead agent swaps.
"""

from core.fsm.stagnation_detector import StagnationDetector


class TestHotSwapLeadAgent:
    """Test Hot-Swap Lead Agent functionality."""

    def test_should_not_swap_on_first_failure(self):
        """First failure should not trigger swap."""
        detector = StagnationDetector()
        detector.record_agent_failure("gemini")

        assert not detector.should_swap_lead("gemini")

    def test_should_swap_after_multiple_failures_with_stagnation(self):
        """Multiple failures with similar messages should trigger swap."""
        detector = StagnationDetector(
            similarity_threshold=0.5,  # Lower threshold for testing
            window_size=3,
        )

        # Add nearly identical stagnating messages
        detector.add_message("Failed to read file auth.py - permission denied")
        detector.add_message("Failed to read file auth.py - permission denied")
        detector.add_message("Failed to read file auth.py - permission denied")

        # Record failures
        detector.record_agent_failure("gemini")
        detector.record_agent_failure("gemini")

        # Should now recommend swap
        assert detector.should_swap_lead("gemini", failure_count=2)

    def test_get_swap_recommendation_no_stagnation(self):
        """No swap recommendation when not stagnating."""
        detector = StagnationDetector()

        recommendation = detector.get_swap_recommendation("gemini")

        assert recommendation["should_swap"] is False
        assert recommendation["new_lead"] is None

    def test_get_swap_recommendation_with_stagnation(self):
        """Swap recommendation when stagnating."""
        detector = StagnationDetector(
            similarity_threshold=0.5,  # Lower threshold for testing
            window_size=3,
        )

        # Create stagnation with identical messages
        detector.add_message("Cannot parse JSON response from API")
        detector.add_message("Cannot parse JSON response from API")
        detector.add_message("Cannot parse JSON response from API")
        detector.record_agent_failure("gemini")
        detector.record_agent_failure("gemini")

        recommendation = detector.get_swap_recommendation("gemini")

        assert recommendation["should_swap"] is True
        assert recommendation["new_lead"] == "claude"
        assert "gemini" in recommendation["reason"]
        assert recommendation["stagnation_count"] == 2

    def test_swap_gemini_to_claude(self):
        """Swap should go from Gemini to Claude."""
        detector = StagnationDetector(similarity_threshold=0.7, window_size=3)

        # Create stagnation
        for _ in range(3):
            detector.add_message("Same error message repeated")
        detector.record_agent_failure("gemini")
        detector.record_agent_failure("gemini")

        recommendation = detector.get_swap_recommendation("gemini")

        assert recommendation["new_lead"] == "claude"

    def test_swap_claude_to_gemini(self):
        """Swap should go from Claude to Gemini."""
        detector = StagnationDetector(similarity_threshold=0.7, window_size=3)

        # Create stagnation
        for _ in range(3):
            detector.add_message("Same error message repeated")
        detector.record_agent_failure("claude")
        detector.record_agent_failure("claude")

        recommendation = detector.get_swap_recommendation("claude")

        assert recommendation["new_lead"] == "gemini"

    def test_reset_clears_stagnation_count(self):
        """Reset should clear stagnation count."""
        detector = StagnationDetector()
        detector.record_agent_failure("gemini")
        detector.record_agent_failure("gemini")

        detector.reset()

        assert detector._stagnation_count == 0
        assert len(detector.message_history) == 0

    def test_extract_stagnant_strategy(self):
        """Extract strategy from stagnant messages."""
        detector = StagnationDetector(window_size=3)

        detector.add_message("failed to authenticate with api")
        detector.add_message("authentication failed for api call")
        detector.add_message("api authentication error")

        strategy = detector.extract_stagnant_strategy()

        # Should find common meaningful words
        assert "api" in strategy.lower() or "authentication" in strategy.lower()

    def test_custom_failure_count_threshold(self):
        """Custom failure count threshold for swap."""
        detector = StagnationDetector(similarity_threshold=0.7, window_size=3)

        # Create stagnation
        for _ in range(3):
            detector.add_message("Same error")
        detector.record_agent_failure("gemini")

        # With failure_count=1, should swap after 1 failure
        assert detector.should_swap_lead("gemini", failure_count=1)

        # With failure_count=3, should not swap after 1 failure
        assert not detector.should_swap_lead("gemini", failure_count=3)


class TestHotSwapIntegration:
    """Test Hot-Swap integration with StrategyBlacklist."""

    def test_report_to_blacklist_without_blacklist(self):
        """Report should return False without blacklist."""
        detector = StagnationDetector()

        # Create stagnation
        for _ in range(3):
            detector.add_message("Same message")
        detector.record_agent_failure("gemini")
        detector.record_agent_failure("gemini")

        # Should not crash, just return False
        result = detector.report_to_blacklist()
        assert result is False

    def test_check_and_report_no_stagnation(self):
        """check_and_report returns False when not stagnating."""
        detector = StagnationDetector()

        result = detector.check_and_report()

        assert result is False

    def test_check_and_report_with_stagnation(self):
        """check_and_report returns True when stagnating."""
        detector = StagnationDetector(similarity_threshold=0.7, window_size=3)

        # Create stagnation
        for _ in range(3):
            detector.add_message("Same error over and over")

        result = detector.check_and_report()

        assert result is True


class TestStagnationStats:
    """Test stagnation statistics."""

    def test_get_stats_includes_stagnation_count(self):
        """Stats should include stagnation count."""
        detector = StagnationDetector()
        detector.record_agent_failure("gemini")
        detector.record_agent_failure("gemini")

        stats = detector.get_stats()

        assert "stagnation_count" in stats
        assert stats["stagnation_count"] == 2

    def test_get_stats_includes_similarity_scores(self):
        """Stats should include similarity scores."""
        detector = StagnationDetector(window_size=3)
        detector.add_message("Test message one")
        detector.add_message("Test message two")
        detector.add_message("Test message three")

        stats = detector.get_stats()

        assert "similarity_scores" in stats
        assert len(stats["similarity_scores"]) == 3  # 3 pairs from 3 messages
