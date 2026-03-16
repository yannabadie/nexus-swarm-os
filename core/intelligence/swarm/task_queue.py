"""
Task Queue Coordinator - Queue and schedule swarm tasks.

V12.4 COGNITIVE BOOST - Task #64

Manages a priority queue of swarm tasks with dependency tracking,
agent assignment, and result forwarding.

Usage:
    from core.intelligence.swarm.task_queue import get_task_queue

    queue = get_task_queue()

    # Enqueue tasks
    t1 = queue.enqueue("Analyze code", priority=2)
    t2 = queue.enqueue("Write tests", priority=1, depends_on=[t1])

    # Acquire next ready task
    task = queue.acquire()  # Returns t1 (higher priority, no deps)

    # Complete task
    queue.complete(t1, result={"findings": [...]})

    # Now t2 is unblocked
    task = queue.acquire()  # Returns t2
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_QUEUE_SIZE = 10000
DEFAULT_PRIORITY = 1


# =============================================================================
# Types
# =============================================================================


class TaskStatus(Enum):
    """Swarm task status."""

    PENDING = "pending"
    READY = "ready"
    ACQUIRED = "acquired"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SwarmTask:
    """A queued swarm task."""

    task_id: str
    description: str
    priority: int = DEFAULT_PRIORITY
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    assigned_agent: str = ""
    result: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description[:100],
            "priority": self.priority,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "assigned_agent": self.assigned_agent,
            "has_result": self.result is not None,
        }


@dataclass
class QueueStats:
    """Queue statistics."""

    total_tasks: int
    pending_count: int
    ready_count: int
    acquired_count: int
    completed_count: int
    failed_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "pending_count": self.pending_count,
            "ready_count": self.ready_count,
            "acquired_count": self.acquired_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
        }


# =============================================================================
# Task Queue
# =============================================================================


class SwarmTaskQueue:
    """
    Priority queue for swarm tasks with dependencies.

    Features:
    - Priority-based ordering (higher = more urgent)
    - Dependency tracking (task blocked until deps complete)
    - Acquire/complete lifecycle
    - Agent assignment tracking
    - Result forwarding between tasks
    - Statistics
    """

    def __init__(self, *, max_size: int = MAX_QUEUE_SIZE):
        self._tasks: dict[str, SwarmTask] = {}
        self._max_size = max_size
        self._lock = threading.Lock()

    # =========================================================================
    # Enqueue
    # =========================================================================

    def enqueue(
        self,
        description: str,
        *,
        priority: int = DEFAULT_PRIORITY,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a task to the queue.

        Args:
            description: Task description
            priority: Priority level (higher = more urgent)
            depends_on: Task IDs that must complete first
            metadata: Additional task context

        Returns:
            Task ID
        """
        task_id = uuid.uuid4().hex[:12]
        deps = depends_on or []

        # Determine initial status
        status = TaskStatus.PENDING if deps else TaskStatus.READY

        task = SwarmTask(
            task_id=task_id,
            description=description,
            priority=priority,
            status=status,
            depends_on=deps,
            metadata=metadata or {},
        )

        with self._lock:
            self._tasks[task_id] = task
            # Enforce max size
            if len(self._tasks) > self._max_size:
                self._evict_oldest_terminal()

        return task_id

    # =========================================================================
    # Acquire / Complete / Fail
    # =========================================================================

    def acquire(self, *, agent_id: str = "") -> SwarmTask | None:
        """
        Acquire the highest-priority ready task.

        Args:
            agent_id: Agent acquiring the task

        Returns:
            SwarmTask or None if no ready tasks
        """
        with self._lock:
            ready = [t for t in self._tasks.values() if t.status == TaskStatus.READY]
            if not ready:
                return None

            # Sort by priority (desc), then creation time (asc)
            ready.sort(key=lambda t: (-t.priority, t.created_at))
            task = ready[0]
            task.status = TaskStatus.ACQUIRED
            task.assigned_agent = agent_id
            return task

    def complete(
        self,
        task_id: str,
        *,
        result: Any = None,
    ) -> bool:
        """
        Mark a task as completed and unblock dependents.

        Returns True if task was found and completed.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.is_terminal:
                return False

            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = time.monotonic()

            # Unblock dependent tasks
            self._update_dependents(task_id)
        return True

    def fail(self, task_id: str, *, error: str = "") -> bool:
        """Mark a task as failed."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.is_terminal:
                return False

            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = time.monotonic()
        return True

    def cancel(self, task_id: str) -> bool:
        """Cancel a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.is_terminal:
                return False

            task.status = TaskStatus.CANCELLED
            task.completed_at = time.monotonic()
        return True

    def _update_dependents(self, completed_id: str) -> None:
        """Update tasks depending on the completed task (called under lock)."""
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if completed_id not in task.depends_on:
                continue
            # Check if all dependencies are now completed
            all_done = all(
                self._tasks.get(dep, SwarmTask(task_id="", description="")).status == TaskStatus.COMPLETED
                for dep in task.depends_on
            )
            if all_done:
                task.status = TaskStatus.READY

    # =========================================================================
    # Query
    # =========================================================================

    def get_task(self, task_id: str) -> SwarmTask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_ready_tasks(self) -> list[SwarmTask]:
        """Get all ready tasks sorted by priority."""
        ready = [t for t in self._tasks.values() if t.status == TaskStatus.READY]
        ready.sort(key=lambda t: (-t.priority, t.created_at))
        return ready

    def get_blocked_tasks(self) -> list[SwarmTask]:
        """Get tasks waiting on dependencies."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def get_result(self, task_id: str) -> Any:
        """Get result of a completed task."""
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.COMPLETED:
            return task.result
        return None

    def is_all_complete(self) -> bool:
        """Check if all tasks are in terminal state."""
        return all(t.is_terminal for t in self._tasks.values())

    # =========================================================================
    # Cleanup
    # =========================================================================

    def remove(self, task_id: str) -> bool:
        """Remove a task."""
        with self._lock:
            return self._tasks.pop(task_id, None) is not None

    def _evict_oldest_terminal(self) -> None:
        """Remove oldest terminal task (called under lock)."""
        terminals = [t for t in self._tasks.values() if t.is_terminal]
        if terminals:
            oldest = min(terminals, key=lambda t: t.created_at)
            del self._tasks[oldest.task_id]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        counts = defaultdict(int)
        for task in self._tasks.values():
            counts[task.status] += 1
        return QueueStats(
            total_tasks=len(self._tasks),
            pending_count=counts[TaskStatus.PENDING],
            ready_count=counts[TaskStatus.READY],
            acquired_count=counts[TaskStatus.ACQUIRED],
            completed_count=counts[TaskStatus.COMPLETED],
            failed_count=counts[TaskStatus.FAILED],
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def size(self) -> int:
        return len(self._tasks)

    @property
    def ready_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.READY)

    def clear(self) -> None:
        """Clear all tasks."""
        with self._lock:
            self._tasks.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_queue: SwarmTaskQueue | None = None
_queue_lock = threading.Lock()


def get_task_queue() -> SwarmTaskQueue:
    """Get or create the global task queue."""
    global _queue
    if _queue is None:
        with _queue_lock:
            if _queue is None:
                _queue = SwarmTaskQueue()
    return _queue


def reset_task_queue() -> None:
    """Reset the global task queue (for testing)."""
    global _queue
    _queue = None
