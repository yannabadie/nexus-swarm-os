"""
Tests for V12.4 Routing Decision Cache.

Validates:
- CachedDecision properties and to_dict
- DecisionOutcome to_dict
- DecisionCacheStats to_dict
- Core operations (record, get, has, delete)
- LRU eviction
- TTL expiration
- Learning / feedback loop
- Best model recommendation
- Maintenance (cleanup, delete_by_model)
- Statistics
- State management
- Global singleton
- Module exports
"""

import time

from core.execution_pkg.routing.decision_cache import (
    DEFAULT_MAX_SIZE,
    DEFAULT_TTL,
    CachedDecision,
    DecisionCacheStats,
    DecisionOutcome,
    RoutingDecisionCache,
    get_decision_cache,
    reset_decision_cache,
)

# =============================================================================
# CachedDecision Tests
# =============================================================================


class TestCachedDecision:
    """Test CachedDecision dataclass."""

    def test_not_expired(self):
        d = CachedDecision(
            task_fingerprint="fp1",
            model_id="sonnet",
            expires_at=time.monotonic() + 100,
        )
        assert d.is_expired is False

    def test_expired(self):
        d = CachedDecision(
            task_fingerprint="fp1",
            model_id="sonnet",
            expires_at=time.monotonic() - 1,
        )
        assert d.is_expired is True

    def test_success_rate_zero(self):
        d = CachedDecision(task_fingerprint="fp1", model_id="sonnet")
        assert d.success_rate == 0.0

    def test_success_rate(self):
        d = CachedDecision(
            task_fingerprint="fp1",
            model_id="sonnet",
            total_outcomes=10,
            success_count=8,
        )
        assert d.success_rate == 0.8

    def test_to_dict(self):
        d = CachedDecision(task_fingerprint="fp1", model_id="opus", cost=0.05)
        result = d.to_dict()
        assert result["model_id"] == "opus"
        assert result["cost"] == 0.05


# =============================================================================
# DecisionOutcome Tests
# =============================================================================


class TestDecisionOutcome:
    """Test DecisionOutcome dataclass."""

    def test_to_dict(self):
        o = DecisionOutcome(task_fingerprint="fp1", success=True, quality=0.9, latency=1.5)
        d = o.to_dict()
        assert d["success"] is True
        assert d["quality"] == 0.9


# =============================================================================
# DecisionCacheStats Tests
# =============================================================================


class TestDecisionCacheStats:
    """Test DecisionCacheStats dataclass."""

    def test_to_dict(self):
        s = DecisionCacheStats(
            size=10,
            max_size=500,
            hits=80,
            misses=20,
            hit_rate=0.8,
            total_decisions=100,
            total_outcomes=50,
            evictions=5,
        )
        d = s.to_dict()
        assert d["hit_rate"] == 0.8
        assert d["evictions"] == 5


# =============================================================================
# Core Operations Tests
# =============================================================================


class TestCoreOperations:
    """Test record, get, has, delete."""

    def test_record_and_get(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        decision = c.get_decision("fp1")
        assert decision is not None
        assert decision.model_id == "sonnet"

    def test_get_miss(self):
        c = RoutingDecisionCache()
        assert c.get_decision("missing") is None

    def test_has(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        assert c.has_decision("fp1") is True
        assert c.has_decision("missing") is False

    def test_delete(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        assert c.delete_decision("fp1") is True
        assert c.get_decision("fp1") is None

    def test_delete_not_found(self):
        c = RoutingDecisionCache()
        assert c.delete_decision("missing") is False

    def test_record_updates_existing(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.record_decision("fp1", model_id="opus")
        decision = c.get_decision("fp1")
        assert decision.model_id == "opus"
        assert c.size == 1

    def test_record_with_cost(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="opus", cost=0.10)
        decision = c.get_decision("fp1")
        assert decision.cost == 0.10

    def test_get_increments_hit_count(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.get_decision("fp1")
        c.get_decision("fp1")
        decision = c.get_decision("fp1")
        assert decision.hit_count == 3


# =============================================================================
# LRU Eviction Tests
# =============================================================================


class TestLRUEviction:
    """Test LRU eviction behavior."""

    def test_evict_on_full(self):
        c = RoutingDecisionCache(max_size=3)
        c.record_decision("a", model_id="m1")
        c.record_decision("b", model_id="m2")
        c.record_decision("c", model_id="m3")
        c.record_decision("d", model_id="m4")  # Evicts "a"
        assert c.get_decision("a") is None
        assert c.get_decision("d") is not None
        assert c.size == 3

    def test_lru_order(self):
        c = RoutingDecisionCache(max_size=3)
        c.record_decision("a", model_id="m1")
        c.record_decision("b", model_id="m2")
        c.record_decision("c", model_id="m3")
        c.get_decision("a")  # Touch "a" -> now most recent
        c.record_decision("d", model_id="m4")  # Evicts "b"
        assert c.get_decision("a") is not None
        assert c.get_decision("b") is None

    def test_eviction_count(self):
        c = RoutingDecisionCache(max_size=2)
        c.record_decision("a", model_id="m1")
        c.record_decision("b", model_id="m2")
        c.record_decision("c", model_id="m3")
        assert c.get_stats().evictions == 1


# =============================================================================
# TTL Expiration Tests
# =============================================================================


class TestTTLExpiration:
    """Test TTL-based expiration."""

    def test_expired_on_get(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet", ttl=0.0)
        assert c.get_decision("fp1") is None

    def test_not_expired(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet", ttl=100.0)
        assert c.get_decision("fp1") is not None

    def test_has_checks_expiry(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet", ttl=0.0)
        assert c.has_decision("fp1") is False

    def test_custom_default_ttl(self):
        c = RoutingDecisionCache(default_ttl=0.0)
        c.record_decision("fp1", model_id="sonnet")
        assert c.get_decision("fp1") is None

    def test_per_decision_ttl_overrides_default(self):
        c = RoutingDecisionCache(default_ttl=0.0)
        c.record_decision("fp1", model_id="sonnet", ttl=100.0)
        assert c.get_decision("fp1") is not None


# =============================================================================
# Learning / Feedback Tests
# =============================================================================


class TestLearning:
    """Test outcome recording and learning."""

    def test_record_outcome_success(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        assert c.record_outcome("fp1", success=True, quality=0.9, latency=2.0) is True
        decision = c.get_decision("fp1")
        assert decision.total_outcomes == 1
        assert decision.success_count == 1
        assert decision.avg_quality == 0.9

    def test_record_outcome_not_found(self):
        c = RoutingDecisionCache()
        assert c.record_outcome("missing", success=True) is False

    def test_ema_learning(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.record_outcome("fp1", success=True, quality=1.0, latency=1.0)
        c.record_outcome("fp1", success=True, quality=0.0, latency=5.0)
        decision = c.get_decision("fp1")
        # EMA: (1-0.15)*1.0 + 0.15*0.0 = 0.85
        assert abs(decision.avg_quality - 0.85) < 0.01
        # EMA: (1-0.15)*1.0 + 0.15*5.0 = 0.85 + 0.75 = 1.60
        assert abs(decision.avg_latency - 1.60) < 0.01

    def test_success_rate_updates(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.record_outcome("fp1", success=True)
        c.record_outcome("fp1", success=False)
        decision = c.get_decision("fp1")
        assert decision.success_rate == 0.5

    def test_quality_clamped(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.record_outcome("fp1", success=True, quality=5.0)  # Clamped to 1.0
        decision = c.get_decision("fp1")
        assert decision.avg_quality == 1.0


# =============================================================================
# Best Model Tests
# =============================================================================


class TestBestModel:
    """Test best model recommendation."""

    def test_returns_model(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="opus")
        assert c.get_best_model("fp1") == "opus"

    def test_returns_none_on_miss(self):
        c = RoutingDecisionCache()
        assert c.get_best_model("missing") is None

    def test_returns_none_low_success_rate(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        for _ in range(3):
            c.record_outcome("fp1", success=False)
        assert c.get_best_model("fp1") is None

    def test_returns_model_high_success_rate(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="opus")
        for _ in range(3):
            c.record_outcome("fp1", success=True, quality=0.9)
        assert c.get_best_model("fp1") == "opus"


# =============================================================================
# Maintenance Tests
# =============================================================================


class TestMaintenance:
    """Test maintenance operations."""

    def test_cleanup_expired(self):
        c = RoutingDecisionCache()
        c.record_decision("fresh", model_id="m1", ttl=100.0)
        c.record_decision("stale", model_id="m2", ttl=0.0)
        count = c.cleanup_expired()
        assert count == 1
        assert c.size == 1

    def test_delete_by_model(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.record_decision("fp2", model_id="opus")
        c.record_decision("fp3", model_id="sonnet")
        count = c.delete_by_model("sonnet")
        assert count == 2
        assert c.size == 1

    def test_list_fingerprints(self):
        c = RoutingDecisionCache()
        c.record_decision("coding:python", model_id="m1")
        c.record_decision("coding:rust", model_id="m2")
        c.record_decision("research:web", model_id="m3")
        fps = c.list_fingerprints(prefix="coding:")
        assert len(fps) == 2

    def test_list_fingerprints_excludes_expired(self):
        c = RoutingDecisionCache()
        c.record_decision("fresh", model_id="m1", ttl=100.0)
        c.record_decision("stale", model_id="m2", ttl=0.0)
        fps = c.list_fingerprints()
        assert len(fps) == 1


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test cache statistics."""

    def test_initial_stats(self):
        c = RoutingDecisionCache()
        stats = c.get_stats()
        assert stats.size == 0
        assert stats.hits == 0
        assert stats.misses == 0

    def test_stats_hit_miss(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.get_decision("fp1")  # Hit
        c.get_decision("missing")  # Miss
        stats = c.get_stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == 0.5

    def test_stats_decisions_and_outcomes(self):
        c = RoutingDecisionCache()
        c.record_decision("fp1", model_id="sonnet")
        c.record_outcome("fp1", success=True)
        stats = c.get_stats()
        assert stats.total_decisions == 1
        assert stats.total_outcomes == 1

    def test_stats_to_dict(self):
        c = RoutingDecisionCache()
        d = c.get_stats().to_dict()
        assert "hits" in d
        assert "hit_rate" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        c = RoutingDecisionCache()
        c.record_decision("a", model_id="m1")
        c.record_decision("b", model_id="m2")
        assert c.size == 2

    def test_max_size(self):
        c = RoutingDecisionCache(max_size=50)
        assert c.max_size == 50

    def test_clear(self):
        c = RoutingDecisionCache()
        c.record_decision("a", model_id="m1")
        c.get_decision("a")
        c.clear()
        assert c.size == 0
        assert c.get_stats().hits == 0

    def test_to_dict(self):
        c = RoutingDecisionCache()
        c.record_decision("a", model_id="m1")
        d = c.to_dict()
        assert d["size"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global decision cache."""

    def test_get(self):
        reset_decision_cache()
        c = get_decision_cache()
        assert isinstance(c, RoutingDecisionCache)

    def test_singleton(self):
        reset_decision_cache()
        c1 = get_decision_cache()
        c2 = get_decision_cache()
        assert c1 is c2

    def test_reset(self):
        reset_decision_cache()
        c1 = get_decision_cache()
        reset_decision_cache()
        c2 = get_decision_cache()
        assert c1 is not c2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_routing_package(self):
        from core.execution_pkg.routing import (
            CachedDecision,
            DecisionCacheStats,
            DecisionOutcome,
            RoutingDecisionCache,
            get_decision_cache,
            reset_decision_cache,
        )

        assert all(
            [
                RoutingDecisionCache,
                CachedDecision,
                DecisionOutcome,
                DecisionCacheStats,
                get_decision_cache,
                reset_decision_cache,
            ]
        )

    def test_constants(self):
        assert DEFAULT_MAX_SIZE == 500
        assert DEFAULT_TTL == 3600.0
