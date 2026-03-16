"""
AsyncRWLock - Async Read-Write Lock.

NEXUS V9.0 Async-First Architecture

Implements a read-write lock pattern for async code:
- Multiple readers can hold the lock simultaneously
- Writers have exclusive access (no readers or other writers)
- Writers are prioritized to prevent starvation

This is essential for protecting shared state (like AsyncBlackboard)
where reads are frequent but writes need exclusive access.

Usage:
    lock = AsyncRWLock()

    # Multiple concurrent reads allowed
    async with lock.read():
        data = shared_dict["key"]

    # Exclusive write access
    async with lock.write():
        shared_dict["key"] = new_value

References:
- https://en.wikipedia.org/wiki/Readers%E2%80%93writer_lock
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass


class AsyncRWLock:
    """
    Async read-write lock with writer priority.

    Allows multiple concurrent readers OR a single exclusive writer.
    Writers are given priority to prevent writer starvation.

    Attributes:
        _readers: Count of active readers
        _writer: Whether a writer holds the lock
        _pending_writers: Count of writers waiting
        _condition: Condition variable for synchronization
    """

    def __init__(self):
        self._readers: int = 0
        self._writer: bool = False
        self._pending_writers: int = 0
        self._condition: asyncio.Condition = asyncio.Condition()

    @asynccontextmanager
    async def read(self):
        """
        Acquire read lock (shared access).

        Multiple readers can hold this lock simultaneously.
        Blocks if a writer holds the lock or writers are waiting.

        Usage:
            async with lock.read():
                # Read shared data
                value = shared_dict[key]
        """
        async with self._condition:
            # Wait if writer holds lock OR writers are waiting (priority)
            while self._writer or self._pending_writers > 0:
                await self._condition.wait()
            self._readers += 1

        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                # Wake up waiting writers if no readers left
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write(self):
        """
        Acquire write lock (exclusive access).

        Only one writer can hold this lock. Blocks all readers.

        Usage:
            async with lock.write():
                # Modify shared data
                shared_dict[key] = new_value
        """
        async with self._condition:
            self._pending_writers += 1
            try:
                # Wait until no readers and no other writer
                while self._writer or self._readers > 0:
                    await self._condition.wait()
                self._writer = True
            finally:
                self._pending_writers -= 1

        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()

    @property
    def readers(self) -> int:
        """Current number of readers holding the lock."""
        return self._readers

    @property
    def is_write_locked(self) -> bool:
        """Whether a writer currently holds the lock."""
        return self._writer

    @property
    def pending_writers(self) -> int:
        """Number of writers waiting for the lock."""
        return self._pending_writers

    def __repr__(self) -> str:
        return f"AsyncRWLock(readers={self._readers}, writer={self._writer}, pending_writers={self._pending_writers})"


class AsyncRWLockWithTimeout(AsyncRWLock):
    """
    AsyncRWLock with timeout support.

    Extends AsyncRWLock to allow timeout on lock acquisition.
    """

    @asynccontextmanager
    async def read_with_timeout(self, timeout: float):
        """
        Acquire read lock with timeout.

        Args:
            timeout: Maximum seconds to wait for lock

        Raises:
            asyncio.TimeoutError: If lock not acquired within timeout
        """
        async with self._condition:
            try:
                await asyncio.wait_for(self._wait_for_read(), timeout=timeout)
            except TimeoutError:
                raise TimeoutError("Timeout acquiring read lock") from None
            self._readers += 1

        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write_with_timeout(self, timeout: float):
        """
        Acquire write lock with timeout.

        Args:
            timeout: Maximum seconds to wait for lock

        Raises:
            asyncio.TimeoutError: If lock not acquired within timeout
        """
        async with self._condition:
            self._pending_writers += 1
            try:
                try:
                    await asyncio.wait_for(self._wait_for_write(), timeout=timeout)
                except TimeoutError:
                    raise TimeoutError("Timeout acquiring write lock") from None
                self._writer = True
            finally:
                self._pending_writers -= 1

        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()

    async def _wait_for_read(self):
        """Wait until read is possible."""
        while self._writer or self._pending_writers > 0:
            await self._condition.wait()

    async def _wait_for_write(self):
        """Wait until write is possible."""
        while self._writer or self._readers > 0:
            await self._condition.wait()


@dataclass
class RWLockStats:
    """Statistics for an AsyncRWLock."""

    total_reads: int = 0
    total_writes: int = 0
    read_wait_time_ms: float = 0.0
    write_wait_time_ms: float = 0.0
    current_readers: int = 0
    has_writer: bool = False
    pending_writers: int = 0


class InstrumentedAsyncRWLock(AsyncRWLock):
    """
    AsyncRWLock with instrumentation for monitoring.

    Tracks statistics about lock usage for debugging and optimization.
    """

    def __init__(self):
        super().__init__()
        self._total_reads = 0
        self._total_writes = 0
        self._read_wait_time = 0.0
        self._write_wait_time = 0.0

    @asynccontextmanager
    async def read(self):
        """Instrumented read lock acquisition."""
        import time

        start = time.monotonic()

        async with self._condition:
            while self._writer or self._pending_writers > 0:
                await self._condition.wait()
            self._readers += 1
            self._total_reads += 1
            self._read_wait_time += (time.monotonic() - start) * 1000

        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write(self):
        """Instrumented write lock acquisition."""
        import time

        start = time.monotonic()

        async with self._condition:
            self._pending_writers += 1
            try:
                while self._writer or self._readers > 0:
                    await self._condition.wait()
                self._writer = True
                self._total_writes += 1
                self._write_wait_time += (time.monotonic() - start) * 1000
            finally:
                self._pending_writers -= 1

        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()

    def stats(self) -> RWLockStats:
        """Get current lock statistics."""
        return RWLockStats(
            total_reads=self._total_reads,
            total_writes=self._total_writes,
            read_wait_time_ms=self._read_wait_time,
            write_wait_time_ms=self._write_wait_time,
            current_readers=self._readers,
            has_writer=self._writer,
            pending_writers=self._pending_writers,
        )
