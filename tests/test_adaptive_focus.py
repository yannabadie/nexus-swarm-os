"""Tests for Adaptive Focus Memory - 3-tier fidelity context management."""

import time

import pytest

from core.memory_pkg.memory.adaptive_focus import (
    TIER_TOKEN_RATIOS,
    AdaptiveFocusManager,
    FidelityAssignment,
    FidelityLevel,
    FocusItem,
    get_adaptive_focus,
    reset_adaptive_focus,
)

# =============================================================================
# FidelityLevel Enum
# =============================================================================


class TestFidelityLevel:
    def test_three_tiers(self):
        assert len(FidelityLevel) == 3

    def test_tier_values(self):
        assert FidelityLevel.FULL.value == "full"
        assert FidelityLevel.COMPRESSED.value == "compressed"
        assert FidelityLevel.PLACEHOLDER.value == "placeholder"

    def test_tier_token_ratios(self):
        assert TIER_TOKEN_RATIOS[FidelityLevel.FULL] == 1.0
        assert TIER_TOKEN_RATIOS[FidelityLevel.COMPRESSED] < 1.0
        assert TIER_TOKEN_RATIOS[FidelityLevel.PLACEHOLDER] < TIER_TOKEN_RATIOS[FidelityLevel.COMPRESSED]


# =============================================================================
# FocusItem
# =============================================================================


class TestFocusItem:
    def test_auto_timestamp(self):
        item = FocusItem(item_id=0, content="test")
        assert item.timestamp > 0

    def test_auto_token_estimate(self):
        item = FocusItem(item_id=0, content="hello world this is a test")
        assert item.token_estimate > 0

    def test_pinned_default_false(self):
        item = FocusItem(item_id=0, content="test")
        assert not item.pinned

    def test_importance_stored(self):
        item = FocusItem(item_id=0, content="test", importance=0.9)
        assert item.importance == 0.9


# =============================================================================
# FidelityAssignment
# =============================================================================


class TestFidelityAssignment:
    def test_compression_ratio_full(self):
        a = FidelityAssignment(
            item_id=0,
            tier=FidelityLevel.FULL,
            composite_score=0.9,
            allocated_tokens=100,
            content="test",
            original_tokens=100,
        )
        assert a.compression_ratio == pytest.approx(0.0)

    def test_compression_ratio_compressed(self):
        a = FidelityAssignment(
            item_id=0,
            tier=FidelityLevel.COMPRESSED,
            composite_score=0.5,
            allocated_tokens=30,
            content="test",
            original_tokens=100,
        )
        assert a.compression_ratio == pytest.approx(0.7)

    def test_to_dict(self):
        a = FidelityAssignment(
            item_id=1,
            tier=FidelityLevel.PLACEHOLDER,
            composite_score=0.2,
            allocated_tokens=5,
            content="[ref]",
            original_tokens=100,
        )
        d = a.to_dict()
        assert d["tier"] == "placeholder"
        assert d["item_id"] == 1


# =============================================================================
# Scoring
# =============================================================================


class TestScoring:
    def setup_method(self):
        self.mgr = AdaptiveFocusManager(token_budget=10000)

    def test_high_importance_scores_high(self):
        item = FocusItem(item_id=0, content="This is important content with many words " * 10, importance=0.95)
        score = self.mgr.score_item(item)
        assert score > 0.6

    def test_low_importance_scores_low(self):
        item = FocusItem(item_id=0, content="ok", importance=0.1)
        score = self.mgr.score_item(item)
        assert score < 0.5  # Low importance + short content, but recency boost

    def test_recent_items_score_higher(self):
        old_item = FocusItem(item_id=0, content="old content " * 20, importance=0.5)
        old_item.timestamp = time.monotonic() - 600  # 10 min ago (past half-life)
        new_item = FocusItem(item_id=1, content="new content " * 20, importance=0.5)

        old_score = self.mgr.score_item(old_item)
        new_score = self.mgr.score_item(new_item)
        assert new_score > old_score

    def test_longer_content_scores_higher(self):
        short = FocusItem(item_id=0, content="hi", importance=0.5)
        long_content = FocusItem(item_id=1, content="detailed analysis " * 50, importance=0.5)

        short_score = self.mgr.score_item(short)
        long_score = self.mgr.score_item(long_content)
        assert long_score > short_score

    def test_score_clamped_0_to_1(self):
        item = FocusItem(item_id=0, content="test " * 200, importance=1.0)
        score = self.mgr.score_item(item)
        assert 0.0 <= score <= 1.0

    def test_score_all_returns_sorted(self):
        self.mgr.add_item("low", importance=0.1)
        self.mgr.add_item("high priority content " * 20, importance=0.95)
        self.mgr.add_item("medium", importance=0.5)

        scored = self.mgr.score_all()
        scores = [s for _, s in scored]
        assert scores == sorted(scores, reverse=True)


# =============================================================================
# Fidelity Assignment
# =============================================================================


class TestFidelityAssignmentLogic:
    def test_high_importance_gets_full(self):
        mgr = AdaptiveFocusManager(token_budget=10000)
        mgr.add_item("Critical decision: use JWT for auth " * 10, importance=0.95)

        result = mgr.assign_fidelity()
        assert result.assignments[0].tier == FidelityLevel.FULL

    def test_low_importance_gets_placeholder(self):
        mgr = AdaptiveFocusManager(token_budget=100)  # Very tight budget
        mgr.add_item("Very important content " * 20, importance=0.95)
        mgr.add_item("ok", importance=0.05)

        result = mgr.assign_fidelity()
        # Find the "ok" item
        ok_assignment = [a for a in result.assignments if "ok" in a.content.lower()][0]
        assert ok_assignment.tier in (FidelityLevel.COMPRESSED, FidelityLevel.PLACEHOLDER)

    def test_pinned_always_full(self):
        mgr = AdaptiveFocusManager(token_budget=50)  # Very tight
        mgr.add_item("This must stay verbatim " * 10, importance=0.1, pinned=True)

        result = mgr.assign_fidelity()
        assert result.assignments[0].tier == FidelityLevel.FULL

    def test_budget_constrains_full_assignments(self):
        mgr = AdaptiveFocusManager(token_budget=100)
        for i in range(20):
            mgr.add_item(f"Content item {i} with some text " * 5, importance=0.8)

        result = mgr.assign_fidelity()
        # Not all can be FULL with tight budget
        assert result.items_full < 20
        assert result.items_compressed + result.items_placeholder > 0

    def test_empty_manager_returns_empty(self):
        mgr = AdaptiveFocusManager()
        result = mgr.assign_fidelity()
        assert result.assignments == []
        assert result.total_tokens_before == 0

    def test_result_has_correct_counts(self):
        mgr = AdaptiveFocusManager(token_budget=200)
        mgr.add_item("Important stuff " * 10, importance=0.9)
        mgr.add_item("Medium relevance " * 10, importance=0.5)
        mgr.add_item("ok", importance=0.05)

        result = mgr.assign_fidelity()
        total = result.items_full + result.items_compressed + result.items_placeholder
        assert total == 3

    def test_compression_ratio_positive(self):
        mgr = AdaptiveFocusManager(token_budget=100)
        for i in range(10):
            mgr.add_item(f"Item {i} with substantial content " * 10, importance=0.5)

        result = mgr.assign_fidelity()
        assert result.compression_ratio > 0


# =============================================================================
# Content Compression
# =============================================================================


class TestContentCompression:
    def setup_method(self):
        self.mgr = AdaptiveFocusManager()

    def test_compress_preserves_first_and_last(self):
        text = "First sentence here. Middle stuff. Another middle. Last conclusion."
        compressed = self.mgr._compress_content(text)
        assert "First sentence" in compressed
        assert "Last conclusion" in compressed

    def test_compress_preserves_signal_words(self):
        text = "Start here. This is filler. The error was found. More filler. Done."
        compressed = self.mgr._compress_content(text)
        assert "error" in compressed

    def test_compress_short_text_unchanged(self):
        text = "Short. Text."
        compressed = self.mgr._compress_content(text)
        assert compressed == text

    def test_placeholder_short_text(self):
        placeholder = self.mgr._placeholder_content("hello", "user")
        assert "hello" in placeholder
        assert "user" in placeholder

    def test_placeholder_long_text(self):
        long_text = "word " * 50
        placeholder = self.mgr._placeholder_content(long_text, "assistant")
        assert "50 words" in placeholder
        assert "..." in placeholder


# =============================================================================
# Compressed Context Output
# =============================================================================


class TestCompressedContext:
    def test_get_compressed_context(self):
        mgr = AdaptiveFocusManager(token_budget=10000)
        mgr.add_item("First important item", importance=0.9)
        mgr.add_item("Second item", importance=0.5)

        context = mgr.get_compressed_context()
        assert "First important item" in context
        assert len(context) > 0

    def test_needs_compression(self):
        mgr = AdaptiveFocusManager(token_budget=10)
        mgr.add_item("This is a long item " * 50, importance=0.5)
        assert mgr.needs_compression()

    def test_no_compression_needed(self):
        mgr = AdaptiveFocusManager(token_budget=100000)
        mgr.add_item("Short", importance=0.5)
        assert not mgr.needs_compression()


# =============================================================================
# State Management
# =============================================================================


class TestStateManagement:
    def test_item_count(self):
        mgr = AdaptiveFocusManager()
        assert mgr.item_count == 0
        mgr.add_item("test")
        assert mgr.item_count == 1

    def test_total_tokens(self):
        mgr = AdaptiveFocusManager()
        mgr.add_item("hello world test")
        assert mgr.total_tokens > 0

    def test_clear(self):
        mgr = AdaptiveFocusManager()
        mgr.add_item("test")
        mgr.clear()
        assert mgr.item_count == 0

    def test_get_stats_empty(self):
        mgr = AdaptiveFocusManager()
        stats = mgr.get_stats()
        assert stats["item_count"] == 0

    def test_get_stats_with_data(self):
        mgr = AdaptiveFocusManager(token_budget=10000)
        mgr.add_item("test content " * 10, importance=0.8)
        stats = mgr.get_stats()
        assert stats["item_count"] == 1
        assert stats["avg_score"] > 0

    def test_importance_clamped(self):
        mgr = AdaptiveFocusManager()
        item = mgr.add_item("test", importance=1.5)
        assert item.importance == 1.0
        item2 = mgr.add_item("test", importance=-0.5)
        assert item2.importance == 0.0

    def test_focus_result_to_dict(self):
        mgr = AdaptiveFocusManager(token_budget=10000)
        mgr.add_item("test", importance=0.8)
        result = mgr.assign_fidelity()
        d = result.to_dict()
        assert "compression_ratio" in d
        assert "items_full" in d


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_adaptive_focus()
        m1 = get_adaptive_focus()
        m2 = get_adaptive_focus()
        assert m1 is m2

    def test_reset_creates_new_instance(self):
        reset_adaptive_focus()
        m1 = get_adaptive_focus()
        reset_adaptive_focus()
        m2 = get_adaptive_focus()
        assert m1 is not m2
