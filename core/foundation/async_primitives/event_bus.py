"""
Event Bus - V9.5

Lightweight async event bus for decoupled communication between
HiveMind, Swarm, and OrchestratorSyncBridge.

Advantages over direct sync calls:
- Avoids deadlocks in async scenarios
- Decouples components (no circular imports)
- Scales better for N-agent architectures
- Enables event replay for debugging

Usage:
    bus = EventBus()

    # Subscribe to events
    async def on_checkpoint(event: SyncEvent):
        print(f"Checkpoint: {event.payload}")

    bus.subscribe("checkpoint", on_checkpoint)

    # Publish events
    await bus.publish(SyncEvent(
        event_type="checkpoint",
        source="hive_mind",
        task_id="task_123",
        payload={"phase": "EXECUTION"},
        timestamp=time.time()
    ))

References:
- AWS Saga Orchestration Patterns
- Event-Driven Architecture best practices
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Standard event types for NEXUS orchestration."""

    # Checkpoint events
    CHECKPOINT_CREATED = "checkpoint_created"
    CHECKPOINT_VALIDATED = "checkpoint_validated"
    CHECKPOINT_FAILED = "checkpoint_failed"

    # Rollback events
    ROLLBACK_REQUESTED = "rollback_requested"
    ROLLBACK_COMPLETED = "rollback_completed"
    ROLLBACK_FAILED = "rollback_failed"

    # State sync events
    STATE_CHANGE = "state_change"
    STATE_MISMATCH = "state_mismatch"

    # System events
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    CIRCUIT_BREAKER_CLOSE = "circuit_breaker_close"
    FALLBACK_ACTIVATED = "fallback_activated"

    # Task events
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


@dataclass
class SyncEvent:
    """
    Event for synchronization between HiveMind/Swarm.

    Attributes:
        event_type: Type of event (from EventType enum or string)
        source: Origin component ("hive_mind", "swarm", "sync_bridge")
        task_id: Unified task ID for correlation
        payload: Event-specific data
        timestamp: Unix timestamp of event creation
        correlation_id: Optional ID for request/response correlation
    """

    event_type: str
    source: str
    task_id: str
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    correlation_id: str | None = None

    def __post_init__(self):
        # Convert enum to string if needed
        if isinstance(self.event_type, EventType):
            self.event_type = self.event_type.value


# Type alias for event handlers
EventHandler = Callable[[SyncEvent], Coroutine[Any, Any, None]]


class EventBus:
    """
    Lightweight async event bus.

    Features:
    - Pub/sub pattern with async handlers
    - Optional bounded queue for backpressure
    - Event history for debugging
    - Handler timeout protection
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        handler_timeout: float = 30.0,
        keep_history: bool = True,
        max_history: int = 100,
    ):
        """
        Initialize EventBus.

        Args:
            max_queue_size: Max events in queue (backpressure)
            handler_timeout: Timeout for handler execution
            keep_history: Whether to keep event history
            max_history: Max events in history
        """
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._handler_timeout = handler_timeout
        self._keep_history = keep_history
        self._max_history = max_history
        self._history: list[SyncEvent] = []
        self._processing = False
        self._stats = {
            "published": 0,
            "delivered": 0,
            "failed": 0,
            "dropped": 0,
        }

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Subscribe to an event type.

        Args:
            event_type: Event type to subscribe to (string or EventType.value)
            handler: Async function to handle the event
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value

        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append(handler)
        logger.debug(f"EventBus: Subscribed handler to '{event_type}'")

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """
        Unsubscribe from an event type.

        Returns:
            True if handler was removed, False if not found
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value

        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False

    async def publish(self, event: SyncEvent) -> bool:
        """
        Publish an event to all subscribers.

        Args:
            event: The event to publish

        Returns:
            True if event was delivered to at least one handler
        """
        self._stats["published"] += 1

        # Keep history if enabled
        if self._keep_history:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)

        # Get handlers for this event type
        handlers = self._subscribers.get(event.event_type, [])

        if not handlers:
            logger.debug(f"EventBus: No handlers for '{event.event_type}'")
            return False

        # Execute handlers
        delivered = 0
        for handler in handlers:
            try:
                await asyncio.wait_for(
                    handler(event),
                    timeout=self._handler_timeout,
                )
                delivered += 1
            except TimeoutError:
                logger.error(f"EventBus: Handler for '{event.event_type}' timed out (>{self._handler_timeout}s)")
                self._stats["failed"] += 1
            except Exception as e:
                logger.error(f"EventBus: Handler for '{event.event_type}' failed: {e}")
                self._stats["failed"] += 1

        self._stats["delivered"] += delivered
        return delivered > 0

    async def publish_and_wait(
        self,
        event: SyncEvent,
        response_type: str,
        timeout: float = 30.0,
    ) -> SyncEvent | None:
        """
        Publish an event and wait for a response event.

        Useful for request/response patterns.

        Args:
            event: Event to publish
            response_type: Event type to wait for
            timeout: Max wait time

        Returns:
            Response event or None if timeout
        """
        response_future: asyncio.Future = asyncio.Future()

        async def response_handler(response_event: SyncEvent):
            if response_event.correlation_id == event.correlation_id and not response_future.done():
                response_future.set_result(response_event)

        # Subscribe temporarily
        self.subscribe(response_type, response_handler)

        try:
            # Publish request
            await self.publish(event)

            # Wait for response
            return await asyncio.wait_for(response_future, timeout=timeout)
        except TimeoutError:
            logger.warning(f"EventBus: Timeout waiting for '{response_type}' (correlation_id={event.correlation_id})")
            return None
        finally:
            self.unsubscribe(response_type, response_handler)

    def get_history(
        self,
        event_type: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[SyncEvent]:
        """
        Get event history with optional filters.

        Args:
            event_type: Filter by event type
            task_id: Filter by task ID
            limit: Max events to return

        Returns:
            List of matching events (most recent first)
        """
        events = self._history.copy()
        events.reverse()

        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if task_id:
            events = [e for e in events if e.task_id == task_id]

        return events[:limit]

    def get_stats(self) -> dict[str, int]:
        """Get event bus statistics."""
        return {
            **self._stats,
            "subscribers": sum(len(h) for h in self._subscribers.values()),
            "history_size": len(self._history),
        }

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "published": 0,
            "delivered": 0,
            "failed": 0,
            "dropped": 0,
        }


# Global singleton for easy access
_global_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global EventBus instance."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> None:
    """Reset the global EventBus (for testing)."""
    global _global_bus
    _global_bus = None
