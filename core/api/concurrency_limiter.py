"""
V11 SYNCHROTRON: Global Concurrency Limiting for Agent Invocations.

Prevents resource starvation by limiting concurrent agent processes.

Problem:
- ParallelExecutor can spawn unlimited concurrent agents
- MAX_PARALLEL_AGENTS=4 exists in constants but was NEVER ENFORCED
- 50 parallel agents = 50 subprocesses = server crash

Solution:
- Global Semaphore limiting concurrent invocations
- Works for both async (asyncio.Semaphore) and sync (threading.Semaphore)
- Respects EXECUTION_LIMITS.MAX_PARALLEL_AGENTS from constants

Usage:
    # Async path (preferred)
    limiter = get_concurrency_limiter()
    async with limiter.acquire_async():
        result = await driver.invoke(...)

    # Sync path (legacy)
    limiter = get_concurrency_limiter()
    if limiter.acquire_sync(timeout=60.0):
        try:
            result = driver.invoke(...)
        finally:
            limiter.release_sync()

Author: Claude (NEXUS V11 SYNCHROTRON)
Date: 2025-12-15
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


def _get_max_concurrent() -> int:
    """Get maximum concurrent agents from constants or environment."""
    # Try to import from constants
    try:
        from core.constants import EXECUTION_LIMITS

        return getattr(EXECUTION_LIMITS, "MAX_PARALLEL_AGENTS", 4)
    except ImportError:
        pass

    # Fallback to environment variable
    env_value = os.environ.get("NEXUS_MAX_PARALLEL_AGENTS")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass

    # Default: CPU count or 4
    return os.cpu_count() or 4


# =============================================================================
# Telemetry
# =============================================================================


@dataclass
class ConcurrencyStats:
    """Statistics for concurrency limiter."""

    total_acquisitions: int = 0
    total_releases: int = 0
    total_timeouts: int = 0
    total_wait_time_ms: float = 0.0
    max_concurrent_observed: int = 0
    current_active: int = 0
    last_acquisition: datetime | None = None


# =============================================================================
# ConcurrencyLimiter
# =============================================================================


class ConcurrencyLimiter:
    """
    Global concurrency limiter for agent invocations.

    Uses Singleton pattern to ensure single point of control across all
    executors (PARALLEL, SEQUENTIAL, LEAD_SUPPORT, etc.).

    Thread-safe and async-safe:
    - asyncio.Semaphore for async paths (non-blocking)
    - threading.Semaphore for sync paths (blocking)
    """

    _instance: ConcurrencyLimiter | None = None
    _init_lock = threading.Lock()

    def __new__(cls) -> ConcurrencyLimiter:
        if cls._instance is None:
            with cls._init_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        """Initialize limiter (only runs once due to singleton)."""
        if getattr(self, "_initialized", False):
            return

        with self._init_lock:
            if self._initialized:
                return

            self._max_concurrent = _get_max_concurrent()

            # Async semaphore (for async paths)
            self._async_semaphore = asyncio.Semaphore(self._max_concurrent)

            # Sync semaphore (for legacy sync paths)
            self._sync_semaphore = threading.Semaphore(self._max_concurrent)

            # Stats tracking
            self._stats = ConcurrencyStats()
            self._stats_lock = threading.Lock()

            # Current active count (for monitoring)
            self._active_count = 0

            logger.info(f"[SYNCHROTRON] ConcurrencyLimiter initialized: max_concurrent={self._max_concurrent}")

            self._initialized = True

    @property
    def max_concurrent(self) -> int:
        """Maximum concurrent invocations allowed."""
        return self._max_concurrent

    @property
    def active_count(self) -> int:
        """Current number of active invocations."""
        return self._active_count

    @property
    def available_permits(self) -> int:
        """Number of permits currently available."""
        return self._max_concurrent - self._active_count

    # =========================================================================
    # Async API (preferred)
    # =========================================================================

    @asynccontextmanager
    async def acquire_async(self, timeout: float = 60.0):
        """
        Async context manager for acquiring a permit.

        Usage:
            async with limiter.acquire_async():
                result = await driver.invoke(...)

        Args:
            timeout: Maximum time to wait for permit (seconds)

        Raises:
            asyncio.TimeoutError: If permit not acquired within timeout
        """
        start_time = time.time()

        try:
            # Wait for semaphore with timeout
            await asyncio.wait_for(self._async_semaphore.acquire(), timeout=timeout)
        except TimeoutError:
            with self._stats_lock:
                self._stats.total_timeouts += 1
            logger.warning(
                f"[SYNCHROTRON] Permit acquisition timed out after {timeout}s "
                f"(active={self._active_count}, max={self._max_concurrent})"
            )
            raise

        # Update stats
        wait_time = (time.time() - start_time) * 1000
        with self._stats_lock:
            self._active_count += 1
            self._stats.total_acquisitions += 1
            self._stats.total_wait_time_ms += wait_time
            self._stats.max_concurrent_observed = max(self._stats.max_concurrent_observed, self._active_count)
            self._stats.current_active = self._active_count
            self._stats.last_acquisition = datetime.now()

        if wait_time > 100:  # Log if waited more than 100ms
            logger.debug(f"[SYNCHROTRON] Permit acquired after {wait_time:.0f}ms wait (active={self._active_count})")

        try:
            yield
        finally:
            self._async_semaphore.release()
            with self._stats_lock:
                self._active_count -= 1
                self._stats.total_releases += 1
                self._stats.current_active = self._active_count

    async def acquire_async_nowait(self) -> bool:
        """
        Try to acquire permit without waiting.

        Returns:
            True if permit acquired, False if not available
        """
        # Check if we can acquire without blocking
        if self._active_count >= self._max_concurrent:
            return False

        try:
            # This should not block since we checked first
            self._async_semaphore.acquire_nowait()
            with self._stats_lock:
                self._active_count += 1
                self._stats.total_acquisitions += 1
                self._stats.current_active = self._active_count
            return True
        except Exception as e:
            logger.debug("Async semaphore acquire failed: %s", e)
            return False

    def release_async(self):
        """Release async permit (use only with acquire_async_nowait)."""
        self._async_semaphore.release()
        with self._stats_lock:
            self._active_count -= 1
            self._stats.total_releases += 1
            self._stats.current_active = self._active_count

    # =========================================================================
    # Sync API (legacy)
    # =========================================================================

    @contextmanager
    def acquire_sync_context(self, timeout: float = 60.0):
        """
        Sync context manager for acquiring a permit.

        Usage:
            with limiter.acquire_sync_context():
                result = driver.invoke(...)

        Args:
            timeout: Maximum time to wait for permit (seconds)

        Raises:
            TimeoutError: If permit not acquired within timeout
        """
        if not self.acquire_sync(timeout=timeout):
            raise TimeoutError(
                f"Concurrency limit reached: could not acquire permit "
                f"within {timeout}s (active={self._active_count}, "
                f"max={self._max_concurrent})"
            )
        try:
            yield
        finally:
            self.release_sync()

    def acquire_sync(self, timeout: float = 60.0) -> bool:
        """
        Acquire a sync permit with timeout.

        Args:
            timeout: Maximum time to wait (seconds)

        Returns:
            True if permit acquired, False if timed out
        """
        start_time = time.time()
        acquired = self._sync_semaphore.acquire(timeout=timeout)

        if not acquired:
            with self._stats_lock:
                self._stats.total_timeouts += 1
            logger.warning(f"[SYNCHROTRON] Sync permit acquisition timed out after {timeout}s")
            return False

        wait_time = (time.time() - start_time) * 1000
        with self._stats_lock:
            self._active_count += 1
            self._stats.total_acquisitions += 1
            self._stats.total_wait_time_ms += wait_time
            self._stats.max_concurrent_observed = max(self._stats.max_concurrent_observed, self._active_count)
            self._stats.current_active = self._active_count
            self._stats.last_acquisition = datetime.now()

        return True

    def release_sync(self):
        """Release a sync permit."""
        self._sync_semaphore.release()
        with self._stats_lock:
            self._active_count -= 1
            self._stats.total_releases += 1
            self._stats.current_active = self._active_count

    # =========================================================================
    # Stats & Monitoring
    # =========================================================================

    def get_stats(self) -> dict:
        """Get current statistics."""
        with self._stats_lock:
            return {
                "max_concurrent": self._max_concurrent,
                "current_active": self._stats.current_active,
                "available_permits": self._max_concurrent - self._stats.current_active,
                "total_acquisitions": self._stats.total_acquisitions,
                "total_releases": self._stats.total_releases,
                "total_timeouts": self._stats.total_timeouts,
                "total_wait_time_ms": round(self._stats.total_wait_time_ms, 2),
                "avg_wait_time_ms": (
                    round(self._stats.total_wait_time_ms / self._stats.total_acquisitions, 2)
                    if self._stats.total_acquisitions > 0
                    else 0
                ),
                "max_concurrent_observed": self._stats.max_concurrent_observed,
                "last_acquisition": (
                    self._stats.last_acquisition.isoformat() if self._stats.last_acquisition else None
                ),
            }

    def reset_stats(self):
        """Reset statistics (for testing)."""
        with self._stats_lock:
            self._stats = ConcurrencyStats()


# =============================================================================
# Module-level API
# =============================================================================


def get_concurrency_limiter() -> ConcurrencyLimiter:
    """
    Get the global concurrency limiter singleton.

    Usage:
        limiter = get_concurrency_limiter()
        async with limiter.acquire_async():
            await driver.invoke(...)
    """
    return ConcurrencyLimiter()


def reset_concurrency_limiter():
    """
    Reset the global limiter (for testing only).

    WARNING: Only use in tests. Resetting while invocations are active
    will cause undefined behavior.
    """
    ConcurrencyLimiter._instance = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ConcurrencyLimiter",
    "ConcurrencyStats",
    "get_concurrency_limiter",
    "reset_concurrency_limiter",
]
