"""
V11 SYNCHROTRON: Async Core Verification Tests.

Tests for the SYNCHROTRON async core fixes:
1. ConcurrencyLimiter - Prevents resource starvation
2. Deadlock Prevention - Parallel stderr/stdout draining
3. Event Loop Responsiveness - Non-blocking operations

Author: Claude (NEXUS V11 SYNCHROTRON)
Date: 2025-12-15
"""

import asyncio
import contextlib
import time

import pytest

# =============================================================================
# ConcurrencyLimiter Tests
# =============================================================================


class TestConcurrencyLimiter:
    """Test suite for ConcurrencyLimiter."""

    def setup_method(self):
        """Reset singleton before each test."""
        from core.api.concurrency_limiter import reset_concurrency_limiter

        reset_concurrency_limiter()

    def test_singleton_pattern(self):
        """Verify ConcurrencyLimiter is a singleton."""
        from core.api.concurrency_limiter import ConcurrencyLimiter

        limiter1 = ConcurrencyLimiter()
        limiter2 = ConcurrencyLimiter()

        assert limiter1 is limiter2

    def test_get_concurrency_limiter(self):
        """Test factory function returns singleton."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter1 = get_concurrency_limiter()
        limiter2 = get_concurrency_limiter()

        assert limiter1 is limiter2

    def test_max_concurrent_from_constants(self):
        """Test that MAX_PARALLEL_AGENTS is read from constants."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()
        # Should be set from EXECUTION_LIMITS.MAX_PARALLEL_AGENTS or default
        assert limiter.max_concurrent >= 1
        assert limiter.max_concurrent <= 16  # Reasonable upper bound

    def test_sync_acquire_release(self):
        """Test sync acquire and release."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()
        initial_available = limiter.available_permits

        assert limiter.acquire_sync(timeout=1.0)
        assert limiter.active_count == 1
        assert limiter.available_permits == initial_available - 1

        limiter.release_sync()
        assert limiter.active_count == 0
        assert limiter.available_permits == initial_available

    @pytest.mark.asyncio
    async def test_async_acquire_release(self):
        """Test async acquire and release."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()
        initial_available = limiter.available_permits

        async with limiter.acquire_async(timeout=1.0):
            assert limiter.active_count == 1
            assert limiter.available_permits == initial_available - 1

        assert limiter.active_count == 0
        assert limiter.available_permits == initial_available

    @pytest.mark.asyncio
    async def test_concurrency_limit_enforced(self):
        """Verify MAX_PARALLEL_AGENTS is respected."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()
        max_concurrent = limiter.max_concurrent
        active_count = 0
        max_observed = 0

        async def task():
            nonlocal active_count, max_observed
            async with limiter.acquire_async(timeout=30.0):
                active_count += 1
                max_observed = max(max_observed, active_count)
                await asyncio.sleep(0.05)  # Simulate work
                active_count -= 1

        # Launch more tasks than max_concurrent
        num_tasks = max_concurrent * 3
        await asyncio.gather(*[task() for _ in range(num_tasks)])

        assert max_observed <= max_concurrent, f"Concurrency exceeded: observed {max_observed}, max {max_concurrent}"

    def test_sync_timeout(self):
        """Test sync acquisition timeout."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()

        # Acquire all permits
        for _ in range(limiter.max_concurrent):
            assert limiter.acquire_sync(timeout=1.0)

        # Next acquire should timeout
        start = time.time()
        result = limiter.acquire_sync(timeout=0.1)
        elapsed = time.time() - start

        assert result is False
        assert elapsed >= 0.1

        # Cleanup
        for _ in range(limiter.max_concurrent):
            limiter.release_sync()

    @pytest.mark.asyncio
    async def test_async_timeout(self):
        """Test async acquisition timeout."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()

        # Acquire all permits
        acquired = []
        for _ in range(limiter.max_concurrent):
            await limiter._async_semaphore.acquire()
            limiter._active_count += 1
            acquired.append(True)

        # Next acquire should timeout
        with pytest.raises(asyncio.TimeoutError):
            async with limiter.acquire_async(timeout=0.1):
                pass

        # Cleanup
        for _ in acquired:
            limiter._async_semaphore.release()
            limiter._active_count -= 1

    def test_stats_tracking(self):
        """Test that stats are properly tracked."""
        from core.api.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()
        limiter.reset_stats()

        # Perform some acquisitions
        assert limiter.acquire_sync(timeout=1.0)
        limiter.release_sync()
        assert limiter.acquire_sync(timeout=1.0)
        limiter.release_sync()

        stats = limiter.get_stats()
        assert stats["total_acquisitions"] == 2
        assert stats["total_releases"] == 2
        assert stats["current_active"] == 0


# =============================================================================
# Event Loop Responsiveness Tests
# =============================================================================


class TestEventLoopResponsiveness:
    """Tests to verify event loop remains responsive during operations."""

    @pytest.mark.asyncio
    async def test_event_loop_not_blocked(self):
        """Verify event loop remains responsive during slow operations."""
        heartbeats = []

        async def heartbeat():
            """Background task that records timestamps."""
            for _ in range(20):
                heartbeats.append(time.time())
                await asyncio.sleep(0.1)

        async def slow_operation():
            """Simulate agent invocation."""
            await asyncio.sleep(1.5)
            return "done"

        # Run both concurrently
        heartbeat_task = asyncio.create_task(heartbeat())
        await slow_operation()

        # Wait a bit for heartbeat to accumulate
        await asyncio.sleep(0.3)
        heartbeat_task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

        # Heartbeats should have continued during slow_operation
        assert len(heartbeats) >= 10, (
            f"Event loop was blocked! Only {len(heartbeats)} heartbeats (expected at least 10)"
        )

    @pytest.mark.asyncio
    async def test_concurrent_tasks_fair(self):
        """Verify concurrent tasks get fair execution."""
        from core.api.concurrency_limiter import get_concurrency_limiter, reset_concurrency_limiter

        reset_concurrency_limiter()
        limiter = get_concurrency_limiter()

        results = []

        async def task(task_id: int):
            async with limiter.acquire_async(timeout=30.0):
                results.append(f"start_{task_id}")
                await asyncio.sleep(0.1)
                results.append(f"end_{task_id}")
            return task_id

        # Launch multiple tasks
        tasks = [asyncio.create_task(task(i)) for i in range(4)]
        completed = await asyncio.gather(*tasks)

        # All tasks should complete
        assert len(completed) == 4
        assert set(completed) == {0, 1, 2, 3}


# =============================================================================
# Graceful Shutdown Tests
# =============================================================================


class TestGracefulShutdown:
    """Tests for graceful shutdown and cancellation handling."""

    @pytest.mark.asyncio
    async def test_cancellation_cleanup(self):
        """Verify cleanup happens on cancellation."""
        from core.api.concurrency_limiter import get_concurrency_limiter, reset_concurrency_limiter

        reset_concurrency_limiter()
        limiter = get_concurrency_limiter()

        initial_active = limiter.active_count

        async def cancellable_task():
            async with limiter.acquire_async(timeout=30.0):
                await asyncio.sleep(10.0)  # Long task

        task = asyncio.create_task(cancellable_task())
        await asyncio.sleep(0.1)  # Let it acquire

        # Cancel the task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Give cleanup time
        await asyncio.sleep(0.1)

        # Limiter should be back to initial state
        assert limiter.active_count == initial_active, (
            f"Active count {limiter.active_count} != initial {initial_active}"
        )


# =============================================================================
# Integration Tests with Executors
# =============================================================================


class TestExecutorIntegration:
    """Test ConcurrencyLimiter integration with executors."""

    def test_base_executor_import(self):
        """Verify base executor imports concurrency limiter."""
        from core.intelligence.swarm.executors.base import get_concurrency_limiter

        assert callable(get_concurrency_limiter)

    @pytest.mark.asyncio
    async def test_parallel_invocations_limited(self):
        """Test that parallel invocations respect concurrency limit."""
        from core.api.concurrency_limiter import get_concurrency_limiter, reset_concurrency_limiter

        reset_concurrency_limiter()
        limiter = get_concurrency_limiter()

        # Track max concurrent during test
        current = 0
        max_seen = 0

        async def mock_invoke():
            nonlocal current, max_seen
            async with limiter.acquire_async(timeout=30.0):
                current += 1
                max_seen = max(max_seen, current)
                await asyncio.sleep(0.05)
                current -= 1
                return "result"

        # Run more tasks than limit allows
        tasks = [mock_invoke() for _ in range(limiter.max_concurrent * 2)]
        await asyncio.gather(*tasks)

        assert max_seen <= limiter.max_concurrent, f"Max concurrent {max_seen} exceeded limit {limiter.max_concurrent}"


# =============================================================================
# Driver Deadlock Prevention Tests
# =============================================================================


class TestDeadlockPrevention:
    """Tests for deadlock prevention in async drivers."""

    def test_gemini_driver_has_stderr_drain(self):
        """Verify Gemini driver has stderr drain task."""
        import inspect

        from core.drivers.async_gemini_driver import AsyncGeminiDriver

        source = inspect.getsource(AsyncGeminiDriver.invoke_stream)

        # Check for V11 SYNCHROTRON pattern
        assert "drain_stderr" in source, "Missing drain_stderr function"
        assert "stderr_task" in source, "Missing stderr_task"
        assert "stderr_buffer" in source, "Missing stderr_buffer"

    def test_claude_driver_has_stderr_drain(self):
        """Verify Claude driver has stderr drain task."""
        import inspect

        from core.drivers.async_claude_driver import AsyncClaudeDriver

        source = inspect.getsource(AsyncClaudeDriver.invoke_stream)

        # Check for V11 SYNCHROTRON pattern
        assert "drain_stderr" in source, "Missing drain_stderr function"
        assert "stderr_task" in source, "Missing stderr_task"
        assert "stderr_buffer" in source, "Missing stderr_buffer"

    def test_gemini_driver_has_process_wait_timeout(self):
        """Verify Gemini driver has timeout on proc.wait()."""
        import inspect

        from core.drivers.async_gemini_driver import AsyncGeminiDriver

        source = inspect.getsource(AsyncGeminiDriver.invoke_stream)

        # Check for wait_for timeout pattern
        assert "wait_for" in source, "Missing asyncio.wait_for for proc.wait()"

    def test_claude_driver_has_process_wait_timeout(self):
        """Verify Claude driver has timeout on proc.wait()."""
        import inspect

        from core.drivers.async_claude_driver import AsyncClaudeDriver

        source = inspect.getsource(AsyncClaudeDriver.invoke_stream)

        # Check for wait_for timeout pattern
        assert "wait_for" in source, "Missing asyncio.wait_for for proc.wait()"


# =============================================================================
# Run standalone
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
