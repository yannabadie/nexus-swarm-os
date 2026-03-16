"""
Task Metrics Collector - Track async task execution metrics.

V12.4 COGNITIVE BOOST

Collects timing, status, and aggregated metrics for async task executions
across the NEXUS orchestrator.  Supports parent/child subtask tracking,
slow-task detection, and per-type aggregate statistics.

Usage:
    from core.foundation.async_primitives.task_metrics_collector import (
        get_task_metrics_collector,
    )

    collector = get_task_metrics_collector()

    # Start a task
    record = collector.start_task("tool_execution", parent_task_id="parent_001")

    # Complete it
    collector.complete_task(record.task_id)

    # Or mark failure
    collector.fail_task(record.task_id, error="Timeout exceeded")

    # Query metrics
    stats = collector.get_stats()
    slow = collector.get_slow_tasks(limit=10)
    by_type = collector.get_type_metrics("tool_execution")
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

MAX_TASK_RECORDS = 50000
SLOW_TASK_THRESHOLD_MS = 5000.0


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class TaskRecord:
    """Record of a single async task execution."""

    task_id: str = ""
    task_type: str = ""
    status: str = "pending"
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0
    error: str = ""
    parent_task_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    @property
    def is_slow(self) -> bool:
        """Whether this task exceeded the slow-task threshold."""
        return self.duration_ms > SLOW_TASK_THRESHOLD_MS

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "parent_task_id": self.parent_task_id,
            "metadata": self.metadata,
            "is_slow": self.is_slow,
        }


@dataclass
class TaskTypeMetrics:
    """Aggregated metrics for a single task type."""

    task_type: str = ""
    total_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = 0.0
    max_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        """Average duration across completed tasks."""
        if self.completed_count > 0:
            return self.total_duration_ms / self.completed_count
        return 0.0

    @property
    def success_rate(self) -> float:
        """Fraction of tasks that completed successfully."""
        if self.total_count > 0:
            return self.completed_count / self.total_count
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "total_count": self.total_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "total_duration_ms": self.total_duration_ms,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "success_rate": round(self.success_rate, 4),
        }


@dataclass
class CollectorStats:
    """Overall collector statistics."""

    total_tasks: int = 0
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    unique_task_types: int = 0
    avg_duration_ms: float = 0.0
    slow_task_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "active_tasks": self.active_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "unique_task_types": self.unique_task_types,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "slow_task_count": self.slow_task_count,
        }


# =============================================================================
# Task Metrics Collector
# =============================================================================


class TaskMetricsCollector:
    """
    Collects and aggregates async task execution metrics.

    Features:
    - Per-task timing with auto-generated IDs
    - Per-type aggregate statistics (count, duration, success rate)
    - Active task tracking for in-flight operations
    - Slow-task detection above configurable threshold
    - Parent/child subtask relationships
    - Bounded history with FIFO eviction
    - Thread-safe via threading.Lock()
    """

    def __init__(self, max_records: int = MAX_TASK_RECORDS):
        self._records: list[TaskRecord] = []
        self._type_metrics: dict[str, TaskTypeMetrics] = {}
        self._active_tasks: dict[str, TaskRecord] = {}
        self._max_records = max_records
        self._lock = threading.Lock()
        self._counter = 0

    # =========================================================================
    # Task Lifecycle
    # =========================================================================

    def start_task(
        self,
        task_type: str,
        task_id: str = "",
        parent_task_id: str = "",
        **metadata: Any,
    ) -> TaskRecord:
        """Start tracking a new task.

        Generates a ``task_NNNNNN`` identifier when *task_id* is empty.
        Initialises per-type metrics on first encounter.
        """
        now = datetime.now(UTC).isoformat()
        with self._lock:
            if not task_id:
                self._counter += 1
                task_id = f"task_{self._counter:06d}"

            record = TaskRecord(
                task_id=task_id,
                task_type=task_type,
                status="running",
                created_at=now,
                started_at=now,
                parent_task_id=parent_task_id,
                metadata=dict(metadata) if metadata else {},
            )
            self._active_tasks[task_id] = record

            if task_type not in self._type_metrics:
                self._type_metrics[task_type] = TaskTypeMetrics(
                    task_type=task_type,
                )
            self._type_metrics[task_type].total_count += 1

        return record

    def complete_task(self, task_id: str, **metadata: Any) -> TaskRecord | None:
        """Mark a running task as completed and record its duration."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        with self._lock:
            record = self._active_tasks.pop(task_id, None)
            if record is None:
                return None

            record.status = "completed"
            record.completed_at = now_iso
            if record.started_at:
                started = datetime.fromisoformat(record.started_at)
                record.duration_ms = (now - started).total_seconds() * 1000.0
            if metadata:
                record.metadata.update(metadata)

            # Update type metrics
            tm = self._type_metrics.get(record.task_type)
            if tm is not None:
                tm.completed_count += 1
                tm.total_duration_ms += record.duration_ms
                if tm.completed_count == 1:
                    tm.min_duration_ms = record.duration_ms
                    tm.max_duration_ms = record.duration_ms
                else:
                    if record.duration_ms < tm.min_duration_ms:
                        tm.min_duration_ms = record.duration_ms
                    if record.duration_ms > tm.max_duration_ms:
                        tm.max_duration_ms = record.duration_ms

            # Append to history with FIFO eviction
            if len(self._records) >= self._max_records:
                self._records.pop(0)
            self._records.append(record)

        return record

    def fail_task(
        self,
        task_id: str,
        error: str = "",
        **metadata: Any,
    ) -> TaskRecord | None:
        """Mark a running task as failed and record its duration."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        with self._lock:
            record = self._active_tasks.pop(task_id, None)
            if record is None:
                return None

            record.status = "failed"
            record.completed_at = now_iso
            record.error = error
            if record.started_at:
                started = datetime.fromisoformat(record.started_at)
                record.duration_ms = (now - started).total_seconds() * 1000.0
            if metadata:
                record.metadata.update(metadata)

            # Update type metrics
            tm = self._type_metrics.get(record.task_type)
            if tm is not None:
                tm.failed_count += 1

            # Append to history with FIFO eviction
            if len(self._records) >= self._max_records:
                self._records.pop(0)
            self._records.append(record)

        return record

    def cancel_task(self, task_id: str) -> TaskRecord | None:
        """Mark a running task as cancelled."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        with self._lock:
            record = self._active_tasks.pop(task_id, None)
            if record is None:
                return None

            record.status = "cancelled"
            record.completed_at = now_iso
            if record.started_at:
                started = datetime.fromisoformat(record.started_at)
                record.duration_ms = (now - started).total_seconds() * 1000.0

            # Update type metrics
            tm = self._type_metrics.get(record.task_type)
            if tm is not None:
                tm.cancelled_count += 1

            # Append to history with FIFO eviction
            if len(self._records) >= self._max_records:
                self._records.pop(0)
            self._records.append(record)

        return record

    # =========================================================================
    # Queries
    # =========================================================================

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Look up a task by ID in active tasks then completed history."""
        with self._lock:
            record = self._active_tasks.get(task_id)
            if record is not None:
                return record
            for rec in reversed(self._records):
                if rec.task_id == task_id:
                    return rec
        return None

    def get_type_metrics(self, task_type: str) -> TaskTypeMetrics | None:
        """Return aggregated metrics for a specific task type."""
        with self._lock:
            return self._type_metrics.get(task_type)

    def get_all_metrics(self) -> list[TaskTypeMetrics]:
        """Return all per-type metrics sorted by total_count descending."""
        with self._lock:
            metrics = list(self._type_metrics.values())
        return sorted(metrics, key=lambda m: m.total_count, reverse=True)

    def get_slow_tasks(self, limit: int = 20) -> list[TaskRecord]:
        """Return completed tasks whose duration exceeded the slow threshold."""
        with self._lock:
            slow = [r for r in self._records if r.is_slow]
        slow.sort(key=lambda r: r.duration_ms, reverse=True)
        return slow[:limit]

    def get_recent_tasks(self, limit: int = 20) -> list[TaskRecord]:
        """Return the most recent completed/failed/cancelled records."""
        with self._lock:
            return list(self._records[-limit:])

    def get_subtasks(self, parent_task_id: str) -> list[TaskRecord]:
        """Return all records that belong to a given parent task."""
        with self._lock:
            return [r for r in self._records if r.parent_task_id == parent_task_id]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> CollectorStats:
        """Compute overall collector statistics."""
        with self._lock:
            total = len(self._records)
            active = len(self._active_tasks)
            completed = sum(1 for r in self._records if r.status == "completed")
            failed = sum(1 for r in self._records if r.status == "failed")
            cancelled = sum(1 for r in self._records if r.status == "cancelled")
            unique = len(self._type_metrics)
            slow = sum(1 for r in self._records if r.is_slow)

            durations = [r.duration_ms for r in self._records if r.status == "completed"]
            avg_dur = sum(durations) / len(durations) if durations else 0.0

        return CollectorStats(
            total_tasks=total,
            active_tasks=active,
            completed_tasks=completed,
            failed_tasks=failed,
            cancelled_tasks=cancelled,
            unique_task_types=unique,
            avg_duration_ms=avg_dur,
            slow_task_count=slow,
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def task_count(self) -> int:
        """Number of completed/failed/cancelled records in history."""
        return len(self._records)

    @property
    def active_count(self) -> int:
        """Number of currently running tasks."""
        return len(self._active_tasks)

    # =========================================================================
    # State Management
    # =========================================================================

    def clear(self) -> None:
        """Reset all state and counters."""
        with self._lock:
            self._records.clear()
            self._type_metrics.clear()
            self._active_tasks.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise collector state as a dict.

        Computes stats before acquiring the lock to avoid re-entrant
        locking (get_stats acquires self._lock internally).
        """
        stats = self.get_stats()
        with self._lock:
            return {
                "max_records": self._max_records,
                "task_count": len(self._records),
                "active_count": len(self._active_tasks),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Singleton
# =============================================================================

_global_collector: TaskMetricsCollector | None = None
_global_lock = threading.Lock()


def get_task_metrics_collector() -> TaskMetricsCollector:
    """Get or create the global task metrics collector."""
    global _global_collector
    if _global_collector is None:
        with _global_lock:
            if _global_collector is None:
                _global_collector = TaskMetricsCollector()
    return _global_collector


def reset_task_metrics_collector() -> None:
    """Reset the global task metrics collector (for testing)."""
    global _global_collector
    with _global_lock:
        _global_collector = None
