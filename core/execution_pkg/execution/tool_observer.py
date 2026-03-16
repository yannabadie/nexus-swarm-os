"""
Tool Observer - Tool execution observability with span tracking and metrics.

V12.4 COGNITIVE BOOST

Tracks tool execution spans with timing, status, error categorization,
and per-tool aggregated metrics.  Provides reporting on slowest tools,
most-failing tools, and overall success rates.

Usage:
    from core.execution_pkg.execution.tool_observer import get_tool_observer

    obs = get_tool_observer()

    # Start a span before tool execution
    span = obs.start_span("file_read", session_id="s-1", agent_id="claude")

    # End the span after execution
    obs.end_span(span, status="success")

    # Query metrics
    metric = obs.get_metric("file_read")
    report = obs.get_report()
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

MAX_SPANS = 50000
SLOW_THRESHOLD_MS = 5000.0


# =============================================================================
# Types
# =============================================================================


@dataclass
class ToolSpan:
    """A single tool execution span with timing and status."""

    tool_name: str
    session_id: str = ""
    agent_id: str = ""
    status: str = "pending"  # pending, running, success, error, timeout
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    duration_ms: float = 0.0
    error_type: str = ""  # empty, "timeout", "validation", "permission", "runtime", "unknown"
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class ToolMetric:
    """Aggregated metrics for a single tool."""

    tool_name: str
    total_calls: int = 0
    successes: int = 0
    errors: int = 0
    timeouts: int = 0
    avg_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    error_categories: dict[str, int] = field(default_factory=dict)  # error_type -> count

    @property
    def success_rate(self) -> float:
        """Fraction of calls that succeeded (0.0 - 1.0)."""
        if self.total_calls == 0:
            return 0.0
        return self.successes / self.total_calls

    @property
    def error_rate(self) -> float:
        """Fraction of calls that errored or timed out (0.0 - 1.0)."""
        if self.total_calls == 0:
            return 0.0
        return (self.errors + self.timeouts) / self.total_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "max_duration_ms": round(self.max_duration_ms, 2),
            "min_duration_ms": round(self.min_duration_ms, 2) if self.min_duration_ms != float("inf") else 0.0,
            "success_rate": round(self.success_rate, 4),
            "error_rate": round(self.error_rate, 4),
            "error_categories": dict(self.error_categories),
        }


@dataclass
class ObservationReport:
    """Summary report across all tracked tools."""

    total_spans: int
    total_tools: int
    overall_success_rate: float
    overall_avg_duration_ms: float
    slowest_tools: list[str]  # top 5 by avg duration
    most_failing_tools: list[str]  # top 5 by error rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_spans": self.total_spans,
            "total_tools": self.total_tools,
            "overall_success_rate": round(self.overall_success_rate, 4),
            "overall_avg_duration_ms": round(self.overall_avg_duration_ms, 2),
            "slowest_tools": self.slowest_tools,
            "most_failing_tools": self.most_failing_tools,
        }


@dataclass
class ToolObserverStats:
    """Lightweight statistics snapshot."""

    total_spans: int
    total_tools: int
    total_errors: int
    total_timeouts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_spans": self.total_spans,
            "total_tools": self.total_tools,
            "total_errors": self.total_errors,
            "total_timeouts": self.total_timeouts,
        }


# =============================================================================
# Tool Observer
# =============================================================================


class ToolObserver:
    """
    Observability layer for tool execution.

    Features:
    - Span-based execution tracking with start/end lifecycle
    - Per-tool aggregated metrics (running averages, min/max, error categories)
    - Slow span detection
    - Error span querying
    - Summary reports
    - Bounded history with configurable max
    - Thread-safe
    """

    def __init__(self, *, max_spans: int = MAX_SPANS):
        self._max_spans = max_spans
        self._spans: list[ToolSpan] = []
        self._metrics: dict[str, ToolMetric] = {}
        self._lock = threading.Lock()

    # =========================================================================
    # Span Lifecycle
    # =========================================================================

    def start_span(
        self,
        tool_name: str,
        *,
        session_id: str = "",
        agent_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ToolSpan:
        """
        Create and register a new execution span.

        The span starts with status="running".  If the span list is at
        capacity, the oldest span is evicted.

        Args:
            tool_name: Name of the tool being executed.
            session_id: Optional session identifier.
            agent_id: Optional agent identifier.
            metadata: Optional arbitrary metadata.

        Returns:
            The newly created ToolSpan.
        """
        span = ToolSpan(
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            status="running",
            metadata=metadata or {},
        )
        with self._lock:
            if len(self._spans) >= self._max_spans:
                self._spans.pop(0)
            self._spans.append(span)
        return span

    def end_span(
        self,
        span: ToolSpan,
        *,
        status: str = "success",
        error_type: str = "",
        error_message: str = "",
    ) -> ToolSpan:
        """
        Finalize a span and update aggregated metrics.

        Args:
            span: The span to finalize.
            status: Final status ("success", "error", "timeout").
            error_type: Error category if status is "error" or "timeout".
            error_message: Human-readable error description.

        Returns:
            The updated ToolSpan.
        """
        span.end_time = time.monotonic()
        span.duration_ms = (span.end_time - span.start_time) * 1000.0
        span.status = status
        span.error_type = error_type
        span.error_message = error_message

        with self._lock:
            self._update_metric(span)

        return span

    def _update_metric(self, span: ToolSpan) -> None:
        """Update aggregated metric for the span's tool (must hold _lock)."""
        metric = self._metrics.get(span.tool_name)
        if metric is None:
            metric = ToolMetric(tool_name=span.tool_name)
            self._metrics[span.tool_name] = metric

        metric.total_calls += 1

        if span.status == "success":
            metric.successes += 1
        elif span.status == "timeout":
            metric.timeouts += 1
        elif span.status == "error":
            metric.errors += 1

        # Running average for duration
        prev_total = metric.avg_duration_ms * (metric.total_calls - 1)
        metric.avg_duration_ms = (prev_total + span.duration_ms) / metric.total_calls

        # Min / Max
        if span.duration_ms > metric.max_duration_ms:
            metric.max_duration_ms = span.duration_ms
        if span.duration_ms < metric.min_duration_ms:
            metric.min_duration_ms = span.duration_ms

        # Error categories
        if span.error_type:
            metric.error_categories[span.error_type] = metric.error_categories.get(span.error_type, 0) + 1

    # =========================================================================
    # Metric Queries
    # =========================================================================

    def get_metric(self, tool_name: str) -> ToolMetric | None:
        """Get aggregated metric for a tool."""
        with self._lock:
            return self._metrics.get(tool_name)

    def get_all_metrics(self) -> list[ToolMetric]:
        """Get all tool metrics sorted by total_calls descending."""
        with self._lock:
            metrics = list(self._metrics.values())
        metrics.sort(key=lambda m: m.total_calls, reverse=True)
        return metrics

    # =========================================================================
    # Span Queries
    # =========================================================================

    def get_spans(
        self,
        *,
        tool_name: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ToolSpan]:
        """
        Query spans with optional filters, most recent first.

        Args:
            tool_name: Filter by tool name.
            session_id: Filter by session ID.
            status: Filter by status.
            limit: Maximum number of spans to return.

        Returns:
            Matching spans ordered most recent first.
        """
        with self._lock:
            candidates = list(reversed(self._spans))

        results: list[ToolSpan] = []
        for span in candidates:
            if tool_name is not None and span.tool_name != tool_name:
                continue
            if session_id is not None and span.session_id != session_id:
                continue
            if status is not None and span.status != status:
                continue
            results.append(span)
            if len(results) >= limit:
                break
        return results

    def get_slow_spans(
        self,
        *,
        threshold_ms: float = SLOW_THRESHOLD_MS,
        limit: int = 20,
    ) -> list[ToolSpan]:
        """
        Return spans where duration_ms exceeds the threshold.

        Args:
            threshold_ms: Duration threshold in milliseconds.
            limit: Maximum number of spans to return.

        Returns:
            Slow spans sorted by duration descending.
        """
        with self._lock:
            slow = [s for s in self._spans if s.duration_ms > threshold_ms]
        slow.sort(key=lambda s: s.duration_ms, reverse=True)
        return slow[:limit]

    def get_error_spans(
        self,
        *,
        tool_name: str | None = None,
        limit: int = 50,
    ) -> list[ToolSpan]:
        """
        Return spans with status "error" or "timeout".

        Args:
            tool_name: Optional filter by tool name.
            limit: Maximum number of spans to return.

        Returns:
            Error/timeout spans, most recent first.
        """
        with self._lock:
            candidates = list(reversed(self._spans))

        results: list[ToolSpan] = []
        for span in candidates:
            if span.status not in ("error", "timeout"):
                continue
            if tool_name is not None and span.tool_name != tool_name:
                continue
            results.append(span)
            if len(results) >= limit:
                break
        return results

    # =========================================================================
    # Reporting
    # =========================================================================

    def get_report(self) -> ObservationReport:
        """
        Compute an overall observation report.

        Returns:
            ObservationReport with overall stats, slowest tools, and
            most-failing tools.
        """
        with self._lock:
            metrics = list(self._metrics.values())
            total_spans = len(self._spans)

        total_tools = len(metrics)

        # Overall success rate
        total_calls = sum(m.total_calls for m in metrics)
        total_successes = sum(m.successes for m in metrics)
        overall_success_rate = total_successes / total_calls if total_calls > 0 else 0.0

        # Overall average duration
        if total_calls > 0:
            weighted_sum = sum(m.avg_duration_ms * m.total_calls for m in metrics)
            overall_avg_duration_ms = weighted_sum / total_calls
        else:
            overall_avg_duration_ms = 0.0

        # Top 5 slowest tools by avg duration (only tools with at least 1 call)
        by_duration = sorted(
            [m for m in metrics if m.total_calls > 0],
            key=lambda m: m.avg_duration_ms,
            reverse=True,
        )
        slowest_tools = [m.tool_name for m in by_duration[:5]]

        # Top 5 most-failing tools by error rate (only tools with errors)
        by_error = sorted(
            [m for m in metrics if m.error_rate > 0],
            key=lambda m: m.error_rate,
            reverse=True,
        )
        most_failing_tools = [m.tool_name for m in by_error[:5]]

        return ObservationReport(
            total_spans=total_spans,
            total_tools=total_tools,
            overall_success_rate=overall_success_rate,
            overall_avg_duration_ms=overall_avg_duration_ms,
            slowest_tools=slowest_tools,
            most_failing_tools=most_failing_tools,
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> ToolObserverStats:
        """Get lightweight statistics snapshot."""
        with self._lock:
            total_spans = len(self._spans)
            total_tools = len(self._metrics)
            total_errors = sum(m.errors for m in self._metrics.values())
            total_timeouts = sum(m.timeouts for m in self._metrics.values())
        return ToolObserverStats(
            total_spans=total_spans,
            total_tools=total_tools,
            total_errors=total_errors,
            total_timeouts=total_timeouts,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def span_count(self) -> int:
        """Number of tracked spans."""
        return len(self._spans)

    def clear(self) -> None:
        """Clear all spans and metrics."""
        with self._lock:
            self._spans.clear()
            self._metrics.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_count": self.span_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_observer: ToolObserver | None = None
_observer_lock = threading.Lock()


def get_tool_observer() -> ToolObserver:
    """Get or create the global tool observer."""
    global _observer
    if _observer is None:
        with _observer_lock:
            if _observer is None:
                _observer = ToolObserver()
    return _observer


def reset_tool_observer() -> None:
    """Reset the global tool observer (for testing)."""
    global _observer
    _observer = None
