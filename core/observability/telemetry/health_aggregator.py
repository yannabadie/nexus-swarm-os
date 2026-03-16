"""
Unified Health Dashboard Aggregator - Single-pane-of-glass health monitoring.

V12.4 COGNITIVE BOOST - Task #36

Collects health data from all NEXUS subsystems and produces a unified
dashboard report. Designed to feed CEREBRO UI and API health endpoints.

Data Sources:
- SystemHealth (component status: constants, task manager, event bus, tools, circuit breaker)
- TelemetryCollector (API calls, tokens, errors, swarm tasks, tool executions)
- BudgetTracker (cost, daily spend, budget utilization)
- Driver health checks (Gemini, Claude, Ollama availability)

Usage:
    from core.observability.telemetry.health_aggregator import HealthAggregator

    aggregator = HealthAggregator()
    aggregator.record_check("gemini_driver", status="healthy", latency_ms=45.0)
    aggregator.record_check("redis", status="degraded", message="High latency")

    report = aggregator.get_report()
    print(report["overall_status"])  # "healthy" / "degraded" / "unhealthy"
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from threading import Lock
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


class AggregateStatus(Enum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentCategory(Enum):
    """Categories for health check components."""

    DRIVER = "driver"
    INFRASTRUCTURE = "infrastructure"
    SUBSYSTEM = "subsystem"
    EXTERNAL = "external"


@dataclass
class HealthCheck:
    """A single health check result."""

    component: str
    status: str  # "healthy", "degraded", "unhealthy"
    category: str = "subsystem"
    message: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status,
            "category": self.category,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class TelemetrySummary:
    """Summary of telemetry metrics for the dashboard."""

    api_calls: int = 0
    total_tokens: int = 0
    total_errors: int = 0
    swarm_tasks: int = 0
    tool_executions: int = 0
    session_duration_seconds: float = 0.0
    cost_usd: float = 0.0
    budget_utilization_pct: float = 0.0
    budget_warning_level: str | None = None
    error_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_calls": self.api_calls,
            "total_tokens": self.total_tokens,
            "total_errors": self.total_errors,
            "swarm_tasks": self.swarm_tasks,
            "tool_executions": self.tool_executions,
            "session_duration_seconds": round(self.session_duration_seconds, 2),
            "cost_usd": round(self.cost_usd, 6),
            "budget_utilization_pct": round(self.budget_utilization_pct, 1),
            "budget_warning_level": self.budget_warning_level,
            "error_rate": round(self.error_rate, 4),
        }


@dataclass
class HealthReport:
    """Complete aggregated health report."""

    overall_status: str  # "healthy", "degraded", "unhealthy"
    health_score: float  # 0.0 - 1.0
    components: list[dict[str, Any]]
    telemetry: dict[str, Any]
    summary: str  # Human-readable summary
    component_count: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    unhealthy_count: int = 0
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "health_score": round(self.health_score, 3),
            "component_count": self.component_count,
            "healthy_count": self.healthy_count,
            "degraded_count": self.degraded_count,
            "unhealthy_count": self.unhealthy_count,
            "components": self.components,
            "telemetry": self.telemetry,
            "summary": self.summary,
            "generated_at": self.generated_at,
        }


# =============================================================================
# Component Weights
# =============================================================================

# Weight determines how much each component affects the overall health score.
# Higher weight = more impact on the composite score.
DEFAULT_WEIGHTS: dict[str, float] = {
    "gemini_driver": 1.0,
    "claude_driver": 1.0,
    "ollama_driver": 0.3,  # Optional component
    "redis": 0.7,
    "event_bus": 0.5,
    "circuit_breaker": 0.8,
    "tool_registry": 0.6,
    "constants": 0.4,
    "safe_task_manager": 0.5,
    "budget": 0.6,
}

# Status score mapping
STATUS_SCORES: dict[str, float] = {
    "healthy": 1.0,
    "degraded": 0.5,
    "unhealthy": 0.0,
}


# =============================================================================
# Health Aggregator
# =============================================================================


class HealthAggregator:
    """
    Unified health dashboard aggregator.

    Collects health checks from all NEXUS subsystems, computes a weighted
    composite health score, and produces dashboard-ready reports.

    Features:
    - Weighted composite health scoring
    - Component health history (ring buffer)
    - Telemetry integration (API calls, cost, errors)
    - Human-readable summary generation
    - Thread-safe
    """

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        history_size: int = 100,
        stale_threshold_seconds: float = 300.0,
    ):
        """
        Initialize the health aggregator.

        Args:
            weights: Component weight overrides (merged with defaults)
            history_size: Max health checks to keep in history per component
            stale_threshold_seconds: After this many seconds, a check is stale
        """
        self._weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self._weights.update(weights)

        self._history_size = history_size
        self._stale_threshold = stale_threshold_seconds
        self._lock = Lock()

        # Latest check per component
        self._latest: dict[str, HealthCheck] = {}

        # History per component (ring buffer)
        self._history: dict[str, deque[HealthCheck]] = {}

        # Telemetry snapshot (updated externally)
        self._telemetry: TelemetrySummary | None = None

    def record_check(
        self,
        component: str,
        *,
        status: str = "healthy",
        category: str = "subsystem",
        message: str = "",
        latency_ms: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> HealthCheck:
        """
        Record a health check result.

        Args:
            component: Component name (e.g., "gemini_driver", "redis")
            status: "healthy", "degraded", or "unhealthy"
            category: Component category
            message: Optional status message
            latency_ms: Check latency in milliseconds
            details: Additional details

        Returns:
            The recorded HealthCheck
        """
        check = HealthCheck(
            component=component,
            status=status,
            category=category,
            message=message,
            latency_ms=latency_ms,
            details=details or {},
        )

        with self._lock:
            self._latest[component] = check

            if component not in self._history:
                self._history[component] = deque(maxlen=self._history_size)
            self._history[component].append(check)

        return check

    def update_telemetry(self, summary: TelemetrySummary) -> None:
        """
        Update the telemetry snapshot.

        Args:
            summary: Current telemetry summary
        """
        with self._lock:
            self._telemetry = summary

    def update_telemetry_from_collector(self, collector: Any) -> None:
        """
        Update telemetry from a TelemetryCollector instance.

        Args:
            collector: TelemetryCollector with session metrics
        """
        session = collector.get_session_summary()
        total_ops = session.total_api_calls + session.tool_executions
        error_rate = session.total_errors / total_ops if total_ops > 0 else 0.0

        budget_stats = collector.get_budget_stats()
        budget_pct = budget_stats.get("percentage_used", 0.0) if budget_stats else 0.0
        budget_warning = collector.get_budget_warning_level()

        summary = TelemetrySummary(
            api_calls=session.total_api_calls,
            total_tokens=session.total_tokens,
            total_errors=session.total_errors,
            swarm_tasks=session.swarm_tasks,
            tool_executions=session.tool_executions,
            session_duration_seconds=session.duration_seconds,
            cost_usd=getattr(collector, "_total_cost_usd", 0.0),
            budget_utilization_pct=budget_pct,
            budget_warning_level=budget_warning,
            error_rate=error_rate,
        )
        self.update_telemetry(summary)

    def get_component_status(self, component: str) -> HealthCheck | None:
        """
        Get the latest health check for a component.

        Args:
            component: Component name

        Returns:
            Latest HealthCheck or None
        """
        with self._lock:
            return self._latest.get(component)

    def get_component_history(self, component: str) -> list[HealthCheck]:
        """
        Get health check history for a component.

        Args:
            component: Component name

        Returns:
            List of historical health checks (oldest first)
        """
        with self._lock:
            history = self._history.get(component)
            return list(history) if history else []

    def compute_health_score(self) -> float:
        """
        Compute weighted composite health score.

        Returns:
            Score between 0.0 (unhealthy) and 1.0 (healthy)
        """
        with self._lock:
            if not self._latest:
                return 1.0  # No checks = assume healthy

            total_weight = 0.0
            weighted_score = 0.0

            for component, check in self._latest.items():
                weight = self._weights.get(component, 0.5)
                score = STATUS_SCORES.get(check.status, 0.0)
                weighted_score += weight * score
                total_weight += weight

            if total_weight == 0.0:
                return 1.0

            return weighted_score / total_weight

    def get_overall_status(self) -> str:
        """
        Determine overall system status.

        Returns:
            "healthy", "degraded", or "unhealthy"
        """
        score = self.compute_health_score()
        if score >= 0.8:
            return AggregateStatus.HEALTHY.value
        elif score >= 0.5:
            return AggregateStatus.DEGRADED.value
        else:
            return AggregateStatus.UNHEALTHY.value

    def get_report(self) -> HealthReport:
        """
        Generate a complete health report.

        Returns:
            HealthReport with all component statuses and telemetry
        """
        with self._lock:
            components = [check.to_dict() for check in self._latest.values()]
            telemetry = self._telemetry.to_dict() if self._telemetry else {}

            healthy = sum(1 for c in self._latest.values() if c.status == "healthy")
            degraded = sum(1 for c in self._latest.values() if c.status == "degraded")
            unhealthy = sum(1 for c in self._latest.values() if c.status == "unhealthy")

        score = self.compute_health_score()
        status = self.get_overall_status()
        summary = self._generate_summary(status, score, healthy, degraded, unhealthy, len(components))

        return HealthReport(
            overall_status=status,
            health_score=score,
            components=components,
            telemetry=telemetry,
            summary=summary,
            component_count=len(components),
            healthy_count=healthy,
            degraded_count=degraded,
            unhealthy_count=unhealthy,
        )

    def get_stale_components(self) -> list[str]:
        """
        Get components whose last check is older than the stale threshold.

        Returns:
            List of stale component names
        """
        now = time.time()
        stale = []

        with self._lock:
            for component, check in self._latest.items():
                try:
                    check_time = datetime.fromisoformat(check.timestamp.replace("Z", "+00:00")).timestamp()
                    if now - check_time > self._stale_threshold:
                        stale.append(component)
                except (ValueError, AttributeError):
                    stale.append(component)

        return stale

    def clear(self) -> None:
        """Clear all recorded health data."""
        with self._lock:
            self._latest.clear()
            self._history.clear()
            self._telemetry = None

    def remove_component(self, component: str) -> bool:
        """
        Remove a component from tracking.

        Args:
            component: Component name

        Returns:
            True if component was removed
        """
        with self._lock:
            removed = component in self._latest
            self._latest.pop(component, None)
            self._history.pop(component, None)
            return removed

    @property
    def tracked_components(self) -> list[str]:
        """List all tracked component names."""
        with self._lock:
            return list(self._latest.keys())

    def to_dict(self) -> dict[str, Any]:
        """Export aggregator state for diagnostics."""
        report = self.get_report()
        return {
            "overall_status": report.overall_status,
            "health_score": report.health_score,
            "tracked_components": len(self._latest),
            "history_size": self._history_size,
            "stale_threshold_seconds": self._stale_threshold,
            "stale_components": self.get_stale_components(),
        }

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _generate_summary(
        self,
        status: str,
        score: float,
        healthy: int,
        degraded: int,
        unhealthy: int,
        total: int,
    ) -> str:
        """Generate a human-readable health summary."""
        lines = [
            f"NEXUS Health: {status.upper()} (score: {score:.0%})",
            f"Components: {healthy}/{total} healthy",
        ]

        if degraded > 0:
            lines.append(f"  Degraded: {degraded}")
        if unhealthy > 0:
            lines.append(f"  Unhealthy: {unhealthy}")

        with self._lock:
            if self._telemetry:
                t = self._telemetry
                lines.append(f"API Calls: {t.api_calls} | Errors: {t.total_errors}")
                if t.cost_usd > 0:
                    lines.append(f"Cost: ${t.cost_usd:.4f} ({t.budget_utilization_pct:.1f}% budget)")
                if t.budget_warning_level:
                    lines.append(f"Budget Warning: {t.budget_warning_level}")

        return "\n".join(lines)
