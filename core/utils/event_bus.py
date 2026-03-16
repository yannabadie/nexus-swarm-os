"""
Event Bus - Lightweight publish/subscribe for inter-module communication.

V12.4 COGNITIVE BOOST - Task #46

Decouples NEXUS modules by allowing publish/subscribe communication
without direct imports. Modules emit events, other modules react.

Supports:
- Typed event topics
- Sync and async handler registration
- Event history for debugging
- Wildcard subscriptions
- Handler priority ordering

Usage:
    from core.utils.event_bus import EventBus, get_event_bus

    bus = get_event_bus()

    # Subscribe
    bus.on("llm.response", lambda event: print(event.data))
    bus.on("llm.*", lambda event: log_all_llm_events(event))

    # Publish
    bus.emit("llm.response", {"model": "claude", "tokens": 500})
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_HISTORY = 1000
DEFAULT_PRIORITY = 50


# =============================================================================
# Types
# =============================================================================


@dataclass
class Event:
    """An event emitted on the bus."""

    topic: str
    data: Any = None
    event_id: str = ""
    timestamp: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.event_id:
            self.event_id = uuid.uuid4().hex[:12]
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "data": str(self.data)[:200] if self.data is not None else None,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class Subscription:
    """A registered event handler."""

    sub_id: str
    pattern: str  # topic pattern (supports * wildcard)
    handler: Callable[[Event], Any]
    priority: int = DEFAULT_PRIORITY
    once: bool = False  # fire once then auto-unsubscribe
    source_filter: str = ""  # only events from this source

    def matches(self, topic: str, source: str = "") -> bool:
        """Check if this subscription matches a topic."""
        if self.source_filter and source != self.source_filter:
            return False
        return fnmatch.fnmatch(topic, self.pattern)


@dataclass
class EmitResult:
    """Result of emitting an event."""

    event_id: str
    topic: str
    handlers_called: int
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "handlers_called": self.handlers_called,
            "success": self.success,
            "errors": self.errors,
        }


# =============================================================================
# Event Bus
# =============================================================================


class EventBus:
    """
    Lightweight publish/subscribe event bus.

    Thread-safe. Supports wildcard topic patterns.
    Handlers are called synchronously in priority order.
    """

    def __init__(
        self,
        *,
        max_history: int = MAX_HISTORY,
        capture_history: bool = True,
    ):
        self._subscriptions: list[Subscription] = []
        self._history: list[Event] = []
        self._max_history = max_history
        self._capture_history = capture_history
        self._lock = threading.Lock()
        self._emit_count = 0

    # =========================================================================
    # Subscribe
    # =========================================================================

    def on(
        self,
        pattern: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = DEFAULT_PRIORITY,
        source_filter: str = "",
    ) -> str:
        """
        Subscribe to events matching a pattern.

        Args:
            pattern: Topic pattern (supports * wildcard, e.g. "llm.*")
            handler: Callback function(event) -> Any
            priority: Handler priority (lower = called first)
            source_filter: Only events from this source

        Returns:
            Subscription ID (for unsubscribing)
        """
        sub_id = uuid.uuid4().hex[:12]
        sub = Subscription(
            sub_id=sub_id,
            pattern=pattern,
            handler=handler,
            priority=priority,
            source_filter=source_filter,
        )
        with self._lock:
            self._subscriptions.append(sub)
        return sub_id

    def once(
        self,
        pattern: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = DEFAULT_PRIORITY,
    ) -> str:
        """Subscribe to one event then auto-unsubscribe."""
        sub_id = uuid.uuid4().hex[:12]
        sub = Subscription(
            sub_id=sub_id,
            pattern=pattern,
            handler=handler,
            priority=priority,
            once=True,
        )
        with self._lock:
            self._subscriptions.append(sub)
        return sub_id

    def off(self, sub_id: str) -> bool:
        """
        Unsubscribe by subscription ID.

        Returns:
            True if found and removed
        """
        with self._lock:
            before = len(self._subscriptions)
            self._subscriptions = [s for s in self._subscriptions if s.sub_id != sub_id]
            return len(self._subscriptions) < before

    def off_all(self, pattern: str | None = None) -> int:
        """
        Remove all subscriptions, optionally filtered by pattern.

        Returns:
            Number of subscriptions removed
        """
        with self._lock:
            if pattern is None:
                count = len(self._subscriptions)
                self._subscriptions.clear()
                return count
            before = len(self._subscriptions)
            self._subscriptions = [s for s in self._subscriptions if s.pattern != pattern]
            return before - len(self._subscriptions)

    # =========================================================================
    # Emit
    # =========================================================================

    def emit(
        self,
        topic: str,
        data: Any = None,
        *,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> EmitResult:
        """
        Emit an event to all matching subscribers.

        Args:
            topic: Event topic (e.g. "llm.response")
            data: Event payload
            source: Source identifier
            metadata: Optional metadata

        Returns:
            EmitResult with handler count and errors
        """
        event = Event(
            topic=topic,
            data=data,
            source=source,
            metadata=metadata or {},
        )

        # Record in history
        if self._capture_history:
            with self._lock:
                self._history.append(event)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history :]

        # Find matching subscriptions
        with self._lock:
            matching = [s for s in self._subscriptions if s.matches(topic, source)]
            # Sort by priority
            matching.sort(key=lambda s: s.priority)

        # Call handlers
        errors = []
        to_remove = []

        for sub in matching:
            try:
                sub.handler(event)
            except Exception as e:
                errors.append(f"Handler {sub.sub_id}: {e}")

            if sub.once:
                to_remove.append(sub.sub_id)

        # Remove one-shot subscriptions
        if to_remove:
            with self._lock:
                self._subscriptions = [s for s in self._subscriptions if s.sub_id not in set(to_remove)]

        self._emit_count += 1

        return EmitResult(
            event_id=event.event_id,
            topic=topic,
            handlers_called=len(matching),
            errors=errors,
        )

    # =========================================================================
    # Queries
    # =========================================================================

    @property
    def subscription_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    @property
    def emit_count(self) -> int:
        return self._emit_count

    @property
    def history_size(self) -> int:
        with self._lock:
            return len(self._history)

    def get_history(
        self,
        *,
        topic: str | None = None,
        limit: int = 50,
    ) -> list[Event]:
        """
        Get event history.

        Args:
            topic: Filter by topic pattern
            limit: Max events to return

        Returns:
            List of events (most recent first)
        """
        with self._lock:
            events = list(reversed(self._history))

        if topic:
            events = [e for e in events if fnmatch.fnmatch(e.topic, topic)]

        return events[:limit]

    def get_topics(self) -> list[str]:
        """Get all topics that have been emitted."""
        with self._lock:
            return sorted(set(e.topic for e in self._history))

    def clear_history(self) -> int:
        """Clear event history."""
        with self._lock:
            count = len(self._history)
            self._history.clear()
            return count

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscription_count": self.subscription_count,
            "emit_count": self._emit_count,
            "history_size": self.history_size,
            "capture_history": self._capture_history,
        }


# =============================================================================
# Global Instance
# =============================================================================

_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get or create the global event bus."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus


def reset_event_bus() -> None:
    """Reset the global event bus (for testing)."""
    global _bus
    _bus = None
