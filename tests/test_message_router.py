"""
Tests for V12.4 Message Router.

Validates:
- RoutedMessage to_dict
- DeadLetter to_dict
- RouteResult to_dict
- QueueInfo to_dict
- RouterStats to_dict
- Agent registration (register, unregister, list)
- Routing (basic, dead letter on unknown, queue full)
- Broadcasting (basic, exclude sender)
- Receiving (receive, peek, pending, by topic)
- Dead letters (get, clear)
- Queue info
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.synapse.message_router import (
    DeadLetter,
    MessageRouter,
    QueueInfo,
    RoutedMessage,
    RouteResult,
    RouterStats,
    get_message_router,
    reset_message_router,
)

# =============================================================================
# RoutedMessage Tests
# =============================================================================


class TestRoutedMessage:
    """Test RoutedMessage dataclass."""

    def test_basic(self):
        m = RoutedMessage(message_id="", sender="claude", recipient="gemini")
        assert m.sender == "claude"
        assert len(m.message_id) > 0  # Auto-generated

    def test_auto_timestamp(self):
        m = RoutedMessage(message_id="m1", sender="a", recipient="b")
        assert m.timestamp > 0

    def test_to_dict(self):
        m = RoutedMessage(message_id="m1", sender="claude", recipient="gemini", topic="analysis")
        d = m.to_dict()
        assert d["sender"] == "claude"
        assert d["topic"] == "analysis"


# =============================================================================
# DeadLetter Tests
# =============================================================================


class TestDeadLetter:
    """Test DeadLetter dataclass."""

    def test_basic(self):
        msg = RoutedMessage(message_id="m1", sender="a", recipient="b")
        dl = DeadLetter(message=msg, reason="Not found")
        assert dl.reason == "Not found"

    def test_to_dict(self):
        msg = RoutedMessage(message_id="m1", sender="a", recipient="b")
        dl = DeadLetter(message=msg, reason="Queue full")
        d = dl.to_dict()
        assert d["reason"] == "Queue full"


# =============================================================================
# RouteResult Tests
# =============================================================================


class TestRouteResult:
    """Test RouteResult dataclass."""

    def test_success(self):
        r = RouteResult(success=True, message_id="m1")
        assert r.success is True

    def test_to_dict(self):
        r = RouteResult(success=False, error="Not found")
        d = r.to_dict()
        assert d["success"] is False


# =============================================================================
# QueueInfo Tests
# =============================================================================


class TestQueueInfo:
    """Test QueueInfo dataclass."""

    def test_to_dict(self):
        q = QueueInfo(agent_id="claude", pending=5, total_received=20, total_delivered=15)
        d = q.to_dict()
        assert d["pending"] == 5


# =============================================================================
# RouterStats Tests
# =============================================================================


class TestRouterStats:
    """Test RouterStats dataclass."""

    def test_to_dict(self):
        s = RouterStats(
            registered_agents=2, total_routed=100, total_delivered=90, total_dead_letters=10, total_broadcasts=5
        )
        d = s.to_dict()
        assert d["total_routed"] == 100


# =============================================================================
# Registration Tests
# =============================================================================


class TestRegistration:
    """Test agent registration."""

    def test_register(self):
        r = MessageRouter()
        assert r.register("claude") is True
        assert r.agent_count == 1

    def test_register_duplicate(self):
        r = MessageRouter()
        r.register("claude")
        assert r.register("claude") is False

    def test_unregister(self):
        r = MessageRouter()
        r.register("claude")
        assert r.unregister("claude") is True
        assert r.agent_count == 0

    def test_unregister_not_found(self):
        r = MessageRouter()
        assert r.unregister("missing") is False

    def test_is_registered(self):
        r = MessageRouter()
        r.register("claude")
        assert r.is_registered("claude") is True
        assert r.is_registered("missing") is False

    def test_list_agents(self):
        r = MessageRouter()
        r.register("gemini")
        r.register("claude")
        assert r.list_agents() == ["claude", "gemini"]  # Sorted


# =============================================================================
# Routing Tests
# =============================================================================


class TestRouting:
    """Test message routing."""

    def test_route_basic(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        result = r.route("claude", "gemini", payload={"data": "hello"})
        assert result.success is True
        assert len(result.message_id) > 0

    def test_route_unknown_recipient(self):
        r = MessageRouter()
        r.register("claude")
        result = r.route("claude", "unknown")
        assert result.success is False
        assert "not registered" in result.error

    def test_route_creates_dead_letter(self):
        r = MessageRouter()
        r.register("claude")
        r.route("claude", "unknown")
        assert len(r.get_dead_letters()) == 1

    def test_route_with_topic(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini", topic="analysis")
        msgs = r.get_by_topic("gemini", "analysis")
        assert len(msgs) == 1

    def test_route_with_priority(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini", priority=5)
        msgs = r.peek("gemini")
        assert msgs[0].priority == 5


# =============================================================================
# Broadcast Tests
# =============================================================================


class TestBroadcast:
    """Test message broadcasting."""

    def test_broadcast_basic(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.register("agent3")
        count = r.broadcast("claude", payload={"msg": "hi"})
        assert count == 2  # Excludes sender by default

    def test_broadcast_include_sender(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        count = r.broadcast("claude", exclude_sender=False)
        assert count == 2  # Includes sender

    def test_broadcast_with_topic(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.broadcast("claude", topic="status")
        msgs = r.get_by_topic("gemini", "status")
        assert len(msgs) == 1


# =============================================================================
# Receiving Tests
# =============================================================================


class TestReceiving:
    """Test message receiving."""

    def test_receive(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini", payload={"data": "test"})
        msgs = r.receive("gemini")
        assert len(msgs) == 1
        assert msgs[0].delivered is True
        assert msgs[0].payload["data"] == "test"

    def test_receive_empties_queue(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        r.receive("gemini")
        assert r.pending_count("gemini") == 0

    def test_receive_with_limit(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        r.route("claude", "gemini")
        r.route("claude", "gemini")
        msgs = r.receive("gemini", limit=2)
        assert len(msgs) == 2
        assert r.pending_count("gemini") == 1

    def test_receive_unregistered(self):
        r = MessageRouter()
        assert r.receive("unknown") == []

    def test_peek(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        msgs = r.peek("gemini")
        assert len(msgs) == 1
        assert r.pending_count("gemini") == 1  # Not consumed

    def test_peek_with_limit(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        r.route("claude", "gemini")
        msgs = r.peek("gemini", limit=1)
        assert len(msgs) == 1

    def test_pending_count(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        r.route("claude", "gemini")
        assert r.pending_count("gemini") == 2

    def test_pending_count_unregistered(self):
        r = MessageRouter()
        assert r.pending_count("unknown") == 0

    def test_get_by_topic(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini", topic="analysis")
        r.route("claude", "gemini", topic="debate")
        r.route("claude", "gemini", topic="analysis")
        msgs = r.get_by_topic("gemini", "analysis")
        assert len(msgs) == 2


# =============================================================================
# Dead Letter Tests
# =============================================================================


class TestDeadLetters:
    """Test dead letter handling."""

    def test_get_dead_letters(self):
        r = MessageRouter()
        r.route("a", "unknown")
        r.route("b", "unknown2")
        dls = r.get_dead_letters()
        assert len(dls) == 2

    def test_get_dead_letters_with_limit(self):
        r = MessageRouter()
        r.route("a", "x")
        r.route("b", "y")
        r.route("c", "z")
        dls = r.get_dead_letters(limit=2)
        assert len(dls) == 2

    def test_clear_dead_letters(self):
        r = MessageRouter()
        r.route("a", "unknown")
        count = r.clear_dead_letters()
        assert count == 1
        assert len(r.get_dead_letters()) == 0


# =============================================================================
# Queue Info Tests
# =============================================================================


class TestQueueInfoQuery:
    """Test queue info queries."""

    def test_get_queue_info(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        r.route("claude", "gemini")
        r.receive("gemini", limit=1)
        info = r.get_queue_info("gemini")
        assert info is not None
        assert info.pending == 1
        assert info.total_received == 2
        assert info.total_delivered == 1

    def test_get_queue_info_not_found(self):
        r = MessageRouter()
        assert r.get_queue_info("unknown") is None


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test router statistics."""

    def test_initial_stats(self):
        r = MessageRouter()
        stats = r.get_stats()
        assert stats.total_routed == 0

    def test_stats_after_work(self):
        r = MessageRouter()
        r.register("claude")
        r.register("gemini")
        r.route("claude", "gemini")
        r.route("claude", "unknown")  # Dead letter
        r.broadcast("claude")
        r.receive("gemini")
        stats = r.get_stats()
        assert stats.registered_agents == 2
        assert stats.total_routed >= 2
        assert stats.total_dead_letters == 1
        assert stats.total_broadcasts == 1

    def test_stats_to_dict(self):
        r = MessageRouter()
        d = r.get_stats().to_dict()
        assert "total_routed" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_agent_count(self):
        r = MessageRouter()
        r.register("a")
        r.register("b")
        assert r.agent_count == 2

    def test_clear(self):
        r = MessageRouter()
        r.register("claude")
        r.route("claude", "gemini")
        r.clear()
        assert r.agent_count == 0
        assert r.get_stats().total_routed == 0

    def test_to_dict(self):
        r = MessageRouter()
        r.register("claude")
        d = r.to_dict()
        assert d["agent_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global message router."""

    def test_get(self):
        reset_message_router()
        r = get_message_router()
        assert isinstance(r, MessageRouter)

    def test_singleton(self):
        reset_message_router()
        r1 = get_message_router()
        r2 = get_message_router()
        assert r1 is r2

    def test_reset(self):
        reset_message_router()
        r1 = get_message_router()
        reset_message_router()
        r2 = get_message_router()
        assert r1 is not r2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_synapse_package(self):
        from core.synapse import (
            DeadLetter,
            MessageRouter,
            QueueInfo,
            RoutedMessage,
            RouteResult,
            RouterStats,
            get_message_router,
            reset_message_router,
        )

        assert all(
            [
                MessageRouter,
                RoutedMessage,
                DeadLetter,
                RouteResult,
                QueueInfo,
                RouterStats,
                get_message_router,
                reset_message_router,
            ]
        )

    def test_from_module(self):
        from core.synapse.message_router import (
            MAX_AGENTS,
        )

        assert MAX_AGENTS == 1000
