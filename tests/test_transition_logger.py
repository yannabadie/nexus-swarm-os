"""
Tests for V12.4 FSM Transition Logger.

Validates:
- TransitionEntry to_dict
- StateDurationStats to_dict
- TransitionFrequency to_dict
- LoggerStats to_dict
- Logging (basic, with context, auto-eviction)
- Queries (recent, by_state, by_trigger, by_session, by_time)
- Analysis (duration stats, frequencies, most common)
- Statistics
- State management
- Global singleton
- Module exports
"""

import time

from core.fsm.transition_logger import (
    MAX_ENTRIES,
    LoggerStats,
    StateDurationStats,
    TransitionEntry,
    TransitionFrequency,
    TransitionLogger,
    get_transition_logger,
    reset_transition_logger,
)

# =============================================================================
# TransitionEntry Tests
# =============================================================================


class TestTransitionEntry:
    """Test TransitionEntry dataclass."""

    def test_basic(self):
        e = TransitionEntry(from_state="idle", to_state="running")
        assert e.from_state == "idle"
        assert e.to_state == "running"

    def test_auto_timestamp(self):
        e = TransitionEntry(from_state="a", to_state="b")
        assert e.timestamp > 0

    def test_to_dict(self):
        e = TransitionEntry(from_state="idle", to_state="running", trigger="user", duration_ms=150.0)
        d = e.to_dict()
        assert d["from"] == "idle"
        assert d["to"] == "running"
        assert d["trigger"] == "user"
        assert d["duration_ms"] == 150.0


# =============================================================================
# StateDurationStats Tests
# =============================================================================


class TestStateDurationStats:
    """Test StateDurationStats dataclass."""

    def test_to_dict(self):
        s = StateDurationStats(state="idle", count=5, total_ms=500.0, min_ms=50.0, max_ms=200.0, avg_ms=100.0)
        d = s.to_dict()
        assert d["state"] == "idle"
        assert d["avg_ms"] == 100.0


# =============================================================================
# TransitionFrequency Tests
# =============================================================================


class TestTransitionFrequency:
    """Test TransitionFrequency dataclass."""

    def test_to_dict(self):
        f = TransitionFrequency(from_state="idle", to_state="running", count=10)
        d = f.to_dict()
        assert d["from"] == "idle"
        assert d["count"] == 10


# =============================================================================
# LoggerStats Tests
# =============================================================================


class TestLoggerStats:
    """Test LoggerStats dataclass."""

    def test_to_dict(self):
        s = LoggerStats(total_entries=100, unique_states=5, unique_transitions=8, entries_by_trigger={"user": 50})
        d = s.to_dict()
        assert d["total_entries"] == 100
        assert d["entries_by_trigger"]["user"] == 50


# =============================================================================
# Logging Tests
# =============================================================================


class TestLogging:
    """Test transition logging."""

    def test_log_basic(self):
        logger = TransitionLogger()
        entry = logger.log("idle", "running")
        assert entry.from_state == "idle"
        assert logger.entry_count == 1

    def test_log_with_details(self):
        logger = TransitionLogger()
        entry = logger.log(
            "idle",
            "running",
            trigger="user_input",
            session_id="s1",
            duration_ms=150.0,
            context={"task": "analyze"},
        )
        assert entry.trigger == "user_input"
        assert entry.context["task"] == "analyze"

    def test_log_multiple(self):
        logger = TransitionLogger()
        logger.log("idle", "running")
        logger.log("running", "done")
        assert logger.entry_count == 2

    def test_auto_eviction(self):
        logger = TransitionLogger(max_entries=5)
        for i in range(10):
            logger.log(f"s{i}", f"s{i + 1}")
        assert logger.entry_count == 5


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test transition queries."""

    def test_get_recent(self):
        logger = TransitionLogger()
        logger.log("a", "b")
        logger.log("b", "c")
        logger.log("c", "d")
        recent = logger.get_recent(limit=2)
        assert len(recent) == 2
        assert recent[0].from_state == "c"  # Most recent first

    def test_get_recent_default_limit(self):
        logger = TransitionLogger()
        for i in range(5):
            logger.log(f"s{i}", f"s{i + 1}")
        assert len(logger.get_recent()) == 5

    def test_get_by_state(self):
        logger = TransitionLogger()
        logger.log("idle", "running")
        logger.log("running", "done")
        logger.log("error", "idle")
        results = logger.get_by_state("running")
        assert len(results) == 2

    def test_get_by_from_state(self):
        logger = TransitionLogger()
        logger.log("idle", "running")
        logger.log("idle", "error")
        logger.log("running", "done")
        results = logger.get_by_from_state("idle")
        assert len(results) == 2

    def test_get_by_to_state(self):
        logger = TransitionLogger()
        logger.log("idle", "running")
        logger.log("error", "running")
        results = logger.get_by_to_state("running")
        assert len(results) == 2

    def test_get_by_trigger(self):
        logger = TransitionLogger()
        logger.log("a", "b", trigger="user")
        logger.log("b", "c", trigger="auto")
        logger.log("c", "d", trigger="user")
        results = logger.get_by_trigger("user")
        assert len(results) == 2

    def test_get_by_session(self):
        logger = TransitionLogger()
        logger.log("a", "b", session_id="s1")
        logger.log("b", "c", session_id="s2")
        logger.log("c", "d", session_id="s1")
        results = logger.get_by_session("s1")
        assert len(results) == 2

    def test_get_by_time_range(self):
        logger = TransitionLogger()
        t1 = time.monotonic()
        logger.log("a", "b")
        logger.log("b", "c")
        t2 = time.monotonic()
        logger.log("c", "d")
        results = logger.get_by_time_range(t1, t2)
        assert len(results) == 2


# =============================================================================
# Analysis Tests
# =============================================================================


class TestAnalysis:
    """Test transition analysis."""

    def test_state_duration_stats(self):
        logger = TransitionLogger()
        logger.log("idle", "running", duration_ms=100.0)
        logger.log("idle", "error", duration_ms=200.0)
        logger.log("running", "done", duration_ms=50.0)
        stats = logger.state_duration_stats("idle")
        assert stats is not None
        assert stats.count == 2
        assert stats.min_ms == 100.0
        assert stats.max_ms == 200.0
        assert stats.avg_ms == 150.0

    def test_state_duration_stats_none(self):
        logger = TransitionLogger()
        assert logger.state_duration_stats("missing") is None

    def test_state_duration_stats_no_durations(self):
        logger = TransitionLogger()
        logger.log("idle", "running")  # duration_ms=0
        assert logger.state_duration_stats("idle") is None

    def test_transition_frequencies(self):
        logger = TransitionLogger()
        logger.log("idle", "running")
        logger.log("idle", "running")
        logger.log("running", "done")
        freqs = logger.transition_frequencies()
        assert len(freqs) == 2
        assert freqs[0].count == 2  # Most frequent first

    def test_transition_frequencies_empty(self):
        logger = TransitionLogger()
        assert logger.transition_frequencies() == []

    def test_most_common_transition(self):
        logger = TransitionLogger()
        logger.log("idle", "running")
        logger.log("idle", "running")
        logger.log("running", "done")
        most = logger.most_common_transition()
        assert most is not None
        assert most.from_state == "idle"
        assert most.to_state == "running"
        assert most.count == 2

    def test_most_common_transition_empty(self):
        logger = TransitionLogger()
        assert logger.most_common_transition() is None


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test logger statistics."""

    def test_initial_stats(self):
        logger = TransitionLogger()
        stats = logger.get_stats()
        assert stats.total_entries == 0
        assert stats.unique_states == 0

    def test_stats_after_work(self):
        logger = TransitionLogger()
        logger.log("idle", "running", trigger="user")
        logger.log("running", "done", trigger="auto")
        logger.log("idle", "running", trigger="user")
        stats = logger.get_stats()
        assert stats.total_entries == 3
        assert stats.unique_states == 3
        assert stats.unique_transitions == 2
        assert stats.entries_by_trigger["user"] == 2

    def test_stats_to_dict(self):
        logger = TransitionLogger()
        d = logger.get_stats().to_dict()
        assert "total_entries" in d
        assert "unique_states" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_entry_count(self):
        logger = TransitionLogger()
        logger.log("a", "b")
        logger.log("b", "c")
        assert logger.entry_count == 2

    def test_clear(self):
        logger = TransitionLogger()
        logger.log("a", "b")
        logger.clear()
        assert logger.entry_count == 0

    def test_to_dict(self):
        logger = TransitionLogger()
        logger.log("a", "b")
        d = logger.to_dict()
        assert d["entry_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global transition logger."""

    def test_get(self):
        reset_transition_logger()
        logger = get_transition_logger()
        assert isinstance(logger, TransitionLogger)

    def test_singleton(self):
        reset_transition_logger()
        l1 = get_transition_logger()
        l2 = get_transition_logger()
        assert l1 is l2

    def test_reset(self):
        reset_transition_logger()
        l1 = get_transition_logger()
        reset_transition_logger()
        l2 = get_transition_logger()
        assert l1 is not l2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_fsm_package(self):
        from core.fsm import (
            LoggerStats,
            StateDurationStats,
            TransitionEntry,
            TransitionFrequency,
            TransitionLogger,
            get_transition_logger,
            reset_transition_logger,
        )

        assert all(
            [
                TransitionLogger,
                TransitionEntry,
                StateDurationStats,
                TransitionFrequency,
                LoggerStats,
                get_transition_logger,
                reset_transition_logger,
            ]
        )

    def test_from_module(self):
        assert MAX_ENTRIES == 50000
