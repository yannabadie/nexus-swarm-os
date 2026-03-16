"""
Task Priority Scheduler - Priority-based task queue with urgency scoring.

V12.4 COGNITIVE BOOST - Task #39

Manages task ordering by priority level, deadline proximity, and dependencies.
Used by the orchestrator to decide which task to execute next when multiple
tasks are pending.

Priority Scoring:
- Base priority (CRITICAL=100, HIGH=75, MEDIUM=50, LOW=25, BACKGROUND=10)
- Deadline urgency bonus (exponential as deadline approaches)
- Age bonus (tasks waiting longer get slight priority boost)
- Dependency penalty (blocked tasks score 0)

Usage:
    from core.execution_pkg.execution.task_scheduler import TaskScheduler, ScheduledTask, Priority

    scheduler = TaskScheduler()
    scheduler.submit("fix_bug", priority=Priority.HIGH, deadline_seconds=300)
    scheduler.submit("cleanup", priority=Priority.LOW)

    next_task = scheduler.next()  # Returns highest-priority task
    scheduler.complete(next_task.task_id)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


class Priority(Enum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"


class TaskStatus(Enum):
    """Task lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# Priority base scores
PRIORITY_SCORES: dict[Priority, float] = {
    Priority.CRITICAL: 100.0,
    Priority.HIGH: 75.0,
    Priority.MEDIUM: 50.0,
    Priority.LOW: 25.0,
    Priority.BACKGROUND: 10.0,
}

# Deadline urgency settings
DEADLINE_URGENCY_WEIGHT = 50.0  # Max bonus for deadline proximity
AGE_WEIGHT = 0.1  # Score per second of waiting


@dataclass
class ScheduledTask:
    """A task in the scheduling queue."""

    task_id: str
    name: str
    priority: Priority = Priority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = 0.0  # monotonic time
    deadline_at: float | None = None  # monotonic time
    started_at: float | None = None
    completed_at: float | None = None
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    result: str | None = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    @property
    def age_seconds(self) -> float:
        """Time since task was created."""
        return time.monotonic() - self.created_at

    @property
    def is_terminal(self) -> bool:
        """Whether task is in a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def is_overdue(self) -> bool:
        """Whether task has passed its deadline."""
        if self.deadline_at is None:
            return False
        return time.monotonic() > self.deadline_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "priority": self.priority.value,
            "status": self.status.value,
            "age_seconds": round(self.age_seconds, 2),
            "is_overdue": self.is_overdue,
            "depends_on": self.depends_on,
            "metadata": self.metadata,
        }


# =============================================================================
# Task Scheduler
# =============================================================================


class TaskScheduler:
    """
    Priority-based task scheduler with deadline urgency and dependency tracking.

    Tasks are scored using a composite formula:
    - Base priority score (10-100)
    - Deadline urgency bonus (exponential as deadline nears)
    - Age bonus (older waiting tasks get slight boost)
    - Blocked tasks always score 0

    Thread-safe for concurrent access.
    """

    def __init__(
        self,
        *,
        deadline_urgency_weight: float = DEADLINE_URGENCY_WEIGHT,
        age_weight: float = AGE_WEIGHT,
        max_queue_size: int = 1000,
    ):
        """
        Initialize the scheduler.

        Args:
            deadline_urgency_weight: Max bonus for deadline proximity
            age_weight: Score per second of waiting
            max_queue_size: Maximum pending tasks
        """
        self._deadline_weight = deadline_urgency_weight
        self._age_weight = age_weight
        self._max_queue_size = max_queue_size
        self._lock = Lock()
        self._tasks: dict[str, ScheduledTask] = {}

    def submit(
        self,
        name: str,
        *,
        priority: Priority = Priority.MEDIUM,
        deadline_seconds: float | None = None,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> ScheduledTask:
        """
        Submit a task to the scheduler.

        Args:
            name: Task name/description
            priority: Priority level
            deadline_seconds: Seconds from now until deadline (None = no deadline)
            depends_on: Task IDs that must complete first
            metadata: Arbitrary metadata
            task_id: Custom task ID (auto-generated if None)

        Returns:
            The scheduled task

        Raises:
            ValueError: If queue is full or task_id already exists
        """
        with self._lock:
            pending = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
            if pending >= self._max_queue_size:
                raise ValueError(f"Queue full ({self._max_queue_size} pending tasks)")

            tid = task_id or uuid.uuid4().hex[:12]
            if tid in self._tasks:
                raise ValueError(f"Task '{tid}' already exists")

            now = time.monotonic()
            deadline = now + deadline_seconds if deadline_seconds else None

            # Check dependency validity
            deps = depends_on or []
            for dep_id in deps:
                if dep_id not in self._tasks:
                    raise ValueError(f"Dependency '{dep_id}' not found")

            task = ScheduledTask(
                task_id=tid,
                name=name,
                priority=priority,
                status=TaskStatus.PENDING,
                created_at=now,
                deadline_at=deadline,
                depends_on=deps,
                metadata=metadata or {},
            )

            # Auto-block if dependencies aren't complete
            if deps and not self._deps_satisfied(deps):
                task.status = TaskStatus.BLOCKED

            self._tasks[tid] = task
            return task

    def next(self) -> ScheduledTask | None:
        """
        Get the highest-priority pending task.

        Returns:
            The next task to execute, or None if queue is empty
        """
        with self._lock:
            self._update_blocked_states()

            candidates = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

            if not candidates:
                return None

            # Sort by score descending
            candidates.sort(key=lambda t: self._score_task(t), reverse=True)
            return candidates[0]

    def start(self, task_id: str) -> bool:
        """
        Mark a task as running.

        Args:
            task_id: Task to start

        Returns:
            True if status changed
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != TaskStatus.PENDING:
                return False
            task.status = TaskStatus.RUNNING
            task.started_at = time.monotonic()
            return True

    def complete(self, task_id: str, result: str | None = None) -> bool:
        """
        Mark a task as completed.

        Args:
            task_id: Task to complete
            result: Optional result string

        Returns:
            True if status changed
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.is_terminal:
                return False
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.monotonic()
            task.result = result
            self._update_blocked_states()
            return True

    def fail(self, task_id: str, error: str | None = None) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: Task to fail
            error: Error description

        Returns:
            True if status changed
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.is_terminal:
                return False
            task.status = TaskStatus.FAILED
            task.completed_at = time.monotonic()
            task.result = error
            return True

    def cancel(self, task_id: str) -> bool:
        """
        Cancel a task.

        Args:
            task_id: Task to cancel

        Returns:
            True if status changed
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.is_terminal:
                return False
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.monotonic()
            return True

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
    ) -> list[ScheduledTask]:
        """
        List tasks, optionally filtered by status.

        Args:
            status: Filter by status (None = all)

        Returns:
            List of tasks sorted by score
        """
        with self._lock:
            if status:
                tasks = [t for t in self._tasks.values() if t.status == status]
            else:
                tasks = list(self._tasks.values())
            tasks.sort(key=lambda t: self._score_task(t), reverse=True)
            return tasks

    def pending_count(self) -> int:
        """Get number of pending tasks."""
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)

    def running_count(self) -> int:
        """Get number of running tasks."""
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)

    def overdue_tasks(self) -> list[ScheduledTask]:
        """Get tasks that have passed their deadline."""
        with self._lock:
            return [t for t in self._tasks.values() if t.is_overdue and not t.is_terminal]

    def clear_completed(self) -> int:
        """
        Remove all completed/failed/cancelled tasks.

        Returns:
            Number of tasks removed
        """
        with self._lock:
            to_remove = [tid for tid, t in self._tasks.items() if t.is_terminal]
            for tid in to_remove:
                del self._tasks[tid]
            return len(to_remove)

    def to_dict(self) -> dict[str, Any]:
        """Export scheduler state."""
        with self._lock:
            by_status = {}
            for t in self._tasks.values():
                s = t.status.value
                by_status[s] = by_status.get(s, 0) + 1

            return {
                "total_tasks": len(self._tasks),
                "by_status": by_status,
                "pending_count": by_status.get("pending", 0),
                "running_count": by_status.get("running", 0),
                "max_queue_size": self._max_queue_size,
            }

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _score_task(self, task: ScheduledTask) -> float:
        """Calculate composite priority score for a task."""
        if task.status == TaskStatus.BLOCKED:
            return 0.0

        if task.is_terminal:
            return -1.0

        # Base priority
        score = PRIORITY_SCORES.get(task.priority, 50.0)

        # Deadline urgency: exponential increase as deadline approaches
        if task.deadline_at is not None:
            remaining = task.deadline_at - time.monotonic()
            if remaining <= 0:
                # Overdue: maximum urgency
                score += self._deadline_weight
            else:
                # Urgency increases as deadline nears
                # At 10s remaining: near max bonus
                # At 60s: moderate bonus
                urgency = self._deadline_weight * (1.0 / (1.0 + remaining / 10.0))
                score += urgency

        # Age bonus: slight increase for waiting tasks
        score += task.age_seconds * self._age_weight

        return score

    def _deps_satisfied(self, depends_on: list[str]) -> bool:
        """Check if all dependencies are completed."""
        for dep_id in depends_on:
            dep = self._tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def _update_blocked_states(self) -> None:
        """Update blocked/unblocked status based on dependencies."""
        for task in self._tasks.values():
            if task.status == TaskStatus.BLOCKED:
                if self._deps_satisfied(task.depends_on):
                    task.status = TaskStatus.PENDING
            elif task.status == TaskStatus.PENDING and task.depends_on and not self._deps_satisfied(task.depends_on):
                task.status = TaskStatus.BLOCKED
