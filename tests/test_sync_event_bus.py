"""
Tests for V12.4 Sync Event Bus (core/utils/event_bus.py).

Validates:
- Event creation and serialization
- Subscribe/unsubscribe
- Emit and handler invocation
- Wildcard topic matching
- Handler priority ordering
- Once (one-shot) subscriptions
- Source filtering
- Event history tracking
- Error handling in handlers
- Global singleton
- Module exports
"""

from core.utils.event_bus import (
    EmitResult,
    Event,
    EventBus,
    Subscription,
    get_event_bus,
    reset_event_bus,
)

# =============================================================================
# Event Tests
# =============================================================================


class TestEvent:
    """Test Event dataclass."""

    def test_basic_creation(self):
        e = Event(topic="llm.response", data={"tokens": 500})
        assert e.topic == "llm.response"
        assert e.data == {"tokens": 500}
        assert e.event_id

    def test_auto_timestamp(self):
        e = Event(topic="test")
        assert e.timestamp > 0

    def test_to_dict(self):
        e = Event(topic="llm.response", data="hello", source="claude")
        d = e.to_dict()
        assert d["topic"] == "llm.response"
        assert d["source"] == "claude"


# =============================================================================
# Subscription Tests
# =============================================================================


class TestSubscription:
    """Test Subscription matching."""

    def test_exact_match(self):
        sub = Subscription(sub_id="s1", pattern="llm.response", handler=lambda e: None)
        assert sub.matches("llm.response") is True
        assert sub.matches("llm.error") is False

    def test_wildcard_match(self):
        sub = Subscription(sub_id="s1", pattern="llm.*", handler=lambda e: None)
        assert sub.matches("llm.response") is True
        assert sub.matches("llm.error") is True
        assert sub.matches("fsm.transition") is False

    def test_catch_all(self):
        sub = Subscription(sub_id="s1", pattern="*", handler=lambda e: None)
        assert sub.matches("anything") is True

    def test_source_filter(self):
        sub = Subscription(
            sub_id="s1",
            pattern="llm.*",
            handler=lambda e: None,
            source_filter="claude",
        )
        assert sub.matches("llm.response", "claude") is True
        assert sub.matches("llm.response", "gemini") is False


# =============================================================================
# Subscribe/Unsubscribe Tests
# =============================================================================


class TestSubscribeUnsubscribe:
    """Test subscription management."""

    def test_on(self):
        bus = EventBus()
        sub_id = bus.on("test", lambda e: None)
        assert sub_id
        assert bus.subscription_count == 1

    def test_off(self):
        bus = EventBus()
        sub_id = bus.on("test", lambda e: None)
        assert bus.off(sub_id) is True
        assert bus.subscription_count == 0

    def test_off_not_found(self):
        bus = EventBus()
        assert bus.off("nonexistent") is False

    def test_off_all(self):
        bus = EventBus()
        bus.on("a", lambda e: None)
        bus.on("b", lambda e: None)
        bus.on("c", lambda e: None)
        count = bus.off_all()
        assert count == 3
        assert bus.subscription_count == 0

    def test_off_all_by_pattern(self):
        bus = EventBus()
        bus.on("llm.*", lambda e: None)
        bus.on("llm.*", lambda e: None)
        bus.on("fsm.*", lambda e: None)
        count = bus.off_all("llm.*")
        assert count == 2
        assert bus.subscription_count == 1


# =============================================================================
# Emit Tests
# =============================================================================


class TestEmit:
    """Test event emission."""

    def test_basic_emit(self):
        bus = EventBus()
        received = []
        bus.on("test", lambda e: received.append(e.data))
        result = bus.emit("test", "hello")
        assert result.handlers_called == 1
        assert received == ["hello"]

    def test_emit_no_subscribers(self):
        bus = EventBus()
        result = bus.emit("test", "hello")
        assert result.handlers_called == 0
        assert result.success is True

    def test_emit_multiple_handlers(self):
        bus = EventBus()
        received = []
        bus.on("test", lambda e: received.append("a"))
        bus.on("test", lambda e: received.append("b"))
        result = bus.emit("test")
        assert result.handlers_called == 2
        assert len(received) == 2

    def test_emit_wildcard_match(self):
        bus = EventBus()
        received = []
        bus.on("llm.*", lambda e: received.append(e.topic))
        bus.emit("llm.response")
        bus.emit("llm.error")
        bus.emit("fsm.transition")
        assert received == ["llm.response", "llm.error"]

    def test_emit_with_source(self):
        bus = EventBus()
        received = []
        bus.on("test", lambda e: received.append(e.source), source_filter="claude")
        bus.emit("test", source="claude")
        bus.emit("test", source="gemini")
        assert received == ["claude"]

    def test_emit_count(self):
        bus = EventBus()
        bus.emit("a")
        bus.emit("b")
        bus.emit("c")
        assert bus.emit_count == 3


# =============================================================================
# Priority Tests
# =============================================================================


class TestPriority:
    """Test handler priority ordering."""

    def test_priority_order(self):
        bus = EventBus()
        order = []
        bus.on("test", lambda e: order.append("low"), priority=100)
        bus.on("test", lambda e: order.append("high"), priority=10)
        bus.on("test", lambda e: order.append("mid"), priority=50)
        bus.emit("test")
        assert order == ["high", "mid", "low"]


# =============================================================================
# Once Tests
# =============================================================================


class TestOnce:
    """Test one-shot subscriptions."""

    def test_once_fires_once(self):
        bus = EventBus()
        received = []
        bus.once("test", lambda e: received.append(e.data))
        bus.emit("test", "first")
        bus.emit("test", "second")
        assert received == ["first"]

    def test_once_auto_unsubscribes(self):
        bus = EventBus()
        bus.once("test", lambda e: None)
        assert bus.subscription_count == 1
        bus.emit("test")
        assert bus.subscription_count == 0


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling in handlers."""

    def test_handler_error_captured(self):
        bus = EventBus()

        def bad_handler(e):
            raise ValueError("boom")

        bus.on("test", bad_handler)
        result = bus.emit("test")
        assert result.success is False
        assert len(result.errors) == 1
        assert "boom" in result.errors[0]

    def test_error_doesnt_stop_other_handlers(self):
        bus = EventBus()
        received = []

        def bad_handler(e):
            raise ValueError("boom")

        bus.on("test", bad_handler, priority=10)
        bus.on("test", lambda e: received.append("ok"), priority=20)
        result = bus.emit("test")
        assert result.handlers_called == 2
        assert received == ["ok"]


# =============================================================================
# History Tests
# =============================================================================


class TestHistory:
    """Test event history."""

    def test_history_captured(self):
        bus = EventBus()
        bus.emit("test.a", "data_a")
        bus.emit("test.b", "data_b")
        assert bus.history_size == 2

    def test_get_history(self):
        bus = EventBus()
        bus.emit("test.a")
        bus.emit("test.b")
        history = bus.get_history()
        assert len(history) == 2
        assert history[0].topic == "test.b"

    def test_get_history_by_topic(self):
        bus = EventBus()
        bus.emit("llm.response")
        bus.emit("fsm.transition")
        bus.emit("llm.error")
        history = bus.get_history(topic="llm.*")
        assert len(history) == 2

    def test_get_history_limit(self):
        bus = EventBus()
        for i in range(10):
            bus.emit(f"test.{i}")
        history = bus.get_history(limit=3)
        assert len(history) == 3

    def test_history_max_size(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.emit(f"test.{i}")
        assert bus.history_size == 5

    def test_history_disabled(self):
        bus = EventBus(capture_history=False)
        bus.emit("test")
        assert bus.history_size == 0

    def test_get_topics(self):
        bus = EventBus()
        bus.emit("llm.response")
        bus.emit("fsm.transition")
        bus.emit("llm.response")
        topics = bus.get_topics()
        assert topics == ["fsm.transition", "llm.response"]

    def test_clear_history(self):
        bus = EventBus()
        bus.emit("test")
        count = bus.clear_history()
        assert count == 1
        assert bus.history_size == 0


# =============================================================================
# EmitResult Tests
# =============================================================================


class TestEmitResult:
    """Test EmitResult dataclass."""

    def test_success(self):
        r = EmitResult(event_id="e1", topic="test", handlers_called=2)
        assert r.success is True

    def test_failure(self):
        r = EmitResult(event_id="e1", topic="test", handlers_called=1, errors=["boom"])
        assert r.success is False

    def test_to_dict(self):
        r = EmitResult(event_id="e1", topic="test", handlers_called=1)
        d = r.to_dict()
        assert d["topic"] == "test"
        assert d["success"] is True


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global event bus."""

    def test_get_event_bus(self):
        reset_event_bus()
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    def test_singleton(self):
        reset_event_bus()
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset(self):
        reset_event_bus()
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2


# =============================================================================
# State Export Tests
# =============================================================================


class TestStateExport:
    """Test state export."""

    def test_to_dict(self):
        bus = EventBus()
        bus.on("test", lambda e: None)
        bus.emit("test")
        d = bus.to_dict()
        assert d["subscription_count"] == 1
        assert d["emit_count"] == 1
        assert d["history_size"] == 1


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_utils_package(self):
        from core.utils import Event, EventBus, get_event_bus, reset_event_bus

        assert all([EventBus, Event, get_event_bus, reset_event_bus])

    def test_from_module(self):
        from core.utils.event_bus import (
            EmitResult,
            Event,
            EventBus,
            Subscription,
        )

        assert all([EventBus, Event, Subscription, EmitResult])
