"""
Message Deduplicator - Idempotent message processing with tracing.

V12.4 COGNITIVE BOOST - Task #78

Provides message deduplication via content-based fingerprinting (SHA-256),
duplicate detection with TTL-based expiration, and message tracing via
correlation IDs for end-to-end observability.

Usage:
    from core.synapse.message_deduplicator import get_deduplicator

    dedup = get_deduplicator()

    # Check for duplicates
    if dedup.is_duplicate("hello world", sender="claude"):
        print("Already processed")

    # Check and get fingerprint back
    is_dup, fp = dedup.check_and_register("hello world", sender="claude")

    # Trace message flow
    dedup.start_trace("corr-123", initial_hop="claude")
    dedup.add_hop("corr-123", "gemini")
    dedup.end_trace("corr-123")
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_FINGERPRINTS = 100_000
DEFAULT_TTL = 300.0  # seconds - how long fingerprints are remembered
MAX_TRACES = 10_000


# =============================================================================
# Helpers
# =============================================================================


def compute_fingerprint(
    content: str,
    sender: str = "",
    message_type: str = "",
) -> str:
    """Compute a SHA-256 fingerprint from content + sender + type."""
    raw = f"{content}|{sender}|{message_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# =============================================================================
# Types
# =============================================================================


@dataclass
class MessageFingerprint:
    """A recorded message fingerprint for deduplication."""

    fingerprint: str
    sender: str = ""
    message_type: str = ""
    first_seen: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "sender": self.sender,
            "message_type": self.message_type,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "count": self.count,
        }


@dataclass
class MessageTrace:
    """Traces a message's journey through agents via correlation ID."""

    correlation_id: str
    hops: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float = 0.0
    status: str = "active"  # active, completed, expired
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def duration_ms(self) -> float:
        if self.ended_at > 0:
            return (self.ended_at - self.started_at) * 1000
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "hops": list(self.hops),
            "hop_count": self.hop_count,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass
class DeduplicationStats:
    """Statistics for message deduplication."""

    total_checked: int = 0
    total_duplicates: int = 0
    total_unique: int = 0
    active_fingerprints: int = 0
    active_traces: int = 0

    @property
    def duplicate_rate(self) -> float:
        if self.total_checked > 0:
            return self.total_duplicates / self.total_checked
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_checked": self.total_checked,
            "total_duplicates": self.total_duplicates,
            "total_unique": self.total_unique,
            "active_fingerprints": self.active_fingerprints,
            "active_traces": self.active_traces,
            "duplicate_rate": round(self.duplicate_rate, 4),
        }


# =============================================================================
# Message Deduplicator
# =============================================================================


class MessageDeduplicator:
    """
    Idempotent message processing with fingerprinting and tracing.

    Features:
    - Content-based SHA-256 fingerprinting (truncated to 16 chars)
    - TTL-based expiration for fingerprints
    - Automatic eviction when capacity exceeded (oldest 10%)
    - Correlation-ID-based message tracing with hop tracking
    - Thread-safe with non-reentrant lock
    - Statistics and introspection
    """

    def __init__(
        self,
        *,
        max_fingerprints: int = MAX_FINGERPRINTS,
        ttl: float = DEFAULT_TTL,
        max_traces: int = MAX_TRACES,
    ):
        self._fingerprints: dict[str, MessageFingerprint] = {}
        self._traces: dict[str, MessageTrace] = {}
        self._max_fingerprints = max_fingerprints
        self._ttl = ttl
        self._max_traces = max_traces
        self._total_checked: int = 0
        self._total_duplicates: int = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Deduplication
    # =========================================================================

    def is_duplicate(
        self,
        content: str,
        *,
        sender: str = "",
        message_type: str = "",
    ) -> bool:
        """
        Check if a message is a duplicate.

        Computes fingerprint from content + sender + message_type.
        If fingerprint exists and is not expired, increments count and
        returns True. Expired fingerprints are treated as new.

        Args:
            content: Message content to fingerprint.
            sender: Sender identifier.
            message_type: Message type string.

        Returns:
            True if the message is a duplicate, False otherwise.
        """
        fp = compute_fingerprint(content, sender, message_type)
        now = time.monotonic()

        with self._lock:
            self._total_checked += 1
            existing = self._fingerprints.get(fp)

            if existing is not None:
                # Check expiration
                if (now - existing.first_seen) <= self._ttl:
                    # Not expired - duplicate
                    existing.count += 1
                    existing.last_seen = now
                    self._total_duplicates += 1
                    return True
                # Expired - treat as new, replace entry
                del self._fingerprints[fp]

            # New fingerprint
            self._fingerprints[fp] = MessageFingerprint(
                fingerprint=fp,
                sender=sender,
                message_type=message_type,
                first_seen=now,
                last_seen=now,
                count=1,
            )
            self._evict_fingerprints_if_needed()
            return False

    def check_and_register(
        self,
        content: str,
        *,
        sender: str = "",
        message_type: str = "",
    ) -> tuple[bool, str]:
        """
        Check for duplicate and return the fingerprint string.

        Like is_duplicate but returns (is_dup, fingerprint_str).
        Useful when the caller needs the fingerprint for tracking.

        Args:
            content: Message content to fingerprint.
            sender: Sender identifier.
            message_type: Message type string.

        Returns:
            Tuple of (is_duplicate, fingerprint_string).
        """
        fp = compute_fingerprint(content, sender, message_type)
        now = time.monotonic()

        with self._lock:
            self._total_checked += 1
            existing = self._fingerprints.get(fp)

            if existing is not None:
                if (now - existing.first_seen) <= self._ttl:
                    existing.count += 1
                    existing.last_seen = now
                    self._total_duplicates += 1
                    return True, fp
                del self._fingerprints[fp]

            self._fingerprints[fp] = MessageFingerprint(
                fingerprint=fp,
                sender=sender,
                message_type=message_type,
                first_seen=now,
                last_seen=now,
                count=1,
            )
            self._evict_fingerprints_if_needed()
            return False, fp

    def get_fingerprint(self, fingerprint: str) -> MessageFingerprint | None:
        """Get a fingerprint entry by its hash string."""
        with self._lock:
            return self._fingerprints.get(fingerprint)

    def cleanup_expired(self) -> int:
        """
        Remove all expired fingerprints.

        Returns:
            Number of fingerprints removed.
        """
        now = time.monotonic()
        with self._lock:
            expired = [fp for fp, entry in self._fingerprints.items() if (now - entry.first_seen) > self._ttl]
            for fp in expired:
                del self._fingerprints[fp]
        return len(expired)

    def _evict_fingerprints_if_needed(self) -> None:
        """Evict oldest 10% of fingerprints if over capacity. Caller holds lock."""
        if len(self._fingerprints) <= self._max_fingerprints:
            return
        sorted_fps = sorted(
            self._fingerprints.items(),
            key=lambda x: x[1].first_seen,
        )
        to_remove = max(1, len(self._fingerprints) // 10)
        for fp, _ in sorted_fps[:to_remove]:
            del self._fingerprints[fp]

    # =========================================================================
    # Tracing
    # =========================================================================

    def start_trace(
        self,
        correlation_id: str,
        *,
        initial_hop: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MessageTrace:
        """
        Start a new message trace.

        Args:
            correlation_id: Unique ID for this trace.
            initial_hop: First agent in the trace path.
            metadata: Arbitrary metadata to attach.

        Returns:
            The created MessageTrace.
        """
        hops: list[str] = []
        if initial_hop:
            hops.append(initial_hop)

        trace = MessageTrace(
            correlation_id=correlation_id,
            hops=hops,
            metadata=metadata or {},
        )

        with self._lock:
            self._traces[correlation_id] = trace
            self._evict_traces_if_needed()

        return trace

    def add_hop(self, correlation_id: str, agent_id: str) -> bool:
        """
        Append an agent hop to an existing trace.

        Args:
            correlation_id: The trace to update.
            agent_id: The agent ID to append.

        Returns:
            True if the trace was found and updated, False otherwise.
        """
        with self._lock:
            trace = self._traces.get(correlation_id)
            if trace is None:
                return False
            trace.hops.append(agent_id)
            return True

    def end_trace(self, correlation_id: str) -> MessageTrace | None:
        """
        End a trace, marking it as completed.

        Args:
            correlation_id: The trace to end.

        Returns:
            The completed trace, or None if not found.
        """
        with self._lock:
            trace = self._traces.get(correlation_id)
            if trace is None:
                return None
            trace.ended_at = time.monotonic()
            trace.status = "completed"
            return trace

    def get_trace(self, correlation_id: str) -> MessageTrace | None:
        """Get a trace by its correlation ID."""
        with self._lock:
            return self._traces.get(correlation_id)

    def list_traces(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[MessageTrace]:
        """
        List traces, optionally filtered by status.

        Args:
            status: Filter by status (active, completed, expired). None for all.
            limit: Maximum traces to return.

        Returns:
            Traces sorted by started_at descending (most recent first).
        """
        with self._lock:
            if status is not None:
                traces = [t for t in self._traces.values() if t.status == status]
            else:
                traces = list(self._traces.values())

        traces.sort(key=lambda t: t.started_at, reverse=True)
        return traces[:limit]

    def _evict_traces_if_needed(self) -> None:
        """Evict oldest 10% of traces if over capacity. Caller holds lock."""
        if len(self._traces) <= self._max_traces:
            return
        sorted_traces = sorted(
            self._traces.items(),
            key=lambda x: x[1].started_at,
        )
        to_remove = max(1, len(self._traces) // 10)
        for cid, _ in sorted_traces[:to_remove]:
            del self._traces[cid]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> DeduplicationStats:
        """Get deduplication and tracing statistics."""
        with self._lock:
            total_checked = self._total_checked
            total_duplicates = self._total_duplicates
            total_unique = total_checked - total_duplicates
            active_fingerprints = len(self._fingerprints)
            active_traces = len(self._traces)

        return DeduplicationStats(
            total_checked=total_checked,
            total_duplicates=total_duplicates,
            total_unique=total_unique,
            active_fingerprints=active_fingerprints,
            active_traces=active_traces,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def fingerprint_count(self) -> int:
        return len(self._fingerprints)

    @property
    def trace_count(self) -> int:
        return len(self._traces)

    def clear(self) -> None:
        """Clear all fingerprints, traces, and reset counters."""
        with self._lock:
            self._fingerprints.clear()
            self._traces.clear()
            self._total_checked = 0
            self._total_duplicates = 0

    def to_dict(self) -> dict[str, Any]:
        # Call get_stats() BEFORE acquiring the lock to avoid deadlock,
        # since get_stats() itself acquires the lock.
        stats = self.get_stats()
        return {
            "fingerprint_count": self.fingerprint_count,
            "trace_count": self.trace_count,
            **stats.to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_deduplicator: MessageDeduplicator | None = None
_dedup_lock = threading.Lock()


def get_deduplicator() -> MessageDeduplicator:
    """Get or create the global message deduplicator."""
    global _deduplicator
    if _deduplicator is None:
        with _dedup_lock:
            if _deduplicator is None:
                _deduplicator = MessageDeduplicator()
    return _deduplicator


def reset_deduplicator() -> None:
    """Reset the global deduplicator (for testing)."""
    global _deduplicator
    _deduplicator = None
