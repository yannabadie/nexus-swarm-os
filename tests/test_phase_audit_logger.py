"""
Tests for V12.4 Phase Audit Logger.

Validates:
- DecisionAudit to_dict
- PhaseAuditReport to_dict
- AuditPattern to_dict
- AuditStats to_dict
- Decision recording (auto-incrementing IDs)
- Queries (by session, phase, agent, recent)
- Phase report generation
- Pattern detection
- Session timeline
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.hive_mind.phase_audit_logger import (
    MAX_AUDITS,
    PHASES,
    AuditPattern,
    AuditStats,
    DecisionAudit,
    PhaseAuditLogger,
    PhaseAuditReport,
    get_phase_audit_logger,
    reset_phase_audit_logger,
)

# =============================================================================
# DecisionAudit Tests
# =============================================================================


class TestDecisionAudit:
    """Test DecisionAudit dataclass."""

    def test_basic(self):
        a = DecisionAudit(audit_id="pa_000001", phase="ANALYSIS")
        assert a.audit_id == "pa_000001"
        assert a.timestamp > 0

    def test_to_dict(self):
        a = DecisionAudit(
            audit_id="pa_000001",
            session_id="s1",
            phase="EXECUTION",
            decision="parallel_mode",
            agent_id="claude",
            duration_ms=150.0,
        )
        d = a.to_dict()
        assert d["phase"] == "EXECUTION"
        assert d["decision"] == "parallel_mode"


# =============================================================================
# PhaseAuditReport Tests
# =============================================================================


class TestPhaseAuditReport:
    """Test PhaseAuditReport dataclass."""

    def test_to_dict(self):
        r = PhaseAuditReport(
            phase="ANALYSIS",
            total_decisions=10,
            avg_duration_ms=200.0,
            unique_agents=2,
            most_common_decision="proceed",
            decision_distribution={"proceed": 7, "retry": 3},
        )
        d = r.to_dict()
        assert d["total_decisions"] == 10
        assert d["most_common_decision"] == "proceed"


# =============================================================================
# AuditPattern Tests
# =============================================================================


class TestAuditPattern:
    """Test AuditPattern dataclass."""

    def test_to_dict(self):
        p = AuditPattern(
            pattern_type="consistent_routing",
            phase="EXECUTION",
            description="Always selects parallel",
            frequency=0.8,
            sample_count=10,
        )
        d = p.to_dict()
        assert d["frequency"] == 0.8


# =============================================================================
# AuditStats Tests
# =============================================================================


class TestAuditStats:
    """Test AuditStats dataclass."""

    def test_to_dict(self):
        s = AuditStats(total_audits=20, audits_by_phase={"ANALYSIS": 10}, unique_sessions=5, unique_agents=3)
        d = s.to_dict()
        assert d["total_audits"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test decision recording."""

    def test_record_decision(self):
        log = PhaseAuditLogger()
        a = log.record_decision(session_id="s1", phase="ANALYSIS", decision="proceed")
        assert a.phase == "ANALYSIS"
        assert a.decision == "proceed"
        assert log.size == 1

    def test_auto_incrementing_id(self):
        log = PhaseAuditLogger()
        a1 = log.record_decision(phase="ANALYSIS")
        a2 = log.record_decision(phase="EXECUTION")
        assert a1.audit_id == "pa_000001"
        assert a2.audit_id == "pa_000002"

    def test_record_with_options(self):
        log = PhaseAuditLogger()
        a = log.record_decision(
            phase="DEBATE",
            decision="proceed",
            options_considered=["proceed", "retry", "escalate"],
            reasoning="Consensus reached",
        )
        assert len(a.options_considered) == 3
        assert a.reasoning == "Consensus reached"

    def test_multiple_phases(self):
        log = PhaseAuditLogger()
        log.record_decision(session_id="s1", phase="ANALYSIS")
        log.record_decision(session_id="s1", phase="DEBATE")
        log.record_decision(session_id="s1", phase="EXECUTION")
        assert log.size == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_query_by_session(self):
        log = PhaseAuditLogger()
        log.record_decision(session_id="s1", phase="ANALYSIS")
        log.record_decision(session_id="s2", phase="ANALYSIS")
        log.record_decision(session_id="s1", phase="EXECUTION")
        results = log.query_by_session("s1")
        assert len(results) == 2

    def test_query_by_phase(self):
        log = PhaseAuditLogger()
        log.record_decision(phase="ANALYSIS")
        log.record_decision(phase="EXECUTION")
        log.record_decision(phase="ANALYSIS")
        results = log.query_by_phase("ANALYSIS")
        assert len(results) == 2

    def test_query_by_agent(self):
        log = PhaseAuditLogger()
        log.record_decision(agent_id="claude")
        log.record_decision(agent_id="gemini")
        log.record_decision(agent_id="claude")
        results = log.query_by_agent("claude")
        assert len(results) == 2

    def test_get_recent(self):
        log = PhaseAuditLogger()
        for i in range(10):
            log.record_decision(session_id=f"s{i}")
        recent = log.get_recent(limit=3)
        assert len(recent) == 3

    def test_query_with_limit(self):
        log = PhaseAuditLogger()
        for _ in range(10):
            log.record_decision(session_id="s1", phase="ANALYSIS")
        results = log.query_by_session("s1", limit=3)
        assert len(results) == 3


# =============================================================================
# Phase Report Tests
# =============================================================================


class TestPhaseReport:
    """Test phase report generation."""

    def test_basic_report(self):
        log = PhaseAuditLogger()
        log.record_decision(phase="ANALYSIS", decision="proceed", agent_id="claude", duration_ms=100)
        log.record_decision(phase="ANALYSIS", decision="proceed", agent_id="gemini", duration_ms=200)
        log.record_decision(phase="ANALYSIS", decision="retry", agent_id="claude", duration_ms=150)
        report = log.get_phase_report("ANALYSIS")
        assert report is not None
        assert report.total_decisions == 3
        assert report.unique_agents == 2
        assert report.most_common_decision == "proceed"
        assert report.decision_distribution["proceed"] == 2

    def test_report_not_found(self):
        log = PhaseAuditLogger()
        assert log.get_phase_report("ANALYSIS") is None

    def test_report_avg_duration(self):
        log = PhaseAuditLogger()
        log.record_decision(phase="EXECUTION", duration_ms=100)
        log.record_decision(phase="EXECUTION", duration_ms=300)
        report = log.get_phase_report("EXECUTION")
        assert abs(report.avg_duration_ms - 200.0) < 0.01


# =============================================================================
# Pattern Detection Tests
# =============================================================================


class TestPatternDetection:
    """Test pattern detection."""

    def test_consistent_routing(self):
        log = PhaseAuditLogger()
        for _ in range(8):
            log.record_decision(phase="EXECUTION", decision="parallel")
        for _ in range(2):
            log.record_decision(phase="EXECUTION", decision="sequential")
        patterns = log.detect_patterns(min_frequency=0.6)
        routing = [p for p in patterns if p.pattern_type == "consistent_routing"]
        assert len(routing) >= 1
        assert routing[0].phase == "EXECUTION"

    def test_frequent_retry(self):
        log = PhaseAuditLogger()
        for _ in range(5):
            log.record_decision(phase="RETRY", decision="retry_attempt")
        patterns = log.detect_patterns()
        retry = [p for p in patterns if p.pattern_type == "frequent_retry"]
        assert len(retry) >= 1

    def test_no_patterns(self):
        log = PhaseAuditLogger()
        log.record_decision(phase="ANALYSIS", decision="a")
        log.record_decision(phase="ANALYSIS", decision="b")
        patterns = log.detect_patterns(min_frequency=0.9)
        routing = [p for p in patterns if p.pattern_type == "consistent_routing"]
        assert len(routing) == 0


# =============================================================================
# Session Timeline Tests
# =============================================================================


class TestSessionTimeline:
    """Test session timeline."""

    def test_timeline_order(self):
        log = PhaseAuditLogger()
        log.record_decision(session_id="s1", phase="ANALYSIS")
        log.record_decision(session_id="s1", phase="DEBATE")
        log.record_decision(session_id="s1", phase="EXECUTION")
        timeline = log.get_session_timeline("s1")
        assert len(timeline) == 3
        # Should be in chronological order (ascending timestamp)
        assert timeline[0].phase == "ANALYSIS"
        assert timeline[2].phase == "EXECUTION"

    def test_timeline_empty(self):
        log = PhaseAuditLogger()
        assert log.get_session_timeline("missing") == []


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded audit history."""

    def test_eviction(self):
        log = PhaseAuditLogger(max_audits=5)
        for i in range(10):
            log.record_decision(session_id=f"s{i}")
        assert log.size == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test audit statistics."""

    def test_initial_stats(self):
        log = PhaseAuditLogger()
        stats = log.get_stats()
        assert stats.total_audits == 0

    def test_stats_after_recording(self):
        log = PhaseAuditLogger()
        log.record_decision(session_id="s1", phase="ANALYSIS", agent_id="claude")
        log.record_decision(session_id="s2", phase="EXECUTION", agent_id="gemini")
        stats = log.get_stats()
        assert stats.total_audits == 2
        assert stats.unique_sessions == 2
        assert stats.unique_agents == 2
        assert stats.audits_by_phase.get("ANALYSIS") == 1

    def test_stats_to_dict(self):
        log = PhaseAuditLogger()
        d = log.get_stats().to_dict()
        assert "total_audits" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        log = PhaseAuditLogger()
        log.record_decision()
        log.record_decision()
        assert log.size == 2

    def test_clear(self):
        log = PhaseAuditLogger()
        log.record_decision()
        log.clear()
        assert log.size == 0

    def test_clear_resets_counter(self):
        log = PhaseAuditLogger()
        log.record_decision()
        log.clear()
        a = log.record_decision()
        assert a.audit_id == "pa_000001"

    def test_to_dict(self):
        log = PhaseAuditLogger()
        log.record_decision()
        d = log.to_dict()
        assert "stats" in d
        assert d["stats"]["total_audits"] == 1


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global phase audit logger."""

    def test_get(self):
        reset_phase_audit_logger()
        log = get_phase_audit_logger()
        assert isinstance(log, PhaseAuditLogger)

    def test_singleton(self):
        reset_phase_audit_logger()
        l1 = get_phase_audit_logger()
        l2 = get_phase_audit_logger()
        assert l1 is l2

    def test_reset(self):
        reset_phase_audit_logger()
        l1 = get_phase_audit_logger()
        reset_phase_audit_logger()
        l2 = get_phase_audit_logger()
        assert l1 is not l2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_hive_mind_package(self):
        from core.intelligence.hive_mind import (
            AuditPattern,
            AuditStats,
            DecisionAudit,
            PhaseAuditLogger,
            PhaseAuditReport,
            get_phase_audit_logger,
            reset_phase_audit_logger,
        )

        assert all(
            [
                PhaseAuditLogger,
                DecisionAudit,
                PhaseAuditReport,
                AuditPattern,
                AuditStats,
                get_phase_audit_logger,
                reset_phase_audit_logger,
            ]
        )

    def test_constants(self):
        assert MAX_AUDITS == 50000
        assert "ANALYSIS" in PHASES
        assert "EXECUTION" in PHASES
