"""
AsyncBlackboard - Thread-Safe Async Shared State.

NEXUS V9.0 Async-First Architecture

The Blackboard is NEXUS's shared memory space where:
- Agents store intermediate results
- Phases communicate context
- Tool results are cached

This async version uses AsyncRWLock for safe concurrent access,
replacing the sync RLock-based implementation.

Features:
- Multiple concurrent reads (via AsyncRWLock)
- Exclusive writes
- Atomic get-or-set operations
- Snapshot for safe iteration
- Namespaced keys for organization

Usage:
    bb = AsyncBlackboard()

    await bb.set("analysis_result", {"score": 0.95})
    result = await bb.get("analysis_result")

    # Atomic get-or-set
    value = await bb.get_or_set("cache_key", compute_default)

    # Safe iteration via snapshot
    data = await bb.snapshot()
    for key, value in data.items():
        process(key, value)
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from .rwlock import AsyncRWLock, InstrumentedAsyncRWLock

T = TypeVar("T")


@dataclass
class BlackboardEntry:
    """
    A single entry in the blackboard with metadata.

    Attributes:
        value: The stored value
        created_at: When the entry was created
        updated_at: When the entry was last updated
        source: What created this entry (agent, phase, etc.)
        ttl_seconds: Optional time-to-live
        version: Monotonic version number for CAS operations (GROK-001 fix)
    """

    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    source: str | None = None
    ttl_seconds: float | None = None
    version: int = 1  # V8.4.7: CAS support for PARALLEL mode race conditions

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired based on TTL."""
        if self.ttl_seconds is None:
            return False
        age = (datetime.now() - self.updated_at).total_seconds()
        return age > self.ttl_seconds


class AsyncBlackboard:
    """
    Thread-safe async shared state container.

    Provides dictionary-like access with async methods and
    proper locking for concurrent access.
    """

    def __init__(self, initial_data: dict[str, Any] | None = None, instrumented: bool = False):
        """
        Initialize the blackboard.

        Args:
            initial_data: Optional initial data to populate
            instrumented: If True, use instrumented lock for stats
        """
        self._data: dict[str, BlackboardEntry] = {}
        self._lock = InstrumentedAsyncRWLock() if instrumented else AsyncRWLock()

        if initial_data:
            for key, value in initial_data.items():
                self._data[key] = BlackboardEntry(value=value)

    async def get(self, key: str, default: T = None, include_expired: bool = False) -> Any | T:
        """
        Get a value from the blackboard.

        Args:
            key: The key to look up
            default: Value to return if key not found
            include_expired: If True, return expired values too

        Returns:
            The value or default if not found
        """
        async with self._lock.read():
            entry = self._data.get(key)
            if entry is None:
                return default
            if entry.is_expired and not include_expired:
                return default
            return entry.value

    async def set(self, key: str, value: Any, source: str | None = None, ttl_seconds: float | None = None) -> int:
        """
        Set a value in the blackboard.

        Args:
            key: The key to set
            value: The value to store
            source: Optional source identifier
            ttl_seconds: Optional time-to-live in seconds

        Returns:
            The new version number of the entry (V8.4.7 CAS support)
        """
        async with self._lock.write():
            now = datetime.now()
            if key in self._data:
                # Update existing - increment version (GROK-001 fix)
                entry = self._data[key]
                entry.value = value
                entry.updated_at = now
                entry.version += 1
                if source:
                    entry.source = source
                if ttl_seconds is not None:
                    entry.ttl_seconds = ttl_seconds
                return entry.version
            else:
                # Create new with version 1
                self._data[key] = BlackboardEntry(
                    value=value, created_at=now, updated_at=now, source=source, ttl_seconds=ttl_seconds, version=1
                )
                return 1

    async def delete(self, key: str) -> bool:
        """
        Delete a key from the blackboard.

        Args:
            key: The key to delete

        Returns:
            True if key existed and was deleted
        """
        async with self._lock.write():
            if key in self._data:
                del self._data[key]
                return True
            return False

    async def update(self, updates: dict[str, Any], source: str | None = None) -> None:
        """
        Update multiple values atomically.

        Args:
            updates: Dictionary of key-value pairs to update
            source: Optional source identifier for all updates
        """
        async with self._lock.write():
            now = datetime.now()
            for key, value in updates.items():
                if key in self._data:
                    entry = self._data[key]
                    entry.value = value
                    entry.updated_at = now
                    if source:
                        entry.source = source
                else:
                    self._data[key] = BlackboardEntry(value=value, created_at=now, updated_at=now, source=source)

    async def get_or_set(
        self, key: str, default_factory: Callable[[], T], source: str | None = None, ttl_seconds: float | None = None
    ) -> T:
        """
        Get a value, or set it if not present (atomic operation).

        Args:
            key: The key to look up
            default_factory: Callable that returns default value if key not found
            source: Optional source identifier
            ttl_seconds: Optional TTL if creating new entry

        Returns:
            The existing or newly created value
        """
        # First try read-only check
        async with self._lock.read():
            entry = self._data.get(key)
            if entry is not None and not entry.is_expired:
                return entry.value

        # Need to write
        async with self._lock.write():
            # Double-check after acquiring write lock
            entry = self._data.get(key)
            if entry is not None and not entry.is_expired:
                return entry.value

            # Create new entry
            value = default_factory()
            now = datetime.now()
            self._data[key] = BlackboardEntry(
                value=value, created_at=now, updated_at=now, source=source, ttl_seconds=ttl_seconds
            )
            return value

    async def snapshot(self, deep_copy: bool = True) -> dict[str, Any]:
        """
        Get a snapshot of all current values.

        Safe to iterate over without holding the lock.

        Args:
            deep_copy: If True, deep copy values to prevent mutation

        Returns:
            Dictionary of all key-value pairs
        """
        async with self._lock.read():
            if deep_copy:
                return {k: copy.deepcopy(v.value) for k, v in self._data.items() if not v.is_expired}
            else:
                return {k: v.value for k, v in self._data.items() if not v.is_expired}

    async def keys(self, include_expired: bool = False) -> list[str]:
        """Get all keys in the blackboard."""
        async with self._lock.read():
            if include_expired:
                return list(self._data.keys())
            return [k for k, v in self._data.items() if not v.is_expired]

    async def contains(self, key: str) -> bool:
        """Check if a key exists (and is not expired)."""
        async with self._lock.read():
            entry = self._data.get(key)
            return entry is not None and not entry.is_expired

    async def clear(self) -> int:
        """
        Clear all data from the blackboard.

        Returns:
            Number of entries cleared
        """
        async with self._lock.write():
            count = len(self._data)
            self._data.clear()
            return count

    async def clear_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        async with self._lock.write():
            expired_keys = [k for k, v in self._data.items() if v.is_expired]
            for key in expired_keys:
                del self._data[key]
            return len(expired_keys)

    async def get_metadata(self, key: str) -> dict[str, Any] | None:
        """
        Get metadata for an entry.

        Returns:
            Dictionary with created_at, updated_at, source, ttl, is_expired, version
        """
        async with self._lock.read():
            entry = self._data.get(key)
            if entry is None:
                return None
            return {
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
                "source": entry.source,
                "ttl_seconds": entry.ttl_seconds,
                "is_expired": entry.is_expired,
                "version": entry.version,  # V8.4.7: CAS support
            }

    async def namespaced_keys(self, namespace: str) -> list[str]:
        """
        Get all keys with a given namespace prefix.

        Args:
            namespace: Prefix to match (e.g., "hive_" matches "hive_analysis")

        Returns:
            List of matching keys
        """
        async with self._lock.read():
            return [k for k, v in self._data.items() if k.startswith(namespace) and not v.is_expired]

    async def size(self) -> int:
        """Get the number of entries (excluding expired)."""
        async with self._lock.read():
            return sum(1 for v in self._data.values() if not v.is_expired)

    # =========================================================================
    # V8.4.7 CAS Operations (GROK-001 Fix)
    # Compare-And-Swap for atomic operations in PARALLEL swarm mode
    # =========================================================================

    async def get_with_version(self, key: str, default: T = None, include_expired: bool = False) -> tuple[Any | T, int]:
        """
        Get a value along with its version number.

        Essential for CAS operations: read value+version, then use
        compare_and_set() to atomically update only if version matches.

        Args:
            key: The key to look up
            default: Value to return if key not found
            include_expired: If True, return expired values too

        Returns:
            Tuple of (value, version). Version is 0 if key not found.
        """
        async with self._lock.read():
            entry = self._data.get(key)
            if entry is None:
                return default, 0
            if entry.is_expired and not include_expired:
                return default, 0
            return entry.value, entry.version

    async def compare_and_set(
        self,
        key: str,
        expected_version: int,
        new_value: Any,
        source: str | None = None,
        ttl_seconds: float | None = None,
    ) -> tuple[bool, int]:
        """
        Atomic Compare-And-Set (CAS) operation.

        Only updates the value if the current version matches expected_version.
        This prevents lost updates in concurrent PARALLEL mode operations.

        Usage pattern:
            value, version = await bb.get_with_version("key")
            # ... process value ...
            success, new_version = await bb.compare_and_set(
                "key", version, new_value
            )
            if not success:
                # Concurrent modification detected, retry or handle

        Args:
            key: The key to update
            expected_version: The version we expect (from get_with_version)
            new_value: The new value to set
            source: Optional source identifier
            ttl_seconds: Optional TTL (preserves existing if None)

        Returns:
            Tuple of (success, current_version).
            - success=True, new_version if update succeeded
            - success=False, current_version if version mismatch (concurrent mod)
        """
        async with self._lock.write():
            entry = self._data.get(key)

            # Key doesn't exist
            if entry is None:
                if expected_version == 0:
                    # Expected no entry, create new
                    now = datetime.now()
                    self._data[key] = BlackboardEntry(
                        value=new_value,
                        created_at=now,
                        updated_at=now,
                        source=source,
                        ttl_seconds=ttl_seconds,
                        version=1,
                    )
                    return True, 1
                else:
                    # Expected existing entry, but it's gone
                    return False, 0

            # Version mismatch - concurrent modification detected
            if entry.version != expected_version:
                return False, entry.version

            # Version matches - update atomically
            now = datetime.now()
            entry.value = new_value
            entry.updated_at = now
            entry.version += 1
            if source:
                entry.source = source
            if ttl_seconds is not None:
                entry.ttl_seconds = ttl_seconds

            return True, entry.version

    async def expire_if_version(self, key: str, expected_version: int) -> tuple[bool, int]:
        """
        Atomically expire (delete) a key only if version matches.

        Prevents race conditions where one agent expires a key that
        another agent has just updated with fresh data.

        Args:
            key: The key to expire
            expected_version: The version we expect

        Returns:
            Tuple of (success, current_version).
            - success=True, 0 if deleted successfully
            - success=False, current_version if version mismatch
        """
        async with self._lock.write():
            entry = self._data.get(key)

            if entry is None:
                return False, 0

            if entry.version != expected_version:
                # Someone updated it - don't expire
                return False, entry.version

            # Version matches - safe to delete
            del self._data[key]
            return True, 0

    async def update_if_fresh(
        self, key: str, new_value: Any, max_age_seconds: float, source: str | None = None
    ) -> tuple[bool, int]:
        """
        Update a value only if the existing entry is still fresh (not stale).

        Combines TTL check with atomic update. Useful for cache refresh
        patterns where we only want to update if our read was recent.

        Args:
            key: The key to update
            new_value: The new value
            max_age_seconds: Maximum age in seconds to consider fresh
            source: Optional source identifier

        Returns:
            Tuple of (success, version).
            - success=True if updated
            - success=False if entry is stale or missing
        """
        async with self._lock.write():
            entry = self._data.get(key)

            if entry is None:
                return False, 0

            # Check freshness
            age = (datetime.now() - entry.updated_at).total_seconds()
            if age > max_age_seconds:
                return False, entry.version

            # Fresh - update
            now = datetime.now()
            entry.value = new_value
            entry.updated_at = now
            entry.version += 1
            if source:
                entry.source = source

            return True, entry.version

    def __repr__(self) -> str:
        # Sync repr for debugging - don't acquire lock
        return f"AsyncBlackboard(entries={len(self._data)})"


# Convenience function for creating a blackboard
def create_blackboard(initial_data: dict[str, Any] | None = None, instrumented: bool = False) -> AsyncBlackboard:
    """Create a new AsyncBlackboard instance."""
    return AsyncBlackboard(initial_data, instrumented)
