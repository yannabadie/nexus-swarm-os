"""
Context Window Tracker - Track context window consumption across sessions.

V12.4 COGNITIVE BOOST

Monitors context window token usage per model and session, records
compression events, classifies utilization levels (normal/warning/critical),
and provides aggregate statistics for capacity planning.

Usage:
    from core.memory_pkg.memory.context_window_tracker import get_context_tracker

    tracker = get_context_tracker()

    # Record usage
    record = tracker.record_usage(
        session_id="sess_001",
        model_id="claude-opus-4-6-20250116",
        input_tokens=12000,
        output_tokens=4000,
        max_tokens=200000,
    )
    print(record.utilization)  # 0.08
    print(record.level)        # "normal"

    # Record a compression event
    evt = tracker.record_compression(
        original_tokens=180000,
        compressed_tokens=60000,
        session_id="sess_001",
    )
    print(evt.compression_ratio)  # 0.6667
    print(evt.tokens_saved)       # 120000

    # Check current level
    level = tracker.get_current_level()  # "normal" | "warning" | "critical"

    # Get statistics
    stats = tracker.get_stats()
    print(stats.peak_utilization)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_USAGE_RECORDS = 50000
CONTEXT_WARNING_THRESHOLD = 0.8  # 80% usage triggers warning
CONTEXT_CRITICAL_THRESHOLD = 0.95  # 95% triggers critical


# =============================================================================
# Types
# =============================================================================


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


@dataclass
class ContextUsageRecord:
    """A single context window usage measurement."""

    record_id: str = ""
    session_id: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    max_tokens: int = 0
    timestamp: str = field(default_factory=_utc_now_iso)

    @property
    def utilization(self) -> float:
        """Fraction of context window in use (0.0 to 1.0+)."""
        if self.max_tokens > 0:
            return self.total_tokens / self.max_tokens
        return 0.0

    @property
    def level(self) -> str:
        """Classify utilization: 'critical', 'warning', or 'normal'."""
        util = self.utilization
        if util >= CONTEXT_CRITICAL_THRESHOLD:
            return "critical"
        if util >= CONTEXT_WARNING_THRESHOLD:
            return "warning"
        return "normal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "utilization": round(self.utilization, 4),
            "level": self.level,
            "timestamp": self.timestamp,
        }


@dataclass
class CompressionEvent:
    """Record of when context was compressed to free capacity."""

    original_tokens: int = 0
    compressed_tokens: int = 0
    session_id: str = ""
    timestamp: str = field(default_factory=_utc_now_iso)

    @property
    def compression_ratio(self) -> float:
        """Fraction of tokens saved (0.0 to 1.0)."""
        if self.original_tokens > 0:
            return 1.0 - (self.compressed_tokens / self.original_tokens)
        return 0.0

    @property
    def tokens_saved(self) -> int:
        """Absolute number of tokens freed by compression."""
        return self.original_tokens - self.compressed_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "compression_ratio": round(self.compression_ratio, 4),
            "tokens_saved": self.tokens_saved,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


@dataclass
class ContextTrackerStats:
    """Aggregate statistics for the context window tracker."""

    total_records: int = 0
    total_compressions: int = 0
    avg_utilization: float = 0.0
    peak_utilization: float = 0.0
    total_tokens_saved: int = 0
    warning_count: int = 0
    critical_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "total_compressions": self.total_compressions,
            "avg_utilization": round(self.avg_utilization, 4),
            "peak_utilization": round(self.peak_utilization, 4),
            "total_tokens_saved": self.total_tokens_saved,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
        }


# =============================================================================
# Context Window Tracker
# =============================================================================


class ContextWindowTracker:
    """
    Tracks context window token consumption across sessions and models.

    Features:
    - Per-request usage recording with auto-generated IDs
    - Compression event logging with ratio computation
    - Utilization classification (normal / warning / critical)
    - Peak utilization tracking
    - Bounded history with FIFO eviction
    - Thread-safe
    """

    def __init__(self, max_records: int = MAX_USAGE_RECORDS):
        self._records: list[ContextUsageRecord] = []
        self._compressions: list[CompressionEvent] = []
        self._max_records = max_records
        self._lock = threading.Lock()
        self._counter = 0
        self._peak_utilization: float = 0.0

    # =========================================================================
    # Recording
    # =========================================================================

    def record_usage(
        self,
        session_id: str = "",
        model_id: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        max_tokens: int = 0,
    ) -> ContextUsageRecord:
        """Record a context window usage measurement.

        Auto-generates a record_id of the form ``ctx_NNNNNN``.
        If *total_tokens* is zero, it is computed as
        ``input_tokens + output_tokens``.  Evicts the oldest record
        when the history limit is reached.
        """
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens

        with self._lock:
            rid = f"ctx_{self._counter:06d}"
            self._counter += 1
            record = ContextUsageRecord(
                record_id=rid,
                session_id=session_id,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                max_tokens=max_tokens,
            )
            # Track peak utilization
            util = record.utilization
            if util > self._peak_utilization:
                self._peak_utilization = util
            # FIFO eviction
            if len(self._records) >= self._max_records:
                self._records.pop(0)
            self._records.append(record)
        return record

    def record_compression(
        self,
        original_tokens: int,
        compressed_tokens: int,
        session_id: str = "",
    ) -> CompressionEvent:
        """Record a context compression event.

        Appends the event to the compression history.
        """
        event = CompressionEvent(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            session_id=session_id,
        )
        with self._lock:
            self._compressions.append(event)
        return event

    # =========================================================================
    # Analysis
    # =========================================================================

    def get_current_level(self) -> str:
        """Return the utilization level of the most recent record.

        Returns ``"normal"`` if no records have been recorded.
        """
        with self._lock:
            if not self._records:
                return "normal"
            return self._records[-1].level

    def get_recent_usage(self, limit: int = 20) -> list[ContextUsageRecord]:
        """Return the most recent usage records (newest last)."""
        with self._lock:
            return list(self._records[-limit:])

    def get_high_usage_records(
        self,
        threshold: float = CONTEXT_WARNING_THRESHOLD,
    ) -> list[ContextUsageRecord]:
        """Return records where utilization >= *threshold*."""
        with self._lock:
            return [r for r in self._records if r.utilization >= threshold]

    def get_compression_history(self, limit: int = 20) -> list[CompressionEvent]:
        """Return the most recent compression events (newest last)."""
        with self._lock:
            return list(self._compressions[-limit:])

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> ContextTrackerStats:
        """Compute aggregate context window statistics."""
        with self._lock:
            total_records = len(self._records)
            total_compressions = len(self._compressions)
            total_tokens_saved = sum(c.tokens_saved for c in self._compressions)

            if self._records:
                utils = [r.utilization for r in self._records]
                avg_util = sum(utils) / len(utils)
                warning_count = sum(1 for r in self._records if r.level in ("warning", "critical"))
                critical_count = sum(1 for r in self._records if r.level == "critical")
            else:
                avg_util = 0.0
                warning_count = 0
                critical_count = 0

            peak = self._peak_utilization

        return ContextTrackerStats(
            total_records=total_records,
            total_compressions=total_compressions,
            avg_utilization=avg_util,
            peak_utilization=peak,
            total_tokens_saved=total_tokens_saved,
            warning_count=warning_count,
            critical_count=critical_count,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def record_count(self) -> int:
        """Number of recorded usage measurements."""
        return len(self._records)

    @property
    def compression_count(self) -> int:
        """Number of recorded compression events."""
        return len(self._compressions)

    def clear(self) -> None:
        """Clear all recorded data and reset counters."""
        with self._lock:
            self._records.clear()
            self._compressions.clear()
            self._counter = 0
            self._peak_utilization = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise tracker state as a dict.

        Computes stats before acquiring the lock to avoid re-entrant
        locking (get_stats uses self._lock internally).
        """
        stats = self.get_stats()
        with self._lock:
            return {
                "record_count": len(self._records),
                "compression_count": len(self._compressions),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_tracker: ContextWindowTracker | None = None
_tracker_lock = threading.Lock()


def get_context_tracker() -> ContextWindowTracker:
    """Get or create the global context window tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ContextWindowTracker()
    return _tracker


def reset_context_tracker() -> None:
    """Reset the global context window tracker (for testing)."""
    global _tracker
    _tracker = None
