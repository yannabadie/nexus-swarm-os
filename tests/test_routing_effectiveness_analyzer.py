"""
Tests for V12.4 Routing Effectiveness Analyzer.

Validates:
- RoutingDecisionRecord to_dict
- PolicyMetrics to_dict / properties
- AnalyzerStats to_dict
- Recording decisions
- Policy metrics updates
- Queries (all metrics, best policy, by model, recent, list policies)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.routing.routing_effectiveness_analyzer import (
    MAX_DECISIONS,
    AnalyzerStats,
    PolicyMetrics,
    RoutingDecisionRecord,
    RoutingEffectivenessAnalyzer,
    get_routing_analyzer,
    reset_routing_analyzer,
)

# =============================================================================
# RoutingDecisionRecord Tests
# =============================================================================


class TestRoutingDecisionRecord:
    """Test RoutingDecisionRecord dataclass."""

    def test_to_dict(self):
        r = RoutingDecisionRecord(
            decision_id="rd_000000", policy="COST_OPTIMIZED", selected_model="claude-sonnet", outcome_quality=0.85
        )
        d = r.to_dict()
        assert d["policy"] == "COST_OPTIMIZED"
        assert d["selected_model"] == "claude-sonnet"


# =============================================================================
# PolicyMetrics Tests
# =============================================================================


class TestPolicyMetrics:
    """Test PolicyMetrics dataclass."""

    def test_optimality_rate(self):
        m = PolicyMetrics(policy="BALANCED", total_decisions=10, optimal_decisions=8)
        assert abs(m.optimality_rate - 0.8) < 0.01

    def test_optimality_rate_zero(self):
        m = PolicyMetrics(policy="BALANCED")
        assert m.optimality_rate == 0.0

    def test_avg_quality(self):
        m = PolicyMetrics(policy="BALANCED", total_decisions=4, total_quality=3.2)
        assert abs(m.avg_quality - 0.8) < 0.01

    def test_avg_quality_zero(self):
        m = PolicyMetrics(policy="BALANCED")
        assert m.avg_quality == 0.0

    def test_avg_latency(self):
        m = PolicyMetrics(policy="BALANCED", total_decisions=4, total_latency_ms=4000.0)
        assert abs(m.avg_latency_ms - 1000.0) < 0.01

    def test_avg_latency_zero(self):
        m = PolicyMetrics(policy="BALANCED")
        assert m.avg_latency_ms == 0.0

    def test_to_dict(self):
        m = PolicyMetrics(policy="BALANCED", total_decisions=5)
        d = m.to_dict()
        assert "optimality_rate" in d
        assert "avg_quality" in d
        assert "avg_latency_ms" in d


# =============================================================================
# AnalyzerStats Tests
# =============================================================================


class TestAnalyzerStats:
    """Test AnalyzerStats dataclass."""

    def test_to_dict(self):
        s = AnalyzerStats(total_decisions=20, unique_policies=3)
        d = s.to_dict()
        assert d["total_decisions"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test decision recording."""

    def test_record_basic(self):
        a = RoutingEffectivenessAnalyzer()
        r = a.record_decision("COST_OPTIMIZED", selected_model="claude-sonnet")
        assert r.decision_id == "rd_000000"
        assert a.decision_count == 1

    def test_policy_metrics_update(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("BALANCED", outcome_quality=0.8, was_optimal=True)
        a.record_decision("BALANCED", outcome_quality=0.6, was_optimal=False)
        a.record_decision("BALANCED", outcome_quality=0.9, was_optimal=True)
        m = a.get_policy_metrics("BALANCED")
        assert m is not None
        assert m.total_decisions == 3
        assert m.optimal_decisions == 2

    def test_multiple_policies(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("COST_OPTIMIZED")
        a.record_decision("QUALITY_FIRST")
        a.record_decision("BALANCED")
        assert len(a.get_all_metrics()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_policy_not_found(self):
        a = RoutingEffectivenessAnalyzer()
        assert a.get_policy_metrics("missing") is None

    def test_get_all_metrics_sorted(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("COST_OPTIMIZED")
        a.record_decision("BALANCED")
        a.record_decision("BALANCED")
        metrics = a.get_all_metrics()
        assert metrics[0].policy == "BALANCED"  # 2 > 1

    def test_best_policy(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("COST_OPTIMIZED", was_optimal=True)
        a.record_decision("QUALITY_FIRST", was_optimal=False)
        assert a.get_best_policy() == "COST_OPTIMIZED"

    def test_best_policy_empty(self):
        a = RoutingEffectivenessAnalyzer()
        assert a.get_best_policy() is None

    def test_decisions_by_model(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("BALANCED", selected_model="claude-opus")
        a.record_decision("BALANCED", selected_model="claude-sonnet")
        a.record_decision("BALANCED", selected_model="claude-opus")
        results = a.get_decisions_by_model("claude-opus")
        assert len(results) == 2

    def test_recent_decisions(self):
        a = RoutingEffectivenessAnalyzer()
        for _i in range(5):
            a.record_decision("BALANCED")
        recent = a.get_recent_decisions(limit=3)
        assert len(recent) == 3

    def test_list_policies(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("QUALITY_FIRST")
        a.record_decision("BALANCED")
        assert a.list_policies() == ["BALANCED", "QUALITY_FIRST"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded decision history."""

    def test_eviction(self):
        a = RoutingEffectivenessAnalyzer(max_decisions=5)
        for _i in range(10):
            a.record_decision("BALANCED")
        assert a.decision_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analyzer statistics."""

    def test_initial_stats(self):
        a = RoutingEffectivenessAnalyzer()
        stats = a.get_stats()
        assert stats.total_decisions == 0

    def test_stats_after_recording(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("COST_OPTIMIZED", selected_model="opus", was_optimal=True)
        a.record_decision("QUALITY_FIRST", selected_model="sonnet", was_optimal=False)
        stats = a.get_stats()
        assert stats.total_decisions == 2
        assert stats.unique_policies == 2
        assert stats.unique_models == 2

    def test_stats_to_dict(self):
        a = RoutingEffectivenessAnalyzer()
        d = a.get_stats().to_dict()
        assert "total_decisions" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("BALANCED")
        assert a.decision_count == 1

    def test_clear(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("BALANCED")
        a.clear()
        assert a.decision_count == 0
        assert a.get_policy_metrics("BALANCED") is None

    def test_to_dict(self):
        a = RoutingEffectivenessAnalyzer()
        a.record_decision("BALANCED")
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global routing analyzer."""

    def test_get(self):
        reset_routing_analyzer()
        a = get_routing_analyzer()
        assert isinstance(a, RoutingEffectivenessAnalyzer)

    def test_singleton(self):
        reset_routing_analyzer()
        a1 = get_routing_analyzer()
        a2 = get_routing_analyzer()
        assert a1 is a2

    def test_reset(self):
        reset_routing_analyzer()
        a1 = get_routing_analyzer()
        reset_routing_analyzer()
        a2 = get_routing_analyzer()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_routing_package(self):
        from core.execution_pkg.routing import (
            PolicyMetrics,
            RoutingAnalyzerStats,
            RoutingDecisionRecord,
            RoutingEffectivenessAnalyzer,
            get_routing_analyzer,
            reset_routing_analyzer,
        )

        assert all(
            [
                RoutingEffectivenessAnalyzer,
                RoutingDecisionRecord,
                PolicyMetrics,
                RoutingAnalyzerStats,
                get_routing_analyzer,
                reset_routing_analyzer,
            ]
        )

    def test_constants(self):
        assert MAX_DECISIONS == 50000
