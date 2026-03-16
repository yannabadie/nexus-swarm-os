"""
Request Deduplicator - Prevent duplicate execution during retries.

V12.4 COGNITIVE BOOST - Task #54

Tracks in-flight and completed requests to prevent duplicate execution
when operations are retried after failures. Uses hash-based fingerprinting
with TTL-based expiration.

Usage:
    from core.infrastructure.resilience.request_deduplicator import get_deduplicator

    dedup = get_deduplicator()

    # Check before executing
    result = dedup.check("tool_exec", {"tool": "bash", "cmd": "ls"})
    if result.is_duplicate:
        return result.cached_result

    # Execute...
    output = execute_tool(...)

    # Mark complete with result
    dedup.complete("tool_exec", {"tool": "bash", "cmd": "ls"}, result=output)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TTL_SECONDS = 300  # 5 minutes
MAX_ENTRIES = 10_000


# =============================================================================
# Types
# =============================================================================


@dataclass
class DeduplicationEntry:
    """A tracked request."""

    request_id: str
    fingerprint: str
    status: str  # "pending", "completed", "failed"
    result: Any = None
    created_at: float = 0.0
    completed_at: float = 0.0
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "fingerprint": self.fingerprint[:12],
            "status": self.status,
            "has_result": self.result is not None,
            "age_seconds": round(self.age_seconds, 2),
            "is_expired": self.is_expired,
        }


@dataclass
class CheckResult:
    """Result of a deduplication check."""

    is_duplicate: bool
    fingerprint: str
    status: str = ""  # "new", "pending", "completed", "failed"
    cached_result: Any = None
    entry: DeduplicationEntry | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_duplicate": self.is_duplicate,
            "fingerprint": self.fingerprint[:12],
            "status": self.status,
            "has_cached_result": self.cached_result is not None,
        }


@dataclass
class DeduplicationStats:
    """Statistics for deduplication."""

    total_checks: int = 0
    duplicates_caught: int = 0
    entries_active: int = 0
    entries_expired: int = 0

    @property
    def duplicate_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.duplicates_caught / self.total_checks

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "duplicates_caught": self.duplicates_caught,
            "entries_active": self.entries_active,
            "entries_expired": self.entries_expired,
            "duplicate_rate": round(self.duplicate_rate, 4),
        }


# =============================================================================
# Request Deduplicator
# =============================================================================


class RequestDeduplicator:
    """
    Prevents duplicate request execution.

    Uses content-based fingerprinting (SHA-256 of operation + fields)
    with TTL-based expiration. Tracks pending, completed, and failed requests.
    """

    def __init__(
        self,
        *,
        default_ttl: float = DEFAULT_TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
    ):
        self._entries: dict[str, DeduplicationEntry] = {}
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._total_checks = 0
        self._duplicates_caught = 0

    # =========================================================================
    # Check & Register
    # =========================================================================

    def check(
        self,
        operation: str,
        fields: dict[str, Any],
        *,
        ttl: float | None = None,
    ) -> CheckResult:
        """
        Check if a request is a duplicate.

        If not a duplicate, registers it as pending.

        Args:
            operation: Operation type (e.g. "tool_exec", "api_call")
            fields: Fields that define uniqueness
            ttl: TTL in seconds (default: default_ttl)

        Returns:
            CheckResult indicating whether this is a duplicate
        """
        fingerprint = self._fingerprint(operation, fields)

        with self._lock:
            self._total_checks += 1

            # Check existing entry
            entry = self._entries.get(fingerprint)
            if entry is not None and not entry.is_expired:
                self._duplicates_caught += 1
                return CheckResult(
                    is_duplicate=True,
                    fingerprint=fingerprint,
                    status=entry.status,
                    cached_result=entry.result,
                    entry=entry,
                )

            # Register as pending
            entry = DeduplicationEntry(
                request_id=fingerprint[:16],
                fingerprint=fingerprint,
                status="pending",
                ttl_seconds=ttl or self._default_ttl,
            )
            self._entries[fingerprint] = entry
            self._enforce_max_entries()

        return CheckResult(
            is_duplicate=False,
            fingerprint=fingerprint,
            status="new",
        )

    def is_duplicate(
        self,
        operation: str,
        fields: dict[str, Any],
    ) -> bool:
        """Simple check without registering."""
        fingerprint = self._fingerprint(operation, fields)
        with self._lock:
            entry = self._entries.get(fingerprint)
            return entry is not None and not entry.is_expired

    # =========================================================================
    # Complete / Fail
    # =========================================================================

    def complete(
        self,
        operation: str,
        fields: dict[str, Any],
        *,
        result: Any = None,
    ) -> bool:
        """
        Mark a request as completed with optional result.

        Returns True if entry was found and updated.
        """
        fingerprint = self._fingerprint(operation, fields)
        with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                return False
            entry.status = "completed"
            entry.result = result
            entry.completed_at = time.monotonic()
        return True

    def fail(
        self,
        operation: str,
        fields: dict[str, Any],
    ) -> bool:
        """
        Mark a request as failed (allows retry).

        Returns True if entry was found and updated.
        """
        fingerprint = self._fingerprint(operation, fields)
        with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                return False
            entry.status = "failed"
        return True

    def remove(
        self,
        operation: str,
        fields: dict[str, Any],
    ) -> bool:
        """Remove an entry entirely (allows immediate retry)."""
        fingerprint = self._fingerprint(operation, fields)
        with self._lock:
            return self._entries.pop(fingerprint, None) is not None

    # =========================================================================
    # Query
    # =========================================================================

    def get_entry(
        self,
        operation: str,
        fields: dict[str, Any],
    ) -> DeduplicationEntry | None:
        """Get an entry by operation + fields."""
        fingerprint = self._fingerprint(operation, fields)
        with self._lock:
            return self._entries.get(fingerprint)

    def get_stats(self) -> DeduplicationStats:
        """Get deduplication statistics."""
        with self._lock:
            active = sum(1 for e in self._entries.values() if not e.is_expired)
            expired = sum(1 for e in self._entries.values() if e.is_expired)
        return DeduplicationStats(
            total_checks=self._total_checks,
            duplicates_caught=self._duplicates_caught,
            entries_active=active,
            entries_expired=expired,
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        with self._lock:
            expired = [fp for fp, entry in self._entries.items() if entry.is_expired]
            for fp in expired:
                del self._entries[fp]
        return len(expired)

    def _enforce_max_entries(self) -> None:
        """Remove oldest entries if over limit."""
        if len(self._entries) <= self._max_entries:
            return
        # Sort by creation time, remove oldest
        sorted_entries = sorted(
            self._entries.items(),
            key=lambda x: x[1].created_at,
        )
        to_remove = len(self._entries) - self._max_entries
        for fp, _ in sorted_entries[:to_remove]:
            del self._entries[fp]

    # =========================================================================
    # Fingerprinting
    # =========================================================================

    @staticmethod
    def _fingerprint(operation: str, fields: dict[str, Any]) -> str:
        """Generate a deterministic fingerprint for a request."""
        canonical = json.dumps(
            {"op": operation, **fields},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    # =========================================================================
    # State
    # =========================================================================

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.status == "pending")

    @property
    def completed_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.status == "completed")

    def clear(self) -> None:
        """Clear all entries and reset stats."""
        with self._lock:
            self._entries.clear()
            self._total_checks = 0
            self._duplicates_caught = 0

    def to_dict(self) -> dict[str, Any]:
        stats = self.get_stats()
        return {
            "entry_count": self.entry_count,
            "pending_count": self.pending_count,
            "completed_count": self.completed_count,
            **stats.to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_deduplicator: RequestDeduplicator | None = None
_dedup_lock = threading.Lock()


def get_deduplicator() -> RequestDeduplicator:
    """Get or create the global request deduplicator."""
    global _deduplicator
    if _deduplicator is None:
        with _dedup_lock:
            if _deduplicator is None:
                _deduplicator = RequestDeduplicator()
    return _deduplicator


def reset_deduplicator() -> None:
    """Reset the global deduplicator (for testing)."""
    global _deduplicator
    _deduplicator = None
