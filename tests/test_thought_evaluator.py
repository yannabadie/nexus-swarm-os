"""
Tests for V12.4 Thought Evaluator.

Validates:
- ThoughtScore to_dict
- EvaluationResult to_dict
- EvaluatorStats to_dict
- Scoring (basic, weighted, clamping)
- Redundancy detection and pruning
- Ranking (top, by tag, best, worst)
- Evaluation (aggregate)
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.reasoning.thought_evaluator import (
    MAX_THOUGHTS,
    REDUNDANCY_THRESHOLD,
    EvaluationResult,
    EvaluatorStats,
    ThoughtEvaluator,
    ThoughtScore,
    get_thought_evaluator,
    reset_thought_evaluator,
)

# =============================================================================
# ThoughtScore Tests
# =============================================================================


class TestThoughtScore:
    """Test ThoughtScore dataclass."""

    def test_basic(self):
        t = ThoughtScore(thought_id="t1", content="Test thought")
        assert t.thought_id == "t1"
        assert t.timestamp > 0

    def test_to_dict(self):
        t = ThoughtScore(thought_id="t1", novelty=0.8, relevance=0.9, confidence=0.7, composite_score=0.81)
        d = t.to_dict()
        assert d["novelty"] == 0.8
        assert d["composite_score"] == 0.81

    def test_content_truncated_in_dict(self):
        long_content = "x" * 200
        t = ThoughtScore(thought_id="t1", content=long_content)
        d = t.to_dict()
        assert len(d["content"]) == 100


# =============================================================================
# EvaluationResult Tests
# =============================================================================


class TestEvaluationResult:
    """Test EvaluationResult dataclass."""

    def test_to_dict(self):
        r = EvaluationResult(
            total_thoughts=10,
            average_score=0.75,
            best_thought_id="t1",
            worst_thought_id="t5",
            redundant_count=2,
            redundant_ids=["t3", "t4"],
        )
        d = r.to_dict()
        assert d["average_score"] == 0.75
        assert d["redundant_count"] == 2


# =============================================================================
# EvaluatorStats Tests
# =============================================================================


class TestEvaluatorStats:
    """Test EvaluatorStats dataclass."""

    def test_to_dict(self):
        s = EvaluatorStats(
            total_scored=5,
            total_pruned=1,
            average_novelty=0.7,
            average_relevance=0.8,
            average_confidence=0.6,
        )
        d = s.to_dict()
        assert d["total_scored"] == 5
        assert d["total_pruned"] == 1


# =============================================================================
# Scoring Tests
# =============================================================================


class TestScoring:
    """Test thought scoring."""

    def test_basic_score(self):
        e = ThoughtEvaluator()
        t = e.score_thought("t1", novelty=0.8, relevance=0.9, confidence=0.7)
        assert t.thought_id == "t1"
        assert t.composite_score > 0

    def test_weighted_score(self):
        e = ThoughtEvaluator()
        t = e.score_thought("t1", novelty=0.8, relevance=0.9, confidence=0.7)
        # Default weights: 0.3, 0.4, 0.3
        expected = 0.3 * 0.8 + 0.4 * 0.9 + 0.3 * 0.7
        assert abs(t.composite_score - expected) < 0.001

    def test_custom_weights(self):
        e = ThoughtEvaluator(novelty_weight=1.0, relevance_weight=0.0, confidence_weight=0.0)
        t = e.score_thought("t1", novelty=0.5, relevance=1.0, confidence=1.0)
        assert abs(t.composite_score - 0.5) < 0.001

    def test_clamping(self):
        e = ThoughtEvaluator()
        t = e.score_thought("t1", novelty=-0.5, relevance=2.0, confidence=0.5)
        assert t.novelty == 0.0
        assert t.relevance == 1.0

    def test_score_with_content(self):
        e = ThoughtEvaluator()
        t = e.score_thought("t1", content="The bug is in auth.py")
        assert t.content == "The bug is in auth.py"

    def test_score_with_tags(self):
        e = ThoughtEvaluator()
        t = e.score_thought("t1", tags=["coding", "debug"])
        assert t.tags == ["coding", "debug"]

    def test_get_score(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.8)
        t = e.get_score("t1")
        assert t is not None
        assert t.novelty == 0.8

    def test_get_score_not_found(self):
        e = ThoughtEvaluator()
        assert e.get_score("missing") is None

    def test_remove_thought(self):
        e = ThoughtEvaluator()
        e.score_thought("t1")
        assert e.remove_thought("t1") is True
        assert e.thought_count == 0

    def test_remove_not_found(self):
        e = ThoughtEvaluator()
        assert e.remove_thought("missing") is False

    def test_overwrite_existing(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.5)
        e.score_thought("t1", novelty=0.9)
        t = e.get_score("t1")
        assert t.novelty == 0.9
        assert e.thought_count == 1


# =============================================================================
# Redundancy Tests
# =============================================================================


class TestRedundancy:
    """Test redundancy detection and pruning."""

    def test_find_redundant(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.8)
        e.score_thought("t2", novelty=0.1)
        e.score_thought("t3", novelty=0.2)
        redundant = e.find_redundant(threshold=0.4)
        assert "t2" in redundant
        assert "t3" in redundant
        assert "t1" not in redundant

    def test_find_redundant_empty(self):
        e = ThoughtEvaluator()
        assert e.find_redundant() == []

    def test_prune_redundant(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.8)
        e.score_thought("t2", novelty=0.1)
        e.score_thought("t3", novelty=0.2)
        count = e.prune_redundant(threshold=0.4)
        assert count == 2
        assert e.thought_count == 1

    def test_prune_updates_stats(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.1)
        e.prune_redundant(threshold=0.5)
        stats = e.get_stats()
        assert stats.total_pruned == 1


# =============================================================================
# Ranking Tests
# =============================================================================


class TestRanking:
    """Test thought ranking."""

    def test_rank_thoughts(self):
        e = ThoughtEvaluator()
        e.score_thought("low", novelty=0.1, relevance=0.1, confidence=0.1)
        e.score_thought("high", novelty=0.9, relevance=0.9, confidence=0.9)
        e.score_thought("mid", novelty=0.5, relevance=0.5, confidence=0.5)
        ranked = e.rank_thoughts(limit=2)
        assert len(ranked) == 2
        assert ranked[0].thought_id == "high"

    def test_rank_with_limit(self):
        e = ThoughtEvaluator()
        for i in range(10):
            e.score_thought(f"t{i}", novelty=i / 10)
        ranked = e.rank_thoughts(limit=3)
        assert len(ranked) == 3

    def test_get_by_tag(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", tags=["coding"])
        e.score_thought("t2", tags=["research"])
        e.score_thought("t3", tags=["coding"])
        results = e.get_by_tag("coding")
        assert len(results) == 2

    def test_best_thought(self):
        e = ThoughtEvaluator()
        e.score_thought("low", novelty=0.1, relevance=0.1, confidence=0.1)
        e.score_thought("high", novelty=0.9, relevance=0.9, confidence=0.9)
        best = e.best_thought()
        assert best.thought_id == "high"

    def test_worst_thought(self):
        e = ThoughtEvaluator()
        e.score_thought("low", novelty=0.1, relevance=0.1, confidence=0.1)
        e.score_thought("high", novelty=0.9, relevance=0.9, confidence=0.9)
        worst = e.worst_thought()
        assert worst.thought_id == "low"

    def test_best_empty(self):
        e = ThoughtEvaluator()
        assert e.best_thought() is None

    def test_worst_empty(self):
        e = ThoughtEvaluator()
        assert e.worst_thought() is None


# =============================================================================
# Evaluation Tests
# =============================================================================


class TestEvaluation:
    """Test aggregate evaluation."""

    def test_evaluate_empty(self):
        e = ThoughtEvaluator()
        result = e.evaluate()
        assert result.total_thoughts == 0
        assert result.average_score == 0.0

    def test_evaluate_with_thoughts(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.8, relevance=0.9, confidence=0.7)
        e.score_thought("t2", novelty=0.1, relevance=0.5, confidence=0.3)
        result = e.evaluate()
        assert result.total_thoughts == 2
        assert result.best_thought_id == "t1"
        assert result.worst_thought_id == "t2"

    def test_evaluate_redundant_detection(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.8)
        e.score_thought("t2", novelty=0.1)
        result = e.evaluate(redundancy_threshold=0.5)
        assert result.redundant_count == 1
        assert "t2" in result.redundant_ids


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test evaluator statistics."""

    def test_initial_stats(self):
        e = ThoughtEvaluator()
        stats = e.get_stats()
        assert stats.total_scored == 0
        assert stats.total_pruned == 0

    def test_stats_after_scoring(self):
        e = ThoughtEvaluator()
        e.score_thought("t1", novelty=0.8, relevance=0.6, confidence=0.4)
        stats = e.get_stats()
        assert stats.total_scored == 1
        assert stats.average_novelty == 0.8
        assert stats.average_relevance == 0.6

    def test_stats_to_dict(self):
        e = ThoughtEvaluator()
        d = e.get_stats().to_dict()
        assert "total_scored" in d
        assert "total_pruned" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_thought_count(self):
        e = ThoughtEvaluator()
        e.score_thought("t1")
        e.score_thought("t2")
        assert e.thought_count == 2

    def test_clear(self):
        e = ThoughtEvaluator()
        e.score_thought("t1")
        e.prune_redundant(threshold=1.0)
        e.clear()
        assert e.thought_count == 0
        assert e.get_stats().total_pruned == 0

    def test_to_dict(self):
        e = ThoughtEvaluator()
        e.score_thought("t1")
        d = e.to_dict()
        assert d["thought_count"] == 1
        assert "weights" in d
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global thought evaluator."""

    def test_get(self):
        reset_thought_evaluator()
        ev = get_thought_evaluator()
        assert isinstance(ev, ThoughtEvaluator)

    def test_singleton(self):
        reset_thought_evaluator()
        e1 = get_thought_evaluator()
        e2 = get_thought_evaluator()
        assert e1 is e2

    def test_reset(self):
        reset_thought_evaluator()
        e1 = get_thought_evaluator()
        reset_thought_evaluator()
        e2 = get_thought_evaluator()
        assert e1 is not e2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_reasoning_package(self):
        from core.intelligence.reasoning import (
            EvaluationResult,
            EvaluatorStats,
            ThoughtEvaluator,
            ThoughtScore,
            get_thought_evaluator,
            reset_thought_evaluator,
        )

        assert all(
            [
                ThoughtEvaluator,
                ThoughtScore,
                EvaluationResult,
                EvaluatorStats,
                get_thought_evaluator,
                reset_thought_evaluator,
            ]
        )

    def test_constants(self):
        assert MAX_THOUGHTS == 10000
        assert REDUNDANCY_THRESHOLD == 0.4
