"""
Handler Performance Tracker - Per-Handler-Type Execution Metrics

NEXUS V12.4 COGNITIVE BOOST - Tracks performance across tool execution handlers.

This module provides centralized tracking of execution performance for all handler types
(bash, file operations, web tools, MCP, etc.), enabling performance analysis, bottleneck
identification, and intelligent routing decisions.

Metrics Tracked:
    - Success/failure rates per handler type
    - Execution duration statistics
    - Error categorization (timeout, permission, validation, etc.)
    - Handler type comparison (slowest, most failing)
    - Recent execution history

Thread-Safety:
    Uses threading.Lock for all mutations. Global singleton with double-checked locking.

Usage:
    from core.execution_pkg.execution.handler_performance_tracker import get_handler_tracker

    tracker = get_handler_tracker()

    # Record execution
    tracker.record_execution(
        handler_type="bash",
        tool_name="pytest",
        duration_ms=1234.5,
        success=True
    )

    # Query metrics
    bash_metrics = tracker.get_handler_metrics("bash")
    print(f"Bash success rate: {bash_metrics.success_rate:.2%}")

    # Find problematic handlers
    failing = tracker.get_failing_handlers()
    slowest = tracker.get_slowest_handlers()

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Constants
MAX_EXECUTIONS: int = 50000  # FIFO eviction beyond this


@dataclass
class HandlerExecution:
    """
    Single handler execution record.

    Captures all metadata for one tool execution through a handler.
    """

    execution_id: str = ""
    handler_type: str = ""  # e.g. "bash", "file_read", "web_fetch", "mcp"
    tool_name: str = ""
    duration_ms: float = 0.0
    success: bool = True
    error_category: str = ""  # e.g. "timeout", "permission", "validation"
    timestamp: str = ""  # ISO format

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


@dataclass
class HandlerTypeMetrics:
    """
    Aggregate metrics for a single handler type.

    Computed from all executions of this handler type.
    """

    handler_type: str = ""
    total_executions: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """Ratio of successes to total executions (0.0-1.0)."""
        if self.total_executions == 0:
            return 0.0
        return self.successes / self.total_executions

    @property
    def avg_duration_ms(self) -> float:
        """Average execution duration in milliseconds."""
        if self.total_executions == 0:
            return 0.0
        return self.total_duration_ms / self.total_executions

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with computed properties."""
        base = dataclasses.asdict(self)
        base["success_rate"] = round(self.success_rate, 4)
        base["avg_duration_ms"] = round(self.avg_duration_ms, 2)
        return base


@dataclass
class TrackerStats:
    """
    Overall tracker statistics.

    Provides high-level summary of all tracked executions.
    """

    total_executions: int = 0
    unique_handler_types: int = 0
    unique_tools: int = 0
    overall_success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


class HandlerPerformanceTracker:
    """
    Centralized tracker for handler execution performance.

    Thread-safe singleton that tracks all tool handler executions with bounded history.
    Provides performance analysis and comparison capabilities.

    Features:
        - Per-handler-type metrics aggregation
        - Success rate and duration tracking
        - Error categorization
        - Recent execution history
        - Bounded FIFO history (configurable max)
        - Handler comparison (slowest, most failing)

    Thread-Safety:
        All mutations are protected by threading.Lock.
        Singleton access via get_handler_tracker() with double-checked locking.
    """

    def __init__(self, max_executions: int = MAX_EXECUTIONS):
        """
        Initialize handler performance tracker.

        Args:
            max_executions: Maximum number of executions to keep in history.
                            Oldest executions are evicted when limit is reached.
        """
        self._lock = threading.Lock()
        self._max_executions = max_executions
        self._counter = 0

        # Storage
        self._executions: deque[HandlerExecution] = deque(maxlen=max_executions)
        self._metrics_by_type: dict[str, HandlerTypeMetrics] = {}

        # Fast lookup indices
        self._tools_seen: set[str] = set()

    def record_execution(
        self,
        handler_type: str,
        tool_name: str = "",
        duration_ms: float = 0.0,
        success: bool = True,
        error_category: str = "",
    ) -> HandlerExecution:
        """
        Record a handler execution.

        Thread-safe. Updates metrics and adds to history with FIFO eviction if at max.

        Args:
            handler_type: Type of handler (e.g. "bash", "file_read", "web_fetch")
            tool_name: Specific tool name (e.g. "pytest", "glob", "curl")
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            error_category: If failed, categorize the error (e.g. "timeout", "permission")

        Returns:
            HandlerExecution: The created execution record
        """
        with self._lock:
            # Generate execution ID
            self._counter += 1
            execution_id = f"he_{self._counter:06d}"

            # Create execution record
            execution = HandlerExecution(
                execution_id=execution_id,
                handler_type=handler_type,
                tool_name=tool_name,
                duration_ms=duration_ms,
                success=success,
                error_category=error_category,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # Add to history (deque handles FIFO eviction automatically)
            self._executions.append(execution)

            # Update metrics for this handler type
            if handler_type not in self._metrics_by_type:
                self._metrics_by_type[handler_type] = HandlerTypeMetrics(handler_type=handler_type)

            metrics = self._metrics_by_type[handler_type]
            metrics.total_executions += 1
            metrics.total_duration_ms += duration_ms

            if success:
                metrics.successes += 1
            else:
                metrics.failures += 1

            # Track unique tools
            if tool_name:
                self._tools_seen.add(tool_name)

            return execution

    def get_handler_metrics(self, handler_type: str) -> HandlerTypeMetrics | None:
        """
        Get metrics for a specific handler type.

        Args:
            handler_type: Handler type to query

        Returns:
            HandlerTypeMetrics if found, None otherwise
        """
        with self._lock:
            return self._metrics_by_type.get(handler_type)

    def get_all_metrics(self) -> list[HandlerTypeMetrics]:
        """
        Get metrics for all handler types.

        Returns:
            List of HandlerTypeMetrics sorted by total_executions (descending)
        """
        with self._lock:
            metrics = list(self._metrics_by_type.values())
            return sorted(metrics, key=lambda m: m.total_executions, reverse=True)

    def get_slowest_handlers(self, limit: int = 5) -> list[HandlerTypeMetrics]:
        """
        Get slowest handler types by average duration.

        Args:
            limit: Maximum number of results

        Returns:
            List of HandlerTypeMetrics sorted by avg_duration_ms (descending)
        """
        with self._lock:
            metrics = list(self._metrics_by_type.values())
            return sorted(metrics, key=lambda m: m.avg_duration_ms, reverse=True)[:limit]

    def get_failing_handlers(self, min_executions: int = 3) -> list[HandlerTypeMetrics]:
        """
        Get handler types with high failure rates.

        Filters to handlers with success_rate < 0.8 and at least min_executions.

        Args:
            min_executions: Minimum number of executions to consider

        Returns:
            List of HandlerTypeMetrics sorted by success_rate (ascending)
        """
        with self._lock:
            metrics = [
                m
                for m in self._metrics_by_type.values()
                if m.total_executions >= min_executions and m.success_rate < 0.8
            ]
            return sorted(metrics, key=lambda m: m.success_rate)

    def get_recent_executions(self, limit: int = 10, handler_type: str | None = None) -> list[HandlerExecution]:
        """
        Get recent executions, optionally filtered by handler type.

        Args:
            limit: Maximum number of executions to return
            handler_type: If provided, filter to this handler type

        Returns:
            List of HandlerExecution (most recent first)
        """
        with self._lock:
            executions = list(self._executions)

            if handler_type:
                executions = [e for e in executions if e.handler_type == handler_type]

            # Reverse to get most recent first
            executions.reverse()
            return executions[:limit]

    def list_handler_types(self) -> list[str]:
        """
        Get list of all tracked handler types.

        Returns:
            List of handler type strings (sorted alphabetically)
        """
        with self._lock:
            return sorted(self._metrics_by_type.keys())

    def get_stats(self) -> TrackerStats:
        """
        Get overall tracker statistics.

        Returns:
            TrackerStats with aggregate metrics
        """
        with self._lock:
            total_executions = sum(m.total_executions for m in self._metrics_by_type.values())
            total_successes = sum(m.successes for m in self._metrics_by_type.values())

            overall_success_rate = 0.0
            if total_executions > 0:
                overall_success_rate = total_successes / total_executions

            return TrackerStats(
                total_executions=total_executions,
                unique_handler_types=len(self._metrics_by_type),
                unique_tools=len(self._tools_seen),
                overall_success_rate=overall_success_rate,
            )

    @property
    def execution_count(self) -> int:
        """Total number of executions tracked."""
        with self._lock:
            return len(self._executions)

    def clear(self) -> None:
        """
        Clear all tracked data.

        Thread-safe. Resets tracker to initial state.
        """
        with self._lock:
            self._executions.clear()
            self._metrics_by_type.clear()
            self._tools_seen.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """
        Convert tracker to dictionary representation.

        CRITICAL: Calls get_stats() BEFORE acquiring lock to prevent deadlock.
        Extracts data directly instead of calling locking methods.

        Returns:
            Dictionary with stats, metrics, and recent executions
        """
        # Get stats BEFORE acquiring lock (deadlock prevention)
        stats = self.get_stats()

        with self._lock:
            # Extract data directly (don't call methods that acquire lock)
            handler_types = sorted(self._metrics_by_type.keys())
            metrics = sorted(self._metrics_by_type.values(), key=lambda m: m.total_executions, reverse=True)

            return {
                "stats": stats.to_dict(),
                "handler_types": handler_types,
                "metrics": [m.to_dict() for m in metrics],
                "recent_executions": [e.to_dict() for e in list(self._executions)[-10:]],
                "execution_count": len(self._executions),
                "max_executions": self._max_executions,
            }


# Global singleton instance
_instance: HandlerPerformanceTracker | None = None
_lock = threading.Lock()


def get_handler_tracker() -> HandlerPerformanceTracker:
    """
    Get the global HandlerPerformanceTracker singleton.

    Thread-safe with double-checked locking pattern.

    Returns:
        HandlerPerformanceTracker: Global singleton instance
    """
    global _instance

    # First check (without lock for performance)
    if _instance is not None:
        return _instance

    # Second check (with lock for thread-safety)
    with _lock:
        if _instance is None:
            _instance = HandlerPerformanceTracker()
        return _instance


def reset_handler_tracker() -> None:
    """
    Reset the global HandlerPerformanceTracker singleton.

    Thread-safe. Useful for testing or reinitializing state.
    """
    global _instance

    with _lock:
        _instance = None


# Convenience exports
__all__ = [
    "HandlerExecution",
    "HandlerTypeMetrics",
    "TrackerStats",
    "HandlerPerformanceTracker",
    "get_handler_tracker",
    "reset_handler_tracker",
    "MAX_EXECUTIONS",
]
