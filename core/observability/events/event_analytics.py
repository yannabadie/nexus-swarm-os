"""
Event Analytics - Event stream analytics for NEXUS event bus.

V12.4 COGNITIVE BOOST

Tracks event stream analytics:
- Event counts by type (total, success, failure)
- Processing latency per event type (avg, total)
- Throughput (events per type over time)
- Event flow patterns (source distribution, type distribution)

Usage:
    from core.observability.events.event_analytics import get_event_analytics

    analytics = get_event_analytics()
    record = analytics.record_event("agent.speak", source="claude", processing_time_ms=12.5)
    metrics = analytics.get_type_metrics("agent.speak")
    stats = analytics.get_stats()
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_EVENTS: int = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class EventRecord:
    """Record of a single event occurrence."""

    event_id: str = ""
    event_type: str = ""
    source: str = ""
    processing_time_ms: float = 0.0
    success: bool = True
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class EventTypeMetrics:
    """Aggregated metrics per event type."""

    event_type: str = ""
    total_events: int = 0
    success_count: int = 0
    total_processing_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_events > 0:
            return self.success_count / self.total_events
        return 0.0

    @property
    def avg_processing_ms(self) -> float:
        if self.total_events > 0:
            return self.total_processing_ms / self.total_events
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "total_events": self.total_events,
            "success_count": self.success_count,
            "total_processing_ms": round(self.total_processing_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "avg_processing_ms": round(self.avg_processing_ms, 2),
        }


@dataclass
class EventAnalyticsStats:
    """Overall event analytics statistics."""

    total_events: int = 0
    unique_event_types: int = 0
    unique_sources: int = 0
    overall_success_rate: float = 0.0
    avg_processing_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# =============================================================================
# Event Analytics
# =============================================================================


class EventAnalytics:
    """
    Event stream analytics with bounded history.

    Features:
    - Record events with type, source, processing time, and success status
    - Per-type aggregated metrics (success rate, avg processing time)
    - FIFO eviction when event history exceeds max_events
    - Query by type, source, or recent history
    - Thread-safe via threading.Lock()
    """

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._max_events = max_events
        self._events: list[EventRecord] = []
        self._type_metrics: dict[str, EventTypeMetrics] = {}
        self._counter = 1
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_event(
        self,
        event_type: str,
        source: str = "",
        processing_time_ms: float = 0.0,
        success: bool = True,
    ) -> EventRecord:
        """Record an event and update aggregated type metrics.

        Args:
            event_type: Type identifier for the event.
            source: Origin of the event (agent, module, etc.).
            processing_time_ms: Time taken to process the event.
            success: Whether the event was processed successfully.

        Returns:
            The created EventRecord.
        """
        with self._lock:
            event_id = f"ev_{self._counter:06d}"
            self._counter += 1

            record = EventRecord(
                event_id=event_id,
                event_type=event_type,
                source=source,
                processing_time_ms=processing_time_ms,
                success=success,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # FIFO eviction
            if len(self._events) >= self._max_events:
                self._events.pop(0)
            self._events.append(record)

            # Update type metrics
            if event_type not in self._type_metrics:
                self._type_metrics[event_type] = EventTypeMetrics(event_type=event_type)
            m = self._type_metrics[event_type]
            m.total_events += 1
            if success:
                m.success_count += 1
            m.total_processing_ms += processing_time_ms

        return record

    # =========================================================================
    # Type Metrics Queries
    # =========================================================================

    def get_type_metrics(self, event_type: str) -> EventTypeMetrics | None:
        """Get aggregated metrics for a specific event type."""
        with self._lock:
            return self._type_metrics.get(event_type)

    def get_all_type_metrics(self) -> list[EventTypeMetrics]:
        """Return all type metrics sorted by total_events descending."""
        with self._lock:
            return sorted(
                self._type_metrics.values(),
                key=lambda m: m.total_events,
                reverse=True,
            )

    # =========================================================================
    # Event Queries
    # =========================================================================

    def get_recent_events(self, limit: int = 10, event_type: str | None = None) -> list[EventRecord]:
        """Return last N events, optionally filtered by event type.

        Args:
            limit: Maximum number of events to return.
            event_type: If provided, only return events of this type.

        Returns:
            List of EventRecord in reverse chronological order (newest first).
        """
        with self._lock:
            if event_type is not None:
                filtered = [ev for ev in self._events if ev.event_type == event_type]
            else:
                filtered = list(self._events)
            return list(reversed(filtered[-limit:]))

    def get_events_by_source(self, source: str) -> list[EventRecord]:
        """Return all events from a specific source."""
        with self._lock:
            return [ev for ev in self._events if ev.source == source]

    # =========================================================================
    # Listing
    # =========================================================================

    def list_event_types(self) -> list[str]:
        """Return sorted list of all tracked event types."""
        with self._lock:
            return sorted(self._type_metrics.keys())

    def list_sources(self) -> list[str]:
        """Return sorted list of all unique sources from event history."""
        with self._lock:
            return sorted(set(ev.source for ev in self._events))

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> EventAnalyticsStats:
        """Compute overall event analytics statistics."""
        with self._lock:
            total = len(self._events)
            unique_types = len(self._type_metrics)
            unique_sources = len(set(ev.source for ev in self._events))

            successes = sum(1 for ev in self._events if ev.success)
            overall_success_rate = successes / total if total > 0 else 0.0

            total_processing = sum(ev.processing_time_ms for ev in self._events)
            avg_processing = total_processing / total if total > 0 else 0.0

            return EventAnalyticsStats(
                total_events=total,
                unique_event_types=unique_types,
                unique_sources=unique_sources,
                overall_success_rate=overall_success_rate,
                avg_processing_ms=avg_processing,
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def event_count(self) -> int:
        """Number of event records currently stored."""
        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        """Reset all analytics state."""
        with self._lock:
            self._events.clear()
            self._type_metrics.clear()
            self._counter = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize analytics state to dict.

        Note: get_stats(), get_all_type_metrics(), and get_recent_events()
        are called BEFORE acquiring self._lock to avoid deadlock
        (threading.Lock is not reentrant).
        """
        stats = self.get_stats()
        all_metrics = self.get_all_type_metrics()
        recent = self.get_recent_events(limit=20)
        with self._lock:
            return {
                "max_events": self._max_events,
                "event_count": len(self._events),
                "stats": stats.to_dict(),
                "type_metrics": [m.to_dict() for m in all_metrics],
                "recent_events": [ev.to_dict() for ev in recent],
            }


# =============================================================================
# Global Instance
# =============================================================================

_instance: EventAnalytics | None = None
_lock = threading.Lock()


def get_event_analytics() -> EventAnalytics:
    """Get or create the global event analytics singleton."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = EventAnalytics()
    return _instance


def reset_event_analytics() -> None:
    """Reset the global event analytics singleton (for testing)."""
    global _instance
    with _lock:
        _instance = None
