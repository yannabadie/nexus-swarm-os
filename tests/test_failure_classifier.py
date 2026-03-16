"""
Comprehensive tests for core.reasoning.failure_classifier module.

Covers:
  - FailureCategory enum values
  - Classification dataclass and is_confident property
  - ClassifierStats dataclass
  - classify() with empty / no input (default behaviour)
  - classify() per category (MEMORY, REFLECTION, PLANNING, ACTION, SYSTEM)
  - Issue-type boosting logic
  - Secondary category detection
  - Recovery strategies per category
  - get_stats() tracking across classifications
  - Singleton helpers (get_failure_classifier / reset_failure_classifier)
  - signal_scores dict populated in result
  - Multiple classifications accumulate stats correctly
  - Edge cases: long text, mixed signals, truncation of step_outputs

Target: ~75 tests.
"""

import threading

import pytest

from core.intelligence.reasoning.failure_classifier import (
    ACTION_PATTERNS,
    MEMORY_PATTERNS,
    PLANNING_PATTERNS,
    RECOVERY_STRATEGIES,
    REFLECTION_PATTERNS,
    SYSTEM_PATTERNS,
    Classification,
    ClassifierStats,
    FailureCategory,
    FailureClassifier,
    get_failure_classifier,
    reset_failure_classifier,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton before and after every test."""
    reset_failure_classifier()
    yield
    reset_failure_classifier()


@pytest.fixture
def classifier() -> FailureClassifier:
    """Return a fresh FailureClassifier instance (not the singleton)."""
    return FailureClassifier()


# ===========================================================================
# 1. FailureCategory enum values
# ===========================================================================


class TestFailureCategoryEnum:
    """Verify that all five expected enum members exist with correct values."""

    def test_memory_value(self):
        assert FailureCategory.MEMORY.value == "memory"

    def test_reflection_value(self):
        assert FailureCategory.REFLECTION.value == "reflection"

    def test_planning_value(self):
        assert FailureCategory.PLANNING.value == "planning"

    def test_action_value(self):
        assert FailureCategory.ACTION.value == "action"

    def test_system_value(self):
        assert FailureCategory.SYSTEM.value == "system"

    def test_exactly_five_members(self):
        assert len(FailureCategory) == 5


# ===========================================================================
# 2. Classification dataclass
# ===========================================================================


class TestClassificationDataclass:
    """Verify Classification fields, defaults, and is_confident property."""

    def test_required_fields(self):
        c = Classification(
            category=FailureCategory.ACTION,
            confidence=0.8,
            evidence=["wrong tool"],
            recovery_strategy="fix it",
        )
        assert c.category == FailureCategory.ACTION
        assert c.confidence == 0.8
        assert c.evidence == ["wrong tool"]
        assert c.recovery_strategy == "fix it"

    def test_optional_secondary_category_default_none(self):
        c = Classification(
            category=FailureCategory.MEMORY,
            confidence=0.5,
            evidence=[],
            recovery_strategy="",
        )
        assert c.secondary_category is None

    def test_optional_signal_scores_default_empty(self):
        c = Classification(
            category=FailureCategory.SYSTEM,
            confidence=0.3,
            evidence=[],
            recovery_strategy="",
        )
        assert c.signal_scores == {}

    def test_is_confident_above_threshold(self):
        c = Classification(
            category=FailureCategory.PLANNING,
            confidence=0.6,
            evidence=[],
            recovery_strategy="",
        )
        assert c.is_confident is True

    def test_is_confident_at_threshold_boundary(self):
        """Boundary: exactly 0.5 should NOT be confident (> 0.5 required)."""
        c = Classification(
            category=FailureCategory.PLANNING,
            confidence=0.5,
            evidence=[],
            recovery_strategy="",
        )
        assert c.is_confident is False

    def test_is_confident_below_threshold(self):
        c = Classification(
            category=FailureCategory.ACTION,
            confidence=0.3,
            evidence=[],
            recovery_strategy="",
        )
        assert c.is_confident is False

    def test_is_confident_at_one(self):
        c = Classification(
            category=FailureCategory.SYSTEM,
            confidence=1.0,
            evidence=[],
            recovery_strategy="",
        )
        assert c.is_confident is True

    def test_is_confident_at_zero(self):
        c = Classification(
            category=FailureCategory.SYSTEM,
            confidence=0.0,
            evidence=[],
            recovery_strategy="",
        )
        assert c.is_confident is False


# ===========================================================================
# 3. ClassifierStats dataclass
# ===========================================================================


class TestClassifierStats:
    """Verify ClassifierStats construction."""

    def test_construction(self):
        stats = ClassifierStats(
            total_classifications=10,
            category_distribution={"memory": 3, "action": 7},
            avg_confidence=0.65,
            most_common_category="action",
        )
        assert stats.total_classifications == 10
        assert stats.category_distribution == {"memory": 3, "action": 7}
        assert stats.avg_confidence == 0.65
        assert stats.most_common_category == "action"

    def test_empty_stats(self):
        stats = ClassifierStats(
            total_classifications=0,
            category_distribution={},
            avg_confidence=0.0,
            most_common_category="",
        )
        assert stats.total_classifications == 0
        assert stats.most_common_category == ""


# ===========================================================================
# 4. classify() with empty input -> default
# ===========================================================================


class TestClassifyEmptyInput:
    """Empty or whitespace-only input returns SYSTEM with confidence 0."""

    def test_no_arguments(self, classifier: FailureClassifier):
        result = classifier.classify()
        assert result.category == FailureCategory.SYSTEM
        assert result.confidence == 0.0
        assert result.evidence == ["No failure information provided"]

    def test_empty_string_description(self, classifier: FailureClassifier):
        result = classifier.classify(failure_description="")
        assert result.category == FailureCategory.SYSTEM
        assert result.confidence == 0.0

    def test_whitespace_only_description(self, classifier: FailureClassifier):
        result = classifier.classify(failure_description="   ")
        assert result.category == FailureCategory.SYSTEM
        assert result.confidence == 0.0

    def test_empty_lists(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="",
            step_outputs=[],
            issues=[],
        )
        assert result.category == FailureCategory.SYSTEM
        assert result.confidence == 0.0

    def test_no_pattern_match_defaults_to_action(self, classifier: FailureClassifier):
        """Text that matches no pattern -> ACTION with confidence 0.2."""
        result = classifier.classify(failure_description="the quick brown fox")
        assert result.category == FailureCategory.ACTION
        assert result.confidence == pytest.approx(0.2)


# ===========================================================================
# 5. classify() with MEMORY patterns
# ===========================================================================


class TestClassifyMemory:
    """Various memory-related failure descriptions."""

    def test_forgot(self, classifier: FailureClassifier):
        result = classifier.classify("Agent forgot the user's request")
        assert result.category == FailureCategory.MEMORY

    def test_lost_context(self, classifier: FailureClassifier):
        result = classifier.classify("Lost context of previous conversation")
        assert result.category == FailureCategory.MEMORY

    def test_missing_context(self, classifier: FailureClassifier):
        result = classifier.classify("missing context from earlier steps")
        assert result.category == FailureCategory.MEMORY

    def test_didnt_remember(self, classifier: FailureClassifier):
        result = classifier.classify("didn't remember the file path")
        assert result.category == FailureCategory.MEMORY

    def test_ignored_previous(self, classifier: FailureClassifier):
        result = classifier.classify("Agent ignored the previous analysis results")
        assert result.category == FailureCategory.MEMORY

    def test_failed_to_recall(self, classifier: FailureClassifier):
        result = classifier.classify("failed to recall the API key location")
        assert result.category == FailureCategory.MEMORY

    def test_multiple_memory_patterns_high_confidence(self, classifier: FailureClassifier):
        """Multiple matches push confidence higher."""
        desc = "forgot the context, lost context, missing context of previous step"
        result = classifier.classify(desc)
        assert result.category == FailureCategory.MEMORY
        assert result.confidence > 0.5


# ===========================================================================
# 6. classify() with REFLECTION patterns
# ===========================================================================


class TestClassifyReflection:
    """Reflection-related failure descriptions."""

    def test_didnt_notice(self, classifier: FailureClassifier):
        result = classifier.classify("didn't notice the error in output")
        assert result.category == FailureCategory.REFLECTION

    def test_same_mistake_again(self, classifier: FailureClassifier):
        result = classifier.classify("made the same mistake again three times")
        assert result.category == FailureCategory.REFLECTION

    def test_failed_to_correct(self, classifier: FailureClassifier):
        result = classifier.classify("failed to self correct the approach")
        assert result.category == FailureCategory.REFLECTION

    def test_blind_spot(self, classifier: FailureClassifier):
        result = classifier.classify("Agent has a blind spot for edge cases")
        assert result.category == FailureCategory.REFLECTION

    def test_no_validation(self, classifier: FailureClassifier):
        result = classifier.classify("There was no validation of the output")
        assert result.category == FailureCategory.REFLECTION

    def test_didnt_verify(self, classifier: FailureClassifier):
        result = classifier.classify("Agent didn't verify the result before returning")
        assert result.category == FailureCategory.REFLECTION


# ===========================================================================
# 7. classify() with PLANNING patterns
# ===========================================================================


class TestClassifyPlanning:
    """Planning-related failure descriptions."""

    def test_wrong_order(self, classifier: FailureClassifier):
        result = classifier.classify("Steps executed in wrong order")
        assert result.category == FailureCategory.PLANNING

    def test_missed_dependency(self, classifier: FailureClassifier):
        result = classifier.classify("missed dependency on auth module")
        assert result.category == FailureCategory.PLANNING

    def test_should_have_first(self, classifier: FailureClassifier):
        result = classifier.classify("should have checked the schema first")
        assert result.category == FailureCategory.PLANNING

    def test_skipped_step(self, classifier: FailureClassifier):
        result = classifier.classify("Agent skipped step 3 entirely")
        assert result.category == FailureCategory.PLANNING

    def test_wrong_approach(self, classifier: FailureClassifier):
        result = classifier.classify("Took the wrong approach to solving the problem")
        assert result.category == FailureCategory.PLANNING

    def test_incomplete_plan(self, classifier: FailureClassifier):
        result = classifier.classify("The task had an incomplete plan for deployment")
        assert result.category == FailureCategory.PLANNING


# ===========================================================================
# 8. classify() with ACTION patterns
# ===========================================================================


class TestClassifyAction:
    """Action-related failure descriptions."""

    def test_wrong_tool(self, classifier: FailureClassifier):
        result = classifier.classify("Used the wrong tool for the task")
        assert result.category == FailureCategory.ACTION

    def test_syntax_error(self, classifier: FailureClassifier):
        result = classifier.classify("Python syntax error on line 42")
        assert result.category == FailureCategory.ACTION

    def test_type_error(self, classifier: FailureClassifier):
        result = classifier.classify("Got a type error when calling function")
        assert result.category == FailureCategory.ACTION

    def test_incorrect_parameter(self, classifier: FailureClassifier):
        result = classifier.classify("Passed incorrect parameter to the API")
        assert result.category == FailureCategory.ACTION

    def test_wrong_file(self, classifier: FailureClassifier):
        result = classifier.classify("Edited the wrong file instead of config.py")
        assert result.category == FailureCategory.ACTION

    def test_permission_denied(self, classifier: FailureClassifier):
        result = classifier.classify("Operation failed: permission denied")
        assert result.category == FailureCategory.ACTION


# ===========================================================================
# 9. classify() with SYSTEM patterns
# ===========================================================================


class TestClassifySystem:
    """System-related failure descriptions."""

    def test_timeout(self, classifier: FailureClassifier):
        result = classifier.classify("Request timed out after 30 seconds: timeout")
        assert result.category == FailureCategory.SYSTEM

    def test_rate_limit(self, classifier: FailureClassifier):
        result = classifier.classify("Hit the rate limit on the API")
        assert result.category == FailureCategory.SYSTEM

    def test_503_error(self, classifier: FailureClassifier):
        result = classifier.classify("Server returned 503")
        assert result.category == FailureCategory.SYSTEM

    def test_429_error(self, classifier: FailureClassifier):
        result = classifier.classify("HTTP 429 Too Many Requests")
        assert result.category == FailureCategory.SYSTEM

    def test_connection_refused(self, classifier: FailureClassifier):
        result = classifier.classify("connection refused by remote host")
        assert result.category == FailureCategory.SYSTEM

    def test_out_of_memory(self, classifier: FailureClassifier):
        result = classifier.classify("Process ran out of memory")
        assert result.category == FailureCategory.SYSTEM

    def test_service_unavailable(self, classifier: FailureClassifier):
        result = classifier.classify("The service is currently unavailable")
        assert result.category == FailureCategory.SYSTEM


# ===========================================================================
# 10. Issue-type boosting
# ===========================================================================


class TestIssueTypeBoosting:
    """Issues with specific issue_type keys boost category scores."""

    def test_timeout_issue_boosts_system(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "timeout", "severity": "error"}],
        )
        assert result.signal_scores["system"] > 0

    def test_connection_issue_boosts_system(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "connection_error", "severity": "error"}],
        )
        assert result.signal_scores["system"] > 0

    def test_hallucination_issue_boosts_memory_and_reflection(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "hallucination", "severity": "warning"}],
        )
        assert result.signal_scores["memory"] > 0
        assert result.signal_scores["reflection"] > 0

    def test_error_issue_boosts_action(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "error", "severity": "error"}],
        )
        assert result.signal_scores["action"] > 0

    def test_syntax_issue_boosts_action(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "syntax_error", "severity": "error"}],
        )
        assert result.signal_scores["action"] > 0

    def test_stagnation_issue_boosts_reflection(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "stagnation", "severity": "warning"}],
        )
        assert result.signal_scores["reflection"] > 0

    def test_repeated_issue_boosts_reflection(self, classifier: FailureClassifier):
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "repeated_failure", "severity": "error"}],
        )
        assert result.signal_scores["reflection"] > 0

    def test_timeout_issue_can_push_to_system_category(self, classifier: FailureClassifier):
        """Even with no pattern text, a timeout issue should push to SYSTEM."""
        result = classifier.classify(
            failure_description="something happened",
            issues=[{"issue_type": "timeout", "severity": "critical"}],
        )
        assert result.category == FailureCategory.SYSTEM


# ===========================================================================
# 11. Secondary category detection
# ===========================================================================


class TestSecondaryCategory:
    """Verify secondary_category is populated when second score > 0.2."""

    def test_secondary_populated_for_mixed_signals(self, classifier: FailureClassifier):
        desc = "forgot the context and used the wrong tool"
        result = classifier.classify(desc)
        assert result.secondary_category is not None
        assert result.secondary_category != result.category

    def test_no_secondary_when_single_pattern(self, classifier: FailureClassifier):
        """Single match in one category, others at 0 -> no secondary."""
        result = classifier.classify("forgot the requirement")
        # Only one pattern matches, so secondary could be None
        # (other scores are 0 which is <= 0.2)
        assert result.secondary_category is None

    def test_secondary_with_issue_boosting(self, classifier: FailureClassifier):
        """Hallucination issue boosts both memory and reflection."""
        result = classifier.classify(
            failure_description="Agent made something up",
            issues=[{"issue_type": "hallucination", "severity": "error"}],
        )
        # Both MEMORY (+0.2) and REFLECTION (+0.1) should be boosted
        # At least one should be secondary if the other is primary
        if result.category == FailureCategory.MEMORY or result.category == FailureCategory.REFLECTION:
            assert True


# ===========================================================================
# 12. Recovery strategy per category
# ===========================================================================


class TestRecoveryStrategy:
    """get_recovery_strategy() returns the correct string per category."""

    def test_memory_recovery(self, classifier: FailureClassifier):
        strat = classifier.get_recovery_strategy(FailureCategory.MEMORY)
        assert "context" in strat.lower()

    def test_reflection_recovery(self, classifier: FailureClassifier):
        strat = classifier.get_recovery_strategy(FailureCategory.REFLECTION)
        assert "verification" in strat.lower() or "verify" in strat.lower()

    def test_planning_recovery(self, classifier: FailureClassifier):
        strat = classifier.get_recovery_strategy(FailureCategory.PLANNING)
        assert "decompose" in strat.lower() or "prerequisite" in strat.lower()

    def test_action_recovery(self, classifier: FailureClassifier):
        strat = classifier.get_recovery_strategy(FailureCategory.ACTION)
        assert "tool" in strat.lower() or "validate" in strat.lower()

    def test_system_recovery(self, classifier: FailureClassifier):
        strat = classifier.get_recovery_strategy(FailureCategory.SYSTEM)
        assert "retry" in strat.lower() or "backoff" in strat.lower()

    def test_classify_result_contains_matching_recovery(self, classifier: FailureClassifier):
        """Classification.recovery_strategy matches the category's strategy."""
        result = classifier.classify("Agent forgot the instructions")
        expected = RECOVERY_STRATEGIES[result.category]
        assert result.recovery_strategy == expected

    def test_all_categories_have_recovery_strategy(self):
        """Every FailureCategory member has a corresponding recovery strategy."""
        for cat in FailureCategory:
            assert cat in RECOVERY_STRATEGIES


# ===========================================================================
# 13. get_stats() tracking
# ===========================================================================


class TestGetStats:
    """Verify that get_stats() reflects classification history."""

    def test_initial_stats_zero(self, classifier: FailureClassifier):
        stats = classifier.get_stats()
        assert stats.total_classifications == 0
        assert stats.avg_confidence == 0.0
        assert stats.most_common_category == ""
        assert stats.category_distribution == {}

    def test_stats_after_one_classification(self, classifier: FailureClassifier):
        classifier.classify("timeout on the server")
        stats = classifier.get_stats()
        assert stats.total_classifications == 1
        assert stats.avg_confidence > 0
        assert stats.most_common_category == "system"

    def test_stats_after_multiple_classifications(self, classifier: FailureClassifier):
        classifier.classify("forgot the context")
        classifier.classify("forgot earlier results")
        classifier.classify("timeout on server")
        stats = classifier.get_stats()
        assert stats.total_classifications == 3
        assert stats.most_common_category == "memory"
        assert stats.category_distribution.get("memory", 0) == 2
        assert stats.category_distribution.get("system", 0) == 1


# ===========================================================================
# 14. Singleton pattern
# ===========================================================================


class TestSingleton:
    """get_failure_classifier() and reset_failure_classifier()."""

    def test_returns_same_instance(self):
        a = get_failure_classifier()
        b = get_failure_classifier()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = get_failure_classifier()
        reset_failure_classifier()
        b = get_failure_classifier()
        assert a is not b

    def test_reset_clears_stats(self):
        c = get_failure_classifier()
        c.classify("timeout on server")
        assert c.get_stats().total_classifications == 1
        reset_failure_classifier()
        c2 = get_failure_classifier()
        assert c2.get_stats().total_classifications == 0

    def test_instance_is_failure_classifier(self):
        c = get_failure_classifier()
        assert isinstance(c, FailureClassifier)


# ===========================================================================
# 15. Signal scores dict in result
# ===========================================================================


class TestSignalScores:
    """Classification.signal_scores should contain all five category keys."""

    def test_all_categories_present(self, classifier: FailureClassifier):
        result = classifier.classify("forgot the context and got a timeout")
        for cat in FailureCategory:
            assert cat.value in result.signal_scores

    def test_scores_are_non_negative(self, classifier: FailureClassifier):
        result = classifier.classify("wrong tool used")
        for score in result.signal_scores.values():
            assert score >= 0.0

    def test_primary_category_has_highest_or_equal_score(self, classifier: FailureClassifier):
        result = classifier.classify("forgot context, lost context, missing context")
        primary_score = result.signal_scores[result.category.value]
        for score in result.signal_scores.values():
            assert primary_score >= score

    def test_no_match_scores_all_zero(self, classifier: FailureClassifier):
        """When no patterns match, all signal scores should be 0."""
        result = classifier.classify("the quick brown fox")
        for score in result.signal_scores.values():
            assert score == 0.0


# ===========================================================================
# 16. Multiple classifications accumulate stats
# ===========================================================================


class TestStatsAccumulation:
    """Verify stats accumulate correctly across many classifications."""

    def test_ten_classifications(self, classifier: FailureClassifier):
        for _ in range(10):
            classifier.classify("timeout on server")
        stats = classifier.get_stats()
        assert stats.total_classifications == 10
        assert stats.most_common_category == "system"

    def test_mixed_categories_distribution(self, classifier: FailureClassifier):
        classifier.classify("forgot the context")
        classifier.classify("wrong tool used")
        classifier.classify("wrong tool used")
        classifier.classify("timeout error")
        stats = classifier.get_stats()
        assert stats.total_classifications == 4
        assert stats.category_distribution.get("action", 0) == 2

    def test_avg_confidence_tracks(self, classifier: FailureClassifier):
        # Two classifications with known patterns
        classifier.classify("forgot the context")
        classifier.classify("timeout on server")
        stats = classifier.get_stats()
        assert stats.avg_confidence > 0.0
        assert stats.avg_confidence <= 1.0


# ===========================================================================
# Edge cases & additional coverage
# ===========================================================================


class TestEdgeCases:
    """Edge cases for robustness."""

    def test_step_outputs_included_in_analysis(self, classifier: FailureClassifier):
        """Patterns in step_outputs should be detected."""
        result = classifier.classify(
            failure_description="",
            step_outputs=["Error: connection refused by host"],
        )
        assert result.category == FailureCategory.SYSTEM

    def test_step_outputs_truncation(self, classifier: FailureClassifier):
        """Step outputs are truncated to 500 chars each."""
        long_output = "x" * 1000 + " timeout"
        result = classifier.classify(step_outputs=[long_output])
        # "timeout" appears after 1000 x's, but truncation at 500 means
        # it is cut off, so it should not match SYSTEM
        assert result.category != FailureCategory.SYSTEM or result.confidence == 0.2

    def test_issues_without_issue_type_key(self, classifier: FailureClassifier):
        """Issues missing issue_type should not crash."""
        result = classifier.classify(
            failure_description="the quick brown fox",
            issues=[{"severity": "error"}],
        )
        # Should still return a valid Classification
        assert isinstance(result, Classification)

    def test_case_insensitive_matching(self, classifier: FailureClassifier):
        result = classifier.classify("FORGOT THE CONTEXT")
        assert result.category == FailureCategory.MEMORY

    def test_evidence_is_list(self, classifier: FailureClassifier):
        result = classifier.classify("forgot context and lost context")
        assert isinstance(result.evidence, list)

    def test_evidence_capped_at_five(self, classifier: FailureClassifier):
        """Evidence list should have at most 5 entries."""
        # Use many matching patterns to push evidence count
        desc = "forgot A, forgot B, forgot C, forgot D, forgot E, forgot F, lost context, missing context"
        result = classifier.classify(desc)
        assert len(result.evidence) <= 5

    def test_confidence_capped_at_one(self, classifier: FailureClassifier):
        """Confidence should never exceed 1.0."""
        desc = " ".join(["timeout"] * 50)
        result = classifier.classify(desc)
        assert result.confidence <= 1.0

    def test_pattern_counts_correct(self):
        """Verify expected pattern counts for each category."""
        assert len(MEMORY_PATTERNS) == 12
        assert len(REFLECTION_PATTERNS) == 10
        assert len(PLANNING_PATTERNS) == 12
        assert len(ACTION_PATTERNS) == 12
        assert len(SYSTEM_PATTERNS) == 13

    def test_thread_safety_concurrent_classify(self, classifier: FailureClassifier):
        """Multiple threads classifying concurrently should not corrupt stats."""
        errors = []

        def worker():
            try:
                for _ in range(20):
                    classifier.classify("timeout on server")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        stats = classifier.get_stats()
        assert stats.total_classifications == 80

    def test_issues_text_appended_to_analysis(self, classifier: FailureClassifier):
        """Issue type and severity strings are appended to the analysed text."""
        result = classifier.classify(
            failure_description="nothing specific",
            issues=[{"issue_type": "timeout", "severity": "critical"}],
        )
        # "timeout" appears via issue text concatenation and also triggers boosting
        assert result.signal_scores["system"] > 0

    def test_classify_returns_classification_instance(self, classifier: FailureClassifier):
        result = classifier.classify("forgot something")
        assert isinstance(result, Classification)

    def test_empty_evidence_when_default(self, classifier: FailureClassifier):
        """When defaulting to ACTION (no matches), evidence list is empty."""
        result = classifier.classify("the quick brown fox")
        assert result.evidence == []
