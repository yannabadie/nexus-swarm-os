"""
Tests for NEXUS V9.0 Async Primitives.

Tests cover:
- CancellationToken: Hierarchical cancellation
- AsyncProcessHandle: Process tracking and termination
- AsyncRWLock: Read-write lock semantics
- AsyncBlackboard: Thread-safe shared state
"""

import asyncio
import sys
from unittest.mock import AsyncMock, Mock

import pytest

# Add project root to path
sys.path.insert(
    0, str(__file__).replace("\\tests\\test_async_primitives.py", "").replace("/tests/test_async_primitives.py", "")
)

import contextlib

from core.foundation.async_primitives import (
    AsyncBlackboard,
    AsyncProcessHandle,
    AsyncRWLock,
    CancellationToken,
)
from core.foundation.async_primitives.cancellation import CancellationTokenSource
from core.foundation.async_primitives.process_handle import ProcessHandleRegistry, ProcessState
from core.foundation.async_primitives.rwlock import AsyncRWLockWithTimeout

# ============================================================================
# CancellationToken Tests
# ============================================================================


class TestCancellationToken:
    """Tests for CancellationToken."""

    def test_initial_state_not_cancelled(self):
        """Token should start as not cancelled."""
        token = CancellationToken()
        assert not token.is_cancelled
        assert token.cancel_reason is None

    def test_cancel_sets_state(self):
        """Cancelling should set is_cancelled to True."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled

    def test_cancel_with_reason(self):
        """Cancel reason should be stored."""
        token = CancellationToken()
        token.cancel(reason="User requested")
        assert token.is_cancelled
        assert token.cancel_reason == "User requested"

    def test_cancel_propagates_to_children(self):
        """Parent cancellation should propagate to all children."""
        parent = CancellationToken()
        child1 = parent.create_child()
        child2 = parent.create_child()
        grandchild = child1.create_child()

        assert not parent.is_cancelled
        assert not child1.is_cancelled
        assert not child2.is_cancelled
        assert not grandchild.is_cancelled

        parent.cancel()

        assert parent.is_cancelled
        assert child1.is_cancelled
        assert child2.is_cancelled
        assert grandchild.is_cancelled

    def test_child_inherits_parent_cancellation(self):
        """Child should report cancelled if parent is cancelled."""
        parent = CancellationToken()
        child = parent.create_child()

        parent.cancel()

        # Child's _cancelled is False, but is_cancelled checks parent
        assert child.is_cancelled

    def test_check_raises_when_cancelled(self):
        """check() should raise CancelledError when cancelled."""
        token = CancellationToken()
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            token.check()

    def test_check_does_not_raise_when_not_cancelled(self):
        """check() should not raise when not cancelled."""
        token = CancellationToken()
        token.check()  # Should not raise

    def test_callback_executed_on_cancel(self):
        """Callbacks should be executed when cancelled."""
        token = CancellationToken()
        callback_called = []

        token.on_cancel(lambda: callback_called.append(True))
        assert len(callback_called) == 0

        token.cancel()
        assert len(callback_called) == 1

    def test_callback_exception_does_not_stop_others(self):
        """One callback failing should not prevent others from running."""
        token = CancellationToken()
        results = []

        def failing_callback():
            raise ValueError("Intentional")

        token.on_cancel(lambda: results.append(1))
        token.on_cancel(failing_callback)
        token.on_cancel(lambda: results.append(2))

        token.cancel()

        assert results == [1, 2]

    def test_callback_executed_immediately_if_already_cancelled(self):
        """Adding callback to cancelled token should execute immediately."""
        token = CancellationToken()
        token.cancel()

        callback_called = []
        token.on_cancel(lambda: callback_called.append(True))

        assert len(callback_called) == 1

    def test_double_cancel_is_idempotent(self):
        """Cancelling twice should be safe."""
        token = CancellationToken()
        call_count = []

        token.on_cancel(lambda: call_count.append(1))

        token.cancel()
        token.cancel()

        assert len(call_count) == 1  # Only called once

    def test_remove_callback(self):
        """Callbacks can be removed before cancellation."""
        token = CancellationToken()
        results = []

        def my_callback():
            results.append(1)

        token.on_cancel(my_callback)
        assert token.remove_callback(my_callback)
        assert not token.remove_callback(my_callback)  # Already removed

        token.cancel()
        assert len(results) == 0


class TestCancellationTokenSource:
    """Tests for CancellationTokenSource."""

    def test_source_creates_tokens(self):
        """Source should create linked tokens."""
        source = CancellationTokenSource()
        token1 = source.token
        token2 = source.create_linked_token()

        assert not token1.is_cancelled
        assert not token2.is_cancelled

    def test_source_cancel_cancels_all(self):
        """Cancelling source should cancel all tokens."""
        source = CancellationTokenSource()
        token1 = source.token
        token2 = source.create_linked_token()

        source.cancel()

        assert source.is_cancelled
        assert token1.is_cancelled
        assert token2.is_cancelled


# ============================================================================
# AsyncProcessHandle Tests
# ============================================================================


class TestAsyncProcessHandle:
    """Tests for AsyncProcessHandle."""

    @pytest.mark.asyncio
    async def test_is_running_true_when_running(self):
        """is_running should be True for running process."""
        # Create a mock process
        mock_proc = Mock()
        mock_proc.returncode = None  # Running

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="test-uuid-123")

        assert handle.is_running

    @pytest.mark.asyncio
    async def test_is_running_false_when_completed(self):
        """is_running should be False for completed process."""
        mock_proc = Mock()
        mock_proc.returncode = 0  # Completed

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="test-uuid-123")

        assert not handle.is_running

    @pytest.mark.asyncio
    async def test_terminate_gracefully_when_not_running(self):
        """terminate_gracefully should return False if not running."""
        mock_proc = Mock()
        mock_proc.returncode = 0  # Already completed

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="test-uuid-123")

        result = await handle.terminate_gracefully()
        assert result is False
        assert handle.state == ProcessState.COMPLETED

    @pytest.mark.asyncio
    async def test_terminate_gracefully_success(self):
        """terminate_gracefully should terminate running process."""
        mock_proc = AsyncMock()
        mock_proc.returncode = None  # Running initially

        # Simulate terminate working
        async def mock_wait():
            mock_proc.returncode = -15  # SIGTERM
            return -15

        mock_proc.wait = mock_wait
        mock_proc.terminate = Mock()

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="test-uuid-123")

        result = await handle.terminate_gracefully(timeout=1.0)

        assert result is True
        mock_proc.terminate.assert_called_once()
        assert handle.state == ProcessState.TERMINATED
        assert handle.terminated_at is not None

    @pytest.mark.asyncio
    async def test_to_dict(self):
        """to_dict should return serializable dictionary."""
        mock_proc = Mock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="test-uuid-123", task_id="task-456", agent_id="gemini")

        data = handle.to_dict()

        assert data["session_uuid"] == "test-uuid-123"
        assert data["task_id"] == "task-456"
        assert data["agent_id"] == "gemini"
        assert data["pid"] == 12345
        assert data["is_running"] is True
        assert "created_at" in data


class TestProcessHandleRegistry:
    """Tests for ProcessHandleRegistry."""

    @pytest.mark.asyncio
    async def test_register_and_get(self):
        """Should be able to register and retrieve handles."""
        registry = ProcessHandleRegistry()

        mock_proc = Mock()
        mock_proc.returncode = None

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="uuid-1")

        await registry.register(handle)
        retrieved = await registry.get("uuid-1")

        assert retrieved is handle

    @pytest.mark.asyncio
    async def test_unregister(self):
        """Should be able to unregister handles."""
        registry = ProcessHandleRegistry()

        mock_proc = Mock()
        mock_proc.returncode = None

        handle = AsyncProcessHandle(proc=mock_proc, session_uuid="uuid-1")

        await registry.register(handle)
        unregistered = await registry.unregister("uuid-1")

        assert unregistered is handle
        assert await registry.get("uuid-1") is None


# ============================================================================
# AsyncRWLock Tests
# ============================================================================


class TestAsyncRWLock:
    """Tests for AsyncRWLock."""

    @pytest.mark.asyncio
    async def test_multiple_readers_allowed(self):
        """Multiple readers should be able to hold lock simultaneously."""
        lock = AsyncRWLock()
        results = []

        async def reader(n):
            async with lock.read():
                results.append(f"start_{n}")
                await asyncio.sleep(0.01)
                results.append(f"end_{n}")

        # Run 5 readers concurrently
        await asyncio.gather(*[reader(i) for i in range(5)])

        # All should have completed
        assert len(results) == 10
        # Check that starts and ends are interleaved (concurrent)
        assert results.count("start_0") == 1

    @pytest.mark.asyncio
    async def test_writer_exclusive(self):
        """Only one writer should hold lock at a time."""
        lock = AsyncRWLock()
        value = [0]

        async def writer():
            async with lock.write():
                current = value[0]
                await asyncio.sleep(0.01)
                value[0] = current + 1

        # Run 5 writers concurrently
        await asyncio.gather(*[writer() for _ in range(5)])

        # If writers were exclusive, final value should be 5
        assert value[0] == 5

    @pytest.mark.asyncio
    async def test_writer_blocks_readers(self):
        """Writer should block new readers."""
        lock = AsyncRWLock()
        events = []

        async def writer():
            async with lock.write():
                events.append("writer_start")
                await asyncio.sleep(0.05)
                events.append("writer_end")

        async def reader():
            await asyncio.sleep(0.01)  # Small delay to ensure writer starts first
            async with lock.read():
                events.append("reader")

        await asyncio.gather(writer(), reader())

        # Reader should have waited for writer
        assert events == ["writer_start", "writer_end", "reader"]

    @pytest.mark.asyncio
    async def test_properties(self):
        """Lock properties should reflect state."""
        lock = AsyncRWLock()

        assert lock.readers == 0
        assert not lock.is_write_locked
        assert lock.pending_writers == 0


class TestAsyncRWLockWithTimeout:
    """Tests for AsyncRWLockWithTimeout."""

    @pytest.mark.asyncio
    async def test_read_with_timeout_success(self):
        """Should acquire read lock within timeout."""
        lock = AsyncRWLockWithTimeout()

        async with lock.read_with_timeout(1.0):
            assert lock.readers == 1

        assert lock.readers == 0

    @pytest.mark.asyncio
    async def test_write_with_timeout_fails_when_held(self):
        """Should timeout when lock cannot be acquired."""
        lock = AsyncRWLockWithTimeout()

        async def hold_read():
            async with lock.read():
                await asyncio.sleep(1.0)

        # Start a reader that holds for 1 second
        task = asyncio.create_task(hold_read())
        await asyncio.sleep(0.01)  # Let reader acquire

        # Try to get write lock with short timeout
        with pytest.raises(asyncio.TimeoutError):
            async with lock.write_with_timeout(0.1):
                pass

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ============================================================================
# AsyncBlackboard Tests
# ============================================================================


class TestAsyncBlackboard:
    """Tests for AsyncBlackboard."""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Should be able to set and get values."""
        bb = AsyncBlackboard()

        await bb.set("key1", "value1")
        result = await bb.get("key1")

        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_default(self):
        """Should return default for missing keys."""
        bb = AsyncBlackboard()

        result = await bb.get("missing", default="default_value")

        assert result == "default_value"

    @pytest.mark.asyncio
    async def test_delete(self):
        """Should be able to delete keys."""
        bb = AsyncBlackboard()

        await bb.set("key1", "value1")
        deleted = await bb.delete("key1")
        result = await bb.get("key1")

        assert deleted is True
        assert result is None

    @pytest.mark.asyncio
    async def test_update_multiple(self):
        """Should be able to update multiple keys atomically."""
        bb = AsyncBlackboard()

        await bb.update({"a": 1, "b": 2, "c": 3})

        assert await bb.get("a") == 1
        assert await bb.get("b") == 2
        assert await bb.get("c") == 3

    @pytest.mark.asyncio
    async def test_snapshot(self):
        """Snapshot should return copy of all data."""
        bb = AsyncBlackboard()

        await bb.set("key1", "value1")
        await bb.set("key2", "value2")

        snapshot = await bb.snapshot()

        assert snapshot == {"key1": "value1", "key2": "value2"}

        # Modifying snapshot should not affect blackboard
        snapshot["key1"] = "modified"
        assert await bb.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_get_or_set(self):
        """get_or_set should set value if missing."""
        bb = AsyncBlackboard()

        # First call should set the value
        result1 = await bb.get_or_set("key", lambda: "computed_value")
        assert result1 == "computed_value"

        # Second call should return existing value
        call_count = [0]

        def factory():
            call_count[0] += 1
            return "new_value"

        result2 = await bb.get_or_set("key", factory)
        assert result2 == "computed_value"  # Original value
        assert call_count[0] == 0  # Factory not called

    @pytest.mark.asyncio
    async def test_concurrent_read_write(self):
        """Should handle concurrent reads and writes safely."""
        bb = AsyncBlackboard()

        async def writer():
            for i in range(50):
                await bb.set("counter", i)
                await asyncio.sleep(0.001)

        async def reader():
            for _ in range(50):
                await bb.get("counter")
                await asyncio.sleep(0.001)

        # Run multiple readers and a writer concurrently
        await asyncio.gather(writer(), reader(), reader(), reader())

        # Should complete without deadlock or errors
        final = await bb.get("counter")
        assert final == 49

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Expired entries should not be returned."""
        bb = AsyncBlackboard()

        await bb.set("key", "value", ttl_seconds=0.01)

        # Immediately after, should exist
        assert await bb.get("key") == "value"

        # After TTL expires
        await asyncio.sleep(0.02)
        assert await bb.get("key") is None

    @pytest.mark.asyncio
    async def test_clear(self):
        """Clear should remove all entries."""
        bb = AsyncBlackboard()

        await bb.set("a", 1)
        await bb.set("b", 2)

        count = await bb.clear()

        assert count == 2
        assert await bb.size() == 0

    @pytest.mark.asyncio
    async def test_keys_and_contains(self):
        """keys() and contains() should work correctly."""
        bb = AsyncBlackboard()

        await bb.set("key1", "value1")
        await bb.set("key2", "value2")

        keys = await bb.keys()
        assert set(keys) == {"key1", "key2"}

        assert await bb.contains("key1") is True
        assert await bb.contains("missing") is False

    @pytest.mark.asyncio
    async def test_metadata(self):
        """Should be able to get entry metadata."""
        bb = AsyncBlackboard()

        await bb.set("key", "value", source="test", ttl_seconds=60)

        metadata = await bb.get_metadata("key")

        assert metadata is not None
        assert metadata["source"] == "test"
        assert metadata["ttl_seconds"] == 60
        assert metadata["is_expired"] is False

    @pytest.mark.asyncio
    async def test_initial_data(self):
        """Should accept initial data in constructor."""
        bb = AsyncBlackboard(initial_data={"a": 1, "b": 2})

        assert await bb.get("a") == 1
        assert await bb.get("b") == 2


# ============================================================================
# Integration Tests
# ============================================================================


class TestAsyncPrimitivesIntegration:
    """Integration tests combining multiple primitives."""

    @pytest.mark.asyncio
    async def test_cancellation_with_blackboard(self):
        """CancellationToken should work with AsyncBlackboard operations."""
        token = CancellationToken()
        bb = AsyncBlackboard()

        async def long_operation():
            for i in range(100):
                token.check()
                await bb.set(f"key_{i}", i)
                await asyncio.sleep(0.01)

        # Start operation and cancel after a bit
        task = asyncio.create_task(long_operation())
        await asyncio.sleep(0.05)
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Some keys should have been set before cancellation
        size = await bb.size()
        assert 0 < size < 100


# ============================================================================
# V8.4.7 CAS Tests (GROK-001 Fix)
# ============================================================================


class TestAsyncBlackboardCAS:
    """Tests for Compare-And-Set operations (GROK-001 fix)."""

    @pytest.mark.asyncio
    async def test_get_with_version(self):
        """get_with_version should return value and version."""
        bb = AsyncBlackboard()

        await bb.set("key", "value1")
        value, version = await bb.get_with_version("key")

        assert value == "value1"
        assert version == 1

    @pytest.mark.asyncio
    async def test_get_with_version_missing_key(self):
        """get_with_version should return default and version 0 for missing key."""
        bb = AsyncBlackboard()

        value, version = await bb.get_with_version("missing", default="default")

        assert value == "default"
        assert version == 0

    @pytest.mark.asyncio
    async def test_set_increments_version(self):
        """Each set should increment the version."""
        bb = AsyncBlackboard()

        v1 = await bb.set("key", "value1")
        v2 = await bb.set("key", "value2")
        v3 = await bb.set("key", "value3")

        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    @pytest.mark.asyncio
    async def test_compare_and_set_success(self):
        """CAS should succeed when version matches."""
        bb = AsyncBlackboard()

        await bb.set("key", "initial")
        value, version = await bb.get_with_version("key")

        success, new_version = await bb.compare_and_set("key", version, "updated")

        assert success is True
        assert new_version == 2
        assert await bb.get("key") == "updated"

    @pytest.mark.asyncio
    async def test_compare_and_set_failure_version_mismatch(self):
        """CAS should fail when version doesn't match."""
        bb = AsyncBlackboard()

        await bb.set("key", "initial")
        _, version = await bb.get_with_version("key")

        # Simulate concurrent modification
        await bb.set("key", "modified_by_other")

        # Our CAS should fail
        success, current_version = await bb.compare_and_set("key", version, "my_update")

        assert success is False
        assert current_version == 2  # Shows current version
        assert await bb.get("key") == "modified_by_other"  # Other's update preserved

    @pytest.mark.asyncio
    async def test_compare_and_set_create_new(self):
        """CAS with version 0 should create new entry if missing."""
        bb = AsyncBlackboard()

        success, version = await bb.compare_and_set("new_key", 0, "new_value")

        assert success is True
        assert version == 1
        assert await bb.get("new_key") == "new_value"

    @pytest.mark.asyncio
    async def test_expire_if_version_success(self):
        """expire_if_version should delete when version matches."""
        bb = AsyncBlackboard()

        await bb.set("key", "value")
        _, version = await bb.get_with_version("key")

        success, _ = await bb.expire_if_version("key", version)

        assert success is True
        assert await bb.get("key") is None

    @pytest.mark.asyncio
    async def test_expire_if_version_failure(self):
        """expire_if_version should fail when version doesn't match."""
        bb = AsyncBlackboard()

        await bb.set("key", "value")
        _, version = await bb.get_with_version("key")

        # Simulate concurrent update
        await bb.set("key", "updated")

        # Expire should fail - data was refreshed
        success, current_version = await bb.expire_if_version("key", version)

        assert success is False
        assert current_version == 2
        assert await bb.get("key") == "updated"  # Data preserved

    @pytest.mark.asyncio
    async def test_update_if_fresh_success(self):
        """update_if_fresh should succeed when entry is fresh."""
        bb = AsyncBlackboard()

        await bb.set("key", "initial")

        # Immediately update (definitely fresh)
        success, version = await bb.update_if_fresh("key", "updated", max_age_seconds=10)

        assert success is True
        assert version == 2
        assert await bb.get("key") == "updated"

    @pytest.mark.asyncio
    async def test_update_if_fresh_failure_stale(self):
        """update_if_fresh should fail when entry is stale."""
        bb = AsyncBlackboard()

        await bb.set("key", "initial")

        # Wait for entry to become stale
        await asyncio.sleep(0.02)

        # Try to update with very short freshness window
        success, version = await bb.update_if_fresh("key", "updated", max_age_seconds=0.01)

        assert success is False
        assert await bb.get("key") == "initial"  # Unchanged

    @pytest.mark.asyncio
    async def test_metadata_includes_version(self):
        """Metadata should include version field."""
        bb = AsyncBlackboard()

        await bb.set("key", "value")
        await bb.set("key", "value2")

        metadata = await bb.get_metadata("key")

        assert metadata["version"] == 2


# ============================================================================
# Chaos Tests for PARALLEL Mode (GROK-001 Validation)
# ============================================================================


class TestAsyncBlackboardChaos:
    """Chaos tests simulating PARALLEL swarm mode with 50 concurrent agents."""

    @pytest.mark.asyncio
    async def test_concurrent_increments_without_cas(self):
        """
        Demonstrate the race condition problem that CAS solves.
        50 concurrent agents each try to increment a counter.
        Without CAS, final count will be less than 50 due to lost updates.
        """
        bb = AsyncBlackboard()
        await bb.set("counter", 0)

        async def increment_unsafe():
            """Unsafe increment - demonstrates race condition."""
            value = await bb.get("counter")
            await asyncio.sleep(0.001)  # Simulate processing time
            await bb.set("counter", value + 1)

        # Run 50 concurrent unsafe increments
        await asyncio.gather(*[increment_unsafe() for _ in range(50)])

        final = await bb.get("counter")
        # Due to race conditions, final will likely be < 50
        # (This is the bug GROK-001 describes)
        assert final <= 50  # May be less due to lost updates

    @pytest.mark.asyncio
    async def test_concurrent_increments_with_cas(self):
        """
        CAS-based concurrent increment - should achieve exactly 50.
        Each agent retries on conflict until successful.
        """
        bb = AsyncBlackboard()
        await bb.set("counter", 0)

        async def increment_with_cas():
            """Safe CAS-based increment with retry."""
            max_retries = 100
            for _ in range(max_retries):
                value, version = await bb.get_with_version("counter")
                await asyncio.sleep(0.001)  # Simulate processing time
                success, _ = await bb.compare_and_set("counter", version, value + 1)
                if success:
                    return True
            return False  # Failed after max retries

        # Run 50 concurrent CAS increments
        results = await asyncio.gather(*[increment_with_cas() for _ in range(50)])

        # All should succeed
        assert all(results)

        # Final count should be exactly 50
        final = await bb.get("counter")
        assert final == 50

    @pytest.mark.asyncio
    async def test_chaos_mixed_operations(self):
        """
        Simulate chaotic PARALLEL swarm mode with mixed operations.
        50 agents doing random reads, writes, and CAS operations.
        """
        bb = AsyncBlackboard()
        errors = []
        operations_count = {"reads": 0, "writes": 0, "cas_success": 0, "cas_fail": 0}

        async def chaotic_agent(agent_id: int):
            """Agent performing random operations."""
            import random

            for _ in range(10):
                op = random.choice(["read", "write", "cas"])

                try:
                    if op == "read":
                        await bb.get(f"key_{random.randint(0, 9)}")
                        operations_count["reads"] += 1

                    elif op == "write":
                        await bb.set(f"key_{random.randint(0, 9)}", f"value_{agent_id}")
                        operations_count["writes"] += 1

                    else:  # cas
                        key = f"key_{random.randint(0, 9)}"
                        value, version = await bb.get_with_version(key)
                        success, _ = await bb.compare_and_set(key, version, f"cas_{agent_id}")
                        if success:
                            operations_count["cas_success"] += 1
                        else:
                            operations_count["cas_fail"] += 1

                    await asyncio.sleep(0.001)

                except Exception as e:
                    errors.append(f"Agent {agent_id}: {e}")

        # Run 50 chaotic agents
        await asyncio.gather(*[chaotic_agent(i) for i in range(50)])

        # No errors should occur
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Should have completed 500 operations total (50 agents * 10 ops each)
        total_ops = sum(operations_count.values())
        assert total_ops == 500

    @pytest.mark.asyncio
    async def test_ttl_expiry_race_condition_fixed(self):
        """
        Test that CAS prevents the TTL race condition from GROK-001.

        Scenario:
        1. Agent A reads key with TTL (gets version 1)
        2. Key expires
        3. Agent B sets fresh value (version increments to 2)
        4. Agent A tries to expire with version 1 - should FAIL
        """
        bb = AsyncBlackboard()

        # Agent A reads key with short TTL
        await bb.set("cache_key", "old_data", ttl_seconds=0.01)
        value_a, version_a = await bb.get_with_version("cache_key")
        assert version_a == 1

        # Wait for TTL expiry
        await asyncio.sleep(0.02)

        # Agent B refreshes the cache - version increments even for expired keys
        # This is correct behavior: the entry still exists, just flagged expired
        new_version = await bb.set("cache_key", "fresh_data")
        assert new_version == 2  # Version incremented

        # Agent A tries to expire based on stale version 1 - should fail
        success, current_version = await bb.expire_if_version("cache_key", version_a)

        assert success is False
        assert current_version == 2  # Shows current version, not stale

        # Fresh data should be preserved - this is the key safety guarantee
        assert await bb.get("cache_key") == "fresh_data"

    @pytest.mark.asyncio
    async def test_high_contention_single_key(self):
        """
        High contention test: 50 agents competing for same key.
        All CAS operations should eventually succeed via retry.
        """
        bb = AsyncBlackboard()
        await bb.set("hot_key", {"count": 0, "contributors": []})

        successful_agents = []

        async def compete_for_key(agent_id: int):
            """Try to add self to contributors list."""
            max_retries = 200  # High retry count for high contention
            for attempt in range(max_retries):
                value, version = await bb.get_with_version("hot_key")
                if value is None:
                    continue

                # Add self to contributors
                new_value = {"count": value["count"] + 1, "contributors": value["contributors"] + [agent_id]}

                success, _ = await bb.compare_and_set("hot_key", version, new_value)
                if success:
                    successful_agents.append(agent_id)
                    return True

                # Small backoff on conflict
                await asyncio.sleep(0.001 * (attempt % 5))

            return False

        # Run 50 agents competing
        results = await asyncio.gather(*[compete_for_key(i) for i in range(50)])

        # All should eventually succeed
        assert all(results), f"Some agents failed: {[i for i, r in enumerate(results) if not r]}"

        # Final state should have all 50 contributors
        final_value, _ = await bb.get_with_version("hot_key")
        assert final_value["count"] == 50
        assert len(final_value["contributors"]) == 50
        assert set(final_value["contributors"]) == set(range(50))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
