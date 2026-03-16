"""
Failover Manager - Intelligent driver failover with circuit breaker.

V12.4 COGNITIVE BOOST

Provides health-based failover routing for LLM drivers with circuit breaker
pattern, degradation strategies, and priority-based driver selection.

When a driver fails repeatedly, the circuit breaker opens to prevent
cascading failures. After a recovery timeout, the circuit enters a
half-open state where a single test call is allowed through.

Driver Status Flow:
    healthy -> degraded -> failing -> circuit_open -> recovering -> healthy
                                                   -> failing (if retry fails)

Usage:
    from core.drivers.failover_manager import get_failover_manager

    mgr = get_failover_manager()

    # Register drivers with priority (lower = higher priority)
    mgr.register_driver("claude/opus", priority=0)
    mgr.register_driver("gemini/pro", priority=1)
    mgr.register_driver("claude/sonnet", priority=2)

    # Select best available driver
    decision = mgr.select_driver()
    print(decision.selected_driver)  # "claude/opus"

    # Record outcomes
    mgr.record_success("claude/opus")
    mgr.record_failure("claude/opus")

    # After repeated failures, circuit opens and failover kicks in
    decision = mgr.select_driver()
    print(decision.selected_driver)  # "gemini/pro" (failover)
    print(decision.fallback_used)    # True
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_FAILURE_THRESHOLD = 3  # Consecutive failures before circuit opens
DEFAULT_RECOVERY_TIMEOUT = 60.0  # Seconds before half-open retry
MAX_DRIVERS = 100
MAX_DECISIONS = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class FailoverState:
    """Runtime state for a single driver in the failover pool."""

    driver_id: str
    status: str = "healthy"  # healthy, degraded, failing, circuit_open, recovering
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    circuit_opened_at: float = 0.0

    @property
    def total_calls(self) -> int:
        """Total number of recorded calls (successes + failures)."""
        return self.total_successes + self.total_failures

    @property
    def success_rate(self) -> float:
        """Success rate as a fraction (0.0 to 1.0)."""
        if self.total_calls == 0:
            return 0.0
        return self.total_successes / self.total_calls

    @property
    def is_available(self) -> bool:
        """Whether the driver can accept requests."""
        return self.status not in ("circuit_open", "failing")

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "total_calls": self.total_calls,
            "success_rate": round(self.success_rate, 4),
            "is_available": self.is_available,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "circuit_opened_at": self.circuit_opened_at,
        }


@dataclass
class FailoverConfig:
    """Configuration for a registered driver."""

    driver_id: str
    priority: int = 0  # Lower = higher priority (0 = primary)
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "priority": self.priority,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


@dataclass
class FailoverDecision:
    """Record of a driver selection decision."""

    selected_driver: str
    reason: str  # e.g. "primary_healthy", "failover_from_X", "circuit_half_open"
    primary_driver: str = ""
    fallback_used: bool = False
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_driver": self.selected_driver,
            "reason": self.reason,
            "primary_driver": self.primary_driver,
            "fallback_used": self.fallback_used,
            "timestamp": self.timestamp,
        }


@dataclass
class FailoverStats:
    """Aggregate statistics for the failover manager."""

    total_drivers: int
    healthy_drivers: int
    degraded_drivers: int
    failing_drivers: int
    circuit_open_drivers: int
    total_failovers: int
    total_decisions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_drivers": self.total_drivers,
            "healthy_drivers": self.healthy_drivers,
            "degraded_drivers": self.degraded_drivers,
            "failing_drivers": self.failing_drivers,
            "circuit_open_drivers": self.circuit_open_drivers,
            "total_failovers": self.total_failovers,
            "total_decisions": self.total_decisions,
        }


# =============================================================================
# Failover Manager
# =============================================================================


class FailoverManager:
    """
    Intelligent failover routing with circuit breaker pattern.

    Manages a pool of LLM drivers with priority-based routing, automatic
    circuit breaking on repeated failures, and half-open recovery probes.

    Features:
    - Priority-based driver selection (lower priority value = preferred)
    - Circuit breaker with configurable threshold and recovery timeout
    - Degradation detection (partial failure before full circuit open)
    - Decision history for auditing and diagnostics
    - Thread-safe for concurrent access
    """

    def __init__(self, *, max_decisions: int = MAX_DECISIONS):
        self._configs: dict[str, FailoverConfig] = {}
        self._states: dict[str, FailoverState] = {}
        self._decisions: list[FailoverDecision] = []
        self._max_decisions = max_decisions
        self._lock = threading.Lock()

    # =========================================================================
    # Driver Registration
    # =========================================================================

    def register_driver(
        self,
        driver_id: str,
        *,
        priority: int = 0,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
    ) -> bool:
        """
        Register a driver with the failover pool.

        Args:
            driver_id: Unique driver identifier
            priority: Selection priority (lower = higher priority, 0 = primary)
            failure_threshold: Consecutive failures before circuit opens
            recovery_timeout: Seconds before half-open retry after circuit opens

        Returns:
            True if registered, False if already registered or pool is full
        """
        with self._lock:
            if driver_id in self._configs:
                _logger.warning("Driver already registered: %s", driver_id)
                return False
            if len(self._configs) >= MAX_DRIVERS:
                _logger.warning("Driver pool full (%d), cannot register: %s", MAX_DRIVERS, driver_id)
                return False

            self._configs[driver_id] = FailoverConfig(
                driver_id=driver_id,
                priority=priority,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            self._states[driver_id] = FailoverState(driver_id=driver_id)
            _logger.info("Registered driver: %s (priority=%d)", driver_id, priority)
            return True

    def unregister_driver(self, driver_id: str) -> bool:
        """
        Remove a driver from the failover pool.

        Args:
            driver_id: Driver to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if driver_id not in self._configs:
                return False
            del self._configs[driver_id]
            del self._states[driver_id]
            _logger.info("Unregistered driver: %s", driver_id)
            return True

    # =========================================================================
    # Record Outcomes
    # =========================================================================

    def record_success(self, driver_id: str) -> bool:
        """
        Record a successful call to a driver.

        Resets consecutive failure count. If the driver was in "recovering"
        state (half-open circuit), promotes it back to "healthy".

        Args:
            driver_id: Driver that succeeded

        Returns:
            True if recorded, False if driver not registered
        """
        with self._lock:
            state = self._states.get(driver_id)
            if state is None:
                return False

            state.consecutive_failures = 0
            state.total_successes += 1
            state.last_success_time = time.monotonic()

            if state.status == "recovering":
                _logger.info("Driver recovered: %s", driver_id)
                state.status = "healthy"
                state.circuit_opened_at = 0.0
            elif state.status == "degraded":
                state.status = "healthy"

            return True

    def record_failure(self, driver_id: str) -> bool:
        """
        Record a failed call to a driver.

        Increments consecutive failure count. When the threshold is reached,
        the circuit opens and the driver becomes unavailable until the
        recovery timeout elapses.

        Degradation logic:
        - If status is "healthy" and consecutive >= threshold/2: -> "degraded"
        - If status is "degraded" and consecutive >= threshold: -> "failing"
        - If consecutive >= threshold: -> "failing" then "circuit_open"

        Args:
            driver_id: Driver that failed

        Returns:
            True if recorded, False if driver not registered
        """
        with self._lock:
            state = self._states.get(driver_id)
            config = self._configs.get(driver_id)
            if state is None or config is None:
                return False

            state.consecutive_failures += 1
            state.total_failures += 1
            state.last_failure_time = time.monotonic()

            threshold = config.failure_threshold
            half_threshold = max(1, threshold // 2)

            if state.status == "recovering":
                # Failed during half-open probe: reopen circuit
                _logger.warning("Recovery probe failed for %s, reopening circuit", driver_id)
                state.status = "circuit_open"
                state.circuit_opened_at = time.monotonic()
            elif state.consecutive_failures >= threshold:
                # Full threshold reached: open circuit
                if state.status != "circuit_open":
                    _logger.warning(
                        "Circuit opened for %s after %d consecutive failures",
                        driver_id,
                        state.consecutive_failures,
                    )
                    state.status = "failing"
                    state.status = "circuit_open"
                    state.circuit_opened_at = time.monotonic()
            elif state.status == "degraded" and state.consecutive_failures >= half_threshold:
                # Degraded driver hitting half-threshold: escalate to failing
                _logger.warning("Degraded driver %s escalated to failing", driver_id)
                state.status = "failing"
                state.circuit_opened_at = time.monotonic()
            elif state.status == "healthy" and state.consecutive_failures >= half_threshold:
                # Healthy driver hitting half-threshold: degrade
                _logger.info("Driver degraded: %s (%d consecutive failures)", driver_id, state.consecutive_failures)
                state.status = "degraded"

            return True

    # =========================================================================
    # Driver Selection
    # =========================================================================

    def select_driver(self) -> FailoverDecision | None:
        """
        Select the best available driver based on priority and health.

        Checks circuit breakers first: if a circuit has been open longer than
        its recovery timeout, the driver transitions to "recovering" (half-open)
        and becomes eligible for a test call.

        Returns:
            FailoverDecision with the selected driver, or None if no drivers
            are available
        """
        with self._lock:
            if not self._configs:
                return None

            now = time.monotonic()

            # Check circuit breakers for recovery timeout
            for driver_id, state in self._states.items():
                if state.status == "circuit_open":
                    config = self._configs[driver_id]
                    elapsed = now - state.circuit_opened_at
                    if elapsed >= config.recovery_timeout:
                        _logger.info(
                            "Circuit half-open for %s after %.1fs",
                            driver_id,
                            elapsed,
                        )
                        state.status = "recovering"

            # Sort configs by priority (lower = higher priority)
            sorted_configs = sorted(
                self._configs.values(),
                key=lambda c: c.priority,
            )

            primary_id = sorted_configs[0].driver_id
            primary_state = self._states[primary_id]

            # Try primary first
            if primary_state.is_available or primary_state.status == "recovering":
                reason = "primary_healthy"
                if primary_state.status == "recovering":
                    reason = "circuit_half_open"
                elif primary_state.status == "degraded":
                    reason = "primary_degraded"

                decision = FailoverDecision(
                    selected_driver=primary_id,
                    reason=reason,
                    primary_driver=primary_id,
                    fallback_used=False,
                )
                self._record_decision(decision)
                return decision

            # Primary unavailable: find next available driver
            for config in sorted_configs[1:]:
                state = self._states[config.driver_id]
                if state.is_available or state.status == "recovering":
                    reason = f"failover_from_{primary_id}"
                    if state.status == "recovering":
                        reason = "circuit_half_open"

                    decision = FailoverDecision(
                        selected_driver=config.driver_id,
                        reason=reason,
                        primary_driver=primary_id,
                        fallback_used=True,
                    )
                    self._record_decision(decision)
                    return decision

            # No drivers available
            _logger.error("No available drivers in failover pool")
            return None

    def get_available_drivers(self) -> list[str]:
        """
        Get all available driver IDs sorted by priority.

        Includes drivers in "recovering" state (half-open circuit) since
        they are eligible for a test call.

        Returns:
            List of driver IDs sorted by priority (lower priority value first)
        """
        with self._lock:
            available = []
            for config in sorted(self._configs.values(), key=lambda c: c.priority):
                state = self._states[config.driver_id]
                if state.is_available or state.status == "recovering":
                    available.append(config.driver_id)
            return available

    # =========================================================================
    # Queries
    # =========================================================================

    def get_driver(self, driver_id: str) -> FailoverState | None:
        """
        Get the current state of a registered driver.

        Args:
            driver_id: Driver to query

        Returns:
            FailoverState copy, or None if not registered
        """
        with self._lock:
            state = self._states.get(driver_id)
            if state is None:
                return None
            # Return a copy to prevent external mutation
            return FailoverState(
                driver_id=state.driver_id,
                status=state.status,
                consecutive_failures=state.consecutive_failures,
                total_failures=state.total_failures,
                total_successes=state.total_successes,
                last_failure_time=state.last_failure_time,
                last_success_time=state.last_success_time,
                circuit_opened_at=state.circuit_opened_at,
            )

    def is_healthy(self, driver_id: str) -> bool:
        """
        Check if a driver is in healthy status.

        Args:
            driver_id: Driver to check

        Returns:
            True if driver exists and status is "healthy"
        """
        with self._lock:
            state = self._states.get(driver_id)
            if state is None:
                return False
            return state.status == "healthy"

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> FailoverStats:
        """Get aggregate failover statistics."""
        with self._lock:
            healthy = degraded = failing = circuit_open = 0
            for state in self._states.values():
                if state.status == "healthy":
                    healthy += 1
                elif state.status == "degraded":
                    degraded += 1
                elif state.status == "failing":
                    failing += 1
                elif state.status == "circuit_open":
                    circuit_open += 1

            total_failovers = sum(1 for d in self._decisions if d.fallback_used)

            return FailoverStats(
                total_drivers=len(self._configs),
                healthy_drivers=healthy,
                degraded_drivers=degraded,
                failing_drivers=failing,
                circuit_open_drivers=circuit_open,
                total_failovers=total_failovers,
                total_decisions=len(self._decisions),
            )

    @property
    def driver_count(self) -> int:
        """Number of registered drivers."""
        return len(self._configs)

    # =========================================================================
    # State Management
    # =========================================================================

    def clear(self) -> None:
        """Clear all drivers, states, and decision history."""
        with self._lock:
            self._configs.clear()
            self._states.clear()
            self._decisions.clear()

    def to_dict(self) -> dict[str, Any]:
        """Export full manager state for diagnostics."""
        stats = self.get_stats()
        with self._lock:
            return {
                "driver_count": len(self._configs),
                "max_decisions": self._max_decisions,
                "decision_count": len(self._decisions),
                "configs": {did: cfg.to_dict() for did, cfg in self._configs.items()},
                "states": {did: st.to_dict() for did, st in self._states.items()},
                "stats": stats.to_dict(),
            }

    # =========================================================================
    # Internal
    # =========================================================================

    def _record_decision(self, decision: FailoverDecision) -> None:
        """Record a decision, evicting oldest if at capacity (called under lock)."""
        if len(self._decisions) >= self._max_decisions:
            # Evict oldest 10% to avoid frequent evictions
            evict_count = max(1, self._max_decisions // 10)
            self._decisions = self._decisions[evict_count:]
        self._decisions.append(decision)


# =============================================================================
# Global Instance
# =============================================================================

_manager: FailoverManager | None = None
_manager_lock = threading.Lock()


def get_failover_manager() -> FailoverManager:
    """Get or create the global failover manager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = FailoverManager()
    return _manager


def reset_failover_manager() -> None:
    """Reset the global failover manager (for testing)."""
    global _manager
    _manager = None
