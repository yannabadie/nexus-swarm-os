"""
Memory Cache Manager - LRU cache for memory queries.

V12.4 COGNITIVE BOOST - Task #73

Provides a high-speed LRU cache layer for frequently-accessed memory
data with TTL-based expiration, hit/miss tracking, and eviction.

Usage:
    from core.memory_pkg.memory.cache_manager import get_cache_manager

    cache = get_cache_manager()

    # Store and retrieve
    cache.put("query:auth", {"results": [...]}, ttl=300)
    result = cache.get("query:auth")

    # Get or compute
    result = cache.get_or_compute("key", lambda: expensive_query())
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

_logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_SIZE = 1000
DEFAULT_TTL = 300.0  # 5 minutes
MAX_CACHE_SIZE = 100000


# =============================================================================
# Types
# =============================================================================


@dataclass
class CacheEntry:
    """A cached item with metadata."""

    key: str
    value: Any
    created_at: float
    expires_at: float
    hit_count: int = 0
    size_bytes: int = 0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at

    @property
    def ttl_remaining(self) -> float:
        r = self.expires_at - time.monotonic()
        return max(0.0, r)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "hit_count": self.hit_count,
            "size_bytes": self.size_bytes,
            "ttl_remaining": round(self.ttl_remaining, 2),
            "is_expired": self.is_expired,
        }


@dataclass
class CacheStats:
    """Cache statistics."""

    size: int
    max_size: int
    hits: int
    misses: int
    evictions: int
    expirations: int
    hit_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "hit_rate": round(self.hit_rate, 4),
        }


# =============================================================================
# Cache Manager
# =============================================================================


class CacheManager:
    """
    LRU cache with TTL expiration.

    Features:
    - LRU eviction when max size reached
    - TTL-based expiration per entry
    - Hit/miss statistics
    - get_or_compute pattern
    - Namespace prefixing
    - Thread-safe
    """

    def __init__(self, *, max_size: int = DEFAULT_MAX_SIZE, default_ttl: float = DEFAULT_TTL):
        self._max_size = min(max_size, MAX_CACHE_SIZE)
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Core Operations
    # =========================================================================

    def put(self, key: str, value: Any, *, ttl: float | None = None, size_bytes: int = 0) -> None:
        """Store a value in the cache."""
        now = time.monotonic()
        actual_ttl = ttl if ttl is not None else self._default_ttl
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=now,
            expires_at=now + actual_ttl,
            size_bytes=size_bytes,
        )
        with self._lock:
            # Remove existing to update position
            if key in self._cache:
                del self._cache[key]
            # Evict LRU if full
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
                self._evictions += 1
            self._cache[key] = entry

    def get(self, key: str) -> Any:
        """Get a value from the cache. Returns None if not found or expired."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired:
                del self._cache[key]
                self._expirations += 1
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._hits += 1
            return entry.value

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], T],
        *,
        ttl: float | None = None,
        size_bytes: int = 0,
    ) -> T:
        """Get from cache or compute and store."""
        result = self.get(key)
        if result is not None:
            return result
        value = compute_fn()
        self.put(key, value, ttl=ttl, size_bytes=size_bytes)
        return value

    def has(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired:
                del self._cache[key]
                self._expirations += 1
                return False
            return True

    def delete(self, key: str) -> bool:
        """Delete a specific key."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def get_entry(self, key: str) -> CacheEntry | None:
        """Get the cache entry (metadata) for a key."""
        entry = self._cache.get(key)
        if entry is None or entry.is_expired:
            return None
        return entry

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all keys matching a prefix."""
        with self._lock:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._cache[key]
            return len(keys_to_delete)

    def list_keys(self, *, prefix: str = "") -> list[str]:
        """List all non-expired keys, optionally filtered by prefix."""
        now = time.monotonic()
        return [k for k, v in self._cache.items() if v.expires_at > now and (not prefix or k.startswith(prefix))]

    # =========================================================================
    # Maintenance
    # =========================================================================

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired]
            for key in expired:
                del self._cache[key]
                self._expirations += 1
            return len(expired)

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return CacheStats(
            size=len(self._cache),
            max_size=self._max_size,
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            expirations=self._expirations,
            hit_rate=hit_rate,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def max_size(self) -> int:
        return self._max_size

    def clear(self) -> None:
        """Clear all cached entries and reset stats."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_size": self._max_size,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_cache: CacheManager | None = None
_cache_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """Get or create the global cache manager."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = CacheManager()
    return _cache


def reset_cache_manager() -> None:
    """Reset the global cache manager (for testing)."""
    global _cache
    _cache = None
