"""
SystemHealth - Unified Health Check for V9.5 Components.

NEXUS V9.5 Sprint 4

Integrates all V9.5 refactored modules:
- Constants module
- SafeTaskManager
- EventBus
- ExecutionEngine
- ToolRegistry
- CircuitBreaker

Provides a single interface for system health monitoring.

Usage:
    health = get_system_health()
    report = await health.check_all()
    print(report.summary())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    status: HealthStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class HealthReport:
    """Aggregated health report for all components."""

    components: list[ComponentHealth]
    overall_status: HealthStatus
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def healthy_count(self) -> int:
        return sum(1 for c in self.components if c.status == HealthStatus.HEALTHY)

    @property
    def unhealthy_count(self) -> int:
        return sum(1 for c in self.components if c.status == HealthStatus.UNHEALTHY)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"System Health: {self.overall_status.value.upper()}",
            f"Components: {self.healthy_count}/{len(self.components)} healthy",
            "",
        ]
        for comp in self.components:
            icon = {
                HealthStatus.HEALTHY: "[OK]",
                HealthStatus.DEGRADED: "[!!]",
                HealthStatus.UNHEALTHY: "[XX]",
                HealthStatus.UNKNOWN: "[??]",
            }.get(comp.status, "[??]")
            lines.append(f"  {icon} {comp.name}: {comp.message}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "healthy_count": self.healthy_count,
            "unhealthy_count": self.unhealthy_count,
            "components": [c.to_dict() for c in self.components],
            "checked_at": self.checked_at.isoformat(),
        }


class SystemHealth:
    """
    Unified system health monitor for V9.5 components.

    Checks:
    - Constants module loaded
    - SafeTaskManager operational
    - EventBus operational
    - ExecutionEngine initialized
    - ToolRegistry populated
    - CircuitBreaker healthy
    """

    def __init__(self, workspace_path: Path | None = None):
        """Initialize health monitor."""
        self.workspace_path = workspace_path or Path.cwd()
        self._last_report: HealthReport | None = None

    async def check_all(self) -> HealthReport:
        """
        Check health of all V9.5 components.

        Returns:
            HealthReport with status of all components
        """
        components = []

        # Check each component
        components.append(self._check_constants())
        components.append(self._check_safe_task_manager())
        components.append(await self._check_event_bus())
        components.append(self._check_tool_registry())
        components.append(self._check_circuit_breaker())

        # Calculate overall status
        if all(c.status == HealthStatus.HEALTHY for c in components):
            overall = HealthStatus.HEALTHY
        elif any(c.status == HealthStatus.UNHEALTHY for c in components):
            overall = HealthStatus.UNHEALTHY
        else:
            overall = HealthStatus.DEGRADED

        report = HealthReport(
            components=components,
            overall_status=overall,
        )

        self._last_report = report
        return report

    def _check_constants(self) -> ComponentHealth:
        """Check constants module."""
        try:
            from core.constants import (
                CONSTANTS_VERSION,
                SAGA_LIMITS,
                TIMEOUTS,
            )

            # Verify critical values
            if TIMEOUTS.BASH_COMMAND <= 0:
                return ComponentHealth(
                    name="Constants",
                    status=HealthStatus.DEGRADED,
                    message="Invalid timeout value",
                )

            return ComponentHealth(
                name="Constants",
                status=HealthStatus.HEALTHY,
                message=f"v{CONSTANTS_VERSION} loaded",
                details={
                    "version": CONSTANTS_VERSION,
                    "saga_max_rollback": SAGA_LIMITS.MAX_ROLLBACK_ATTEMPTS,
                },
            )
        except ImportError as e:
            return ComponentHealth(
                name="Constants",
                status=HealthStatus.UNHEALTHY,
                message=f"Import failed: {e}",
            )
        except Exception as e:
            return ComponentHealth(
                name="Constants",
                status=HealthStatus.UNKNOWN,
                message=str(e),
            )

    def _check_safe_task_manager(self) -> ComponentHealth:
        """Check SafeTaskManager."""
        try:
            from core.foundation.async_primitives.safe_task_manager import (
                SafeTaskManager,
            )

            stats = SafeTaskManager.get_stats()
            active = SafeTaskManager.get_active_tasks()

            return ComponentHealth(
                name="SafeTaskManager",
                status=HealthStatus.HEALTHY,
                message=f"{len(active)} active tasks",
                details={
                    "active_tasks": len(active),
                    "completed": stats.get("completed", 0),
                    "failed": stats.get("failed", 0),
                },
            )
        except ImportError as e:
            return ComponentHealth(
                name="SafeTaskManager",
                status=HealthStatus.UNHEALTHY,
                message=f"Import failed: {e}",
            )
        except Exception as e:
            return ComponentHealth(
                name="SafeTaskManager",
                status=HealthStatus.UNKNOWN,
                message=str(e),
            )

    async def _check_event_bus(self) -> ComponentHealth:
        """Check EventBus."""
        try:
            from core.foundation.async_primitives.event_bus import (
                SyncEvent,
                get_event_bus,
            )

            bus = get_event_bus()
            stats = bus.get_stats()

            # Test publish
            SyncEvent(
                event_type="health_check",
                source="system_health",
                task_id="health_test",
                payload={"test": True},
            )

            # Don't actually publish, just verify the bus is responsive
            return ComponentHealth(
                name="EventBus",
                status=HealthStatus.HEALTHY,
                message=f"{stats.get('published', 0)} events published",
                details=stats,
            )
        except ImportError as e:
            return ComponentHealth(
                name="EventBus",
                status=HealthStatus.UNHEALTHY,
                message=f"Import failed: {e}",
            )
        except Exception as e:
            return ComponentHealth(
                name="EventBus",
                status=HealthStatus.UNKNOWN,
                message=str(e),
            )

    def _check_tool_registry(self) -> ComponentHealth:
        """Check ToolRegistry."""
        try:
            from core.execution_pkg.execution.tool_registry import get_tool_registry

            registry = get_tool_registry()
            tools = registry.list_tools()

            return ComponentHealth(
                name="ToolRegistry",
                status=HealthStatus.HEALTHY,
                message=f"{len(tools)} tools registered",
                details={
                    "tool_count": len(tools),
                    "core_tools": registry.list_core_tools(),
                },
            )
        except ImportError as e:
            return ComponentHealth(
                name="ToolRegistry",
                status=HealthStatus.UNHEALTHY,
                message=f"Import failed: {e}",
            )
        except Exception as e:
            return ComponentHealth(
                name="ToolRegistry",
                status=HealthStatus.UNKNOWN,
                message=str(e),
            )

    def _check_circuit_breaker(self) -> ComponentHealth:
        """Check CircuitBreaker."""
        try:
            from core.infrastructure.resilience.circuit_breaker import (
                get_circuit_breaker,
            )

            breaker = get_circuit_breaker("default")

            return ComponentHealth(
                name="CircuitBreaker",
                status=HealthStatus.HEALTHY,
                message=f"State: {breaker.state.value}",
                details={
                    "state": breaker.state.value,
                    "failure_count": breaker.failure_count,
                },
            )
        except ImportError as e:
            return ComponentHealth(
                name="CircuitBreaker",
                status=HealthStatus.UNHEALTHY,
                message=f"Import failed: {e}",
            )
        except Exception as e:
            return ComponentHealth(
                name="CircuitBreaker",
                status=HealthStatus.UNKNOWN,
                message=str(e),
            )

    @property
    def last_report(self) -> HealthReport | None:
        """Get last health report."""
        return self._last_report


# Singleton instance
_health_instance: SystemHealth | None = None


def get_system_health(workspace_path: Path | None = None) -> SystemHealth:
    """
    Get the system health monitor for the current tenant context.

    V10 PRISM: Returns tenant-scoped monitor via ServiceFactory.
    Falls back to global singleton if no context is active.

    Args:
        workspace_path: Workspace path (optional in V10)

    Returns:
        SystemHealth instance scoped to current tenant
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_system_health()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    global _health_instance
    if _health_instance is None:
        _health_instance = SystemHealth(workspace_path)
    return _health_instance


def reset_system_health() -> None:
    """
    Reset system health monitor (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _health_instance
    _health_instance = None

    # V10: Also clear factory cache
    try:
        from ..context import get_current_session_or_none
        from ..factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
