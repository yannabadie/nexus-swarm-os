"""
Resilience Event Tracker for NEXUS V12.4.

Tracks resilience events across the system:
- Circuit breaker trips
- Rate limiter activations
- Checkpoint restorations
- Retries
- Failovers
- Recovery actions
- System degradation

Thread-safe singleton implementation with bounded FIFO history.
Provides aggregate metrics per event type and component.

Architecture:
- ResilienceEvent: Single event record
- EventTypeMetrics: Aggregates per event type
- TrackerStats: Overall system stats
- ResilienceEventTracker: Thread-safe singleton

Usage:
    tracker = get_resilience_tracker()
    event = tracker.record_event(
        event_type="circuit_break",
        component="gemini_driver",
        description="Too many 503 errors",
        severity="warning"
    )
    metrics = tracker.get_type_metrics("circuit_break")
    stats = tracker.get_stats()
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

# Constants
MAX_EVENTS: int = 50000
EVENT_TYPES: tuple = (
    "circuit_break",
    "rate_limit",
    "checkpoint_restore",
    "retry",
    "failover",
    "recovery",
    "degradation",
)


@dataclass
class ResilienceEvent:
    """
    Single resilience event record.

    Attributes:
        event_id: Unique event identifier (auto-generated)
        event_type: Type of event (from EVENT_TYPES)
        component: Component that triggered the event
        description: Human-readable description
        severity: Event severity (info, warning, critical)
        resolved: Whether the event was resolved
        resolution_ms: Time to resolution in milliseconds
        timestamp: ISO8601 timestamp (auto-set)
    """

    event_id: str = ""
    event_type: str = ""
    component: str = ""
    description: str = ""
    severity: str = "info"
    resolved: bool = False
    resolution_ms: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return dataclasses.asdict(self)


@dataclass
class EventTypeMetrics:
    """
    Aggregate metrics for a specific event type.

    Attributes:
        event_type: The event type being tracked
        total_count: Total number of events
        resolved_count: Number of resolved events
        total_resolution_ms: Cumulative resolution time
    """

    event_type: str = ""
    total_count: int = 0
    resolved_count: int = 0
    total_resolution_ms: float = 0.0

    @property
    def resolution_rate(self) -> float:
        """Calculate resolution rate (0.0 to 1.0)."""
        if self.total_count == 0:
            return 0.0
        return self.resolved_count / self.total_count

    @property
    def avg_resolution_ms(self) -> float:
        """Calculate average resolution time in milliseconds."""
        if self.resolved_count == 0:
            return 0.0
        return self.total_resolution_ms / self.resolved_count

    def to_dict(self) -> dict:
        """Convert to dictionary with computed properties."""
        data = dataclasses.asdict(self)
        data["resolution_rate"] = self.resolution_rate
        data["avg_resolution_ms"] = self.avg_resolution_ms
        return data


@dataclass
class TrackerStats:
    """
    Overall tracker statistics.

    Attributes:
        total_events: Total number of events tracked
        unique_event_types: Number of unique event types seen
        unique_components: Number of unique components seen
        overall_resolution_rate: System-wide resolution rate
    """

    total_events: int = 0
    unique_event_types: int = 0
    unique_components: int = 0
    overall_resolution_rate: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return dataclasses.asdict(self)


class ResilienceEventTracker:
    """
    Thread-safe tracker for resilience events.

    Maintains bounded FIFO history of events with aggregate metrics.
    Supports querying by type, component, severity, and recency.

    Thread Safety:
        All public methods are thread-safe via internal lock.

    Singleton Pattern:
        Use get_resilience_tracker() to access the singleton instance.
    """

    def __init__(self, max_events: int = MAX_EVENTS):
        """
        Initialize resilience event tracker.

        Args:
            max_events: Maximum number of events to retain (FIFO eviction)
        """
        self._max_events = max_events
        self._lock = threading.Lock()
        self._events: list[ResilienceEvent] = []
        self._counter = 1
        self._type_metrics: dict[str, EventTypeMetrics] = {}

    def record_event(
        self,
        event_type: str,
        component: str = "",
        description: str = "",
        severity: str = "info",
        resolved: bool = False,
        resolution_ms: float = 0.0,
    ) -> ResilienceEvent:
        """
        Record a new resilience event.

        Args:
            event_type: Type of event (from EVENT_TYPES)
            component: Component that triggered the event
            description: Human-readable description
            severity: Event severity (info, warning, critical)
            resolved: Whether the event was resolved
            resolution_ms: Time to resolution in milliseconds

        Returns:
            The recorded ResilienceEvent

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            # Generate event ID
            event_id = f"rev_{self._counter:06d}"
            self._counter += 1

            # Create event
            timestamp = datetime.now(UTC).isoformat()
            event = ResilienceEvent(
                event_id=event_id,
                event_type=event_type,
                component=component,
                description=description,
                severity=severity,
                resolved=resolved,
                resolution_ms=resolution_ms,
                timestamp=timestamp,
            )

            # FIFO eviction if at max
            if len(self._events) >= self._max_events:
                self._events.pop(0)

            # Add event
            self._events.append(event)

            # Update metrics
            if event_type not in self._type_metrics:
                self._type_metrics[event_type] = EventTypeMetrics(event_type=event_type)

            metrics = self._type_metrics[event_type]
            metrics.total_count += 1
            if resolved:
                metrics.resolved_count += 1
                metrics.total_resolution_ms += resolution_ms

            return event

    def get_type_metrics(self, event_type: str) -> EventTypeMetrics | None:
        """
        Get aggregate metrics for a specific event type.

        Args:
            event_type: The event type to query

        Returns:
            EventTypeMetrics if type exists, None otherwise

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return self._type_metrics.get(event_type)

    def get_all_metrics(self) -> list[EventTypeMetrics]:
        """
        Get all event type metrics sorted by total count descending.

        Returns:
            List of EventTypeMetrics sorted by total_count

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            metrics = list(self._type_metrics.values())
            metrics.sort(key=lambda m: m.total_count, reverse=True)
            return metrics

    def get_events_by_type(self, event_type: str) -> list[ResilienceEvent]:
        """
        Get all events of a specific type.

        Args:
            event_type: The event type to filter by

        Returns:
            List of ResilienceEvents matching the type

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return [e for e in self._events if e.event_type == event_type]

    def get_events_by_component(self, component: str) -> list[ResilienceEvent]:
        """
        Get all events from a specific component.

        Args:
            component: The component to filter by

        Returns:
            List of ResilienceEvents from the component

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return [e for e in self._events if e.component == component]

    def get_events_by_severity(self, severity: str) -> list[ResilienceEvent]:
        """
        Get all events with a specific severity.

        Args:
            severity: The severity level to filter by

        Returns:
            List of ResilienceEvents matching severity

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return [e for e in self._events if e.severity == severity]

    def get_recent_events(self, limit: int = 10) -> list[ResilienceEvent]:
        """
        Get most recent events.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of most recent ResilienceEvents (newest first)

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return list(reversed(self._events[-limit:]))

    def get_critical_events(self) -> list[ResilienceEvent]:
        """
        Get all critical severity events.

        Returns:
            List of critical ResilienceEvents

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return [e for e in self._events if e.severity == "critical"]

    def list_components(self) -> list[str]:
        """
        List all unique components that have triggered events.

        Returns:
            Sorted list of component names

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            components = {e.component for e in self._events if e.component}
            return sorted(components)

    def get_stats(self) -> TrackerStats:
        """
        Get overall tracker statistics.

        Returns:
            TrackerStats with system-wide metrics

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            total_events = len(self._events)
            unique_types = len(self._type_metrics)
            unique_components = len({e.component for e in self._events if e.component})

            # Calculate overall resolution rate
            total_resolved = sum(1 for e in self._events if e.resolved)
            overall_resolution_rate = total_resolved / total_events if total_events > 0 else 0.0

            return TrackerStats(
                total_events=total_events,
                unique_event_types=unique_types,
                unique_components=unique_components,
                overall_resolution_rate=overall_resolution_rate,
            )

    @property
    def event_count(self) -> int:
        """
        Get current number of tracked events.

        Returns:
            Number of events in history

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        """
        Clear all tracked events and metrics.

        Thread Safety:
            Thread-safe via internal lock
        """
        with self._lock:
            self._events.clear()
            self._type_metrics.clear()
            self._counter = 1

    def to_dict(self) -> dict:
        """
        Convert tracker state to dictionary.

        Returns:
            Dictionary with stats, metrics, and recent events

        Thread Safety:
            Thread-safe via internal lock
            CRITICAL: Calls get_stats() BEFORE acquiring lock to prevent deadlock
        """
        # DEADLOCK PREVENTION: Call all locking methods BEFORE acquiring lock
        stats = self.get_stats()
        all_metrics = self.get_all_metrics()
        recent = self.get_recent_events(limit=20)

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "metrics": [m.to_dict() for m in all_metrics],
                "recent_events": [e.to_dict() for e in recent],
                "max_events": self._max_events,
            }


# Singleton pattern with double-checked locking
_instance: ResilienceEventTracker | None = None
_lock = threading.Lock()


def get_resilience_tracker() -> ResilienceEventTracker:
    """
    Get the global ResilienceEventTracker singleton.

    Returns:
        The singleton ResilienceEventTracker instance

    Thread Safety:
        Thread-safe via double-checked locking
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ResilienceEventTracker()
    return _instance


def reset_resilience_tracker() -> None:
    """
    Reset the global ResilienceEventTracker singleton.

    Creates a new instance, discarding all tracked events.

    Thread Safety:
        Thread-safe via global lock
    """
    global _instance
    with _lock:
        _instance = None
