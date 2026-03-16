"""
Retry Handler - Exponential backoff retry logic for tool execution.

V12.4 COGNITIVE BOOST - Task #69

Provides configurable retry logic with exponential backoff, jitter,
and retry predicates for determining which errors are retryable.

Usage:
    from core.execution_pkg.execution.retry_handler import get_retry_handler

    handler = get_retry_handler()

    # Configure a retry policy
    handler.configure("api_calls", max_attempts=3, base_delay=0.5)

    # Execute with retries
    result = handler.execute("api_calls", callable_fn)
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

_logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_BACKOFF_FACTOR = 2.0
MAX_POLICIES = 200


# =============================================================================
# Types
# =============================================================================


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""

    name: str
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    jitter: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_attempts": self.max_attempts,
            "base_delay": self.base_delay,
            "max_delay": self.max_delay,
            "backoff_factor": self.backoff_factor,
            "jitter": self.jitter,
        }


@dataclass
class RetryAttempt:
    """Record of a single retry attempt."""

    attempt_number: int
    error: str
    delay_seconds: float
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt_number,
            "error": self.error,
            "delay_seconds": round(self.delay_seconds, 3),
        }


@dataclass
class RetryResult:
    """Result of a retry-wrapped execution."""

    success: bool
    result: Any = None
    attempts: int = 0
    total_delay: float = 0.0
    last_error: str = ""
    history: list[RetryAttempt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "total_delay": round(self.total_delay, 3),
            "last_error": self.last_error,
        }


@dataclass
class RetryStats:
    """Retry handler statistics."""

    configured_policies: int
    total_executions: int
    total_retries: int
    total_successes: int
    total_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured_policies": self.configured_policies,
            "total_executions": self.total_executions,
            "total_retries": self.total_retries,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
        }


# =============================================================================
# Retry Handler
# =============================================================================


class RetryHandler:
    """
    Exponential backoff retry handler.

    Features:
    - Named retry policies
    - Exponential backoff with configurable factor
    - Optional jitter to prevent thundering herd
    - Custom retry predicates
    - Attempt history tracking
    - Statistics
    - Thread-safe
    """

    def __init__(self):
        self._policies: dict[str, RetryPolicy] = {}
        self._total_executions = 0
        self._total_retries = 0
        self._total_successes = 0
        self._total_failures = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Policy Management
    # =========================================================================

    def configure(
        self,
        name: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        jitter: bool = True,
    ) -> RetryPolicy:
        """Configure a named retry policy."""
        policy = RetryPolicy(
            name=name,
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            backoff_factor=backoff_factor,
            jitter=jitter,
        )
        with self._lock:
            if len(self._policies) >= MAX_POLICIES and name not in self._policies:
                raise ValueError(f"Maximum policies ({MAX_POLICIES}) reached")
            self._policies[name] = policy
        return policy

    def unconfigure(self, name: str) -> bool:
        """Remove a retry policy."""
        with self._lock:
            return self._policies.pop(name, None) is not None

    def get_policy(self, name: str) -> RetryPolicy | None:
        """Get a retry policy by name."""
        return self._policies.get(name)

    def list_policies(self) -> list[RetryPolicy]:
        """List all configured policies."""
        return list(self._policies.values())

    # =========================================================================
    # Delay Calculation
    # =========================================================================

    def calculate_delay(self, policy: RetryPolicy, attempt: int) -> float:
        """Calculate delay for a given attempt number."""
        delay = policy.base_delay * (policy.backoff_factor**attempt)
        delay = min(delay, policy.max_delay)
        if policy.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return delay

    # =========================================================================
    # Execution
    # =========================================================================

    def execute(
        self,
        policy_name: str,
        fn: Callable[[], T],
        *,
        retryable: Callable[[Exception], bool] | None = None,
        on_retry: Callable[[int, Exception, float], None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> RetryResult:
        """
        Execute a function with retry logic.

        Args:
            policy_name: Name of the retry policy to use
            fn: Function to execute
            retryable: Predicate to check if error is retryable (default: all)
            on_retry: Callback on each retry (attempt, error, delay)
            sleep_fn: Custom sleep function (for testing)

        Returns:
            RetryResult with execution details
        """
        policy = self._policies.get(policy_name)
        if policy is None:
            # No policy = execute once
            with self._lock:
                self._total_executions += 1
            try:
                result = fn()
                with self._lock:
                    self._total_successes += 1
                return RetryResult(success=True, result=result, attempts=1)
            except Exception as e:
                with self._lock:
                    self._total_failures += 1
                return RetryResult(
                    success=False,
                    attempts=1,
                    last_error=str(e),
                )

        _sleep = sleep_fn or time.sleep

        with self._lock:
            self._total_executions += 1

        history: list[RetryAttempt] = []
        total_delay = 0.0
        last_error = ""

        for attempt in range(policy.max_attempts):
            try:
                result = fn()
                with self._lock:
                    self._total_successes += 1
                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                    history=history,
                )
            except Exception as e:
                last_error = str(e)

                # Check if retryable
                if retryable and not retryable(e):
                    with self._lock:
                        self._total_failures += 1
                    return RetryResult(
                        success=False,
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        last_error=last_error,
                        history=history,
                    )

                # Last attempt - no retry
                if attempt >= policy.max_attempts - 1:
                    break

                # Calculate and apply delay
                delay = self.calculate_delay(policy, attempt)
                total_delay += delay

                record = RetryAttempt(
                    attempt_number=attempt + 1,
                    error=last_error,
                    delay_seconds=delay,
                )
                history.append(record)

                with self._lock:
                    self._total_retries += 1

                if on_retry:
                    on_retry(attempt + 1, e, delay)

                _sleep(delay)

        with self._lock:
            self._total_failures += 1
        return RetryResult(
            success=False,
            attempts=policy.max_attempts,
            total_delay=total_delay,
            last_error=last_error,
            history=history,
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> RetryStats:
        """Get retry handler statistics."""
        return RetryStats(
            configured_policies=len(self._policies),
            total_executions=self._total_executions,
            total_retries=self._total_retries,
            total_successes=self._total_successes,
            total_failures=self._total_failures,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def policy_count(self) -> int:
        return len(self._policies)

    def clear(self) -> None:
        """Clear all policies and stats."""
        with self._lock:
            self._policies.clear()
            self._total_executions = 0
            self._total_retries = 0
            self._total_successes = 0
            self._total_failures = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_count": self.policy_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_handler: RetryHandler | None = None
_handler_lock = threading.Lock()


def get_retry_handler() -> RetryHandler:
    """Get or create the global retry handler."""
    global _handler
    if _handler is None:
        with _handler_lock:
            if _handler is None:
                _handler = RetryHandler()
    return _handler


def reset_retry_handler() -> None:
    """Reset the global retry handler (for testing)."""
    global _handler
    _handler = None
