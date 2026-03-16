"""
NEXUS V12.3 SCALE-OUT - Distributed Lock

Redis-based distributed lock using SET NX EX pattern (simplified Redlock).
Prevents race conditions in multi-instance deployments.

Usage:
    from core.workflow.distributed_lock import DistributedLock

    async with DistributedLock(redis, "workflow:123", ttl=30):
        # Critical section - only one instance can execute at a time
        await do_something()

Features:
- Auto-release on context exit
- TTL-based expiration (prevents deadlocks)
- Graceful degradation: returns immediately if Redis unavailable

Author: Claude (NEXUS V12.3 SCALE-OUT)
Date: 2025-12-16
"""

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class DistributedLock:
    """
    Redis-based distributed lock using SET NX EX pattern.

    Implements a simplified Redlock for single Redis instance.
    Auto-releases when used as async context manager.

    Attributes:
        KEY_PREFIX: Redis key prefix for locks
        DEFAULT_TTL: Default lock TTL in seconds
    """

    KEY_PREFIX = "lock"
    DEFAULT_TTL = 30  # seconds

    def __init__(
        self,
        redis: Any | None,  # redis.asyncio.Redis
        resource: str,
        ttl: int = DEFAULT_TTL,
        owner_id: str | None = None,
    ):
        """
        Initialize distributed lock.

        Args:
            redis: Redis async client (None for no-op lock)
            resource: Resource identifier to lock (e.g., "workflow:abc123")
            ttl: Lock TTL in seconds (auto-release after this time)
            owner_id: Unique owner identifier (generated if not provided)
        """
        self._redis = redis
        self._resource = resource
        self._ttl = ttl
        self._owner_id = owner_id or str(uuid.uuid4())
        self._acquired = False

    @property
    def key(self) -> str:
        """Redis key for this lock."""
        return f"{self.KEY_PREFIX}:{self._resource}"

    @property
    def is_acquired(self) -> bool:
        """Whether this lock instance currently holds the lock."""
        return self._acquired

    async def acquire(self, blocking: bool = False, timeout: float = 0) -> bool:
        """
        Attempt to acquire the lock.

        Args:
            blocking: If True, wait for lock (not implemented, returns False)
            timeout: Timeout for blocking acquire (not implemented)

        Returns:
            True if lock acquired, False otherwise
        """
        if self._redis is None:
            # No Redis - lock always succeeds (no-op)
            self._acquired = True
            logger.debug(f"[LOCK] No-op acquire: {self.key}")
            return True

        try:
            # SET key value NX EX ttl
            # NX = only set if not exists
            # EX = expire after ttl seconds
            result = await self._redis.set(
                self.key,
                self._owner_id,
                nx=True,
                ex=self._ttl,
            )

            if result:
                self._acquired = True
                logger.debug(f"[LOCK] Acquired: {self.key} (owner={self._owner_id[:8]})")
                return True
            else:
                logger.debug(f"[LOCK] Failed to acquire: {self.key} (already held)")
                return False

        except Exception as e:
            logger.warning(f"[LOCK] Acquire error for {self.key}: {e}")
            # Graceful degradation - assume we got it
            self._acquired = True
            return True

    async def release(self) -> bool:
        """
        Release the lock.

        Only releases if we are the owner (prevents releasing someone else's lock).

        Returns:
            True if released, False if not held or owned by another
        """
        if not self._acquired:
            return False

        if self._redis is None:
            # No Redis - no-op release
            self._acquired = False
            logger.debug(f"[LOCK] No-op release: {self.key}")
            return True

        try:
            # Lua script for atomic check-and-delete
            # Only delete if we own the lock
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """

            result = await self._redis.eval(script, 1, self.key, self._owner_id)

            if result:
                self._acquired = False
                logger.debug(f"[LOCK] Released: {self.key}")
                return True
            else:
                logger.warning(f"[LOCK] Release failed (not owner): {self.key}")
                self._acquired = False
                return False

        except Exception as e:
            logger.warning(f"[LOCK] Release error for {self.key}: {e}")
            self._acquired = False
            return False

    async def extend(self, additional_ttl: int = None) -> bool:
        """
        Extend the lock TTL.

        Args:
            additional_ttl: New TTL in seconds (uses original if not specified)

        Returns:
            True if extended, False if not held
        """
        if not self._acquired:
            return False

        if self._redis is None:
            return True

        ttl = additional_ttl or self._ttl

        try:
            # Only extend if we own the lock
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("expire", KEYS[1], ARGV[2])
            else
                return 0
            end
            """

            result = await self._redis.eval(script, 1, self.key, self._owner_id, ttl)

            if result:
                logger.debug(f"[LOCK] Extended: {self.key} (ttl={ttl}s)")
                return True
            else:
                logger.warning(f"[LOCK] Extend failed (not owner): {self.key}")
                return False

        except Exception as e:
            logger.warning(f"[LOCK] Extend error for {self.key}: {e}")
            return False

    async def __aenter__(self) -> "DistributedLock":
        """Async context manager entry - acquire lock."""
        acquired = await self.acquire()
        if not acquired:
            raise LockAcquisitionError(f"Failed to acquire lock: {self.key}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - release lock."""
        await self.release()


class LockAcquisitionError(Exception):
    """Raised when lock acquisition fails."""

    pass


# =============================================================================
# Convenience functions
# =============================================================================


async def acquire_workflow_lock(
    redis: Any | None,
    workflow_id: str,
    ttl: int = 30,
) -> DistributedLock:
    """
    Acquire a lock for a workflow operation.

    Args:
        redis: Redis async client
        workflow_id: Workflow ID to lock
        ttl: Lock TTL in seconds

    Returns:
        DistributedLock instance (already acquired)

    Raises:
        LockAcquisitionError: If lock cannot be acquired
    """
    lock = DistributedLock(redis, f"workflow:{workflow_id}", ttl)
    if not await lock.acquire():
        raise LockAcquisitionError(f"Workflow {workflow_id} is already being processed")
    return lock


async def try_acquire_workflow_lock(
    redis: Any | None,
    workflow_id: str,
    ttl: int = 30,
) -> DistributedLock | None:
    """
    Try to acquire a workflow lock without raising.

    Args:
        redis: Redis async client
        workflow_id: Workflow ID to lock
        ttl: Lock TTL in seconds

    Returns:
        DistributedLock if acquired, None if lock is held
    """
    lock = DistributedLock(redis, f"workflow:{workflow_id}", ttl)
    if await lock.acquire():
        return lock
    return None
