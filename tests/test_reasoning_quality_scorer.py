"""
Tests for V12.4 Reasoning Quality Scorer.

Validates:
- ReasoningEvaluation to_dict / properties
- AgentReasoningProfile to_dict / properties
- ScorerStats to_dict
- Recording evaluations
- Profile updates
- Queries (profiles, best reasoner, recent, by domain)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.reasoning.reasoning_quality_scorer import (
    MAX_EVALUATIONS,
    AgentReasoningProfile,
    ReasoningEvaluation,
    ReasoningQualityScorer,
    ScorerStats,
    get_quality_scorer,
    reset_quality_scorer,
)

# =============================================================================
# ReasoningEvaluation Tests
# =============================================================================


class TestReasoningEvaluation:
    """Test ReasoningEvaluation dataclass."""

    def test_composite_score(self):
        e = ReasoningEvaluation(depth_score=0.9, coherence_score=0.8, completeness_score=0.7)
        assert abs(e.composite_score - 0.8) < 0.01  # (0.9+0.8+0.7)/3 = 0.8

    def test_confidence_calibration(self):
        e = ReasoningEvaluation(confidence=0.8, actual_outcome_quality=0.7)
        # 1.0 - abs(0.8 - 0.7) = 0.9
        assert abs(e.confidence_calibration - 0.9) < 0.01

    def test_confidence_perfect(self):
        e = ReasoningEvaluation(confidence=0.7, actual_outcome_quality=0.7)
        assert abs(e.confidence_calibration - 1.0) < 0.01

    def test_to_dict(self):
        e = ReasoningEvaluation(
            evaluation_id="re_000001", agent_id="claude", depth_score=0.8, coherence_score=0.7, completeness_score=0.9
        )
        d = e.to_dict()
        assert "composite_score" in d
        assert "confidence_calibration" in d


# =============================================================================
# AgentReasoningProfile Tests
# =============================================================================


class TestAgentReasoningProfile:
    """Test AgentReasoningProfile dataclass."""

    def test_avg_depth(self):
        p = AgentReasoningProfile(agent_id="claude", total_evaluations=4, total_depth=3.2)
        assert abs(p.avg_depth - 0.8) < 0.01

    def test_avg_composite(self):
        p = AgentReasoningProfile(
            agent_id="claude", total_evaluations=4, total_depth=3.2, total_coherence=2.8, total_completeness=3.6
        )
        # avg_depth=0.8, avg_coherence=0.7, avg_completeness=0.9 -> composite=0.8
        assert abs(p.avg_composite - 0.8) < 0.01

    def test_zero_evaluations(self):
        p = AgentReasoningProfile(agent_id="claude")
        assert p.avg_depth == 0.0
        assert p.avg_composite == 0.0

    def test_to_dict(self):
        p = AgentReasoningProfile(agent_id="claude", total_evaluations=5)
        d = p.to_dict()
        assert "avg_depth" in d
        assert "avg_composite" in d


# =============================================================================
# ScorerStats Tests
# =============================================================================


class TestScorerStats:
    """Test ScorerStats dataclass."""

    def test_to_dict(self):
        s = ScorerStats(total_evaluations=20, unique_agents=3)
        d = s.to_dict()
        assert d["total_evaluations"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test evaluation recording."""

    def test_record_basic(self):
        s = ReasoningQualityScorer()
        e = s.record_evaluation("claude", depth_score=0.8, coherence_score=0.7)
        assert e.evaluation_id == "re_000000"
        assert s.evaluation_count == 1

    def test_profile_updates(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8, coherence_score=0.7, completeness_score=0.9)
        s.record_evaluation("claude", depth_score=0.6, coherence_score=0.5, completeness_score=0.7)
        p = s.get_agent_profile("claude")
        assert p is not None
        assert p.total_evaluations == 2

    def test_multiple_agents(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8)
        s.record_evaluation("gemini", depth_score=0.7)
        assert len(s.get_all_profiles()) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        s = ReasoningQualityScorer()
        assert s.get_agent_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("weak", depth_score=0.3, coherence_score=0.3, completeness_score=0.3)
        s.record_evaluation("strong", depth_score=0.9, coherence_score=0.9, completeness_score=0.9)
        profiles = s.get_all_profiles()
        assert profiles[0].agent_id == "strong"

    def test_best_reasoner(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.9, coherence_score=0.9, completeness_score=0.9)
        s.record_evaluation("gemini", depth_score=0.6, coherence_score=0.6, completeness_score=0.6)
        assert s.get_best_reasoner() == "claude"

    def test_best_reasoner_empty(self):
        s = ReasoningQualityScorer()
        assert s.get_best_reasoner() is None

    def test_recent_evaluations(self):
        s = ReasoningQualityScorer()
        for _i in range(5):
            s.record_evaluation("claude", depth_score=0.5)
        recent = s.get_recent_evaluations(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8)
        s.record_evaluation("gemini", depth_score=0.7)
        s.record_evaluation("claude", depth_score=0.9)
        recent = s.get_recent_evaluations(agent_id="claude")
        assert len(recent) == 2

    def test_by_domain(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", task_domain="coding", depth_score=0.8)
        s.record_evaluation("claude", task_domain="security", depth_score=0.7)
        s.record_evaluation("claude", task_domain="coding", depth_score=0.9)
        results = s.get_evaluations_by_domain("coding")
        assert len(results) == 2

    def test_list_agents(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("gemini", depth_score=0.7)
        s.record_evaluation("claude", depth_score=0.8)
        assert s.list_agents() == ["claude", "gemini"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded evaluation history."""

    def test_eviction(self):
        s = ReasoningQualityScorer(max_evaluations=5)
        for _i in range(10):
            s.record_evaluation("claude", depth_score=0.5)
        assert s.evaluation_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test scorer statistics."""

    def test_initial_stats(self):
        s = ReasoningQualityScorer()
        stats = s.get_stats()
        assert stats.total_evaluations == 0

    def test_stats_after_recording(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8, coherence_score=0.7, completeness_score=0.9)
        s.record_evaluation("gemini", depth_score=0.6, coherence_score=0.5, completeness_score=0.7)
        stats = s.get_stats()
        assert stats.total_evaluations == 2
        assert stats.unique_agents == 2

    def test_stats_to_dict(self):
        s = ReasoningQualityScorer()
        d = s.get_stats().to_dict()
        assert "total_evaluations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8)
        assert s.evaluation_count == 1

    def test_clear(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8)
        s.clear()
        assert s.evaluation_count == 0
        assert s.get_agent_profile("claude") is None

    def test_to_dict(self):
        s = ReasoningQualityScorer()
        s.record_evaluation("claude", depth_score=0.8)
        d = s.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global quality scorer."""

    def test_get(self):
        reset_quality_scorer()
        s = get_quality_scorer()
        assert isinstance(s, ReasoningQualityScorer)

    def test_singleton(self):
        reset_quality_scorer()
        s1 = get_quality_scorer()
        s2 = get_quality_scorer()
        assert s1 is s2

    def test_reset(self):
        reset_quality_scorer()
        s1 = get_quality_scorer()
        reset_quality_scorer()
        s2 = get_quality_scorer()
        assert s1 is not s2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_reasoning_package(self):
        from core.intelligence.reasoning import (
            AgentReasoningProfile,
            ReasoningEvaluation,
            ReasoningQualityScorer,
            ScorerStats,
            get_quality_scorer,
            reset_quality_scorer,
        )

        assert all(
            [
                ReasoningQualityScorer,
                ReasoningEvaluation,
                AgentReasoningProfile,
                ScorerStats,
                get_quality_scorer,
                reset_quality_scorer,
            ]
        )

    def test_constants(self):
        assert MAX_EVALUATIONS == 50000
