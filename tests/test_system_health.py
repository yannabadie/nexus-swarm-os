"""
Tests for core/resilience/system_health.py - V9.5

Validates unified health monitoring for all V9.5 components.
"""

import pytest

from core.infrastructure.resilience.system_health import (
    ComponentHealth,
    HealthReport,
    HealthStatus,
    SystemHealth,
    get_system_health,
    reset_system_health,
)


@pytest.fixture(autouse=True)
def reset_health():
    """Reset system health before each test."""
    reset_system_health()
    yield
    reset_system_health()


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_status_values(self):
        """All status values should exist."""
        assert HealthStatus.HEALTHY
        assert HealthStatus.DEGRADED
        assert HealthStatus.UNHEALTHY
        assert HealthStatus.UNKNOWN

    def test_status_string_values(self):
        """Status should have correct string values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"


class TestComponentHealth:
    """Test ComponentHealth dataclass."""

    def test_create_healthy_component(self):
        """Should create healthy component."""
        health = ComponentHealth(name="TestComponent", status=HealthStatus.HEALTHY, message="All good")
        assert health.name == "TestComponent"
        assert health.status == HealthStatus.HEALTHY

    def test_component_with_details(self):
        """Should store details."""
        health = ComponentHealth(name="Test", status=HealthStatus.HEALTHY, message="OK", details={"count": 42})
        assert health.details["count"] == 42

    def test_to_dict(self):
        """Should convert to dictionary."""
        health = ComponentHealth(name="Test", status=HealthStatus.HEALTHY, message="OK")
        data = health.to_dict()
        assert data["name"] == "Test"
        assert data["status"] == "healthy"


class TestHealthReport:
    """Test HealthReport dataclass."""

    def test_create_report(self):
        """Should create health report."""
        components = [
            ComponentHealth("A", HealthStatus.HEALTHY, "OK"),
            ComponentHealth("B", HealthStatus.HEALTHY, "OK"),
        ]
        report = HealthReport(components=components, overall_status=HealthStatus.HEALTHY)
        assert len(report.components) == 2
        assert report.overall_status == HealthStatus.HEALTHY

    def test_healthy_count(self):
        """Should count healthy components."""
        components = [
            ComponentHealth("A", HealthStatus.HEALTHY, "OK"),
            ComponentHealth("B", HealthStatus.UNHEALTHY, "Failed"),
            ComponentHealth("C", HealthStatus.HEALTHY, "OK"),
        ]
        report = HealthReport(components, HealthStatus.DEGRADED)
        assert report.healthy_count == 2
        assert report.unhealthy_count == 1

    def test_summary(self):
        """Should generate summary string."""
        components = [
            ComponentHealth("Test", HealthStatus.HEALTHY, "OK"),
        ]
        report = HealthReport(components, HealthStatus.HEALTHY)
        summary = report.summary()
        assert "HEALTHY" in summary
        assert "Test" in summary

    def test_to_dict(self):
        """Should convert to dictionary."""
        components = [
            ComponentHealth("A", HealthStatus.HEALTHY, "OK"),
        ]
        report = HealthReport(components, HealthStatus.HEALTHY)
        data = report.to_dict()
        assert data["overall_status"] == "healthy"
        assert len(data["components"]) == 1


class TestSystemHealth:
    """Test SystemHealth class."""

    def test_create_health_monitor(self):
        """Should create health monitor."""
        health = SystemHealth()
        assert health is not None

    @pytest.mark.asyncio
    async def test_check_all(self):
        """Should check all components."""
        health = SystemHealth()
        report = await health.check_all()

        assert report is not None
        assert len(report.components) > 0
        assert report.overall_status in HealthStatus

    @pytest.mark.asyncio
    async def test_check_constants(self):
        """Should check constants module."""
        health = SystemHealth()
        result = health._check_constants()

        assert result.name == "Constants"
        # Should be healthy if module is installed
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]

    @pytest.mark.asyncio
    async def test_check_safe_task_manager(self):
        """Should check SafeTaskManager."""
        health = SystemHealth()
        result = health._check_safe_task_manager()

        assert result.name == "SafeTaskManager"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]

    @pytest.mark.asyncio
    async def test_check_event_bus(self):
        """Should check EventBus."""
        health = SystemHealth()
        result = await health._check_event_bus()

        assert result.name == "EventBus"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]

    @pytest.mark.asyncio
    async def test_check_tool_registry(self):
        """Should check ToolRegistry."""
        health = SystemHealth()
        result = health._check_tool_registry()

        assert result.name == "ToolRegistry"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]

    @pytest.mark.asyncio
    async def test_last_report(self):
        """Should store last report."""
        health = SystemHealth()
        assert health.last_report is None

        await health.check_all()
        assert health.last_report is not None


class TestGlobalHealthMonitor:
    """Test global singleton."""

    def test_singleton_instance(self):
        """get_system_health should return same instance."""
        h1 = get_system_health()
        h2 = get_system_health()
        assert h1 is h2

    def test_reset_creates_new(self):
        """reset_system_health should clear instance."""
        h1 = get_system_health()
        reset_system_health()
        h2 = get_system_health()
        assert h1 is not h2


class TestV95Integration:
    """Integration tests for V9.5 components."""

    @pytest.mark.asyncio
    async def test_all_v95_components_available(self):
        """All V9.5 components should be importable."""
        # This tests that all Sprint 1-4 components integrate
        from core.constants import CONSTANTS_VERSION

        # All imports succeeded
        # V11.4: Accept any 9.x or higher version
        major_version = int(CONSTANTS_VERSION.split(".")[0])
        assert major_version >= 9, f"Expected version >= 9, got {CONSTANTS_VERSION}"

    @pytest.mark.asyncio
    async def test_health_check_reports_all_components(self):
        """Health check should report on all V9.5 components."""
        health = get_system_health()
        report = await health.check_all()

        component_names = [c.name for c in report.components]

        # Should include all V9.5 components
        assert "Constants" in component_names
        assert "SafeTaskManager" in component_names
        assert "EventBus" in component_names
        assert "ToolRegistry" in component_names
        assert "CircuitBreaker" in component_names

    @pytest.mark.asyncio
    async def test_summary_is_readable(self):
        """Summary should be human-readable."""
        health = get_system_health()
        report = await health.check_all()
        summary = report.summary()

        # Should contain status and components
        assert "System Health" in summary
        assert "Components" in summary
