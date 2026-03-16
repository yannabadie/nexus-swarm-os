"""
Tests for V12.4 FSM Guard Logger.

Validates:
- GuardEvaluation to_dict
- GuardMetrics to_dict / properties
- BlockedTransition to_dict
- GuardLoggerStats to_dict
- Evaluation recording (metric updates)
- Blocked transition tracking
- Queries (by guard, state, result, blocked transitions)
- Most blocking guards
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.fsm.guard_logger import (
    MAX_EVALUATIONS,
    BlockedTransition,
    GuardEvaluation,
    GuardLogger,
    GuardLoggerStats,
    GuardMetrics,
    get_guard_logger,
    reset_guard_logger,
)

# =============================================================================
# GuardEvaluation Tests
# =============================================================================


class TestGuardEvaluation:
    """Test GuardEvaluation dataclass."""

    def test_basic(self):
        e = GuardEvaluation(guard_name="can_execute", from_state="IDLE", to_state="EXECUTING", result=True)
        assert e.result is True

    def test_to_dict(self):
        e = GuardEvaluation(
            guard_name="can_execute",
            from_state="IDLE",
            to_state="EXECUTING",
            result=False,
            reason="Not authorized",
        )
        d = e.to_dict()
        assert d["result"] is False
        assert d["reason"] == "Not authorized"


# =============================================================================
# GuardMetrics Tests
# =============================================================================


class TestGuardMetrics:
    """Test GuardMetrics dataclass."""

    def test_allow_rate(self):
        m = GuardMetrics(guard_name="g", total_evaluations=10, allowed_count=8, blocked_count=2)
        assert abs(m.allow_rate - 0.8) < 0.01

    def test_block_rate(self):
        m = GuardMetrics(guard_name="g", total_evaluations=10, allowed_count=8, blocked_count=2)
        assert abs(m.block_rate - 0.2) < 0.01

    def test_rates_zero(self):
        m = GuardMetrics(guard_name="g")
        assert m.allow_rate == 0.0
        assert m.block_rate == 0.0

    def test_to_dict(self):
        m = GuardMetrics(guard_name="g", total_evaluations=5)
        d = m.to_dict()
        assert "allow_rate" in d


# =============================================================================
# BlockedTransition Tests
# =============================================================================


class TestBlockedTransition:
    """Test BlockedTransition dataclass."""

    def test_to_dict(self):
        b = BlockedTransition(from_state="IDLE", to_state="PANIC", guard_name="safety_check", reason="Not safe")
        d = b.to_dict()
        assert d["guard_name"] == "safety_check"


# =============================================================================
# GuardLoggerStats Tests
# =============================================================================


class TestGuardLoggerStats:
    """Test GuardLoggerStats dataclass."""

    def test_to_dict(self):
        s = GuardLoggerStats(
            total_evaluations=20, total_blocked=5, total_allowed=15, unique_guards=3, unique_transitions=4
        )
        d = s.to_dict()
        assert d["total_evaluations"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test evaluation recording."""

    def test_record_allowed(self):
        log = GuardLogger()
        e = log.record_evaluation("can_execute", "IDLE", "EXECUTING", True)
        assert e.result is True
        assert log.evaluation_count == 1

    def test_record_blocked(self):
        log = GuardLogger()
        e = log.record_evaluation("safety_check", "IDLE", "PANIC", False, reason="Not safe")
        assert e.result is False
        assert log.blocked_count == 1

    def test_metrics_updated(self):
        log = GuardLogger()
        log.record_evaluation("can_execute", "IDLE", "EXECUTING", True, latency_ms=10)
        log.record_evaluation("can_execute", "IDLE", "EXECUTING", True, latency_ms=20)
        log.record_evaluation("can_execute", "IDLE", "EXECUTING", False, latency_ms=5)
        m = log.get_guard_metrics("can_execute")
        assert m is not None
        assert m.total_evaluations == 3
        assert m.allowed_count == 2
        assert m.blocked_count == 1

    def test_multiple_guards(self):
        log = GuardLogger()
        log.record_evaluation("guard_a", "IDLE", "EXEC", True)
        log.record_evaluation("guard_b", "EXEC", "IDLE", True)
        metrics = log.get_all_metrics()
        assert len(metrics) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_guard_metrics_not_found(self):
        log = GuardLogger()
        assert log.get_guard_metrics("missing") is None

    def test_get_all_metrics(self):
        log = GuardLogger()
        log.record_evaluation("a", "IDLE", "EXEC", True)
        log.record_evaluation("b", "IDLE", "EXEC", True)
        log.record_evaluation("a", "IDLE", "EXEC", True)
        metrics = log.get_all_metrics()
        assert len(metrics) == 2
        assert metrics[0].guard_name == "a"  # highest total_evaluations first

    def test_get_blocked_transitions(self):
        log = GuardLogger()
        log.record_evaluation("safety", "IDLE", "PANIC", False, reason="Unsafe")
        log.record_evaluation("safety", "IDLE", "EXEC", True)
        log.record_evaluation("auth", "IDLE", "PANIC", False, reason="Not authorized")
        blocked = log.get_blocked_transitions()
        assert len(blocked) == 2

    def test_get_blocked_by_guard(self):
        log = GuardLogger()
        log.record_evaluation("safety", "IDLE", "PANIC", False)
        log.record_evaluation("auth", "IDLE", "PANIC", False)
        blocked = log.get_blocked_transitions(guard_name="safety")
        assert len(blocked) == 1

    def test_get_blocked_by_from_state(self):
        log = GuardLogger()
        log.record_evaluation("safety", "IDLE", "PANIC", False)
        log.record_evaluation("safety", "EXEC", "PANIC", False)
        blocked = log.get_blocked_transitions(from_state="IDLE")
        assert len(blocked) == 1

    def test_get_evaluations_filtered(self):
        log = GuardLogger()
        log.record_evaluation("a", "IDLE", "EXEC", True)
        log.record_evaluation("b", "EXEC", "IDLE", False)
        log.record_evaluation("a", "IDLE", "EXEC", False)
        results = log.get_evaluations(guard_name="a")
        assert len(results) == 2
        results = log.get_evaluations(result=False)
        assert len(results) == 2

    def test_get_evaluations_with_limit(self):
        log = GuardLogger()
        for _ in range(10):
            log.record_evaluation("a", "IDLE", "EXEC", True)
        results = log.get_evaluations(limit=3)
        assert len(results) == 3

    def test_most_blocking_guards(self):
        log = GuardLogger()
        for _ in range(5):
            log.record_evaluation("safety", "IDLE", "PANIC", False)
        for _ in range(2):
            log.record_evaluation("auth", "IDLE", "PANIC", False)
        log.record_evaluation("timing", "IDLE", "EXEC", True)
        blocking = log.get_most_blocking_guards(limit=2)
        assert len(blocking) == 2
        assert blocking[0].guard_name == "safety"


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded evaluation history."""

    def test_eviction(self):
        log = GuardLogger(max_evaluations=5)
        for i in range(10):
            log.record_evaluation(f"guard_{i}", "IDLE", "EXEC", True)
        assert log.evaluation_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test guard logger statistics."""

    def test_initial_stats(self):
        log = GuardLogger()
        stats = log.get_stats()
        assert stats.total_evaluations == 0

    def test_stats_after_recording(self):
        log = GuardLogger()
        log.record_evaluation("a", "IDLE", "EXEC", True)
        log.record_evaluation("b", "EXEC", "IDLE", False)
        stats = log.get_stats()
        assert stats.total_evaluations == 2
        assert stats.total_allowed == 1
        assert stats.total_blocked == 1
        assert stats.unique_guards == 2

    def test_stats_to_dict(self):
        log = GuardLogger()
        d = log.get_stats().to_dict()
        assert "total_evaluations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        log = GuardLogger()
        log.record_evaluation("a", "IDLE", "EXEC", True)
        log.record_evaluation("b", "IDLE", "EXEC", False)
        assert log.evaluation_count == 2
        assert log.blocked_count == 1

    def test_clear(self):
        log = GuardLogger()
        log.record_evaluation("a", "IDLE", "EXEC", True)
        log.clear()
        assert log.evaluation_count == 0
        assert log.blocked_count == 0
        assert log.get_guard_metrics("a") is None

    def test_to_dict(self):
        log = GuardLogger()
        log.record_evaluation("a", "IDLE", "EXEC", True)
        d = log.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global guard logger."""

    def test_get(self):
        reset_guard_logger()
        log = get_guard_logger()
        assert isinstance(log, GuardLogger)

    def test_singleton(self):
        reset_guard_logger()
        l1 = get_guard_logger()
        l2 = get_guard_logger()
        assert l1 is l2

    def test_reset(self):
        reset_guard_logger()
        l1 = get_guard_logger()
        reset_guard_logger()
        l2 = get_guard_logger()
        assert l1 is not l2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_fsm_package(self):
        from core.fsm import (
            BlockedTransition,
            GuardEvaluation,
            GuardLogger,
            GuardLoggerStats,
            GuardMetrics,
            get_guard_logger,
            reset_guard_logger,
        )

        assert all(
            [
                GuardLogger,
                GuardEvaluation,
                GuardMetrics,
                BlockedTransition,
                GuardLoggerStats,
                get_guard_logger,
                reset_guard_logger,
            ]
        )

    def test_constants(self):
        assert MAX_EVALUATIONS == 50000
