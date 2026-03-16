"""
Tests for V12.4 Tool Execution Observer.

Validates:
- ToolSpan to_dict
- ToolMetric to_dict / properties
- ObservationReport to_dict
- ToolObserverStats to_dict
- Span lifecycle (start, end)
- Metric aggregation (averages, min/max, error categories)
- Span queries (by tool, session, status)
- Slow span detection
- Error span detection
- Report generation
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.execution.tool_observer import (
    MAX_SPANS,
    SLOW_THRESHOLD_MS,
    ObservationReport,
    ToolMetric,
    ToolObserver,
    ToolObserverStats,
    ToolSpan,
    get_tool_observer,
    reset_tool_observer,
)

# =============================================================================
# ToolSpan Tests
# =============================================================================


class TestToolSpan:
    """Test ToolSpan dataclass."""

    def test_basic(self):
        s = ToolSpan(tool_name="file_read")
        assert s.tool_name == "file_read"
        assert s.status == "pending"

    def test_to_dict(self):
        s = ToolSpan(
            tool_name="file_read",
            session_id="s1",
            agent_id="claude",
            status="success",
            duration_ms=150.0,
        )
        d = s.to_dict()
        assert d["tool_name"] == "file_read"
        assert d["duration_ms"] == 150.0


# =============================================================================
# ToolMetric Tests
# =============================================================================


class TestToolMetric:
    """Test ToolMetric dataclass."""

    def test_success_rate_zero(self):
        m = ToolMetric(tool_name="file_read")
        assert m.success_rate == 0.0

    def test_success_rate(self):
        m = ToolMetric(tool_name="file_read", total_calls=10, successes=8, errors=2)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_error_rate(self):
        m = ToolMetric(tool_name="file_read", total_calls=10, successes=8, errors=2)
        assert abs(m.error_rate - 0.2) < 0.01

    def test_to_dict(self):
        m = ToolMetric(tool_name="file_read", total_calls=5, successes=4)
        d = m.to_dict()
        assert d["tool_name"] == "file_read"
        assert "success_rate" in d


# =============================================================================
# ObservationReport Tests
# =============================================================================


class TestObservationReport:
    """Test ObservationReport dataclass."""

    def test_to_dict(self):
        r = ObservationReport(
            total_spans=100,
            total_tools=5,
            overall_success_rate=0.95,
            overall_avg_duration_ms=200.0,
            slowest_tools=["web_fetch"],
            most_failing_tools=["bash"],
        )
        d = r.to_dict()
        assert d["total_spans"] == 100
        assert d["overall_success_rate"] == 0.95


# =============================================================================
# ToolObserverStats Tests
# =============================================================================


class TestToolObserverStats:
    """Test ToolObserverStats dataclass."""

    def test_to_dict(self):
        s = ToolObserverStats(total_spans=50, total_tools=5, total_errors=3, total_timeouts=1)
        d = s.to_dict()
        assert d["total_errors"] == 3


# =============================================================================
# Span Lifecycle Tests
# =============================================================================


class TestSpanLifecycle:
    """Test span start and end."""

    def test_start_span(self):
        obs = ToolObserver()
        span = obs.start_span("file_read", session_id="s1", agent_id="claude")
        assert span.tool_name == "file_read"
        assert span.status == "running"
        assert span.session_id == "s1"
        assert obs.span_count == 1

    def test_end_span_success(self):
        obs = ToolObserver()
        span = obs.start_span("file_read")
        result = obs.end_span(span, status="success")
        assert result.status == "success"
        assert result.duration_ms > 0

    def test_end_span_error(self):
        obs = ToolObserver()
        span = obs.start_span("bash")
        result = obs.end_span(span, status="error", error_type="runtime", error_message="exit code 1")
        assert result.status == "error"
        assert result.error_type == "runtime"
        assert result.error_message == "exit code 1"

    def test_end_span_timeout(self):
        obs = ToolObserver()
        span = obs.start_span("web_fetch")
        result = obs.end_span(span, status="timeout", error_type="timeout")
        assert result.status == "timeout"

    def test_multiple_spans(self):
        obs = ToolObserver()
        obs.start_span("file_read")
        obs.start_span("bash")
        obs.start_span("grep")
        assert obs.span_count == 3


# =============================================================================
# Metric Aggregation Tests
# =============================================================================


class TestMetricAggregation:
    """Test metric aggregation from spans."""

    def test_single_success(self):
        obs = ToolObserver()
        span = obs.start_span("file_read")
        obs.end_span(span, status="success")
        m = obs.get_metric("file_read")
        assert m is not None
        assert m.total_calls == 1
        assert m.successes == 1
        assert m.errors == 0

    def test_error_categories(self):
        obs = ToolObserver()
        for error_type in ["runtime", "runtime", "validation", "timeout"]:
            span = obs.start_span("bash")
            status = "timeout" if error_type == "timeout" else "error"
            obs.end_span(span, status=status, error_type=error_type)
        m = obs.get_metric("bash")
        assert m.errors == 3  # runtime x2 + validation
        assert m.timeouts == 1
        assert m.error_categories.get("runtime") == 2

    def test_duration_min_max(self):
        obs = ToolObserver()
        # Simulate different durations by ending spans immediately
        for _ in range(3):
            span = obs.start_span("file_read")
            obs.end_span(span, status="success")
        m = obs.get_metric("file_read")
        assert m.min_duration_ms <= m.avg_duration_ms <= m.max_duration_ms

    def test_get_metric_not_found(self):
        obs = ToolObserver()
        assert obs.get_metric("missing") is None

    def test_get_all_metrics(self):
        obs = ToolObserver()
        for tool in ["file_read", "bash", "grep"]:
            span = obs.start_span(tool)
            obs.end_span(span, status="success")
        metrics = obs.get_all_metrics()
        assert len(metrics) == 3


# =============================================================================
# Span Query Tests
# =============================================================================


class TestSpanQueries:
    """Test span query methods."""

    def test_get_spans_by_tool(self):
        obs = ToolObserver()
        for tool in ["file_read", "bash", "file_read"]:
            span = obs.start_span(tool)
            obs.end_span(span, status="success")
        results = obs.get_spans(tool_name="file_read")
        assert len(results) == 2

    def test_get_spans_by_session(self):
        obs = ToolObserver()
        span1 = obs.start_span("file_read", session_id="s1")
        obs.end_span(span1, status="success")
        span2 = obs.start_span("file_read", session_id="s2")
        obs.end_span(span2, status="success")
        results = obs.get_spans(session_id="s1")
        assert len(results) == 1

    def test_get_spans_by_status(self):
        obs = ToolObserver()
        span1 = obs.start_span("file_read")
        obs.end_span(span1, status="success")
        span2 = obs.start_span("bash")
        obs.end_span(span2, status="error", error_type="runtime")
        results = obs.get_spans(status="error")
        assert len(results) == 1

    def test_get_spans_with_limit(self):
        obs = ToolObserver()
        for _ in range(10):
            span = obs.start_span("file_read")
            obs.end_span(span, status="success")
        results = obs.get_spans(limit=3)
        assert len(results) == 3

    def test_get_error_spans(self):
        obs = ToolObserver()
        span1 = obs.start_span("file_read")
        obs.end_span(span1, status="success")
        span2 = obs.start_span("bash")
        obs.end_span(span2, status="error", error_type="runtime")
        span3 = obs.start_span("web_fetch")
        obs.end_span(span3, status="timeout", error_type="timeout")
        errors = obs.get_error_spans()
        assert len(errors) == 2

    def test_get_slow_spans(self):
        obs = ToolObserver()
        # All spans will be fast (< threshold), so manually check the API
        span = obs.start_span("file_read")
        obs.end_span(span, status="success")
        results = obs.get_slow_spans(threshold_ms=0.0)  # Every span is "slow" at 0ms threshold
        assert len(results) >= 1


# =============================================================================
# Report Tests
# =============================================================================


class TestReport:
    """Test report generation."""

    def test_empty_report(self):
        obs = ToolObserver()
        report = obs.get_report()
        assert report.total_spans == 0
        assert report.total_tools == 0

    def test_report_with_data(self):
        obs = ToolObserver()
        for _ in range(5):
            span = obs.start_span("file_read")
            obs.end_span(span, status="success")
        span = obs.start_span("bash")
        obs.end_span(span, status="error", error_type="runtime")
        report = obs.get_report()
        assert report.total_spans == 6
        assert report.total_tools == 2
        assert report.overall_success_rate > 0

    def test_report_to_dict(self):
        obs = ToolObserver()
        d = obs.get_report().to_dict()
        assert "total_spans" in d
        assert "slowest_tools" in d


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded span history."""

    def test_eviction(self):
        obs = ToolObserver(max_spans=5)
        for i in range(10):
            span = obs.start_span(f"tool_{i}")
            obs.end_span(span, status="success")
        assert obs.span_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test observer statistics."""

    def test_initial_stats(self):
        obs = ToolObserver()
        stats = obs.get_stats()
        assert stats.total_spans == 0
        assert stats.total_tools == 0

    def test_stats_after_spans(self):
        obs = ToolObserver()
        span = obs.start_span("file_read")
        obs.end_span(span, status="success")
        span = obs.start_span("bash")
        obs.end_span(span, status="error", error_type="runtime")
        stats = obs.get_stats()
        assert stats.total_spans == 2
        assert stats.total_tools == 2
        assert stats.total_errors == 1

    def test_stats_to_dict(self):
        obs = ToolObserver()
        d = obs.get_stats().to_dict()
        assert "total_spans" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_span_count(self):
        obs = ToolObserver()
        obs.start_span("file_read")
        obs.start_span("bash")
        assert obs.span_count == 2

    def test_clear(self):
        obs = ToolObserver()
        span = obs.start_span("file_read")
        obs.end_span(span, status="success")
        obs.clear()
        assert obs.span_count == 0
        assert obs.get_metric("file_read") is None

    def test_to_dict(self):
        obs = ToolObserver()
        span = obs.start_span("file_read")
        obs.end_span(span, status="success")
        d = obs.to_dict()
        assert d["span_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global tool observer."""

    def test_get(self):
        reset_tool_observer()
        obs = get_tool_observer()
        assert isinstance(obs, ToolObserver)

    def test_singleton(self):
        reset_tool_observer()
        o1 = get_tool_observer()
        o2 = get_tool_observer()
        assert o1 is o2

    def test_reset(self):
        reset_tool_observer()
        o1 = get_tool_observer()
        reset_tool_observer()
        o2 = get_tool_observer()
        assert o1 is not o2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import (
            ObservationReport,
            ToolMetric,
            ToolObserver,
            ToolObserverStats,
            ToolSpan,
            get_tool_observer,
            reset_tool_observer,
        )

        assert all(
            [
                ToolObserver,
                ToolSpan,
                ToolMetric,
                ObservationReport,
                ToolObserverStats,
                get_tool_observer,
                reset_tool_observer,
            ]
        )

    def test_constants(self):
        assert MAX_SPANS == 50000
        assert SLOW_THRESHOLD_MS == 5000.0
