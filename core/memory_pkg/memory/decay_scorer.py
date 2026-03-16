"""
Memory Decay Scorer - Ebbinghaus forgetting curve for RAG retrieval.

V12.4 COGNITIVE BOOST

Implements time-based decay scoring for memory chunks based on the
Ebbinghaus forgetting curve (arxiv:2512.13564). Memories that are
accessed frequently retain high scores; unused memories gradually
fade, reducing noise in retrieval results.

Decay formula:
    retention = 1 - exp(-access_count / (days_since_last_access + 1))

This naturally prioritizes:
- Frequently accessed chunks (high access_count)
- Recently accessed chunks (low days_since_last_access)
- New chunks get a grace period (first access = full score)

Usage:
    from core.memory_pkg.memory.decay_scorer import get_decay_scorer

    scorer = get_decay_scorer()

    # Record access when a chunk is retrieved
    scorer.record_access("core/auth.py:10-50")

    # Get decay-adjusted scores
    adjusted = scorer.apply_decay(scored_chunks)
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class AccessRecord:
    """Tracks access patterns for a single chunk."""

    chunk_id: str = ""
    access_count: int = 0
    first_access: float = 0.0  # timestamp
    last_access: float = 0.0  # timestamp
    total_score: float = 0.0  # sum of retrieval scores over accesses

    @property
    def avg_score(self) -> float:
        if self.access_count == 0:
            return 0.0
        return self.total_score / self.access_count

    @property
    def days_since_last(self) -> float:
        if self.last_access == 0:
            return 0.0
        return (time.time() - self.last_access) / 86400.0

    @property
    def retention(self) -> float:
        """Ebbinghaus-inspired retention score (0.0 to 1.0)."""
        if self.access_count == 0:
            return 0.5  # Unknown chunks get neutral score
        days = self.days_since_last
        return 1.0 - math.exp(-self.access_count / (days + 1.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "access_count": self.access_count,
            "days_since_last": round(self.days_since_last, 2),
            "retention": round(self.retention, 4),
            "avg_score": round(self.avg_score, 4),
        }


@dataclass
class DecayScorerStats:
    """Statistics for the decay scorer."""

    tracked_chunks: int = 0
    total_accesses: int = 0
    avg_retention: float = 0.0
    stale_chunks: int = 0  # retention < 0.3

    def to_dict(self) -> dict[str, Any]:
        return {
            "tracked_chunks": self.tracked_chunks,
            "total_accesses": self.total_accesses,
            "avg_retention": round(self.avg_retention, 4),
            "stale_chunks": self.stale_chunks,
        }


class MemoryDecayScorer:
    """
    Applies Ebbinghaus forgetting curve to RAG retrieval scores.

    Tracks access patterns per chunk and adjusts retrieval scores:
    - final_score = base_score * (decay_weight * retention + (1 - decay_weight))

    The decay_weight controls how much the forgetting curve affects
    the final score (0.0 = no decay effect, 1.0 = full decay effect).
    Default 0.3 means decay accounts for 30% of the final score.
    """

    def __init__(
        self,
        decay_weight: float = 0.3,
        max_tracked: int = 50000,
        stale_threshold: float = 0.3,
    ) -> None:
        self._records: dict[str, AccessRecord] = {}
        self._decay_weight = decay_weight
        self._max_tracked = max_tracked
        self._stale_threshold = stale_threshold
        self._lock = threading.Lock()
        self._total_accesses = 0

    def record_access(
        self,
        chunk_id: str,
        score: float = 0.0,
    ) -> AccessRecord:
        """Record that a chunk was accessed (retrieved and used).

        Args:
            chunk_id: Unique chunk identifier (e.g., "file.py:10-50").
            score: Retrieval score for this access.

        Returns:
            Updated AccessRecord.
        """
        now = time.time()
        with self._lock:
            self._total_accesses += 1

            if chunk_id not in self._records:
                if len(self._records) >= self._max_tracked:
                    self._evict_stalest()
                self._records[chunk_id] = AccessRecord(
                    chunk_id=chunk_id,
                    access_count=0,
                    first_access=now,
                )

            rec = self._records[chunk_id]
            rec.access_count += 1
            rec.last_access = now
            rec.total_score += score

        return rec

    def get_retention(self, chunk_id: str) -> float:
        """Get the current retention score for a chunk."""
        with self._lock:
            rec = self._records.get(chunk_id)
        if rec is None:
            return 0.5  # Unknown = neutral
        return rec.retention

    def adjust_score(self, chunk_id: str, base_score: float) -> float:
        """Adjust a retrieval score with decay weighting.

        final = base * (w * retention + (1 - w))
        where w = decay_weight (default 0.3).
        """
        retention = self.get_retention(chunk_id)
        w = self._decay_weight
        return base_score * (w * retention + (1.0 - w))

    def apply_decay_to_scored(
        self,
        scored_chunks: list,
        record: bool = True,
    ) -> list:
        """Apply decay scoring to a list of ScoredChunk objects.

        Adjusts each ScoredChunk.score with the decay curve and
        optionally records the access for future decay calculations.

        Args:
            scored_chunks: List of ScoredChunk from backend retrieval.
            record: Whether to record this as an access event.

        Returns:
            Same list with adjusted scores, re-sorted by score.
        """
        for sc in scored_chunks:
            cid = sc.chunk_id
            original = sc.score
            sc.score = self.adjust_score(cid, original)
            if record:
                self.record_access(cid, original)

        scored_chunks.sort(key=lambda s: s.score, reverse=True)
        return scored_chunks

    def get_stats(self) -> DecayScorerStats:
        """Get decay scorer statistics."""
        with self._lock:
            records = list(self._records.values())

        if not records:
            return DecayScorerStats()

        retentions = [r.retention for r in records]
        avg_ret = sum(retentions) / len(retentions)
        stale = sum(1 for r in retentions if r < self._stale_threshold)

        return DecayScorerStats(
            tracked_chunks=len(records),
            total_accesses=self._total_accesses,
            avg_retention=avg_ret,
            stale_chunks=stale,
        )

    def get_stale_chunks(self, limit: int = 20) -> list[AccessRecord]:
        """Get chunks with lowest retention (candidates for cleanup)."""
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda r: r.retention)
        return records[:limit]

    def clear(self) -> None:
        """Clear all access records."""
        with self._lock:
            self._records.clear()
            self._total_accesses = 0

    def _evict_stalest(self) -> None:
        """Evict the chunk with lowest retention to make room."""
        if not self._records:
            return
        stalest = min(self._records.values(), key=lambda r: r.retention)
        del self._records[stalest.chunk_id]


# =============================================================================
# Global Singleton
# =============================================================================

_scorer: MemoryDecayScorer | None = None
_scorer_lock = threading.Lock()


def get_decay_scorer() -> MemoryDecayScorer:
    """Get or create the global memory decay scorer."""
    global _scorer
    if _scorer is None:
        with _scorer_lock:
            if _scorer is None:
                _scorer = MemoryDecayScorer()
    return _scorer


def reset_decay_scorer() -> None:
    """Reset the global decay scorer (for testing)."""
    global _scorer
    _scorer = None
