"""
LLM Response Cache - Deduplication cache for identical API calls.

V12.4 COGNITIVE BOOST - Task #40

LRU cache with TTL for deduplicating identical LLM requests.
Caches responses by prompt hash + model + temperature to avoid
redundant API calls and reduce costs.

Usage:
    from core.drivers.response_cache import ResponseCache

    cache = ResponseCache(max_size=500, ttl_seconds=300)

    # Check cache before API call
    cached = cache.get("gemini-3-pro", "What is NEXUS?", temperature=0.7)
    if cached:
        return cached  # Cache hit!

    # After API call, store result
    cache.put("gemini-3-pro", "What is NEXUS?", response_content, temperature=0.7)
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


@dataclass
class CacheEntry:
    """A cached LLM response."""

    key: str
    model: str
    content: str
    created_at: float  # monotonic time
    expires_at: float  # monotonic time
    tokens_saved: int = 0
    hit_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key[:16] + "...",
            "model": self.model,
            "content_length": len(self.content),
            "tokens_saved": self.tokens_saved,
            "hit_count": self.hit_count,
            "age_seconds": round(self.age_seconds, 1),
            "is_expired": self.is_expired,
        }


@dataclass
class CacheStats:
    """Cache performance statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    total_tokens_saved: int = 0

    @property
    def total_lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_lookups == 0:
            return 0.0
        return self.hits / self.total_lookups

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "total_lookups": self.total_lookups,
            "hit_rate": round(self.hit_rate, 4),
            "total_tokens_saved": self.total_tokens_saved,
        }


# =============================================================================
# Response Cache
# =============================================================================


class ResponseCache:
    """
    LRU cache with TTL for LLM responses.

    Keys are computed from model + prompt + temperature hash.
    Entries expire after TTL and are evicted LRU when cache is full.
    Thread-safe for concurrent access.
    """

    def __init__(
        self,
        max_size: int = 500,
        ttl_seconds: float = 300.0,
        enabled: bool = True,
    ):
        """
        Initialize response cache.

        Args:
            max_size: Maximum cached entries
            ttl_seconds: Time-to-live for entries
            enabled: Whether cache is active
        """
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._enabled = enabled
        self._lock = Lock()
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats()

    def get(
        self,
        model: str,
        prompt: str,
        *,
        temperature: float = 0.7,
        system_prompt: str = "",
    ) -> str | None:
        """
        Look up a cached response.

        Args:
            model: Model name
            prompt: User prompt
            temperature: Temperature setting
            system_prompt: System prompt

        Returns:
            Cached response content, or None on miss
        """
        if not self._enabled:
            return None

        key = self._make_key(model, prompt, temperature, system_prompt)

        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats.misses += 1
                return None

            if entry.is_expired:
                del self._cache[key]
                self._stats.expirations += 1
                self._stats.misses += 1
                return None

            # LRU: move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._stats.hits += 1
            self._stats.total_tokens_saved += entry.tokens_saved

            return entry.content

    def put(
        self,
        model: str,
        prompt: str,
        content: str,
        *,
        temperature: float = 0.7,
        system_prompt: str = "",
        tokens_used: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Cache a response.

        Args:
            model: Model name
            prompt: User prompt
            content: Response content
            temperature: Temperature setting
            system_prompt: System prompt
            tokens_used: Tokens used (for savings tracking)
            metadata: Optional metadata

        Returns:
            Cache key
        """
        if not self._enabled:
            return ""

        key = self._make_key(model, prompt, temperature, system_prompt)
        now = time.monotonic()

        with self._lock:
            # Evict expired entries
            self._evict_expired()

            # Evict LRU if full
            while len(self._cache) >= self._max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                self._stats.evictions += 1

            entry = CacheEntry(
                key=key,
                model=model,
                content=content,
                created_at=now,
                expires_at=now + self._ttl,
                tokens_saved=tokens_used,
                metadata=metadata or {},
            )

            self._cache[key] = entry

        return key

    def invalidate(self, model: str, prompt: str, **kwargs) -> bool:
        """
        Remove a specific entry from cache.

        Returns:
            True if entry was found and removed
        """
        key = self._make_key(
            model,
            prompt,
            kwargs.get("temperature", 0.7),
            kwargs.get("system_prompt", ""),
        )
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> int:
        """
        Clear all cached entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        with self._lock:
            self._stats = CacheStats()

    @property
    def size(self) -> int:
        """Current number of cached entries."""
        with self._lock:
            return len(self._cache)

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics (copy)."""
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                expirations=self._stats.expirations,
                total_tokens_saved=self._stats.total_tokens_saved,
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def to_dict(self) -> dict[str, Any]:
        """Export cache state."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "max_size": self._max_size,
                "current_size": len(self._cache),
                "ttl_seconds": self._ttl,
                "stats": self._stats.to_dict(),
            }

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _make_key(
        self,
        model: str,
        prompt: str,
        temperature: float,
        system_prompt: str,
    ) -> str:
        """Create a cache key from request parameters."""
        raw = f"{model}|{temperature:.2f}|{system_prompt}|{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _evict_expired(self) -> None:
        """Remove expired entries (must hold lock)."""
        expired = [key for key, entry in self._cache.items() if entry.is_expired]
        for key in expired:
            del self._cache[key]
            self._stats.expirations += 1
