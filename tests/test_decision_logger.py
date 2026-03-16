"""
Tests for V12.4 Governance Decision Logger.

Validates:
- GovernanceDecision to_dict
- DecisionPattern to_dict
- DecisionLogStats to_dict
- Recording (mode choice, spawn, violation, phase routing)
- Queries (by session, agent, type, outcome, recent, violations)
- Pattern analysis
- Mode success summary
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.security_pkg.governance.decision_logger import (
    DECISION_TYPES,
    MAX_ENTRIES,
    DecisionLogStats,
    DecisionPattern,
    GovernanceDecision,
    GovernanceDecisionLog,
    get_decision_logger,
    reset_decision_logger,
)

# =============================================================================
# GovernanceDecision Tests
# =============================================================================


class TestGovernanceDecision:
    """Test GovernanceDecision dataclass."""

    def test_basic(self):
        d = GovernanceDecision(decision_id="gd_1", decision_type="mode_choice")
        assert d.decision_id == "gd_1"
        assert d.timestamp > 0

    def test_to_dict(self):
        d = GovernanceDecision(
            decision_id="gd_1",
            decision_type="spawn_decision",
            agent_id="claude",
            reasoning="Expert needed",
        )
        result = d.to_dict()
        assert result["decision_type"] == "spawn_decision"
        assert result["agent_id"] == "claude"


# =============================================================================
# DecisionPattern Tests
# =============================================================================


class TestDecisionPattern:
    """Test DecisionPattern dataclass."""

    def test_to_dict(self):
        p = DecisionPattern(decision_type="mode_choice", outcome="PARALLEL", count=10, frequency=0.5)
        d = p.to_dict()
        assert d["count"] == 10
        assert d["frequency"] == 0.5


# =============================================================================
# DecisionLogStats Tests
# =============================================================================


class TestDecisionLogStats:
    """Test DecisionLogStats dataclass."""

    def test_to_dict(self):
        s = DecisionLogStats(
            total_decisions=20,
            mode_choices=10,
            spawn_decisions=5,
            policy_violations=3,
            phase_routings=2,
            unique_sessions=4,
        )
        d = s.to_dict()
        assert d["total_decisions"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test decision recording methods."""

    def test_record_mode_choice(self):
        log = GovernanceDecisionLog()
        d = log.record_mode_choice(
            session_id="s1",
            proposed_mode="PARALLEL",
            accepted_mode="LEAD_SUPPORT",
            reasoning="Lead has context",
            agents=["claude", "gemini"],
        )
        assert d.decision_type == "mode_choice"
        assert d.outcome == "LEAD_SUPPORT"
        assert d.metadata["proposed_mode"] == "PARALLEL"
        assert log.size == 1

    def test_record_spawn_decision(self):
        log = GovernanceDecisionLog()
        d = log.record_spawn_decision(
            session_id="s1",
            agent_id="security_expert",
            agent_spec="Security domain expert",
            approved=True,
        )
        assert d.decision_type == "spawn_decision"
        assert d.outcome == "approved"

    def test_record_spawn_rejected(self):
        log = GovernanceDecisionLog()
        d = log.record_spawn_decision(approved=False, reasoning="Agent limit reached")
        assert d.outcome == "rejected"

    def test_record_policy_violation(self):
        log = GovernanceDecisionLog()
        d = log.record_policy_violation(
            session_id="s1",
            agent_id="rogue",
            violation_type="Tool access denied",
            severity="high",
            remediation="Blocked tool call",
        )
        assert d.decision_type == "policy_violation"
        assert d.metadata["severity"] == "high"

    def test_record_phase_routing(self):
        log = GovernanceDecisionLog()
        d = log.record_phase_routing(
            session_id="s1",
            from_phase="ANALYSIS",
            to_phase="EXECUTION",
            reasoning="Analysis complete",
        )
        assert d.decision_type == "phase_routing"
        assert d.metadata["to_phase"] == "EXECUTION"

    def test_auto_incrementing_id(self):
        log = GovernanceDecisionLog()
        d1 = log.record_mode_choice()
        d2 = log.record_mode_choice()
        assert d1.decision_id == "gd_000001"
        assert d2.decision_id == "gd_000002"

    def test_multiple_types(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice(session_id="s1")
        log.record_spawn_decision(session_id="s1")
        log.record_policy_violation(session_id="s1")
        log.record_phase_routing(session_id="s1")
        assert log.size == 4


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_query_by_session(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice(session_id="s1")
        log.record_mode_choice(session_id="s2")
        log.record_mode_choice(session_id="s1")
        results = log.query_by_session("s1")
        assert len(results) == 2

    def test_query_by_agent(self):
        log = GovernanceDecisionLog()
        log.record_spawn_decision(agent_id="claude")
        log.record_spawn_decision(agent_id="gemini")
        results = log.query_by_agent("claude")
        assert len(results) == 1

    def test_query_by_type(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice()
        log.record_spawn_decision()
        log.record_mode_choice()
        results = log.query_by_type("mode_choice")
        assert len(results) == 2

    def test_query_by_outcome(self):
        log = GovernanceDecisionLog()
        log.record_spawn_decision(approved=True)
        log.record_spawn_decision(approved=False)
        results = log.query_by_outcome("approved")
        assert len(results) == 1

    def test_get_recent(self):
        log = GovernanceDecisionLog()
        for i in range(10):
            log.record_mode_choice(session_id=f"s{i}")
        recent = log.get_recent(limit=3)
        assert len(recent) == 3
        assert recent[0].session_id == "s9"

    def test_get_violations(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice()
        log.record_policy_violation(violation_type="Breach")
        log.record_policy_violation(violation_type="Abuse")
        violations = log.get_violations()
        assert len(violations) == 2

    def test_query_with_limit(self):
        log = GovernanceDecisionLog()
        for _ in range(10):
            log.record_mode_choice(session_id="s1")
        results = log.query_by_session("s1", limit=3)
        assert len(results) == 3


# =============================================================================
# Analytics Tests
# =============================================================================


class TestAnalytics:
    """Test pattern analysis and analytics."""

    def test_analyze_patterns(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice(accepted_mode="PARALLEL")
        log.record_mode_choice(accepted_mode="PARALLEL")
        log.record_mode_choice(accepted_mode="SPECIALIST")
        patterns = log.analyze_patterns("mode_choice")
        assert len(patterns) == 2
        assert patterns[0].outcome == "PARALLEL"
        assert patterns[0].count == 2
        assert abs(patterns[0].frequency - 2 / 3) < 0.01

    def test_analyze_empty(self):
        log = GovernanceDecisionLog()
        patterns = log.analyze_patterns("mode_choice")
        assert patterns == []

    def test_mode_success_summary(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice(accepted_mode="PARALLEL")
        log.record_mode_choice(accepted_mode="PARALLEL")
        log.record_mode_choice(accepted_mode="SPECIALIST")
        summary = log.mode_success_summary()
        assert summary["PARALLEL"] == 2
        assert summary["SPECIALIST"] == 1


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded history with auto-eviction."""

    def test_eviction(self):
        log = GovernanceDecisionLog(max_entries=5)
        for i in range(10):
            log.record_mode_choice(session_id=f"s{i}")
        assert log.size == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test decision log statistics."""

    def test_initial_stats(self):
        log = GovernanceDecisionLog()
        stats = log.get_stats()
        assert stats.total_decisions == 0

    def test_stats_after_recording(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice(session_id="s1")
        log.record_spawn_decision(session_id="s1")
        log.record_policy_violation(session_id="s2")
        log.record_phase_routing(session_id="s2")
        stats = log.get_stats()
        assert stats.total_decisions == 4
        assert stats.mode_choices == 1
        assert stats.spawn_decisions == 1
        assert stats.policy_violations == 1
        assert stats.phase_routings == 1
        assert stats.unique_sessions == 2

    def test_stats_to_dict(self):
        log = GovernanceDecisionLog()
        d = log.get_stats().to_dict()
        assert "total_decisions" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice()
        log.record_mode_choice()
        assert log.size == 2

    def test_clear(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice()
        log.clear()
        assert log.size == 0

    def test_clear_resets_id_counter(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice()
        log.clear()
        d = log.record_mode_choice()
        assert d.decision_id == "gd_000001"

    def test_to_dict(self):
        log = GovernanceDecisionLog()
        log.record_mode_choice()
        d = log.to_dict()
        assert d["size"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global decision logger."""

    def test_get(self):
        reset_decision_logger()
        logger = get_decision_logger()
        assert isinstance(logger, GovernanceDecisionLog)

    def test_singleton(self):
        reset_decision_logger()
        l1 = get_decision_logger()
        l2 = get_decision_logger()
        assert l1 is l2

    def test_reset(self):
        reset_decision_logger()
        l1 = get_decision_logger()
        reset_decision_logger()
        l2 = get_decision_logger()
        assert l1 is not l2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_governance_package(self):
        from core.security_pkg.governance import (
            DecisionLogStats,
            DecisionPattern,
            GovernanceDecision,
            GovernanceDecisionLog,
            get_decision_logger,
            reset_decision_logger,
        )

        assert all(
            [
                GovernanceDecisionLog,
                GovernanceDecision,
                DecisionPattern,
                DecisionLogStats,
                get_decision_logger,
                reset_decision_logger,
            ]
        )

    def test_constants(self):
        assert MAX_ENTRIES == 50000
        assert "mode_choice" in DECISION_TYPES
