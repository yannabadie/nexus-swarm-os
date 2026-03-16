"""
Performance Profiler - Execution timing and bottleneck detection.

V12.4 COGNITIVE BOOST - Task #49

Tracks execution time for FSM state transitions, swarm negotiation
latency, LLM driver calls, and arbitrary spans. Identifies bottlenecks
and generates timing reports.

Usage:
    from core.observability.telemetry.performance_profiler import get_profiler

    profiler = get_profiler()

    # Record a timed span
    with profiler.span("llm.call", tags={"model": "opus"}):
        result = call_llm(...)

    # Record state transition
    profiler.record_transition("IDLE", "BRAINSTORMING", duration_ms=12.5)

    # Get slowest operations
    report = profiler.get_report()
    print(report.slowest_spans)
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import defaultdict, deque
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_RECORDS = 10_000  # Per category
DEFAULT_PERCENTILES = (50, 90, 95, 99)


# =============================================================================
# Types
# =============================================================================


@dataclass
class TimingRecord:
    """A single timing observation."""

    category: str  # e.g. "fsm.transition", "llm.call", "swarm.negotiation"
    name: str  # e.g. "IDLE->BRAINSTORMING", "claude/opus", "ping_pong"
    duration_ms: float
    timestamp: float = 0.0
    tags: dict[str, str] = field(default_factory=dict)
    success: bool = True

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()


@dataclass
class TimingStats:
    """Aggregated statistics for a timing category+name."""

    category: str
    name: str
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0

    @property
    def success_rate(self) -> float:
        if self.count == 0:
            return 0.0
        return self.success_count / self.count

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "count": self.count,
            "total_ms": round(self.total_ms, 2),
            "min_ms": round(self.min_ms, 2) if self.min_ms != float("inf") else 0.0,
            "max_ms": round(self.max_ms, 2),
            "mean_ms": round(self.mean_ms, 2),
            "median_ms": round(self.median_ms, 2),
            "p90_ms": round(self.p90_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "success_rate": round(self.success_rate, 4),
        }


@dataclass
class Bottleneck:
    """An identified performance bottleneck."""

    category: str
    name: str
    severity: str  # "low", "medium", "high"
    reason: str
    stats: TimingStats

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "severity": self.severity,
            "reason": self.reason,
            "mean_ms": round(self.stats.mean_ms, 2),
            "p95_ms": round(self.stats.p95_ms, 2),
            "count": self.stats.count,
        }


@dataclass
class ProfileReport:
    """Complete profiling report."""

    total_records: int
    categories: list[str]
    stats: list[TimingStats]
    bottlenecks: list[Bottleneck]
    slowest_spans: list[TimingStats]
    uptime_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "categories": self.categories,
            "uptime_ms": round(self.uptime_ms, 2),
            "stats": [s.to_dict() for s in self.stats],
            "bottleneck_count": len(self.bottlenecks),
            "bottlenecks": [b.to_dict() for b in self.bottlenecks],
            "slowest_spans": [s.to_dict() for s in self.slowest_spans],
        }


# =============================================================================
# Active Span (for context manager)
# =============================================================================


@dataclass
class _ActiveSpan:
    """An in-progress timing span."""

    category: str
    name: str
    start: float
    tags: dict[str, str] = field(default_factory=dict)
    success: bool = True


# =============================================================================
# Performance Profiler
# =============================================================================


class PerformanceProfiler:
    """
    Tracks execution timing across NEXUS subsystems.

    Records timing data for:
    - FSM state transitions
    - Swarm negotiations and mode execution
    - LLM driver calls (latency per model)
    - HiveMind phase execution
    - Arbitrary spans via context manager

    Identifies bottlenecks and generates reports.
    """

    def __init__(
        self,
        *,
        max_records: int = MAX_RECORDS,
        bottleneck_threshold_ms: float = 1000.0,
        high_p95_threshold_ms: float = 5000.0,
    ):
        self._records: dict[str, deque[TimingRecord]] = defaultdict(lambda: deque(maxlen=max_records))
        self._max_records = max_records
        self._bottleneck_threshold_ms = bottleneck_threshold_ms
        self._high_p95_threshold_ms = high_p95_threshold_ms
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._total_records = 0

    # =========================================================================
    # Record Timing
    # =========================================================================

    def record(
        self,
        category: str,
        name: str,
        duration_ms: float,
        *,
        tags: dict[str, str] | None = None,
        success: bool = True,
    ) -> None:
        """
        Record a timing observation.

        Args:
            category: Category (e.g. "fsm.transition", "llm.call")
            name: Specific operation name
            duration_ms: Duration in milliseconds
            tags: Optional tags
            success: Whether the operation succeeded
        """
        record = TimingRecord(
            category=category,
            name=name,
            duration_ms=duration_ms,
            tags=tags or {},
            success=success,
        )
        key = f"{category}:{name}"
        with self._lock:
            self._records[key].append(record)
            self._total_records += 1

    def record_transition(
        self,
        from_state: str,
        to_state: str,
        duration_ms: float,
        *,
        success: bool = True,
    ) -> None:
        """Record an FSM state transition timing."""
        self.record(
            "fsm.transition",
            f"{from_state}->{to_state}",
            duration_ms,
            success=success,
        )

    def record_negotiation(
        self,
        mode: str,
        duration_ms: float,
        *,
        rounds: int = 0,
        success: bool = True,
    ) -> None:
        """Record a swarm negotiation timing."""
        self.record(
            "swarm.negotiation",
            mode,
            duration_ms,
            tags={"rounds": str(rounds)},
            success=success,
        )

    def record_driver_call(
        self,
        driver: str,
        model: str,
        duration_ms: float,
        *,
        tokens: int = 0,
        success: bool = True,
    ) -> None:
        """Record an LLM driver call timing."""
        self.record(
            "llm.call",
            f"{driver}/{model}",
            duration_ms,
            tags={"tokens": str(tokens)},
            success=success,
        )

    def record_phase(
        self,
        phase: str,
        duration_ms: float,
        *,
        success: bool = True,
    ) -> None:
        """Record a HiveMind phase timing."""
        self.record(
            "hive.phase",
            phase,
            duration_ms,
            success=success,
        )

    # =========================================================================
    # Context Manager (Span)
    # =========================================================================

    @contextmanager
    def span(
        self,
        category: str,
        name: str = "",
        *,
        tags: dict[str, str] | None = None,
    ) -> Generator[_ActiveSpan, None, None]:
        """
        Context manager for timing a block of code.

        Usage:
            with profiler.span("llm.call", "claude/opus") as s:
                result = call_llm(...)
                if not result:
                    s.success = False

        Args:
            category: Timing category
            name: Operation name (defaults to category if empty)
            tags: Optional tags
        """
        active = _ActiveSpan(
            category=category,
            name=name or category,
            start=time.monotonic(),
            tags=tags or {},
        )
        try:
            yield active
        except Exception:
            active.success = False
            raise
        finally:
            elapsed_ms = (time.monotonic() - active.start) * 1000
            self.record(
                active.category,
                active.name,
                elapsed_ms,
                tags=active.tags,
                success=active.success,
            )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self, category: str, name: str) -> TimingStats | None:
        """Get aggregated stats for a specific category+name."""
        key = f"{category}:{name}"
        with self._lock:
            records = list(self._records.get(key, []))
        if not records:
            return None
        return self._compute_stats(category, name, records)

    def get_all_stats(self) -> list[TimingStats]:
        """Get stats for all recorded categories."""
        with self._lock:
            snapshot = {k: list(v) for k, v in self._records.items()}
        results = []
        for key, records in sorted(snapshot.items()):
            cat, name = key.split(":", 1)
            results.append(self._compute_stats(cat, name, records))
        return results

    def get_category_stats(self, category: str) -> list[TimingStats]:
        """Get stats for all names within a category."""
        prefix = f"{category}:"
        with self._lock:
            snapshot = {k: list(v) for k, v in self._records.items() if k.startswith(prefix)}
        results = []
        for key, records in sorted(snapshot.items()):
            name = key[len(prefix) :]
            results.append(self._compute_stats(category, name, records))
        return results

    def _compute_stats(
        self,
        category: str,
        name: str,
        records: list[TimingRecord],
    ) -> TimingStats:
        """Compute statistics from a list of records."""
        durations = [r.duration_ms for r in records]
        sorted_d = sorted(durations)
        n = len(sorted_d)

        stats = TimingStats(
            category=category,
            name=name,
            count=n,
            total_ms=sum(durations),
            min_ms=sorted_d[0],
            max_ms=sorted_d[-1],
            mean_ms=statistics.mean(durations),
            median_ms=statistics.median(durations),
            success_count=sum(1 for r in records if r.success),
            failure_count=sum(1 for r in records if not r.success),
        )

        # Percentiles
        if n >= 2:
            stats.p90_ms = self._percentile(sorted_d, 90)
            stats.p95_ms = self._percentile(sorted_d, 95)
            stats.p99_ms = self._percentile(sorted_d, 99)
        else:
            stats.p90_ms = stats.p95_ms = stats.p99_ms = sorted_d[0]

        return stats

    @staticmethod
    def _percentile(sorted_data: list[float], pct: int) -> float:
        """Calculate percentile from sorted data."""
        n = len(sorted_data)
        idx = (pct / 100) * (n - 1)
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        return sorted_data[lower] + frac * (sorted_data[upper] - sorted_data[lower])

    # =========================================================================
    # Bottleneck Detection
    # =========================================================================

    def detect_bottlenecks(self) -> list[Bottleneck]:
        """
        Identify performance bottlenecks.

        Checks:
        - Mean duration above threshold
        - P95 above high threshold
        - High failure rate (>20%)
        """
        all_stats = self.get_all_stats()
        bottlenecks = []

        for stats in all_stats:
            if stats.count < 3:
                continue  # Not enough data

            # High mean latency
            if stats.mean_ms > self._bottleneck_threshold_ms:
                bottlenecks.append(
                    Bottleneck(
                        category=stats.category,
                        name=stats.name,
                        severity="high" if stats.mean_ms > self._high_p95_threshold_ms else "medium",
                        reason=f"High mean latency: {stats.mean_ms:.1f}ms",
                        stats=stats,
                    )
                )
            # High P95
            elif stats.p95_ms > self._high_p95_threshold_ms:
                bottlenecks.append(
                    Bottleneck(
                        category=stats.category,
                        name=stats.name,
                        severity="high",
                        reason=f"High P95 latency: {stats.p95_ms:.1f}ms",
                        stats=stats,
                    )
                )
            # High failure rate
            elif stats.success_rate < 0.8:
                bottlenecks.append(
                    Bottleneck(
                        category=stats.category,
                        name=stats.name,
                        severity="medium",
                        reason=f"High failure rate: {(1 - stats.success_rate) * 100:.1f}%",
                        stats=stats,
                    )
                )

        bottlenecks.sort(key=lambda b: b.stats.mean_ms, reverse=True)
        return bottlenecks

    # =========================================================================
    # Report
    # =========================================================================

    def get_report(self, *, top_n: int = 10) -> ProfileReport:
        """
        Generate a complete profiling report.

        Args:
            top_n: Number of slowest spans to include
        """
        all_stats = self.get_all_stats()
        categories = sorted(set(s.category for s in all_stats))
        bottlenecks = self.detect_bottlenecks()

        # Slowest by mean
        slowest = sorted(all_stats, key=lambda s: s.mean_ms, reverse=True)[:top_n]

        return ProfileReport(
            total_records=self._total_records,
            categories=categories,
            stats=all_stats,
            bottlenecks=bottlenecks,
            slowest_spans=slowest,
            uptime_ms=(time.monotonic() - self._start_time) * 1000,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def total_records(self) -> int:
        return self._total_records

    @property
    def category_count(self) -> int:
        with self._lock:
            return len(set(k.split(":")[0] for k in self._records))

    @property
    def span_count(self) -> int:
        with self._lock:
            return len(self._records)

    def get_categories(self) -> list[str]:
        """List all recorded categories."""
        with self._lock:
            return sorted(set(k.split(":")[0] for k in self._records))

    def clear(self) -> int:
        """Clear all records. Returns count cleared."""
        with self._lock:
            count = self._total_records
            self._records.clear()
            self._total_records = 0
        return count

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self._total_records,
            "category_count": self.category_count,
            "span_count": self.span_count,
            "uptime_ms": round((time.monotonic() - self._start_time) * 1000, 2),
        }


# =============================================================================
# Global Instance
# =============================================================================

_profiler: PerformanceProfiler | None = None
_profiler_lock = threading.Lock()


def get_profiler() -> PerformanceProfiler:
    """Get or create the global performance profiler."""
    global _profiler
    if _profiler is None:
        with _profiler_lock:
            if _profiler is None:
                _profiler = PerformanceProfiler()
    return _profiler


def reset_profiler() -> None:
    """Reset the global profiler (for testing)."""
    global _profiler
    _profiler = None
