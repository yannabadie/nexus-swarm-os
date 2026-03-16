"""
Startup Analytics - Track bootstrap and startup performance for NEXUS.

V12.4 COGNITIVE BOOST

Tracks bootstrap and startup performance:
- Component initialization times
- Startup order tracking
- Failure detection and profiling
- Total boot time aggregation

Usage:
    from core.infrastructure.bootstrap.startup_analytics import get_startup_analytics

    analytics = get_startup_analytics()
    analytics.record_step("orchestrator", duration_ms=120.5, order=1)
    analytics.record_step("swarm_engine", duration_ms=85.3, order=2)
    profile = analytics.get_component_profile("orchestrator")
    stats = analytics.get_stats()
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_BOOT_RECORDS: int = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class BootStepRecord:
    """Record of a single bootstrap step."""

    step_id: str = ""
    component_name: str = ""
    duration_ms: float = 0.0
    success: bool = True
    error_message: str = ""
    order: int = 0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ComponentProfile:
    """Aggregated profile for a single component across boots."""

    component_name: str = ""
    total_boots: int = 0
    success_count: int = 0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_boots > 0:
            return self.success_count / self.total_boots
        return 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.total_boots > 0:
            return self.total_duration_ms / self.total_boots
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "total_boots": self.total_boots,
            "success_count": self.success_count,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


@dataclass
class StartupStats:
    """Overall startup analytics statistics."""

    total_boots: int = 0
    unique_components: int = 0
    overall_success_rate: float = 0.0
    avg_boot_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# =============================================================================
# Startup Analytics
# =============================================================================


class StartupAnalytics:
    """
    Track bootstrap and startup performance with bounded history.

    Features:
    - Record boot steps with component name, duration, and order
    - Per-component aggregated profiles (success rate, avg duration)
    - FIFO eviction when step history exceeds max_records
    - Identify slowest and failing components
    - Thread-safe via threading.Lock()
    """

    def __init__(self, max_records: int = MAX_BOOT_RECORDS) -> None:
        self._max_records = max_records
        self._steps: list[BootStepRecord] = []
        self._profiles: dict[str, ComponentProfile] = {}
        self._counter = 1
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_step(
        self,
        component_name: str,
        duration_ms: float = 0.0,
        success: bool = True,
        error_message: str = "",
        order: int = 0,
    ) -> BootStepRecord:
        """Record a bootstrap step and update the component profile."""
        with self._lock:
            step_id = f"bs_{self._counter:06d}"
            self._counter += 1

            record = BootStepRecord(
                step_id=step_id,
                component_name=component_name,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
                order=order,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # FIFO eviction
            if len(self._steps) >= self._max_records:
                self._steps.pop(0)
            self._steps.append(record)

            # Update component profile
            if component_name not in self._profiles:
                self._profiles[component_name] = ComponentProfile(
                    component_name=component_name,
                )
            profile = self._profiles[component_name]
            profile.total_boots += 1
            if success:
                profile.success_count += 1
            profile.total_duration_ms += duration_ms

        return record

    # =========================================================================
    # Profile Queries
    # =========================================================================

    def get_component_profile(self, component_name: str) -> ComponentProfile | None:
        """Get the aggregated profile for a specific component."""
        with self._lock:
            return self._profiles.get(component_name)

    def get_all_profiles(self) -> list[ComponentProfile]:
        """Return all component profiles sorted by total_boots descending."""
        with self._lock:
            return sorted(
                self._profiles.values(),
                key=lambda p: p.total_boots,
                reverse=True,
            )

    def get_slowest_components(self, limit: int = 5) -> list[ComponentProfile]:
        """Return top N components by avg_duration_ms descending."""
        with self._lock:
            return sorted(
                self._profiles.values(),
                key=lambda p: p.avg_duration_ms,
                reverse=True,
            )[:limit]

    def get_failing_components(self, min_boots: int = 3, threshold: float = 0.8) -> list[ComponentProfile]:
        """Return components with success_rate < threshold and at least min_boots.

        Sorted by success_rate ascending (worst first).
        """
        with self._lock:
            return sorted(
                [p for p in self._profiles.values() if p.total_boots >= min_boots and p.success_rate < threshold],
                key=lambda p: p.success_rate,
            )

    # =========================================================================
    # Step Queries
    # =========================================================================

    def get_recent_steps(self, limit: int = 10, component_name: str | None = None) -> list[BootStepRecord]:
        """Return last N steps, optionally filtered by component name.

        Results are returned in reverse chronological order (newest first).
        """
        with self._lock:
            if component_name is not None:
                filtered = [s for s in self._steps if s.component_name == component_name]
            else:
                filtered = list(self._steps)
            return list(reversed(filtered[-limit:]))

    def list_components(self) -> list[str]:
        """Return sorted list of all tracked component names."""
        with self._lock:
            return sorted(self._profiles.keys())

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> StartupStats:
        """Compute overall startup statistics."""
        with self._lock:
            total = len(self._steps)
            successes = sum(1 for s in self._steps if s.success)
            total_duration = sum(s.duration_ms for s in self._steps)
            unique = len(self._profiles)

            return StartupStats(
                total_boots=total,
                unique_components=unique,
                overall_success_rate=(successes / total if total > 0 else 0.0),
                avg_boot_duration_ms=(total_duration / total if total > 0 else 0.0),
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def step_count(self) -> int:
        """Number of boot step records currently stored."""
        with self._lock:
            return len(self._steps)

    def clear(self) -> None:
        """Reset all analytics state."""
        with self._lock:
            self._steps.clear()
            self._profiles.clear()
            self._counter = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize analytics state to dict.

        Note: get_stats(), get_all_profiles(), and get_recent_steps()
        are called BEFORE acquiring self._lock to avoid deadlock
        (threading.Lock is not reentrant).
        """
        stats = self.get_stats()
        profiles = self.get_all_profiles()
        recent = self.get_recent_steps(limit=20)
        with self._lock:
            return {
                "max_records": self._max_records,
                "step_count": len(self._steps),
                "stats": stats.to_dict(),
                "profiles": [p.to_dict() for p in profiles],
                "recent_steps": [s.to_dict() for s in recent],
            }


# =============================================================================
# Global Instance
# =============================================================================

_instance: StartupAnalytics | None = None
_lock = threading.Lock()


def get_startup_analytics() -> StartupAnalytics:
    """Get or create the global startup analytics singleton."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = StartupAnalytics()
    return _instance


def reset_startup_analytics() -> None:
    """Reset the global startup analytics singleton (for testing)."""
    global _instance
    with _lock:
        _instance = None
