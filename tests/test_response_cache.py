"""
Tests for V12.4 LLM Response Cache.

Validates:
- CacheEntry creation, expiration, serialization
- CacheStats tracking (hits, misses, evictions, hit rate)
- ResponseCache get/put/invalidate/clear
- LRU eviction on size limit
- TTL expiration
- Cache key generation (model + prompt + temperature + system)
- Disabled cache behavior
- Token savings tracking
- Module exports
"""

import time

from core.drivers.response_cache import (
    CacheEntry,
    CacheStats,
    ResponseCache,
)

# =============================================================================
# CacheEntry Tests
# =============================================================================


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_basic_creation(self):
        now = time.monotonic()
        entry = CacheEntry(
            key="abc123",
            model="gemini-3-pro",
            content="Hello!",
            created_at=now,
            expires_at=now + 300,
        )
        assert entry.key == "abc123"
        assert entry.model == "gemini-3-pro"
        assert entry.content == "Hello!"

    def test_not_expired(self):
        now = time.monotonic()
        entry = CacheEntry(
            key="k",
            model="m",
            content="c",
            created_at=now,
            expires_at=now + 1000,
        )
        assert entry.is_expired is False

    def test_expired(self):
        now = time.monotonic()
        entry = CacheEntry(
            key="k",
            model="m",
            content="c",
            created_at=now - 10,
            expires_at=now - 1,
        )
        assert entry.is_expired is True

    def test_age_seconds(self):
        entry = CacheEntry(
            key="k",
            model="m",
            content="c",
            created_at=time.monotonic() - 5.0,
            expires_at=time.monotonic() + 100,
        )
        assert entry.age_seconds >= 4.9

    def test_to_dict(self):
        now = time.monotonic()
        entry = CacheEntry(
            key="abc123def456",
            model="gemini",
            content="Hello",
            created_at=now,
            expires_at=now + 300,
            tokens_saved=100,
            hit_count=3,
        )
        d = entry.to_dict()
        assert d["model"] == "gemini"
        assert d["content_length"] == 5
        assert d["tokens_saved"] == 100
        assert d["hit_count"] == 3


# =============================================================================
# CacheStats Tests
# =============================================================================


class TestCacheStats:
    """Test CacheStats dataclass."""

    def test_defaults(self):
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.hit_rate == 0.0

    def test_hit_rate(self):
        stats = CacheStats(hits=3, misses=7)
        assert stats.hit_rate == 0.3

    def test_total_lookups(self):
        stats = CacheStats(hits=5, misses=10)
        assert stats.total_lookups == 15

    def test_to_dict(self):
        stats = CacheStats(hits=10, misses=5, evictions=2, total_tokens_saved=5000)
        d = stats.to_dict()
        assert d["hits"] == 10
        assert d["misses"] == 5
        assert d["hit_rate"] == 0.6667
        assert d["total_tokens_saved"] == 5000


# =============================================================================
# ResponseCache - Basic Tests
# =============================================================================


class TestBasicCache:
    """Test basic cache operations."""

    def test_put_and_get(self):
        cache = ResponseCache()
        cache.put("gemini", "Hello", "World")
        result = cache.get("gemini", "Hello")
        assert result == "World"

    def test_cache_miss(self):
        cache = ResponseCache()
        result = cache.get("gemini", "Unknown prompt")
        assert result is None

    def test_different_models(self):
        cache = ResponseCache()
        cache.put("gemini", "Hello", "Gemini response")
        cache.put("claude", "Hello", "Claude response")
        assert cache.get("gemini", "Hello") == "Gemini response"
        assert cache.get("claude", "Hello") == "Claude response"

    def test_different_temperatures(self):
        cache = ResponseCache()
        cache.put("gemini", "Hello", "Creative", temperature=0.9)
        cache.put("gemini", "Hello", "Precise", temperature=0.1)
        assert cache.get("gemini", "Hello", temperature=0.9) == "Creative"
        assert cache.get("gemini", "Hello", temperature=0.1) == "Precise"

    def test_different_system_prompts(self):
        cache = ResponseCache()
        cache.put("gemini", "Hello", "Resp A", system_prompt="You are helpful")
        cache.put("gemini", "Hello", "Resp B", system_prompt="You are concise")
        assert cache.get("gemini", "Hello", system_prompt="You are helpful") == "Resp A"
        assert cache.get("gemini", "Hello", system_prompt="You are concise") == "Resp B"

    def test_size_property(self):
        cache = ResponseCache()
        assert cache.size == 0
        cache.put("gemini", "A", "response A")
        assert cache.size == 1
        cache.put("gemini", "B", "response B")
        assert cache.size == 2


# =============================================================================
# ResponseCache - TTL Tests
# =============================================================================


class TestTTL:
    """Test time-to-live expiration."""

    def test_not_expired(self):
        cache = ResponseCache(ttl_seconds=60.0)
        cache.put("gemini", "Hello", "World")
        assert cache.get("gemini", "Hello") == "World"

    def test_expired(self):
        cache = ResponseCache(ttl_seconds=0.01)
        cache.put("gemini", "Hello", "World")
        time.sleep(0.02)
        assert cache.get("gemini", "Hello") is None

    def test_expiration_tracked_in_stats(self):
        cache = ResponseCache(ttl_seconds=0.01)
        cache.put("gemini", "Hello", "World")
        time.sleep(0.02)
        cache.get("gemini", "Hello")
        assert cache.stats.expirations >= 1


# =============================================================================
# ResponseCache - LRU Eviction Tests
# =============================================================================


class TestLRUEviction:
    """Test LRU eviction on size limit."""

    def test_evicts_oldest(self):
        cache = ResponseCache(max_size=3)
        cache.put("m", "A", "resp A")
        cache.put("m", "B", "resp B")
        cache.put("m", "C", "resp C")
        cache.put("m", "D", "resp D")  # Evicts A
        assert cache.get("m", "A") is None
        assert cache.get("m", "D") == "resp D"

    def test_lru_access_prevents_eviction(self):
        cache = ResponseCache(max_size=3)
        cache.put("m", "A", "resp A")
        cache.put("m", "B", "resp B")
        cache.put("m", "C", "resp C")
        # Access A to make it recently used
        cache.get("m", "A")
        # Now add D - should evict B (oldest unused)
        cache.put("m", "D", "resp D")
        assert cache.get("m", "A") == "resp A"  # Still cached
        assert cache.get("m", "B") is None  # Evicted

    def test_eviction_tracked_in_stats(self):
        cache = ResponseCache(max_size=2)
        cache.put("m", "A", "a")
        cache.put("m", "B", "b")
        cache.put("m", "C", "c")  # Evicts A
        assert cache.stats.evictions >= 1


# =============================================================================
# ResponseCache - Stats Tests
# =============================================================================


class TestStats:
    """Test cache statistics."""

    def test_hit_tracking(self):
        cache = ResponseCache()
        cache.put("m", "A", "response")
        cache.get("m", "A")  # Hit
        cache.get("m", "A")  # Hit
        assert cache.stats.hits == 2

    def test_miss_tracking(self):
        cache = ResponseCache()
        cache.get("m", "missing")
        assert cache.stats.misses == 1

    def test_hit_rate(self):
        cache = ResponseCache()
        cache.put("m", "A", "response")
        cache.get("m", "A")  # Hit
        cache.get("m", "B")  # Miss
        assert cache.stats.hit_rate == 0.5

    def test_tokens_saved(self):
        cache = ResponseCache()
        cache.put("m", "A", "response", tokens_used=500)
        cache.get("m", "A")  # Hit: saves 500 tokens
        cache.get("m", "A")  # Hit: saves 500 more
        assert cache.stats.total_tokens_saved == 1000

    def test_reset_stats(self):
        cache = ResponseCache()
        cache.put("m", "A", "response")
        cache.get("m", "A")
        cache.reset_stats()
        assert cache.stats.hits == 0
        assert cache.stats.misses == 0


# =============================================================================
# ResponseCache - Invalidate Tests
# =============================================================================


class TestInvalidate:
    """Test cache entry invalidation."""

    def test_invalidate_existing(self):
        cache = ResponseCache()
        cache.put("m", "A", "response")
        assert cache.invalidate("m", "A") is True
        assert cache.get("m", "A") is None

    def test_invalidate_nonexistent(self):
        cache = ResponseCache()
        assert cache.invalidate("m", "missing") is False

    def test_clear_all(self):
        cache = ResponseCache()
        cache.put("m", "A", "a")
        cache.put("m", "B", "b")
        cache.put("m", "C", "c")
        count = cache.clear()
        assert count == 3
        assert cache.size == 0


# =============================================================================
# ResponseCache - Disabled Tests
# =============================================================================


class TestDisabled:
    """Test disabled cache behavior."""

    def test_disabled_put(self):
        cache = ResponseCache(enabled=False)
        key = cache.put("m", "A", "response")
        assert key == ""

    def test_disabled_get(self):
        cache = ResponseCache(enabled=False)
        assert cache.get("m", "A") is None

    def test_enable_disable(self):
        cache = ResponseCache()
        cache.put("m", "A", "response")
        assert cache.get("m", "A") == "response"
        cache.enabled = False
        assert cache.get("m", "A") is None
        cache.enabled = True
        assert cache.get("m", "A") == "response"


# =============================================================================
# ResponseCache - Key Generation Tests
# =============================================================================


class TestKeyGeneration:
    """Test cache key generation."""

    def test_same_input_same_key(self):
        cache = ResponseCache()
        k1 = cache._make_key("model", "prompt", 0.7, "system")
        k2 = cache._make_key("model", "prompt", 0.7, "system")
        assert k1 == k2

    def test_different_model_different_key(self):
        cache = ResponseCache()
        k1 = cache._make_key("model_a", "prompt", 0.7, "")
        k2 = cache._make_key("model_b", "prompt", 0.7, "")
        assert k1 != k2

    def test_different_temp_different_key(self):
        cache = ResponseCache()
        k1 = cache._make_key("m", "p", 0.1, "")
        k2 = cache._make_key("m", "p", 0.9, "")
        assert k1 != k2

    def test_key_is_sha256(self):
        cache = ResponseCache()
        key = cache._make_key("m", "p", 0.7, "")
        assert len(key) == 64  # SHA-256 hex digest


# =============================================================================
# ResponseCache - State Export Tests
# =============================================================================


class TestStateExport:
    """Test cache state export."""

    def test_to_dict(self):
        cache = ResponseCache(max_size=100, ttl_seconds=60)
        cache.put("m", "A", "response")
        d = cache.to_dict()
        assert d["enabled"] is True
        assert d["max_size"] == 100
        assert d["current_size"] == 1
        assert d["ttl_seconds"] == 60
        assert "stats" in d

    def test_to_dict_empty(self):
        cache = ResponseCache()
        d = cache.to_dict()
        assert d["current_size"] == 0


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_drivers_package(self):
        from core.drivers import CacheStats, ResponseCache

        assert all([ResponseCache, CacheStats])

    def test_from_module(self):
        from core.drivers.response_cache import (
            CacheEntry,
            CacheStats,
            ResponseCache,
        )

        assert all([ResponseCache, CacheEntry, CacheStats])
