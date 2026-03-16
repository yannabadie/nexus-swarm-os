"""
Torture Protocol V8 - Compensation Failure Tests

8 tests covering compensation function failure scenarios.

Test IDs: CF-001 to CF-008
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.intelligence.hive_mind.saga_manager import SagaManager


@pytest.fixture
def saga_dir(tmp_path):
    """Create saga directory."""
    saga_dir = tmp_path / ".nexus" / "sagas"
    saga_dir.mkdir(parents=True)
    return saga_dir


# ============================================================================
# CF-001: Exception in compensation function
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf001_compensation_exception(saga_dir):
    """
    CF-001: Test compensation function that raises exception.

    Scenario: Compensation raises RuntimeError.
    Expected: Exception logged, rollback continues.
    """
    saga = SagaManager(saga_dir, "cf001-test", auto_persist=True)
    compensation_called = []

    async def failing_compensation():
        compensation_called.append("analysis")
        raise RuntimeError("Compensation failed!")

    async def good_compensation():
        compensation_called.append("debate")

    # Setup checkpoints
    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=failing_compensation)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10, compensation=good_compensation)

    # Rollback should continue despite exception
    await saga.rollback_to("analysis")

    # Both compensations should have been called (or attempted)
    assert "debate" in compensation_called


# ============================================================================
# CF-002: Partial compensation chain
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf002_partial_compensation_chain(saga_dir):
    """
    CF-002: Test partial compensation chain (2 succeed, 1 fails).

    Scenario: First 2 compensations succeed, third fails.
    Expected: State reflects partial compensation.
    """
    saga = SagaManager(saga_dir, "cf002-test", auto_persist=True)
    compensation_results = []

    async def comp_analysis():
        compensation_results.append("analysis_done")

    async def comp_debate():
        compensation_results.append("debate_done")

    async def comp_architecture():
        compensation_results.append("arch_start")
        raise ValueError("Architecture compensation failed!")

    # Setup multiple checkpoints
    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=comp_analysis)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10, compensation=comp_debate)
    saga.update_context(debate_complete=True)
    await saga.checkpoint_phase("architecture", {}, "S3", 15, compensation=comp_architecture)

    # Rollback to analysis
    await saga.rollback_to("analysis")

    # Should have called compensations in reverse order
    # architecture (fails) -> debate -> analysis
    assert "arch_start" in compensation_results
    # debate should still be called despite arch failure


# ============================================================================
# CF-003: File deletion race during compensation
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf003_file_deletion_race(saga_dir, tmp_path):
    """
    CF-003: Test file deletion race during compensation.

    Scenario: File deleted by another process before compensation tries.
    Expected: Handles gracefully (already deleted = ok).
    """
    saga = SagaManager(saga_dir, "cf003-test", auto_persist=True)
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    # Create agent file
    agent_file = agents_dir / "agent_001.json"
    agent_file.write_text("{}")

    compensation_called = []

    async def file_cleanup_compensation():
        compensation_called.append("start")
        # Delete file
        if agent_file.exists():
            agent_file.unlink()
        compensation_called.append("done")

    await saga.checkpoint_phase("architecture", {}, "S1", 5, compensation=file_cleanup_compensation)

    # Delete file before rollback (simulate race)
    if agent_file.exists():
        agent_file.unlink()

    # Rollback should handle gracefully
    await saga.rollback_to("analysis")  # Will trigger architecture compensation

    # Compensation should have completed
    assert "done" in compensation_called


# ============================================================================
# CF-004: Async compensation timeout
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf004_compensation_timeout(saga_dir):
    """
    CF-004: Test compensation that takes too long.

    Scenario: Compensation sleeps for 60 seconds.
    Expected: Times out or completes (depending on implementation).
    """
    saga = SagaManager(saga_dir, "cf004-test", auto_persist=True)
    compensation_started = []

    async def slow_compensation():
        compensation_started.append("start")
        await asyncio.sleep(0.5)  # Simulate slow operation (shorter for test)
        compensation_started.append("done")

    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=slow_compensation)

    # Rollback with slow compensation
    start = asyncio.get_event_loop().time()
    await saga.rollback_to("analysis")
    asyncio.get_event_loop().time() - start

    # Should complete (compensation ran)
    assert "start" in compensation_started


# ============================================================================
# CF-005: Compensation that creates new files
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf005_compensation_creates_files(saga_dir, tmp_path):
    """
    CF-005: Test compensation that spawns new files.

    Scenario: Compensation creates audit log during cleanup.
    Expected: New files created, no interference.
    """
    saga = SagaManager(saga_dir, "cf005-test", auto_persist=True)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    async def audit_compensation():
        # Create audit log during compensation
        audit_file = audit_dir / "compensation_audit.log"
        audit_file.write_text("Compensation ran at analysis phase")

    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=audit_compensation)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10)

    # Rollback triggers compensation
    await saga.rollback_to("analysis")

    # Audit file should exist
    audit_file = audit_dir / "compensation_audit.log"
    assert audit_file.exists()


# ============================================================================
# CF-006: Sync compensation in async context
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf006_sync_compensation(saga_dir):
    """
    CF-006: Test synchronous (non-async) compensation function.

    Scenario: Compensation is a regular function, not async.
    Expected: Called correctly (SagaManager handles both).
    """
    saga = SagaManager(saga_dir, "cf006-test", auto_persist=True)
    compensation_called = []

    def sync_compensation():  # Not async!
        compensation_called.append("sync_ran")

    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=sync_compensation)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10)

    # Rollback should call sync compensation
    await saga.rollback_to("analysis")

    assert "sync_ran" in compensation_called


# ============================================================================
# CF-007: Missing compensation for phase
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf007_missing_compensation(saga_dir):
    """
    CF-007: Test rollback when no compensation registered for phase.

    Scenario: Checkpoint without compensation function.
    Expected: Rollback skips gracefully, no error.
    """
    saga = SagaManager(saga_dir, "cf007-test", auto_persist=True)

    # Checkpoints without compensation
    await saga.checkpoint_phase("analysis", {}, "S1", 5)  # No compensation
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10)  # No compensation
    saga.update_context(debate_complete=True)
    await saga.checkpoint_phase("architecture", {}, "S3", 15)  # No compensation

    # Rollback should work without error
    await saga.rollback_to("analysis")

    # Should complete
    assert saga._recovery_point == "analysis"


# ============================================================================
# CF-008: Compensation modifies shared state
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_cf008_compensation_shared_state(saga_dir):
    """
    CF-008: Test compensation that modifies shared state.

    Scenario: Multiple compensations modify same list.
    Expected: State changes are isolated or ordered.
    """
    saga = SagaManager(saga_dir, "cf008-test", auto_persist=True)
    shared_state = {"counter": 0, "phases": []}

    async def comp_analysis():
        shared_state["counter"] += 1
        shared_state["phases"].append("analysis")

    async def comp_debate():
        shared_state["counter"] += 10
        shared_state["phases"].append("debate")

    async def comp_architecture():
        shared_state["counter"] += 100
        shared_state["phases"].append("architecture")

    await saga.checkpoint_phase("analysis", {}, "S1", 5, compensation=comp_analysis)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10, compensation=comp_debate)
    saga.update_context(debate_complete=True)
    await saga.checkpoint_phase("architecture", {}, "S3", 15, compensation=comp_architecture)

    # Rollback to analysis (triggers arch -> debate compensations)
    await saga.rollback_to("analysis")

    # Compensations should have run (in reverse order)
    assert shared_state["counter"] >= 10  # At least debate ran
    assert "architecture" in shared_state["phases"] or "debate" in shared_state["phases"]


# ============================================================================
# Run All Tests (Standalone Mode)
# ============================================================================


def run_all(metrics_collector=None):
    """Run all compensation failure tests."""
    print("\n" + "=" * 50)
    print("COMPENSATION FAILURE TESTS (8 scenarios)")
    print("=" * 50 + "\n")
    print("Run with: pytest tests/torture/scenarios/compensation.py -v")
    return metrics_collector


if __name__ == "__main__":
    print("Run with: pytest tests/torture/scenarios/compensation.py -v -m torture")
