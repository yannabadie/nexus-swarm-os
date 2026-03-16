"""
Routing Decision Cache - Cache and learn from routing decisions.

V12.4 COGNITIVE BOOST

Caches model routing decisions to avoid re-computation for repeated
task patterns, and learns from execution outcomes to improve future routing.

Usage:
    from core.execution_pkg.routing.decision_cache import get_decision_cache

    cache = get_decision_cache()

    # Cache a routing decision
    cache.record_decision("coding:python:medium", model_id="claude-sonnet", cost=0.01)

    # Look up cached decision
    decision = cache.get_decision("coding:python:medium")

    # Record outcome for learning
    cache.record_outcome("coding:python:medium", success=True, quality=0.95, latency=2.5)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_SIZE = 500
DEFAULT_TTL = 3600.0  # 1 hour
LEARNING_RATE = 0.15  # EMA learning rate for quality/latency
MAX_CACHE_SIZE = 10000


# =============================================================================
# Types
# =============================================================================


@dataclass
class CachedDecision:
    """A cached routing decision."""

    task_fingerprint: str
    model_id: str
    cost: float = 0.0
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float = 0.0
    hit_count: int = 0
    # Learned metrics (updated via feedback)
    avg_quality: float = 0.0
    avg_latency: float = 0.0
    total_outcomes: int = 0
    success_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at

    @property
    def success_rate(self) -> float:
        if self.total_outcomes == 0:
            return 0.0
        return self.success_count / self.total_outcomes

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_fingerprint": self.task_fingerprint,
            "model_id": self.model_id,
            "cost": self.cost,
            "hit_count": self.hit_count,
            "avg_quality": round(self.avg_quality, 4),
            "avg_latency": round(self.avg_latency, 4),
            "total_outcomes": self.total_outcomes,
            "success_rate": round(self.success_rate, 4),
            "is_expired": self.is_expired,
        }


@dataclass
class DecisionOutcome:
    """Outcome of a routing decision for learning."""

    task_fingerprint: str
    success: bool
    quality: float = 0.0
    latency: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_fingerprint": self.task_fingerprint,
            "success": self.success,
            "quality": self.quality,
            "latency": self.latency,
            "timestamp": self.timestamp,
        }


@dataclass
class DecisionCacheStats:
    """Cache statistics."""

    size: int
    max_size: int
    hits: int
    misses: int
    hit_rate: float
    total_decisions: int
    total_outcomes: int
    evictions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "total_decisions": self.total_decisions,
            "total_outcomes": self.total_outcomes,
            "evictions": self.evictions,
        }


# =============================================================================
# Decision Cache
# =============================================================================


class RoutingDecisionCache:
    """
    LRU cache for routing decisions with learning from outcomes.

    Features:
    - LRU eviction when max size reached
    - TTL expiration per decision
    - Feedback loop: outcomes update cached decision quality/latency
    - Hit/miss tracking
    - Thread-safe
    """

    def __init__(self, *, max_size: int = DEFAULT_MAX_SIZE, default_ttl: float = DEFAULT_TTL):
        self._max_size = min(max_size, MAX_CACHE_SIZE)
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, CachedDecision] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._total_decisions = 0
        self._total_outcomes = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Core Operations
    # =========================================================================

    def record_decision(
        self,
        task_fingerprint: str,
        *,
        model_id: str,
        cost: float = 0.0,
        ttl: float | None = None,
    ) -> CachedDecision:
        """Record a routing decision in the cache."""
        now = time.monotonic()
        actual_ttl = ttl if ttl is not None else self._default_ttl

        with self._lock:
            # Update existing or create new
            if task_fingerprint in self._cache:
                decision = self._cache[task_fingerprint]
                decision.model_id = model_id
                decision.cost = cost
                decision.created_at = now
                decision.expires_at = now + actual_ttl
                self._cache.move_to_end(task_fingerprint)
            else:
                decision = CachedDecision(
                    task_fingerprint=task_fingerprint,
                    model_id=model_id,
                    cost=cost,
                    created_at=now,
                    expires_at=now + actual_ttl,
                )
                # Evict LRU if full
                while len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                    self._evictions += 1
                self._cache[task_fingerprint] = decision

            self._total_decisions += 1
            return decision

    def get_decision(self, task_fingerprint: str) -> CachedDecision | None:
        """Look up a cached routing decision."""
        with self._lock:
            decision = self._cache.get(task_fingerprint)
            if decision is None:
                self._misses += 1
                return None
            if decision.is_expired:
                del self._cache[task_fingerprint]
                self._misses += 1
                return None
            self._cache.move_to_end(task_fingerprint)
            decision.hit_count += 1
            self._hits += 1
            return decision

    def has_decision(self, task_fingerprint: str) -> bool:
        """Check if a non-expired decision exists."""
        decision = self._cache.get(task_fingerprint)
        if decision is None:
            return False
        return not decision.is_expired

    def delete_decision(self, task_fingerprint: str) -> bool:
        """Remove a cached decision."""
        with self._lock:
            if task_fingerprint in self._cache:
                del self._cache[task_fingerprint]
                return True
            return False

    # =========================================================================
    # Learning / Feedback
    # =========================================================================

    def record_outcome(
        self,
        task_fingerprint: str,
        *,
        success: bool,
        quality: float = 0.0,
        latency: float = 0.0,
    ) -> bool:
        """
        Record the outcome of a routing decision for learning.
        Updates the cached decision's average quality and latency via EMA.

        Returns True if outcome was recorded (decision found in cache).
        """
        with self._lock:
            decision = self._cache.get(task_fingerprint)
            if decision is None:
                return False

            decision.total_outcomes += 1
            if success:
                decision.success_count += 1

            self._total_outcomes += 1

            # Exponential moving average for quality and latency
            q = max(0.0, min(1.0, quality))
            if decision.total_outcomes == 1:
                decision.avg_quality = q
                decision.avg_latency = latency
            else:
                decision.avg_quality = (1 - LEARNING_RATE) * decision.avg_quality + LEARNING_RATE * q
                decision.avg_latency = (1 - LEARNING_RATE) * decision.avg_latency + LEARNING_RATE * latency

            return True

    def get_best_model(self, task_fingerprint: str) -> str | None:
        """
        Get the cached model for a task fingerprint, or None.
        Only returns models with positive success rates.
        """
        decision = self.get_decision(task_fingerprint)
        if decision is None:
            return None
        # If we have outcomes and success rate is too low, don't recommend
        if decision.total_outcomes >= 3 and decision.success_rate < 0.3:
            return None
        return decision.model_id

    # =========================================================================
    # Maintenance
    # =========================================================================

    def cleanup_expired(self) -> int:
        """Remove expired entries."""
        with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired]
            for key in expired:
                del self._cache[key]
            return len(expired)

    def delete_by_model(self, model_id: str) -> int:
        """Delete all decisions for a specific model."""
        with self._lock:
            keys = [k for k, v in self._cache.items() if v.model_id == model_id]
            for key in keys:
                del self._cache[key]
            return len(keys)

    def list_fingerprints(self, *, prefix: str = "") -> list[str]:
        """List all non-expired fingerprints."""
        now = time.monotonic()
        return [k for k, v in self._cache.items() if v.expires_at > now and (not prefix or k.startswith(prefix))]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> DecisionCacheStats:
        total_lookups = self._hits + self._misses
        hit_rate = self._hits / total_lookups if total_lookups > 0 else 0.0
        return DecisionCacheStats(
            size=len(self._cache),
            max_size=self._max_size,
            hits=self._hits,
            misses=self._misses,
            hit_rate=hit_rate,
            total_decisions=self._total_decisions,
            total_outcomes=self._total_outcomes,
            evictions=self._evictions,
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
        """Clear cache and reset stats."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._total_decisions = 0
            self._total_outcomes = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_size": self._max_size,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_cache: RoutingDecisionCache | None = None
_cache_lock = threading.Lock()


def get_decision_cache() -> RoutingDecisionCache:
    """Get or create the global decision cache."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = RoutingDecisionCache()
    return _cache


def reset_decision_cache() -> None:
    """Reset the global decision cache (for testing)."""
    global _cache
    _cache = None
