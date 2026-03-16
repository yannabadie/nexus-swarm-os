"""
Tests for V12.4 Memory Cache Manager.

Validates:
- CacheEntry properties and to_dict
- CacheStats to_dict
- Core operations (put, get, has, delete)
- LRU eviction
- TTL expiration
- get_or_compute
- Namespace operations (delete_by_prefix, list_keys)
- Cleanup
- Statistics
- State management
- Global singleton
- Module exports
"""

import time

from core.memory_pkg.memory.cache_manager import (
    DEFAULT_MAX_SIZE,
    DEFAULT_TTL,
    CacheEntry,
    CacheManager,
    CacheStats,
    get_cache_manager,
    reset_cache_manager,
)

# =============================================================================
# CacheEntry Tests
# =============================================================================


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_not_expired(self):
        e = CacheEntry(key="k", value="v", created_at=time.monotonic(), expires_at=time.monotonic() + 100)
        assert e.is_expired is False
        assert e.ttl_remaining > 99

    def test_expired(self):
        e = CacheEntry(key="k", value="v", created_at=time.monotonic(), expires_at=time.monotonic() - 1)
        assert e.is_expired is True
        assert e.ttl_remaining == 0.0

    def test_to_dict(self):
        e = CacheEntry(key="k", value="v", created_at=time.monotonic(), expires_at=time.monotonic() + 100, hit_count=5)
        d = e.to_dict()
        assert d["key"] == "k"
        assert d["hit_count"] == 5


# =============================================================================
# CacheStats Tests
# =============================================================================


class TestCacheStats:
    """Test CacheStats dataclass."""

    def test_to_dict(self):
        s = CacheStats(size=10, max_size=100, hits=80, misses=20, evictions=5, expirations=2, hit_rate=0.8)
        d = s.to_dict()
        assert d["hit_rate"] == 0.8
        assert d["evictions"] == 5


# =============================================================================
# Core Operations Tests
# =============================================================================


class TestCoreOperations:
    """Test put, get, has, delete."""

    def test_put_and_get(self):
        c = CacheManager()
        c.put("key1", "value1")
        assert c.get("key1") == "value1"

    def test_get_miss(self):
        c = CacheManager()
        assert c.get("missing") is None

    def test_has(self):
        c = CacheManager()
        c.put("key1", "value1")
        assert c.has("key1") is True
        assert c.has("missing") is False

    def test_delete(self):
        c = CacheManager()
        c.put("key1", "value1")
        assert c.delete("key1") is True
        assert c.get("key1") is None

    def test_delete_not_found(self):
        c = CacheManager()
        assert c.delete("missing") is False

    def test_put_overwrites(self):
        c = CacheManager()
        c.put("key1", "old")
        c.put("key1", "new")
        assert c.get("key1") == "new"
        assert c.size == 1

    def test_get_entry(self):
        c = CacheManager()
        c.put("key1", "value1")
        entry = c.get_entry("key1")
        assert entry is not None
        assert entry.key == "key1"

    def test_get_entry_not_found(self):
        c = CacheManager()
        assert c.get_entry("missing") is None


# =============================================================================
# LRU Eviction Tests
# =============================================================================


class TestLRUEviction:
    """Test LRU eviction behavior."""

    def test_evict_on_full(self):
        c = CacheManager(max_size=3)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
        c.put("d", 4)  # Should evict "a"
        assert c.get("a") is None
        assert c.get("d") == 4
        assert c.size == 3

    def test_lru_order(self):
        c = CacheManager(max_size=3)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
        c.get("a")  # Access "a" -> now most recent
        c.put("d", 4)  # Should evict "b" (least recently used)
        assert c.get("a") is not None
        assert c.get("b") is None

    def test_eviction_count(self):
        c = CacheManager(max_size=2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)  # Evicts "a"
        assert c.get_stats().evictions == 1


# =============================================================================
# TTL Expiration Tests
# =============================================================================


class TestTTLExpiration:
    """Test TTL-based expiration."""

    def test_expired_on_get(self):
        c = CacheManager()
        c.put("key1", "value1", ttl=0.0)  # Immediately expires
        assert c.get("key1") is None

    def test_not_expired(self):
        c = CacheManager()
        c.put("key1", "value1", ttl=100.0)
        assert c.get("key1") == "value1"

    def test_has_checks_expiry(self):
        c = CacheManager()
        c.put("key1", "value1", ttl=0.0)
        assert c.has("key1") is False

    def test_custom_ttl(self):
        c = CacheManager(default_ttl=0.0)
        c.put("key1", "value1")  # Uses default TTL of 0.0
        assert c.get("key1") is None

    def test_per_entry_ttl_overrides_default(self):
        c = CacheManager(default_ttl=0.0)
        c.put("key1", "value1", ttl=100.0)
        assert c.get("key1") == "value1"


# =============================================================================
# get_or_compute Tests
# =============================================================================


class TestGetOrCompute:
    """Test get_or_compute pattern."""

    def test_computes_on_miss(self):
        c = CacheManager()
        result = c.get_or_compute("key1", lambda: "computed")
        assert result == "computed"

    def test_returns_cached_on_hit(self):
        c = CacheManager()
        c.put("key1", "cached")
        call_count = [0]

        def compute():
            call_count[0] += 1
            return "computed"

        result = c.get_or_compute("key1", compute)
        assert result == "cached"
        assert call_count[0] == 0

    def test_stores_computed_value(self):
        c = CacheManager()
        c.get_or_compute("key1", lambda: "stored")
        assert c.get("key1") == "stored"


# =============================================================================
# Namespace Tests
# =============================================================================


class TestNamespace:
    """Test namespace operations."""

    def test_delete_by_prefix(self):
        c = CacheManager()
        c.put("ns1:a", 1)
        c.put("ns1:b", 2)
        c.put("ns2:a", 3)
        count = c.delete_by_prefix("ns1:")
        assert count == 2
        assert c.size == 1

    def test_list_keys(self):
        c = CacheManager()
        c.put("ns1:a", 1)
        c.put("ns1:b", 2)
        c.put("ns2:a", 3)
        keys = c.list_keys()
        assert len(keys) == 3

    def test_list_keys_with_prefix(self):
        c = CacheManager()
        c.put("ns1:a", 1)
        c.put("ns1:b", 2)
        c.put("ns2:a", 3)
        keys = c.list_keys(prefix="ns1:")
        assert len(keys) == 2

    def test_list_keys_excludes_expired(self):
        c = CacheManager()
        c.put("fresh", 1, ttl=100.0)
        c.put("stale", 2, ttl=0.0)
        keys = c.list_keys()
        assert len(keys) == 1


# =============================================================================
# Cleanup Tests
# =============================================================================


class TestCleanup:
    """Test expired entry cleanup."""

    def test_cleanup_expired(self):
        c = CacheManager()
        c.put("fresh", 1, ttl=100.0)
        c.put("stale", 2, ttl=0.0)
        count = c.cleanup_expired()
        assert count == 1
        assert c.size == 1

    def test_cleanup_none_expired(self):
        c = CacheManager()
        c.put("fresh", 1, ttl=100.0)
        assert c.cleanup_expired() == 0


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test cache statistics."""

    def test_initial_stats(self):
        c = CacheManager()
        stats = c.get_stats()
        assert stats.size == 0
        assert stats.hits == 0
        assert stats.misses == 0

    def test_stats_hit_miss(self):
        c = CacheManager()
        c.put("key1", "value1")
        c.get("key1")  # Hit
        c.get("missing")  # Miss
        stats = c.get_stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == 0.5

    def test_stats_to_dict(self):
        c = CacheManager()
        d = c.get_stats().to_dict()
        assert "hits" in d
        assert "hit_rate" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        c = CacheManager()
        c.put("a", 1)
        c.put("b", 2)
        assert c.size == 2

    def test_max_size(self):
        c = CacheManager(max_size=50)
        assert c.max_size == 50

    def test_clear(self):
        c = CacheManager()
        c.put("a", 1)
        c.get("a")
        c.clear()
        assert c.size == 0
        assert c.get_stats().hits == 0

    def test_to_dict(self):
        c = CacheManager()
        c.put("a", 1)
        d = c.to_dict()
        assert d["size"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global cache manager."""

    def test_get(self):
        reset_cache_manager()
        c = get_cache_manager()
        assert isinstance(c, CacheManager)

    def test_singleton(self):
        reset_cache_manager()
        c1 = get_cache_manager()
        c2 = get_cache_manager()
        assert c1 is c2

    def test_reset(self):
        reset_cache_manager()
        c1 = get_cache_manager()
        reset_cache_manager()
        c2 = get_cache_manager()
        assert c1 is not c2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_memory_package(self):
        from core.memory_pkg.memory import (
            CacheEntry,
            CacheManager,
            CacheStats,
            get_cache_manager,
            reset_cache_manager,
        )

        assert all(
            [
                CacheManager,
                CacheEntry,
                CacheStats,
                get_cache_manager,
                reset_cache_manager,
            ]
        )

    def test_from_module(self):
        assert DEFAULT_MAX_SIZE == 1000
        assert DEFAULT_TTL == 300.0
