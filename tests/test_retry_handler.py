"""
Tests for V12.4 Execution Retry Handler.

Validates:
- RetryPolicy to_dict
- RetryAttempt to_dict
- RetryResult to_dict
- RetryStats to_dict
- Policy management (configure, unconfigure, get, list)
- Delay calculation (exponential backoff, jitter, max cap)
- Execute (success, failure, retries, retryable predicate, callbacks)
- No policy = single attempt
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.execution.retry_handler import (
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_ATTEMPTS,
    RetryAttempt,
    RetryHandler,
    RetryPolicy,
    RetryResult,
    RetryStats,
    get_retry_handler,
    reset_retry_handler,
)

# =============================================================================
# RetryPolicy Tests
# =============================================================================


class TestRetryPolicy:
    """Test RetryPolicy dataclass."""

    def test_defaults(self):
        p = RetryPolicy(name="default")
        assert p.max_attempts == DEFAULT_MAX_ATTEMPTS
        assert p.base_delay == DEFAULT_BASE_DELAY

    def test_custom(self):
        p = RetryPolicy(name="fast", max_attempts=5, base_delay=0.1)
        assert p.max_attempts == 5

    def test_to_dict(self):
        p = RetryPolicy(name="api", max_attempts=3)
        d = p.to_dict()
        assert d["name"] == "api"
        assert d["max_attempts"] == 3


# =============================================================================
# RetryAttempt Tests
# =============================================================================


class TestRetryAttempt:
    """Test RetryAttempt dataclass."""

    def test_basic(self):
        a = RetryAttempt(attempt_number=1, error="timeout", delay_seconds=1.0)
        assert a.attempt_number == 1
        assert a.timestamp > 0

    def test_to_dict(self):
        a = RetryAttempt(attempt_number=2, error="err", delay_seconds=2.5)
        d = a.to_dict()
        assert d["attempt"] == 2
        assert d["delay_seconds"] == 2.5


# =============================================================================
# RetryResult Tests
# =============================================================================


class TestRetryResult:
    """Test RetryResult dataclass."""

    def test_success(self):
        r = RetryResult(success=True, result="ok", attempts=1)
        assert r.success is True

    def test_failure(self):
        r = RetryResult(success=False, last_error="fatal", attempts=3)
        assert r.success is False

    def test_to_dict(self):
        r = RetryResult(success=True, attempts=2, total_delay=1.5)
        d = r.to_dict()
        assert d["success"] is True
        assert d["total_delay"] == 1.5


# =============================================================================
# RetryStats Tests
# =============================================================================


class TestRetryStats:
    """Test RetryStats dataclass."""

    def test_to_dict(self):
        s = RetryStats(
            configured_policies=2,
            total_executions=100,
            total_retries=10,
            total_successes=90,
            total_failures=10,
        )
        d = s.to_dict()
        assert d["total_retries"] == 10


# =============================================================================
# Policy Management Tests
# =============================================================================


class TestPolicyManagement:
    """Test policy CRUD."""

    def test_configure(self):
        h = RetryHandler()
        p = h.configure("api", max_attempts=5)
        assert p.name == "api"
        assert h.policy_count == 1

    def test_configure_defaults(self):
        h = RetryHandler()
        p = h.configure("default")
        assert p.max_attempts == DEFAULT_MAX_ATTEMPTS

    def test_reconfigure(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3)
        h.configure("api", max_attempts=5)
        assert h.get_policy("api").max_attempts == 5

    def test_unconfigure(self):
        h = RetryHandler()
        h.configure("api")
        assert h.unconfigure("api") is True
        assert h.policy_count == 0

    def test_unconfigure_not_found(self):
        h = RetryHandler()
        assert h.unconfigure("missing") is False

    def test_get_policy(self):
        h = RetryHandler()
        h.configure("api")
        assert h.get_policy("api") is not None

    def test_get_policy_not_found(self):
        h = RetryHandler()
        assert h.get_policy("missing") is None

    def test_list_policies(self):
        h = RetryHandler()
        h.configure("a")
        h.configure("b")
        assert len(h.list_policies()) == 2


# =============================================================================
# Delay Calculation Tests
# =============================================================================


class TestDelayCalculation:
    """Test exponential backoff delay."""

    def test_exponential_growth(self):
        h = RetryHandler()
        p = RetryPolicy(name="test", base_delay=1.0, backoff_factor=2.0, jitter=False, max_delay=100.0)
        assert h.calculate_delay(p, 0) == 1.0
        assert h.calculate_delay(p, 1) == 2.0
        assert h.calculate_delay(p, 2) == 4.0
        assert h.calculate_delay(p, 3) == 8.0

    def test_max_delay_cap(self):
        h = RetryHandler()
        p = RetryPolicy(name="test", base_delay=1.0, backoff_factor=2.0, jitter=False, max_delay=5.0)
        assert h.calculate_delay(p, 10) == 5.0

    def test_jitter_reduces_delay(self):
        h = RetryHandler()
        p = RetryPolicy(name="test", base_delay=10.0, backoff_factor=1.0, jitter=True, max_delay=100.0)
        delays = [h.calculate_delay(p, 0) for _ in range(20)]
        # All delays should be between 5.0 and 10.0 (0.5 to 1.0 of base)
        assert all(4.9 <= d <= 10.1 for d in delays)
        # Not all the same (jitter is random)
        assert len(set(round(d, 3) for d in delays)) > 1


# =============================================================================
# Execute Tests
# =============================================================================


class TestExecute:
    """Test retry execution."""

    def test_success_first_try(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3)
        result = h.execute("api", lambda: "ok", sleep_fn=lambda d: None)
        assert result.success is True
        assert result.result == "ok"
        assert result.attempts == 1

    def test_success_after_retries(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3, base_delay=0.01, jitter=False)
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 3:
                raise RuntimeError("flaky")
            return "ok"

        result = h.execute("api", flaky, sleep_fn=lambda d: None)
        assert result.success is True
        assert result.attempts == 3
        assert len(result.history) == 2  # 2 retries

    def test_failure_all_attempts(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3, base_delay=0.01, jitter=False)
        result = h.execute(
            "api",
            lambda: (_ for _ in ()).throw(RuntimeError("fail")),
            sleep_fn=lambda d: None,
        )
        assert result.success is False
        assert result.attempts == 3
        assert result.last_error == "fail"

    def test_retryable_predicate(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3)
        call_count = [0]

        def failing():
            call_count[0] += 1
            raise ValueError("not retryable")

        result = h.execute(
            "api",
            failing,
            retryable=lambda e: isinstance(e, RuntimeError),  # Only RuntimeError
            sleep_fn=lambda d: None,
        )
        assert result.success is False
        assert call_count[0] == 1  # No retries

    def test_on_retry_callback(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3, base_delay=0.01, jitter=False)
        retries = []
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 3:
                raise RuntimeError("err")
            return "ok"

        result = h.execute(
            "api",
            flaky,
            on_retry=lambda attempt, err, delay: retries.append(attempt),
            sleep_fn=lambda d: None,
        )
        assert result.success is True
        assert retries == [1, 2]

    def test_no_policy_single_attempt_success(self):
        h = RetryHandler()
        result = h.execute("nonexistent", lambda: "ok")
        assert result.success is True
        assert result.attempts == 1

    def test_no_policy_single_attempt_failure(self):
        h = RetryHandler()
        result = h.execute(
            "nonexistent",
            lambda: (_ for _ in ()).throw(RuntimeError("oops")),
        )
        assert result.success is False
        assert result.attempts == 1

    def test_total_delay_tracked(self):
        h = RetryHandler()
        h.configure("api", max_attempts=3, base_delay=1.0, jitter=False)
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 3:
                raise RuntimeError("err")
            return "ok"

        result = h.execute("api", flaky, sleep_fn=lambda d: None)
        assert result.total_delay > 0


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test retry handler statistics."""

    def test_initial_stats(self):
        h = RetryHandler()
        stats = h.get_stats()
        assert stats.total_executions == 0

    def test_stats_after_work(self):
        h = RetryHandler()
        h.configure("api", max_attempts=2, base_delay=0.01, jitter=False)
        h.execute("api", lambda: "ok", sleep_fn=lambda d: None)
        counter = [0]

        def fail():
            counter[0] += 1
            raise RuntimeError("err")

        h.execute("api", fail, sleep_fn=lambda d: None)
        stats = h.get_stats()
        assert stats.total_executions == 2
        assert stats.total_successes == 1
        assert stats.total_failures == 1
        assert stats.total_retries == 1  # 1 retry before final failure

    def test_stats_to_dict(self):
        h = RetryHandler()
        d = h.get_stats().to_dict()
        assert "total_executions" in d
        assert "total_retries" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_policy_count(self):
        h = RetryHandler()
        h.configure("a")
        h.configure("b")
        assert h.policy_count == 2

    def test_clear(self):
        h = RetryHandler()
        h.configure("api")
        h.execute("api", lambda: "ok", sleep_fn=lambda d: None)
        h.clear()
        assert h.policy_count == 0
        assert h.get_stats().total_executions == 0

    def test_to_dict(self):
        h = RetryHandler()
        h.configure("api")
        d = h.to_dict()
        assert d["policy_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global retry handler."""

    def test_get(self):
        reset_retry_handler()
        h = get_retry_handler()
        assert isinstance(h, RetryHandler)

    def test_singleton(self):
        reset_retry_handler()
        h1 = get_retry_handler()
        h2 = get_retry_handler()
        assert h1 is h2

    def test_reset(self):
        reset_retry_handler()
        h1 = get_retry_handler()
        reset_retry_handler()
        h2 = get_retry_handler()
        assert h1 is not h2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import (
            RetryAttempt,
            RetryHandler,
            RetryPolicy,
            RetryResult,
            RetryStats,
            get_retry_handler,
            reset_retry_handler,
        )

        assert all(
            [
                RetryHandler,
                RetryPolicy,
                RetryResult,
                RetryAttempt,
                RetryStats,
                get_retry_handler,
                reset_retry_handler,
            ]
        )

    def test_from_module(self):
        from core.execution_pkg.execution.retry_handler import (
            DEFAULT_BASE_DELAY,
            DEFAULT_MAX_ATTEMPTS,
        )

        assert DEFAULT_MAX_ATTEMPTS == 3
        assert DEFAULT_BASE_DELAY == 1.0
