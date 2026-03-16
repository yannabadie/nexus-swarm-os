"""
Tests for V12.4 Session Efficiency Scorecard.

Validates:
- SessionRecord to_dict / properties
- SessionProfile to_dict / properties
- ScorecardStats to_dict
- Recording sessions
- Profile updates
- Queries (profiles, best session, recent, list sessions)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.infrastructure.session.session_efficiency_scorecard import (
    MAX_SESSION_RECORDS,
    ScorecardStats,
    SessionEfficiencyScorecard,
    SessionProfile,
    SessionRecord,
    get_session_scorecard,
    reset_session_scorecard,
)

# =============================================================================
# SessionRecord Tests
# =============================================================================


class TestSessionRecord:
    """Test SessionRecord dataclass."""

    def test_completion_rate(self):
        r = SessionRecord(tasks_completed=8, tasks_attempted=10)
        assert abs(r.completion_rate - 0.8) < 0.01

    def test_completion_rate_zero(self):
        r = SessionRecord()
        assert r.completion_rate == 0.0

    def test_tool_success_rate(self):
        r = SessionRecord(tool_calls_total=20, tool_calls_successful=18)
        assert abs(r.tool_success_rate - 0.9) < 0.01

    def test_tool_success_rate_zero(self):
        r = SessionRecord()
        assert r.tool_success_rate == 0.0

    def test_to_dict(self):
        r = SessionRecord(session_id="sess_1", tasks_completed=5, tasks_attempted=10)
        d = r.to_dict()
        assert "completion_rate" in d
        assert "tool_success_rate" in d
        assert d["session_id"] == "sess_1"


# =============================================================================
# SessionProfile Tests
# =============================================================================


class TestSessionProfile:
    """Test SessionProfile dataclass."""

    def test_avg_completion_rate(self):
        p = SessionProfile(
            session_id="sess_1",
            total_tasks_completed=8,
            total_tasks_attempted=10,
        )
        assert abs(p.avg_completion_rate - 0.8) < 0.01

    def test_avg_completion_rate_zero(self):
        p = SessionProfile(session_id="sess_1")
        assert p.avg_completion_rate == 0.0

    def test_avg_tool_success_rate(self):
        p = SessionProfile(
            session_id="sess_1",
            total_tool_calls=20,
            total_tool_successes=16,
        )
        assert abs(p.avg_tool_success_rate - 0.8) < 0.01

    def test_avg_tool_success_rate_zero(self):
        p = SessionProfile(session_id="sess_1")
        assert p.avg_tool_success_rate == 0.0

    def test_avg_duration_ms(self):
        p = SessionProfile(
            session_id="sess_1",
            total_records=4,
            total_duration_ms=4000.0,
        )
        assert abs(p.avg_duration_ms - 1000.0) < 0.01

    def test_avg_duration_zero(self):
        p = SessionProfile(session_id="sess_1")
        assert p.avg_duration_ms == 0.0

    def test_to_dict(self):
        p = SessionProfile(session_id="sess_1", total_records=5)
        d = p.to_dict()
        assert "avg_completion_rate" in d
        assert "avg_tool_success_rate" in d
        assert "avg_duration_ms" in d


# =============================================================================
# ScorecardStats Tests
# =============================================================================


class TestScorecardStats:
    """Test ScorecardStats dataclass."""

    def test_to_dict(self):
        s = ScorecardStats(total_records=20, unique_sessions=3)
        d = s.to_dict()
        assert d["total_records"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test session recording."""

    def test_record_basic(self):
        s = SessionEfficiencyScorecard()
        r = s.record_session("sess_1", tasks_completed=5, tasks_attempted=10)
        assert r.record_id == "sr_000000"
        assert s.record_count == 1

    def test_profile_updates(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_1", tasks_completed=5, tasks_attempted=10, tool_calls_total=20, tool_calls_successful=18)
        s.record_session("sess_1", tasks_completed=3, tasks_attempted=5, tool_calls_total=10, tool_calls_successful=8)
        p = s.get_session_profile("sess_1")
        assert p is not None
        assert p.total_records == 2
        assert p.total_tasks_completed == 8
        assert p.total_tasks_attempted == 15

    def test_multiple_sessions(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_1", tasks_completed=5, tasks_attempted=10)
        s.record_session("sess_2", tasks_completed=3, tasks_attempted=5)
        assert len(s.get_all_profiles()) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        s = SessionEfficiencyScorecard()
        assert s.get_session_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        s = SessionEfficiencyScorecard()
        s.record_session("once", tasks_completed=1, tasks_attempted=1)
        s.record_session("twice", tasks_completed=1, tasks_attempted=1)
        s.record_session("twice", tasks_completed=1, tasks_attempted=1)
        profiles = s.get_all_profiles()
        assert profiles[0].session_id == "twice"  # 2 records > 1

    def test_best_session(self):
        s = SessionEfficiencyScorecard()
        s.record_session("good", tasks_completed=9, tasks_attempted=10)
        s.record_session("bad", tasks_completed=3, tasks_attempted=10)
        assert s.get_best_session() == "good"

    def test_best_session_empty(self):
        s = SessionEfficiencyScorecard()
        assert s.get_best_session() is None

    def test_recent_records(self):
        s = SessionEfficiencyScorecard()
        for i in range(5):
            s.record_session(f"sess_{i}", tasks_completed=1, tasks_attempted=1)
        recent = s.get_recent_records(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_a", tasks_completed=1, tasks_attempted=1)
        s.record_session("sess_b", tasks_completed=1, tasks_attempted=1)
        s.record_session("sess_a", tasks_completed=1, tasks_attempted=1)
        recent = s.get_recent_records(session_id="sess_a")
        assert len(recent) == 2

    def test_list_sessions(self):
        s = SessionEfficiencyScorecard()
        s.record_session("zeta")
        s.record_session("alpha")
        assert s.list_sessions() == ["alpha", "zeta"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded record history."""

    def test_eviction(self):
        s = SessionEfficiencyScorecard(max_records=5)
        for i in range(10):
            s.record_session(f"sess_{i}")
        assert s.record_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test scorecard statistics."""

    def test_initial_stats(self):
        s = SessionEfficiencyScorecard()
        stats = s.get_stats()
        assert stats.total_records == 0

    def test_stats_after_recording(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_1", tasks_completed=8, tasks_attempted=10, tool_calls_total=20, tool_calls_successful=18)
        s.record_session("sess_2", tasks_completed=4, tasks_attempted=5, tool_calls_total=10, tool_calls_successful=9)
        stats = s.get_stats()
        assert stats.total_records == 2
        assert stats.unique_sessions == 2

    def test_stats_to_dict(self):
        s = SessionEfficiencyScorecard()
        d = s.get_stats().to_dict()
        assert "total_records" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_1")
        assert s.record_count == 1

    def test_clear(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_1")
        s.clear()
        assert s.record_count == 0
        assert s.get_session_profile("sess_1") is None

    def test_to_dict(self):
        s = SessionEfficiencyScorecard()
        s.record_session("sess_1")
        d = s.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global session scorecard."""

    def test_get(self):
        reset_session_scorecard()
        s = get_session_scorecard()
        assert isinstance(s, SessionEfficiencyScorecard)

    def test_singleton(self):
        reset_session_scorecard()
        s1 = get_session_scorecard()
        s2 = get_session_scorecard()
        assert s1 is s2

    def test_reset(self):
        reset_session_scorecard()
        s1 = get_session_scorecard()
        reset_session_scorecard()
        s2 = get_session_scorecard()
        assert s1 is not s2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_session_package(self):
        from core.infrastructure.session import (
            ScorecardStats,
            SessionEfficiencyScorecard,
            SessionProfile,
            SessionRecord,
            get_session_scorecard,
            reset_session_scorecard,
        )

        assert all(
            [
                SessionEfficiencyScorecard,
                SessionRecord,
                SessionProfile,
                ScorecardStats,
                get_session_scorecard,
                reset_session_scorecard,
            ]
        )

    def test_constants(self):
        assert MAX_SESSION_RECORDS == 50000
