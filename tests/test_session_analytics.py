"""
Tests for V12.4 Session Analytics.

Validates:
- PhaseMetric to_dict
- AgentAction to_dict
- SessionMetrics to_dict
- AnalyticsStats to_dict
- Phase recording
- Action recording
- Session metrics computation
- Phase breakdown
- Agent actions query
- Agent effectiveness (cross-session)
- Session management (list, has)
- Session eviction
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.infrastructure.session.session_analytics import (
    MAX_SESSIONS,
    AgentAction,
    AnalyticsStats,
    PhaseMetric,
    SessionAnalytics,
    SessionMetrics,
    get_session_analytics,
    reset_session_analytics,
)

# =============================================================================
# PhaseMetric Tests
# =============================================================================


class TestPhaseMetric:
    """Test PhaseMetric dataclass."""

    def test_basic(self):
        p = PhaseMetric(session_id="s1", phase="ANALYSIS", duration_ms=500)
        assert p.phase == "ANALYSIS"

    def test_to_dict(self):
        p = PhaseMetric(session_id="s1", phase="EXECUTION", tokens_used=1200, cost=0.05)
        d = p.to_dict()
        assert d["tokens_used"] == 1200
        assert d["cost"] == 0.05


# =============================================================================
# AgentAction Tests
# =============================================================================


class TestAgentAction:
    """Test AgentAction dataclass."""

    def test_basic(self):
        a = AgentAction(session_id="s1", agent_id="claude", action_type="tool_call")
        assert a.agent_id == "claude"

    def test_to_dict(self):
        a = AgentAction(session_id="s1", agent_id="claude", action_type="brainstorm", success=True, quality=0.9)
        d = a.to_dict()
        assert d["quality"] == 0.9


# =============================================================================
# SessionMetrics Tests
# =============================================================================


class TestSessionMetrics:
    """Test SessionMetrics dataclass."""

    def test_to_dict(self):
        m = SessionMetrics(
            session_id="s1",
            total_phases=3,
            total_actions=10,
            total_duration_ms=5000,
            total_tokens=3000,
            total_cost=0.15,
            success_rate=0.9,
            average_quality=0.85,
        )
        d = m.to_dict()
        assert d["total_phases"] == 3
        assert d["success_rate"] == 0.9


# =============================================================================
# AnalyticsStats Tests
# =============================================================================


class TestAnalyticsStats:
    """Test AnalyticsStats dataclass."""

    def test_to_dict(self):
        s = AnalyticsStats(total_sessions=5, total_phases=15, total_actions=50, total_tokens=10000, total_cost=0.5)
        d = s.to_dict()
        assert d["total_sessions"] == 5


# =============================================================================
# Phase Recording Tests
# =============================================================================


class TestPhaseRecording:
    """Test phase metric recording."""

    def test_record_phase(self):
        a = SessionAnalytics()
        p = a.record_phase("s1", phase="ANALYSIS", duration_ms=500, tokens=1200, cost=0.05)
        assert p.phase == "ANALYSIS"
        assert a.session_count == 1

    def test_multiple_phases(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="ANALYSIS", duration_ms=500)
        a.record_phase("s1", phase="EXECUTION", duration_ms=1500)
        breakdown = a.get_phase_breakdown("s1")
        assert len(breakdown) == 2


# =============================================================================
# Action Recording Tests
# =============================================================================


class TestActionRecording:
    """Test agent action recording."""

    def test_record_action(self):
        a = SessionAnalytics()
        act = a.record_action("s1", agent_id="claude", action="tool_call", success=True, quality=0.9)
        assert act.agent_id == "claude"
        assert act.success is True

    def test_multiple_actions(self):
        a = SessionAnalytics()
        a.record_action("s1", agent_id="claude", action="tool_call")
        a.record_action("s1", agent_id="gemini", action="brainstorm")
        actions = a.get_agent_actions("s1")
        assert len(actions) == 2


# =============================================================================
# Session Metrics Tests
# =============================================================================


class TestSessionMetricsComputation:
    """Test session metrics computation."""

    def test_basic_metrics(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="ANALYSIS", duration_ms=500, tokens=1000, cost=0.03)
        a.record_phase("s1", phase="EXECUTION", duration_ms=1500, tokens=2000, cost=0.07)
        a.record_action("s1", agent_id="claude", action="tool", success=True, quality=0.9)
        a.record_action("s1", agent_id="gemini", action="brainstorm", success=True, quality=0.8)

        m = a.get_session_metrics("s1")
        assert m is not None
        assert m.total_phases == 2
        assert m.total_actions == 2
        assert m.total_duration_ms == 2000
        assert m.total_tokens == 3000
        assert m.total_cost == 0.10
        assert m.success_rate == 1.0
        assert abs(m.average_quality - 0.85) < 0.01
        assert set(m.agents_involved) == {"claude", "gemini"}

    def test_metrics_with_failures(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="ANALYSIS", duration_ms=500)
        a.record_action("s1", agent_id="claude", action="tool", success=True, quality=0.9)
        a.record_action("s1", agent_id="claude", action="tool", success=False)
        m = a.get_session_metrics("s1")
        assert m.success_rate == 0.5

    def test_metrics_not_found(self):
        a = SessionAnalytics()
        assert a.get_session_metrics("missing") is None


# =============================================================================
# Agent Actions Query Tests
# =============================================================================


class TestAgentActionsQuery:
    """Test agent actions querying."""

    def test_filter_by_agent(self):
        a = SessionAnalytics()
        a.record_action("s1", agent_id="claude", action="tool")
        a.record_action("s1", agent_id="gemini", action="brainstorm")
        a.record_action("s1", agent_id="claude", action="validate")
        actions = a.get_agent_actions("s1", agent_id="claude")
        assert len(actions) == 2

    def test_all_actions(self):
        a = SessionAnalytics()
        a.record_action("s1", agent_id="claude", action="tool")
        a.record_action("s1", agent_id="gemini", action="brainstorm")
        actions = a.get_agent_actions("s1")
        assert len(actions) == 2


# =============================================================================
# Cross-Session Tests
# =============================================================================


class TestCrossSession:
    """Test cross-session analysis."""

    def test_agent_effectiveness(self):
        a = SessionAnalytics()
        a.record_action("s1", agent_id="claude", action="tool", success=True, quality=0.9)
        a.record_action("s2", agent_id="claude", action="tool", success=True, quality=0.8)
        a.record_action("s3", agent_id="claude", action="tool", success=False)
        eff = a.get_agent_effectiveness("claude")
        assert eff["total_actions"] == 3
        assert abs(eff["success_rate"] - 2 / 3) < 0.01
        assert eff["sessions_participated"] == 3

    def test_agent_effectiveness_not_found(self):
        a = SessionAnalytics()
        eff = a.get_agent_effectiveness("missing")
        assert eff["total_actions"] == 0

    def test_list_sessions(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="ANALYSIS")
        a.record_phase("s2", phase="ANALYSIS")
        assert a.list_sessions() == ["s1", "s2"]

    def test_has_session(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="ANALYSIS")
        assert a.has_session("s1") is True
        assert a.has_session("missing") is False


# =============================================================================
# Session Eviction Tests
# =============================================================================


class TestSessionEviction:
    """Test session eviction when at limit."""

    def test_eviction(self):
        a = SessionAnalytics(max_sessions=3)
        a.record_phase("s1", phase="A")
        a.record_phase("s2", phase="A")
        a.record_phase("s3", phase="A")
        a.record_phase("s4", phase="A")  # Evicts s1
        assert a.session_count == 3
        assert not a.has_session("s1")
        assert a.has_session("s4")


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analytics statistics."""

    def test_initial_stats(self):
        a = SessionAnalytics()
        stats = a.get_stats()
        assert stats.total_sessions == 0
        assert stats.total_phases == 0

    def test_stats_after_recording(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="ANALYSIS", tokens=1000, cost=0.05)
        a.record_action("s1", agent_id="claude", action="tool")
        stats = a.get_stats()
        assert stats.total_sessions == 1
        assert stats.total_phases == 1
        assert stats.total_actions == 1
        assert stats.total_tokens == 1000
        assert stats.total_cost == 0.05

    def test_stats_to_dict(self):
        a = SessionAnalytics()
        d = a.get_stats().to_dict()
        assert "total_sessions" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_session_count(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="A")
        a.record_phase("s2", phase="A")
        assert a.session_count == 2

    def test_clear(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="A")
        a.record_action("s1", agent_id="claude", action="tool")
        a.clear()
        assert a.session_count == 0

    def test_to_dict(self):
        a = SessionAnalytics()
        a.record_phase("s1", phase="A")
        d = a.to_dict()
        assert d["session_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global session analytics."""

    def test_get(self):
        reset_session_analytics()
        a = get_session_analytics()
        assert isinstance(a, SessionAnalytics)

    def test_singleton(self):
        reset_session_analytics()
        a1 = get_session_analytics()
        a2 = get_session_analytics()
        assert a1 is a2

    def test_reset(self):
        reset_session_analytics()
        a1 = get_session_analytics()
        reset_session_analytics()
        a2 = get_session_analytics()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_session_package(self):
        from core.infrastructure.session import (
            AgentAction,
            AnalyticsStats,
            PhaseMetric,
            SessionAnalytics,
            SessionMetrics,
            get_session_analytics,
            reset_session_analytics,
        )

        assert all(
            [
                SessionAnalytics,
                PhaseMetric,
                AgentAction,
                SessionMetrics,
                AnalyticsStats,
                get_session_analytics,
                reset_session_analytics,
            ]
        )

    def test_constants(self):
        assert MAX_SESSIONS == 5000
