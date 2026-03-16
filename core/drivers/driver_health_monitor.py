"""
Driver Health Monitor - Track driver performance and availability.

V12.4 COGNITIVE BOOST - Task #58

Monitors driver latency, error rates, throughput, and availability.
Enables automatic degradation detection and health-based routing.

Usage:
    from core.drivers.driver_health_monitor import get_health_monitor

    monitor = get_health_monitor()

    # Record events
    monitor.record_success("claude/opus", latency_ms=450, tokens=1500)
    monitor.record_failure("gemini/pro", error="timeout")

    # Check health
    health = monitor.get_health("claude/opus")
    print(health.status)  # "healthy" | "degraded" | "unhealthy"

    # Get all healthy drivers
    healthy = monitor.get_healthy_drivers()
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_HISTORY = 200  # Max events per driver
DEGRADED_ERROR_RATE = 0.2  # 20% errors = degraded
UNHEALTHY_ERROR_RATE = 0.5  # 50% errors = unhealthy
DEGRADED_LATENCY_MS = 5000.0  # 5s = degraded
UNHEALTHY_LATENCY_MS = 15000.0  # 15s = unhealthy
STALE_THRESHOLD_SECONDS = 300.0  # No events for 5min = stale


# =============================================================================
# Types
# =============================================================================


class HealthStatus(Enum):
    """Driver health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthEvent:
    """A single health event."""

    driver_id: str
    success: bool
    latency_ms: float = 0.0
    tokens: int = 0
    error: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()


@dataclass
class DriverHealth:
    """Health summary for a driver."""

    driver_id: str
    status: HealthStatus = HealthStatus.UNKNOWN
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_tokens: int = 0
    last_event_age_seconds: float = 0.0
    recent_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "status": self.status.value,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "error_rate": round(self.error_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "total_tokens": self.total_tokens,
            "recent_errors": self.recent_errors[:5],
        }


@dataclass
class HealthAlert:
    """An alert triggered by health degradation."""

    driver_id: str
    alert_type: str  # "degraded", "unhealthy", "recovered", "stale"
    message: str
    previous_status: HealthStatus
    current_status: HealthStatus
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "alert_type": self.alert_type,
            "message": self.message,
            "previous_status": self.previous_status.value,
            "current_status": self.current_status.value,
        }


@dataclass
class MonitorStats:
    """Overall monitoring statistics."""

    drivers_tracked: int
    healthy_count: int
    degraded_count: int
    unhealthy_count: int
    total_events: int
    total_alerts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "drivers_tracked": self.drivers_tracked,
            "healthy_count": self.healthy_count,
            "degraded_count": self.degraded_count,
            "unhealthy_count": self.unhealthy_count,
            "total_events": self.total_events,
            "total_alerts": self.total_alerts,
        }


# =============================================================================
# Driver Health Monitor
# =============================================================================


class DriverHealthMonitor:
    """
    Monitors driver health based on latency and error rates.

    Features:
    - Per-driver event tracking
    - Automatic health classification (healthy/degraded/unhealthy)
    - Health alerts on status changes
    - P95 latency tracking
    - Stale driver detection
    """

    def __init__(
        self,
        *,
        max_history: int = MAX_HISTORY,
        degraded_error_rate: float = DEGRADED_ERROR_RATE,
        unhealthy_error_rate: float = UNHEALTHY_ERROR_RATE,
        degraded_latency_ms: float = DEGRADED_LATENCY_MS,
        unhealthy_latency_ms: float = UNHEALTHY_LATENCY_MS,
    ):
        self._events: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self._max_history = max_history
        self._degraded_error_rate = degraded_error_rate
        self._unhealthy_error_rate = unhealthy_error_rate
        self._degraded_latency_ms = degraded_latency_ms
        self._unhealthy_latency_ms = unhealthy_latency_ms
        self._last_status: dict[str, HealthStatus] = {}
        self._alerts: list[HealthAlert] = []
        self._lock = threading.Lock()

    # =========================================================================
    # Record Events
    # =========================================================================

    def record_success(
        self,
        driver_id: str,
        *,
        latency_ms: float = 0.0,
        tokens: int = 0,
    ) -> None:
        """Record a successful driver call."""
        event = HealthEvent(
            driver_id=driver_id,
            success=True,
            latency_ms=latency_ms,
            tokens=tokens,
        )
        with self._lock:
            self._events[driver_id].append(event)
            self._check_status_change(driver_id)

    def record_failure(
        self,
        driver_id: str,
        *,
        error: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """Record a failed driver call."""
        event = HealthEvent(
            driver_id=driver_id,
            success=False,
            latency_ms=latency_ms,
            error=error,
        )
        with self._lock:
            self._events[driver_id].append(event)
            self._check_status_change(driver_id)

    # =========================================================================
    # Health Queries
    # =========================================================================

    def get_health(self, driver_id: str) -> DriverHealth:
        """Get health summary for a driver."""
        with self._lock:
            events = list(self._events.get(driver_id, []))

        if not events:
            return DriverHealth(driver_id=driver_id, status=HealthStatus.UNKNOWN)

        successes = sum(1 for e in events if e.success)
        failures = len(events) - successes
        error_rate = failures / len(events) if events else 0.0

        latencies = [e.latency_ms for e in events if e.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        p95_latency = self._percentile(latencies, 95) if latencies else 0.0

        total_tokens = sum(e.tokens for e in events)

        now = time.monotonic()
        last_age = now - events[-1].timestamp if events else 0.0

        recent_errors = [e.error for e in reversed(events) if not e.success and e.error][:5]

        status = self._classify_health(error_rate, avg_latency, last_age)

        return DriverHealth(
            driver_id=driver_id,
            status=status,
            total_requests=len(events),
            successful_requests=successes,
            failed_requests=failures,
            error_rate=error_rate,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            total_tokens=total_tokens,
            last_event_age_seconds=last_age,
            recent_errors=recent_errors,
        )

    def get_healthy_drivers(self) -> list[str]:
        """Get list of healthy driver IDs."""
        result = []
        with self._lock:
            driver_ids = list(self._events.keys())
        for did in driver_ids:
            health = self.get_health(did)
            if health.status == HealthStatus.HEALTHY:
                result.append(did)
        return sorted(result)

    def get_all_health(self) -> dict[str, DriverHealth]:
        """Get health for all tracked drivers."""
        with self._lock:
            driver_ids = list(self._events.keys())
        return {did: self.get_health(did) for did in driver_ids}

    def is_healthy(self, driver_id: str) -> bool:
        """Check if a driver is healthy."""
        return self.get_health(driver_id).status == HealthStatus.HEALTHY

    # =========================================================================
    # Alerts
    # =========================================================================

    def get_alerts(self, *, limit: int = 50) -> list[HealthAlert]:
        """Get recent health alerts."""
        with self._lock:
            return list(self._alerts[-limit:])

    def _check_status_change(self, driver_id: str) -> None:
        """Check if driver status changed and emit alert (called under lock)."""
        events = list(self._events.get(driver_id, []))
        if not events:
            return

        successes = sum(1 for e in events if e.success)
        failures = len(events) - successes
        error_rate = failures / len(events)
        latencies = [e.latency_ms for e in events if e.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        last_age = time.monotonic() - events[-1].timestamp

        new_status = self._classify_health(error_rate, avg_latency, last_age)
        old_status = self._last_status.get(driver_id, HealthStatus.UNKNOWN)

        if new_status != old_status and old_status != HealthStatus.UNKNOWN:
            alert_type = "recovered" if new_status == HealthStatus.HEALTHY else new_status.value
            alert = HealthAlert(
                driver_id=driver_id,
                alert_type=alert_type,
                message=f"Driver {driver_id}: {old_status.value} -> {new_status.value}",
                previous_status=old_status,
                current_status=new_status,
            )
            self._alerts.append(alert)

        self._last_status[driver_id] = new_status

    # =========================================================================
    # Classification
    # =========================================================================

    def _classify_health(
        self,
        error_rate: float,
        avg_latency: float,
        last_event_age: float,
    ) -> HealthStatus:
        """Classify driver health based on metrics."""
        if last_event_age > STALE_THRESHOLD_SECONDS:
            return HealthStatus.UNKNOWN

        if error_rate >= self._unhealthy_error_rate:
            return HealthStatus.UNHEALTHY
        if avg_latency >= self._unhealthy_latency_ms:
            return HealthStatus.UNHEALTHY

        if error_rate >= self._degraded_error_rate:
            return HealthStatus.DEGRADED
        if avg_latency >= self._degraded_latency_ms:
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    @staticmethod
    def _percentile(values: list[float], pct: int) -> float:
        """Calculate percentile."""
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * pct / 100)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> MonitorStats:
        """Get overall monitoring statistics."""
        with self._lock:
            driver_ids = list(self._events.keys())
            total_events = sum(len(v) for v in self._events.values())
            total_alerts = len(self._alerts)

        healthy = degraded = unhealthy = 0
        for did in driver_ids:
            h = self.get_health(did)
            if h.status == HealthStatus.HEALTHY:
                healthy += 1
            elif h.status == HealthStatus.DEGRADED:
                degraded += 1
            elif h.status == HealthStatus.UNHEALTHY:
                unhealthy += 1

        return MonitorStats(
            drivers_tracked=len(driver_ids),
            healthy_count=healthy,
            degraded_count=degraded,
            unhealthy_count=unhealthy,
            total_events=total_events,
            total_alerts=total_alerts,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def driver_count(self) -> int:
        return len(self._events)

    @property
    def alert_count(self) -> int:
        return len(self._alerts)

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._events.clear()
            self._last_status.clear()
            self._alerts.clear()

    def clear_driver(self, driver_id: str) -> bool:
        """Clear data for a specific driver."""
        with self._lock:
            if driver_id not in self._events:
                return False
            del self._events[driver_id]
            self._last_status.pop(driver_id, None)
            return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_count": self.driver_count,
            "alert_count": self.alert_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_monitor: DriverHealthMonitor | None = None
_monitor_lock = threading.Lock()


def get_health_monitor() -> DriverHealthMonitor:
    """Get or create the global driver health monitor."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = DriverHealthMonitor()
    return _monitor


def reset_health_monitor() -> None:
    """Reset the global health monitor (for testing)."""
    global _monitor
    _monitor = None
