"""
Tests for core/async_primitives/safe_task_manager.py - V9.5

Validates fire-and-forget task error tracking.
"""

import asyncio
import contextlib
from unittest.mock import MagicMock, patch

import pytest

from core.foundation.async_primitives.safe_task_manager import (
    SafeTaskManager,
    TaskInfo,
    create_safe_task,
)


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset SafeTaskManager before each test."""
    SafeTaskManager.reset()
    yield
    SafeTaskManager.reset()


class TestSafeTaskManagerBasics:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_create_task_returns_task(self):
        """create_task should return an asyncio.Task."""

        async def dummy():
            return 42

        task = SafeTaskManager.create_task(dummy())
        assert isinstance(task, asyncio.Task)
        result = await task
        assert result == 42

    @pytest.mark.asyncio
    async def test_task_with_name(self):
        """Task should be created with specified name."""

        async def dummy():
            return "hello"

        task = SafeTaskManager.create_task(dummy(), name="test_task")
        assert task.get_name() == "test_task"
        await task

    @pytest.mark.asyncio
    async def test_create_safe_task_convenience(self):
        """create_safe_task should work as convenience function."""

        async def dummy():
            return 123

        task = create_safe_task(dummy(), name="convenience_test")
        assert isinstance(task, asyncio.Task)
        result = await task
        assert result == 123


class TestTaskTracking:
    """Task tracking tests."""

    @pytest.mark.asyncio
    async def test_active_tasks_tracked(self):
        """Active tasks should be visible in get_active_tasks."""
        event = asyncio.Event()

        async def wait_for_event():
            await event.wait()

        task = SafeTaskManager.create_task(wait_for_event(), name="waiting_task")

        # Task should be tracked
        active = SafeTaskManager.get_active_tasks()
        assert "waiting_task" in active

        # Complete the task
        event.set()
        await task

        # Task should be removed from active
        active = SafeTaskManager.get_active_tasks()
        assert "waiting_task" not in active

    @pytest.mark.asyncio
    async def test_stats_updated(self):
        """Stats should track completed and failed tasks."""

        async def success():
            return "ok"

        async def failure():
            raise ValueError("test error")

        # Run success
        task1 = SafeTaskManager.create_task(success(), name="success_task")
        await task1

        stats = SafeTaskManager.get_stats()
        assert stats["completed"] >= 1

        # Run failure
        task2 = SafeTaskManager.create_task(failure(), name="failure_task")
        with contextlib.suppress(ValueError):
            await task2

        stats = SafeTaskManager.get_stats()
        assert stats["failed"] >= 1


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_exception_logged(self):
        """Exceptions should be logged, not swallowed."""

        async def failing():
            raise RuntimeError("Test exception")

        with patch("core.foundation.async_primitives.safe_task_manager.logger") as mock_logger:
            SafeTaskManager.create_task(failing(), name="failing_task")

            # Wait for task to complete
            await asyncio.sleep(0.1)

            # Exception should be logged
            mock_logger.error.assert_called()
            call_args = str(mock_logger.error.call_args)
            assert "failing_task" in call_args or "RuntimeError" in call_args

    @pytest.mark.asyncio
    async def test_custom_error_callback(self):
        """Custom error callback should be invoked."""
        error_received = []

        def on_error(exc):
            error_received.append(exc)

        async def failing():
            raise ValueError("Custom callback test")

        SafeTaskManager.create_task(
            failing(),
            name="callback_test",
            on_error=on_error,
        )

        await asyncio.sleep(0.1)

        assert len(error_received) == 1
        assert isinstance(error_received[0], ValueError)

    @pytest.mark.asyncio
    async def test_cancelled_task_not_logged_as_error(self):
        """Cancelled tasks should not be logged as errors."""
        event = asyncio.Event()

        async def wait():
            await event.wait()

        with patch("core.foundation.async_primitives.safe_task_manager.logger") as mock_logger:
            task = SafeTaskManager.create_task(wait(), name="cancel_test")
            task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await task

            # Should not log error for cancellation
            # (debug is ok, error is not)
            for call in mock_logger.error.call_args_list:
                assert "cancel_test" not in str(call) or "cancelled" not in str(call).lower()


class TestCancelAll:
    """Test cancel_all functionality."""

    @pytest.mark.asyncio
    async def test_cancel_all_tasks(self):
        """cancel_all should cancel all active tasks."""
        events = [asyncio.Event() for _ in range(3)]

        async def wait(event):
            await event.wait()

        [SafeTaskManager.create_task(wait(e), name=f"task_{i}") for i, e in enumerate(events)]

        # All should be active
        assert len(SafeTaskManager.get_active_tasks()) == 3

        # Cancel all
        cancelled = await SafeTaskManager.cancel_all(timeout=1.0)
        assert cancelled == 3

        # All should be gone
        assert len(SafeTaskManager.get_active_tasks()) == 0


class TestSingleton:
    """Singleton pattern tests."""

    def test_same_instance(self):
        """Multiple calls should return same instance."""
        mgr1 = SafeTaskManager()
        mgr2 = SafeTaskManager()
        assert mgr1 is mgr2

    @pytest.mark.asyncio
    async def test_class_methods_use_singleton(self):
        """Class methods should use the singleton instance."""

        async def dummy():
            return 1

        # Create via class method
        task = SafeTaskManager.create_task(dummy())
        await task

        # Stats should reflect the task
        stats = SafeTaskManager.get_stats()
        assert stats["completed"] >= 1


class TestTaskInfo:
    """TaskInfo dataclass tests."""

    def test_task_info_creation(self):
        """TaskInfo should store task metadata."""
        from datetime import datetime

        mock_task = MagicMock(spec=asyncio.Task)
        info = TaskInfo(
            name="test_info",
            created_at=datetime.now(),
            task=mock_task,
        )

        assert info.name == "test_info"
        assert info.task is mock_task
        assert info.on_error is None
