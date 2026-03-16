"""
Tests for V12.4 Event Analytics.

Validates:
- EventRecord to_dict
- EventTypeMetrics to_dict / properties
- EventAnalyticsStats to_dict
- Recording events
- Type metrics updates
- Queries (all metrics, recent, by source, list types/sources)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.observability.events.event_analytics import (
    MAX_EVENTS,
    EventAnalytics,
    EventAnalyticsStats,
    EventRecord,
    EventTypeMetrics,
    get_event_analytics,
    reset_event_analytics,
)

# =============================================================================
# EventRecord Tests
# =============================================================================


class TestEventRecord:
    """Test EventRecord dataclass."""

    def test_to_dict(self):
        r = EventRecord(event_id="ev_000001", event_type="interaction_ask", source="repl")
        d = r.to_dict()
        assert d["event_type"] == "interaction_ask"
        assert d["source"] == "repl"


# =============================================================================
# EventTypeMetrics Tests
# =============================================================================


class TestEventTypeMetrics:
    """Test EventTypeMetrics dataclass."""

    def test_success_rate(self):
        m = EventTypeMetrics(event_type="test", total_events=10, success_count=8)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        m = EventTypeMetrics(event_type="test")
        assert m.success_rate == 0.0

    def test_avg_processing(self):
        m = EventTypeMetrics(event_type="test", total_events=4, total_processing_ms=400.0)
        assert abs(m.avg_processing_ms - 100.0) < 0.01

    def test_avg_processing_zero(self):
        m = EventTypeMetrics(event_type="test")
        assert m.avg_processing_ms == 0.0

    def test_to_dict(self):
        m = EventTypeMetrics(event_type="test", total_events=5)
        d = m.to_dict()
        assert "success_rate" in d
        assert "avg_processing_ms" in d


# =============================================================================
# EventAnalyticsStats Tests
# =============================================================================


class TestEventAnalyticsStats:
    """Test EventAnalyticsStats dataclass."""

    def test_to_dict(self):
        s = EventAnalyticsStats(total_events=20, unique_event_types=3)
        d = s.to_dict()
        assert d["total_events"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test event recording."""

    def test_record_basic(self):
        a = EventAnalytics()
        r = a.record_event("state_transition", source="fsm")
        assert r.event_id == "ev_000001"
        assert a.event_count == 1

    def test_type_metrics_update(self):
        a = EventAnalytics()
        a.record_event("state_transition", processing_time_ms=100, success=True)
        a.record_event("state_transition", processing_time_ms=200, success=True)
        a.record_event("state_transition", success=False)
        m = a.get_type_metrics("state_transition")
        assert m is not None
        assert m.total_events == 3
        assert m.success_count == 2

    def test_multiple_types(self):
        a = EventAnalytics()
        a.record_event("type_a")
        a.record_event("type_b")
        a.record_event("type_c")
        assert len(a.get_all_type_metrics()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_type_not_found(self):
        a = EventAnalytics()
        assert a.get_type_metrics("missing") is None

    def test_get_all_types_sorted(self):
        a = EventAnalytics()
        a.record_event("once")
        a.record_event("twice")
        a.record_event("twice")
        metrics = a.get_all_type_metrics()
        assert metrics[0].event_type == "twice"

    def test_events_by_source(self):
        a = EventAnalytics()
        a.record_event("a", source="fsm")
        a.record_event("b", source="swarm")
        a.record_event("c", source="fsm")
        results = a.get_events_by_source("fsm")
        assert len(results) == 2

    def test_recent_events(self):
        a = EventAnalytics()
        for _i in range(5):
            a.record_event("test")
        recent = a.get_recent_events(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        a = EventAnalytics()
        a.record_event("alpha")
        a.record_event("beta")
        a.record_event("alpha")
        recent = a.get_recent_events(event_type="alpha")
        assert len(recent) == 2

    def test_list_event_types(self):
        a = EventAnalytics()
        a.record_event("zeta")
        a.record_event("alpha")
        assert a.list_event_types() == ["alpha", "zeta"]

    def test_list_sources(self):
        a = EventAnalytics()
        a.record_event("a", source="fsm")
        a.record_event("b", source="swarm")
        a.record_event("c", source="fsm")
        sources = a.list_sources()
        assert sources == ["fsm", "swarm"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded event history."""

    def test_eviction(self):
        a = EventAnalytics(max_events=5)
        for _i in range(10):
            a.record_event("test")
        assert a.event_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analytics statistics."""

    def test_initial_stats(self):
        a = EventAnalytics()
        stats = a.get_stats()
        assert stats.total_events == 0

    def test_stats_after_recording(self):
        a = EventAnalytics()
        a.record_event("type_a", source="src_1", success=True)
        a.record_event("type_b", source="src_2", success=False)
        stats = a.get_stats()
        assert stats.total_events == 2
        assert stats.unique_event_types == 2
        assert stats.unique_sources == 2

    def test_stats_to_dict(self):
        a = EventAnalytics()
        d = a.get_stats().to_dict()
        assert "total_events" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = EventAnalytics()
        a.record_event("test")
        assert a.event_count == 1

    def test_clear(self):
        a = EventAnalytics()
        a.record_event("test")
        a.clear()
        assert a.event_count == 0
        assert a.get_type_metrics("test") is None

    def test_to_dict(self):
        a = EventAnalytics()
        a.record_event("test")
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global event analytics."""

    def test_get(self):
        reset_event_analytics()
        a = get_event_analytics()
        assert isinstance(a, EventAnalytics)

    def test_singleton(self):
        reset_event_analytics()
        a1 = get_event_analytics()
        a2 = get_event_analytics()
        assert a1 is a2

    def test_reset(self):
        reset_event_analytics()
        a1 = get_event_analytics()
        reset_event_analytics()
        a2 = get_event_analytics()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_events_package(self):
        from core.observability.events import (
            EventAnalytics,
            EventAnalyticsStats,
            EventRecord,
            EventTypeMetrics,
            get_event_analytics,
            reset_event_analytics,
        )

        assert all(
            [
                EventAnalytics,
                EventRecord,
                EventTypeMetrics,
                EventAnalyticsStats,
                get_event_analytics,
                reset_event_analytics,
            ]
        )

    def test_constants(self):
        assert MAX_EVENTS == 50000
