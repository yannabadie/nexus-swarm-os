"""
Tests for V12.4 Message Reliability Tracker.

Validates:
- DeliveryRecord to_dict
- ChannelMetrics to_dict / properties
- ReliabilityStats to_dict
- Recording deliveries
- Channel metrics updates
- Queries (channels, dead letters, by sender, recent, list senders/receivers)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.synapse.message_reliability_tracker import (
    MAX_DELIVERIES,
    ChannelMetrics,
    DeliveryRecord,
    MessageReliabilityTracker,
    ReliabilityStats,
    get_message_tracker,
    reset_message_tracker,
)

# =============================================================================
# DeliveryRecord Tests
# =============================================================================


class TestDeliveryRecord:
    """Test DeliveryRecord dataclass."""

    def test_to_dict(self):
        r = DeliveryRecord(delivery_id="md_000001", sender="gemini", receiver="claude", message_type="talk")
        d = r.to_dict()
        assert d["sender"] == "gemini"
        assert d["receiver"] == "claude"


# =============================================================================
# ChannelMetrics Tests
# =============================================================================


class TestChannelMetrics:
    """Test ChannelMetrics dataclass."""

    def test_delivery_rate(self):
        m = ChannelMetrics(sender="a", receiver="b", total_messages=10, delivered_count=8)
        assert abs(m.delivery_rate - 0.8) < 0.01

    def test_delivery_rate_zero(self):
        m = ChannelMetrics(sender="a", receiver="b")
        assert m.delivery_rate == 0.0

    def test_avg_latency(self):
        m = ChannelMetrics(sender="a", receiver="b", delivered_count=4, total_latency_ms=400.0)
        assert abs(m.avg_latency_ms - 100.0) < 0.01

    def test_avg_latency_zero(self):
        m = ChannelMetrics(sender="a", receiver="b")
        assert m.avg_latency_ms == 0.0

    def test_to_dict(self):
        m = ChannelMetrics(sender="gemini", receiver="claude", total_messages=5)
        d = m.to_dict()
        assert "delivery_rate" in d
        assert "avg_latency_ms" in d


# =============================================================================
# ReliabilityStats Tests
# =============================================================================


class TestReliabilityStats:
    """Test ReliabilityStats dataclass."""

    def test_to_dict(self):
        s = ReliabilityStats(total_messages=20, unique_senders=2)
        d = s.to_dict()
        assert d["total_messages"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test delivery recording."""

    def test_record_basic(self):
        t = MessageReliabilityTracker()
        r = t.record_delivery("gemini", "claude", message_type="talk")
        assert r.delivery_id == "md_000001"
        assert t.delivery_count == 1

    def test_channel_metrics_update(self):
        t = MessageReliabilityTracker()
        t.record_delivery("gemini", "claude", delivered=True, latency_ms=100)
        t.record_delivery("gemini", "claude", delivered=True, latency_ms=200)
        t.record_delivery("gemini", "claude", delivered=False, dead_letter=True)
        m = t.get_channel_metrics("gemini", "claude")
        assert m is not None
        assert m.total_messages == 3
        assert m.delivered_count == 2
        assert m.dead_letters == 1

    def test_multiple_channels(self):
        t = MessageReliabilityTracker()
        t.record_delivery("gemini", "claude")
        t.record_delivery("claude", "gemini")
        t.record_delivery("user", "claude")
        assert len(t.get_all_channels()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_channel_not_found(self):
        t = MessageReliabilityTracker()
        assert t.get_channel_metrics("a", "b") is None

    def test_get_all_channels_sorted(self):
        t = MessageReliabilityTracker()
        t.record_delivery("a", "b")
        t.record_delivery("c", "d")
        t.record_delivery("a", "b")
        channels = t.get_all_channels()
        assert channels[0].sender == "a"  # 2 > 1

    def test_dead_letters(self):
        t = MessageReliabilityTracker()
        t.record_delivery("a", "b", dead_letter=False)
        t.record_delivery("a", "b", dead_letter=True)
        t.record_delivery("c", "d", dead_letter=True)
        dl = t.get_dead_letters()
        assert len(dl) == 2

    def test_messages_by_sender(self):
        t = MessageReliabilityTracker()
        t.record_delivery("gemini", "claude")
        t.record_delivery("claude", "gemini")
        t.record_delivery("gemini", "user")
        results = t.get_messages_by_sender("gemini")
        assert len(results) == 2

    def test_recent_deliveries(self):
        t = MessageReliabilityTracker()
        for _i in range(5):
            t.record_delivery("a", "b")
        recent = t.get_recent_deliveries(limit=3)
        assert len(recent) == 3

    def test_list_senders(self):
        t = MessageReliabilityTracker()
        t.record_delivery("gemini", "claude")
        t.record_delivery("claude", "gemini")
        assert t.list_senders() == ["claude", "gemini"]

    def test_list_receivers(self):
        t = MessageReliabilityTracker()
        t.record_delivery("gemini", "claude")
        t.record_delivery("gemini", "user")
        assert t.list_receivers() == ["claude", "user"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded delivery history."""

    def test_eviction(self):
        t = MessageReliabilityTracker(max_deliveries=5)
        for _i in range(10):
            t.record_delivery("a", "b")
        assert t.delivery_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = MessageReliabilityTracker()
        stats = t.get_stats()
        assert stats.total_messages == 0

    def test_stats_after_recording(self):
        t = MessageReliabilityTracker()
        t.record_delivery("gemini", "claude", delivered=True)
        t.record_delivery("claude", "gemini", delivered=False, dead_letter=True)
        stats = t.get_stats()
        assert stats.total_messages == 2
        assert stats.unique_senders == 2
        assert stats.unique_receivers == 2
        assert stats.unique_channels == 2
        assert stats.total_dead_letters == 1

    def test_stats_to_dict(self):
        t = MessageReliabilityTracker()
        d = t.get_stats().to_dict()
        assert "total_messages" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = MessageReliabilityTracker()
        t.record_delivery("a", "b")
        assert t.delivery_count == 1

    def test_clear(self):
        t = MessageReliabilityTracker()
        t.record_delivery("a", "b")
        t.clear()
        assert t.delivery_count == 0
        assert t.get_channel_metrics("a", "b") is None

    def test_to_dict(self):
        t = MessageReliabilityTracker()
        t.record_delivery("a", "b")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global message tracker."""

    def test_get(self):
        reset_message_tracker()
        t = get_message_tracker()
        assert isinstance(t, MessageReliabilityTracker)

    def test_singleton(self):
        reset_message_tracker()
        t1 = get_message_tracker()
        t2 = get_message_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_message_tracker()
        t1 = get_message_tracker()
        reset_message_tracker()
        t2 = get_message_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_synapse_package(self):
        from core.synapse import (
            ChannelMetrics,
            DeliveryRecord,
            MessageReliabilityStats,
            MessageReliabilityTracker,
            get_message_tracker,
            reset_message_tracker,
        )

        assert all(
            [
                MessageReliabilityTracker,
                DeliveryRecord,
                ChannelMetrics,
                MessageReliabilityStats,
                get_message_tracker,
                reset_message_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_DELIVERIES == 50000
