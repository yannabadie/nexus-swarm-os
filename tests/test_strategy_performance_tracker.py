"""
Tests for V12.4 Evolution Strategy Performance Tracker.

Validates:
- StrategyApplication to_dict / properties
- StrategyMetrics to_dict / properties
- StrategyRecommendation to_dict
- TrackerStats to_dict
- Recording applications (metric updates)
- Strategy metrics queries
- Recommendations (confidence, min_trials)
- Domain ranking
- Listing strategies / domains
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.evolution.strategy_performance_tracker import (
    MAX_APPLICATIONS,
    MIN_TRIALS_FOR_RECOMMENDATION,
    StrategyApplication,
    StrategyMetrics,
    StrategyPerformanceTracker,
    StrategyRecommendation,
    TrackerStats,
    get_strategy_tracker,
    reset_strategy_tracker,
)

# =============================================================================
# StrategyApplication Tests
# =============================================================================


class TestStrategyApplication:
    """Test StrategyApplication dataclass."""

    def test_fitness_delta(self):
        a = StrategyApplication(strategy="code_specialist", domain="python", fitness_before=0.5, fitness_after=0.8)
        assert abs(a.fitness_delta - 0.3) < 0.01

    def test_improvement(self):
        a = StrategyApplication(strategy="code_specialist", domain="python", fitness_before=0.5, fitness_after=0.75)
        assert abs(a.improvement - 0.5) < 0.01  # 50% improvement

    def test_improvement_zero_baseline(self):
        a = StrategyApplication(strategy="s", domain="d", fitness_before=0.0, fitness_after=0.5)
        assert a.improvement == 0.0

    def test_to_dict(self):
        a = StrategyApplication(
            strategy="code_specialist", domain="python", fitness_before=0.5, fitness_after=0.8, success=True
        )
        d = a.to_dict()
        assert d["strategy"] == "code_specialist"
        assert "fitness_delta" in d


# =============================================================================
# StrategyMetrics Tests
# =============================================================================


class TestStrategyMetrics:
    """Test StrategyMetrics dataclass."""

    def test_success_rate(self):
        m = StrategyMetrics(strategy="s", total_applications=10, successes=8)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        m = StrategyMetrics(strategy="s")
        assert m.success_rate == 0.0

    def test_to_dict(self):
        m = StrategyMetrics(strategy="code_specialist", total_applications=5, successes=4)
        d = m.to_dict()
        assert "success_rate" in d


# =============================================================================
# StrategyRecommendation Tests
# =============================================================================


class TestStrategyRecommendation:
    """Test StrategyRecommendation dataclass."""

    def test_to_dict(self):
        r = StrategyRecommendation(
            strategy="code_specialist", confidence=0.8, expected_improvement=0.15, based_on_trials=10
        )
        d = r.to_dict()
        assert d["confidence"] == 0.8


# =============================================================================
# TrackerStats Tests
# =============================================================================


class TestTrackerStats:
    """Test TrackerStats dataclass."""

    def test_to_dict(self):
        s = TrackerStats(total_applications=20, unique_strategies=3, unique_domains=5, overall_success_rate=0.85)
        d = s.to_dict()
        assert d["total_applications"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test application recording."""

    def test_record_basic(self):
        t = StrategyPerformanceTracker()
        a = t.record_application("code_specialist", "python", fitness_before=0.5, fitness_after=0.8, success=True)
        assert a.strategy == "code_specialist"
        assert t.application_count == 1

    def test_metrics_update(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "d", fitness_before=0.5, fitness_after=0.8, success=True)
        t.record_application("s", "d", fitness_before=0.6, fitness_after=0.7, success=True)
        t.record_application("s", "d", fitness_before=0.5, fitness_after=0.4, success=False)
        m = t.get_strategy_metrics("s")
        assert m is not None
        assert m.total_applications == 3
        assert m.successes == 2

    def test_multiple_strategies(self):
        t = StrategyPerformanceTracker()
        t.record_application("code_specialist", "python", success=True)
        t.record_application("reasoning_enhancer", "security", success=True)
        assert t.application_count == 2


# =============================================================================
# Metrics Query Tests
# =============================================================================


class TestMetricsQueries:
    """Test metrics queries."""

    def test_get_metrics_not_found(self):
        t = StrategyPerformanceTracker()
        assert t.get_strategy_metrics("missing") is None

    def test_get_all_metrics(self):
        t = StrategyPerformanceTracker()
        t.record_application("a", "d", success=True)
        t.record_application("b", "d", success=True)
        t.record_application("b", "d", success=False)
        metrics = t.get_all_metrics()
        assert len(metrics) == 2
        # Sorted by success_rate descending
        assert metrics[0].strategy == "a"  # 100% success rate


# =============================================================================
# Recommendation Tests
# =============================================================================


class TestRecommendations:
    """Test strategy recommendations."""

    def test_no_data(self):
        t = StrategyPerformanceTracker()
        assert t.recommend_strategy("python") is None

    def test_insufficient_trials(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "python", fitness_before=0.5, fitness_after=0.8)
        # Only 1 trial, default min is 3
        assert t.recommend_strategy("python") is None

    def test_sufficient_trials(self):
        t = StrategyPerformanceTracker()
        for _ in range(5):
            t.record_application("code_specialist", "python", fitness_before=0.5, fitness_after=0.8)
        rec = t.recommend_strategy("python")
        assert rec is not None
        assert rec.strategy == "code_specialist"

    def test_custom_min_trials(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "python", fitness_before=0.5, fitness_after=0.8)
        rec = t.recommend_strategy("python", min_trials=1)
        assert rec is not None

    def test_picks_best_strategy(self):
        t = StrategyPerformanceTracker()
        for _ in range(5):
            t.record_application("weak", "python", fitness_before=0.5, fitness_after=0.6)
        for _ in range(5):
            t.record_application("strong", "python", fitness_before=0.5, fitness_after=0.9)
        rec = t.recommend_strategy("python")
        assert rec.strategy == "strong"

    def test_confidence(self):
        t = StrategyPerformanceTracker()
        for _ in range(3):
            t.record_application("s", "python", fitness_before=0.5, fitness_after=0.8)
        rec = t.recommend_strategy("python")
        # confidence = 3 / (3 + 3) = 0.5
        assert abs(rec.confidence - 0.5) < 0.01


# =============================================================================
# Domain Ranking Tests
# =============================================================================


class TestDomainRanking:
    """Test domain ranking."""

    def test_ranking(self):
        t = StrategyPerformanceTracker()
        for _ in range(3):
            t.record_application("weak", "python", fitness_before=0.5, fitness_after=0.6)
        for _ in range(3):
            t.record_application("strong", "python", fitness_before=0.5, fitness_after=0.9)
        ranking = t.get_domain_ranking("python")
        assert len(ranking) == 2
        assert ranking[0][0] == "strong"  # highest avg fitness_delta first

    def test_ranking_empty(self):
        t = StrategyPerformanceTracker()
        assert t.get_domain_ranking("missing") == []


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test listing strategies and domains."""

    def test_list_strategies(self):
        t = StrategyPerformanceTracker()
        t.record_application("b", "python")
        t.record_application("a", "security")
        assert t.list_strategies() == ["a", "b"]

    def test_list_domains(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "python")
        t.record_application("s", "security")
        assert t.list_domains() == ["python", "security"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded application history."""

    def test_eviction(self):
        t = StrategyPerformanceTracker(max_applications=5)
        for i in range(10):
            t.record_application(f"s_{i}", "python")
        assert t.application_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = StrategyPerformanceTracker()
        stats = t.get_stats()
        assert stats.total_applications == 0

    def test_stats_after_recording(self):
        t = StrategyPerformanceTracker()
        t.record_application("code_specialist", "python", success=True)
        t.record_application("reasoning_enhancer", "security", success=False)
        stats = t.get_stats()
        assert stats.total_applications == 2
        assert stats.unique_strategies == 2
        assert stats.unique_domains == 2
        assert abs(stats.overall_success_rate - 0.5) < 0.01

    def test_stats_to_dict(self):
        t = StrategyPerformanceTracker()
        d = t.get_stats().to_dict()
        assert "total_applications" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_application_count(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "d")
        t.record_application("s", "d")
        assert t.application_count == 2

    def test_clear(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "d")
        t.clear()
        assert t.application_count == 0
        assert t.get_strategy_metrics("s") is None

    def test_to_dict(self):
        t = StrategyPerformanceTracker()
        t.record_application("s", "d")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global strategy tracker."""

    def test_get(self):
        reset_strategy_tracker()
        t = get_strategy_tracker()
        assert isinstance(t, StrategyPerformanceTracker)

    def test_singleton(self):
        reset_strategy_tracker()
        t1 = get_strategy_tracker()
        t2 = get_strategy_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_strategy_tracker()
        t1 = get_strategy_tracker()
        reset_strategy_tracker()
        t2 = get_strategy_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_evolution_package(self):
        from core.intelligence.evolution import (
            StrategyApplication,
            StrategyMetrics,
            StrategyPerformanceTracker,
            StrategyRecommendation,
            TrackerStats,
            get_strategy_tracker,
            reset_strategy_tracker,
        )

        assert all(
            [
                StrategyPerformanceTracker,
                StrategyApplication,
                StrategyMetrics,
                StrategyRecommendation,
                TrackerStats,
                get_strategy_tracker,
                reset_strategy_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_APPLICATIONS == 50000
        assert MIN_TRIALS_FOR_RECOMMENDATION == 3
