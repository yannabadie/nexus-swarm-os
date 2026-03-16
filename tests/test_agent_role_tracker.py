"""
Tests for V12.4 Agent Role Tracker.

Validates:
- RoleAssignment to_dict
- AgentRoleProfile to_dict / properties
- RoleTrackerStats to_dict
- Recording assignments
- Profile updates
- Agent/role queries (profiles, best agent, best role)
- Listing agents/roles
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.swarm.agent_role_tracker import (
    MAX_ASSIGNMENTS,
    ROLES,
    AgentRoleProfile,
    AgentRoleTracker,
    RoleAssignment,
    RoleTrackerStats,
    get_role_tracker,
    reset_role_tracker,
)

# =============================================================================
# RoleAssignment Tests
# =============================================================================


class TestRoleAssignment:
    """Test RoleAssignment dataclass."""

    def test_to_dict(self):
        a = RoleAssignment(agent_id="claude", role="lead", mode="LEAD_SUPPORT", quality_score=0.9, success=True)
        d = a.to_dict()
        assert d["agent_id"] == "claude"
        assert d["role"] == "lead"


# =============================================================================
# AgentRoleProfile Tests
# =============================================================================


class TestAgentRoleProfile:
    """Test AgentRoleProfile dataclass."""

    def test_success_rate(self):
        p = AgentRoleProfile(agent_id="claude", role="lead", total_assignments=10, successes=8)
        assert abs(p.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        p = AgentRoleProfile(agent_id="claude", role="lead")
        assert p.success_rate == 0.0

    def test_avg_quality(self):
        p = AgentRoleProfile(agent_id="claude", role="lead", total_assignments=4, total_quality=3.2)
        assert abs(p.avg_quality - 0.8) < 0.01

    def test_to_dict(self):
        p = AgentRoleProfile(agent_id="claude", role="lead", total_assignments=5)
        d = p.to_dict()
        assert "success_rate" in d
        assert "avg_quality" in d


# =============================================================================
# RoleTrackerStats Tests
# =============================================================================


class TestRoleTrackerStats:
    """Test RoleTrackerStats dataclass."""

    def test_to_dict(self):
        s = RoleTrackerStats(total_assignments=20, unique_agents=3, unique_roles=4)
        d = s.to_dict()
        assert d["total_assignments"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test assignment recording."""

    def test_record_basic(self):
        t = AgentRoleTracker()
        a = t.record_assignment("claude", "lead", quality_score=0.9, success=True)
        assert a.agent_id == "claude"
        assert t.assignment_count == 1

    def test_profile_updates(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9, success=True)
        t.record_assignment("claude", "lead", quality_score=0.7, success=True)
        t.record_assignment("claude", "lead", quality_score=0.5, success=False)
        p = t.get_agent_role_profile("claude", "lead")
        assert p is not None
        assert p.total_assignments == 3
        assert p.successes == 2

    def test_multiple_roles(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9)
        t.record_assignment("claude", "support", quality_score=0.7)
        profiles = t.get_agent_profiles("claude")
        assert len(profiles) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        t = AgentRoleTracker()
        assert t.get_agent_role_profile("missing", "lead") is None

    def test_get_agent_profiles(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9)
        t.record_assignment("claude", "support", quality_score=0.7)
        profiles = t.get_agent_profiles("claude")
        assert len(profiles) == 2
        assert profiles[0].avg_quality > profiles[1].avg_quality  # sorted desc

    def test_get_role_profiles(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9)
        t.record_assignment("gemini", "lead", quality_score=0.7)
        profiles = t.get_role_profiles("lead")
        assert len(profiles) == 2
        assert profiles[0].agent_id == "claude"  # higher quality first

    def test_best_agent_for_role(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9)
        t.record_assignment("gemini", "lead", quality_score=0.7)
        assert t.get_best_agent_for_role("lead") == "claude"

    def test_best_agent_empty(self):
        t = AgentRoleTracker()
        assert t.get_best_agent_for_role("lead") is None

    def test_best_role_for_agent(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9)
        t.record_assignment("claude", "support", quality_score=0.6)
        assert t.get_best_role_for_agent("claude") == "lead"

    def test_best_role_empty(self):
        t = AgentRoleTracker()
        assert t.get_best_role_for_agent("missing") is None

    def test_recent_assignments(self):
        t = AgentRoleTracker()
        for i in range(5):
            t.record_assignment(f"agent_{i}", "lead")
        recent = t.get_recent_assignments(limit=3)
        assert len(recent) == 3


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test listing methods."""

    def test_list_agents(self):
        t = AgentRoleTracker()
        t.record_assignment("gemini", "lead")
        t.record_assignment("claude", "support")
        assert t.list_agents() == ["claude", "gemini"]

    def test_list_roles(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "support")
        t.record_assignment("claude", "lead")
        assert t.list_roles() == ["lead", "support"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded assignment history."""

    def test_eviction(self):
        t = AgentRoleTracker(max_assignments=5)
        for i in range(10):
            t.record_assignment(f"agent_{i}", "lead")
        assert t.assignment_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = AgentRoleTracker()
        stats = t.get_stats()
        assert stats.total_assignments == 0

    def test_stats_after_recording(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead", quality_score=0.9, success=True)
        t.record_assignment("gemini", "support", quality_score=0.7, success=False)
        stats = t.get_stats()
        assert stats.total_assignments == 2
        assert stats.unique_agents == 2
        assert stats.unique_roles == 2

    def test_stats_to_dict(self):
        t = AgentRoleTracker()
        d = t.get_stats().to_dict()
        assert "total_assignments" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead")
        assert t.assignment_count == 1

    def test_clear(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead")
        t.clear()
        assert t.assignment_count == 0
        assert t.get_agent_role_profile("claude", "lead") is None

    def test_to_dict(self):
        t = AgentRoleTracker()
        t.record_assignment("claude", "lead")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global role tracker."""

    def test_get(self):
        reset_role_tracker()
        t = get_role_tracker()
        assert isinstance(t, AgentRoleTracker)

    def test_singleton(self):
        reset_role_tracker()
        t1 = get_role_tracker()
        t2 = get_role_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_role_tracker()
        t1 = get_role_tracker()
        reset_role_tracker()
        t2 = get_role_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_swarm_package(self):
        from core.intelligence.swarm import (
            AgentRoleProfile,
            AgentRoleTracker,
            RoleAssignment,
            RoleTrackerStats,
            get_role_tracker,
            reset_role_tracker,
        )

        assert all(
            [
                AgentRoleTracker,
                RoleAssignment,
                AgentRoleProfile,
                RoleTrackerStats,
                get_role_tracker,
                reset_role_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_ASSIGNMENTS == 50000
        assert "lead" in ROLES
        assert "support" in ROLES
