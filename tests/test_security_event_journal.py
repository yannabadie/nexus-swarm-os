"""
Tests for V12.4 Security Event Journal.

Validates:
- SecurityEvent to_dict
- ThreatPattern to_dict
- SecurityJournalStats to_dict
- Event recording (generic, auth, access denied, threat)
- Auto-incrementing IDs
- Queries (by actor, type, severity, session, recent, critical)
- Pattern detection (repeated auth failure, privilege probe)
- Actor summary
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.security_pkg.security.security_event_journal import (
    EVENT_TYPES,
    MAX_EVENTS,
    SEVERITY_LEVELS,
    SecurityEvent,
    SecurityEventJournal,
    SecurityJournalStats,
    ThreatPattern,
    get_security_journal,
    reset_security_journal,
)

# =============================================================================
# SecurityEvent Tests
# =============================================================================


class TestSecurityEvent:
    """Test SecurityEvent dataclass."""

    def test_basic(self):
        e = SecurityEvent(event_id="se_000001", event_type="auth_attempt")
        assert e.event_id == "se_000001"
        assert e.timestamp > 0

    def test_to_dict(self):
        e = SecurityEvent(
            event_id="se_000001",
            event_type="auth_attempt",
            severity="medium",
            actor="rogue",
            resource="/kernel",
        )
        d = e.to_dict()
        assert d["event_type"] == "auth_attempt"
        assert d["actor"] == "rogue"


# =============================================================================
# ThreatPattern Tests
# =============================================================================


class TestThreatPattern:
    """Test ThreatPattern dataclass."""

    def test_to_dict(self):
        p = ThreatPattern(
            pattern_type="repeated_auth_failure",
            actor="rogue",
            event_count=5,
            severity="high",
            first_seen=100.0,
            last_seen=200.0,
        )
        d = p.to_dict()
        assert d["pattern_type"] == "repeated_auth_failure"
        assert d["event_count"] == 5


# =============================================================================
# SecurityJournalStats Tests
# =============================================================================


class TestSecurityJournalStats:
    """Test SecurityJournalStats dataclass."""

    def test_to_dict(self):
        s = SecurityJournalStats(
            total_events=20,
            events_by_type={"auth_attempt": 10},
            events_by_severity={"high": 5},
            unique_actors=3,
            critical_events=2,
        )
        d = s.to_dict()
        assert d["total_events"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test event recording methods."""

    def test_record_event(self):
        j = SecurityEventJournal()
        e = j.record_event("auth_attempt", actor="claude", result="allowed")
        assert e.event_type == "auth_attempt"
        assert e.actor == "claude"
        assert j.size == 1

    def test_auto_incrementing_id(self):
        j = SecurityEventJournal()
        e1 = j.record_event("auth_attempt")
        e2 = j.record_event("auth_attempt")
        assert e1.event_id == "se_000001"
        assert e2.event_id == "se_000002"

    def test_record_auth_attempt_success(self):
        j = SecurityEventJournal()
        e = j.record_auth_attempt(actor="claude", success=True)
        assert e.event_type == "auth_attempt"
        assert e.result == "allowed"
        assert e.severity == "info"

    def test_record_auth_attempt_failure(self):
        j = SecurityEventJournal()
        e = j.record_auth_attempt(actor="rogue", success=False)
        assert e.result == "blocked"
        assert e.severity != "info"  # higher severity for failure

    def test_record_access_denied(self):
        j = SecurityEventJournal()
        e = j.record_access_denied(actor="rogue", resource="/kernel")
        assert e.event_type == "access_denied"
        assert e.severity == "high"
        assert e.resource == "/kernel"

    def test_record_threat(self):
        j = SecurityEventJournal()
        e = j.record_threat(actor="rogue", threat_type="input_threat", severity="critical")
        assert e.event_type == "input_threat"
        assert e.severity == "critical"

    def test_multiple_events(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", actor="claude")
        j.record_event("access_denied", actor="rogue")
        j.record_event("policy_violation", actor="agent_x")
        assert j.size == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_query_by_actor(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", actor="claude")
        j.record_event("auth_attempt", actor="rogue")
        j.record_event("access_denied", actor="claude")
        results = j.query_by_actor("claude")
        assert len(results) == 2

    def test_query_by_type(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt")
        j.record_event("access_denied")
        j.record_event("auth_attempt")
        results = j.query_by_type("auth_attempt")
        assert len(results) == 2

    def test_query_by_severity(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", severity="info")
        j.record_event("auth_attempt", severity="high")
        j.record_event("auth_attempt", severity="critical")
        results = j.query_by_severity("high")
        assert len(results) == 1

    def test_query_by_session(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", session_id="s1")
        j.record_event("auth_attempt", session_id="s2")
        j.record_event("auth_attempt", session_id="s1")
        results = j.query_by_session("s1")
        assert len(results) == 2

    def test_get_recent(self):
        j = SecurityEventJournal()
        for i in range(10):
            j.record_event("auth_attempt", actor=f"agent_{i}")
        recent = j.get_recent(limit=3)
        assert len(recent) == 3

    def test_get_critical_events(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", severity="info")
        j.record_event("policy_violation", severity="critical")
        j.record_event("input_threat", severity="critical")
        critical = j.get_critical_events()
        assert len(critical) == 2

    def test_query_with_limit(self):
        j = SecurityEventJournal()
        for _ in range(10):
            j.record_event("auth_attempt", actor="claude")
        results = j.query_by_actor("claude", limit=3)
        assert len(results) == 3


# =============================================================================
# Pattern Detection Tests
# =============================================================================


class TestPatternDetection:
    """Test threat pattern detection."""

    def test_repeated_auth_failure(self):
        j = SecurityEventJournal()
        for _ in range(5):
            j.record_auth_attempt(actor="rogue", success=False)
        patterns = j.detect_patterns(actor="rogue")
        auth_patterns = [p for p in patterns if p.pattern_type == "repeated_auth_failure"]
        assert len(auth_patterns) >= 1
        assert auth_patterns[0].event_count >= 3

    def test_privilege_probe(self):
        j = SecurityEventJournal()
        for _ in range(5):
            j.record_access_denied(actor="rogue", resource="/admin")
        patterns = j.detect_patterns(actor="rogue")
        probe_patterns = [p for p in patterns if p.pattern_type == "privilege_probe"]
        assert len(probe_patterns) >= 1

    def test_no_patterns(self):
        j = SecurityEventJournal()
        j.record_auth_attempt(actor="claude", success=True)
        patterns = j.detect_patterns(actor="claude")
        assert len(patterns) == 0

    def test_detect_patterns_empty(self):
        j = SecurityEventJournal()
        patterns = j.detect_patterns()
        assert patterns == []


# =============================================================================
# Actor Summary Tests
# =============================================================================


class TestActorSummary:
    """Test actor summary."""

    def test_basic_summary(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", actor="claude", severity="info")
        j.record_event("access_denied", actor="claude", severity="high")
        summary = j.get_actor_summary("claude")
        assert summary["total_events"] == 2
        assert "auth_attempt" in summary["events_by_type"]

    def test_unknown_actor(self):
        j = SecurityEventJournal()
        summary = j.get_actor_summary("unknown")
        assert summary["total_events"] == 0


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded event history."""

    def test_eviction(self):
        j = SecurityEventJournal(max_events=5)
        for i in range(10):
            j.record_event("auth_attempt", actor=f"agent_{i}")
        assert j.size == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test journal statistics."""

    def test_initial_stats(self):
        j = SecurityEventJournal()
        stats = j.get_stats()
        assert stats.total_events == 0

    def test_stats_after_recording(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt", actor="claude", severity="info")
        j.record_event("access_denied", actor="rogue", severity="high")
        j.record_event("policy_violation", severity="critical")
        stats = j.get_stats()
        assert stats.total_events == 3
        assert stats.unique_actors >= 2
        assert stats.critical_events == 1

    def test_stats_to_dict(self):
        j = SecurityEventJournal()
        d = j.get_stats().to_dict()
        assert "total_events" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt")
        j.record_event("auth_attempt")
        assert j.size == 2

    def test_clear(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt")
        j.clear()
        assert j.size == 0

    def test_clear_resets_counter(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt")
        j.clear()
        e = j.record_event("auth_attempt")
        assert e.event_id == "se_000001"

    def test_to_dict(self):
        j = SecurityEventJournal()
        j.record_event("auth_attempt")
        d = j.to_dict()
        assert d["size"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global security journal."""

    def test_get(self):
        reset_security_journal()
        j = get_security_journal()
        assert isinstance(j, SecurityEventJournal)

    def test_singleton(self):
        reset_security_journal()
        j1 = get_security_journal()
        j2 = get_security_journal()
        assert j1 is j2

    def test_reset(self):
        reset_security_journal()
        j1 = get_security_journal()
        reset_security_journal()
        j2 = get_security_journal()
        assert j1 is not j2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_security_package(self):
        from core.security_pkg.security import (
            SecurityEvent,
            SecurityEventJournal,
            SecurityJournalStats,
            ThreatPattern,
            get_security_journal,
            reset_security_journal,
        )

        assert all(
            [
                SecurityEventJournal,
                SecurityEvent,
                ThreatPattern,
                SecurityJournalStats,
                get_security_journal,
                reset_security_journal,
            ]
        )

    def test_constants(self):
        assert MAX_EVENTS == 100000
        assert "critical" in SEVERITY_LEVELS
        assert "auth_attempt" in EVENT_TYPES
