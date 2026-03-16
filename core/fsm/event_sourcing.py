"""
NEXUS V12.4 COGNITIVE BOOST - FSM Event Sourcing

Append-only event log for FSM state transitions.
Enables crash recovery by replaying transition history.

Architecture:
    FSM Transition
        -> TransitionEvent created
        -> Appended to event store (Redis stream or local file)
        -> Published to CEREBRO event bus (fire-and-forget)

    On Boot (crash recovery):
        -> Read event store
        -> Replay transitions to reconstruct state
        -> Resume from last known state

Event Store Backends:
    1. Redis Streams (production) - append-only, auto-trimmed
    2. JSONL file (development) - workspace/.nexus/fsm_events.jsonl

Usage:
    from core.fsm.event_sourcing import FSMEventStore, TransitionEvent

    store = FSMEventStore(workspace_path)
    store.append(TransitionEvent(
        from_state="IDLE",
        to_state="BRAINSTORMING",
        trigger="user_input",
    ))

    # On crash recovery:
    events = store.replay()
    last_state = events[-1].to_state if events else "IDLE"

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-15
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class TransitionEvent:
    """
    Immutable record of a single FSM state transition.

    Every state change in the orchestrator creates one of these.
    The append-only log of TransitionEvents is the source of truth
    for crash recovery.
    """

    from_state: str
    to_state: str
    trigger: str  # What caused the transition
    session_id: str | None = None  # Session UUID
    task_summary: str | None = None  # Human-readable task context
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_id: str = field(default_factory=lambda: uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransitionEvent:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class FSMEventStore:
    """
    Append-only event store for FSM transitions.

    Supports two backends:
    1. Local JSONL file (default, zero dependencies)
    2. Redis Streams (production, via connect_redis())

    The store automatically trims old events to prevent unbounded growth.
    Default retention: last 1000 events per session.
    """

    def __init__(
        self,
        workspace_path: Path | None = None,
        max_events: int = 1000,
    ):
        self._workspace = workspace_path or Path("workspace")
        self._max_events = max_events
        self._events_file = self._workspace / ".nexus" / "fsm_events.jsonl"
        self._redis = None
        self._redis_stream_key = "nexus:fsm:transitions"

        # Ensure directory exists
        self._events_file.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TransitionEvent) -> None:
        """
        Append a transition event to the store.

        Writes to both local file (always) and Redis (if connected).
        """
        json_line = event.to_json()

        # Always write to local file (backup)
        try:
            with open(self._events_file, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")
        except OSError as e:
            logger.warning(f"Failed to write FSM event to file: {e}")

        # Write to Redis if connected
        if self._redis:
            try:
                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    task = asyncio.ensure_future(self._append_redis(event))
                    task.add_done_callback(
                        lambda t: logger.warning("Redis FSM event write failed: %s", t.exception())
                        if t.exception()
                        else None
                    )
                else:
                    loop.run_until_complete(self._append_redis(event))
            except Exception as e:
                logger.warning("Redis FSM append failed: %s", e)

        # Publish to CEREBRO event bus (fire-and-forget)
        self._publish_to_cerebro(event)

        # V12.4: Emit OTel span for FSM transition
        try:
            from core.observability.telemetry.otel_provider import trace_fsm_transition

            trace_fsm_transition(
                from_state=event.from_state,
                to_state=event.to_state,
                trigger=event.trigger,
                session_id=event.session_id,
            )
        except Exception:
            pass  # Never block FSM for telemetry

        logger.debug(f"FSM event: {event.from_state} -> {event.to_state} [{event.trigger}]")

    async def _append_redis(self, event: TransitionEvent) -> None:
        """Append event to Redis Stream."""
        if not self._redis:
            return
        try:
            await self._redis.xadd(
                self._redis_stream_key,
                event.to_dict(),
                maxlen=self._max_events,
            )
        except Exception as e:
            logger.debug(f"Redis XADD failed: {e}")

    def _publish_to_cerebro(self, event: TransitionEvent) -> None:
        """Fire-and-forget publish to CEREBRO event bus."""
        try:
            from core.observability.events.redis_bus import get_redis_bus
            from core.observability.events.types import CerebroEvent, CerebroEventType

            cerebro_event = CerebroEvent(
                event_type=CerebroEventType.STATE_CHANGE,
                tenant_id="system",
                workspace_id="default",
                payload={
                    "from_state": event.from_state,
                    "to_state": event.to_state,
                    "trigger": event.trigger,
                    "session_id": event.session_id,
                },
            )

            bus = get_redis_bus()
            # Don't await - fire-and-forget
            import asyncio

            try:
                asyncio.get_running_loop()
                asyncio.ensure_future(bus.publish(cerebro_event))
            except RuntimeError:
                pass  # No running event loop - skip
        except Exception:
            pass  # Never block FSM for telemetry

    def replay(self, session_id: str | None = None) -> list[TransitionEvent]:
        """
        Replay all events from the store.

        Used for crash recovery: reads all events and returns them
        in chronological order. Optionally filter by session_id.

        Args:
            session_id: If provided, only return events for this session

        Returns:
            List of TransitionEvents in chronological order
        """
        events = []

        if not self._events_file.exists():
            return events

        try:
            with open(self._events_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        event = TransitionEvent.from_dict(data)
                        if session_id is None or event.session_id == session_id:
                            events.append(event)
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError as e:
            logger.warning(f"Failed to read FSM events: {e}")

        return events

    def get_last_state(self, session_id: str | None = None) -> str | None:
        """
        Get the last known FSM state from the event log.

        Used at boot to detect interrupted sessions.

        Returns:
            Last known state string, or None if no events found
        """
        events = self.replay(session_id=session_id)
        if events:
            return events[-1].to_state
        return None

    def get_interrupted_sessions(self) -> list[dict[str, Any]]:
        """
        Find sessions that were interrupted (not cleanly closed).

        A session is "interrupted" if its last event is NOT a terminal
        state (IDLE, WAITING_USER, ERROR, PANIC).

        Returns:
            List of interrupted session info dicts
        """
        terminal_states = {"IDLE", "WAITING_USER", "ERROR", "PANIC"}

        # Group events by session
        sessions: dict[str, list[TransitionEvent]] = {}
        for event in self.replay():
            sid = event.session_id or "unknown"
            sessions.setdefault(sid, []).append(event)

        interrupted = []
        for sid, events in sessions.items():
            last_event = events[-1]
            if last_event.to_state not in terminal_states:
                interrupted.append(
                    {
                        "session_id": sid,
                        "last_state": last_event.to_state,
                        "last_trigger": last_event.trigger,
                        "last_timestamp": last_event.timestamp,
                        "event_count": len(events),
                    }
                )

        return interrupted

    def trim(self, keep_last: int | None = None) -> int:
        """
        Trim the event store to keep only recent events.

        Args:
            keep_last: Number of events to keep (default: self._max_events)

        Returns:
            Number of events trimmed
        """
        keep = keep_last or self._max_events
        events = self.replay()

        if len(events) <= keep:
            return 0

        trimmed_count = len(events) - keep
        events_to_keep = events[-keep:]

        try:
            with open(self._events_file, "w", encoding="utf-8") as f:
                for event in events_to_keep:
                    f.write(event.to_json() + "\n")
        except OSError as e:
            logger.warning(f"Failed to trim FSM events: {e}")
            return 0

        return trimmed_count

    async def connect_redis(self, redis_url: str = "redis://localhost:6379") -> bool:
        """
        Connect to Redis for production event sourcing.

        Args:
            redis_url: Redis connection URL

        Returns:
            True if connected successfully
        """
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(redis_url)
            await self._redis.ping()
            logger.info(f"FSM EventStore connected to Redis: {redis_url}")
            return True
        except Exception as e:
            logger.debug(f"Redis connection failed: {e}")
            self._redis = None
            return False


# =============================================================================
# Module-level singleton
# =============================================================================

_global_store: FSMEventStore | None = None


def get_event_store(workspace_path: Path | None = None) -> FSMEventStore:
    """Get or create the global FSM event store."""
    global _global_store
    if _global_store is None:
        _global_store = FSMEventStore(workspace_path)
    return _global_store


def record_transition(
    from_state: str,
    to_state: str,
    trigger: str,
    session_id: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Convenience function to record a state transition.

    Can be called from anywhere in the codebase:
        from core.fsm.event_sourcing import record_transition
        record_transition("IDLE", "BRAINSTORMING", "user_input")
    """
    store = get_event_store()
    event = TransitionEvent(
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        session_id=session_id,
        **kwargs,
    )
    store.append(event)
