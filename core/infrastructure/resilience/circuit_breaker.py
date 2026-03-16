"""
V9.3 ISSUE-007: Circuit Breaker Pattern for NEXUS

Prevents cascading failures when agent invocations repeatedly fail.
Implements exponential backoff with three states: CLOSED, OPEN, HALF_OPEN.

Research Sources:
- aiobreaker: https://github.com/arlyon/aiobreaker
- Python backoff: https://github.com/litl/backoff
- Microsoft AI Agent Patterns: Failure isolation best practices

Usage:
    breaker = get_circuit_breaker("gemini")

    try:
        result = await breaker.call(agent.invoke, prompt)
    except CircuitOpenError as e:
        # Circuit is open - don't retry, use fallback
        logger.warning(f"Circuit open: {e.time_until_retry}s until retry")
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any

logger = logging.getLogger("nexus.circuit_breaker")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation - requests pass through
    OPEN = "open"  # Failures exceeded threshold - requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and call is rejected."""

    def __init__(self, name: str, time_until_retry: float, failure_count: int):
        self.name = name
        self.time_until_retry = time_until_retry
        self.failure_count = failure_count
        super().__init__(
            f"Circuit '{name}' is OPEN. {failure_count} consecutive failures. Retry in {time_until_retry:.1f}s"
        )


@dataclass
class CircuitBreaker:
    """
    Circuit breaker with exponential backoff for agent invocations.

    V9.3: Prevents cascading failures between FSM -> HiveMind -> Swarm layers.

    States:
        CLOSED: Normal operation. Failures increment counter.
        OPEN: Too many failures. Requests rejected with CircuitOpenError.
        HALF_OPEN: After recovery_timeout, allow ONE request through.
                   Success -> CLOSED, Failure -> OPEN (with longer timeout)

    Attributes:
        name: Identifier for this circuit (e.g., "gemini", "claude", "swarm")
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before attempting recovery (HALF_OPEN)
        max_backoff: Maximum backoff time in seconds
        backoff_multiplier: Multiplier for exponential backoff (default 2.0)
    """

    name: str
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    max_backoff: float = 300.0
    backoff_multiplier: float = 2.0

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _last_failure_time: float | None = field(default=None, repr=False)
    _current_backoff: float = field(default=30.0, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self):
        self._current_backoff = self.recovery_timeout

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return True

        elapsed = time.time() - self._last_failure_time
        return elapsed >= self._current_backoff

    def _get_time_until_retry(self) -> float:
        """Get seconds until next retry attempt is allowed."""
        if self._last_failure_time is None:
            return 0.0

        elapsed = time.time() - self._last_failure_time
        remaining = self._current_backoff - elapsed
        return max(0.0, remaining)

    def _on_success(self):
        """Handle successful call - reset circuit to CLOSED."""
        with self._lock:
            logger.info(f"Circuit '{self.name}': Success - resetting to CLOSED")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._current_backoff = self.recovery_timeout
            self._last_failure_time = None

    def _on_failure(self, error: Exception):
        """Handle failed call - increment counter, potentially open circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery attempt - increase backoff
                self._current_backoff = min(self._current_backoff * self.backoff_multiplier, self.max_backoff)
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit '{self.name}': Recovery failed - OPEN (backoff: {self._current_backoff:.1f}s)")

            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit '{self.name}': Threshold reached ({self._failure_count}) - OPEN")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.

        Args:
            func: Async or sync function to call
            *args, **kwargs: Arguments to pass to function

        Returns:
            Function result if successful

        Raises:
            CircuitOpenError: If circuit is OPEN and retry time not elapsed
            Exception: Original exception from function (also trips circuit)
        """
        # Check if circuit allows the call
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    logger.info(f"Circuit '{self.name}': Attempting recovery (HALF_OPEN)")
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitOpenError(
                        name=self.name, time_until_retry=self._get_time_until_retry(), failure_count=self._failure_count
                    )

        # Execute the call
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            self._on_success()
            return result

        except Exception as e:
            self._on_failure(e)
            raise

    def call_sync(self, func: Callable, *args, **kwargs) -> Any:
        """
        Synchronous version of call() for non-async contexts.

        Args:
            func: Sync function to call
            *args, **kwargs: Arguments to pass to function

        Returns:
            Function result if successful

        Raises:
            CircuitOpenError: If circuit is OPEN
            Exception: Original exception from function
        """
        # Check if circuit allows the call
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    logger.info(f"Circuit '{self.name}': Attempting recovery (HALF_OPEN)")
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitOpenError(
                        name=self.name, time_until_retry=self._get_time_until_retry(), failure_count=self._failure_count
                    )

        # Execute the call
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure(e)
            raise

    def reset(self):
        """Manually reset circuit to CLOSED state."""
        with self._lock:
            logger.info(f"Circuit '{self.name}': Manual reset to CLOSED")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._current_backoff = self.recovery_timeout
            self._last_failure_time = None

    def get_status(self) -> dict[str, Any]:
        """Get circuit breaker status for monitoring."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "current_backoff": self._current_backoff,
            "time_until_retry": self._get_time_until_retry(),
            "last_failure": self._last_failure_time,
        }


# =============================================================================
# V11 FIX F17: HIERARCHICAL CIRCUIT BREAKER
# =============================================================================


class HierarchicalCircuitBreaker:
    """
    V11 FIX F17: Hierarchical circuit breaker with global parent.

    Problem: Independent circuit breakers don't detect global network failures.
    If all providers fail simultaneously (network down), each breaker opens
    independently, causing N separate recovery attempts.

    Solution: Two-level hierarchy:
    - Global breaker: Trips on widespread failures (e.g., network down)
    - Per-provider breakers: Trip on provider-specific issues

    When global breaker is OPEN, all calls are rejected immediately without
    checking per-provider breakers.

    Usage:
        hcb = HierarchicalCircuitBreaker()

        # This checks global first, then provider-specific
        result = await hcb.call("gemini", agent.invoke, prompt)

    Cascade Detection:
        When multiple providers fail within a short window (cascade_window),
        the global breaker trips to prevent further cascade damage.
    """

    def __init__(
        self,
        global_failure_threshold: int = 10,
        global_recovery_timeout: float = 60.0,
        cascade_window: float = 30.0,
        cascade_threshold: int = 3,
    ):
        """
        Initialize hierarchical circuit breaker.

        Args:
            global_failure_threshold: Failures to trip global breaker
            global_recovery_timeout: Global breaker recovery time
            cascade_window: Window (seconds) to detect cascade failures
            cascade_threshold: Provider failures in window to trip global
        """
        self._global = CircuitBreaker(
            name="global",
            failure_threshold=global_failure_threshold,
            recovery_timeout=global_recovery_timeout,
            max_backoff=600.0,  # 10 min max for global
        )

        self._per_provider: dict[str, CircuitBreaker] = {}
        self._lock = Lock()

        # Cascade detection
        self._cascade_window = cascade_window
        self._cascade_threshold = cascade_threshold
        self._recent_failures: list[tuple[str, float]] = []  # (provider, timestamp)

        logger.info(
            f"HierarchicalCircuitBreaker initialized: "
            f"global_threshold={global_failure_threshold}, "
            f"cascade_threshold={cascade_threshold}"
        )

    def _get_provider_breaker(self, provider: str) -> CircuitBreaker:
        """Get or create per-provider circuit breaker."""
        with self._lock:
            if provider not in self._per_provider:
                self._per_provider[provider] = CircuitBreaker(
                    name=provider, failure_threshold=3, recovery_timeout=30.0, max_backoff=300.0
                )
                logger.debug(f"Created provider breaker: {provider}")
            return self._per_provider[provider]

    def _check_cascade(self, provider: str) -> bool:
        """
        Check if we're in a cascade failure scenario.

        Returns True if cascade detected (should trip global breaker).
        """
        now = time.time()

        # Add this failure
        self._recent_failures.append((provider, now))

        # Clean old failures outside window
        self._recent_failures = [(p, t) for p, t in self._recent_failures if (now - t) <= self._cascade_window]

        # Count unique providers that failed in window
        failed_providers = set(p for p, t in self._recent_failures)

        if len(failed_providers) >= self._cascade_threshold:
            logger.warning(
                f"CASCADE DETECTED: {len(failed_providers)} providers failed "
                f"in {self._cascade_window}s window: {failed_providers}"
            )
            return True

        return False

    async def call(self, provider: str, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through hierarchical circuit breaker.

        Checks global breaker first, then provider-specific breaker.

        Args:
            provider: Provider name (gemini, claude, etc.)
            func: Async or sync function to call
            *args, **kwargs: Arguments to pass to function

        Returns:
            Function result if successful

        Raises:
            CircuitOpenError: If global or provider circuit is OPEN
            Exception: Original exception from function
        """
        # 1. Check global breaker first
        if self._global.state == CircuitState.OPEN:
            if not self._global._should_attempt_recovery():
                raise CircuitOpenError(
                    name="global",
                    time_until_retry=self._global._get_time_until_retry(),
                    failure_count=self._global.failure_count,
                )
            # Allow recovery attempt
            logger.info("Global circuit: Attempting recovery (HALF_OPEN)")
            self._global._state = CircuitState.HALF_OPEN

        # 2. Get provider-specific breaker
        provider_breaker = self._get_provider_breaker(provider)

        # 3. Execute through provider breaker
        try:
            result = await provider_breaker.call(func, *args, **kwargs)

            # Success - also signal global recovery
            if self._global.state == CircuitState.HALF_OPEN:
                self._global._on_success()

            return result

        except CircuitOpenError:
            # Provider breaker is open - re-raise
            raise

        except Exception as e:
            # Failure - check for cascade
            if self._check_cascade(provider):
                # Cascade detected - trip global breaker
                self._global._on_failure(e)

            raise

    def call_sync(self, provider: str, func: Callable, *args, **kwargs) -> Any:
        """
        Synchronous version of call().

        Args:
            provider: Provider name
            func: Sync function to call
            *args, **kwargs: Arguments

        Returns:
            Function result

        Raises:
            CircuitOpenError: If circuit is OPEN
            Exception: Original exception
        """
        # 1. Check global breaker
        if self._global.state == CircuitState.OPEN:
            if not self._global._should_attempt_recovery():
                raise CircuitOpenError(
                    name="global",
                    time_until_retry=self._global._get_time_until_retry(),
                    failure_count=self._global.failure_count,
                )
            self._global._state = CircuitState.HALF_OPEN

        # 2. Get provider breaker
        provider_breaker = self._get_provider_breaker(provider)

        # 3. Execute
        try:
            result = provider_breaker.call_sync(func, *args, **kwargs)

            if self._global.state == CircuitState.HALF_OPEN:
                self._global._on_success()

            return result

        except CircuitOpenError:
            raise

        except Exception as e:
            if self._check_cascade(provider):
                self._global._on_failure(e)
            raise

    def reset_all(self):
        """Reset global and all provider breakers."""
        with self._lock:
            self._global.reset()
            for breaker in self._per_provider.values():
                breaker.reset()
            self._recent_failures.clear()
            logger.info("HierarchicalCircuitBreaker: All breakers reset")

    def reset_provider(self, provider: str):
        """Reset specific provider breaker."""
        if provider in self._per_provider:
            self._per_provider[provider].reset()

    def get_status(self) -> dict[str, Any]:
        """Get hierarchical breaker status."""
        with self._lock:
            return {
                "global": self._global.get_status(),
                "providers": {name: breaker.get_status() for name, breaker in self._per_provider.items()},
                "cascade_detection": {
                    "window_seconds": self._cascade_window,
                    "threshold": self._cascade_threshold,
                    "recent_failures": len(self._recent_failures),
                },
            }

    @property
    def global_state(self) -> CircuitState:
        """Get global circuit state."""
        return self._global.state

    def get_provider_state(self, provider: str) -> CircuitState:
        """Get specific provider circuit state."""
        if provider in self._per_provider:
            return self._per_provider[provider].state
        return CircuitState.CLOSED  # Not created yet = healthy


# =============================================================================
# GLOBAL REGISTRIES
# =============================================================================

# Global circuit breaker registry (legacy - per-provider independent)
_circuit_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = Lock()

# V11: Hierarchical circuit breaker singleton
_hierarchical_breaker: HierarchicalCircuitBreaker | None = None


def get_circuit_breaker(
    name: str, failure_threshold: int = 3, recovery_timeout: float = 30.0, max_backoff: float = 300.0
) -> CircuitBreaker:
    """
    Get or create a circuit breaker by name.

    Args:
        name: Identifier for the circuit (e.g., "gemini", "claude", "hivemind")
        failure_threshold: Failures before opening (default 3)
        recovery_timeout: Initial recovery wait time in seconds (default 30)
        max_backoff: Maximum backoff time (default 300s = 5 minutes)

    Returns:
        CircuitBreaker instance (shared by name)
    """
    with _registry_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                max_backoff=max_backoff,
            )
            logger.debug(f"Created circuit breaker '{name}'")

        return _circuit_breakers[name]


def reset_all_circuits():
    """Reset all circuit breakers (for testing or emergency recovery)."""
    with _registry_lock:
        for breaker in _circuit_breakers.values():
            breaker.reset()
        logger.info(f"Reset all {len(_circuit_breakers)} circuit breakers")


def get_all_circuit_status() -> dict[str, dict[str, Any]]:
    """Get status of all circuit breakers."""
    with _registry_lock:
        return {name: breaker.get_status() for name, breaker in _circuit_breakers.items()}


# =============================================================================
# V11 FIX F17: HIERARCHICAL BREAKER ACCESS
# =============================================================================


def get_hierarchical_breaker() -> HierarchicalCircuitBreaker:
    """
    V11 FIX F17: Get the global hierarchical circuit breaker.

    Creates one if it doesn't exist. Use this for cascade-aware
    circuit breaking across multiple providers.

    Returns:
        HierarchicalCircuitBreaker singleton instance
    """
    global _hierarchical_breaker
    with _registry_lock:
        if _hierarchical_breaker is None:
            _hierarchical_breaker = HierarchicalCircuitBreaker()
        return _hierarchical_breaker


def reset_hierarchical_breaker():
    """Reset the hierarchical circuit breaker (for testing)."""
    global _hierarchical_breaker
    with _registry_lock:
        if _hierarchical_breaker is not None:
            _hierarchical_breaker.reset_all()
        _hierarchical_breaker = None


__all__ = [
    "CircuitState",
    "CircuitOpenError",
    "CircuitBreaker",
    "HierarchicalCircuitBreaker",
    "get_circuit_breaker",
    "get_hierarchical_breaker",
    "reset_all_circuits",
    "reset_hierarchical_breaker",
    "get_all_circuit_status",
]
