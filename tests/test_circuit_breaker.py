"""
V9.3 ISSUE-007: Circuit Breaker Tests

Tests for the resilience circuit breaker pattern.
"""

import time

import pytest

from core.infrastructure.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    reset_all_circuits,
)


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def test_initial_state_is_closed(self):
        """Circuit should start in CLOSED state."""
        breaker = CircuitBreaker(name="test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_stays_closed_on_success(self):
        """Successful calls keep circuit CLOSED."""
        breaker = CircuitBreaker(name="test")

        result = breaker.call_sync(lambda: "success")

        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_opens_after_threshold_failures(self):
        """Circuit opens after failure_threshold failures."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        def failing_func():
            raise ValueError("Test error")

        # Fail 3 times
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call_sync(failing_func)

        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    def test_rejects_calls_when_open(self):
        """Circuit rejects calls when OPEN."""
        breaker = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)

        # Trip the circuit
        with pytest.raises(ValueError):
            breaker.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Should reject next call
        with pytest.raises(CircuitOpenError) as exc_info:
            breaker.call_sync(lambda: "should not run")

        assert exc_info.value.name == "test"
        assert exc_info.value.failure_count == 1

    def test_allows_retry_after_recovery_timeout(self):
        """Circuit allows retry after recovery_timeout."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,  # 100ms for fast test
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            breaker.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # Should allow call (HALF_OPEN)
        result = breaker.call_sync(lambda: "recovered")
        assert result == "recovered"
        assert breaker.state == CircuitState.CLOSED

    def test_exponential_backoff_on_repeated_failures(self):
        """Backoff increases exponentially on repeated failures."""
        breaker = CircuitBreaker(
            name="test", failure_threshold=1, recovery_timeout=1.0, backoff_multiplier=2.0, max_backoff=10.0
        )

        def fail():
            raise ValueError("fail")

        # First failure - opens circuit
        with pytest.raises(ValueError):
            breaker.call_sync(fail)

        assert breaker._current_backoff == 1.0

        # Simulate recovery attempt that fails
        breaker._last_failure_time = time.time() - 2  # Pretend time passed
        breaker._state = CircuitState.HALF_OPEN

        with pytest.raises(ValueError):
            breaker.call_sync(fail)

        # Backoff should have doubled
        assert breaker._current_backoff == 2.0
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerAsync:
    """Test async circuit breaker operations."""

    @pytest.mark.asyncio
    async def test_async_call_success(self):
        """Async calls work through circuit breaker."""
        breaker = CircuitBreaker(name="async_test")

        async def async_success():
            return "async_result"

        result = await breaker.call(async_success)
        assert result == "async_result"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_async_call_failure_trips_circuit(self):
        """Async failures trip the circuit."""
        breaker = CircuitBreaker(name="async_test", failure_threshold=2)

        async def async_fail():
            raise RuntimeError("async failure")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(async_fail)

        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerRegistry:
    """Test global circuit breaker registry."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_all_circuits()

    def test_get_circuit_breaker_creates_new(self):
        """get_circuit_breaker creates new breaker if not exists."""
        breaker = get_circuit_breaker("new_breaker")
        assert breaker.name == "new_breaker"
        assert breaker.state == CircuitState.CLOSED

    def test_get_circuit_breaker_returns_same_instance(self):
        """get_circuit_breaker returns same instance for same name."""
        breaker1 = get_circuit_breaker("shared")
        breaker2 = get_circuit_breaker("shared")
        assert breaker1 is breaker2

    def test_reset_all_circuits(self):
        """reset_all_circuits resets all breakers."""
        breaker = get_circuit_breaker("reset_test", failure_threshold=1)

        # Trip it
        with pytest.raises(ValueError):
            breaker.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Reset all
        reset_all_circuits()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0


class TestCircuitBreakerStatus:
    """Test status reporting."""

    def test_get_status_returns_all_fields(self):
        """get_status returns complete status dict."""
        breaker = CircuitBreaker(name="status_test", failure_threshold=5)
        status = breaker.get_status()

        assert status["name"] == "status_test"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["failure_threshold"] == 5
        assert "current_backoff" in status
        assert "time_until_retry" in status


class TestCircuitBreakerManualReset:
    """Test manual reset functionality."""

    def test_manual_reset(self):
        """reset() returns circuit to CLOSED state."""
        breaker = CircuitBreaker(name="reset_test", failure_threshold=1)

        # Trip it
        with pytest.raises(ValueError):
            breaker.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Manual reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
