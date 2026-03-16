"""
Security Event Journal - Append-only security event logging.

V12.4 COGNITIVE BOOST

Provides append-only security event journaling for threat analysis,
compliance auditing, and pattern detection.

Usage:
    from core.security_pkg.security.security_event_journal import get_security_journal

    journal = get_security_journal()
    journal.record_event("auth_attempt", actor="claude", result="allowed")
    journal.record_auth_attempt(actor="rogue", success=False)
    journal.record_access_denied(actor="rogue", resource="/kernel")

    patterns = journal.detect_patterns(actor="rogue")
    stats = journal.get_stats()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_EVENTS = 100000
SEVERITY_LEVELS = {"info", "low", "medium", "high", "critical"}
EVENT_TYPES = {
    "auth_attempt",
    "access_denied",
    "policy_violation",
    "input_threat",
    "output_leak",
    "privilege_escalation",
    "anomaly",
    "tool_abuse",
}


# =============================================================================
# Types
# =============================================================================


@dataclass
class SecurityEvent:
    """Record of a security event."""

    event_id: str
    event_type: str  # from EVENT_TYPES
    severity: str = "medium"  # from SEVERITY_LEVELS
    actor: str = ""  # agent or user who triggered
    resource: str = ""  # what was accessed/affected
    action: str = ""  # what happened
    result: str = ""  # outcome (blocked, allowed, flagged)
    session_id: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "actor": self.actor,
            "resource": self.resource,
            "action": self.action,
            "result": self.result,
            "session_id": self.session_id,
            "details": self.details,
            "metadata": dict(self.metadata),
        }


@dataclass
class ThreatPattern:
    """Detected threat pattern from event analysis."""

    pattern_type: str  # e.g. "repeated_auth_failure", "privilege_probe"
    actor: str
    event_count: int
    severity: str
    first_seen: float
    last_seen: float
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "actor": self.actor,
            "event_count": self.event_count,
            "severity": self.severity,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "description": self.description,
        }


@dataclass
class SecurityJournalStats:
    """Journal statistics."""

    total_events: int
    events_by_type: dict[str, int]
    events_by_severity: dict[str, int]
    unique_actors: int
    critical_events: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_events": self.total_events,
            "events_by_type": dict(self.events_by_type),
            "events_by_severity": dict(self.events_by_severity),
            "unique_actors": self.unique_actors,
            "critical_events": self.critical_events,
        }


# =============================================================================
# Security Event Journal
# =============================================================================


class SecurityEventJournal:
    """
    Append-only security event journal.

    Features:
    - Record security events with type, severity, actor, resource
    - Convenience methods for common event types (auth, access, threat)
    - Query events by actor, type, severity, session
    - Detect threat patterns (repeated failures, privilege probes)
    - Per-actor summary analytics
    - Thread-safe, bounded history
    """

    def __init__(self, *, max_events: int = MAX_EVENTS):
        self._max_events = max_events
        self._events: list[SecurityEvent] = []
        self._counter: int = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_event(
        self,
        event_type: str,
        *,
        severity: str = "medium",
        actor: str = "",
        resource: str = "",
        action: str = "",
        result: str = "",
        session_id: str = "",
        details: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SecurityEvent:
        """
        Record a security event.

        Auto-generates event_id as 'se_NNNNNN'. Evicts oldest events
        when max capacity is reached.
        """
        with self._lock:
            self._counter += 1
            event_id = f"se_{self._counter:06d}"

            event = SecurityEvent(
                event_id=event_id,
                event_type=event_type,
                severity=severity,
                actor=actor,
                resource=resource,
                action=action,
                result=result,
                session_id=session_id,
                details=details,
                metadata=metadata or {},
            )

            self._events.append(event)
            while len(self._events) > self._max_events:
                self._events.pop(0)

        _logger.debug(
            "Security event %s: type=%s severity=%s actor=%s",
            event_id,
            event_type,
            severity,
            actor,
        )
        return event

    def record_auth_attempt(
        self,
        *,
        actor: str,
        success: bool,
        resource: str = "",
        session_id: str = "",
        details: str = "",
    ) -> SecurityEvent:
        """Record an authentication attempt."""
        return self.record_event(
            "auth_attempt",
            severity="info" if success else "medium",
            actor=actor,
            resource=resource,
            action="authenticate",
            result="allowed" if success else "blocked",
            session_id=session_id,
            details=details,
        )

    def record_access_denied(
        self,
        *,
        actor: str,
        resource: str,
        session_id: str = "",
        details: str = "",
    ) -> SecurityEvent:
        """Record an access denied event."""
        return self.record_event(
            "access_denied",
            severity="high",
            actor=actor,
            resource=resource,
            action="access",
            result="blocked",
            session_id=session_id,
            details=details,
        )

    def record_threat(
        self,
        *,
        actor: str = "",
        threat_type: str = "input_threat",
        severity: str = "high",
        details: str = "",
        session_id: str = "",
    ) -> SecurityEvent:
        """Record a threat event (input_threat, output_leak, etc.)."""
        return self.record_event(
            threat_type,
            severity=severity,
            actor=actor,
            action="threat_detected",
            result="flagged",
            session_id=session_id,
            details=details,
        )

    # =========================================================================
    # Queries
    # =========================================================================

    def query_by_actor(self, actor: str, *, limit: int = 100) -> list[SecurityEvent]:
        """Query events by actor (most recent first)."""
        results: list[SecurityEvent] = []
        for event in reversed(self._events):
            if event.actor == actor:
                results.append(event)
                if len(results) >= limit:
                    break
        return results

    def query_by_type(self, event_type: str, *, limit: int = 100) -> list[SecurityEvent]:
        """Query events by type (most recent first)."""
        results: list[SecurityEvent] = []
        for event in reversed(self._events):
            if event.event_type == event_type:
                results.append(event)
                if len(results) >= limit:
                    break
        return results

    def query_by_severity(self, severity: str, *, limit: int = 100) -> list[SecurityEvent]:
        """Query events by severity (most recent first)."""
        results: list[SecurityEvent] = []
        for event in reversed(self._events):
            if event.severity == severity:
                results.append(event)
                if len(results) >= limit:
                    break
        return results

    def query_by_session(self, session_id: str, *, limit: int = 100) -> list[SecurityEvent]:
        """Query events by session ID (most recent first)."""
        results: list[SecurityEvent] = []
        for event in reversed(self._events):
            if event.session_id == session_id:
                results.append(event)
                if len(results) >= limit:
                    break
        return results

    def get_recent(self, *, limit: int = 50) -> list[SecurityEvent]:
        """Get the most recent events (most recent first)."""
        return list(reversed(self._events[-limit:]))

    def get_critical_events(self, *, limit: int = 50) -> list[SecurityEvent]:
        """Get critical severity events (most recent first)."""
        return self.query_by_severity("critical", limit=limit)

    # =========================================================================
    # Analytics
    # =========================================================================

    def detect_patterns(self, *, actor: str | None = None, window_size: int = 100) -> list[ThreatPattern]:
        """
        Detect threat patterns in recent events.

        Looks at the last *window_size* events for:
        - repeated_auth_failure: same actor with 3+ failed auth_attempt events
        - privilege_probe: same actor with 3+ access_denied events

        Args:
            actor: If provided, only analyse events from this actor.
            window_size: Number of recent events to analyse.

        Returns:
            List of detected ThreatPattern instances.
        """
        window = self._events[-window_size:] if window_size < len(self._events) else list(self._events)

        if actor:
            window = [e for e in window if e.actor == actor]

        # Group auth failures by actor
        auth_failures: dict[str, list[SecurityEvent]] = {}
        access_denials: dict[str, list[SecurityEvent]] = {}

        for event in window:
            if not event.actor:
                continue
            if event.event_type == "auth_attempt" and event.result == "blocked":
                auth_failures.setdefault(event.actor, []).append(event)
            if event.event_type == "access_denied":
                access_denials.setdefault(event.actor, []).append(event)

        patterns: list[ThreatPattern] = []

        for act, events in auth_failures.items():
            if len(events) >= 3:
                patterns.append(
                    ThreatPattern(
                        pattern_type="repeated_auth_failure",
                        actor=act,
                        event_count=len(events),
                        severity="high",
                        first_seen=events[0].timestamp,
                        last_seen=events[-1].timestamp,
                        description=(
                            f"Actor '{act}' has {len(events)} failed authentication "
                            f"attempts in the last {window_size} events"
                        ),
                    )
                )

        for act, events in access_denials.items():
            if len(events) >= 3:
                patterns.append(
                    ThreatPattern(
                        pattern_type="privilege_probe",
                        actor=act,
                        event_count=len(events),
                        severity="high",
                        first_seen=events[0].timestamp,
                        last_seen=events[-1].timestamp,
                        description=(
                            f"Actor '{act}' has {len(events)} access denied events in the last {window_size} events"
                        ),
                    )
                )

        return patterns

    def get_actor_summary(self, actor: str) -> dict[str, Any]:
        """
        Get a summary of all events for a specific actor.

        Returns:
            Dict with total_events, events_by_type, events_by_severity.
        """
        events_by_type: dict[str, int] = {}
        events_by_severity: dict[str, int] = {}
        total = 0

        for event in self._events:
            if event.actor != actor:
                continue
            total += 1
            events_by_type[event.event_type] = events_by_type.get(event.event_type, 0) + 1
            events_by_severity[event.severity] = events_by_severity.get(event.severity, 0) + 1

        return {
            "actor": actor,
            "total_events": total,
            "events_by_type": events_by_type,
            "events_by_severity": events_by_severity,
        }

    # =========================================================================
    # State
    # =========================================================================

    def get_stats(self) -> SecurityJournalStats:
        """Get journal statistics."""
        events_by_type: dict[str, int] = {}
        events_by_severity: dict[str, int] = {}
        actors: set[str] = set()
        critical_count = 0

        for event in self._events:
            events_by_type[event.event_type] = events_by_type.get(event.event_type, 0) + 1
            events_by_severity[event.severity] = events_by_severity.get(event.severity, 0) + 1
            if event.actor:
                actors.add(event.actor)
            if event.severity == "critical":
                critical_count += 1

        return SecurityJournalStats(
            total_events=len(self._events),
            events_by_type=events_by_type,
            events_by_severity=events_by_severity,
            unique_actors=len(actors),
            critical_events=critical_count,
        )

    @property
    def size(self) -> int:
        """Number of events in the journal."""
        return len(self._events)

    def clear(self) -> None:
        """Clear all events and reset counter."""
        with self._lock:
            self._events.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "counter": self._counter,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_journal: SecurityEventJournal | None = None
_journal_lock = threading.Lock()


def get_security_journal() -> SecurityEventJournal:
    """Get or create the global security event journal."""
    global _journal
    if _journal is None:
        with _journal_lock:
            if _journal is None:
                _journal = SecurityEventJournal()
    return _journal


def reset_security_journal() -> None:
    """Reset the global security event journal (for testing)."""
    global _journal
    _journal = None
