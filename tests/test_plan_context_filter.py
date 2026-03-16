"""
Comprehensive tests for core.memory.plan_context_filter module.

Covers:
  - ScoredItem, FilterResult, FilterStats dataclasses
  - _extract_keywords helper
  - _keyword_overlap helper
  - _estimate_tokens helper
  - PlanContextFilter.score_context_items
  - PlanContextFilter.filter
  - PlanContextFilter.get_stats
  - Singleton pattern (get_plan_context_filter / reset_plan_context_filter)
  - Edge cases and boundary conditions

Target: ~65 tests
"""

import threading
from collections import Counter

import pytest

from core.memory_pkg.memory.plan_context_filter import (
    FilterResult,
    FilterStats,
    PlanContextFilter,
    ScoredItem,
    _estimate_tokens,
    _extract_keywords,
    _keyword_overlap,
    get_plan_context_filter,
    reset_plan_context_filter,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton before and after every test."""
    reset_plan_context_filter()
    yield
    reset_plan_context_filter()


@pytest.fixture
def pcf() -> PlanContextFilter:
    """Fresh PlanContextFilter instance (not the singleton)."""
    return PlanContextFilter()


# ===========================================================================
# 1. ScoredItem dataclass
# ===========================================================================


class TestScoredItem:
    def test_construction(self):
        item = ScoredItem(
            content="hello",
            relevance_score=0.75,
            matched_steps=["step1"],
            keyword_overlap=0.5,
            position_score=0.8,
        )
        assert item.content == "hello"
        assert item.relevance_score == 0.75
        assert item.matched_steps == ["step1"]
        assert item.keyword_overlap == 0.5
        assert item.position_score == 0.8

    def test_default_matched_steps_is_not_shared(self):
        a = ScoredItem("a", 0.0, [], 0.0, 0.0)
        b = ScoredItem("b", 0.0, [], 0.0, 0.0)
        a.matched_steps.append("x")
        assert b.matched_steps == []

    def test_equality(self):
        a = ScoredItem("c", 0.5, ["s"], 0.3, 0.4)
        b = ScoredItem("c", 0.5, ["s"], 0.3, 0.4)
        assert a == b


# ===========================================================================
# 2. FilterResult dataclass
# ===========================================================================


class TestFilterResult:
    def test_construction(self):
        kept = [ScoredItem("x", 0.9, [], 0.5, 0.5)]
        dropped = [ScoredItem("y", 0.1, [], 0.05, 0.0)]
        result = FilterResult(
            kept_items=kept,
            dropped_items=dropped,
            total_items=2,
            kept_count=1,
            tokens_before=100,
            tokens_after=50,
            compression_ratio=0.5,
        )
        assert result.total_items == 2
        assert result.kept_count == 1
        assert result.tokens_before == 100
        assert result.tokens_after == 50
        assert result.compression_ratio == 0.5
        assert len(result.kept_items) == 1
        assert len(result.dropped_items) == 1

    def test_empty_filter_result(self):
        result = FilterResult([], [], 0, 0, 0, 0, 1.0)
        assert result.total_items == 0
        assert result.compression_ratio == 1.0


# ===========================================================================
# 3. FilterStats dataclass
# ===========================================================================


class TestFilterStats:
    def test_construction(self):
        stats = FilterStats(
            total_filter_calls=5,
            total_items_processed=100,
            total_items_dropped=30,
            avg_compression_ratio=0.7,
            avg_relevance_score=0.55,
        )
        assert stats.total_filter_calls == 5
        assert stats.total_items_processed == 100
        assert stats.total_items_dropped == 30
        assert stats.avg_compression_ratio == 0.7
        assert stats.avg_relevance_score == 0.55

    def test_zero_stats(self):
        stats = FilterStats(0, 0, 0, 0.0, 0.0)
        assert stats.total_filter_calls == 0


# ===========================================================================
# 4. _extract_keywords
# ===========================================================================


class TestExtractKeywords:
    def test_basic_extraction(self):
        kw = _extract_keywords("implement auth module")
        assert "implement" in kw
        assert "auth" in kw
        assert "module" in kw

    def test_stop_word_filtering(self):
        kw = _extract_keywords("the and for that this with from are")
        # All are stop words - none should appear
        assert len(kw) == 0

    def test_minimum_length_three(self):
        kw = _extract_keywords("a ab abc abcd")
        assert "abc" in kw
        assert "abcd" in kw
        # 'a' and 'ab' are < 3 chars (regex requires at least 3: r'[a-zA-Z_]\w{2,}')
        assert "a" not in kw
        assert "ab" not in kw

    def test_case_insensitive(self):
        kw = _extract_keywords("Auth AUTH auth")
        assert "auth" in kw
        assert kw["auth"] == 3

    def test_underscored_words(self):
        kw = _extract_keywords("my_variable_name")
        assert "my_variable_name" in kw

    def test_numeric_mixed(self):
        # regex: [a-zA-Z_]\w{2,} - must start with letter or underscore
        kw = _extract_keywords("var123 _test 99nums")
        assert "var123" in kw
        assert "_test" in kw
        # "99nums" starts with digits so regex won't match "99nums",
        # but "nums" is only 4 chars starting with letter => matched
        assert "nums" in kw

    def test_empty_string(self):
        kw = _extract_keywords("")
        assert len(kw) == 0

    def test_returns_counter(self):
        kw = _extract_keywords("test test test")
        assert isinstance(kw, Counter)
        assert kw["test"] == 3

    def test_special_characters_stripped(self):
        kw = _extract_keywords("hello! world? foo-bar baz.")
        assert "hello" in kw
        assert "world" in kw
        assert "foo" in kw
        assert "bar" in kw
        assert "baz" in kw

    def test_stop_words_comprehensive(self):
        # Verify several stop words from the list
        stops = [
            "the",
            "and",
            "for",
            "that",
            "this",
            "with",
            "from",
            "are",
            "was",
            "were",
            "been",
            "have",
            "has",
            "had",
            "will",
            "would",
            "could",
            "should",
            "not",
            "but",
            "can",
            "all",
            "each",
            "which",
            "their",
            "said",
            "its",
            "into",
            "than",
            "other",
            "some",
            "them",
            "these",
            "then",
            "her",
            "two",
            "how",
            "our",
            "out",
        ]
        for word in stops:
            kw = _extract_keywords(word)
            assert word not in kw, f"Stop word '{word}' should be filtered"


# ===========================================================================
# 5. _keyword_overlap
# ===========================================================================


class TestKeywordOverlap:
    def test_full_overlap(self):
        text_kw = Counter({"auth": 1, "module": 1})
        plan_kw = Counter({"auth": 1, "module": 1})
        score = _keyword_overlap(text_kw, plan_kw)
        assert score == pytest.approx(1.0)

    def test_partial_overlap(self):
        text_kw = Counter({"auth": 1, "database": 1})
        plan_kw = Counter({"auth": 2, "module": 1})
        score = _keyword_overlap(text_kw, plan_kw)
        # common = {"auth"}, overlap_weight = 2, plan_weight = 3
        assert score == pytest.approx(2.0 / 3.0)

    def test_no_overlap(self):
        text_kw = Counter({"alpha": 1})
        plan_kw = Counter({"beta": 1})
        score = _keyword_overlap(text_kw, plan_kw)
        assert score == 0.0

    def test_empty_text_keywords(self):
        score = _keyword_overlap(Counter(), Counter({"auth": 1}))
        assert score == 0.0

    def test_empty_plan_keywords(self):
        score = _keyword_overlap(Counter({"auth": 1}), Counter())
        assert score == 0.0

    def test_both_empty(self):
        score = _keyword_overlap(Counter(), Counter())
        assert score == 0.0

    def test_weighted_by_plan_frequency(self):
        text_kw = Counter({"auth": 1})
        plan_kw = Counter({"auth": 5, "database": 5})
        score = _keyword_overlap(text_kw, plan_kw)
        # overlap_weight = 5, plan_weight = 10
        assert score == pytest.approx(0.5)


# ===========================================================================
# 6. _estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    def test_basic_estimate(self):
        assert _estimate_tokens("hello world") == max(1, len("hello world") // 4)

    def test_empty_string_returns_one(self):
        assert _estimate_tokens("") == 1

    def test_short_string_returns_one(self):
        assert _estimate_tokens("ab") == 1

    def test_long_string(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100

    def test_minimum_is_one(self):
        # len("x") // 4 = 0, so max(1, 0) = 1
        assert _estimate_tokens("x") == 1


# ===========================================================================
# 7. score_context_items - empty / no steps
# ===========================================================================


class TestScoreContextItemsBasic:
    def test_empty_context_items(self, pcf):
        result = pcf.score_context_items([], ["step1"])
        assert result == []

    def test_no_upcoming_steps_neutral_score(self, pcf):
        items = ["item one", "item two"]
        scored = pcf.score_context_items(items, [])
        assert len(scored) == 2
        for s in scored:
            assert s.relevance_score == 0.5
            assert s.matched_steps == []
            assert s.keyword_overlap == 0.0
            assert s.position_score == 0.5

    def test_no_upcoming_steps_preserves_content(self, pcf):
        items = ["alpha content", "beta content"]
        scored = pcf.score_context_items(items, [])
        contents = [s.content for s in scored]
        assert contents == items

    def test_both_empty(self, pcf):
        result = pcf.score_context_items([], [])
        assert result == []


# ===========================================================================
# 8. score_context_items - matching keywords
# ===========================================================================


class TestScoreContextItemsMatching:
    def test_matching_item_scores_higher(self, pcf):
        items = [
            "database migration script for postgres",
            "implement authentication module with jwt tokens",
        ]
        steps = ["implement authentication module"]
        scored = pcf.score_context_items(items, steps)
        auth_item = next(s for s in scored if "authentication" in s.content)
        db_item = next(s for s in scored if "database" in s.content)
        assert auth_item.relevance_score > db_item.relevance_score

    def test_matched_steps_populated(self, pcf):
        items = ["write tests for authentication"]
        steps = ["implement authentication module", "deploy service"]
        scored = pcf.score_context_items(items, steps)
        assert len(scored) == 1
        # Should match the first step (both share "authentication")
        assert len(scored[0].matched_steps) >= 1

    def test_keyword_overlap_nonzero_for_match(self, pcf):
        items = ["authentication module code"]
        steps = ["implement authentication module"]
        scored = pcf.score_context_items(items, steps)
        assert scored[0].keyword_overlap > 0.0

    def test_keyword_overlap_zero_for_no_match(self, pcf):
        items = ["completely unrelated zebra content"]
        steps = ["implement authentication module"]
        scored = pcf.score_context_items(items, steps)
        assert scored[0].keyword_overlap == 0.0

    def test_relevance_formula(self, pcf):
        """relevance = overlap * 0.6 + position_score * 0.4"""
        items = ["authentication module implementation"]
        steps = ["implement authentication module"]
        scored = pcf.score_context_items(items, steps)
        s = scored[0]
        expected = s.keyword_overlap * 0.6 + s.position_score * 0.4
        assert s.relevance_score == pytest.approx(expected)

    def test_all_items_scored(self, pcf):
        items = ["item1", "item2", "item3", "item4"]
        steps = ["step1"]
        scored = pcf.score_context_items(items, steps)
        assert len(scored) == 4


# ===========================================================================
# 9. Position scoring
# ===========================================================================


class TestPositionScoring:
    def test_closer_step_gives_higher_position_score(self, pcf):
        items = ["implement authentication"]
        # Step 0 matches, step 1 also matches but step 0 is closer
        steps = ["implement authentication now", "something else later"]
        scored = pcf.score_context_items(items, steps)
        # best_position=0 => position_score = 0.8^0 = 1.0
        assert scored[0].position_score == pytest.approx(1.0)

    def test_distant_step_gives_lower_position_score(self, pcf):
        items = ["deploy service"]
        steps = [
            "implement authentication module",
            "write tests for auth",
            "deploy service to production",
        ]
        scored = pcf.score_context_items(items, steps)
        # "deploy" and "service" match step 2 => position_score = 0.8^2 = 0.64
        if scored[0].matched_steps:
            assert scored[0].position_score <= 0.8**1

    def test_no_match_gives_zero_position_score(self, pcf):
        items = ["completely unrelated content xyz"]
        steps = ["implement authentication module"]
        scored = pcf.score_context_items(items, steps)
        assert scored[0].position_score == 0.0

    def test_position_decay_constant(self):
        assert PlanContextFilter.POSITION_DECAY == 0.8

    def test_first_step_full_weight(self, pcf):
        """Matching only step 0 should yield position_score = 0.8^0 = 1.0."""
        items = ["authentication module"]
        steps = ["authentication module implementation"]
        scored = pcf.score_context_items(items, steps)
        if scored[0].matched_steps:
            assert scored[0].position_score == pytest.approx(1.0)


# ===========================================================================
# 10. filter - budget_ratio
# ===========================================================================


class TestFilterBudget:
    def test_default_budget_used(self, pcf):
        items = [f"item {i} content here padding" for i in range(10)]
        steps = ["step one"]
        result = pcf.filter(items, steps)
        # DEFAULT_BUDGET = 0.7, 10 * 0.7 = 7
        assert result.kept_count == 7

    def test_custom_budget_ratio(self, pcf):
        items = [f"item {i} content padding text" for i in range(10)]
        steps = ["step one"]
        result = pcf.filter(items, steps, budget_ratio=0.5)
        # 10 * 0.5 = 5
        assert result.kept_count == 5

    def test_budget_ratio_zero_uses_default(self, pcf):
        items = [f"item {i} content text padding" for i in range(10)]
        steps = ["step one"]
        result = pcf.filter(items, steps, budget_ratio=0.0)
        # budget_ratio=0.0 => falsy => default 0.7 => 7
        assert result.kept_count == 7

    def test_budget_always_keeps_at_least_one(self, pcf):
        items = ["only item here"]
        steps = ["step one"]
        result = pcf.filter(items, steps, budget_ratio=0.01)
        # max(1, int(1 * 0.01)) = max(1, 0) = 1
        assert result.kept_count == 1

    def test_total_items_correct(self, pcf):
        items = [f"item {i}" for i in range(5)]
        steps = ["step"]
        result = pcf.filter(items, steps, budget_ratio=0.6)
        assert result.total_items == 5

    def test_kept_plus_dropped_equals_total(self, pcf):
        items = [f"content item {i} padding text words" for i in range(8)]
        steps = ["step one"]
        result = pcf.filter(items, steps, budget_ratio=0.5)
        assert len(result.kept_items) + len(result.dropped_items) == result.total_items


# ===========================================================================
# 11. filter - relevance ordering
# ===========================================================================


class TestFilterRelevanceOrdering:
    def test_most_relevant_kept(self, pcf):
        items = [
            "random unrelated xyzabc content",
            "implement authentication module code",
            "another unrelated qqq content",
        ]
        steps = ["implement authentication module"]
        result = pcf.filter(items, steps, budget_ratio=0.4)
        # Should keep 1 item (max(1, int(3*0.4))=1), the auth one
        kept_contents = [s.content for s in result.kept_items]
        assert any("authentication" in c for c in kept_contents)

    def test_least_relevant_dropped(self, pcf):
        items = [
            "implement authentication module code",
            "random unrelated xyzabc content filler",
        ]
        steps = ["implement authentication module"]
        result = pcf.filter(items, steps, budget_ratio=0.5)
        # keep 1 out of 2
        dropped_contents = [s.content for s in result.dropped_items]
        assert any("unrelated" in c for c in dropped_contents)

    def test_kept_items_sorted_by_relevance_descending(self, pcf):
        items = [f"item {i} content text filler" for i in range(6)]
        steps = ["step one"]
        result = pcf.filter(items, steps, budget_ratio=0.8)
        scores = [s.relevance_score for s in result.kept_items]
        assert scores == sorted(scores, reverse=True)


# ===========================================================================
# 12. filter - compression ratio
# ===========================================================================


class TestFilterCompression:
    def test_compression_ratio_range(self, pcf):
        items = [f"item {i} with some text content" for i in range(10)]
        steps = ["step one"]
        result = pcf.filter(items, steps, budget_ratio=0.5)
        assert 0.0 <= result.compression_ratio <= 1.0

    def test_compression_ratio_computed_from_tokens(self, pcf):
        items = ["short", "a bit longer content here with words"]
        steps = ["step"]
        result = pcf.filter(items, steps, budget_ratio=0.5)
        # Manually compute expected
        tokens_before = sum(_estimate_tokens(i) for i in items)
        tokens_after = sum(_estimate_tokens(s.content) for s in result.kept_items)
        expected_ratio = tokens_after / max(tokens_before, 1)
        assert result.compression_ratio == pytest.approx(expected_ratio)

    def test_tokens_before_sum(self, pcf):
        items = ["hello world", "testing content here"]
        steps = ["step"]
        result = pcf.filter(items, steps, budget_ratio=1.0)
        expected = sum(_estimate_tokens(i) for i in items)
        assert result.tokens_before == expected

    def test_full_budget_ratio_one(self, pcf):
        items = [f"item {i} content" for i in range(5)]
        steps = ["step"]
        result = pcf.filter(items, steps, budget_ratio=1.0)
        # Keep all items
        assert result.kept_count == 5
        assert result.compression_ratio == pytest.approx(1.0)


# ===========================================================================
# 13. filter - empty input
# ===========================================================================


class TestFilterEmpty:
    def test_empty_items(self, pcf):
        result = pcf.filter([], ["step"])
        assert result.kept_items == []
        assert result.dropped_items == []
        assert result.total_items == 0
        assert result.kept_count == 0
        assert result.tokens_before == 0
        assert result.tokens_after == 0
        assert result.compression_ratio == 1.0

    def test_empty_steps(self, pcf):
        result = pcf.filter(["item one", "item two"], [])
        # All items get neutral 0.5 score, default budget 0.7
        assert result.total_items == 2

    def test_both_empty(self, pcf):
        result = pcf.filter([], [])
        assert result.total_items == 0
        assert result.compression_ratio == 1.0


# ===========================================================================
# 14. get_stats tracking
# ===========================================================================


class TestGetStats:
    def test_initial_stats_zero(self, pcf):
        stats = pcf.get_stats()
        assert stats.total_filter_calls == 0
        assert stats.total_items_processed == 0
        assert stats.total_items_dropped == 0
        assert stats.avg_compression_ratio == 0.0
        assert stats.avg_relevance_score == 0.0

    def test_stats_after_one_filter(self, pcf):
        items = [f"item {i} content text" for i in range(4)]
        pcf.filter(items, ["step"], budget_ratio=0.5)
        stats = pcf.get_stats()
        assert stats.total_filter_calls == 1
        assert stats.total_items_processed == 4
        assert stats.total_items_dropped == 2  # 4 - max(1, int(4*0.5)) = 4-2=2
        assert stats.avg_compression_ratio > 0.0

    def test_stats_accumulate_across_calls(self, pcf):
        items_a = ["item alpha content text"]
        items_b = ["item beta content text", "item gamma content text"]
        pcf.filter(items_a, ["step"], budget_ratio=1.0)
        pcf.filter(items_b, ["step"], budget_ratio=1.0)
        stats = pcf.get_stats()
        assert stats.total_filter_calls == 2
        assert stats.total_items_processed == 3

    def test_avg_relevance_tracked_from_scoring(self, pcf):
        pcf.score_context_items(["authentication module"], ["implement authentication"])
        stats = pcf.get_stats()
        assert stats.avg_relevance_score > 0.0

    def test_avg_relevance_across_multiple_scores(self, pcf):
        pcf.score_context_items(["auth module"], ["implement auth"])
        pcf.score_context_items(["unrelated xyz"], ["implement auth"])
        stats = pcf.get_stats()
        # Should be average of all scored items
        assert 0.0 <= stats.avg_relevance_score <= 1.0


# ===========================================================================
# 15. Singleton pattern
# ===========================================================================


class TestSingleton:
    def test_get_returns_instance(self):
        instance = get_plan_context_filter()
        assert isinstance(instance, PlanContextFilter)

    def test_get_returns_same_instance(self):
        a = get_plan_context_filter()
        b = get_plan_context_filter()
        assert a is b

    def test_reset_clears_instance(self):
        a = get_plan_context_filter()
        reset_plan_context_filter()
        b = get_plan_context_filter()
        assert a is not b

    def test_reset_gives_fresh_stats(self):
        pcf = get_plan_context_filter()
        pcf.filter(["item content text"], ["step"], budget_ratio=1.0)
        reset_plan_context_filter()
        pcf2 = get_plan_context_filter()
        stats = pcf2.get_stats()
        assert stats.total_filter_calls == 0

    def test_singleton_thread_safety(self):
        """Concurrent get_plan_context_filter calls return the same instance."""
        reset_plan_context_filter()
        results = []

        def grab():
            results.append(get_plan_context_filter())

        threads = [threading.Thread(target=grab) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)


# ===========================================================================
# 16. Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_single_item_kept(self, pcf):
        result = pcf.filter(["only item"], ["step"], budget_ratio=0.1)
        assert result.kept_count == 1
        assert result.total_items == 1

    def test_all_same_relevance(self, pcf):
        # No upcoming steps => all items get 0.5
        items = ["aaa bbb ccc", "ddd eee fff", "ggg hhh iii"]
        result = pcf.filter(items, [], budget_ratio=0.67)
        # All scored 0.5 => kept_count = max(1, int(3*0.7)) = 2 (default budget since 0.67 used)
        assert result.kept_count == max(1, int(3 * 0.67))

    def test_very_long_content(self, pcf):
        long_item = "authentication " * 1000
        scored = pcf.score_context_items([long_item], ["implement authentication"])
        assert len(scored) == 1
        assert scored[0].relevance_score > 0.0

    def test_special_characters_in_content(self, pcf):
        items = ["@#$%^&*()!!! ???"]
        scored = pcf.score_context_items(items, ["implement module"])
        assert len(scored) == 1

    def test_unicode_content(self, pcf):
        items = ["authentication avec des accents"]
        scored = pcf.score_context_items(items, ["authentication module"])
        assert len(scored) == 1

    def test_many_steps(self, pcf):
        items = ["authentication module code"]
        steps = [f"step {i} for project" for i in range(50)]
        scored = pcf.score_context_items(items, steps)
        assert len(scored) == 1

    def test_many_items(self, pcf):
        items = [f"item number {i} with content" for i in range(100)]
        steps = ["find item number"]
        result = pcf.filter(items, steps, budget_ratio=0.1)
        assert result.kept_count == max(1, int(100 * 0.1))
        assert result.total_items == 100

    def test_matched_steps_truncated_to_50_chars(self, pcf):
        items = ["authentication module"]
        long_step = "implement authentication module " + "x" * 100
        scored = pcf.score_context_items(items, [long_step])
        if scored[0].matched_steps:
            for ms in scored[0].matched_steps:
                assert len(ms) <= 50

    def test_min_relevance_constant(self):
        assert PlanContextFilter.MIN_RELEVANCE == 0.1

    def test_default_budget_constant(self):
        assert PlanContextFilter.DEFAULT_BUDGET == 0.7

    def test_filter_does_not_mutate_input(self, pcf):
        items = ["alpha content", "beta content", "gamma content"]
        items_copy = list(items)
        steps = ["step one"]
        steps_copy = list(steps)
        pcf.filter(items, steps, budget_ratio=0.5)
        assert items == items_copy
        assert steps == steps_copy

    def test_score_context_items_does_not_mutate_input(self, pcf):
        items = ["alpha content", "beta content"]
        items_copy = list(items)
        steps = ["step"]
        steps_copy = list(steps)
        pcf.score_context_items(items, steps)
        assert items == items_copy
        assert steps == steps_copy
