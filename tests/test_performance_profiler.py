"""
Tests for V12.4 Performance Profiler.

Validates:
- TimingRecord creation
- TimingStats computation and serialization
- Basic recording (record, record_transition, record_negotiation, etc.)
- Span context manager
- Statistics (get_stats, get_all_stats, get_category_stats)
- Percentile calculations
- Bottleneck detection
- Report generation
- State management (clear, categories, counts)
- Global singleton
- Module exports
"""

import time

import pytest

from core.observability.telemetry.performance_profiler import (
    MAX_RECORDS,
    PerformanceProfiler,
    TimingRecord,
    TimingStats,
    get_profiler,
    reset_profiler,
)

# =============================================================================
# TimingRecord Tests
# =============================================================================


class TestTimingRecord:
    """Test TimingRecord dataclass."""

    def test_basic_creation(self):
        r = TimingRecord(category="llm.call", name="claude/opus", duration_ms=150.5)
        assert r.category == "llm.call"
        assert r.name == "claude/opus"
        assert r.duration_ms == 150.5
        assert r.success is True

    def test_auto_timestamp(self):
        r = TimingRecord(category="test", name="op", duration_ms=10.0)
        assert r.timestamp > 0

    def test_custom_tags(self):
        r = TimingRecord(
            category="test",
            name="op",
            duration_ms=10.0,
            tags={"model": "opus"},
        )
        assert r.tags["model"] == "opus"

    def test_failure_record(self):
        r = TimingRecord(
            category="test",
            name="op",
            duration_ms=10.0,
            success=False,
        )
        assert r.success is False


# =============================================================================
# TimingStats Tests
# =============================================================================


class TestTimingStats:
    """Test TimingStats dataclass."""

    def test_success_rate_all_success(self):
        stats = TimingStats(
            category="test",
            name="op",
            count=10,
            success_count=10,
            failure_count=0,
        )
        assert stats.success_rate == 1.0

    def test_success_rate_mixed(self):
        stats = TimingStats(
            category="test",
            name="op",
            count=10,
            success_count=7,
            failure_count=3,
        )
        assert stats.success_rate == 0.7

    def test_success_rate_empty(self):
        stats = TimingStats(category="test", name="op")
        assert stats.success_rate == 0.0

    def test_to_dict(self):
        stats = TimingStats(
            category="llm.call",
            name="claude/opus",
            count=5,
            total_ms=500.0,
            min_ms=50.0,
            max_ms=200.0,
            mean_ms=100.0,
            median_ms=95.0,
            p90_ms=180.0,
            p95_ms=190.0,
            p99_ms=198.0,
            success_count=4,
            failure_count=1,
        )
        d = stats.to_dict()
        assert d["category"] == "llm.call"
        assert d["name"] == "claude/opus"
        assert d["count"] == 5
        assert d["mean_ms"] == 100.0
        assert d["success_rate"] == 0.8

    def test_to_dict_inf_min(self):
        stats = TimingStats(category="test", name="op")
        d = stats.to_dict()
        assert d["min_ms"] == 0.0  # inf gets converted to 0.0


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test recording timing data."""

    def test_record_basic(self):
        p = PerformanceProfiler()
        p.record("test", "op", 100.0)
        assert p.total_records == 1

    def test_record_multiple(self):
        p = PerformanceProfiler()
        p.record("test", "a", 100.0)
        p.record("test", "b", 200.0)
        p.record("test", "a", 150.0)
        assert p.total_records == 3

    def test_record_with_tags(self):
        p = PerformanceProfiler()
        p.record("test", "op", 100.0, tags={"key": "val"})
        stats = p.get_stats("test", "op")
        assert stats is not None

    def test_record_failure(self):
        p = PerformanceProfiler()
        p.record("test", "op", 100.0, success=False)
        stats = p.get_stats("test", "op")
        assert stats.failure_count == 1

    def test_record_transition(self):
        p = PerformanceProfiler()
        p.record_transition("IDLE", "BRAINSTORMING", 12.5)
        stats = p.get_stats("fsm.transition", "IDLE->BRAINSTORMING")
        assert stats is not None
        assert stats.mean_ms == 12.5

    def test_record_negotiation(self):
        p = PerformanceProfiler()
        p.record_negotiation("ping_pong", 250.0, rounds=3)
        stats = p.get_stats("swarm.negotiation", "ping_pong")
        assert stats is not None
        assert stats.count == 1

    def test_record_driver_call(self):
        p = PerformanceProfiler()
        p.record_driver_call("claude", "opus", 1500.0, tokens=5000)
        stats = p.get_stats("llm.call", "claude/opus")
        assert stats is not None
        assert stats.mean_ms == 1500.0

    def test_record_phase(self):
        p = PerformanceProfiler()
        p.record_phase("ANALYSIS", 800.0)
        stats = p.get_stats("hive.phase", "ANALYSIS")
        assert stats is not None


# =============================================================================
# Span Context Manager Tests
# =============================================================================


class TestSpan:
    """Test span context manager."""

    def test_basic_span(self):
        p = PerformanceProfiler()
        with p.span("test", "operation"):
            time.sleep(0.01)  # 10ms
        stats = p.get_stats("test", "operation")
        assert stats is not None
        assert stats.count == 1
        assert stats.mean_ms >= 5  # At least some time

    def test_span_default_name(self):
        p = PerformanceProfiler()
        with p.span("my.category"):
            pass
        stats = p.get_stats("my.category", "my.category")
        assert stats is not None

    def test_span_with_tags(self):
        p = PerformanceProfiler()
        with p.span("test", "op", tags={"model": "opus"}):
            pass
        assert p.total_records == 1

    def test_span_success(self):
        p = PerformanceProfiler()
        with p.span("test", "op"):
            pass
        stats = p.get_stats("test", "op")
        assert stats.success_count == 1

    def test_span_manual_failure(self):
        p = PerformanceProfiler()
        with p.span("test", "op") as s:
            s.success = False
        stats = p.get_stats("test", "op")
        assert stats.failure_count == 1

    def test_span_exception_marks_failure(self):
        p = PerformanceProfiler()
        with pytest.raises(ValueError), p.span("test", "op"):
            raise ValueError("boom")
        stats = p.get_stats("test", "op")
        assert stats.failure_count == 1
        assert stats.count == 1

    def test_span_records_after_exception(self):
        p = PerformanceProfiler()
        try:
            with p.span("test", "op"):
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert p.total_records == 1


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test statistics computation."""

    def test_get_stats_basic(self):
        p = PerformanceProfiler()
        for v in [100.0, 200.0, 300.0, 400.0, 500.0]:
            p.record("test", "op", v)
        stats = p.get_stats("test", "op")
        assert stats.count == 5
        assert stats.min_ms == 100.0
        assert stats.max_ms == 500.0
        assert stats.mean_ms == 300.0
        assert stats.total_ms == 1500.0

    def test_get_stats_not_found(self):
        p = PerformanceProfiler()
        assert p.get_stats("missing", "op") is None

    def test_get_stats_single_record(self):
        p = PerformanceProfiler()
        p.record("test", "op", 42.0)
        stats = p.get_stats("test", "op")
        assert stats.count == 1
        assert stats.p90_ms == 42.0
        assert stats.p95_ms == 42.0

    def test_median(self):
        p = PerformanceProfiler()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            p.record("test", "op", v)
        stats = p.get_stats("test", "op")
        assert stats.median_ms == 30.0

    def test_percentiles(self):
        p = PerformanceProfiler()
        for i in range(100):
            p.record("test", "op", float(i + 1))
        stats = p.get_stats("test", "op")
        assert stats.p90_ms >= 89.0
        assert stats.p95_ms >= 94.0
        assert stats.p99_ms >= 98.0

    def test_get_all_stats(self):
        p = PerformanceProfiler()
        p.record("cat_a", "op1", 100.0)
        p.record("cat_a", "op2", 200.0)
        p.record("cat_b", "op1", 300.0)
        all_stats = p.get_all_stats()
        assert len(all_stats) == 3

    def test_get_category_stats(self):
        p = PerformanceProfiler()
        p.record("llm.call", "claude/opus", 100.0)
        p.record("llm.call", "gemini/pro", 200.0)
        p.record("fsm.transition", "IDLE->BRAINSTORMING", 10.0)
        llm_stats = p.get_category_stats("llm.call")
        assert len(llm_stats) == 2
        fsm_stats = p.get_category_stats("fsm.transition")
        assert len(fsm_stats) == 1

    def test_get_category_stats_empty(self):
        p = PerformanceProfiler()
        assert p.get_category_stats("nonexistent") == []

    def test_success_failure_tracking(self):
        p = PerformanceProfiler()
        p.record("test", "op", 100.0, success=True)
        p.record("test", "op", 200.0, success=True)
        p.record("test", "op", 300.0, success=False)
        stats = p.get_stats("test", "op")
        assert stats.success_count == 2
        assert stats.failure_count == 1
        assert abs(stats.success_rate - 2 / 3) < 0.01


# =============================================================================
# Bottleneck Detection Tests
# =============================================================================


class TestBottleneckDetection:
    """Test bottleneck identification."""

    def test_no_bottlenecks(self):
        p = PerformanceProfiler(bottleneck_threshold_ms=1000.0)
        for _ in range(5):
            p.record("test", "op", 10.0)
        assert p.detect_bottlenecks() == []

    def test_high_mean_latency(self):
        p = PerformanceProfiler(bottleneck_threshold_ms=100.0)
        for _ in range(5):
            p.record("test", "slow", 200.0)
        bottlenecks = p.detect_bottlenecks()
        assert len(bottlenecks) == 1
        assert bottlenecks[0].name == "slow"
        assert "mean" in bottlenecks[0].reason.lower()

    def test_high_p95_latency(self):
        p = PerformanceProfiler(
            bottleneck_threshold_ms=1000.0,
            high_p95_threshold_ms=500.0,
        )
        # Most are fast but some are very slow
        for _ in range(17):
            p.record("test", "spiky", 50.0)
        for _ in range(3):
            p.record("test", "spiky", 5000.0)
        bottlenecks = p.detect_bottlenecks()
        assert len(bottlenecks) >= 1

    def test_high_failure_rate(self):
        p = PerformanceProfiler(bottleneck_threshold_ms=10000.0)
        p.record("test", "flaky", 10.0, success=True)
        p.record("test", "flaky", 10.0, success=False)
        p.record("test", "flaky", 10.0, success=False)
        p.record("test", "flaky", 10.0, success=False)
        bottlenecks = p.detect_bottlenecks()
        assert len(bottlenecks) == 1
        assert "failure" in bottlenecks[0].reason.lower()

    def test_not_enough_data(self):
        p = PerformanceProfiler(bottleneck_threshold_ms=10.0)
        p.record("test", "op", 5000.0)  # High but only 1 record
        p.record("test", "op", 5000.0)  # Still only 2
        assert p.detect_bottlenecks() == []  # Needs >= 3

    def test_bottleneck_severity(self):
        p = PerformanceProfiler(
            bottleneck_threshold_ms=100.0,
            high_p95_threshold_ms=500.0,
        )
        for _ in range(5):
            p.record("test", "very_slow", 10000.0)
        bottlenecks = p.detect_bottlenecks()
        assert bottlenecks[0].severity == "high"

    def test_bottleneck_to_dict(self):
        p = PerformanceProfiler(bottleneck_threshold_ms=10.0)
        for _ in range(5):
            p.record("test", "slow", 100.0)
        bottlenecks = p.detect_bottlenecks()
        d = bottlenecks[0].to_dict()
        assert d["category"] == "test"
        assert d["name"] == "slow"
        assert "severity" in d
        assert "reason" in d

    def test_bottlenecks_sorted_by_latency(self):
        p = PerformanceProfiler(bottleneck_threshold_ms=10.0)
        for _ in range(5):
            p.record("test", "slow", 100.0)
        for _ in range(5):
            p.record("test", "slower", 200.0)
        bottlenecks = p.detect_bottlenecks()
        assert bottlenecks[0].name == "slower"
        assert bottlenecks[1].name == "slow"


# =============================================================================
# Report Tests
# =============================================================================


class TestReport:
    """Test report generation."""

    def test_empty_report(self):
        p = PerformanceProfiler()
        report = p.get_report()
        assert report.total_records == 0
        assert report.categories == []
        assert report.stats == []
        assert report.bottlenecks == []

    def test_report_with_data(self):
        p = PerformanceProfiler()
        p.record("llm.call", "claude/opus", 1500.0)
        p.record("fsm.transition", "IDLE->BRAINSTORMING", 10.0)
        report = p.get_report()
        assert report.total_records == 2
        assert "fsm.transition" in report.categories
        assert "llm.call" in report.categories
        assert len(report.stats) == 2

    def test_report_slowest_spans(self):
        p = PerformanceProfiler()
        p.record("test", "fast", 10.0)
        p.record("test", "slow", 1000.0)
        p.record("test", "medium", 500.0)
        report = p.get_report(top_n=2)
        assert len(report.slowest_spans) == 2
        assert report.slowest_spans[0].name == "slow"

    def test_report_uptime(self):
        p = PerformanceProfiler()
        report = p.get_report()
        assert report.uptime_ms >= 0

    def test_report_to_dict(self):
        p = PerformanceProfiler()
        p.record("test", "op", 100.0)
        report = p.get_report()
        d = report.to_dict()
        assert d["total_records"] == 1
        assert "categories" in d
        assert "stats" in d
        assert "bottleneck_count" in d
        assert "slowest_spans" in d
        assert "uptime_ms" in d


# =============================================================================
# State Management Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_total_records(self):
        p = PerformanceProfiler()
        assert p.total_records == 0
        p.record("test", "op", 10.0)
        assert p.total_records == 1

    def test_category_count(self):
        p = PerformanceProfiler()
        p.record("cat_a", "op", 10.0)
        p.record("cat_b", "op", 20.0)
        assert p.category_count == 2

    def test_span_count(self):
        p = PerformanceProfiler()
        p.record("cat", "op1", 10.0)
        p.record("cat", "op2", 20.0)
        assert p.span_count == 2

    def test_get_categories(self):
        p = PerformanceProfiler()
        p.record("llm.call", "op", 10.0)
        p.record("fsm.transition", "op", 20.0)
        cats = p.get_categories()
        assert cats == ["fsm.transition", "llm.call"]

    def test_clear(self):
        p = PerformanceProfiler()
        p.record("test", "a", 10.0)
        p.record("test", "b", 20.0)
        count = p.clear()
        assert count == 2
        assert p.total_records == 0
        assert p.span_count == 0

    def test_to_dict(self):
        p = PerformanceProfiler()
        p.record("test", "op", 10.0)
        d = p.to_dict()
        assert d["total_records"] == 1
        assert d["category_count"] == 1
        assert d["span_count"] == 1
        assert "uptime_ms" in d

    def test_max_records_per_key(self):
        p = PerformanceProfiler(max_records=5)
        for i in range(10):
            p.record("test", "op", float(i))
        stats = p.get_stats("test", "op")
        assert stats.count == 5  # Limited to max_records


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global profiler."""

    def test_get_profiler(self):
        reset_profiler()
        p = get_profiler()
        assert isinstance(p, PerformanceProfiler)

    def test_singleton(self):
        reset_profiler()
        p1 = get_profiler()
        p2 = get_profiler()
        assert p1 is p2

    def test_reset(self):
        reset_profiler()
        p1 = get_profiler()
        reset_profiler()
        p2 = get_profiler()
        assert p1 is not p2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_telemetry_package(self):
        from core.observability.telemetry import (
            Bottleneck,
            PerformanceProfiler,
            ProfileReport,
            TimingRecord,
            TimingStats,
            get_profiler,
            reset_profiler,
        )

        assert all(
            [
                PerformanceProfiler,
                TimingRecord,
                TimingStats,
                Bottleneck,
                ProfileReport,
                get_profiler,
                reset_profiler,
            ]
        )

    def test_from_module(self):
        assert MAX_RECORDS == 10_000
