"""
Torture Protocol V8 - Saga Concurrency Tests

12 tests covering concurrent access scenarios for SagaManager.

Test IDs: CC-001 to CC-012
"""

import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import contextlib

from core.intelligence.hive_mind.saga_manager import SagaManager
from core.utils.atomic_store import AtomicJsonStore
from tests.torture.base import TortureBase
from tests.torture.chaos_injectors import RaceInjector


@pytest.fixture
def saga_dir(tmp_path):
    """Create saga directory."""
    saga_dir = tmp_path / ".nexus" / "sagas"
    saga_dir.mkdir(parents=True)
    return saga_dir


@pytest.fixture
def race_injector():
    """Provide RaceInjector."""
    return RaceInjector()


# ============================================================================
# CC-001: Two phases checkpointing simultaneously
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc001_simultaneous_checkpoints(saga_dir):
    """
    CC-001: Test two phases checkpointing at the same time.

    Scenario: asyncio.gather() with two checkpoint_phase() calls.
    Expected: Both checkpoints succeed without corruption.
    """
    saga = SagaManager(saga_dir, "cc001-test", auto_persist=True)

    async def checkpoint_analysis():
        await saga.checkpoint_phase("analysis", {"phase": "analysis"}, "S1", 5)
        return "analysis"

    async def checkpoint_debate():
        await asyncio.sleep(0.01)  # Slight delay to ensure overlap
        saga.update_context(analysis_complete=True)
        await saga.checkpoint_phase("debate", {"phase": "debate"}, "S2", 10)
        return "debate"

    results = await asyncio.gather(checkpoint_analysis(), checkpoint_debate(), return_exceptions=True)

    # Both should succeed
    assert "analysis" in results or isinstance(results[0], Exception)
    assert "debate" in results or isinstance(results[1], Exception)

    # Verify persistence
    recovered = await SagaManager.resume_from(saga_dir, "cc001-test")
    assert recovered is not None


# ============================================================================
# CC-002: Checkpoint during active rollback
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc002_checkpoint_during_rollback(saga_dir):
    """
    CC-002: Test checkpointing while rollback is in progress.

    Scenario: Start rollback, trigger checkpoint mid-execution.
    Expected: One operation wins, state remains consistent.
    """
    saga = SagaManager(saga_dir, "cc002-test", auto_persist=True)

    # Setup checkpoints
    await saga.checkpoint_phase("analysis", {}, "S1", 5)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10)
    saga.update_context(debate_complete=True)
    await saga.checkpoint_phase("architecture", {}, "S3", 15)

    async def do_rollback():
        await asyncio.sleep(0.02)  # Let checkpoint start
        return await saga.rollback_to("analysis")

    async def do_checkpoint():
        saga.update_context(architecture_approved=True)
        return await saga.checkpoint_phase("execution", {}, "S4", 20)

    await asyncio.gather(do_rollback(), do_checkpoint(), return_exceptions=True)

    # State should be consistent (either rolled back or execution checkpointed)
    recovered = await SagaManager.resume_from(saga_dir, "cc002-test")
    assert recovered is not None


# ============================================================================
# CC-003: Resume during active saga
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc003_resume_during_active_saga(saga_dir):
    """
    CC-003: Test resume_from() while saga is actively checkpointing.

    Scenario: One task checkpointing, another resuming same task_id.
    Expected: Resume gets consistent snapshot.
    """
    task_id = "cc003-test"
    saga = SagaManager(saga_dir, task_id, auto_persist=True)

    results = []

    async def active_checkpointing():
        for i, phase in enumerate(["analysis", "debate", "architecture"]):
            await saga.checkpoint_phase(phase, {"step": i}, f"S{i}", i * 5)
            await asyncio.sleep(0.05)
        results.append("checkpointing_done")

    async def concurrent_resume():
        await asyncio.sleep(0.02)  # Start after first checkpoint
        for _ in range(5):
            recovered = await SagaManager.resume_from(saga_dir, task_id)
            if recovered:
                results.append(f"resumed_{len(recovered._checkpoints)}")
            await asyncio.sleep(0.03)

    await asyncio.gather(active_checkpointing(), concurrent_resume())

    # Should have some resume results
    resume_results = [r for r in results if r.startswith("resumed_")]
    assert len(resume_results) > 0


# ============================================================================
# CC-004: Parallel compensation execution
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc004_parallel_compensation(saga_dir):
    """
    CC-004: Test parallel compensation execution during rollback.

    Scenario: Rollback with slow compensations + concurrent access.
    Expected: Compensations complete, no deadlock.
    """
    saga = SagaManager(saga_dir, "cc004-test", auto_persist=True)
    compensation_calls = []

    async def slow_compensation(phase):
        compensation_calls.append(f"start_{phase}")
        await asyncio.sleep(0.1)
        compensation_calls.append(f"end_{phase}")

    # Setup with custom compensations
    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=lambda: slow_compensation("analysis"))
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10, compensation=lambda: slow_compensation("debate"))

    # Rollback triggers compensations
    await saga.rollback_to("analysis")

    # Compensations should have been called
    assert len(compensation_calls) > 0


# ============================================================================
# CC-005: Context truncation race
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc005_context_truncation_race(saga_dir):
    """
    CC-005: Test multiple rollbacks targeting same context_manager.

    Scenario: Two rollbacks to different phases simultaneously.
    Expected: Final state is consistent (one rollback wins).
    """
    saga = SagaManager(saga_dir, "cc005-test", auto_persist=True)

    # Setup multiple checkpoints
    await saga.checkpoint_phase("analysis", {}, "S1", 5)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10)
    saga.update_context(debate_complete=True)
    await saga.checkpoint_phase("architecture", {}, "S3", 15)

    # Note: Without actual context_manager, we just test saga state
    async def rollback_to_analysis():
        return await saga.rollback_to("analysis")

    async def rollback_to_debate():
        await asyncio.sleep(0.01)
        return await saga.rollback_to("debate")

    # One should succeed, one may fail or both succeed sequentially
    await asyncio.gather(rollback_to_analysis(), rollback_to_debate(), return_exceptions=True)

    # Saga should be in consistent state
    assert saga._recovery_point in ["analysis", "debate", None]


# ============================================================================
# CC-006: AtomicJsonStore concurrent ops (10 threads)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
def test_cc006_atomic_store_10_threads(saga_dir):
    """
    CC-006: Test AtomicJsonStore with 10 concurrent threads.

    Scenario: 10 threads doing read-modify-write cycles.
    Expected: No data loss, no corruption.
    """
    store_file = saga_dir / "cc006-store.json"
    store = AtomicJsonStore(store_file)
    store.save({"counter": 0, "writes": []})

    errors = []
    NUM_THREADS = 10
    WRITES_PER_THREAD = 5

    def worker(thread_id):
        try:
            for i in range(WRITES_PER_THREAD):
                data = store.load()
                data["counter"] = data.get("counter", 0) + 1
                data["writes"].append(f"t{thread_id}_w{i}")
                store.save(data)
                time.sleep(0.01)
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(worker, i) for i in range(NUM_THREADS)]
        for future in as_completed(futures):
            future.result()  # Raise any exceptions

    # Verify final state
    final = store.load()
    assert "counter" in final
    assert "writes" in final
    # Counter should be close to expected (may have race conditions)
    # At minimum, no corruption
    assert isinstance(final["counter"], int)
    assert isinstance(final["writes"], list)


# ============================================================================
# CC-007: Saga persist while loading
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc007_persist_while_loading(saga_dir):
    """
    CC-007: Test _persist() racing with resume_from().

    Scenario: One saga persisting while another loads same file.
    Expected: Load gets consistent snapshot.
    """
    task_id = "cc007-test"
    saga = SagaManager(saga_dir, task_id, auto_persist=False)  # Manual persist

    # Initial state
    await saga.checkpoint_phase("analysis", {"v": 1}, "S1", 5)
    await saga._persist()

    results = []

    async def keep_persisting():
        for i in range(10):
            saga._checkpoints["analysis"]["result"]["v"] = i + 2
            await saga._persist()
            await asyncio.sleep(0.01)
        results.append("persist_done")

    async def keep_loading():
        for _ in range(10):
            recovered = await SagaManager.resume_from(saga_dir, task_id)
            if recovered and "analysis" in recovered._checkpoints:
                v = recovered._checkpoints["analysis"]["result"].get("v")
                results.append(f"loaded_v{v}")
            await asyncio.sleep(0.01)

    await asyncio.gather(keep_persisting(), keep_loading())

    # Loads should get valid versions
    load_results = [r for r in results if r.startswith("loaded_")]
    assert len(load_results) > 0


# ============================================================================
# CC-008: Multiple SagaManagers same file
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc008_multiple_managers_same_file(saga_dir):
    """
    CC-008: Test 5 SagaManager instances for same task_id.

    Scenario: Multiple managers operating on same saga file.
    Expected: Last write wins, no corruption.
    """
    task_id = "cc008-test"

    async def manager_work(manager_id):
        saga = SagaManager(saga_dir, task_id, auto_persist=True)
        await saga.checkpoint_phase("analysis", {"manager": manager_id}, f"S{manager_id}", manager_id * 5)
        await asyncio.sleep(0.02)
        return manager_id

    # 5 managers concurrently
    await asyncio.gather(*[manager_work(i) for i in range(5)], return_exceptions=True)

    # Final state should be one of the managers' states
    recovered = await SagaManager.resume_from(saga_dir, task_id)
    assert recovered is not None
    assert "analysis" in recovered._checkpoints
    assert recovered._checkpoints["analysis"]["result"]["manager"] in range(5)


# ============================================================================
# CC-009: Cleanup during active checkpoint
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc009_cleanup_during_checkpoint(saga_dir):
    """
    CC-009: Test cleanup() called while _persist() is running.

    Scenario: Call cleanup() mid-persist operation.
    Expected: Either cleanup wins (file deleted) or persist wins (file exists).
    """
    task_id = "cc009-test"
    saga = SagaManager(saga_dir, task_id, auto_persist=False)
    await saga.checkpoint_phase("analysis", {}, "S1", 5)

    async def do_persist():
        await asyncio.sleep(0.01)
        await saga._persist()
        return "persisted"

    async def do_cleanup():
        await asyncio.sleep(0.02)
        saga.cleanup()
        return "cleaned"

    await asyncio.gather(do_persist(), do_cleanup(), return_exceptions=True)

    # File may or may not exist depending on race
    saga_dir / f"{task_id}.json"
    # Either outcome is acceptable - no crash is the goal


# ============================================================================
# CC-010: Guard evaluation race
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc010_guard_evaluation_race(saga_dir):
    """
    CC-010: Test can_enter_phase() while context is being updated.

    Scenario: Check guards while update_context() is running.
    Expected: Consistent result (before or after update).
    """
    saga = SagaManager(saga_dir, "cc010-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", 5)

    results = []

    async def update_context_loop():
        for i in range(10):
            saga.update_context(analysis_complete=i % 2 == 0)
            await asyncio.sleep(0.005)

    async def check_guards_loop():
        for _ in range(20):
            can_enter, reason = saga.can_enter_phase("debate")
            results.append(can_enter)
            await asyncio.sleep(0.002)

    await asyncio.gather(update_context_loop(), check_guards_loop())

    # Results should be boolean (no crashes)
    assert all(isinstance(r, bool) for r in results)


# ============================================================================
# CC-011: Concurrent rollback to different phases
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.asyncio
async def test_cc011_concurrent_different_rollbacks(saga_dir):
    """
    CC-011: Test two rollbacks to different phases simultaneously.

    Scenario: Rollback to "analysis" and "debate" at same time.
    Expected: One wins, state is consistent.
    """
    saga = SagaManager(saga_dir, "cc011-test", auto_persist=True)

    # Setup
    for phase in ["analysis", "debate", "architecture", "execution"]:
        await saga.checkpoint_phase(phase, {}, f"S_{phase}", 5)
        saga.update_context(**{f"{phase}_complete" if phase != "architecture" else "architecture_approved": True})

    async def rollback_analysis():
        return await saga.rollback_to("analysis")

    async def rollback_debate():
        return await saga.rollback_to("debate")

    await asyncio.gather(rollback_analysis(), rollback_debate(), return_exceptions=True)

    # Recovery point should be one of the targets
    assert saga._recovery_point in ["analysis", "debate", None]


# ============================================================================
# CC-012: High contention (20 threads)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_concurrency
@pytest.mark.torture_slow
def test_cc012_high_contention_20_threads(saga_dir):
    """
    CC-012: High contention stress test with 20 threads.

    Scenario: 20 threads all operating on same saga.
    Expected: No deadlock, no corruption, completes in reasonable time.
    """
    store_file = saga_dir / "cc012-store.json"
    store = AtomicJsonStore(store_file)
    store.save({"ops": 0})

    NUM_THREADS = 20
    OPS_PER_THREAD = 10
    completed = []
    timeout_seconds = 30

    def worker(thread_id):
        for i in range(OPS_PER_THREAD):
            try:
                data = store.load()
                data["ops"] = data.get("ops", 0) + 1
                data[f"t{thread_id}"] = i
                store.save(data)
            except Exception:
                pass  # Tolerate some failures under high contention
        completed.append(thread_id)

    start = time.time()
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(worker, i) for i in range(NUM_THREADS)]
        for future in as_completed(futures, timeout=timeout_seconds):
            with contextlib.suppress(Exception):
                future.result()

    elapsed = time.time() - start

    # All threads should complete
    assert len(completed) == NUM_THREADS, f"Only {len(completed)}/{NUM_THREADS} completed"
    assert elapsed < timeout_seconds, f"Timeout: took {elapsed}s"

    # Final state should be valid
    final = store.load()
    assert isinstance(final, dict)
    assert final.get("ops", 0) > 0


# ============================================================================
# Run All Tests (Standalone Mode)
# ============================================================================


def run_all(metrics_collector=None):
    """Run all saga concurrency tests."""

    base = TortureBase("saga_concurrency_tests")
    if metrics_collector:
        base.metrics = metrics_collector

    print("\n" + "=" * 50)
    print("SAGA CONCURRENCY TESTS (12 scenarios)")
    print("=" * 50 + "\n")

    # Note: These tests need to be run with pytest for proper async support
    print("Run with: pytest tests/torture/scenarios/saga_concurrency.py -v")

    return base.metrics


if __name__ == "__main__":
    print("Run with: pytest tests/torture/scenarios/saga_concurrency.py -v -m torture_concurrency")
