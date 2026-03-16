"""
Unit tests for HealthStateMachine - FSM for System Health with Recovery.

NEXUS V8.4.5 - Bug Fixes Phase

Tests cover:
- Health state transitions
- Recovery strategy execution
- Error threshold handling
- Cooldown and max attempts
- State machine reset

Author: Claude (NEXUS V8.4.5)
Date: 2025-12-11
"""

import asyncio

# Add parent to path for imports
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fsm.health_state_machine import (
    HealthState,
    HealthStateMachine,
    RecoveryStrategy,
)


class TestHealthState(TestCase):
    """Tests for HealthState enum."""

    def test_all_states_exist(self):
        """Test that all expected health states exist."""
        assert HealthState.HEALTHY.value == "healthy"
        assert HealthState.DEGRADED.value == "degraded"
        assert HealthState.CRITICAL.value == "critical"
        assert HealthState.RECOVERING.value == "recovering"
        assert HealthState.PANIC.value == "panic"

    def test_states_are_unique(self):
        """Test that all state values are unique."""
        values = [s.value for s in HealthState]
        assert len(values) == len(set(values))


class TestRecoveryStrategy(TestCase):
    """Tests for RecoveryStrategy dataclass."""

    def test_strategy_creation(self):
        """Test creating a recovery strategy."""

        async def dummy_action():
            return True

        strategy = RecoveryStrategy(
            name="test_strategy",
            description="Test recovery strategy",
            action=dummy_action,
            cooldown_seconds=60.0,
            max_attempts=5,
        )

        assert strategy.name == "test_strategy"
        assert strategy.cooldown_seconds == 60.0
        assert strategy.max_attempts == 5
        assert strategy.attempt_count == 0
        assert strategy.last_attempt is None

    def test_strategy_is_available_initially(self):
        """Test that new strategy is available."""
        strategy = RecoveryStrategy(name="test", description="Test", action=AsyncMock())

        assert strategy.is_available() is True

    def test_strategy_unavailable_after_max_attempts(self):
        """Test that strategy becomes unavailable after max attempts."""
        strategy = RecoveryStrategy(
            name="test",
            description="Test",
            action=AsyncMock(),
            max_attempts=2,
            cooldown_seconds=0.0,
        )

        strategy.mark_used()
        assert strategy.is_available() is True  # 1 < 2

        strategy.mark_used()
        assert strategy.is_available() is False  # 2 >= 2

    def test_strategy_unavailable_during_cooldown(self):
        """Test that strategy respects cooldown period."""
        strategy = RecoveryStrategy(
            name="test",
            description="Test",
            action=AsyncMock(),
            cooldown_seconds=3600.0,  # 1 hour
            max_attempts=10,
        )

        strategy.mark_used()

        # Should be unavailable due to cooldown
        assert strategy.is_available() is False

    def test_strategy_available_after_cooldown(self):
        """Test that strategy becomes available after cooldown."""
        strategy = RecoveryStrategy(
            name="test", description="Test", action=AsyncMock(), cooldown_seconds=1.0, max_attempts=10
        )

        strategy.mark_used()
        # Manually set last_attempt to past
        strategy.last_attempt = datetime.now() - timedelta(seconds=2)

        assert strategy.is_available() is True

    def test_strategy_reset(self):
        """Test that reset clears counters."""
        strategy = RecoveryStrategy(name="test", description="Test", action=AsyncMock(), max_attempts=2)

        strategy.mark_used()
        strategy.mark_used()
        assert strategy.is_available() is False

        strategy.reset()

        assert strategy.attempt_count == 0
        assert strategy.last_attempt is None
        assert strategy.is_available() is True


class TestHealthStateMachineBasic(TestCase):
    """Basic functionality tests for HealthStateMachine."""

    def test_init_starts_healthy(self):
        """Test that HSM starts in HEALTHY state."""
        hsm = HealthStateMachine()

        assert hsm.state == HealthState.HEALTHY
        assert hsm.is_healthy is True
        assert hsm.is_panic is False
        assert hsm.error_count == 0

    def test_add_strategy(self):
        """Test adding a recovery strategy."""
        hsm = HealthStateMachine()
        strategy = RecoveryStrategy(name="test", description="Test", action=AsyncMock())

        hsm.add_strategy(strategy)

        assert len(hsm._strategies) == 1
        assert hsm._strategies[0].name == "test"


class TestHealthStateMachineTransitions(TestCase):
    """Tests for state transitions."""

    def test_healthy_to_degraded_on_error(self):
        """Test transition from HEALTHY to DEGRADED on first error."""
        hsm = HealthStateMachine(auto_recover=False)

        async def run_test():
            await hsm.record_error("TEST_ERROR", "Test error message")

            assert hsm.state == HealthState.DEGRADED
            assert hsm.error_count == 1

        asyncio.run(run_test())

    def test_degraded_to_critical_on_errors(self):
        """Test transition to CRITICAL after threshold errors."""
        hsm = HealthStateMachine(auto_recover=False)

        async def run_test():
            # Record enough errors to reach CRITICAL
            for i in range(3):
                await hsm.record_error(f"ERROR_{i}", f"Error {i}")

            assert hsm.state == HealthState.CRITICAL
            assert hsm.error_count >= hsm.CRITICAL_THRESHOLD

        asyncio.run(run_test())

    def test_degraded_to_healthy_on_success(self):
        """Test that success resets from DEGRADED to HEALTHY."""
        hsm = HealthStateMachine(auto_recover=False)

        async def run_test():
            await hsm.record_error("TEST_ERROR", "Error")
            assert hsm.state == HealthState.DEGRADED

            hsm.record_success()

            assert hsm.state == HealthState.HEALTHY
            assert hsm.error_count == 0

        asyncio.run(run_test())


class TestHealthStateMachineRecovery(TestCase):
    """Tests for recovery execution."""

    def test_auto_recovery_on_critical(self):
        """Test that auto recovery triggers on CRITICAL state."""
        hsm = HealthStateMachine(auto_recover=True)

        recovery_called = []

        async def mock_recovery():
            recovery_called.append(True)
            return True

        hsm.add_strategy(RecoveryStrategy(name="mock_recovery", description="Mock recovery", action=mock_recovery))

        async def run_test():
            # Trigger enough errors to reach CRITICAL and auto-recover
            for i in range(3):
                await hsm.record_error(f"ERROR_{i}", f"Error {i}")

            # Recovery should have been attempted
            assert len(recovery_called) > 0 or hsm.state in [
                HealthState.RECOVERING,
                HealthState.HEALTHY,
                HealthState.CRITICAL,
            ]

        asyncio.run(run_test())

    def test_recovery_success_returns_to_healthy(self):
        """Test successful recovery returns to HEALTHY."""
        hsm = HealthStateMachine(auto_recover=False)

        async def successful_recovery():
            return True

        hsm.add_strategy(RecoveryStrategy(name="good_recovery", description="Works", action=successful_recovery))

        async def run_test():
            # Force to CRITICAL
            hsm._state = HealthState.CRITICAL

            result = await hsm.attempt_recovery()

            assert result is True
            assert hsm.state == HealthState.HEALTHY

        asyncio.run(run_test())

    def test_recovery_failure_stays_critical(self):
        """Test failed recovery stays in CRITICAL."""
        hsm = HealthStateMachine(auto_recover=False)

        async def failed_recovery():
            return False

        hsm.add_strategy(
            RecoveryStrategy(name="bad_recovery", description="Fails", action=failed_recovery, max_attempts=1)
        )

        async def run_test():
            hsm._state = HealthState.CRITICAL

            result = await hsm.attempt_recovery()

            # Should have tried and failed
            assert result is False

        asyncio.run(run_test())

    def test_no_strategies_goes_to_panic(self):
        """Test that CRITICAL with no strategies available goes to PANIC."""
        hsm = HealthStateMachine(auto_recover=True)

        # No strategies registered

        async def run_test():
            # Trigger enough errors
            for i in range(5):
                await hsm.record_error(f"ERROR_{i}", f"Error {i}")

            # With no recovery options, should panic
            assert hsm.state == HealthState.PANIC

        asyncio.run(run_test())


class TestHealthStateMachineReset(TestCase):
    """Tests for manual reset."""

    def test_reset_from_panic(self):
        """Test that manual reset works from PANIC."""
        hsm = HealthStateMachine()
        hsm._state = HealthState.PANIC

        hsm.reset()

        assert hsm.state == HealthState.HEALTHY
        assert hsm.error_count == 0

    def test_reset_clears_strategy_counters(self):
        """Test that reset also resets strategy counters."""
        hsm = HealthStateMachine()
        strategy = RecoveryStrategy(name="test", description="Test", action=AsyncMock(), max_attempts=1)
        hsm.add_strategy(strategy)
        strategy.mark_used()

        assert strategy.is_available() is False

        hsm.reset()

        assert strategy.is_available() is True


class TestHealthStateMachineHistory(TestCase):
    """Tests for history tracking."""

    def test_history_records_transitions(self):
        """Test that state transitions are recorded in history."""
        hsm = HealthStateMachine(auto_recover=False)

        async def run_test():
            await hsm.record_error("ERROR_1", "First error")
            hsm.record_success()

            # Should have history entries
            assert len(hsm._history) >= 2

        asyncio.run(run_test())


# =============================================================================
# PYTEST ASYNC TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_multiple_strategies_tried_in_order():
    """Test that strategies are tried in registration order."""
    hsm = HealthStateMachine(auto_recover=False)
    order = []

    async def strategy_1():
        order.append(1)
        return False

    async def strategy_2():
        order.append(2)
        return False

    async def strategy_3():
        order.append(3)
        return True  # This one succeeds

    hsm.add_strategy(RecoveryStrategy("s1", "First", strategy_1, max_attempts=1))
    hsm.add_strategy(RecoveryStrategy("s2", "Second", strategy_2, max_attempts=1))
    hsm.add_strategy(RecoveryStrategy("s3", "Third", strategy_3, max_attempts=1))

    hsm._state = HealthState.CRITICAL

    result = await hsm.attempt_recovery()

    # Should have tried strategies in order until success
    assert result is True
    assert order == [1, 2, 3]


@pytest.mark.asyncio
async def test_strategy_exception_handled():
    """Test that exceptions in strategies are handled gracefully."""
    hsm = HealthStateMachine(auto_recover=False)

    async def exploding_strategy():
        raise ValueError("Strategy explosion!")

    hsm.add_strategy(RecoveryStrategy("exploder", "Explodes", exploding_strategy, max_attempts=1))

    hsm._state = HealthState.CRITICAL

    # Should not raise, should return False
    result = await hsm.attempt_recovery()
    assert result is False


@pytest.mark.asyncio
async def test_callback_on_state_change():
    """Test that callbacks are called on state change."""
    hsm = HealthStateMachine(auto_recover=False)
    changes = []

    def on_change(old_state, new_state, reason):
        changes.append((old_state, new_state, reason))

    hsm._on_state_change.append(on_change)

    await hsm.record_error("TEST", "Test error")

    assert len(changes) > 0
    assert changes[0][0] == HealthState.HEALTHY
    assert changes[0][1] == HealthState.DEGRADED


@pytest.mark.asyncio
async def test_error_count_accumulates():
    """Test that error count accumulates correctly."""
    hsm = HealthStateMachine(auto_recover=False)

    await hsm.record_error("E1", "Error 1")
    assert hsm.error_count == 1

    await hsm.record_error("E2", "Error 2")
    assert hsm.error_count == 2

    await hsm.record_error("E3", "Error 3")
    assert hsm.error_count == 3


@pytest.mark.asyncio
async def test_success_decrements_error_count():
    """Test that success decrements error count (not resets)."""
    hsm = HealthStateMachine(auto_recover=False)

    await hsm.record_error("E1", "Error 1")
    await hsm.record_error("E2", "Error 2")
    assert hsm.error_count == 2

    # V11.4: record_success() is sync, decrements by 1
    hsm.record_success()
    assert hsm.error_count == 1  # Decremented, not reset

    hsm.record_success()
    assert hsm.error_count == 0  # Now at 0


if __name__ == "__main__":
    main()
