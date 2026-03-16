"""
Tests for core/async_primitives/event_bus.py - V9.5

Validates lightweight async pub/sub EventBus.
"""

import asyncio
from unittest.mock import patch

import pytest

from core.foundation.async_primitives.event_bus import (
    EventBus,
    EventType,
    SyncEvent,
    get_event_bus,
    reset_event_bus,
)


@pytest.fixture(autouse=True)
def reset_bus():
    """Reset global EventBus before each test."""
    reset_event_bus()
    yield
    reset_event_bus()


class TestSyncEvent:
    """Test SyncEvent dataclass."""

    def test_create_event(self):
        """SyncEvent should be created with required fields."""
        event = SyncEvent(
            event_type="checkpoint",
            source="hive_mind",
            task_id="task_123",
            payload={"phase": "EXECUTION"},
        )

        assert event.event_type == "checkpoint"
        assert event.source == "hive_mind"
        assert event.task_id == "task_123"
        assert event.payload["phase"] == "EXECUTION"
        assert event.timestamp > 0

    def test_event_with_enum_type(self):
        """SyncEvent should accept EventType enum."""
        event = SyncEvent(
            event_type=EventType.CHECKPOINT_CREATED,
            source="swarm",
            task_id="task_456",
            payload={},
        )

        # Should be converted to string
        assert event.event_type == "checkpoint_created"

    def test_event_with_correlation_id(self):
        """SyncEvent should support correlation_id."""
        event = SyncEvent(
            event_type="request",
            source="test",
            task_id="t1",
            payload={},
            correlation_id="corr_123",
        )

        assert event.correlation_id == "corr_123"


class TestEventType:
    """Test EventType enum."""

    def test_checkpoint_events_exist(self):
        """Checkpoint events should be defined."""
        assert EventType.CHECKPOINT_CREATED
        assert EventType.CHECKPOINT_VALIDATED
        assert EventType.CHECKPOINT_FAILED

    def test_rollback_events_exist(self):
        """Rollback events should be defined."""
        assert EventType.ROLLBACK_REQUESTED
        assert EventType.ROLLBACK_COMPLETED
        assert EventType.ROLLBACK_FAILED

    def test_circuit_breaker_events_exist(self):
        """Circuit breaker events should be defined."""
        assert EventType.CIRCUIT_BREAKER_OPEN
        assert EventType.CIRCUIT_BREAKER_CLOSE
        assert EventType.FALLBACK_ACTIVATED


class TestEventBusBasics:
    """Basic EventBus functionality."""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        """Basic subscribe/publish should work."""
        bus = EventBus()
        received = []

        async def handler(event: SyncEvent):
            received.append(event)

        bus.subscribe("test_event", handler)

        event = SyncEvent(
            event_type="test_event",
            source="test",
            task_id="t1",
            payload={"value": 42},
        )

        result = await bus.publish(event)

        assert result is True
        assert len(received) == 1
        assert received[0].payload["value"] == 42

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        """Multiple handlers should all receive events."""
        bus = EventBus()
        received_a = []
        received_b = []

        async def handler_a(event):
            received_a.append(event)

        async def handler_b(event):
            received_b.append(event)

        bus.subscribe("multi", handler_a)
        bus.subscribe("multi", handler_b)

        await bus.publish(
            SyncEvent(
                event_type="multi",
                source="test",
                task_id="t1",
                payload={},
            )
        )

        assert len(received_a) == 1
        assert len(received_b) == 1

    @pytest.mark.asyncio
    async def test_no_handlers_returns_false(self):
        """Publishing to no handlers should return False."""
        bus = EventBus()

        result = await bus.publish(
            SyncEvent(
                event_type="no_handlers",
                source="test",
                task_id="t1",
                payload={},
            )
        )

        assert result is False


class TestEventBusUnsubscribe:
    """Unsubscribe functionality."""

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Unsubscribed handlers should not receive events."""
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("unsub_test", handler)

        # First publish - should receive
        await bus.publish(
            SyncEvent(
                event_type="unsub_test",
                source="test",
                task_id="t1",
                payload={},
            )
        )
        assert len(received) == 1

        # Unsubscribe
        result = bus.unsubscribe("unsub_test", handler)
        assert result is True

        # Second publish - should not receive
        await bus.publish(
            SyncEvent(
                event_type="unsub_test",
                source="test",
                task_id="t2",
                payload={},
            )
        )
        assert len(received) == 1  # Still 1

    def test_unsubscribe_not_found(self):
        """Unsubscribing unknown handler should return False."""
        bus = EventBus()

        async def handler(event):
            pass

        result = bus.unsubscribe("unknown", handler)
        assert result is False


class TestEventBusHistory:
    """Event history functionality."""

    @pytest.mark.asyncio
    async def test_history_kept(self):
        """Published events should be kept in history."""
        bus = EventBus(keep_history=True)

        await bus.publish(
            SyncEvent(
                event_type="history_test",
                source="test",
                task_id="t1",
                payload={"seq": 1},
            )
        )
        await bus.publish(
            SyncEvent(
                event_type="history_test",
                source="test",
                task_id="t2",
                payload={"seq": 2},
            )
        )

        history = bus.get_history()
        assert len(history) == 2
        # Most recent first
        assert history[0].payload["seq"] == 2

    @pytest.mark.asyncio
    async def test_history_filter_by_type(self):
        """History should be filterable by event type."""
        bus = EventBus()

        await bus.publish(SyncEvent(event_type="type_a", source="t", task_id="1", payload={}))
        await bus.publish(SyncEvent(event_type="type_b", source="t", task_id="2", payload={}))
        await bus.publish(SyncEvent(event_type="type_a", source="t", task_id="3", payload={}))

        history = bus.get_history(event_type="type_a")
        assert len(history) == 2
        assert all(e.event_type == "type_a" for e in history)

    @pytest.mark.asyncio
    async def test_history_filter_by_task_id(self):
        """History should be filterable by task_id."""
        bus = EventBus()

        await bus.publish(SyncEvent(event_type="x", source="t", task_id="task_1", payload={}))
        await bus.publish(SyncEvent(event_type="x", source="t", task_id="task_2", payload={}))
        await bus.publish(SyncEvent(event_type="x", source="t", task_id="task_1", payload={}))

        history = bus.get_history(task_id="task_1")
        assert len(history) == 2
        assert all(e.task_id == "task_1" for e in history)

    def test_clear_history(self):
        """clear_history should remove all history."""
        bus = EventBus()
        bus._history = [SyncEvent(event_type="x", source="t", task_id="1", payload={})]

        bus.clear_history()
        assert len(bus.get_history()) == 0


class TestEventBusStats:
    """Statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_published_count(self):
        """Stats should track published events."""
        bus = EventBus()

        await bus.publish(SyncEvent(event_type="s", source="t", task_id="1", payload={}))
        await bus.publish(SyncEvent(event_type="s", source="t", task_id="2", payload={}))

        stats = bus.get_stats()
        assert stats["published"] == 2

    @pytest.mark.asyncio
    async def test_stats_delivered_count(self):
        """Stats should track delivered events."""
        bus = EventBus()

        async def handler(e):
            pass

        bus.subscribe("delivered_test", handler)

        await bus.publish(SyncEvent(event_type="delivered_test", source="t", task_id="1", payload={}))

        stats = bus.get_stats()
        assert stats["delivered"] >= 1

    def test_reset_stats(self):
        """reset_stats should clear all counters."""
        bus = EventBus()
        bus._stats["published"] = 100

        bus.reset_stats()
        assert bus.get_stats()["published"] == 0


class TestEventBusErrorHandling:
    """Error handling in handlers."""

    @pytest.mark.asyncio
    async def test_handler_exception_logged(self):
        """Handler exceptions should be logged."""
        bus = EventBus()

        async def failing_handler(event):
            raise RuntimeError("Handler error")

        bus.subscribe("fail_test", failing_handler)

        with patch("core.foundation.async_primitives.event_bus.logger") as mock_logger:
            await bus.publish(SyncEvent(event_type="fail_test", source="t", task_id="1", payload={}))
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_handler_timeout_logged(self):
        """Slow handlers should be timed out."""
        bus = EventBus(handler_timeout=0.1)

        async def slow_handler(event):
            await asyncio.sleep(1.0)  # Much longer than timeout

        bus.subscribe("slow_test", slow_handler)

        with patch("core.foundation.async_primitives.event_bus.logger") as mock_logger:
            await bus.publish(SyncEvent(event_type="slow_test", source="t", task_id="1", payload={}))
            # Should have logged timeout error
            mock_logger.error.assert_called()
            call_str = str(mock_logger.error.call_args)
            assert "timed out" in call_str.lower() or "timeout" in call_str.lower()


class TestEventBusPublishAndWait:
    """Request/response pattern tests."""

    @pytest.mark.asyncio
    async def test_publish_and_wait_success(self):
        """publish_and_wait should receive response."""
        bus = EventBus()

        async def responder(event):
            # Simulate response
            await bus.publish(
                SyncEvent(
                    event_type="response",
                    source="responder",
                    task_id=event.task_id,
                    payload={"answer": 42},
                    correlation_id=event.correlation_id,
                )
            )

        bus.subscribe("request", responder)

        request = SyncEvent(
            event_type="request",
            source="requester",
            task_id="t1",
            payload={"question": "?"},
            correlation_id="corr_1",
        )

        response = await bus.publish_and_wait(request, "response", timeout=1.0)

        assert response is not None
        assert response.payload["answer"] == 42

    @pytest.mark.asyncio
    async def test_publish_and_wait_timeout(self):
        """publish_and_wait should return None on timeout."""
        bus = EventBus()

        request = SyncEvent(
            event_type="no_response",
            source="requester",
            task_id="t1",
            payload={},
            correlation_id="corr_2",
        )

        response = await bus.publish_and_wait(request, "response", timeout=0.1)

        assert response is None


class TestGlobalEventBus:
    """Global singleton EventBus."""

    def test_get_event_bus_singleton(self):
        """get_event_bus should return same instance."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset_event_bus(self):
        """reset_event_bus should create new instance."""
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2
