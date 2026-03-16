"""
Tests for V12.4 Handler Performance Tracker.

Validates:
- HandlerExecution to_dict
- HandlerTypeMetrics to_dict / properties
- TrackerStats to_dict
- Recording executions
- Handler metrics updates
- Queries (all metrics, slowest, failing, recent)
- Listing handler types
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.execution.handler_performance_tracker import (
    MAX_EXECUTIONS,
    HandlerExecution,
    HandlerPerformanceTracker,
    HandlerTypeMetrics,
    TrackerStats,
    get_handler_tracker,
    reset_handler_tracker,
)

# =============================================================================
# HandlerExecution Tests
# =============================================================================


class TestHandlerExecution:
    """Test HandlerExecution dataclass."""

    def test_to_dict(self):
        e = HandlerExecution(execution_id="he_000001", handler_type="bash", tool_name="pytest", duration_ms=150.0)
        d = e.to_dict()
        assert d["handler_type"] == "bash"
        assert d["tool_name"] == "pytest"


# =============================================================================
# HandlerTypeMetrics Tests
# =============================================================================


class TestHandlerTypeMetrics:
    """Test HandlerTypeMetrics dataclass."""

    def test_success_rate(self):
        m = HandlerTypeMetrics(handler_type="bash", total_executions=10, successes=8)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        m = HandlerTypeMetrics(handler_type="bash")
        assert m.success_rate == 0.0

    def test_avg_duration(self):
        m = HandlerTypeMetrics(handler_type="bash", total_executions=4, total_duration_ms=400.0)
        assert abs(m.avg_duration_ms - 100.0) < 0.01

    def test_avg_duration_zero(self):
        m = HandlerTypeMetrics(handler_type="bash")
        assert m.avg_duration_ms == 0.0

    def test_to_dict(self):
        m = HandlerTypeMetrics(handler_type="bash", total_executions=5)
        d = m.to_dict()
        assert "success_rate" in d
        assert "avg_duration_ms" in d


# =============================================================================
# TrackerStats Tests
# =============================================================================


class TestTrackerStats:
    """Test TrackerStats dataclass."""

    def test_to_dict(self):
        s = TrackerStats(total_executions=20, unique_handler_types=3)
        d = s.to_dict()
        assert d["total_executions"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test execution recording."""

    def test_record_basic(self):
        t = HandlerPerformanceTracker()
        e = t.record_execution("bash", tool_name="pytest", duration_ms=100.0)
        assert e.execution_id == "he_000001"
        assert t.execution_count == 1

    def test_handler_metrics_update(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash", duration_ms=100, success=True)
        t.record_execution("bash", duration_ms=200, success=True)
        t.record_execution("bash", duration_ms=300, success=False)
        m = t.get_handler_metrics("bash")
        assert m is not None
        assert m.total_executions == 3
        assert m.successes == 2
        assert m.failures == 1

    def test_multiple_handlers(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash")
        t.record_execution("file_read")
        t.record_execution("web_fetch")
        assert len(t.get_all_metrics()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_handler_not_found(self):
        t = HandlerPerformanceTracker()
        assert t.get_handler_metrics("missing") is None

    def test_get_all_metrics_sorted(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash")
        t.record_execution("file_read")
        t.record_execution("bash")
        metrics = t.get_all_metrics()
        assert metrics[0].handler_type == "bash"  # 2 > 1

    def test_slowest_handlers(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash", duration_ms=100)
        t.record_execution("web_fetch", duration_ms=500)
        slow = t.get_slowest_handlers(limit=1)
        assert len(slow) == 1
        assert slow[0].handler_type == "web_fetch"

    def test_failing_handlers(self):
        t = HandlerPerformanceTracker()
        for _ in range(5):
            t.record_execution("bash", success=True)
        for _ in range(4):
            t.record_execution("risky", success=False)
        t.record_execution("risky", success=True)
        failing = t.get_failing_handlers(min_executions=3)
        assert len(failing) >= 1
        assert failing[0].handler_type == "risky"

    def test_recent_executions(self):
        t = HandlerPerformanceTracker()
        for _i in range(5):
            t.record_execution("bash")
        recent = t.get_recent_executions(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash")
        t.record_execution("file_read")
        t.record_execution("bash")
        recent = t.get_recent_executions(handler_type="bash")
        assert len(recent) == 2

    def test_list_handler_types(self):
        t = HandlerPerformanceTracker()
        t.record_execution("web_fetch")
        t.record_execution("bash")
        assert t.list_handler_types() == ["bash", "web_fetch"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded execution history."""

    def test_eviction(self):
        t = HandlerPerformanceTracker(max_executions=5)
        for _i in range(10):
            t.record_execution("bash")
        assert t.execution_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = HandlerPerformanceTracker()
        stats = t.get_stats()
        assert stats.total_executions == 0

    def test_stats_after_recording(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash", tool_name="pytest", success=True)
        t.record_execution("file_read", tool_name="glob", success=False)
        stats = t.get_stats()
        assert stats.total_executions == 2
        assert stats.unique_handler_types == 2
        assert stats.unique_tools == 2

    def test_stats_to_dict(self):
        t = HandlerPerformanceTracker()
        d = t.get_stats().to_dict()
        assert "total_executions" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash")
        assert t.execution_count == 1

    def test_clear(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash")
        t.clear()
        assert t.execution_count == 0
        assert t.get_handler_metrics("bash") is None

    def test_to_dict(self):
        t = HandlerPerformanceTracker()
        t.record_execution("bash")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global handler tracker."""

    def test_get(self):
        reset_handler_tracker()
        t = get_handler_tracker()
        assert isinstance(t, HandlerPerformanceTracker)

    def test_singleton(self):
        reset_handler_tracker()
        t1 = get_handler_tracker()
        t2 = get_handler_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_handler_tracker()
        t1 = get_handler_tracker()
        reset_handler_tracker()
        t2 = get_handler_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import (
            HandlerExecution,
            HandlerPerformanceTracker,
            HandlerTrackerStats,
            HandlerTypeMetrics,
            get_handler_tracker,
            reset_handler_tracker,
        )

        assert all(
            [
                HandlerPerformanceTracker,
                HandlerExecution,
                HandlerTypeMetrics,
                HandlerTrackerStats,
                get_handler_tracker,
                reset_handler_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_EXECUTIONS == 50000
