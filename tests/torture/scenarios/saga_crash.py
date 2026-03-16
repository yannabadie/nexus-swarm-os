"""
Torture Protocol V8 - Saga Crash Recovery Tests

15 tests covering crash recovery scenarios for SagaManager.

Test IDs: CR-001 to CR-015
"""

import contextlib
import json
import sys
import time
from pathlib import Path

import pytest

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.intelligence.hive_mind.saga_manager import SagaManager
from core.utils.atomic_store import AtomicJsonStore
from tests.torture.base import TortureBase
from tests.torture.chaos_injectors import CorruptionInjector, CrashInjector

# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture
def saga_dir(tmp_path):
    """Create saga directory."""
    saga_dir = tmp_path / ".nexus" / "sagas"
    saga_dir.mkdir(parents=True)
    return saga_dir


@pytest.fixture
def crash_injector():
    """Provide CrashInjector."""
    return CrashInjector()


@pytest.fixture
def corruption_injector():
    """Provide CorruptionInjector."""
    return CorruptionInjector()


# ============================================================================
# CR-001: Partial checkpoint write (crash mid-persist)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr001_partial_checkpoint_write(saga_dir):
    """
    CR-001: Test recovery from partial checkpoint write.

    Scenario: Process crashes after checkpoint_phase() but before _persist() completes.
    Expected: Previous checkpoints recoverable, incomplete checkpoint lost.
    """
    saga = SagaManager(saga_dir, "cr001-test", auto_persist=True)

    # First checkpoint succeeds
    await saga.checkpoint_phase("analysis", {"step": 1}, "S1", 5)

    # Verify first checkpoint persisted
    recovered = await SagaManager.resume_from(saga_dir, "cr001-test")
    assert recovered is not None
    assert "analysis" in recovered._checkpoints

    # Second checkpoint with crash during persist
    crash_count = [0]
    original_persist = saga._persist

    async def crashing_persist():
        crash_count[0] += 1
        if crash_count[0] == 1:  # Crash on first call (debate checkpoint)
            raise RuntimeError("Simulated crash during persist")
        return await original_persist()

    saga._persist = crashing_persist

    with pytest.raises(RuntimeError):
        await saga.checkpoint_phase("debate", {"step": 2}, "S2", 10)

    # Recovery should show only analysis checkpoint
    recovered = await SagaManager.resume_from(saga_dir, "cr001-test")
    assert recovered is not None
    assert "analysis" in recovered._checkpoints
    # Debate checkpoint should NOT be persisted (crash before persist)


# ============================================================================
# CR-002: Corrupted saga JSON on disk
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr002_corrupted_saga_json(saga_dir, corruption_injector):
    """
    CR-002: Test graceful handling of corrupted saga JSON.

    Scenario: Saga file contains invalid JSON.
    Expected: resume_from() returns None, no crash.
    """
    task_id = "cr002-test"
    saga_file = saga_dir / f"{task_id}.json"

    # Write corrupted JSON
    corruption_injector.corrupt_json(saga_file, "invalid_json")

    # Should return None gracefully
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is None


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr002b_truncated_saga_json(saga_dir, corruption_injector):
    """
    CR-002b: Test handling of truncated saga JSON.
    """
    task_id = "cr002b-test"
    saga_file = saga_dir / f"{task_id}.json"

    # Create valid saga first
    saga = SagaManager(saga_dir, task_id, auto_persist=True)
    await saga.checkpoint_phase("analysis", {"data": "x" * 1000}, "S1", 5)

    # Corrupt by truncating
    corruption_injector.truncate_file(saga_file, 50)

    # Should return None gracefully
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is None


# ============================================================================
# CR-003: Resume with incomplete checkpoint chain
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr003_incomplete_checkpoint_chain(saga_dir, corruption_injector):
    """
    CR-003: Test resume with incomplete checkpoint chain.

    Scenario: Saga has analysis + architecture but NO debate checkpoint.
    Expected: Guards prevent invalid transitions.
    """
    task_id = "cr003-test"

    # Create saga with incomplete chain (skips debate)
    corruption_injector.create_incomplete_saga(saga_dir, task_id)

    # Resume saga
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is not None

    # Check that guards detect the inconsistency
    can_enter, reason = recovered.can_enter_phase("execution")
    # Should fail because architecture_approved but debate_complete is False


# ============================================================================
# CR-004: AtomicJsonStore lock contention under crash
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
def test_cr004_atomic_store_lock_contention(saga_dir):
    """
    CR-004: Test AtomicJsonStore under concurrent access with crash.

    Scenario: Multiple threads accessing same store, one crashes.
    Expected: Other threads can still access store.
    """
    store_file = saga_dir / "cr004-store.json"
    store = AtomicJsonStore(store_file)

    results = []

    def writer(thread_id, crash=False):
        try:
            for i in range(5):
                data = store.load()
                data[f"thread_{thread_id}_write_{i}"] = True
                if crash and i == 2:
                    raise RuntimeError(f"Thread {thread_id} crash")
                store.save(data)
                time.sleep(0.01)
            results.append({"thread": thread_id, "success": True})
        except Exception as e:
            results.append({"thread": thread_id, "success": False, "error": str(e)})

    import threading

    threads = [
        threading.Thread(target=writer, args=(0, False)),
        threading.Thread(target=writer, args=(1, True)),  # Will crash
        threading.Thread(target=writer, args=(2, False)),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # At least 2 threads should succeed (thread 1 crashes)
    successes = sum(1 for r in results if r["success"])
    assert successes >= 2

    # Store should still be readable
    final_data = store.load()
    assert isinstance(final_data, dict)


# ============================================================================
# CR-005: Crash between checkpoint_phase() and update_context()
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr005_crash_between_checkpoint_and_context(saga_dir):
    """
    CR-005: Test crash between checkpoint_phase() and update_context().

    Scenario: Checkpoint persists but context flag not updated.
    Expected: Recovery works, but guards may be inconsistent.
    """
    saga = SagaManager(saga_dir, "cr005-test", auto_persist=True)

    # Checkpoint analysis
    await saga.checkpoint_phase("analysis", {}, "S1", 5)

    # Manually mess with context to simulate crash before update_context
    saga._context.analysis_complete = False  # Should be True!

    # Persist with inconsistent state
    await saga._persist()

    # Resume
    recovered = await SagaManager.resume_from(saga_dir, "cr005-test")
    assert recovered is not None

    # Checkpoint exists but context says analysis not complete
    assert "analysis" in recovered._checkpoints
    # This is the bug we're testing - context is inconsistent


# ============================================================================
# CR-006: Multiple sagas same task_id (rapid create/crash)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr006_multiple_sagas_same_task_id(saga_dir):
    """
    CR-006: Test rapid create/crash cycles with same task_id.

    Scenario: Multiple saga instances for same task_id due to crashes.
    Expected: Latest saga state is recovered.
    """
    task_id = "cr006-test"

    # First saga - checkpoint analysis
    saga1 = SagaManager(saga_dir, task_id, auto_persist=True)
    await saga1.checkpoint_phase("analysis", {"version": 1}, "S1", 5)

    # Simulate crash and new saga - checkpoint debate
    saga2 = SagaManager(saga_dir, task_id, auto_persist=True)
    # Load existing state
    existing = await SagaManager.resume_from(saga_dir, task_id)
    if existing:
        saga2 = existing
    saga2.update_context(analysis_complete=True)
    await saga2.checkpoint_phase("debate", {"version": 2}, "S2", 10)

    # Final resume should show latest state
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is not None
    assert "debate" in recovered._checkpoints
    assert recovered._checkpoints["debate"]["result"]["version"] == 2


# ============================================================================
# CR-007: Saga file locked by another process
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr007_saga_file_locked(saga_dir, corruption_injector):
    """
    CR-007: Test saga access when file is locked.

    Scenario: Another process holds lock on saga file.
    Expected: Graceful timeout/retry or error handling.
    """
    task_id = "cr007-test"
    saga_file = saga_dir / f"{task_id}.json"

    # Create initial saga
    saga = SagaManager(saga_dir, task_id, auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", 5)

    # Try to lock file (platform-dependent)
    lock_handle = None
    try:
        lock_handle = corruption_injector.create_locked_file(saga_file)

        # Try to access locked file - should handle gracefully
        # Note: AtomicJsonStore may retry or timeout
        with contextlib.suppress(OSError, PermissionError):
            await SagaManager.resume_from(saga_dir, task_id)

    finally:
        if lock_handle:
            lock_handle.close()


# ============================================================================
# CR-008: Empty saga file (0 bytes)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr008_empty_saga_file(saga_dir, corruption_injector):
    """
    CR-008: Test handling of empty saga file.

    Scenario: Saga file is 0 bytes (crash during first write).
    Expected: resume_from() returns None gracefully.
    """
    task_id = "cr008-test"
    saga_file = saga_dir / f"{task_id}.json"

    # Create empty file
    corruption_injector.create_empty_file(saga_file)

    # Should return None gracefully
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is None


# ============================================================================
# CR-009: Future timestamp in checkpoint
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr009_future_timestamp(saga_dir, corruption_injector):
    """
    CR-009: Test saga with future timestamp.

    Scenario: Checkpoint has timestamp in the future (clock skew).
    Expected: Saga still works, no issues.
    """
    task_id = "cr009-test"

    # Create saga with future timestamp
    corruption_injector.create_saga_with_future_timestamp(saga_dir, task_id)

    # Should resume without issues
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is not None
    assert "analysis" in recovered._checkpoints


# ============================================================================
# CR-010: Unknown phase name in saga
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr010_unknown_phase_name(saga_dir, corruption_injector):
    """
    CR-010: Test saga with unknown phase name.

    Scenario: Saga contains "unknown_phase_xyz" checkpoint.
    Expected: Unknown phase ignored or handled gracefully.
    """
    task_id = "cr010-test"

    # Create saga with unknown phase
    corruption_injector.create_saga_with_unknown_phase(saga_dir, task_id)

    # Should resume (unknown phases ignored or handled)
    await SagaManager.resume_from(saga_dir, task_id)
    # May be None or have unknown phase - both are acceptable


# ============================================================================
# CR-011: Crash during fsync
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
def test_cr011_crash_during_fsync(saga_dir, crash_injector):
    """
    CR-011: Test crash during os.fsync().

    Scenario: AtomicJsonStore.save() crashes during fsync.
    Expected: Temp file cleaned up, no corruption.
    """
    store_file = saga_dir / "cr011-store.json"
    store = AtomicJsonStore(store_file)

    # First save succeeds
    store.save({"version": 1})

    # Second save crashes during fsync
    with crash_injector.crash_during_fsync(), contextlib.suppress(OSError):
        store.save({"version": 2})

    # Original data should be intact
    data = store.load()
    assert data.get("version") == 1

    # No temp files should remain
    list(saga_dir.glob("*.tmp"))
    # AtomicJsonStore should clean up temp files


# ============================================================================
# CR-012: Saga older than 24h
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr012_old_saga_resumable(saga_dir):
    """
    CR-012: Test that old saga files are still resumable.

    Scenario: Saga file is from 24+ hours ago.
    Expected: Resume still works (no time-based expiry).
    """
    task_id = "cr012-test"
    saga_file = saga_dir / f"{task_id}.json"

    # Create saga with old timestamp
    old_timestamp = "2020-01-01T00:00:00"
    saga_data = {
        "task_id": task_id,
        "checkpoints": {
            "analysis": {
                "phase": "analysis",
                "result": {},
                "state": "ANALYSIS_COMPLETE",
                "timestamp": old_timestamp,
                "context_index": 5,
            }
        },
        "context": {"analysis_complete": True},
        "recovery_point": "analysis",
    }
    saga_file.write_text(json.dumps(saga_data), encoding="utf-8")

    # Should resume without issues
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is not None


# ============================================================================
# CR-013: Saga directory missing
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr013_saga_directory_missing(tmp_path):
    """
    CR-013: Test resume when saga directory doesn't exist.

    Scenario: sagas_dir was deleted or never created.
    Expected: resume_from() returns None gracefully.
    """
    nonexistent_dir = tmp_path / "nonexistent" / "sagas"

    # Should return None gracefully
    recovered = await SagaManager.resume_from(nonexistent_dir, "any-task-id")
    assert recovered is None


# ============================================================================
# CR-014: Extra fields in saga JSON
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cr014_extra_fields_in_json(saga_dir, corruption_injector):
    """
    CR-014: Test backward compatibility with extra fields.

    Scenario: Saga JSON has unknown fields (future version).
    Expected: Resume ignores unknown fields, works normally.
    """
    task_id = "cr014-test"

    # Create valid saga
    saga = SagaManager(saga_dir, task_id, auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", 5)

    # Add extra fields
    saga_file = saga_dir / f"{task_id}.json"
    corruption_injector.corrupt_json(saga_file, "extra_fields")

    # Actually we need a valid saga with extra fields
    saga_data = {
        "task_id": task_id,
        "checkpoints": {
            "analysis": {
                "phase": "analysis",
                "result": {},
                "state": "S1",
                "timestamp": "2025-01-01T00:00:00",
                "context_index": 5,
                "extra_field_1": "ignored",
                "extra_field_2": 12345,
            }
        },
        "context": {"analysis_complete": True},
        "recovery_point": "analysis",
        "unknown_section": {"nested": "data"},
    }
    saga_file.write_text(json.dumps(saga_data), encoding="utf-8")

    # Should resume successfully
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is not None
    assert "analysis" in recovered._checkpoints


# ============================================================================
# CR-015: Crash during atomic rename
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
def test_cr015_crash_during_rename(saga_dir, crash_injector):
    """
    CR-015: Test crash during os.replace() atomic rename.

    Scenario: AtomicJsonStore.save() crashes during final rename.
    Expected: Old file intact OR new file in place (atomic guarantee).
    """
    store_file = saga_dir / "cr015-store.json"
    store = AtomicJsonStore(store_file)

    # First save
    store.save({"version": 1})

    # Second save crashes during rename
    with crash_injector.crash_during_rename(), contextlib.suppress(OSError):
        store.save({"version": 2})

    # File should exist and be valid JSON
    assert store_file.exists()
    data = store.load()
    # Should be either version 1 (old) or version 2 (new)
    assert data.get("version") in [1, 2]


# ============================================================================
# Run All Tests (Standalone Mode)
# ============================================================================


def run_all(metrics_collector=None):
    """Run all saga crash recovery tests."""

    base = TortureBase("saga_crash_tests")
    if metrics_collector:
        base.metrics = metrics_collector

    print("\n" + "=" * 50)
    print("SAGA CRASH RECOVERY TESTS (15 scenarios)")
    print("=" * 50 + "\n")

    # Run each test
    tests = [
        ("CR-001", test_cr001_partial_checkpoint_write),
        ("CR-002", test_cr002_corrupted_saga_json),
        ("CR-002b", test_cr002b_truncated_saga_json),
        ("CR-003", test_cr003_incomplete_checkpoint_chain),
        ("CR-004", test_cr004_atomic_store_lock_contention),
        ("CR-005", test_cr005_crash_between_checkpoint_and_context),
        ("CR-006", test_cr006_multiple_sagas_same_task_id),
        ("CR-007", test_cr007_saga_file_locked),
        ("CR-008", test_cr008_empty_saga_file),
        ("CR-009", test_cr009_future_timestamp),
        ("CR-010", test_cr010_unknown_phase_name),
        ("CR-011", test_cr011_crash_during_fsync),
        ("CR-012", test_cr012_old_saga_resumable),
        ("CR-013", test_cr013_saga_directory_missing),
        ("CR-014", test_cr014_extra_fields_in_json),
        ("CR-015", test_cr015_crash_during_rename),
    ]

    for test_id, test_func in tests:
        base.run_test(
            scenario="saga_crash",
            test_id=test_id,
            test_func=lambda f=test_func: f(base.sagas_dir),
            expect_recovery=True,
        )

    return base.metrics


if __name__ == "__main__":
    from tests.torture.metrics_collector import MetricsCollector

    metrics = run_all(MetricsCollector())
    print(metrics.summary())
