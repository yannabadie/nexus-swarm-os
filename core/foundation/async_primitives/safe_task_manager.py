"""
Safe Task Manager - V9.5

Manages asyncio tasks with automatic error tracking and logging.
Prevents the "fire-and-forget" anti-pattern where task exceptions
are silently swallowed.

Usage:
    # Instead of:
    asyncio.create_task(some_coroutine())  # Errors lost!

    # Use:
    SafeTaskManager.create_task(some_coroutine(), name="my_task")

Features:
- Automatic error logging with full traceback
- Task tracking (all active tasks visible)
- Graceful cleanup on shutdown
- Optional error callbacks for custom handling

References:
- https://quantlane.com/blog/ensure-asyncio-task-exceptions-get-logged/
- Python asyncio best practices
"""

import asyncio
import logging
import traceback
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    """Metadata about a tracked task."""

    name: str
    created_at: datetime
    task: asyncio.Task
    on_error: Callable[[Exception], None] | None = None


class SafeTaskManager:
    """
    Manages fire-and-forget tasks with error tracking.

    Thread-safe singleton pattern for global task tracking.
    """

    _instance: Optional["SafeTaskManager"] = None
    _active_tasks: dict[int, TaskInfo] = {}
    _completed_count: int = 0
    _failed_count: int = 0

    def __new__(cls) -> "SafeTaskManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._active_tasks = {}
            cls._instance._completed_count = 0
            cls._instance._failed_count = 0
        return cls._instance

    @classmethod
    def create_task(
        cls,
        coro: Coroutine[Any, Any, Any],
        name: str | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> asyncio.Task:
        """
        Create an asyncio task with automatic error handling.

        Args:
            coro: The coroutine to run
            name: Optional name for debugging
            on_error: Optional callback on exception

        Returns:
            The created asyncio.Task
        """
        instance = cls()

        # Create the task
        task_name = name or f"task_{id(coro)}"
        task = asyncio.create_task(coro, name=task_name)

        # Track it
        task_info = TaskInfo(
            name=task_name,
            created_at=datetime.now(),
            task=task,
            on_error=on_error,
        )
        instance._active_tasks[id(task)] = task_info

        # Add completion callback
        task.add_done_callback(lambda t: instance._task_done_callback(t))

        logger.debug(f"SafeTaskManager: Created task '{task_name}' (active: {len(instance._active_tasks)})")
        return task

    def _task_done_callback(self, task: asyncio.Task) -> None:
        """Handle task completion - log errors if any."""
        task_id = id(task)
        task_info = self._active_tasks.pop(task_id, None)
        task_name = task_info.name if task_info else "unknown"

        if task.cancelled():
            logger.debug(f"SafeTaskManager: Task '{task_name}' was cancelled")
            return

        exception = task.exception()
        if exception:
            self._failed_count += 1

            # Log with full traceback
            tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
            logger.error(
                f"SafeTaskManager: Task '{task_name}' failed with {type(exception).__name__}: {exception}\n"
                f"Traceback:\n{tb}"
            )

            # Call custom error handler if provided
            if task_info and task_info.on_error:
                try:
                    task_info.on_error(exception)
                except Exception as callback_error:
                    logger.error(f"SafeTaskManager: Error callback for '{task_name}' also failed: {callback_error}")
        else:
            self._completed_count += 1
            logger.debug(f"SafeTaskManager: Task '{task_name}' completed successfully")

    @classmethod
    def get_active_tasks(cls) -> dict[str, TaskInfo]:
        """Get all currently active tasks."""
        instance = cls()
        return {info.name: info for info in instance._active_tasks.values()}

    @classmethod
    def get_stats(cls) -> dict[str, int]:
        """Get task statistics."""
        instance = cls()
        return {
            "active": len(instance._active_tasks),
            "completed": instance._completed_count,
            "failed": instance._failed_count,
        }

    @classmethod
    async def cancel_all(cls, timeout: float = 5.0) -> int:
        """
        Cancel all active tasks gracefully.

        Args:
            timeout: Max wait time for cancellation

        Returns:
            Number of tasks cancelled
        """
        instance = cls()
        tasks = list(instance._active_tasks.values())

        if not tasks:
            return 0

        logger.info(f"SafeTaskManager: Cancelling {len(tasks)} active tasks...")

        for task_info in tasks:
            task_info.task.cancel()

        # Wait for cancellations to complete
        await asyncio.wait(
            [t.task for t in tasks],
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        cancelled = len(tasks)
        instance._active_tasks.clear()
        logger.info(f"SafeTaskManager: Cancelled {cancelled} tasks")

        return cancelled

    @classmethod
    def reset(cls) -> None:
        """Reset the manager (for testing)."""
        if cls._instance:
            cls._instance._active_tasks.clear()
            cls._instance._completed_count = 0
            cls._instance._failed_count = 0


# Convenience function for direct import
def create_safe_task(
    coro: Coroutine[Any, Any, Any],
    name: str | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> asyncio.Task:
    """
    Convenience wrapper for SafeTaskManager.create_task().

    Usage:
        from core.foundation.async_primitives.safe_task_manager import create_safe_task

        task = create_safe_task(my_coroutine(), name="my_task")
    """
    return SafeTaskManager.create_task(coro, name=name, on_error=on_error)
