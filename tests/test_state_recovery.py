"""
Tests for V12.4 State Recovery Manager.

Validates:
- StateSnapshot creation and to_dict
- SnapshotReason enum values
- RecoveryResult creation and to_dict
- RecoveryStats and success_rate
- Capture (basic, reasons, labels, metadata)
- Savepoint convenience method
- Query (get, latest, list, find_savepoint)
- Recovery (latest, by ID, by label, wrong session)
- Rollback (basic, insufficient snapshots)
- Max snapshots eviction
- Cleanup (delete, session, old)
- Statistics tracking
- State management
- Global singleton
- Module exports
"""

import time

from core.infrastructure.session.state_recovery import (
    RecoveryResult,
    RecoveryStats,
    SnapshotReason,
    StateRecoveryManager,
    StateSnapshot,
    get_recovery_manager,
    reset_recovery_manager,
)

# =============================================================================
# SnapshotReason Tests
# =============================================================================


class TestSnapshotReason:
    """Test SnapshotReason enum."""

    def test_manual(self):
        assert SnapshotReason.MANUAL.value == "manual"

    def test_auto(self):
        assert SnapshotReason.AUTO.value == "auto"

    def test_pre_execution(self):
        assert SnapshotReason.PRE_EXECUTION.value == "pre_execution"

    def test_post_execution(self):
        assert SnapshotReason.POST_EXECUTION.value == "post_execution"

    def test_error(self):
        assert SnapshotReason.ERROR.value == "error"

    def test_savepoint(self):
        assert SnapshotReason.SAVEPOINT.value == "savepoint"

    def test_all_values(self):
        assert len(SnapshotReason) == 6


# =============================================================================
# StateSnapshot Tests
# =============================================================================


class TestStateSnapshot:
    """Test StateSnapshot dataclass."""

    def test_basic_creation(self):
        snap = StateSnapshot(
            snapshot_id="snap1",
            session_id="sess1",
            state={"phase": "EXECUTING"},
        )
        assert snap.snapshot_id == "snap1"
        assert snap.session_id == "sess1"
        assert snap.state == {"phase": "EXECUTING"}

    def test_auto_timestamp(self):
        snap = StateSnapshot(
            snapshot_id="snap1",
            session_id="sess1",
            state={},
        )
        assert snap.timestamp > 0

    def test_defaults(self):
        snap = StateSnapshot(
            snapshot_id="snap1",
            session_id="sess1",
            state={},
        )
        assert snap.reason == SnapshotReason.MANUAL
        assert snap.label == ""
        assert snap.metadata == {}

    def test_to_dict(self):
        snap = StateSnapshot(
            snapshot_id="snap1",
            session_id="sess1",
            state={"a": 1, "b": 2},
            reason=SnapshotReason.SAVEPOINT,
            label="before_deploy",
        )
        d = snap.to_dict()
        assert d["snapshot_id"] == "snap1"
        assert d["reason"] == "savepoint"
        assert d["label"] == "before_deploy"
        assert "a" in d["state_keys"]


# =============================================================================
# RecoveryResult Tests
# =============================================================================


class TestRecoveryResult:
    """Test RecoveryResult dataclass."""

    def test_success(self):
        r = RecoveryResult(success=True, snapshot_id="snap1", state={"k": "v"})
        assert r.success is True
        assert r.state == {"k": "v"}

    def test_failure(self):
        r = RecoveryResult(success=False, reason="No snapshot found")
        assert r.success is False
        assert r.state == {}

    def test_to_dict(self):
        r = RecoveryResult(
            success=True,
            snapshot_id="s1",
            session_id="sess1",
            state={"phase": "IDLE"},
            reason="recovered",
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["snapshot_id"] == "s1"
        assert "phase" in d["state_keys"]


# =============================================================================
# RecoveryStats Tests
# =============================================================================


class TestRecoveryStats:
    """Test RecoveryStats dataclass."""

    def test_basic(self):
        stats = RecoveryStats(
            total_snapshots=10,
            total_recoveries=5,
            successful_recoveries=4,
            failed_recoveries=1,
            sessions_tracked=3,
        )
        assert stats.success_rate == 0.8

    def test_zero_recoveries(self):
        stats = RecoveryStats(
            total_snapshots=5,
            total_recoveries=0,
            successful_recoveries=0,
            failed_recoveries=0,
            sessions_tracked=2,
        )
        assert stats.success_rate == 0.0

    def test_to_dict(self):
        stats = RecoveryStats(
            total_snapshots=1,
            total_recoveries=1,
            successful_recoveries=1,
            failed_recoveries=0,
            sessions_tracked=1,
        )
        d = stats.to_dict()
        assert d["total_snapshots"] == 1
        assert d["success_rate"] == 1.0


# =============================================================================
# Capture Tests
# =============================================================================


class TestCapture:
    """Test state capture."""

    def test_capture_basic(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {"phase": "IDLE"})
        assert len(sid) == 16
        assert mgr.snapshot_count == 1

    def test_capture_with_reason(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {"phase": "EXEC"}, reason=SnapshotReason.PRE_EXECUTION)
        snap = mgr.get_snapshot(sid)
        assert snap.reason == SnapshotReason.PRE_EXECUTION

    def test_capture_with_label(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {}, label="before_deploy")
        snap = mgr.get_snapshot(sid)
        assert snap.label == "before_deploy"

    def test_capture_with_metadata(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {}, metadata={"agent": "claude"})
        snap = mgr.get_snapshot(sid)
        assert snap.metadata == {"agent": "claude"}

    def test_capture_deep_copies(self):
        mgr = StateRecoveryManager()
        state = {"data": [1, 2, 3]}
        sid = mgr.capture("sess1", state)
        state["data"].append(4)  # Modify original
        snap = mgr.get_snapshot(sid)
        assert snap.state["data"] == [1, 2, 3]  # Snapshot unaffected

    def test_capture_multiple_sessions(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"a": 1})
        mgr.capture("sess2", {"b": 2})
        assert mgr.session_count == 2

    def test_savepoint(self):
        mgr = StateRecoveryManager()
        sid = mgr.savepoint("sess1", {"step": 5}, "checkpoint_alpha")
        snap = mgr.get_snapshot(sid)
        assert snap.reason == SnapshotReason.SAVEPOINT
        assert snap.label == "checkpoint_alpha"


# =============================================================================
# Query Tests
# =============================================================================


class TestQuery:
    """Test snapshot queries."""

    def test_get_snapshot(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {"k": "v"})
        snap = mgr.get_snapshot(sid)
        assert snap is not None
        assert snap.state == {"k": "v"}

    def test_get_snapshot_not_found(self):
        mgr = StateRecoveryManager()
        assert mgr.get_snapshot("missing") is None

    def test_latest(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        mgr.capture("sess1", {"step": 3})
        snap = mgr.latest("sess1")
        assert snap.state["step"] == 3

    def test_latest_empty(self):
        mgr = StateRecoveryManager()
        assert mgr.latest("sess1") is None

    def test_list_snapshots(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"a": 1})
        mgr.capture("sess1", {"b": 2})
        mgr.capture("sess2", {"c": 3})
        snaps = mgr.list_snapshots("sess1")
        assert len(snaps) == 2

    def test_list_snapshots_filtered(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {}, reason=SnapshotReason.AUTO)
        mgr.capture("sess1", {}, reason=SnapshotReason.ERROR)
        mgr.capture("sess1", {}, reason=SnapshotReason.AUTO)
        snaps = mgr.list_snapshots("sess1", reason=SnapshotReason.AUTO)
        assert len(snaps) == 2

    def test_find_savepoint(self):
        mgr = StateRecoveryManager()
        mgr.savepoint("sess1", {"v": 1}, "alpha")
        mgr.savepoint("sess1", {"v": 2}, "beta")
        snap = mgr.find_savepoint("sess1", "alpha")
        assert snap is not None
        assert snap.state["v"] == 1

    def test_find_savepoint_not_found(self):
        mgr = StateRecoveryManager()
        assert mgr.find_savepoint("sess1", "missing") is None

    def test_find_savepoint_returns_latest(self):
        mgr = StateRecoveryManager()
        mgr.savepoint("sess1", {"v": 1}, "deploy")
        mgr.savepoint("sess1", {"v": 2}, "deploy")
        snap = mgr.find_savepoint("sess1", "deploy")
        assert snap.state["v"] == 2


# =============================================================================
# Recovery Tests
# =============================================================================


class TestRecovery:
    """Test state recovery."""

    def test_recover_latest(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        result = mgr.recover("sess1")
        assert result.success is True
        assert result.state["step"] == 2

    def test_recover_by_id(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        result = mgr.recover("sess1", snapshot_id=sid)
        assert result.success is True
        assert result.state["step"] == 1

    def test_recover_by_label(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.savepoint("sess1", {"step": 2}, "checkpoint")
        mgr.capture("sess1", {"step": 3})
        result = mgr.recover("sess1", label="checkpoint")
        assert result.success is True
        assert result.state["step"] == 2

    def test_recover_no_snapshots(self):
        mgr = StateRecoveryManager()
        result = mgr.recover("sess1")
        assert result.success is False
        assert "No snapshot found" in result.reason

    def test_recover_wrong_session(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {"data": 1})
        result = mgr.recover("sess2", snapshot_id=sid)
        assert result.success is False

    def test_recover_deep_copies(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"items": [1, 2]})
        r1 = mgr.recover("sess1")
        r2 = mgr.recover("sess1")
        r1.state["items"].append(3)
        assert r2.state["items"] == [1, 2]

    def test_recover_to_dict(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"a": 1})
        result = mgr.recover("sess1")
        d = result.to_dict()
        assert d["success"] is True
        assert "a" in d["state_keys"]


# =============================================================================
# Rollback Tests
# =============================================================================


class TestRollback:
    """Test rollback functionality."""

    def test_rollback_one(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        mgr.capture("sess1", {"step": 3})
        result = mgr.rollback("sess1", steps=1)
        assert result.success is True
        assert result.state["step"] == 2

    def test_rollback_two(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        mgr.capture("sess1", {"step": 3})
        result = mgr.rollback("sess1", steps=2)
        assert result.success is True
        assert result.state["step"] == 1

    def test_rollback_insufficient_uses_oldest(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        result = mgr.rollback("sess1", steps=5)
        assert result.success is True
        assert result.state["step"] == 1

    def test_rollback_empty_session(self):
        mgr = StateRecoveryManager()
        result = mgr.rollback("sess1")
        assert result.success is False

    def test_rollback_reason_message(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        result = mgr.rollback("sess1", steps=1)
        assert "1 step" in result.reason


# =============================================================================
# Max Snapshots Tests
# =============================================================================


class TestMaxSnapshots:
    """Test max snapshot eviction."""

    def test_eviction(self):
        mgr = StateRecoveryManager(max_snapshots=3)
        mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        mgr.capture("sess1", {"step": 3})
        mgr.capture("sess1", {"step": 4})  # Should evict step 1
        assert mgr.session_snapshot_count("sess1") == 3
        snap = mgr.list_snapshots("sess1")[0]
        assert snap.state["step"] == 2  # Oldest remaining

    def test_eviction_removes_from_index(self):
        mgr = StateRecoveryManager(max_snapshots=2)
        sid1 = mgr.capture("sess1", {"step": 1})
        mgr.capture("sess1", {"step": 2})
        mgr.capture("sess1", {"step": 3})
        assert mgr.get_snapshot(sid1) is None


# =============================================================================
# Cleanup Tests
# =============================================================================


class TestCleanup:
    """Test cleanup operations."""

    def test_delete_snapshot(self):
        mgr = StateRecoveryManager()
        sid = mgr.capture("sess1", {"k": "v"})
        assert mgr.delete_snapshot(sid) is True
        assert mgr.snapshot_count == 0

    def test_delete_snapshot_not_found(self):
        mgr = StateRecoveryManager()
        assert mgr.delete_snapshot("missing") is False

    def test_delete_session(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"a": 1})
        mgr.capture("sess1", {"b": 2})
        mgr.capture("sess2", {"c": 3})
        count = mgr.delete_session("sess1")
        assert count == 2
        assert mgr.session_count == 1

    def test_delete_session_empty(self):
        mgr = StateRecoveryManager()
        assert mgr.delete_session("missing") == 0

    def test_cleanup_old(self):
        mgr = StateRecoveryManager()
        # Create snapshots with old timestamps
        sid = mgr.capture("sess1", {"old": True})
        snap = mgr.get_snapshot(sid)
        snap.timestamp = time.monotonic() - 100  # 100 seconds ago
        mgr.capture("sess1", {"new": True})
        removed = mgr.cleanup_old(max_age_seconds=50)
        assert removed == 1
        assert mgr.snapshot_count == 1


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test recovery statistics."""

    def test_initial_stats(self):
        mgr = StateRecoveryManager()
        stats = mgr.get_stats()
        assert stats.total_snapshots == 0
        assert stats.total_recoveries == 0

    def test_stats_after_operations(self):
        mgr = StateRecoveryManager()
        mgr.capture("sess1", {"k": "v"})
        mgr.recover("sess1")
        mgr.recover("missing")  # Failed
        stats = mgr.get_stats()
        assert stats.total_snapshots == 1
        assert stats.total_recoveries == 2
        assert stats.successful_recoveries == 1
        assert stats.failed_recoveries == 1
        assert stats.success_rate == 0.5

    def test_stats_to_dict(self):
        mgr = StateRecoveryManager()
        stats = mgr.get_stats()
        d = stats.to_dict()
        assert "total_snapshots" in d
        assert "success_rate" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_session_count(self):
        mgr = StateRecoveryManager()
        mgr.capture("s1", {})
        mgr.capture("s2", {})
        assert mgr.session_count == 2

    def test_snapshot_count(self):
        mgr = StateRecoveryManager()
        mgr.capture("s1", {})
        mgr.capture("s1", {})
        mgr.capture("s2", {})
        assert mgr.snapshot_count == 3

    def test_session_snapshot_count(self):
        mgr = StateRecoveryManager()
        mgr.capture("s1", {})
        mgr.capture("s1", {})
        assert mgr.session_snapshot_count("s1") == 2
        assert mgr.session_snapshot_count("s2") == 0

    def test_clear(self):
        mgr = StateRecoveryManager()
        mgr.capture("s1", {})
        mgr.recover("s1")
        mgr.clear()
        assert mgr.snapshot_count == 0
        assert mgr.session_count == 0
        stats = mgr.get_stats()
        assert stats.total_recoveries == 0

    def test_to_dict(self):
        mgr = StateRecoveryManager()
        mgr.capture("s1", {})
        d = mgr.to_dict()
        assert d["session_count"] == 1
        assert d["snapshot_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global recovery manager."""

    def test_get_recovery_manager(self):
        reset_recovery_manager()
        mgr = get_recovery_manager()
        assert isinstance(mgr, StateRecoveryManager)

    def test_singleton(self):
        reset_recovery_manager()
        m1 = get_recovery_manager()
        m2 = get_recovery_manager()
        assert m1 is m2

    def test_reset(self):
        reset_recovery_manager()
        m1 = get_recovery_manager()
        reset_recovery_manager()
        m2 = get_recovery_manager()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_session_package(self):
        from core.infrastructure.session import (
            RecoveryResult,
            RecoveryStats,
            SnapshotReason,
            StateRecoveryManager,
            StateSnapshot,
            get_recovery_manager,
            reset_recovery_manager,
        )

        assert all(
            [
                StateRecoveryManager,
                StateSnapshot,
                RecoveryResult,
                RecoveryStats,
                SnapshotReason,
                get_recovery_manager,
                reset_recovery_manager,
            ]
        )

    def test_from_module(self):
        from core.infrastructure.session.state_recovery import (
            MAX_SNAPSHOTS_PER_SESSION,
        )

        assert MAX_SNAPSHOTS_PER_SESSION == 100
