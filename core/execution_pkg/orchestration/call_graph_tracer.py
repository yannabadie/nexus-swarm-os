"""
Call Graph Tracer - Agent-tool call chain tracing and edge analytics.

V12.4 COGNITIVE BOOST - Traces every caller->callee interaction across
agents, tools, and the user, building a weighted directed graph of call
relationships with aggregated per-edge metrics.

Features:
- Record individual calls with caller/callee/type/duration/success
- Aggregate EdgeMetrics per unique caller->callee edge
- Fan-out / fan-in analysis per node
- Hottest-edge and failing-edge queries
- Bounded history with FIFO eviction (default 50 000 records)
- Thread-safe with threading.Lock (non-reentrant)
- Global singleton via get_call_tracer() / reset_call_tracer()

Usage:
    from core.execution_pkg.orchestration.call_graph_tracer import get_call_tracer

    tracer = get_call_tracer()
    tracer.record_call(
        caller="claude",
        callee="web_search",
        call_type="agent_to_tool",
        duration_ms=142.5,
        success=True,
        session_id="sess-001",
    )

    stats = tracer.get_stats()
    hot = tracer.get_hottest_edges(limit=5)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

MAX_CALLS: int = 50_000


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class CallRecord:
    """A single call in the graph."""

    caller: str = ""
    callee: str = ""
    call_type: str = ""  # agent_to_tool, agent_to_agent, tool_to_agent, user_to_agent
    duration_ms: float = 0.0
    success: bool = True
    session_id: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "call_type": self.call_type,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


@dataclass
class EdgeMetrics:
    """Aggregated metrics per caller->callee edge."""

    caller: str = ""
    callee: str = ""
    call_count: int = 0
    total_duration_ms: float = 0.0
    failures: int = 0

    @property
    def avg_duration_ms(self) -> float:
        if self.call_count <= 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def failure_rate(self) -> float:
        if self.call_count <= 0:
            return 0.0
        return self.failures / self.call_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "call_count": self.call_count,
            "total_duration_ms": self.total_duration_ms,
            "failures": self.failures,
            "avg_duration_ms": self.avg_duration_ms,
            "failure_rate": self.failure_rate,
        }


@dataclass
class TracerStats:
    """Overall statistics for the call graph tracer."""

    total_calls: int = 0
    unique_callers: int = 0
    unique_callees: int = 0
    unique_edges: int = 0
    overall_failure_rate: float = 0.0
    busiest_edge: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "unique_callers": self.unique_callers,
            "unique_callees": self.unique_callees,
            "unique_edges": self.unique_edges,
            "overall_failure_rate": self.overall_failure_rate,
            "busiest_edge": self.busiest_edge,
        }


# =============================================================================
# CallGraphTracer
# =============================================================================


class CallGraphTracer:
    """
    Traces agent-tool call chains and computes per-edge analytics.

    Maintains a bounded list of CallRecord entries (FIFO eviction) and
    aggregated EdgeMetrics for every unique caller->callee pair.  All
    public methods are thread-safe via a non-reentrant threading.Lock.
    """

    def __init__(self, max_calls: int = MAX_CALLS) -> None:
        self._calls: list[CallRecord] = []
        self._edges: dict[str, EdgeMetrics] = {}
        self._caller_counts: dict[str, int] = {}
        self._callee_counts: dict[str, int] = {}
        self._max_calls: int = max_calls
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_call(
        self,
        caller: str,
        callee: str,
        call_type: str = "",
        duration_ms: float = 0.0,
        success: bool = True,
        session_id: str = "",
    ) -> CallRecord:
        """
        Record a single call in the graph.

        Creates a CallRecord, updates the per-edge EdgeMetrics, and
        maintains bounded history via FIFO eviction.

        Args:
            caller: Who initiated (agent_id, tool_name, "user").
            callee: Who was called (agent_id, tool_name).
            call_type: Relationship type (agent_to_tool, etc.).
            duration_ms: Call duration in milliseconds.
            success: Whether the call succeeded.
            session_id: Session identifier.

        Returns:
            The recorded CallRecord.
        """
        record = CallRecord(
            caller=caller,
            callee=callee,
            call_type=call_type,
            duration_ms=duration_ms,
            success=success,
            session_id=session_id,
        )

        with self._lock:
            # -- edge metrics --
            edge_key = f"{caller}->{callee}"
            edge = self._edges.get(edge_key)
            if edge is None:
                edge = EdgeMetrics(caller=caller, callee=callee)
                self._edges[edge_key] = edge
            edge.call_count += 1
            edge.total_duration_ms += duration_ms
            if not success:
                edge.failures += 1

            # -- caller / callee counts --
            self._caller_counts[caller] = self._caller_counts.get(caller, 0) + 1
            self._callee_counts[callee] = self._callee_counts.get(callee, 0) + 1

            # -- FIFO eviction --
            if len(self._calls) >= self._max_calls:
                self._calls.pop(0)

            self._calls.append(record)

        return record

    # =========================================================================
    # Edge Queries
    # =========================================================================

    def get_edge_metrics(self, caller: str, callee: str) -> EdgeMetrics | None:
        """Return EdgeMetrics for a specific caller->callee pair, or None."""
        with self._lock:
            return self._edges.get(f"{caller}->{callee}")

    def get_all_edges(self) -> list[EdgeMetrics]:
        """Return all edges sorted by call_count descending."""
        with self._lock:
            edges = list(self._edges.values())
        return sorted(edges, key=lambda e: e.call_count, reverse=True)

    def get_hottest_edges(self, limit: int = 10) -> list[EdgeMetrics]:
        """Return the *limit* most-called edges."""
        return self.get_all_edges()[:limit]

    def get_failing_edges(self, min_calls: int = 3) -> list[EdgeMetrics]:
        """
        Return edges with failure_rate > 0, sorted by failure_rate descending.

        Only edges with at least *min_calls* are included.
        """
        with self._lock:
            edges = list(self._edges.values())
        return sorted(
            [e for e in edges if e.call_count >= min_calls and e.failure_rate > 0],
            key=lambda e: e.failure_rate,
            reverse=True,
        )

    # =========================================================================
    # Fan-out / Fan-in
    # =========================================================================

    def get_caller_fan_out(self, caller: str) -> list[EdgeMetrics]:
        """Return all edges originating from *caller*."""
        with self._lock:
            edges = [e for e in self._edges.values() if e.caller == caller]
        return sorted(edges, key=lambda e: e.call_count, reverse=True)

    def get_callee_fan_in(self, callee: str) -> list[EdgeMetrics]:
        """Return all edges terminating at *callee*."""
        with self._lock:
            edges = [e for e in self._edges.values() if e.callee == callee]
        return sorted(edges, key=lambda e: e.call_count, reverse=True)

    # =========================================================================
    # Call History
    # =========================================================================

    def get_recent_calls(self, limit: int = 20) -> list[CallRecord]:
        """Return the most recent *limit* call records (newest first)."""
        with self._lock:
            tail = self._calls[-limit:] if limit < len(self._calls) else list(self._calls)
        return list(reversed(tail))

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> TracerStats:
        """Compute and return overall tracer statistics."""
        with self._lock:
            total_calls = len(self._calls)
            unique_callers = len(self._caller_counts)
            unique_callees = len(self._callee_counts)
            unique_edges = len(self._edges)

            # overall failure rate
            total_failures = sum(e.failures for e in self._edges.values())
            total_edge_calls = sum(e.call_count for e in self._edges.values())
            overall_failure_rate = total_failures / total_edge_calls if total_edge_calls > 0 else 0.0

            # busiest edge
            busiest_edge = ""
            if self._edges:
                busiest = max(self._edges.values(), key=lambda e: e.call_count)
                busiest_edge = f"{busiest.caller} -> {busiest.callee}"

        return TracerStats(
            total_calls=total_calls,
            unique_callers=unique_callers,
            unique_callees=unique_callees,
            unique_edges=unique_edges,
            overall_failure_rate=overall_failure_rate,
            busiest_edge=busiest_edge,
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def call_count(self) -> int:
        """Total number of recorded calls currently held."""
        with self._lock:
            return len(self._calls)

    # =========================================================================
    # Listing
    # =========================================================================

    def list_callers(self) -> list[str]:
        """Return sorted list of unique callers."""
        with self._lock:
            return sorted(self._caller_counts.keys())

    def list_callees(self) -> list[str]:
        """Return sorted list of unique callees."""
        with self._lock:
            return sorted(self._callee_counts.keys())

    # =========================================================================
    # State
    # =========================================================================

    def clear(self) -> None:
        """Clear all recorded calls and aggregated metrics."""
        with self._lock:
            self._calls.clear()
            self._edges.clear()
            self._caller_counts.clear()
            self._callee_counts.clear()

    def to_dict(self) -> dict[str, Any]:
        """
        Serialise the tracer state to a dictionary.

        NOTE: get_stats() is called BEFORE acquiring self._lock to avoid
        reentrant locking (threading.Lock is non-reentrant).
        """
        stats = self.get_stats()

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "edges": [
                    e.to_dict()
                    for e in sorted(
                        self._edges.values(),
                        key=lambda e: e.call_count,
                        reverse=True,
                    )
                ],
                "recent_calls": [c.to_dict() for c in self._calls[-20:]],
            }


# =============================================================================
# Global Singleton
# =============================================================================

_tracer: CallGraphTracer | None = None
_tracer_lock = threading.Lock()


def get_call_tracer() -> CallGraphTracer:
    """Get or create the global CallGraphTracer (double-checked locking)."""
    global _tracer
    if _tracer is None:
        with _tracer_lock:
            if _tracer is None:
                _tracer = CallGraphTracer()
    return _tracer


def reset_call_tracer() -> None:
    """Reset the global tracer (for testing)."""
    global _tracer
    _tracer = None
