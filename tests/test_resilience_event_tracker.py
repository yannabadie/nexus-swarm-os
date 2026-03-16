"""
Tests for V12.4 Resilience Event Tracker.

Validates:
- ResilienceEvent to_dict
- EventTypeMetrics to_dict / properties
- TrackerStats to_dict
- Recording events
- Type metrics updates
- Queries (by type, component, severity, recent, critical)
- Listing components
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.infrastructure.resilience.resilience_event_tracker import (
    EVENT_TYPES,
    MAX_EVENTS,
    EventTypeMetrics,
    ResilienceEvent,
    ResilienceEventTracker,
    TrackerStats,
    get_resilience_tracker,
    reset_resilience_tracker,
)

# =============================================================================
# ResilienceEvent Tests
# =============================================================================


class TestResilienceEvent:
    """Test ResilienceEvent dataclass."""

    def test_to_dict(self):
        e = ResilienceEvent(
            event_id="rev_000001", event_type="circuit_break", component="gemini_driver", severity="warning"
        )
        d = e.to_dict()
        assert d["event_type"] == "circuit_break"
        assert d["severity"] == "warning"


# =============================================================================
# EventTypeMetrics Tests
# =============================================================================


class TestEventTypeMetrics:
    """Test EventTypeMetrics dataclass."""

    def test_resolution_rate(self):
        m = EventTypeMetrics(event_type="circuit_break", total_count=10, resolved_count=8)
        assert abs(m.resolution_rate - 0.8) < 0.01

    def test_resolution_rate_zero(self):
        m = EventTypeMetrics(event_type="circuit_break")
        assert m.resolution_rate == 0.0

    def test_avg_resolution_ms(self):
        m = EventTypeMetrics(event_type="circuit_break", resolved_count=4, total_resolution_ms=400.0)
        assert abs(m.avg_resolution_ms - 100.0) < 0.01

    def test_avg_resolution_zero(self):
        m = EventTypeMetrics(event_type="circuit_break")
        assert m.avg_resolution_ms == 0.0

    def test_to_dict(self):
        m = EventTypeMetrics(event_type="retry", total_count=5)
        d = m.to_dict()
        assert "resolution_rate" in d
        assert "avg_resolution_ms" in d


# =============================================================================
# TrackerStats Tests
# =============================================================================


class TestTrackerStats:
    """Test TrackerStats dataclass."""

    def test_to_dict(self):
        s = TrackerStats(total_events=20, unique_event_types=3)
        d = s.to_dict()
        assert d["total_events"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test event recording."""

    def test_record_basic(self):
        t = ResilienceEventTracker()
        e = t.record_event("circuit_break", component="driver")
        assert e.event_id == "rev_000001"
        assert t.event_count == 1

    def test_record_with_resolution(self):
        t = ResilienceEventTracker()
        e = t.record_event("retry", resolved=True, resolution_ms=250.0)
        assert e.resolved is True
        m = t.get_type_metrics("retry")
        assert m.resolved_count == 1

    def test_type_metrics_update(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break", resolved=True, resolution_ms=100)
        t.record_event("circuit_break", resolved=False)
        t.record_event("circuit_break", resolved=True, resolution_ms=200)
        m = t.get_type_metrics("circuit_break")
        assert m is not None
        assert m.total_count == 3
        assert m.resolved_count == 2

    def test_multiple_types(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break")
        t.record_event("rate_limit")
        t.record_event("retry")
        assert len(t.get_all_metrics()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_type_not_found(self):
        t = ResilienceEventTracker()
        assert t.get_type_metrics("missing") is None

    def test_get_all_metrics_sorted(self):
        t = ResilienceEventTracker()
        t.record_event("retry")
        t.record_event("circuit_break")
        t.record_event("circuit_break")
        metrics = t.get_all_metrics()
        assert metrics[0].event_type == "circuit_break"  # 2 > 1

    def test_events_by_type(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break")
        t.record_event("rate_limit")
        t.record_event("circuit_break")
        results = t.get_events_by_type("circuit_break")
        assert len(results) == 2

    def test_events_by_component(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break", component="gemini_driver")
        t.record_event("rate_limit", component="claude_driver")
        t.record_event("retry", component="gemini_driver")
        results = t.get_events_by_component("gemini_driver")
        assert len(results) == 2

    def test_events_by_severity(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break", severity="warning")
        t.record_event("rate_limit", severity="info")
        t.record_event("retry", severity="warning")
        results = t.get_events_by_severity("warning")
        assert len(results) == 2

    def test_recent_events(self):
        t = ResilienceEventTracker()
        for _i in range(5):
            t.record_event("retry")
        recent = t.get_recent_events(limit=3)
        assert len(recent) == 3

    def test_critical_events(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break", severity="critical")
        t.record_event("rate_limit", severity="info")
        t.record_event("failover", severity="critical")
        critical = t.get_critical_events()
        assert len(critical) == 2

    def test_list_components(self):
        t = ResilienceEventTracker()
        t.record_event("retry", component="gemini")
        t.record_event("retry", component="claude")
        assert t.list_components() == ["claude", "gemini"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded event history."""

    def test_eviction(self):
        t = ResilienceEventTracker(max_events=5)
        for _i in range(10):
            t.record_event("retry")
        assert t.event_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = ResilienceEventTracker()
        stats = t.get_stats()
        assert stats.total_events == 0

    def test_stats_after_recording(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break", component="driver_a", resolved=True)
        t.record_event("rate_limit", component="driver_b", resolved=False)
        stats = t.get_stats()
        assert stats.total_events == 2
        assert stats.unique_event_types == 2
        assert stats.unique_components == 2

    def test_stats_to_dict(self):
        t = ResilienceEventTracker()
        d = t.get_stats().to_dict()
        assert "total_events" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = ResilienceEventTracker()
        t.record_event("retry")
        assert t.event_count == 1

    def test_clear(self):
        t = ResilienceEventTracker()
        t.record_event("circuit_break")
        t.clear()
        assert t.event_count == 0
        assert t.get_type_metrics("circuit_break") is None

    def test_to_dict(self):
        t = ResilienceEventTracker()
        t.record_event("retry")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global resilience tracker."""

    def test_get(self):
        reset_resilience_tracker()
        t = get_resilience_tracker()
        assert isinstance(t, ResilienceEventTracker)

    def test_singleton(self):
        reset_resilience_tracker()
        t1 = get_resilience_tracker()
        t2 = get_resilience_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_resilience_tracker()
        t1 = get_resilience_tracker()
        reset_resilience_tracker()
        t2 = get_resilience_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_resilience_package(self):
        from core.infrastructure.resilience import (
            EventTypeMetrics,
            ResilienceEvent,
            ResilienceEventTracker,
            ResilienceTrackerStats,
            get_resilience_tracker,
            reset_resilience_tracker,
        )

        assert all(
            [
                ResilienceEventTracker,
                ResilienceEvent,
                EventTypeMetrics,
                ResilienceTrackerStats,
                get_resilience_tracker,
                reset_resilience_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_EVENTS == 50000
        assert "circuit_break" in EVENT_TYPES
