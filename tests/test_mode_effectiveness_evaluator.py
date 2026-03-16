"""
Tests for V12.4 Mode Effectiveness Evaluator.

Validates:
- ModeEvaluation to_dict
- ModeEffectivenessSummary to_dict / properties
- EvaluatorStats to_dict
- Recording evaluations
- Mode summary updates
- Domain-mode analysis (best mode, ranking)
- Queries (all summaries, recent evaluations)
- Listing modes/domains
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.swarm.mode_effectiveness_evaluator import (
    MAX_EVALUATIONS,
    EvaluatorStats,
    ModeEffectivenessEvaluator,
    ModeEffectivenessSummary,
    ModeEvaluation,
    get_mode_evaluator,
    reset_mode_evaluator,
)

# =============================================================================
# ModeEvaluation Tests
# =============================================================================


class TestModeEvaluation:
    """Test ModeEvaluation dataclass."""

    def test_to_dict(self):
        e = ModeEvaluation(mode="PARALLEL", task_domain="coding", quality_score=0.85, success=True)
        d = e.to_dict()
        assert d["mode"] == "PARALLEL"
        assert d["quality_score"] == 0.85


# =============================================================================
# ModeEffectivenessSummary Tests
# =============================================================================


class TestModeEffectivenessSummary:
    """Test ModeEffectivenessSummary dataclass."""

    def test_success_rate(self):
        m = ModeEffectivenessSummary(mode="P", total_evaluations=10, successes=8)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        m = ModeEffectivenessSummary(mode="P")
        assert m.success_rate == 0.0

    def test_avg_quality(self):
        m = ModeEffectivenessSummary(mode="P", total_evaluations=4, total_quality=3.2)
        assert abs(m.avg_quality - 0.8) < 0.01

    def test_avg_duration(self):
        m = ModeEffectivenessSummary(mode="P", total_evaluations=4, total_duration_ms=400.0)
        assert abs(m.avg_duration_ms - 100.0) < 0.01

    def test_to_dict(self):
        m = ModeEffectivenessSummary(mode="PARALLEL", total_evaluations=5)
        d = m.to_dict()
        assert "success_rate" in d
        assert "avg_quality" in d


# =============================================================================
# EvaluatorStats Tests
# =============================================================================


class TestEvaluatorStats:
    """Test EvaluatorStats dataclass."""

    def test_to_dict(self):
        s = EvaluatorStats(total_evaluations=20, unique_modes=3, unique_domains=5)
        d = s.to_dict()
        assert d["total_evaluations"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test evaluation recording."""

    def test_record_basic(self):
        e = ModeEffectivenessEvaluator()
        ev = e.record_evaluation("PARALLEL", task_domain="coding", quality_score=0.9, success=True)
        assert ev.mode == "PARALLEL"
        assert e.evaluation_count == 1

    def test_summary_updates(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("PARALLEL", quality_score=0.8, success=True)
        e.record_evaluation("PARALLEL", quality_score=0.6, success=False)
        s = e.get_mode_summary("PARALLEL")
        assert s is not None
        assert s.total_evaluations == 2
        assert s.successes == 1

    def test_multiple_modes(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("PARALLEL", quality_score=0.8)
        e.record_evaluation("SEQUENTIAL", quality_score=0.7)
        assert len(e.get_all_summaries()) == 2


# =============================================================================
# Domain Analysis Tests
# =============================================================================


class TestDomainAnalysis:
    """Test domain-mode analysis."""

    def test_best_mode_for_domain(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("PARALLEL", task_domain="coding", quality_score=0.6)
        e.record_evaluation("LEAD_SUPPORT", task_domain="coding", quality_score=0.9)
        best = e.get_best_mode_for_domain("coding")
        assert best == "LEAD_SUPPORT"

    def test_best_mode_empty(self):
        e = ModeEffectivenessEvaluator()
        assert e.get_best_mode_for_domain("missing") is None

    def test_domain_mode_ranking(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("PARALLEL", task_domain="coding", quality_score=0.6)
        e.record_evaluation("LEAD_SUPPORT", task_domain="coding", quality_score=0.9)
        e.record_evaluation("SEQUENTIAL", task_domain="coding", quality_score=0.7)
        ranking = e.get_domain_mode_ranking("coding")
        assert len(ranking) == 3
        assert ranking[0][0] == "LEAD_SUPPORT"  # highest quality

    def test_domain_ranking_empty(self):
        e = ModeEffectivenessEvaluator()
        assert e.get_domain_mode_ranking("missing") == []


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_mode_summary_not_found(self):
        e = ModeEffectivenessEvaluator()
        assert e.get_mode_summary("missing") is None

    def test_get_all_summaries_sorted(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("weak", quality_score=0.3)
        e.record_evaluation("strong", quality_score=0.9)
        summaries = e.get_all_summaries()
        assert summaries[0].mode == "strong"  # highest avg_quality

    def test_recent_evaluations(self):
        e = ModeEffectivenessEvaluator()
        for i in range(5):
            e.record_evaluation(f"mode_{i}", quality_score=0.5)
        recent = e.get_recent_evaluations(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("PARALLEL", quality_score=0.8)
        e.record_evaluation("SEQUENTIAL", quality_score=0.7)
        e.record_evaluation("PARALLEL", quality_score=0.9)
        recent = e.get_recent_evaluations(mode="PARALLEL")
        assert len(recent) == 2


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test listing methods."""

    def test_list_modes(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("SEQUENTIAL")
        e.record_evaluation("PARALLEL")
        assert e.list_modes() == ["PARALLEL", "SEQUENTIAL"]

    def test_list_domains(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("P", task_domain="security")
        e.record_evaluation("P", task_domain="coding")
        assert e.list_domains() == ["coding", "security"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded evaluation history."""

    def test_eviction(self):
        e = ModeEffectivenessEvaluator(max_evaluations=5)
        for i in range(10):
            e.record_evaluation(f"mode_{i}", quality_score=0.5)
        assert e.evaluation_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test evaluator statistics."""

    def test_initial_stats(self):
        e = ModeEffectivenessEvaluator()
        stats = e.get_stats()
        assert stats.total_evaluations == 0

    def test_stats_after_recording(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("PARALLEL", task_domain="coding", quality_score=0.8, success=True)
        e.record_evaluation("SEQUENTIAL", task_domain="security", quality_score=0.6, success=False)
        stats = e.get_stats()
        assert stats.total_evaluations == 2
        assert stats.unique_modes == 2
        assert stats.unique_domains == 2

    def test_stats_to_dict(self):
        e = ModeEffectivenessEvaluator()
        d = e.get_stats().to_dict()
        assert "total_evaluations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("P", quality_score=0.5)
        assert e.evaluation_count == 1

    def test_clear(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("P", task_domain="coding", quality_score=0.5)
        e.clear()
        assert e.evaluation_count == 0
        assert e.get_mode_summary("P") is None

    def test_to_dict(self):
        e = ModeEffectivenessEvaluator()
        e.record_evaluation("P", quality_score=0.5)
        d = e.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global mode evaluator."""

    def test_get(self):
        reset_mode_evaluator()
        e = get_mode_evaluator()
        assert isinstance(e, ModeEffectivenessEvaluator)

    def test_singleton(self):
        reset_mode_evaluator()
        e1 = get_mode_evaluator()
        e2 = get_mode_evaluator()
        assert e1 is e2

    def test_reset(self):
        reset_mode_evaluator()
        e1 = get_mode_evaluator()
        reset_mode_evaluator()
        e2 = get_mode_evaluator()
        assert e1 is not e2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_swarm_package(self):
        from core.intelligence.swarm import (
            EvaluatorStats,
            ModeEffectivenessEvaluator,
            ModeEffectivenessSummary,
            ModeEvaluation,
            get_mode_evaluator,
            reset_mode_evaluator,
        )

        assert all(
            [
                ModeEffectivenessEvaluator,
                ModeEvaluation,
                ModeEffectivenessSummary,
                EvaluatorStats,
                get_mode_evaluator,
                reset_mode_evaluator,
            ]
        )

    def test_constants(self):
        assert MAX_EVALUATIONS == 50000
