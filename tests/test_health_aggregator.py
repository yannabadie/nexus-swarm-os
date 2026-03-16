"""
Tests for V12.4 Unified Health Dashboard Aggregator.

Validates:
- HealthCheck dataclass (creation, serialization, auto-timestamp)
- TelemetrySummary (metrics, error rate, serialization)
- HealthReport (composite report, summary generation)
- HealthAggregator recording and retrieval
- Weighted composite health scoring
- Overall status determination (healthy/degraded/unhealthy)
- Component history (ring buffer)
- Telemetry integration
- Stale component detection
- Component removal and clearing
- Human-readable summary generation
- Module exports
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from core.observability.telemetry.health_aggregator import (
    DEFAULT_WEIGHTS,
    STATUS_SCORES,
    AggregateStatus,
    ComponentCategory,
    HealthAggregator,
    HealthCheck,
    HealthReport,
    TelemetrySummary,
)

# =============================================================================
# HealthCheck Tests
# =============================================================================


class TestHealthCheck:
    """Test HealthCheck dataclass."""

    def test_basic_creation(self):
        check = HealthCheck(component="redis", status="healthy")
        assert check.component == "redis"
        assert check.status == "healthy"
        assert check.category == "subsystem"
        assert check.message == ""
        assert check.latency_ms == 0.0

    def test_auto_timestamp(self):
        check = HealthCheck(component="test", status="healthy")
        assert check.timestamp != ""
        assert "T" in check.timestamp

    def test_explicit_timestamp(self):
        ts = "2025-01-01T00:00:00Z"
        check = HealthCheck(component="test", status="healthy", timestamp=ts)
        assert check.timestamp == ts

    def test_full_creation(self):
        check = HealthCheck(
            component="gemini_driver",
            status="degraded",
            category="driver",
            message="High latency",
            latency_ms=250.0,
            details={"model": "gemini-3-pro"},
        )
        assert check.component == "gemini_driver"
        assert check.status == "degraded"
        assert check.category == "driver"
        assert check.latency_ms == 250.0
        assert check.details["model"] == "gemini-3-pro"

    def test_to_dict(self):
        check = HealthCheck(
            component="redis",
            status="healthy",
            category="infrastructure",
            message="Connected",
            latency_ms=5.0,
        )
        d = check.to_dict()
        assert d["component"] == "redis"
        assert d["status"] == "healthy"
        assert d["category"] == "infrastructure"
        assert d["message"] == "Connected"
        assert d["latency_ms"] == 5.0
        assert "timestamp" in d


# =============================================================================
# TelemetrySummary Tests
# =============================================================================


class TestTelemetrySummary:
    """Test TelemetrySummary dataclass."""

    def test_defaults(self):
        summary = TelemetrySummary()
        assert summary.api_calls == 0
        assert summary.total_tokens == 0
        assert summary.error_rate == 0.0
        assert summary.cost_usd == 0.0

    def test_with_data(self):
        summary = TelemetrySummary(
            api_calls=100,
            total_tokens=50000,
            total_errors=5,
            cost_usd=0.05,
            budget_utilization_pct=12.5,
            error_rate=0.05,
        )
        assert summary.api_calls == 100
        assert summary.error_rate == 0.05

    def test_to_dict(self):
        summary = TelemetrySummary(
            api_calls=10,
            total_tokens=5000,
            cost_usd=0.001234567,
            session_duration_seconds=123.456789,
        )
        d = summary.to_dict()
        assert d["api_calls"] == 10
        assert d["total_tokens"] == 5000
        assert d["cost_usd"] == 0.001235  # Rounded to 6 places
        assert d["session_duration_seconds"] == 123.46

    def test_budget_warning(self):
        summary = TelemetrySummary(
            budget_utilization_pct=85.0,
            budget_warning_level="warning",
        )
        d = summary.to_dict()
        assert d["budget_warning_level"] == "warning"


# =============================================================================
# HealthReport Tests
# =============================================================================


class TestHealthReport:
    """Test HealthReport dataclass."""

    def test_basic_report(self):
        report = HealthReport(
            overall_status="healthy",
            health_score=0.95,
            components=[],
            telemetry={},
            summary="All good",
        )
        assert report.overall_status == "healthy"
        assert report.health_score == 0.95

    def test_auto_timestamp(self):
        report = HealthReport(
            overall_status="healthy",
            health_score=1.0,
            components=[],
            telemetry={},
            summary="OK",
        )
        assert report.generated_at != ""

    def test_to_dict(self):
        report = HealthReport(
            overall_status="degraded",
            health_score=0.65,
            components=[{"component": "redis", "status": "degraded"}],
            telemetry={"api_calls": 100},
            summary="Degraded",
            component_count=1,
            healthy_count=0,
            degraded_count=1,
            unhealthy_count=0,
        )
        d = report.to_dict()
        assert d["overall_status"] == "degraded"
        assert d["health_score"] == 0.65
        assert len(d["components"]) == 1
        assert d["telemetry"]["api_calls"] == 100
        assert d["degraded_count"] == 1


# =============================================================================
# HealthAggregator - Initialization Tests
# =============================================================================


class TestAggregatorInit:
    """Test aggregator initialization."""

    def test_default_init(self):
        agg = HealthAggregator()
        assert agg.tracked_components == []
        assert agg.compute_health_score() == 1.0  # No checks = healthy

    def test_custom_weights(self):
        agg = HealthAggregator(weights={"custom_service": 2.0})
        assert agg._weights["custom_service"] == 2.0
        # Default weights preserved
        assert agg._weights["gemini_driver"] == DEFAULT_WEIGHTS["gemini_driver"]

    def test_custom_history_size(self):
        agg = HealthAggregator(history_size=10)
        assert agg._history_size == 10

    def test_custom_stale_threshold(self):
        agg = HealthAggregator(stale_threshold_seconds=60.0)
        assert agg._stale_threshold == 60.0


# =============================================================================
# HealthAggregator - Recording Tests
# =============================================================================


class TestRecording:
    """Test recording health checks."""

    def test_record_check(self):
        agg = HealthAggregator()
        check = agg.record_check("redis", status="healthy", message="Connected")
        assert check.component == "redis"
        assert check.status == "healthy"

    def test_record_updates_latest(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("redis", status="degraded")
        latest = agg.get_component_status("redis")
        assert latest.status == "degraded"

    def test_record_with_category(self):
        agg = HealthAggregator()
        agg.record_check("gemini_driver", status="healthy", category="driver")
        check = agg.get_component_status("gemini_driver")
        assert check.category == "driver"

    def test_record_with_details(self):
        agg = HealthAggregator()
        agg.record_check(
            "claude_driver",
            status="healthy",
            details={"model": "opus", "latency": 120},
        )
        check = agg.get_component_status("claude_driver")
        assert check.details["model"] == "opus"

    def test_record_with_latency(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy", latency_ms=3.5)
        check = agg.get_component_status("redis")
        assert check.latency_ms == 3.5

    def test_tracked_components(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("gemini_driver", status="healthy")
        components = agg.tracked_components
        assert "redis" in components
        assert "gemini_driver" in components
        assert len(components) == 2

    def test_get_nonexistent_component(self):
        agg = HealthAggregator()
        assert agg.get_component_status("missing") is None


# =============================================================================
# HealthAggregator - History Tests
# =============================================================================


class TestHistory:
    """Test component health history."""

    def test_history_accumulates(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("redis", status="degraded")
        agg.record_check("redis", status="healthy")
        history = agg.get_component_history("redis")
        assert len(history) == 3
        assert history[0].status == "healthy"
        assert history[1].status == "degraded"
        assert history[2].status == "healthy"

    def test_history_ring_buffer(self):
        agg = HealthAggregator(history_size=3)
        for i in range(5):
            agg.record_check("redis", status="healthy", message=f"check-{i}")
        history = agg.get_component_history("redis")
        assert len(history) == 3
        assert history[0].message == "check-2"  # Oldest kept
        assert history[2].message == "check-4"  # Most recent

    def test_empty_history(self):
        agg = HealthAggregator()
        assert agg.get_component_history("missing") == []

    def test_independent_histories(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("gemini", status="degraded")
        assert len(agg.get_component_history("redis")) == 1
        assert len(agg.get_component_history("gemini")) == 1


# =============================================================================
# HealthAggregator - Scoring Tests
# =============================================================================


class TestScoring:
    """Test composite health scoring."""

    def test_all_healthy(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("gemini_driver", status="healthy")
        assert agg.compute_health_score() == 1.0

    def test_all_unhealthy(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="unhealthy")
        agg.record_check("gemini_driver", status="unhealthy")
        assert agg.compute_health_score() == 0.0

    def test_mixed_status(self):
        agg = HealthAggregator(weights={"a": 1.0, "b": 1.0})
        agg.record_check("a", status="healthy")
        agg.record_check("b", status="unhealthy")
        score = agg.compute_health_score()
        assert score == 0.5  # Equal weights: (1.0 + 0.0) / 2

    def test_weighted_scoring(self):
        agg = HealthAggregator(weights={"critical": 2.0, "optional": 0.5})
        agg.record_check("critical", status="healthy")
        agg.record_check("optional", status="unhealthy")
        score = agg.compute_health_score()
        # (2.0 * 1.0 + 0.5 * 0.0) / (2.0 + 0.5) = 2.0 / 2.5 = 0.8
        assert abs(score - 0.8) < 0.001

    def test_degraded_scores_half(self):
        agg = HealthAggregator(weights={"a": 1.0})
        agg.record_check("a", status="degraded")
        assert agg.compute_health_score() == 0.5

    def test_no_checks_returns_1(self):
        agg = HealthAggregator()
        assert agg.compute_health_score() == 1.0

    def test_unknown_component_default_weight(self):
        agg = HealthAggregator()
        agg.record_check("unknown_service", status="healthy")
        # Default weight = 0.5
        assert agg.compute_health_score() == 1.0


# =============================================================================
# HealthAggregator - Overall Status Tests
# =============================================================================


class TestOverallStatus:
    """Test overall status determination."""

    def test_healthy_threshold(self):
        agg = HealthAggregator()
        agg.record_check("a", status="healthy")
        assert agg.get_overall_status() == "healthy"

    def test_degraded_threshold(self):
        agg = HealthAggregator(weights={"a": 1.0, "b": 1.0})
        agg.record_check("a", status="healthy")
        agg.record_check("b", status="degraded")
        # Score = 0.75 -> between 0.5 and 0.8 -> degraded
        assert agg.get_overall_status() == "degraded"

    def test_unhealthy_threshold(self):
        agg = HealthAggregator(weights={"a": 1.0, "b": 1.0})
        agg.record_check("a", status="unhealthy")
        agg.record_check("b", status="unhealthy")
        assert agg.get_overall_status() == "unhealthy"

    def test_boundary_at_08(self):
        agg = HealthAggregator(weights={"critical": 2.0, "optional": 0.5})
        agg.record_check("critical", status="healthy")
        agg.record_check("optional", status="unhealthy")
        # Score = 0.8 exactly -> healthy
        assert agg.get_overall_status() == "healthy"

    def test_boundary_below_05(self):
        agg = HealthAggregator(weights={"a": 1.0, "b": 1.0, "c": 1.0})
        agg.record_check("a", status="unhealthy")
        agg.record_check("b", status="unhealthy")
        agg.record_check("c", status="degraded")
        # Score = (0 + 0 + 0.5) / 3 = 0.167 -> unhealthy
        assert agg.get_overall_status() == "unhealthy"


# =============================================================================
# HealthAggregator - Report Tests
# =============================================================================


class TestReport:
    """Test report generation."""

    def test_basic_report(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy", message="OK")
        agg.record_check("gemini_driver", status="healthy", message="Online")
        report = agg.get_report()
        assert report.overall_status == "healthy"
        assert report.component_count == 2
        assert report.healthy_count == 2
        assert report.degraded_count == 0
        assert report.unhealthy_count == 0

    def test_report_with_telemetry(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.update_telemetry(
            TelemetrySummary(
                api_calls=50,
                total_tokens=25000,
                cost_usd=0.01,
            )
        )
        report = agg.get_report()
        assert report.telemetry["api_calls"] == 50
        assert report.telemetry["total_tokens"] == 25000

    def test_report_without_telemetry(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        report = agg.get_report()
        assert report.telemetry == {}

    def test_report_counts(self):
        agg = HealthAggregator()
        agg.record_check("a", status="healthy")
        agg.record_check("b", status="degraded")
        agg.record_check("c", status="unhealthy")
        report = agg.get_report()
        assert report.component_count == 3
        assert report.healthy_count == 1
        assert report.degraded_count == 1
        assert report.unhealthy_count == 1

    def test_report_to_dict(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        report = agg.get_report()
        d = report.to_dict()
        assert "overall_status" in d
        assert "health_score" in d
        assert "components" in d
        assert "generated_at" in d

    def test_report_summary_text(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        report = agg.get_report()
        assert "NEXUS Health:" in report.summary
        assert "HEALTHY" in report.summary

    def test_report_summary_with_telemetry(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.update_telemetry(
            TelemetrySummary(
                api_calls=10,
                total_errors=2,
                cost_usd=0.005,
                budget_utilization_pct=15.0,
            )
        )
        report = agg.get_report()
        assert "API Calls: 10" in report.summary
        assert "Errors: 2" in report.summary

    def test_report_summary_with_budget_warning(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.update_telemetry(
            TelemetrySummary(
                budget_warning_level="critical",
                cost_usd=0.01,
                budget_utilization_pct=92.0,
            )
        )
        report = agg.get_report()
        assert "Budget Warning: critical" in report.summary


# =============================================================================
# HealthAggregator - Telemetry Integration Tests
# =============================================================================


class TestTelemetryIntegration:
    """Test telemetry collector integration."""

    def test_update_from_collector(self):
        agg = HealthAggregator()

        # Create a mock collector
        collector = MagicMock()
        session = MagicMock()
        session.total_api_calls = 100
        session.total_tokens = 50000
        session.total_errors = 3
        session.swarm_tasks = 5
        session.tool_executions = 20
        session.duration_seconds = 300.0
        collector.get_session_summary.return_value = session
        collector.get_budget_stats.return_value = {"percentage_used": 25.0}
        collector.get_budget_warning_level.return_value = None
        collector._total_cost_usd = 0.05

        agg.update_telemetry_from_collector(collector)
        report = agg.get_report()

        assert report.telemetry["api_calls"] == 100
        assert report.telemetry["total_tokens"] == 50000
        assert report.telemetry["total_errors"] == 3
        assert report.telemetry["budget_utilization_pct"] == 25.0

    def test_error_rate_calculation(self):
        agg = HealthAggregator()

        collector = MagicMock()
        session = MagicMock()
        session.total_api_calls = 80
        session.total_tokens = 40000
        session.total_errors = 10
        session.swarm_tasks = 5
        session.tool_executions = 20
        session.duration_seconds = 200.0
        collector.get_session_summary.return_value = session
        collector.get_budget_stats.return_value = None
        collector.get_budget_warning_level.return_value = None
        collector._total_cost_usd = 0.0

        agg.update_telemetry_from_collector(collector)
        report = agg.get_report()

        # Error rate = 10 / (80 + 20) = 0.1
        assert report.telemetry["error_rate"] == 0.1

    def test_zero_operations_no_division_error(self):
        agg = HealthAggregator()

        collector = MagicMock()
        session = MagicMock()
        session.total_api_calls = 0
        session.total_tokens = 0
        session.total_errors = 0
        session.swarm_tasks = 0
        session.tool_executions = 0
        session.duration_seconds = 0.0
        collector.get_session_summary.return_value = session
        collector.get_budget_stats.return_value = None
        collector.get_budget_warning_level.return_value = None
        collector._total_cost_usd = 0.0

        agg.update_telemetry_from_collector(collector)
        report = agg.get_report()
        assert report.telemetry["error_rate"] == 0.0


# =============================================================================
# HealthAggregator - Stale Detection Tests
# =============================================================================


class TestStaleDetection:
    """Test stale component detection."""

    def test_fresh_not_stale(self):
        agg = HealthAggregator(stale_threshold_seconds=300)
        agg.record_check("redis", status="healthy")
        assert "redis" not in agg.get_stale_components()

    def test_old_check_is_stale(self):
        agg = HealthAggregator(stale_threshold_seconds=1.0)
        old_ts = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        check = HealthCheck(component="redis", status="healthy", timestamp=old_ts)
        with agg._lock:
            agg._latest["redis"] = check
        stale = agg.get_stale_components()
        assert "redis" in stale

    def test_no_stale_when_empty(self):
        agg = HealthAggregator()
        assert agg.get_stale_components() == []


# =============================================================================
# HealthAggregator - Clear/Remove Tests
# =============================================================================


class TestClearRemove:
    """Test clearing and removing components."""

    def test_clear_all(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("gemini", status="healthy")
        agg.update_telemetry(TelemetrySummary(api_calls=10))
        agg.clear()
        assert agg.tracked_components == []
        report = agg.get_report()
        assert report.telemetry == {}

    def test_remove_component(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("gemini", status="healthy")
        assert agg.remove_component("redis") is True
        assert "redis" not in agg.tracked_components
        assert "gemini" in agg.tracked_components

    def test_remove_nonexistent(self):
        agg = HealthAggregator()
        assert agg.remove_component("missing") is False

    def test_remove_clears_history(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        agg.record_check("redis", status="degraded")
        agg.remove_component("redis")
        assert agg.get_component_history("redis") == []


# =============================================================================
# HealthAggregator - State Export Tests
# =============================================================================


class TestStateExport:
    """Test aggregator state export."""

    def test_to_dict(self):
        agg = HealthAggregator()
        agg.record_check("redis", status="healthy")
        d = agg.to_dict()
        assert d["tracked_components"] == 1
        assert d["overall_status"] == "healthy"
        assert "health_score" in d
        assert "stale_components" in d

    def test_to_dict_empty(self):
        agg = HealthAggregator()
        d = agg.to_dict()
        assert d["tracked_components"] == 0
        assert d["overall_status"] == "healthy"


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test module-level constants."""

    def test_aggregate_status_values(self):
        assert AggregateStatus.HEALTHY.value == "healthy"
        assert AggregateStatus.DEGRADED.value == "degraded"
        assert AggregateStatus.UNHEALTHY.value == "unhealthy"

    def test_component_category_values(self):
        assert ComponentCategory.DRIVER.value == "driver"
        assert ComponentCategory.INFRASTRUCTURE.value == "infrastructure"

    def test_status_scores(self):
        assert STATUS_SCORES["healthy"] == 1.0
        assert STATUS_SCORES["degraded"] == 0.5
        assert STATUS_SCORES["unhealthy"] == 0.0

    def test_default_weights_exist(self):
        assert "gemini_driver" in DEFAULT_WEIGHTS
        assert "claude_driver" in DEFAULT_WEIGHTS
        assert "redis" in DEFAULT_WEIGHTS


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that health aggregator types are importable."""

    def test_from_telemetry_package(self):
        from core.observability.telemetry import (
            AggregateStatus,
            HealthAggregator,
            HealthCheck,
            HealthReport,
            TelemetrySummary,
        )

        assert all([HealthAggregator, HealthCheck, HealthReport, TelemetrySummary, AggregateStatus])

    def test_from_module(self):
        from core.observability.telemetry.health_aggregator import (
            AggregateStatus,
            ComponentCategory,
            HealthAggregator,
            HealthCheck,
            HealthReport,
            TelemetrySummary,
        )

        assert all([HealthAggregator, HealthCheck, HealthReport, TelemetrySummary, AggregateStatus, ComponentCategory])
