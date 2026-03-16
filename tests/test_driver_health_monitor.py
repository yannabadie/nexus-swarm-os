"""
Tests for V12.4 Driver Health Monitor.

Validates:
- HealthStatus enum values
- HealthEvent creation
- DriverHealth to_dict
- HealthAlert creation and to_dict
- MonitorStats to_dict
- Record success/failure events
- Health classification (healthy, degraded, unhealthy)
- P95 latency tracking
- Alert generation on status change
- Healthy driver listing
- Statistics tracking
- State management (clear, clear_driver)
- Global singleton
- Module exports
"""

from core.drivers.driver_health_monitor import (
    DriverHealth,
    DriverHealthMonitor,
    HealthAlert,
    HealthEvent,
    HealthStatus,
    get_health_monitor,
    reset_health_monitor,
)

# =============================================================================
# HealthStatus Tests
# =============================================================================


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_healthy(self):
        assert HealthStatus.HEALTHY.value == "healthy"

    def test_degraded(self):
        assert HealthStatus.DEGRADED.value == "degraded"

    def test_unhealthy(self):
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_unknown(self):
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_count(self):
        assert len(HealthStatus) == 4


# =============================================================================
# HealthEvent Tests
# =============================================================================


class TestHealthEvent:
    """Test HealthEvent dataclass."""

    def test_basic(self):
        e = HealthEvent(driver_id="claude", success=True, latency_ms=100)
        assert e.driver_id == "claude"
        assert e.success is True
        assert e.latency_ms == 100

    def test_auto_timestamp(self):
        e = HealthEvent(driver_id="test", success=True)
        assert e.timestamp > 0

    def test_failure_with_error(self):
        e = HealthEvent(driver_id="test", success=False, error="timeout")
        assert e.error == "timeout"


# =============================================================================
# DriverHealth Tests
# =============================================================================


class TestDriverHealth:
    """Test DriverHealth dataclass."""

    def test_to_dict(self):
        h = DriverHealth(
            driver_id="claude",
            status=HealthStatus.HEALTHY,
            total_requests=100,
            error_rate=0.05,
            avg_latency_ms=200.5,
        )
        d = h.to_dict()
        assert d["driver_id"] == "claude"
        assert d["status"] == "healthy"
        assert d["error_rate"] == 0.05

    def test_defaults(self):
        h = DriverHealth(driver_id="test")
        assert h.status == HealthStatus.UNKNOWN
        assert h.total_requests == 0


# =============================================================================
# HealthAlert Tests
# =============================================================================


class TestHealthAlert:
    """Test HealthAlert dataclass."""

    def test_creation(self):
        a = HealthAlert(
            driver_id="claude",
            alert_type="degraded",
            message="test",
            previous_status=HealthStatus.HEALTHY,
            current_status=HealthStatus.DEGRADED,
        )
        assert a.alert_type == "degraded"

    def test_to_dict(self):
        a = HealthAlert(
            driver_id="claude",
            alert_type="unhealthy",
            message="msg",
            previous_status=HealthStatus.DEGRADED,
            current_status=HealthStatus.UNHEALTHY,
        )
        d = a.to_dict()
        assert d["previous_status"] == "degraded"
        assert d["current_status"] == "unhealthy"


# =============================================================================
# Record Tests
# =============================================================================


class TestRecord:
    """Test event recording."""

    def test_record_success(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude", latency_ms=200, tokens=500)
        assert mon.driver_count == 1

    def test_record_failure(self):
        mon = DriverHealthMonitor()
        mon.record_failure("claude", error="timeout", latency_ms=10000)
        health = mon.get_health("claude")
        assert health.failed_requests == 1

    def test_record_multiple_drivers(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude")
        mon.record_success("gemini")
        assert mon.driver_count == 2

    def test_record_tracks_tokens(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude", tokens=100)
        mon.record_success("claude", tokens=200)
        health = mon.get_health("claude")
        assert health.total_tokens == 300


# =============================================================================
# Health Classification Tests
# =============================================================================


class TestClassification:
    """Test health classification."""

    def test_healthy(self):
        mon = DriverHealthMonitor()
        for _ in range(10):
            mon.record_success("claude", latency_ms=200)
        health = mon.get_health("claude")
        assert health.status == HealthStatus.HEALTHY

    def test_degraded_by_errors(self):
        mon = DriverHealthMonitor()
        for _ in range(8):
            mon.record_success("claude")
        for _ in range(3):
            mon.record_failure("claude")
        health = mon.get_health("claude")
        # error_rate = 3/11 ≈ 0.27 > 0.2 = degraded
        assert health.status == HealthStatus.DEGRADED

    def test_unhealthy_by_errors(self):
        mon = DriverHealthMonitor()
        for _ in range(5):
            mon.record_success("claude")
        for _ in range(6):
            mon.record_failure("claude")
        health = mon.get_health("claude")
        # error_rate = 6/11 ≈ 0.55 > 0.5 = unhealthy
        assert health.status == HealthStatus.UNHEALTHY

    def test_degraded_by_latency(self):
        mon = DriverHealthMonitor()
        for _ in range(10):
            mon.record_success("claude", latency_ms=6000)
        health = mon.get_health("claude")
        assert health.status == HealthStatus.DEGRADED

    def test_unhealthy_by_latency(self):
        mon = DriverHealthMonitor()
        for _ in range(10):
            mon.record_success("claude", latency_ms=20000)
        health = mon.get_health("claude")
        assert health.status == HealthStatus.UNHEALTHY

    def test_unknown_no_events(self):
        mon = DriverHealthMonitor()
        health = mon.get_health("missing")
        assert health.status == HealthStatus.UNKNOWN

    def test_error_rate_calculation(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude")
        mon.record_failure("claude")
        health = mon.get_health("claude")
        assert abs(health.error_rate - 0.5) < 0.01

    def test_avg_latency(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude", latency_ms=100)
        mon.record_success("claude", latency_ms=300)
        health = mon.get_health("claude")
        assert abs(health.avg_latency_ms - 200) < 0.01

    def test_p95_latency(self):
        mon = DriverHealthMonitor()
        for i in range(100):
            mon.record_success("claude", latency_ms=float(i + 1))
        health = mon.get_health("claude")
        assert health.p95_latency_ms >= 95

    def test_recent_errors(self):
        mon = DriverHealthMonitor()
        mon.record_failure("claude", error="err1")
        mon.record_failure("claude", error="err2")
        health = mon.get_health("claude")
        assert "err2" in health.recent_errors
        assert "err1" in health.recent_errors


# =============================================================================
# Alert Tests
# =============================================================================


class TestAlerts:
    """Test health alerts."""

    def test_alert_on_degradation(self):
        mon = DriverHealthMonitor()
        # Start healthy
        for _ in range(10):
            mon.record_success("claude", latency_ms=100)
        # Then degrade
        for _ in range(10):
            mon.record_failure("claude")
        alerts = mon.get_alerts()
        assert len(alerts) >= 1
        # Should have a degraded or unhealthy alert
        types = [a.alert_type for a in alerts]
        assert any(t in ("degraded", "unhealthy") for t in types)

    def test_alert_on_recovery(self):
        mon = DriverHealthMonitor()
        # Start with failures (establish unhealthy baseline)
        for _ in range(20):
            mon.record_failure("claude")
        # Then recover with enough successes to bring error_rate < 0.2
        for _ in range(100):
            mon.record_success("claude", latency_ms=100)
        alerts = mon.get_alerts()
        types = [a.alert_type for a in alerts]
        assert "recovered" in types

    def test_no_alert_first_event(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude")
        assert mon.alert_count == 0

    def test_alert_to_dict(self):
        mon = DriverHealthMonitor()
        for _ in range(10):
            mon.record_success("claude", latency_ms=100)
        for _ in range(20):
            mon.record_failure("claude")
        alerts = mon.get_alerts()
        if alerts:
            d = alerts[0].to_dict()
            assert "driver_id" in d
            assert "alert_type" in d


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test driver listing."""

    def test_get_healthy_drivers(self):
        mon = DriverHealthMonitor()
        for _ in range(10):
            mon.record_success("claude", latency_ms=100)
        for _ in range(10):
            mon.record_success("gemini", latency_ms=200)
        for _ in range(10):
            mon.record_failure("broken")
        healthy = mon.get_healthy_drivers()
        assert "claude" in healthy
        assert "gemini" in healthy
        assert "broken" not in healthy

    def test_get_all_health(self):
        mon = DriverHealthMonitor()
        mon.record_success("a")
        mon.record_success("b")
        all_health = mon.get_all_health()
        assert "a" in all_health
        assert "b" in all_health

    def test_is_healthy(self):
        mon = DriverHealthMonitor()
        for _ in range(5):
            mon.record_success("claude", latency_ms=100)
        assert mon.is_healthy("claude") is True
        assert mon.is_healthy("missing") is False


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test monitoring statistics."""

    def test_initial_stats(self):
        mon = DriverHealthMonitor()
        stats = mon.get_stats()
        assert stats.drivers_tracked == 0
        assert stats.total_events == 0

    def test_stats_after_events(self):
        mon = DriverHealthMonitor()
        for _ in range(5):
            mon.record_success("claude")
        for _ in range(3):
            mon.record_failure("gemini")
        stats = mon.get_stats()
        assert stats.drivers_tracked == 2
        assert stats.total_events == 8

    def test_stats_to_dict(self):
        mon = DriverHealthMonitor()
        d = mon.get_stats().to_dict()
        assert "drivers_tracked" in d
        assert "healthy_count" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_driver_count(self):
        mon = DriverHealthMonitor()
        mon.record_success("a")
        mon.record_success("b")
        assert mon.driver_count == 2

    def test_clear(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude")
        mon.clear()
        assert mon.driver_count == 0
        assert mon.alert_count == 0

    def test_clear_driver(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude")
        mon.record_success("gemini")
        assert mon.clear_driver("claude") is True
        assert mon.driver_count == 1

    def test_clear_driver_not_found(self):
        mon = DriverHealthMonitor()
        assert mon.clear_driver("missing") is False

    def test_to_dict(self):
        mon = DriverHealthMonitor()
        mon.record_success("claude")
        d = mon.to_dict()
        assert d["driver_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global health monitor."""

    def test_get_health_monitor(self):
        reset_health_monitor()
        mon = get_health_monitor()
        assert isinstance(mon, DriverHealthMonitor)

    def test_singleton(self):
        reset_health_monitor()
        m1 = get_health_monitor()
        m2 = get_health_monitor()
        assert m1 is m2

    def test_reset(self):
        reset_health_monitor()
        m1 = get_health_monitor()
        reset_health_monitor()
        m2 = get_health_monitor()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_drivers_package(self):
        from core.drivers import (
            DriverHealth,
            DriverHealthMonitor,
            HealthAlert,
            HealthStatus,
            MonitorStats,
            get_health_monitor,
            reset_health_monitor,
        )

        assert all(
            [
                DriverHealthMonitor,
                DriverHealth,
                HealthStatus,
                HealthAlert,
                MonitorStats,
                get_health_monitor,
                reset_health_monitor,
            ]
        )

    def test_from_module(self):
        from core.drivers.driver_health_monitor import (
            DEGRADED_ERROR_RATE,
            MAX_HISTORY,
        )

        assert MAX_HISTORY == 200
        assert DEGRADED_ERROR_RATE == 0.2
