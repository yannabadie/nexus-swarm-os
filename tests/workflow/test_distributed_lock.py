"""
V12.3 SCALE-OUT - Distributed Lock Tests

Tests:
- Lock acquire/release
- No-op mode (when Redis unavailable)
- Context manager usage
- Owner verification
- TTL behavior

Author: Claude (NEXUS V12.3 SCALE-OUT)
Date: 2025-12-16
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.workflow import (
    DistributedLock,
    LockAcquisitionError,
    acquire_workflow_lock,
    try_acquire_workflow_lock,
)


class TestDistributedLockNoOp:
    """Tests for no-op mode (when Redis is None)."""

    @pytest.mark.asyncio
    async def test_acquire_without_redis(self):
        """Test lock acquisition without Redis (no-op)."""
        lock = DistributedLock(redis=None, resource="test:123")

        acquired = await lock.acquire()

        assert acquired
        assert lock.is_acquired

    @pytest.mark.asyncio
    async def test_release_without_redis(self):
        """Test lock release without Redis."""
        lock = DistributedLock(redis=None, resource="test:456")
        await lock.acquire()

        released = await lock.release()

        assert released
        assert not lock.is_acquired

    @pytest.mark.asyncio
    async def test_context_manager_without_redis(self):
        """Test async context manager without Redis."""
        async with DistributedLock(redis=None, resource="ctx:test") as lock:
            assert lock.is_acquired

        assert not lock.is_acquired

    @pytest.mark.asyncio
    async def test_multiple_locks_without_redis(self):
        """Test multiple locks can be acquired without Redis."""
        lock1 = DistributedLock(redis=None, resource="multi:1")
        lock2 = DistributedLock(redis=None, resource="multi:1")  # Same resource

        assert await lock1.acquire()
        assert await lock2.acquire()  # No conflict in no-op mode


class TestDistributedLockWithMockRedis:
    """Tests with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)
        return redis

    @pytest.mark.asyncio
    async def test_acquire_success(self, mock_redis):
        """Test successful lock acquisition with Redis."""
        lock = DistributedLock(mock_redis, "test:acquire", ttl=30)

        acquired = await lock.acquire()

        assert acquired
        assert lock.is_acquired
        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args.kwargs
        assert call_kwargs["nx"]
        assert call_kwargs["ex"] == 30

    @pytest.mark.asyncio
    async def test_acquire_failure(self, mock_redis):
        """Test lock acquisition failure (already held)."""
        mock_redis.set = AsyncMock(return_value=None)  # Key exists

        lock = DistributedLock(mock_redis, "test:conflict")

        acquired = await lock.acquire()

        assert not acquired
        assert not lock.is_acquired

    @pytest.mark.asyncio
    async def test_release_success(self, mock_redis):
        """Test successful lock release."""
        lock = DistributedLock(mock_redis, "test:release")
        await lock.acquire()

        released = await lock.release()

        assert released
        assert not lock.is_acquired
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_not_acquired(self, mock_redis):
        """Test release without prior acquisition."""
        lock = DistributedLock(mock_redis, "test:no-acquire")

        released = await lock.release()

        assert not released
        mock_redis.eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_wrong_owner(self, mock_redis):
        """Test release fails if not owner."""
        mock_redis.eval = AsyncMock(return_value=0)  # Not owner

        lock = DistributedLock(mock_redis, "test:wrong-owner")
        await lock.acquire()

        released = await lock.release()

        assert not released

    @pytest.mark.asyncio
    async def test_extend_success(self, mock_redis):
        """Test TTL extension."""
        lock = DistributedLock(mock_redis, "test:extend", ttl=30)
        await lock.acquire()

        extended = await lock.extend(additional_ttl=60)

        assert extended
        mock_redis.eval.assert_called()

    @pytest.mark.asyncio
    async def test_extend_not_acquired(self, mock_redis):
        """Test extend without acquisition."""
        lock = DistributedLock(mock_redis, "test:no-extend")

        extended = await lock.extend()

        assert not extended

    @pytest.mark.asyncio
    async def test_context_manager_success(self, mock_redis):
        """Test context manager with Redis."""
        async with DistributedLock(mock_redis, "ctx:redis") as lock:
            assert lock.is_acquired

        assert not lock.is_acquired
        mock_redis.eval.assert_called()  # Release was called

    @pytest.mark.asyncio
    async def test_context_manager_acquisition_failure(self, mock_redis):
        """Test context manager raises on acquisition failure."""
        mock_redis.set = AsyncMock(return_value=None)

        with pytest.raises(LockAcquisitionError):
            async with DistributedLock(mock_redis, "ctx:fail"):
                pass


class TestDistributedLockKey:
    """Tests for lock key generation."""

    def test_key_format(self):
        """Test lock key follows expected format."""
        lock = DistributedLock(redis=None, resource="workflow:abc123")
        assert lock.key == "lock:workflow:abc123"

    def test_key_prefix(self):
        """Test KEY_PREFIX constant."""
        assert DistributedLock.KEY_PREFIX == "lock"


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @pytest.mark.asyncio
    async def test_acquire_workflow_lock_success(self):
        """Test acquire_workflow_lock convenience function."""
        lock = await acquire_workflow_lock(redis=None, workflow_id="wf-123", ttl=30)

        assert lock is not None
        assert lock.is_acquired
        assert "workflow:wf-123" in lock.key

    @pytest.mark.asyncio
    async def test_acquire_workflow_lock_failure(self):
        """Test acquire_workflow_lock raises on failure."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)

        with pytest.raises(LockAcquisitionError) as exc_info:
            await acquire_workflow_lock(mock_redis, "wf-fail")

        assert "already being processed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_try_acquire_workflow_lock_success(self):
        """Test try_acquire_workflow_lock returns lock on success."""
        lock = await try_acquire_workflow_lock(redis=None, workflow_id="wf-try")

        assert lock is not None
        assert lock.is_acquired

    @pytest.mark.asyncio
    async def test_try_acquire_workflow_lock_failure(self):
        """Test try_acquire_workflow_lock returns None on failure."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)

        lock = await try_acquire_workflow_lock(mock_redis, "wf-try-fail")

        assert lock is None


class TestGracefulDegradation:
    """Tests for graceful degradation on Redis errors."""

    @pytest.mark.asyncio
    async def test_acquire_on_redis_error(self):
        """Test acquisition succeeds on Redis error (degradation)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Connection refused"))

        lock = DistributedLock(mock_redis, "error:acquire")
        acquired = await lock.acquire()

        # Should succeed despite error (graceful degradation)
        assert acquired
        assert lock.is_acquired

    @pytest.mark.asyncio
    async def test_release_on_redis_error(self):
        """Test release handles Redis error gracefully."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(side_effect=Exception("Connection lost"))

        lock = DistributedLock(mock_redis, "error:release")
        await lock.acquire()

        released = await lock.release()

        # Should handle error gracefully
        assert not released
        assert not lock.is_acquired

    @pytest.mark.asyncio
    async def test_extend_on_redis_error(self):
        """Test extend handles Redis error gracefully."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(side_effect=Exception("Timeout"))

        lock = DistributedLock(mock_redis, "error:extend")
        await lock.acquire()

        extended = await lock.extend()

        assert not extended


class TestLockOwnership:
    """Tests for lock ownership verification."""

    def test_custom_owner_id(self):
        """Test custom owner ID is used."""
        lock = DistributedLock(
            redis=None,
            resource="owner:test",
            owner_id="my-custom-id",
        )
        assert lock._owner_id == "my-custom-id"

    def test_auto_generated_owner_id(self):
        """Test owner ID is auto-generated when not provided."""
        lock = DistributedLock(redis=None, resource="owner:auto")
        assert lock._owner_id is not None
        assert len(lock._owner_id) > 0

    def test_different_instances_different_owners(self):
        """Test different lock instances have different owner IDs."""
        lock1 = DistributedLock(redis=None, resource="owner:diff")
        lock2 = DistributedLock(redis=None, resource="owner:diff")
        assert lock1._owner_id != lock2._owner_id


class TestDefaultTTL:
    """Tests for TTL settings."""

    def test_default_ttl(self):
        """Test DEFAULT_TTL constant."""
        assert DistributedLock.DEFAULT_TTL == 30

    def test_custom_ttl(self):
        """Test custom TTL is used."""
        lock = DistributedLock(redis=None, resource="ttl:test", ttl=60)
        assert lock._ttl == 60
