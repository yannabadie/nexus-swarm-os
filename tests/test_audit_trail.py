"""
Tests for V12.4 Context Audit Trail.

Validates:
- AuditEntry to_dict
- AuditStats to_dict
- Recording (activation, deactivation, violation)
- Queries (by tenant, user, action, context, time range)
- Violation tracking
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

import time

from core.infrastructure.context.audit_trail import (
    DEFAULT_RETENTION,
    MAX_ENTRIES,
    AuditEntry,
    AuditStats,
    ContextAuditTrail,
    get_audit_trail,
    reset_audit_trail,
)

# =============================================================================
# AuditEntry Tests
# =============================================================================


class TestAuditEntry:
    """Test AuditEntry dataclass."""

    def test_basic(self):
        e = AuditEntry(context_id="ctx1", action="activation", tenant_id="t1")
        assert e.context_id == "ctx1"
        assert e.timestamp > 0

    def test_to_dict(self):
        e = AuditEntry(context_id="ctx1", action="violation", reason="Unauthorized")
        d = e.to_dict()
        assert d["action"] == "violation"
        assert d["reason"] == "Unauthorized"

    def test_with_metadata(self):
        e = AuditEntry(context_id="ctx1", action="activation", metadata={"ip": "127.0.0.1"})
        assert e.metadata["ip"] == "127.0.0.1"


# =============================================================================
# AuditStats Tests
# =============================================================================


class TestAuditStats:
    """Test AuditStats dataclass."""

    def test_to_dict(self):
        s = AuditStats(
            total_entries=10,
            activations=5,
            deactivations=3,
            violations=2,
            unique_tenants=2,
            unique_users=3,
        )
        d = s.to_dict()
        assert d["violations"] == 2
        assert d["unique_tenants"] == 2


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test audit entry recording."""

    def test_record_activation(self):
        t = ContextAuditTrail()
        entry = t.record_activation("ctx1", tenant_id="t1", user_id="u1")
        assert entry.action == "activation"
        assert entry.tenant_id == "t1"
        assert t.size == 1

    def test_record_deactivation(self):
        t = ContextAuditTrail()
        entry = t.record_deactivation("ctx1", tenant_id="t1")
        assert entry.action == "deactivation"
        assert t.size == 1

    def test_record_violation(self):
        t = ContextAuditTrail()
        entry = t.record_violation("ctx1", tenant_id="t1", reason="Cross-tenant access")
        assert entry.action == "violation"
        assert entry.reason == "Cross-tenant access"

    def test_record_with_metadata(self):
        t = ContextAuditTrail()
        entry = t.record_activation("ctx1", metadata={"source": "api"})
        assert entry.metadata["source"] == "api"

    def test_record_with_workspace(self):
        t = ContextAuditTrail()
        entry = t.record_activation("ctx1", workspace_id="ws1")
        assert entry.workspace_id == "ws1"

    def test_multiple_records(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1", tenant_id="t1")
        t.record_activation("ctx2", tenant_id="t2")
        t.record_deactivation("ctx1")
        assert t.size == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_query_by_tenant(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1", tenant_id="t1")
        t.record_activation("ctx2", tenant_id="t2")
        t.record_activation("ctx3", tenant_id="t1")
        results = t.query_by_tenant("t1")
        assert len(results) == 2
        assert all(e.tenant_id == "t1" for e in results)

    def test_query_by_user(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1", user_id="alice")
        t.record_activation("ctx2", user_id="bob")
        results = t.query_by_user("alice")
        assert len(results) == 1

    def test_query_by_action(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1")
        t.record_deactivation("ctx1")
        t.record_violation("ctx2")
        results = t.query_by_action("violation")
        assert len(results) == 1

    def test_query_by_context(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1")
        t.record_deactivation("ctx1")
        t.record_activation("ctx2")
        results = t.query_by_context("ctx1")
        assert len(results) == 2

    def test_query_by_time_range(self):
        t = ContextAuditTrail()
        start = time.monotonic()
        t.record_activation("ctx1")
        t.record_activation("ctx2")
        end = time.monotonic()
        results = t.query_by_time_range(start, end)
        assert len(results) == 2

    def test_query_with_limit(self):
        t = ContextAuditTrail()
        for i in range(10):
            t.record_activation(f"ctx{i}")
        results = t.query_by_action("activation", limit=3)
        assert len(results) == 3

    def test_get_violations(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1")
        t.record_violation("ctx2", reason="Unauthorized")
        t.record_violation("ctx3", reason="Cross-tenant")
        violations = t.get_violations()
        assert len(violations) == 2

    def test_get_recent(self):
        t = ContextAuditTrail()
        for i in range(10):
            t.record_activation(f"ctx{i}")
        recent = t.get_recent(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].context_id == "ctx9"

    def test_query_returns_most_recent_first(self):
        t = ContextAuditTrail()
        t.record_activation("first", tenant_id="t1")
        t.record_activation("second", tenant_id="t1")
        results = t.query_by_tenant("t1")
        assert results[0].context_id == "second"


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded history with auto-eviction."""

    def test_eviction(self):
        t = ContextAuditTrail(max_entries=5)
        for i in range(10):
            t.record_activation(f"ctx{i}")
        assert t.size == 5

    def test_oldest_evicted(self):
        t = ContextAuditTrail(max_entries=3)
        t.record_activation("old1")
        t.record_activation("old2")
        t.record_activation("old3")
        t.record_activation("new1")
        results = t.get_recent(limit=10)
        context_ids = [e.context_id for e in results]
        assert "old1" not in context_ids
        assert "new1" in context_ids


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test audit trail statistics."""

    def test_initial_stats(self):
        t = ContextAuditTrail()
        stats = t.get_stats()
        assert stats.total_entries == 0
        assert stats.violations == 0

    def test_stats_after_recording(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1", tenant_id="t1", user_id="u1")
        t.record_deactivation("ctx1", tenant_id="t1", user_id="u2")
        t.record_violation("ctx2", tenant_id="t2", user_id="u1")
        stats = t.get_stats()
        assert stats.total_entries == 3
        assert stats.activations == 1
        assert stats.deactivations == 1
        assert stats.violations == 1
        assert stats.unique_tenants == 2
        assert stats.unique_users == 2

    def test_stats_to_dict(self):
        t = ContextAuditTrail()
        d = t.get_stats().to_dict()
        assert "total_entries" in d
        assert "violations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1")
        t.record_activation("ctx2")
        assert t.size == 2

    def test_clear(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1")
        t.record_violation("ctx2")
        t.clear()
        assert t.size == 0

    def test_to_dict(self):
        t = ContextAuditTrail()
        t.record_activation("ctx1")
        d = t.to_dict()
        assert d["size"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global audit trail."""

    def test_get(self):
        reset_audit_trail()
        trail = get_audit_trail()
        assert isinstance(trail, ContextAuditTrail)

    def test_singleton(self):
        reset_audit_trail()
        t1 = get_audit_trail()
        t2 = get_audit_trail()
        assert t1 is t2

    def test_reset(self):
        reset_audit_trail()
        t1 = get_audit_trail()
        reset_audit_trail()
        t2 = get_audit_trail()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_context_package(self):
        from core.infrastructure.context import (
            AuditEntry,
            AuditStats,
            ContextAuditTrail,
            get_audit_trail,
            reset_audit_trail,
        )

        assert all(
            [
                ContextAuditTrail,
                AuditEntry,
                AuditStats,
                get_audit_trail,
                reset_audit_trail,
            ]
        )

    def test_constants(self):
        assert MAX_ENTRIES == 50000
        assert DEFAULT_RETENTION == 86400.0
