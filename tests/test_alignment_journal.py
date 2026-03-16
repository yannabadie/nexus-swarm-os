"""
Tests for V12.4 Governance Alignment Journal.

Validates:
- VerificationEntry to_dict
- ViolationEntry to_dict
- TrustScore to_dict
- JournalStats to_dict
- Recording verifications (pass/fail, trust updates)
- Recording violations (severity-weighted trust decay)
- Trust score computation
- Trust listing and untrusted agent detection
- Query methods (by agent, principle, severity)
- Agent history
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.security_pkg.governance.alignment_journal import (
    DEFAULT_TRUST_SCORE,
    MAX_ENTRIES,
    TRUST_DECAY_PER_VIOLATION,
    TRUST_RECOVERY_PER_PASS,
    AlignmentJournal,
    JournalStats,
    TrustScore,
    VerificationEntry,
    ViolationEntry,
    get_alignment_journal,
    reset_alignment_journal,
)

# =============================================================================
# VerificationEntry Tests
# =============================================================================


class TestVerificationEntry:
    """Test VerificationEntry dataclass."""

    def test_basic(self):
        v = VerificationEntry(agent_id="claude", principle="safety", passed=True)
        assert v.agent_id == "claude"
        assert v.passed is True

    def test_to_dict(self):
        v = VerificationEntry(
            agent_id="claude",
            principle="safety",
            passed=True,
            score=0.95,
            details="All checks passed",
        )
        d = v.to_dict()
        assert d["score"] == 0.95
        assert d["details"] == "All checks passed"


# =============================================================================
# ViolationEntry Tests
# =============================================================================


class TestViolationEntry:
    """Test ViolationEntry dataclass."""

    def test_basic(self):
        v = ViolationEntry(agent_id="rogue", principle="transparency")
        assert v.severity == "medium"

    def test_to_dict(self):
        v = ViolationEntry(
            agent_id="rogue",
            principle="transparency",
            severity="high",
            remediation="Blocked output",
        )
        d = v.to_dict()
        assert d["severity"] == "high"
        assert d["remediation"] == "Blocked output"


# =============================================================================
# TrustScore Tests
# =============================================================================


class TestTrustScore:
    """Test TrustScore dataclass."""

    def test_to_dict(self):
        t = TrustScore(
            agent_id="claude",
            score=0.95,
            total_verifications=10,
            total_violations=1,
            passes=9,
            fails=1,
        )
        d = t.to_dict()
        assert d["score"] == 0.95
        assert d["passes"] == 9


# =============================================================================
# JournalStats Tests
# =============================================================================


class TestJournalStats:
    """Test JournalStats dataclass."""

    def test_to_dict(self):
        s = JournalStats(
            total_verifications=20,
            total_violations=3,
            unique_agents=5,
            unique_principles=4,
            average_trust=0.85,
        )
        d = s.to_dict()
        assert d["total_verifications"] == 20
        assert d["average_trust"] == 0.85


# =============================================================================
# Verification Recording Tests
# =============================================================================


class TestVerificationRecording:
    """Test verification recording and trust updates."""

    def test_record_verification_pass(self):
        j = AlignmentJournal()
        v = j.record_verification("claude", principle="safety", passed=True, score=0.95)
        assert v.agent_id == "claude"
        assert v.passed is True
        assert j.verification_count == 1

    def test_record_verification_fail(self):
        j = AlignmentJournal()
        v = j.record_verification("rogue", principle="safety", passed=False)
        assert v.passed is False

    def test_trust_increases_on_pass(self):
        j = AlignmentJournal()
        # First lower trust, then verify recovery
        j.record_verification("claude", principle="safety", passed=False)
        lowered = j.get_trust_score("claude").score
        j.record_verification("claude", principle="safety", passed=True)
        ts = j.get_trust_score("claude")
        assert abs(ts.score - (lowered + TRUST_RECOVERY_PER_PASS)) < 0.001

    def test_trust_decreases_on_fail(self):
        j = AlignmentJournal()
        j.record_verification("rogue", principle="safety", passed=False)
        ts = j.get_trust_score("rogue")
        assert ts.score == DEFAULT_TRUST_SCORE - TRUST_DECAY_PER_VIOLATION

    def test_trust_capped_at_1(self):
        j = AlignmentJournal()
        # Many passes shouldn't exceed 1.0
        for _ in range(100):
            j.record_verification("claude", principle="safety", passed=True)
        ts = j.get_trust_score("claude")
        assert ts.score <= 1.0

    def test_trust_floored_at_0(self):
        j = AlignmentJournal()
        # Many fails shouldn't go below 0.0
        for _ in range(100):
            j.record_verification("rogue", principle="safety", passed=False)
        ts = j.get_trust_score("rogue")
        assert ts.score >= 0.0

    def test_score_clamped(self):
        j = AlignmentJournal()
        v = j.record_verification("claude", principle="safety", passed=True, score=1.5)
        assert v.score == 1.0

    def test_multiple_verifications(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("claude", principle="transparency", passed=True)
        j.record_verification("gemini", principle="safety", passed=False)
        assert j.verification_count == 3


# =============================================================================
# Violation Recording Tests
# =============================================================================


class TestViolationRecording:
    """Test violation recording with severity-weighted trust decay."""

    def test_record_violation(self):
        j = AlignmentJournal()
        v = j.record_violation("rogue", principle="safety", severity="high", remediation="Blocked")
        assert v.severity == "high"
        assert j.violation_count == 1

    def test_low_severity_decay(self):
        j = AlignmentJournal()
        j.record_violation("agent", principle="p", severity="low")
        ts = j.get_trust_score("agent")
        expected = DEFAULT_TRUST_SCORE - TRUST_DECAY_PER_VIOLATION * 0.5
        assert abs(ts.score - expected) < 0.001

    def test_medium_severity_decay(self):
        j = AlignmentJournal()
        j.record_violation("agent", principle="p", severity="medium")
        ts = j.get_trust_score("agent")
        expected = DEFAULT_TRUST_SCORE - TRUST_DECAY_PER_VIOLATION * 1.0
        assert abs(ts.score - expected) < 0.001

    def test_high_severity_decay(self):
        j = AlignmentJournal()
        j.record_violation("agent", principle="p", severity="high")
        ts = j.get_trust_score("agent")
        expected = DEFAULT_TRUST_SCORE - TRUST_DECAY_PER_VIOLATION * 2.0
        assert abs(ts.score - expected) < 0.001

    def test_critical_severity_decay(self):
        j = AlignmentJournal()
        j.record_violation("agent", principle="p", severity="critical")
        ts = j.get_trust_score("agent")
        expected = DEFAULT_TRUST_SCORE - TRUST_DECAY_PER_VIOLATION * 3.0
        assert abs(ts.score - expected) < 0.001

    def test_trust_floors_at_zero(self):
        j = AlignmentJournal()
        for _ in range(20):
            j.record_violation("rogue", principle="p", severity="critical")
        ts = j.get_trust_score("rogue")
        assert ts.score == 0.0


# =============================================================================
# Trust Score Tests
# =============================================================================


class TestTrustScoreComputation:
    """Test trust score computation."""

    def test_unknown_agent(self):
        j = AlignmentJournal()
        assert j.get_trust_score("unknown") is None

    def test_trust_score_fields(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("claude", principle="safety", passed=False)
        j.record_violation("claude", principle="transparency", severity="low")
        ts = j.get_trust_score("claude")
        assert ts.total_verifications == 2
        assert ts.total_violations == 1
        assert ts.passes == 1
        assert ts.fails == 1

    def test_all_trust_scores(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("gemini", principle="safety", passed=True)
        j.record_violation("rogue", principle="safety", severity="critical")
        scores = j.get_all_trust_scores()
        assert len(scores) == 3
        # Sorted ascending, rogue should be first (lowest trust)
        assert scores[0].agent_id == "rogue"

    def test_untrusted_agents(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        # Rogue gets multiple critical violations
        for _ in range(5):
            j.record_violation("rogue", principle="safety", severity="critical")
        untrusted = j.get_untrusted_agents(threshold=0.5)
        assert "rogue" in untrusted
        assert "claude" not in untrusted

    def test_untrusted_custom_threshold(self):
        j = AlignmentJournal()
        j.record_violation("agent", principle="p", severity="medium")
        # Trust = 1.0 - 0.1 = 0.9
        untrusted = j.get_untrusted_agents(threshold=0.95)
        assert "agent" in untrusted


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_verifications_all(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("gemini", principle="safety", passed=True)
        results = j.get_verifications()
        assert len(results) == 2

    def test_get_verifications_by_agent(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("gemini", principle="safety", passed=True)
        j.record_verification("claude", principle="transparency", passed=True)
        results = j.get_verifications(agent_id="claude")
        assert len(results) == 2

    def test_get_verifications_by_principle(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("claude", principle="transparency", passed=True)
        results = j.get_verifications(principle="safety")
        assert len(results) == 1

    def test_get_verifications_with_limit(self):
        j = AlignmentJournal()
        for _i in range(10):
            j.record_verification("claude", principle="safety", passed=True)
        results = j.get_verifications(limit=3)
        assert len(results) == 3

    def test_get_violations_all(self):
        j = AlignmentJournal()
        j.record_violation("rogue", principle="safety", severity="high")
        j.record_violation("rogue", principle="transparency", severity="low")
        results = j.get_violations()
        assert len(results) == 2

    def test_get_violations_by_agent(self):
        j = AlignmentJournal()
        j.record_violation("rogue", principle="safety", severity="high")
        j.record_violation("other", principle="safety", severity="low")
        results = j.get_violations(agent_id="rogue")
        assert len(results) == 1

    def test_get_violations_by_severity(self):
        j = AlignmentJournal()
        j.record_violation("rogue", principle="safety", severity="high")
        j.record_violation("rogue", principle="transparency", severity="low")
        results = j.get_violations(severity="high")
        assert len(results) == 1

    def test_get_violations_with_limit(self):
        j = AlignmentJournal()
        for _ in range(10):
            j.record_violation("rogue", principle="p", severity="high")
        results = j.get_violations(limit=3)
        assert len(results) == 3


# =============================================================================
# Agent History Tests
# =============================================================================


class TestAgentHistory:
    """Test agent history."""

    def test_basic_history(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("claude", principle="safety", passed=False)
        j.record_violation("claude", principle="transparency", severity="low")
        h = j.get_agent_history("claude")
        assert h["agent_id"] == "claude"
        assert h["verifications"] == 2
        assert h["violations"] == 1
        assert h["passes"] == 1
        assert h["fails"] == 1

    def test_unknown_agent_history(self):
        j = AlignmentJournal()
        h = j.get_agent_history("unknown")
        assert h["verifications"] == 0
        assert h["violations"] == 0
        assert h["trust_score"] == DEFAULT_TRUST_SCORE


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded history with eviction."""

    def test_verification_eviction(self):
        j = AlignmentJournal(max_entries=5)
        for i in range(10):
            j.record_verification(f"agent_{i}", principle="p", passed=True)
        assert j.verification_count == 5

    def test_violation_eviction(self):
        j = AlignmentJournal(max_entries=5)
        for i in range(10):
            j.record_violation(f"agent_{i}", principle="p", severity="low")
        assert j.violation_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test journal statistics."""

    def test_initial_stats(self):
        j = AlignmentJournal()
        stats = j.get_stats()
        assert stats.total_verifications == 0
        assert stats.total_violations == 0

    def test_stats_after_recording(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_verification("gemini", principle="transparency", passed=True)
        j.record_violation("rogue", principle="safety", severity="high")
        stats = j.get_stats()
        assert stats.total_verifications == 2
        assert stats.total_violations == 1
        assert stats.unique_agents == 3
        assert stats.unique_principles == 2
        assert stats.average_trust > 0

    def test_stats_to_dict(self):
        j = AlignmentJournal()
        d = j.get_stats().to_dict()
        assert "total_verifications" in d
        assert "average_trust" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_violation("rogue", principle="safety", severity="high")
        assert j.verification_count == 1
        assert j.violation_count == 1

    def test_clear(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        j.record_violation("rogue", principle="safety", severity="high")
        j.clear()
        assert j.verification_count == 0
        assert j.violation_count == 0
        assert j.get_trust_score("claude") is None

    def test_to_dict(self):
        j = AlignmentJournal()
        j.record_verification("claude", principle="safety", passed=True)
        d = j.to_dict()
        assert d["verification_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global alignment journal."""

    def test_get(self):
        reset_alignment_journal()
        j = get_alignment_journal()
        assert isinstance(j, AlignmentJournal)

    def test_singleton(self):
        reset_alignment_journal()
        j1 = get_alignment_journal()
        j2 = get_alignment_journal()
        assert j1 is j2

    def test_reset(self):
        reset_alignment_journal()
        j1 = get_alignment_journal()
        reset_alignment_journal()
        j2 = get_alignment_journal()
        assert j1 is not j2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_governance_package(self):
        from core.security_pkg.governance import (
            AlignmentJournal,
            JournalStats,
            TrustScore,
            VerificationEntry,
            ViolationEntry,
            get_alignment_journal,
            reset_alignment_journal,
        )

        assert all(
            [
                AlignmentJournal,
                VerificationEntry,
                ViolationEntry,
                TrustScore,
                JournalStats,
                get_alignment_journal,
                reset_alignment_journal,
            ]
        )

    def test_constants(self):
        from core.security_pkg.governance.alignment_journal import (
            DEFAULT_TRUST_SCORE,
            TRUST_DECAY_PER_VIOLATION,
            TRUST_RECOVERY_PER_PASS,
        )

        assert MAX_ENTRIES == 50000
        assert DEFAULT_TRUST_SCORE == 1.0
        assert TRUST_DECAY_PER_VIOLATION == 0.1
        assert TRUST_RECOVERY_PER_PASS == 0.02
