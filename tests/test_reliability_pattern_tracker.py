"""
Tests for V12.4 Reliability Pattern Tracker.

Validates:
- RetryAttempt to_dict
- ToolReliabilityProfile to_dict / properties
- ReliabilityStats to_dict
- Recording attempts
- Tool profile updates
- Queries (all profiles, most reliable, least reliable, recent)
- Listing tools
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.execution.reliability_pattern_tracker import (
    MAX_ATTEMPTS,
    ReliabilityPatternTracker,
    ReliabilityStats,
    RetryAttempt,
    ToolReliabilityProfile,
    get_reliability_tracker,
    reset_reliability_tracker,
)

# =============================================================================
# RetryAttempt Tests
# =============================================================================


class TestRetryAttempt:
    """Test RetryAttempt dataclass."""

    def test_to_dict(self):
        a = RetryAttempt(attempt_id="ra_000000", tool_name="bash", retry_count=2, success=True)
        d = a.to_dict()
        assert d["tool_name"] == "bash"
        assert d["retry_count"] == 2


# =============================================================================
# ToolReliabilityProfile Tests
# =============================================================================


class TestToolReliabilityProfile:
    """Test ToolReliabilityProfile dataclass."""

    def test_success_rate(self):
        p = ToolReliabilityProfile(tool_name="bash", total_attempts=10, successes=8)
        assert abs(p.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        p = ToolReliabilityProfile(tool_name="bash")
        assert p.success_rate == 0.0

    def test_avg_retries(self):
        p = ToolReliabilityProfile(tool_name="bash", total_attempts=4, total_retries=8)
        assert abs(p.avg_retries - 2.0) < 0.01

    def test_avg_retries_zero(self):
        p = ToolReliabilityProfile(tool_name="bash")
        assert p.avg_retries == 0.0

    def test_timeout_rate(self):
        p = ToolReliabilityProfile(tool_name="bash", total_attempts=10, timeouts=3)
        assert abs(p.timeout_rate - 0.3) < 0.01

    def test_timeout_rate_zero(self):
        p = ToolReliabilityProfile(tool_name="bash")
        assert p.timeout_rate == 0.0

    def test_to_dict(self):
        p = ToolReliabilityProfile(tool_name="bash", total_attempts=5)
        d = p.to_dict()
        assert "success_rate" in d
        assert "avg_retries" in d
        assert "timeout_rate" in d


# =============================================================================
# ReliabilityStats Tests
# =============================================================================


class TestReliabilityStats:
    """Test ReliabilityStats dataclass."""

    def test_to_dict(self):
        s = ReliabilityStats(total_attempts=20, unique_tools=3)
        d = s.to_dict()
        assert d["total_attempts"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test attempt recording."""

    def test_record_basic(self):
        t = ReliabilityPatternTracker()
        a = t.record_attempt("bash", retry_count=0, success=True)
        assert a.attempt_id == "ra_000000"
        assert t.attempt_count == 1

    def test_profile_updates(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash", retry_count=0, success=True, timed_out=False)
        t.record_attempt("bash", retry_count=2, success=True, timed_out=False)
        t.record_attempt("bash", retry_count=1, success=False, timed_out=True)
        p = t.get_tool_profile("bash")
        assert p is not None
        assert p.total_attempts == 3
        assert p.successes == 2
        assert p.total_retries == 3
        assert p.timeouts == 1

    def test_multiple_tools(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash")
        t.record_attempt("glob")
        t.record_attempt("web_fetch")
        assert len(t.get_all_profiles()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        t = ReliabilityPatternTracker()
        assert t.get_tool_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash")
        t.record_attempt("glob")
        t.record_attempt("bash")
        profiles = t.get_all_profiles()
        assert profiles[0].tool_name == "bash"  # 2 > 1

    def test_most_reliable(self):
        t = ReliabilityPatternTracker()
        for _ in range(5):
            t.record_attempt("reliable_tool", success=True)
        for _ in range(3):
            t.record_attempt("flaky_tool", success=True)
        t.record_attempt("flaky_tool", success=False)
        t.record_attempt("flaky_tool", success=False)
        reliable = t.get_most_reliable(min_attempts=3)
        assert len(reliable) >= 1
        assert reliable[0].tool_name == "reliable_tool"

    def test_least_reliable(self):
        t = ReliabilityPatternTracker()
        for _ in range(5):
            t.record_attempt("good_tool", success=True)
        for _ in range(2):
            t.record_attempt("bad_tool", success=True)
        for _ in range(3):
            t.record_attempt("bad_tool", success=False)
        unreliable = t.get_least_reliable(min_attempts=3)
        assert len(unreliable) >= 1
        assert unreliable[0].tool_name == "bad_tool"

    def test_recent_attempts(self):
        t = ReliabilityPatternTracker()
        for _i in range(5):
            t.record_attempt("bash")
        recent = t.get_recent_attempts(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash")
        t.record_attempt("glob")
        t.record_attempt("bash")
        recent = t.get_recent_attempts(tool_name="bash")
        assert len(recent) == 2

    def test_list_tools(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("web_fetch")
        t.record_attempt("bash")
        assert t.list_tools() == ["bash", "web_fetch"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded attempt history."""

    def test_eviction(self):
        t = ReliabilityPatternTracker(max_attempts=5)
        for _i in range(10):
            t.record_attempt("bash")
        assert t.attempt_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = ReliabilityPatternTracker()
        stats = t.get_stats()
        assert stats.total_attempts == 0

    def test_stats_after_recording(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash", success=True, timed_out=False)
        t.record_attempt("glob", success=False, timed_out=True)
        stats = t.get_stats()
        assert stats.total_attempts == 2
        assert stats.unique_tools == 2

    def test_stats_to_dict(self):
        t = ReliabilityPatternTracker()
        d = t.get_stats().to_dict()
        assert "total_attempts" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash")
        assert t.attempt_count == 1

    def test_clear(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash")
        t.clear()
        assert t.attempt_count == 0
        assert t.get_tool_profile("bash") is None

    def test_to_dict(self):
        t = ReliabilityPatternTracker()
        t.record_attempt("bash")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global reliability tracker."""

    def test_get(self):
        reset_reliability_tracker()
        t = get_reliability_tracker()
        assert isinstance(t, ReliabilityPatternTracker)

    def test_singleton(self):
        reset_reliability_tracker()
        t1 = get_reliability_tracker()
        t2 = get_reliability_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_reliability_tracker()
        t1 = get_reliability_tracker()
        reset_reliability_tracker()
        t2 = get_reliability_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import (
            ReliabilityPatternTracker,
            ReliabilityRetryAttempt,
            ReliabilityStats,
            ToolReliabilityProfile,
            get_reliability_tracker,
            reset_reliability_tracker,
        )

        assert all(
            [
                ReliabilityPatternTracker,
                ReliabilityRetryAttempt,
                ToolReliabilityProfile,
                ReliabilityStats,
                get_reliability_tracker,
                reset_reliability_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_ATTEMPTS == 50000
