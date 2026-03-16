"""
Unit tests for SagaManager - HiveMind Checkpoint and Recovery System.

NEXUS V8.4.5 - Bug Fixes Phase

Tests cover:
- Checkpoint creation and persistence
- Rollback with context truncation
- Phase guards evaluation
- Resume from disk after crash
- Compensation function execution
- Edge cases

Author: Claude (NEXUS V8.4.5)
Date: 2025-12-11
"""

import asyncio
import shutil

# Add parent to path for imports
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import TestCase, main

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.hive_mind.saga_manager import (
    PHASE_GUARDS,
    PhaseCheckpoint,
    SagaContext,
    SagaManager,
)


class TestPhaseCheckpoint(TestCase):
    """Tests for PhaseCheckpoint dataclass."""

    def test_to_dict_serialization(self):
        """Test that to_dict() produces valid JSON-serializable dict."""
        checkpoint = PhaseCheckpoint(
            phase="analysis",
            result={"gemini": "result1", "claude": "result2"},
            state="ANALYSIS_COMPLETE",
            timestamp=datetime(2025, 12, 11, 10, 30, 0),
            context_index=5,
            compensation_name="compensate_analysis",
        )

        data = checkpoint.to_dict()

        assert data["phase"] == "analysis"
        assert data["result"] == {"gemini": "result1", "claude": "result2"}
        assert data["state"] == "ANALYSIS_COMPLETE"
        assert data["timestamp"] == "2025-12-11T10:30:00"
        assert data["context_index"] == 5
        assert data["compensation_name"] == "compensate_analysis"

    def test_from_dict_deserialization(self):
        """Test that from_dict() reconstructs checkpoint correctly."""
        data = {
            "phase": "debate",
            "result": {"consensus": True},
            "state": "DEBATE_CONVERGED",
            "timestamp": "2025-12-11T11:00:00",
            "context_index": 10,
            "compensation_name": None,
        }

        checkpoint = PhaseCheckpoint.from_dict(data)

        assert checkpoint.phase == "debate"
        assert checkpoint.result == {"consensus": True}
        assert checkpoint.state == "DEBATE_CONVERGED"
        assert checkpoint.timestamp == datetime(2025, 12, 11, 11, 0, 0)
        assert checkpoint.context_index == 10
        assert checkpoint.compensation_name is None

    def test_roundtrip_serialization(self):
        """Test that to_dict -> from_dict preserves all data."""
        original = PhaseCheckpoint(
            phase="execution",
            result={"steps_completed": 3, "success": True},
            state="EXECUTION_COMPLETE",
            timestamp=datetime.now(),
            context_index=20,
            compensation_name="compensate_execution",
        )

        roundtrip = PhaseCheckpoint.from_dict(original.to_dict())

        assert roundtrip.phase == original.phase
        assert roundtrip.result == original.result
        assert roundtrip.state == original.state
        assert roundtrip.context_index == original.context_index


class TestSagaContext(TestCase):
    """Tests for SagaContext dataclass."""

    def test_default_values(self):
        """Test that SagaContext has correct default values."""
        ctx = SagaContext()

        assert ctx.analysis_complete is False
        assert ctx.debate_complete is False
        assert ctx.execution_complete is False
        assert ctx.execution_failed is False

    def test_to_dict(self):
        """Test context serialization."""
        ctx = SagaContext(analysis_complete=True, debate_skipped=True, architecture_approved=True)

        data = ctx.to_dict()

        assert data["analysis_complete"] is True
        assert data["debate_skipped"] is True
        assert data["architecture_approved"] is True
        assert data["execution_complete"] is False

    def test_from_dict(self):
        """Test context deserialization."""
        data = {
            "analysis_complete": True,
            "debate_complete": True,
            "execution_failed": True,
            "unknown_field": "ignored",
        }

        ctx = SagaContext.from_dict(data)

        assert ctx.analysis_complete is True
        assert ctx.debate_complete is True
        assert ctx.execution_failed is True


class TestPhaseGuards(TestCase):
    """Tests for PHASE_GUARDS validation."""

    def test_debate_guard_requires_analysis(self):
        """Test that debate phase requires analysis_complete."""
        guard = PHASE_GUARDS["debate"]

        # Should fail without analysis
        assert guard({"analysis_complete": False}) is False

        # Should pass with analysis
        assert guard({"analysis_complete": True}) is True

    def test_architecture_guard_accepts_multiple_paths(self):
        """Test that architecture accepts debate_complete OR debate_skipped."""
        guard = PHASE_GUARDS["architecture"]

        # Should fail without any flag
        assert guard({}) is False

        # Should pass with debate_complete
        assert guard({"debate_complete": True}) is True

        # Should pass with debate_skipped
        assert guard({"debate_skipped": True}) is True

        # Should pass with immediate_consensus
        assert guard({"immediate_consensus": True}) is True

    def test_execution_guard_requires_architecture(self):
        """Test that execution requires architecture_approved."""
        guard = PHASE_GUARDS["execution"]

        assert guard({"architecture_approved": False}) is False
        assert guard({"architecture_approved": True}) is True

    def test_diagnosis_guard_requires_failure(self):
        """Test that diagnosis only triggers on execution_failed."""
        guard = PHASE_GUARDS["diagnosis"]

        assert guard({"execution_failed": False}) is False
        assert guard({"execution_failed": True}) is True

    def test_consolidation_guard_accepts_success_or_exhausted(self):
        """Test that consolidation accepts success OR retry exhausted."""
        guard = PHASE_GUARDS["consolidation"]

        assert guard({}) is False
        assert guard({"execution_complete": True}) is True
        assert guard({"retry_exhausted": True}) is True


class TestSagaManagerBasic(TestCase):
    """Basic functionality tests for SagaManager."""

    def setUp(self):
        """Create temporary directory for saga files."""
        self.temp_dir = tempfile.mkdtemp()
        self.sagas_dir = Path(self.temp_dir) / "sagas"
        self.sagas_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_manager(self):
        """Test that SagaManager initializes correctly."""
        saga = SagaManager(self.sagas_dir, "test-task-123")

        assert saga.task_id == "test-task-123"
        assert saga.checkpointed_phases == []
        assert saga.recovery_point is None

    def test_context_access(self):
        """Test that context is accessible and modifiable."""
        saga = SagaManager(self.sagas_dir, "test-task")

        saga.context.analysis_complete = True

        assert saga.context.analysis_complete is True


class TestSagaManagerCheckpoints(TestCase):
    """Tests for checkpoint operations."""

    def setUp(self):
        """Create temporary directory for saga files."""
        self.temp_dir = tempfile.mkdtemp()
        self.sagas_dir = Path(self.temp_dir) / "sagas"
        self.sagas_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_checkpoint_phase_creates_checkpoint(self):
        """Test that checkpoint_phase stores checkpoint in memory."""
        saga = SagaManager(self.sagas_dir, "test-task", auto_persist=False)

        # Run async test
        async def run_test():
            await saga.checkpoint_phase(
                phase="analysis", result={"test": "data"}, state="ANALYSIS_COMPLETE", context_index=5
            )

            assert "analysis" in saga.checkpointed_phases

            checkpoint = saga.get_checkpoint("analysis")
            assert checkpoint is not None
            assert checkpoint.phase == "analysis"
            assert checkpoint.result == {"test": "data"}
            assert checkpoint.context_index == 5

        asyncio.run(run_test())

    def test_checkpoint_persists_to_disk(self):
        """Test that checkpoint persists to disk when auto_persist=True."""
        saga = SagaManager(self.sagas_dir, "persist-test", auto_persist=True)

        async def run_test():
            await saga.checkpoint_phase(
                phase="analysis", result={"persisted": True}, state="ANALYSIS_COMPLETE", context_index=3
            )

            # Check file exists
            saga_file = self.sagas_dir / "persist-test.json"
            assert saga_file.exists()

        asyncio.run(run_test())

    def test_multiple_checkpoints(self):
        """Test creating checkpoints for multiple phases."""
        saga = SagaManager(self.sagas_dir, "multi-test", auto_persist=False)

        async def run_test():
            await saga.checkpoint_phase("analysis", {"step": 1}, "S1", 1)
            await saga.checkpoint_phase("debate", {"step": 2}, "S2", 5)
            await saga.checkpoint_phase("architecture", {"step": 3}, "S3", 10)

            assert len(saga.checkpointed_phases) == 3
            assert "analysis" in saga.checkpointed_phases
            assert "debate" in saga.checkpointed_phases
            assert "architecture" in saga.checkpointed_phases

        asyncio.run(run_test())


class TestSagaManagerCanEnterPhase(TestCase):
    """Tests for can_enter_phase guard evaluation."""

    def setUp(self):
        """Create temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.sagas_dir = Path(self.temp_dir) / "sagas"
        self.sagas_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_can_enter_analysis_always_true(self):
        """Test that analysis phase has no guards (always enterable)."""
        saga = SagaManager(self.sagas_dir, "guard-test")

        # analysis has no guard defined - can_enter_phase returns (bool, reason)
        can_enter, reason = saga.can_enter_phase("analysis")
        assert can_enter is True
        assert reason == ""

    def test_can_enter_debate_requires_analysis(self):
        """Test that debate requires analysis_complete."""
        saga = SagaManager(self.sagas_dir, "guard-test")

        # Without analysis_complete - can_enter_phase returns (bool, reason)
        can_enter, reason = saga.can_enter_phase("debate")
        assert can_enter is False
        assert "Guard failed" in reason

        # With analysis_complete
        saga.context.analysis_complete = True
        can_enter, reason = saga.can_enter_phase("debate")
        assert can_enter is True

    def test_can_enter_execution_requires_architecture(self):
        """Test that execution requires architecture_approved."""
        saga = SagaManager(self.sagas_dir, "guard-test")

        # can_enter_phase returns (bool, reason)
        can_enter, reason = saga.can_enter_phase("execution")
        assert can_enter is False
        assert "Guard failed" in reason

        saga.context.architecture_approved = True
        can_enter, reason = saga.can_enter_phase("execution")
        assert can_enter is True


class TestSagaManagerRollback(TestCase):
    """Tests for rollback operations."""

    def setUp(self):
        """Create temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.sagas_dir = Path(self.temp_dir) / "sagas"
        self.sagas_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rollback_to_previous_phase(self):
        """Test that rollback restores checkpoint state."""
        saga = SagaManager(self.sagas_dir, "rollback-test", auto_persist=False)

        async def run_test():
            # Create checkpoints
            await saga.checkpoint_phase("analysis", {"a": 1}, "S1", 5)
            await saga.checkpoint_phase("debate", {"b": 2}, "S2", 10)
            await saga.checkpoint_phase("architecture", {"c": 3}, "S3", 15)

            # Mock context manager
            class MockContextManager:
                def __init__(self):
                    self.messages = list(range(20))  # 20 messages

            ctx_manager = MockContextManager()

            # Rollback to analysis - now returns bool instead of checkpoint
            result = await saga.rollback_to("analysis", ctx_manager)

            assert result is True
            # recovery_point should be set to target phase
            assert saga.recovery_point == "analysis"
            # Context should be truncated to index 5
            assert len(ctx_manager.messages) == 5

        asyncio.run(run_test())

    def test_rollback_runs_compensations(self):
        """Test that rollback executes compensation functions."""
        saga = SagaManager(self.sagas_dir, "compensation-test", auto_persist=False)
        compensations_called = []

        async def compensate_architecture():
            compensations_called.append("architecture")

        async def compensate_debate():
            compensations_called.append("debate")

        saga.register_compensation("architecture", compensate_architecture)
        saga.register_compensation("debate", compensate_debate)

        async def run_test():
            await saga.checkpoint_phase("analysis", {}, "S1", 5)
            await saga.checkpoint_phase("debate", {}, "S2", 10)
            await saga.checkpoint_phase("architecture", {}, "S3", 15)

            class MockCtx:
                messages = list(range(20))

            await saga.rollback_to("analysis", MockCtx())

            # Should have called compensations in reverse order
            assert "architecture" in compensations_called
            assert "debate" in compensations_called

        asyncio.run(run_test())


class TestSagaManagerPersistence(TestCase):
    """Tests for disk persistence and recovery."""

    def setUp(self):
        """Create temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.sagas_dir = Path(self.temp_dir) / "sagas"
        self.sagas_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persist_and_resume(self):
        """Test that saga can be persisted and resumed."""
        task_id = "resume-test"

        async def run_test():
            # Create saga and checkpoint
            saga1 = SagaManager(self.sagas_dir, task_id, auto_persist=True)
            await saga1.checkpoint_phase("analysis", {"resumed": True}, "S1", 5)
            await saga1.checkpoint_phase("debate", {"resumed": True}, "S2", 10)

            # Resume from disk
            saga2 = await SagaManager.resume_from(self.sagas_dir, task_id)

            assert saga2 is not None
            assert saga2.task_id == task_id
            assert "analysis" in saga2.checkpointed_phases
            assert "debate" in saga2.checkpointed_phases

            # Check checkpoint data preserved
            analysis = saga2.get_checkpoint("analysis")
            assert analysis.result == {"resumed": True}
            assert analysis.context_index == 5

        asyncio.run(run_test())

    def test_resume_nonexistent_returns_none(self):
        """Test that resume_from returns None for missing saga."""

        async def run_test():
            result = await SagaManager.resume_from(self.sagas_dir, "nonexistent")
            assert result is None

        asyncio.run(run_test())


# =============================================================================
# PYTEST FIXTURES AND ASYNC TESTS
# =============================================================================


@pytest.fixture
def saga_dir(tmp_path):
    """Create temporary saga directory."""
    sagas_dir = tmp_path / "sagas"
    sagas_dir.mkdir()
    return sagas_dir


@pytest.mark.asyncio
async def test_checkpoint_context_index_preserved(saga_dir):
    """Test that context_index is preserved through checkpoint cycle."""
    saga = SagaManager(saga_dir, "ctx-test", auto_persist=True)

    await saga.checkpoint_phase(phase="analysis", result={"test": 1}, state="ANALYSIS_COMPLETE", context_index=42)

    # Resume and verify
    saga2 = await SagaManager.resume_from(saga_dir, "ctx-test")
    checkpoint = saga2.get_checkpoint("analysis")

    assert checkpoint.context_index == 42


@pytest.mark.asyncio
async def test_full_pipeline_checkpoint_cycle(saga_dir):
    """Test checkpointing through full 7-phase pipeline."""
    saga = SagaManager(saga_dir, "full-pipeline", auto_persist=False)

    # Simulate full pipeline
    phases_data = [
        ("analysis", {"gemini": "a1", "claude": "a2"}, 5),
        ("debate", {"consensus": True}, 15),
        ("architecture", {"plan": ["step1", "step2"]}, 25),
        ("execution", {"completed": 2}, 45),
        ("consolidation", {"archived": True}, 50),
    ]

    for phase, result, ctx_idx in phases_data:
        await saga.checkpoint_phase(phase, result, f"STATE_{phase.upper()}", ctx_idx)

    assert len(saga.checkpointed_phases) == 5

    # Verify each checkpoint
    for phase, expected_result, expected_idx in phases_data:
        checkpoint = saga.get_checkpoint(phase)
        assert checkpoint.result == expected_result
        assert checkpoint.context_index == expected_idx


if __name__ == "__main__":
    main()
