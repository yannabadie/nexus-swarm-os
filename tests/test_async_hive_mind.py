"""
Tests for NEXUS V9.0 Async Hive Mind Adapter.

Tests cover:
- AsyncHiveMindAdapter: Task execution with cancellation
- CancellationToken integration: Graceful shutdown
- AsyncBlackboard: Task status tracking
"""

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# Add project root to path
sys.path.insert(
    0, str(__file__).replace("\\tests\\test_async_hive_mind.py", "").replace("/tests/test_async_hive_mind.py", "")
)

import contextlib

from core.foundation.async_primitives import AsyncBlackboard, CancellationToken
from core.intelligence.hive_mind.async_adapter import AsyncHiveMindAdapter

# ============================================================================
# Mock HiveMind
# ============================================================================


def create_mock_hive_mind(success: bool = True, duration: float = 0.1):
    """Create a mock TrueHiveMind."""
    mock = MagicMock()

    # Create mock result
    result = MagicMock()
    result.success = success
    result.phases_completed = ["analysis", "debate", "architecture", "execution"]
    result.total_duration = duration
    result.total_tokens = 1000
    result.agents_used = ["gemini", "claude"]
    result.agents_spawned = []
    result.artifacts_created = []
    result.knowledge_archived = 5

    async def mock_process_task(task, complexity=None):
        await asyncio.sleep(0.01)  # Simulate some work
        return result

    mock.process_task = mock_process_task
    return mock


# ============================================================================
# AsyncHiveMindAdapter Tests
# ============================================================================


class TestAsyncHiveMindAdapter:
    """Tests for AsyncHiveMindAdapter."""

    @pytest.fixture
    def mock_hive_mind(self):
        """Create mock hive mind."""
        return create_mock_hive_mind()

    @pytest.fixture
    def blackboard(self):
        """Create async blackboard."""
        return AsyncBlackboard()

    @pytest.fixture
    def adapter(self, mock_hive_mind, blackboard):
        """Create adapter with mocks."""
        return AsyncHiveMindAdapter(hive_mind=mock_hive_mind, driver_factory=None, blackboard=blackboard)

    @pytest.mark.asyncio
    async def test_process_task_success(self, adapter):
        """Should process task and return result."""
        result = await adapter.process_task("Test task")

        assert result.success is True
        assert "analysis" in result.phases_completed

    @pytest.mark.asyncio
    async def test_process_task_with_session_uuid(self, adapter, blackboard):
        """Should track task in blackboard by UUID."""
        await adapter.process_task("Test task", session_uuid="test-uuid-123")

        # Check blackboard was updated
        started = await blackboard.get("task_test-uuid-123_started")
        assert started is not None

        result = await blackboard.get("task_test-uuid-123_result")
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_process_task_with_cancellation_token(self, adapter):
        """Should respect cancellation token."""
        token = CancellationToken()

        # Pre-cancel
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            await adapter.process_task("Test task", token=token)

    @pytest.mark.asyncio
    async def test_cancel_during_execution(self, blackboard):
        """Should handle cancellation during execution.

        Note: The adapter checks token.check() at start, but the actual
        HiveMind process_task is external and doesn't check the token
        internally. This test verifies pre-cancellation behavior.
        """
        # Create a slow mock that checks cancellation
        slow_mock = MagicMock()
        result = MagicMock()
        result.success = True
        result.phases_completed = ["analysis"]
        result.total_duration = 1.0
        result.total_tokens = 500
        result.agents_used = ["gemini"]
        result.agents_spawned = []
        result.artifacts_created = []
        result.knowledge_archived = 0

        cancel_token_ref = [None]

        async def slow_process(task, complexity=None):
            # Simulate checking cancellation during work
            for _i in range(5):
                await asyncio.sleep(0.02)
                if cancel_token_ref[0] and cancel_token_ref[0].is_cancelled:
                    raise asyncio.CancelledError("Cancelled during execution")
            return result

        slow_mock.process_task = slow_process

        adapter = AsyncHiveMindAdapter(hive_mind=slow_mock, blackboard=blackboard)

        token = CancellationToken()
        cancel_token_ref[0] = token

        async def cancel_after_delay():
            await asyncio.sleep(0.05)
            token.cancel()

        cancel_task = asyncio.create_task(cancel_after_delay())

        with pytest.raises(asyncio.CancelledError):
            await adapter.process_task("Test task", token=token, session_uuid="slow-task")

        cancel_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cancel_task

    @pytest.mark.asyncio
    async def test_cancel_task_by_uuid(self, adapter):
        """Should be able to cancel task by UUID."""
        token = CancellationToken()
        adapter._active_tasks["task-123"] = token

        result = await adapter.cancel_task("task-123")

        assert result is True
        assert token.is_cancelled

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, adapter):
        """Should return False for nonexistent task."""
        result = await adapter.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_all(self, adapter):
        """Should cancel all active tasks."""
        # Add some fake active tasks
        token1 = CancellationToken()
        token2 = CancellationToken()
        adapter._active_tasks["task-1"] = token1
        adapter._active_tasks["task-2"] = token2

        count = await adapter.cancel_all()

        assert count == 2
        assert token1.is_cancelled
        assert token2.is_cancelled

    @pytest.mark.asyncio
    async def test_active_task_count(self, adapter):
        """Should track active task count."""
        assert adapter.active_task_count == 0

        adapter._active_tasks["task-1"] = CancellationToken()
        adapter._active_tasks["task-2"] = CancellationToken()

        assert adapter.active_task_count == 2

    @pytest.mark.asyncio
    async def test_get_task_status(self, adapter, blackboard):
        """Should return task status from blackboard."""
        # Process a task first
        await adapter.process_task("Test task", session_uuid="status-test")

        status = await adapter.get_task_status("status-test")

        assert status is not None
        assert status["session_uuid"] == "status-test"
        assert status["completed"] is True
        assert status["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_nonexistent_task_status(self, adapter):
        """Should return None for nonexistent task."""
        status = await adapter.get_task_status("nonexistent")
        assert status is None


# ============================================================================
# Integration Tests
# ============================================================================


class TestAsyncHiveMindIntegration:
    """Integration tests for async hive mind."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_tasks(self):
        """Should handle multiple tasks concurrently."""
        mock_hive = create_mock_hive_mind()
        blackboard = AsyncBlackboard()
        adapter = AsyncHiveMindAdapter(hive_mind=mock_hive, blackboard=blackboard)

        # Run multiple tasks concurrently
        results = await asyncio.gather(
            adapter.process_task("Task 1", session_uuid="uuid-1"),
            adapter.process_task("Task 2", session_uuid="uuid-2"),
            adapter.process_task("Task 3", session_uuid="uuid-3"),
        )

        assert len(results) == 3
        assert all(r.success for r in results)

        # All should be tracked in blackboard
        for i in range(1, 4):
            result = await blackboard.get(f"task_uuid-{i}_result")
            assert result is not None

    @pytest.mark.asyncio
    async def test_blackboard_cleanup_on_cancel(self):
        """Blackboard should still have partial data on cancel."""
        cancel_token_ref = [None]
        slow_mock = MagicMock()

        async def slow_process(task, complexity=None):
            # Simulate work that checks cancellation
            for _i in range(10):
                await asyncio.sleep(0.02)
                if cancel_token_ref[0] and cancel_token_ref[0].is_cancelled:
                    raise asyncio.CancelledError("Cancelled during work")
            return MagicMock(success=True)

        slow_mock.process_task = slow_process

        blackboard = AsyncBlackboard()
        adapter = AsyncHiveMindAdapter(hive_mind=slow_mock, blackboard=blackboard)

        token = CancellationToken()
        cancel_token_ref[0] = token

        async def cancel_soon():
            await asyncio.sleep(0.05)
            token.cancel()

        asyncio.create_task(cancel_soon())

        with pytest.raises(asyncio.CancelledError):
            await adapter.process_task("Cancellable task", token=token, session_uuid="cancel-test")

        # Started timestamp should still be in blackboard
        started = await blackboard.get("task_cancel-test_started")
        assert started is not None

        # Result should NOT be set (cancelled before completion)
        result = await blackboard.get("task_cancel-test_result")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
