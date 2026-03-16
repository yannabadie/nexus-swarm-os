"""
Memory Pressure Monitor - Track memory utilization and eviction pressure.

V12.4 COGNITIVE BOOST

Monitors memory snapshots, eviction events, pressure trends, and
recommends compression actions when utilization exceeds thresholds.

Usage:
    from core.memory_pkg.memory.memory_pressure_monitor import get_pressure_monitor

    monitor = get_pressure_monitor()

    # Record a memory snapshot
    snap = monitor.record_snapshot(
        cache_items=250,
        cache_bytes=1024000,
        blackboard_bytes=512000,
        conversation_turns=45,
        total_bytes=1536000,
        max_bytes=4096000,
    )

    # Check pressure level
    level = monitor.get_pressure_level()
    print(level.level)           # "normal" | "warning" | "critical"
    print(level.recommendation)  # action guidance

    # Record eviction
    monitor.record_eviction(reason="lru", items_evicted=10, bytes_freed=8192, source="cache")

    # Analyze trends
    trend = monitor.get_trend(window=10)
    print(trend["trend"])  # "increasing" | "decreasing" | "stable"
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_SNAPSHOTS = 10000
MAX_EVICTIONS = 50000
PRESSURE_THRESHOLD_WARNING = 0.7  # 70% utilization
PRESSURE_THRESHOLD_CRITICAL = 0.9  # 90% utilization


# =============================================================================
# Types
# =============================================================================


@dataclass
class MemorySnapshot:
    """A point-in-time capture of memory utilization."""

    snapshot_id: str = ""
    cache_items: int = 0
    cache_bytes: int = 0
    blackboard_bytes: int = 0
    conversation_turns: int = 0
    total_bytes: int = 0
    max_bytes: int = 0
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def utilization(self) -> float:
        """Fraction of capacity in use (0.0 to 1.0+)."""
        if self.max_bytes > 0:
            return self.total_bytes / self.max_bytes
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "cache_items": self.cache_items,
            "cache_bytes": self.cache_bytes,
            "blackboard_bytes": self.blackboard_bytes,
            "conversation_turns": self.conversation_turns,
            "total_bytes": self.total_bytes,
            "max_bytes": self.max_bytes,
            "utilization": round(self.utilization, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class EvictionEvent:
    """Record of an eviction from a cache or store."""

    reason: str = ""
    items_evicted: int = 0
    bytes_freed: int = 0
    source: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "items_evicted": self.items_evicted,
            "bytes_freed": self.bytes_freed,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class PressureLevel:
    """Current memory pressure classification with recommendation."""

    level: str
    utilization: float
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "utilization": round(self.utilization, 4),
            "recommendation": self.recommendation,
        }


@dataclass
class PressureStats:
    """Aggregate statistics for the pressure monitor."""

    total_snapshots: int
    total_evictions: int
    total_bytes_freed: int
    current_level: str
    avg_utilization: float
    peak_utilization: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_snapshots": self.total_snapshots,
            "total_evictions": self.total_evictions,
            "total_bytes_freed": self.total_bytes_freed,
            "current_level": self.current_level,
            "avg_utilization": round(self.avg_utilization, 4),
            "peak_utilization": round(self.peak_utilization, 4),
        }


# =============================================================================
# Memory Pressure Monitor
# =============================================================================


class MemoryPressureMonitor:
    """
    Tracks memory snapshots and eviction events to assess pressure.

    Features:
    - Point-in-time memory snapshots with auto-generated IDs
    - Eviction event recording by reason and source
    - Pressure classification (normal / warning / critical)
    - Utilization trend analysis over a sliding window
    - Bounded history with configurable maximums
    - Thread-safe
    """

    def __init__(
        self,
        *,
        max_snapshots: int = MAX_SNAPSHOTS,
        max_evictions: int = MAX_EVICTIONS,
    ):
        self._snapshots: list[MemorySnapshot] = []
        self._evictions: list[EvictionEvent] = []
        self._counter: int = 0
        self._max_snapshots = max_snapshots
        self._max_evictions = max_evictions
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_snapshot(
        self,
        *,
        cache_items: int = 0,
        cache_bytes: int = 0,
        blackboard_bytes: int = 0,
        conversation_turns: int = 0,
        total_bytes: int = 0,
        max_bytes: int = 0,
    ) -> MemorySnapshot:
        """Record a memory utilization snapshot.

        Auto-generates a snapshot_id of the form ``ms_NNNNNN``.
        Evicts the oldest snapshot when the history limit is reached.
        """
        with self._lock:
            self._counter += 1
            sid = f"ms_{self._counter:06d}"
            snap = MemorySnapshot(
                snapshot_id=sid,
                cache_items=cache_items,
                cache_bytes=cache_bytes,
                blackboard_bytes=blackboard_bytes,
                conversation_turns=conversation_turns,
                total_bytes=total_bytes,
                max_bytes=max_bytes,
            )
            if len(self._snapshots) >= self._max_snapshots:
                self._snapshots.pop(0)
            self._snapshots.append(snap)
        return snap

    def record_eviction(
        self,
        *,
        reason: str = "",
        items_evicted: int = 0,
        bytes_freed: int = 0,
        source: str = "",
    ) -> EvictionEvent:
        """Record an eviction event.

        Evicts the oldest event when the history limit is reached.
        """
        event = EvictionEvent(
            reason=reason,
            items_evicted=items_evicted,
            bytes_freed=bytes_freed,
            source=source,
        )
        with self._lock:
            if len(self._evictions) >= self._max_evictions:
                self._evictions.pop(0)
            self._evictions.append(event)
        return event

    # =========================================================================
    # Analysis
    # =========================================================================

    def get_pressure_level(self) -> PressureLevel:
        """Classify current memory pressure based on the latest snapshot.

        Returns ``normal`` if no snapshots have been recorded.
        """
        with self._lock:
            if not self._snapshots:
                return PressureLevel(
                    level="normal",
                    utilization=0.0,
                    recommendation="No action needed",
                )
            last = self._snapshots[-1]
            util = last.utilization

        if util >= PRESSURE_THRESHOLD_CRITICAL:
            return PressureLevel(
                level="critical",
                utilization=util,
                recommendation="Immediate eviction required",
            )
        if util >= PRESSURE_THRESHOLD_WARNING:
            return PressureLevel(
                level="warning",
                utilization=util,
                recommendation="Consider compressing context",
            )
        return PressureLevel(
            level="normal",
            utilization=util,
            recommendation="No action needed",
        )

    def get_trend(self, *, window: int = 10) -> dict[str, Any]:
        """Analyse utilization trend over the last *window* snapshots.

        Returns a dict with:
        - ``avg_utilization``: mean utilization in the window
        - ``trend``: ``"increasing"``, ``"decreasing"``, or ``"stable"``
        - ``growth_rate_bytes_per_sec``: estimated byte-growth per second
        """
        with self._lock:
            recent = list(self._snapshots[-window:])

        if not recent:
            return {
                "avg_utilization": 0.0,
                "trend": "stable",
                "growth_rate_bytes_per_sec": 0.0,
            }

        utils = [s.utilization for s in recent]
        avg_util = sum(utils) / len(utils)

        # Determine trend direction
        if len(recent) < 2:
            trend = "stable"
            growth_rate = 0.0
        else:
            first = recent[0]
            last = recent[-1]
            elapsed = last.timestamp - first.timestamp
            byte_delta = last.total_bytes - first.total_bytes

            if elapsed > 0:
                growth_rate = byte_delta / elapsed
            else:
                growth_rate = 0.0

            # Use the first-half vs second-half average to determine trend
            mid = len(utils) // 2
            first_half_avg = sum(utils[:mid]) / mid if mid > 0 else 0.0
            second_half_avg = sum(utils[mid:]) / len(utils[mid:]) if len(utils[mid:]) > 0 else 0.0
            delta = second_half_avg - first_half_avg

            if delta > 0.02:
                trend = "increasing"
            elif delta < -0.02:
                trend = "decreasing"
            else:
                trend = "stable"

        return {
            "avg_utilization": round(avg_util, 4),
            "trend": trend,
            "growth_rate_bytes_per_sec": round(growth_rate, 2),
        }

    def get_eviction_summary(self) -> dict[str, int]:
        """Count evictions grouped by reason."""
        with self._lock:
            evictions = list(self._evictions)

        summary: dict[str, int] = {}
        for ev in evictions:
            key = ev.reason or "unknown"
            summary[key] = summary.get(key, 0) + 1
        return summary

    # =========================================================================
    # Queries
    # =========================================================================

    def get_recent_snapshots(self, *, limit: int = 20) -> list[MemorySnapshot]:
        """Return the most recent snapshots (newest first)."""
        with self._lock:
            tail = self._snapshots[-limit:]
        return list(reversed(tail))

    def get_recent_evictions(self, *, limit: int = 50) -> list[EvictionEvent]:
        """Return the most recent eviction events (newest first)."""
        with self._lock:
            tail = self._evictions[-limit:]
        return list(reversed(tail))

    def get_evictions_by_source(self, source: str, *, limit: int = 50) -> list[EvictionEvent]:
        """Return recent evictions filtered by source (newest first)."""
        with self._lock:
            matched = [e for e in self._evictions if e.source == source]
        return list(reversed(matched[-limit:]))

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> PressureStats:
        """Compute aggregate pressure statistics."""
        # Get pressure level without holding lock (it acquires lock internally)
        level = self.get_pressure_level()

        with self._lock:
            total_snapshots = len(self._snapshots)
            total_evictions = len(self._evictions)
            total_bytes_freed = sum(e.bytes_freed for e in self._evictions)

            if self._snapshots:
                utils = [s.utilization for s in self._snapshots]
                avg_util = sum(utils) / len(utils)
                peak_util = max(utils)
            else:
                avg_util = 0.0
                peak_util = 0.0

        return PressureStats(
            total_snapshots=total_snapshots,
            total_evictions=total_evictions,
            total_bytes_freed=total_bytes_freed,
            current_level=level.level,
            avg_utilization=avg_util,
            peak_utilization=peak_util,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def snapshot_count(self) -> int:
        """Number of recorded snapshots."""
        return len(self._snapshots)

    @property
    def eviction_count(self) -> int:
        """Number of recorded eviction events."""
        return len(self._evictions)

    def clear(self) -> None:
        """Clear all recorded data and reset the ID counter."""
        with self._lock:
            self._snapshots.clear()
            self._evictions.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise monitor state as a dict.

        Computes stats before acquiring the lock to avoid re-entrant
        locking (get_stats -> get_pressure_level both use self._lock).
        """
        stats = self.get_stats()
        with self._lock:
            return {
                "snapshot_count": len(self._snapshots),
                "eviction_count": len(self._evictions),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_monitor: MemoryPressureMonitor | None = None
_monitor_lock = threading.Lock()


def get_pressure_monitor() -> MemoryPressureMonitor:
    """Get or create the global memory pressure monitor."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = MemoryPressureMonitor()
    return _monitor


def reset_pressure_monitor() -> None:
    """Reset the global pressure monitor (for testing)."""
    global _monitor
    _monitor = None
