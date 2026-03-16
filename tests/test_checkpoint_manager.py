"""
Tests for V12.4 Checkpoint Manager.

Validates:
- Checkpoint creation and IDs
- Checkpoint data (state, metadata, sequence)
- Listing checkpoints per session
- Getting latest checkpoint
- Restoring from checkpoint
- Rewinding to checkpoint
- Deleting checkpoints (single and session)
- Cleanup
- Max checkpoints per session
- Persistence (save/load)
- State management
- Global singleton
- Module exports
"""

import tempfile

from core.infrastructure.resilience.checkpoint_manager import (
    MAX_CHECKPOINTS_PER_SESSION,
    Checkpoint,
    CheckpointInfo,
    CheckpointManager,
    get_checkpoint_manager,
    reset_checkpoint_manager,
)

# =============================================================================
# Checkpoint Dataclass Tests
# =============================================================================


class TestCheckpoint:
    """Test Checkpoint dataclass."""

    def test_basic_creation(self):
        cp = Checkpoint(
            checkpoint_id="cp1",
            session_id="s1",
            label="phase_1",
            state={"key": "value"},
        )
        assert cp.checkpoint_id == "cp1"
        assert cp.session_id == "s1"
        assert cp.label == "phase_1"
        assert cp.state == {"key": "value"}

    def test_auto_timestamp(self):
        cp = Checkpoint(checkpoint_id="cp1", session_id="s1", label="test", state={})
        assert cp.created_at > 0

    def test_to_dict(self):
        cp = Checkpoint(
            checkpoint_id="cp1",
            session_id="s1",
            label="test",
            state={"a": 1},
            metadata={"phase": "analysis"},
            sequence=3,
        )
        d = cp.to_dict()
        assert d["checkpoint_id"] == "cp1"
        assert d["state"] == {"a": 1}
        assert d["metadata"] == {"phase": "analysis"}
        assert d["sequence"] == 3

    def test_from_dict(self):
        data = {
            "checkpoint_id": "cp1",
            "session_id": "s1",
            "label": "test",
            "state": {"x": 42},
            "metadata": {},
            "sequence": 2,
            "created_at": 100.0,
        }
        cp = Checkpoint.from_dict(data)
        assert cp.checkpoint_id == "cp1"
        assert cp.state == {"x": 42}
        assert cp.sequence == 2


# =============================================================================
# Create Tests
# =============================================================================


class TestCreate:
    """Test checkpoint creation."""

    def test_create_returns_id(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test", state={"key": "val"})
        assert cp_id
        assert len(cp_id) == 16

    def test_create_stores_state(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test", state={"data": [1, 2, 3]})
        cp = mgr.get(cp_id)
        assert cp is not None
        assert cp.state == {"data": [1, 2, 3]}

    def test_create_stores_metadata(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test", metadata={"phase": "analysis"})
        cp = mgr.get(cp_id)
        assert cp.metadata == {"phase": "analysis"}

    def test_create_increments_sequence(self):
        mgr = CheckpointManager(persist=False)
        id1 = mgr.create("s1", "first")
        id2 = mgr.create("s1", "second")
        id3 = mgr.create("s1", "third")
        assert mgr.get(id1).sequence == 0
        assert mgr.get(id2).sequence == 1
        assert mgr.get(id3).sequence == 2

    def test_create_unique_ids(self):
        mgr = CheckpointManager(persist=False)
        ids = [mgr.create("s1", f"cp_{i}") for i in range(10)]
        assert len(set(ids)) == 10

    def test_create_empty_state(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "empty")
        cp = mgr.get(cp_id)
        assert cp.state == {}

    def test_create_increments_count(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.checkpoint_count == 0
        mgr.create("s1", "a")
        mgr.create("s1", "b")
        assert mgr.checkpoint_count == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQuery:
    """Test checkpoint querying."""

    def test_get_existing(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test", state={"x": 1})
        cp = mgr.get(cp_id)
        assert cp is not None
        assert cp.label == "test"

    def test_get_nonexistent(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.get("missing") is None

    def test_exists(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test")
        assert mgr.exists(cp_id) is True
        assert mgr.exists("missing") is False

    def test_list_empty_session(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.list("nonexistent") == []

    def test_list_session(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "first", state={"a": 1})
        mgr.create("s1", "second", state={"b": 2})
        mgr.create("s2", "other")
        infos = mgr.list("s1")
        assert len(infos) == 2
        assert infos[0].label == "first"
        assert infos[1].label == "second"

    def test_list_returns_checkpoint_info(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "test", state={"key": "val"}, metadata={"p": 1})
        infos = mgr.list("s1")
        assert len(infos) == 1
        info = infos[0]
        assert isinstance(info, CheckpointInfo)
        assert info.label == "test"
        assert info.state_keys == ["key"]
        assert info.metadata == {"p": 1}

    def test_list_info_to_dict(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "test", state={"a": 1})
        info = mgr.list("s1")[0]
        d = info.to_dict()
        assert d["label"] == "test"
        assert d["state_keys"] == ["a"]

    def test_latest_empty(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.latest("missing") is None

    def test_latest(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "first")
        mgr.create("s1", "second")
        mgr.create("s1", "third")
        cp = mgr.latest("s1")
        assert cp is not None
        assert cp.label == "third"


# =============================================================================
# Restore Tests
# =============================================================================


class TestRestore:
    """Test checkpoint restoration."""

    def test_restore_success(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "saved", state={"phase": 3, "data": [1, 2]})
        result = mgr.restore(cp_id)
        assert result.success is True
        assert result.state == {"phase": 3, "data": [1, 2]}
        assert result.label == "saved"
        assert result.session_id == "s1"

    def test_restore_returns_copy(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test", state={"key": "original"})
        result = mgr.restore(cp_id)
        result.state["key"] = "modified"
        # Original should be unchanged
        cp = mgr.get(cp_id)
        assert cp.state["key"] == "original"

    def test_restore_not_found(self):
        mgr = CheckpointManager(persist=False)
        result = mgr.restore("missing")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_restore_to_dict(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test", state={"a": 1})
        result = mgr.restore(cp_id)
        d = result.to_dict()
        assert d["success"] is True
        assert d["state_keys"] == ["a"]


# =============================================================================
# Rewind Tests
# =============================================================================


class TestRewind:
    """Test checkpoint rewind."""

    def test_rewind_removes_later(self):
        mgr = CheckpointManager(persist=False)
        id1 = mgr.create("s1", "first")
        id2 = mgr.create("s1", "second")
        id3 = mgr.create("s1", "third")
        removed = mgr.rewind("s1", id1)
        assert removed == 2
        assert mgr.exists(id1) is True
        assert mgr.exists(id2) is False
        assert mgr.exists(id3) is False

    def test_rewind_last_removes_none(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "first")
        id2 = mgr.create("s1", "second")
        removed = mgr.rewind("s1", id2)
        assert removed == 0
        assert mgr.checkpoint_count == 2

    def test_rewind_nonexistent_checkpoint(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "first")
        removed = mgr.rewind("s1", "missing")
        assert removed == 0

    def test_rewind_wrong_session(self):
        mgr = CheckpointManager(persist=False)
        id1 = mgr.create("s1", "first")
        removed = mgr.rewind("s2", id1)
        assert removed == 0

    def test_rewind_resets_sequence(self):
        mgr = CheckpointManager(persist=False)
        id1 = mgr.create("s1", "first")
        mgr.create("s1", "second")
        mgr.create("s1", "third")
        mgr.rewind("s1", id1)
        # New checkpoint should get sequence 1
        id_new = mgr.create("s1", "new_second")
        cp = mgr.get(id_new)
        assert cp.sequence == 1


# =============================================================================
# Delete Tests
# =============================================================================


class TestDelete:
    """Test checkpoint deletion."""

    def test_delete_single(self):
        mgr = CheckpointManager(persist=False)
        cp_id = mgr.create("s1", "test")
        assert mgr.delete(cp_id) is True
        assert mgr.exists(cp_id) is False
        assert mgr.checkpoint_count == 0

    def test_delete_nonexistent(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.delete("missing") is False

    def test_delete_updates_session_list(self):
        mgr = CheckpointManager(persist=False)
        id1 = mgr.create("s1", "first")
        mgr.create("s1", "second")
        mgr.delete(id1)
        infos = mgr.list("s1")
        assert len(infos) == 1
        assert infos[0].label == "second"

    def test_delete_session(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "a")
        mgr.create("s1", "b")
        mgr.create("s2", "c")
        count = mgr.delete_session("s1")
        assert count == 2
        assert mgr.list("s1") == []
        assert len(mgr.list("s2")) == 1

    def test_delete_session_nonexistent(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.delete_session("missing") == 0


# =============================================================================
# Max Checkpoints Tests
# =============================================================================


class TestMaxCheckpoints:
    """Test max checkpoints per session."""

    def test_max_enforced(self):
        mgr = CheckpointManager(persist=False, max_per_session=3)
        ids = []
        for i in range(5):
            ids.append(mgr.create("s1", f"cp_{i}"))
        assert mgr.checkpoint_count == 3
        # Oldest should be removed
        assert mgr.exists(ids[0]) is False
        assert mgr.exists(ids[1]) is False
        assert mgr.exists(ids[2]) is True
        assert mgr.exists(ids[3]) is True
        assert mgr.exists(ids[4]) is True

    def test_max_per_session_independent(self):
        mgr = CheckpointManager(persist=False, max_per_session=2)
        mgr.create("s1", "a")
        mgr.create("s1", "b")
        mgr.create("s2", "c")
        mgr.create("s2", "d")
        assert mgr.checkpoint_count == 4  # 2 per session


# =============================================================================
# Cleanup Tests
# =============================================================================


class TestCleanup:
    """Test checkpoint cleanup."""

    def test_cleanup_all(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "a")
        mgr.create("s2", "b")
        count = mgr.cleanup()
        assert count == 2
        assert mgr.checkpoint_count == 0

    def test_cleanup_removes_from_session_list(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "a")
        mgr.cleanup()
        assert mgr.list("s1") == []


# =============================================================================
# Persistence Tests
# =============================================================================


class TestPersistence:
    """Test checkpoint persistence."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cp_dir = f"{tmpdir}/checkpoints"

            # Create and save
            mgr1 = CheckpointManager(checkpoint_dir=cp_dir)
            id1 = mgr1.create("s1", "phase_1", state={"findings": [1, 2]})
            mgr1.create("s1", "phase_2", state={"result": "ok"})

            # Load in new instance
            mgr2 = CheckpointManager(checkpoint_dir=cp_dir)
            assert mgr2.checkpoint_count == 2
            cp = mgr2.get(id1)
            assert cp is not None
            assert cp.state == {"findings": [1, 2]}
            assert cp.label == "phase_1"

    def test_persist_false_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cp_dir = f"{tmpdir}/checkpoints"
            mgr = CheckpointManager(checkpoint_dir=cp_dir, persist=False)
            mgr.create("s1", "test")
            from pathlib import Path

            assert not (Path(cp_dir) / "index.json").exists()


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_checkpoint_count(self):
        mgr = CheckpointManager(persist=False)
        assert mgr.checkpoint_count == 0
        mgr.create("s1", "a")
        assert mgr.checkpoint_count == 1

    def test_session_count(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "a")
        mgr.create("s2", "b")
        assert mgr.session_count == 2

    def test_get_sessions(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("beta", "a")
        mgr.create("alpha", "b")
        assert mgr.get_sessions() == ["alpha", "beta"]

    def test_clear(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "a")
        mgr.create("s2", "b")
        mgr.clear()
        assert mgr.checkpoint_count == 0
        assert mgr.session_count == 0

    def test_to_dict(self):
        mgr = CheckpointManager(persist=False)
        mgr.create("s1", "a")
        mgr.create("s1", "b")
        mgr.create("s2", "c")
        d = mgr.to_dict()
        assert d["checkpoint_count"] == 3
        assert d["session_count"] == 2
        assert d["sessions"]["s1"] == 2
        assert d["sessions"]["s2"] == 1


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global checkpoint manager."""

    def test_get_checkpoint_manager(self):
        reset_checkpoint_manager()
        mgr = get_checkpoint_manager()
        assert isinstance(mgr, CheckpointManager)

    def test_singleton(self):
        reset_checkpoint_manager()
        m1 = get_checkpoint_manager()
        m2 = get_checkpoint_manager()
        assert m1 is m2

    def test_reset(self):
        reset_checkpoint_manager()
        m1 = get_checkpoint_manager()
        reset_checkpoint_manager()
        m2 = get_checkpoint_manager()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_resilience_package(self):
        from core.infrastructure.resilience import (
            Checkpoint,
            CheckpointInfo,
            CheckpointManager,
            RestoreResult,
            get_checkpoint_manager,
            reset_checkpoint_manager,
        )

        assert all(
            [
                CheckpointManager,
                Checkpoint,
                CheckpointInfo,
                RestoreResult,
                get_checkpoint_manager,
                reset_checkpoint_manager,
            ]
        )

    def test_from_module(self):
        assert MAX_CHECKPOINTS_PER_SESSION == 50
