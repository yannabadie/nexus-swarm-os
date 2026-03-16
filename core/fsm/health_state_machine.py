"""
HealthStateMachine - FSM for System Health with Automatic Recovery.

NEXUS V8.4.4 - Blind Spot Remediation Phase 4

This module provides a state machine for tracking system health and
automatically attempting recovery strategies before escalating to PANIC.

States:
    HEALTHY -> DEGRADED -> CRITICAL -> RECOVERING -> HEALTHY
                                       ↓
                                     PANIC

Recovery Strategies (tried in sequence):
1. reset_stagnation - Clear stagnation detector
2. switch_agent - Switch to alternate agent
3. compress_context - Reduce context window
4. clear_tool_cache - Clear tool execution cache
5. rollback_phase - Rollback to last checkpoint (if SagaManager available)

Integration:
- Works alongside existing PanicSystem (doesn't replace it)
- PanicSystem handles final panic state
- HealthStateMachine handles recovery attempts

Author: Claude (NEXUS V8.4.4)
Date: 2025-12-10
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# HEALTH STATES
# =============================================================================


class HealthState(Enum):
    """System health states."""

    HEALTHY = "healthy"  # Normal operation
    DEGRADED = "degraded"  # 1-2 errors, monitoring closely
    CRITICAL = "critical"  # 3+ errors, attempting recovery
    RECOVERING = "recovering"  # Recovery in progress
    PANIC = "panic"  # All recovery failed, escalate to user


# =============================================================================
# RECOVERY STRATEGIES
# =============================================================================


@dataclass
class RecoveryStrategy:
    """
    A single recovery strategy with metadata.

    Attributes:
        name: Unique identifier for the strategy
        description: Human-readable description
        action: Async callable to execute
        cooldown_seconds: Minimum time between uses
        max_attempts: Maximum times to try this strategy
        last_attempt: Timestamp of last attempt
        attempt_count: Number of times tried
    """

    name: str
    description: str
    action: Callable
    cooldown_seconds: float = 30.0
    max_attempts: int = 3
    last_attempt: datetime | None = None
    attempt_count: int = 0

    def is_available(self) -> bool:
        """Check if strategy can be used (cooldown + max attempts)."""
        if self.attempt_count >= self.max_attempts:
            return False

        if self.last_attempt is None:
            return True

        elapsed = (datetime.now() - self.last_attempt).total_seconds()
        return elapsed >= self.cooldown_seconds

    def mark_used(self) -> None:
        """Mark strategy as used."""
        self.last_attempt = datetime.now()
        self.attempt_count += 1

    def reset(self) -> None:
        """Reset strategy counters (on healthy state)."""
        self.attempt_count = 0
        self.last_attempt = None


# =============================================================================
# HEALTH STATE MACHINE
# =============================================================================


class HealthStateMachine:
    """
    FSM for tracking system health with automatic recovery.

    This FSM monitors error rates and attempts recovery strategies
    before escalating to PANIC state.

    Usage:
        health = HealthStateMachine(orchestrator)

        # Register custom recovery strategies
        health.add_strategy(RecoveryStrategy(
            name="custom_fix",
            description="Custom recovery",
            action=my_custom_recovery
        ))

        # On error
        await health.record_error("TOOL_FAILURE", "grep failed")

        # Check state
        if health.state == HealthState.PANIC:
            # Escalate to user
            ...
    """

    # State transition matrix
    TRANSITIONS = {
        HealthState.HEALTHY: {
            "error": HealthState.DEGRADED,
        },
        HealthState.DEGRADED: {
            "error": HealthState.CRITICAL,
            "success": HealthState.HEALTHY,
        },
        HealthState.CRITICAL: {
            "recovery_start": HealthState.RECOVERING,
            "panic": HealthState.PANIC,
        },
        HealthState.RECOVERING: {
            "recovery_success": HealthState.HEALTHY,
            "recovery_failed": HealthState.CRITICAL,
            "panic": HealthState.PANIC,
        },
        HealthState.PANIC: {
            "reset": HealthState.HEALTHY,  # Manual reset only
        },
    }

    # Error thresholds
    DEGRADED_THRESHOLD = 1  # Errors to enter DEGRADED
    CRITICAL_THRESHOLD = 3  # Errors to enter CRITICAL

    def __init__(self, orchestrator: Any | None = None, *, auto_recover: bool = True):
        """
        Initialize health state machine.

        Args:
            orchestrator: Optional OrchestratorV7 instance for recovery actions
            auto_recover: If True, automatically attempt recovery on CRITICAL
        """
        self._orchestrator = orchestrator
        self._auto_recover = auto_recover

        # State tracking
        self._state = HealthState.HEALTHY
        self._error_count = 0
        self._recovery_attempts = 0
        self._last_state_change = datetime.now()

        # Recovery strategies (registered in order)
        self._strategies: list[RecoveryStrategy] = []

        # Event callbacks
        self._on_state_change: list[Callable] = []

        # History for debugging
        self._history: list[dict[str, Any]] = []

        # Register default strategies if orchestrator provided
        if orchestrator:
            self._register_default_strategies()

    @property
    def state(self) -> HealthState:
        """Get current health state."""
        return self._state

    @property
    def error_count(self) -> int:
        """Get current error count."""
        return self._error_count

    @property
    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        return self._state == HealthState.HEALTHY

    @property
    def is_panic(self) -> bool:
        """Check if system is in panic."""
        return self._state == HealthState.PANIC

    # -------------------------------------------------------------------------
    # Strategy Registration
    # -------------------------------------------------------------------------

    def add_strategy(self, strategy: RecoveryStrategy) -> None:
        """
        Add a recovery strategy.

        Strategies are tried in order of registration.

        Args:
            strategy: RecoveryStrategy to add
        """
        self._strategies.append(strategy)
        logger.debug(f"Recovery strategy registered: {strategy.name}")

    def _register_default_strategies(self) -> None:
        """Register default recovery strategies based on orchestrator."""
        orch = self._orchestrator

        # 1. Reset stagnation detector
        async def reset_stagnation():
            if hasattr(orch, "stagnation_detector"):
                orch.stagnation_detector.reset()
                logger.info("Stagnation detector reset")
                return True
            return False

        self.add_strategy(
            RecoveryStrategy(
                name="reset_stagnation",
                description="Reset stagnation detector counters",
                action=reset_stagnation,
                cooldown_seconds=30.0,
                max_attempts=3,
            )
        )

        # 2. Switch active agent
        async def switch_agent():
            if hasattr(orch, "active_agent") and hasattr(orch, "_switch_agent"):
                current = orch.active_agent
                orch._switch_agent()
                logger.info(f"Agent switched from {current} to {orch.active_agent}")
                return True
            return False

        self.add_strategy(
            RecoveryStrategy(
                name="switch_agent",
                description="Switch to alternate agent",
                action=switch_agent,
                cooldown_seconds=60.0,
                max_attempts=2,
            )
        )

        # 3. Compress context
        async def compress_context():
            if hasattr(orch, "context_manager") and hasattr(orch.context_manager, "compress"):
                await orch.context_manager.compress()
                logger.info("Context compressed")
                return True
            return False

        self.add_strategy(
            RecoveryStrategy(
                name="compress_context",
                description="Compress conversation context",
                action=compress_context,
                cooldown_seconds=120.0,
                max_attempts=2,
            )
        )

        # 4. Clear tool cache
        async def clear_tool_cache():
            if hasattr(orch, "tool_manager") and hasattr(orch.tool_manager, "clear_cache"):
                orch.tool_manager.clear_cache()
                logger.info("Tool cache cleared")
                return True
            return False

        self.add_strategy(
            RecoveryStrategy(
                name="clear_tool_cache",
                description="Clear tool execution cache",
                action=clear_tool_cache,
                cooldown_seconds=60.0,
                max_attempts=2,
            )
        )

        # 5. Rollback to checkpoint (if SagaManager available)
        async def rollback_phase():
            if hasattr(orch, "saga_manager") and orch.saga_manager:
                saga = orch.saga_manager
                if saga.recovery_point:
                    # Rollback to recovery point
                    ctx_manager = getattr(orch, "context_manager", None)
                    success = await saga.rollback_to(saga.recovery_point, ctx_manager)
                    if success:
                        logger.info(f"Rolled back to phase: {saga.recovery_point}")
                        return True
            return False

        self.add_strategy(
            RecoveryStrategy(
                name="rollback_phase",
                description="Rollback to last checkpoint via SagaManager",
                action=rollback_phase,
                cooldown_seconds=180.0,
                max_attempts=1,  # Only try once per session
            )
        )

    # -------------------------------------------------------------------------
    # State Transitions
    # -------------------------------------------------------------------------

    def _transition_to(self, new_state: HealthState, reason: str = "") -> bool:
        """
        Transition to new state if valid.

        Args:
            new_state: Target state
            reason: Reason for transition

        Returns:
            True if transition occurred
        """
        if new_state == self._state:
            return False

        # Log transition
        self._history.append(
            {
                "from": self._state.value,
                "to": new_state.value,
                "reason": reason,
                "error_count": self._error_count,
                "timestamp": datetime.now().isoformat(),
            }
        )

        old_state = self._state
        self._state = new_state
        self._last_state_change = datetime.now()

        logger.info(f"Health state: {old_state.value} -> {new_state.value} ({reason})")

        # Call callbacks
        for callback in self._on_state_change:
            try:
                callback(old_state, new_state, reason)
            except Exception as e:
                logger.error(f"State change callback failed: {e}")

        return True

    def on_state_change(self, callback: Callable) -> None:
        """Register callback for state changes."""
        self._on_state_change.append(callback)

    # -------------------------------------------------------------------------
    # Error Recording
    # -------------------------------------------------------------------------

    async def record_error(self, error_type: str, error_message: str, *, severity: float = 1.0) -> HealthState:
        """
        Record an error and update health state.

        Args:
            error_type: Type of error (TOOL_FAILURE, PARSING_ERROR, etc.)
            error_message: Error message
            severity: Error severity multiplier (default 1.0)

        Returns:
            Current health state after recording
        """
        # Increment error count (weighted by severity)
        self._error_count += int(severity)

        logger.debug(f"Error recorded: {error_type} - {error_message} (count={self._error_count})")

        # State transitions based on error count
        if self._state == HealthState.HEALTHY:
            if self._error_count >= self.DEGRADED_THRESHOLD:
                self._transition_to(HealthState.DEGRADED, f"Error threshold: {error_type}")

        elif self._state == HealthState.DEGRADED and self._error_count >= self.CRITICAL_THRESHOLD:
            self._transition_to(HealthState.CRITICAL, f"Critical threshold: {error_type}")

        # Auto-recover if enabled and in CRITICAL
        if self._auto_recover and self._state == HealthState.CRITICAL:
            await self.attempt_recovery()

        return self._state

    def record_success(self) -> HealthState:
        """
        Record a successful operation, potentially improving health.

        Returns:
            Current health state after recording
        """
        # Decrease error count (don't go below 0)
        self._error_count = max(0, self._error_count - 1)

        logger.debug(f"Success recorded (error_count={self._error_count})")

        # State transitions on success
        if self._state == HealthState.DEGRADED:
            if self._error_count < self.DEGRADED_THRESHOLD:
                self._transition_to(HealthState.HEALTHY, "Success recovery")
                self._reset_strategies()

        elif self._state == HealthState.RECOVERING:
            # Recovery succeeded
            self._transition_to(HealthState.HEALTHY, "Recovery success")
            self._reset_strategies()

        return self._state

    # -------------------------------------------------------------------------
    # Recovery
    # -------------------------------------------------------------------------

    async def attempt_recovery(self) -> bool:
        """
        Attempt recovery using registered strategies.

        Tries strategies in order until one succeeds or all fail.

        Returns:
            True if recovery succeeded
        """
        if self._state not in (HealthState.CRITICAL, HealthState.RECOVERING):
            return False

        self._transition_to(HealthState.RECOVERING, "Starting recovery")

        for strategy in self._strategies:
            if not strategy.is_available():
                logger.debug(f"Strategy '{strategy.name}' not available (cooldown or max attempts)")
                continue

            logger.info(f"Trying recovery strategy: {strategy.name}")
            strategy.mark_used()
            self._recovery_attempts += 1

            try:
                if asyncio.iscoroutinefunction(strategy.action):
                    success = await strategy.action()
                else:
                    success = strategy.action()

                if success:
                    logger.info(f"Recovery strategy '{strategy.name}' succeeded")
                    self._transition_to(HealthState.HEALTHY, f"Strategy: {strategy.name}")
                    self._error_count = 0
                    return True

            except Exception as e:
                logger.error(f"Recovery strategy '{strategy.name}' failed: {e}")

        # All strategies failed
        logger.error("All recovery strategies exhausted")
        self._transition_to(HealthState.PANIC, "Recovery exhausted")
        return False

    def _reset_strategies(self) -> None:
        """Reset all strategy counters."""
        for strategy in self._strategies:
            strategy.reset()
        self._recovery_attempts = 0

    # -------------------------------------------------------------------------
    # Manual Controls
    # -------------------------------------------------------------------------

    def reset(self) -> None:
        """
        Manual reset to HEALTHY state.

        Used after user intervention or system restart.
        """
        self._error_count = 0
        self._recovery_attempts = 0
        self._reset_strategies()
        self._transition_to(HealthState.HEALTHY, "Manual reset")

    def force_panic(self, reason: str) -> None:
        """
        Force transition to PANIC state.

        Args:
            reason: Reason for forced panic
        """
        self._transition_to(HealthState.PANIC, f"Forced: {reason}")

    # -------------------------------------------------------------------------
    # Status & Debugging
    # -------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Get health status for debugging/monitoring."""
        return {
            "state": self._state.value,
            "error_count": self._error_count,
            "recovery_attempts": self._recovery_attempts,
            "last_state_change": self._last_state_change.isoformat(),
            "strategies": [
                {
                    "name": s.name,
                    "available": s.is_available(),
                    "attempt_count": s.attempt_count,
                }
                for s in self._strategies
            ],
            "history_length": len(self._history),
        }

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent state transition history."""
        return self._history[-limit:]

    def __repr__(self) -> str:
        return f"HealthStateMachine(state={self._state.value}, errors={self._error_count})"


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "HealthState",
    "HealthStateMachine",
    "RecoveryStrategy",
]
