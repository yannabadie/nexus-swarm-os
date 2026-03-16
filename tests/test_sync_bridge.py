"""
V9.4 ISSUE-003: OrchestratorSyncBridge Unit Tests

Tests for state synchronization between HiveMind and Swarm.
"""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock

import pytest

from core.execution_pkg.orchestration.sync_bridge import (
    OrchestratorSyncBridge,
    SyncEvent,
    SyncEventType,
    get_sync_bridge,
    reset_sync_bridge,
)


class TestSyncEventType:
    """Test SyncEventType enum."""

    def test_all_event_types_defined(self):
        """All required event types exist."""
        assert SyncEventType.TASK_CREATED
        assert SyncEventType.CHECKPOINT_CREATED
        assert SyncEventType.CHECKPOINT_RESTORED
        assert SyncEventType.ROLLBACK_STARTED
        assert SyncEventType.ROLLBACK_COMPLETED
        assert SyncEventType.TASK_COMPLETED
        assert SyncEventType.VALIDATION_FAILED
        assert SyncEventType.VALIDATION_PASSED


class TestSyncEvent:
    """Test SyncEvent dataclass."""

    def test_create_event(self):
        """Event created with required fields."""
        event = SyncEvent(event_type=SyncEventType.TASK_CREATED, source="hivemind", task_id="test_123")

        assert event.event_type == SyncEventType.TASK_CREATED
        assert event.source == "hivemind"
        assert event.task_id == "test_123"
        assert isinstance(event.timestamp, datetime)
        assert event.data == {}
        assert event.propagated_to == []

    def test_event_with_data(self):
        """Event can include additional data."""
        event = SyncEvent(
            event_type=SyncEventType.CHECKPOINT_CREATED,
            source="swarm",
            task_id="test_456",
            data={"phase": "analysis", "context_index": 50},
            propagated_to=["hivemind"],
        )

        assert event.data["phase"] == "analysis"
        assert event.propagated_to == ["hivemind"]

    def test_event_to_dict(self):
        """Event serializes to dict."""
        event = SyncEvent(event_type=SyncEventType.ROLLBACK_STARTED, source="sync_bridge", task_id="test_789")

        d = event.to_dict()

        assert d["event_type"] == "rollback_started"
        assert d["source"] == "sync_bridge"
        assert d["task_id"] == "test_789"
        assert "timestamp" in d


class TestOrchestratorSyncBridge:
    """Test OrchestratorSyncBridge class."""

    def setup_method(self):
        """Reset global state before each test."""
        reset_sync_bridge()

    def test_init_without_managers(self):
        """Bridge can be created without managers."""
        bridge = OrchestratorSyncBridge()

        assert bridge._saga is None
        assert bridge._session is None
        assert bridge.is_connected is False

    def test_init_with_workspace(self):
        """Bridge accepts workspace path."""
        with TemporaryDirectory() as tmpdir:
            bridge = OrchestratorSyncBridge(workspace_path=Path(tmpdir))
            assert bridge._workspace == Path(tmpdir)

    def test_set_saga_manager(self):
        """Saga manager can be set later."""
        bridge = OrchestratorSyncBridge()
        mock_saga = Mock()
        mock_saga.task_id = "test_task"

        bridge.set_saga_manager(mock_saga)

        assert bridge._saga is mock_saga
        assert bridge.is_connected is True

    def test_set_session_manager(self):
        """Session manager can be set later."""
        bridge = OrchestratorSyncBridge()
        mock_session = Mock()

        bridge.set_session_manager(mock_session)

        assert bridge._session is mock_session
        assert bridge.is_connected is True


class TestUnifiedTaskCreation:
    """Test unified task creation."""

    def setup_method(self):
        reset_sync_bridge()

    def test_create_unified_task_without_session_manager(self):
        """Task ID generated even without session manager."""
        bridge = OrchestratorSyncBridge()

        task_id = bridge.create_unified_task("Test objective", "PARALLEL")

        assert task_id.startswith("unified_")
        assert len(bridge.get_events()) == 1
        assert bridge.get_events()[0].event_type == SyncEventType.TASK_CREATED

    def test_create_unified_task_with_session_manager(self):
        """Task created in session manager when available."""
        bridge = OrchestratorSyncBridge()
        mock_session = Mock()
        bridge.set_session_manager(mock_session)

        task_id = bridge.create_unified_task("Build API", "SEQUENTIAL", metadata={"priority": "high"})

        mock_session.create_task.assert_called_once()
        call_args = mock_session.create_task.call_args
        assert call_args.kwargs["task_id"] == task_id
        assert call_args.kwargs["swarm_mode"] == "SEQUENTIAL"
        assert "sync_bridge" in call_args.kwargs["metadata"]

    def test_task_correlation_recorded(self):
        """Task correlation stored for reference."""
        bridge = OrchestratorSyncBridge()

        task_id = bridge.create_unified_task("Test", "PARALLEL")

        assert task_id in bridge._task_correlation
        assert bridge._task_correlation[task_id]["swarm_mode"] == "PARALLEL"


class TestCheckpointSynchronization:
    """Test checkpoint propagation."""

    def setup_method(self):
        reset_sync_bridge()

    @pytest.mark.asyncio
    async def test_sync_checkpoint_hivemind_to_swarm(self):
        """HiveMind checkpoint creates Swarm checkpoint."""
        bridge = OrchestratorSyncBridge()
        mock_session = Mock()
        mock_session.create_checkpoint.return_value = "cp_123"
        bridge.set_session_manager(mock_session)

        result = await bridge.sync_checkpoint(
            source="hivemind", task_id="task_001", phase_or_mode="analysis", checkpoint_data={"context_index": 50}
        )

        assert result is True
        mock_session.create_checkpoint.assert_called_once_with("task_001")

        events = bridge.get_events()
        assert len(events) == 1
        assert events[0].event_type == SyncEventType.CHECKPOINT_CREATED
        assert events[0].data["swarm_checkpoint_id"] == "cp_123"
        assert "swarm" in events[0].propagated_to

    @pytest.mark.asyncio
    async def test_sync_checkpoint_swarm_to_hivemind(self):
        """Swarm checkpoint recorded for HiveMind."""
        bridge = OrchestratorSyncBridge()

        result = await bridge.sync_checkpoint(
            source="swarm",
            task_id="task_002",
            phase_or_mode="PARALLEL",
            checkpoint_data={"fallback_chain": ["PARALLEL", "SEQUENTIAL"]},
        )

        assert result is True
        events = bridge.get_events()
        assert events[0].data["mode"] == "PARALLEL"

    @pytest.mark.asyncio
    async def test_sync_checkpoint_no_target(self):
        """No propagation when target not available."""
        bridge = OrchestratorSyncBridge()
        # No session manager set

        result = await bridge.sync_checkpoint(source="hivemind", task_id="task_003", phase_or_mode="debate")

        assert result is False

    def test_sync_checkpoint_sync_version(self):
        """Synchronous version works in non-async context."""
        bridge = OrchestratorSyncBridge()
        mock_session = Mock()
        mock_session.create_checkpoint.return_value = "cp_sync"
        bridge.set_session_manager(mock_session)

        result = bridge.sync_checkpoint_sync(source="hivemind", task_id="task_sync", phase_or_mode="architecture")

        assert result is True


class TestCoordinatedRollback:
    """Test rollback coordination."""

    def setup_method(self):
        reset_sync_bridge()

    @pytest.mark.asyncio
    async def test_rollback_both_systems(self):
        """Rollback affects both HiveMind and Swarm."""
        bridge = OrchestratorSyncBridge()

        # Mock SagaManager
        mock_saga = AsyncMock()
        mock_saga.task_id = "task_rollback"
        mock_saga.checkpointed_phases = ["analysis", "debate"]
        mock_saga.rollback_to = AsyncMock(return_value=True)
        bridge.set_saga_manager(mock_saga)

        # Mock SwarmSessionManager
        mock_session = Mock()
        mock_session.list_checkpoints.return_value = ["cp_1", "cp_2"]
        mock_session.restore_checkpoint.return_value = True
        bridge.set_session_manager(mock_session)

        result = await bridge.coordinated_rollback(
            task_id="task_rollback", target_phase="analysis", context_manager=None
        )

        assert result is True
        mock_saga.rollback_to.assert_called_once()
        mock_session.restore_checkpoint.assert_called_once_with("task_rollback", "cp_2")

        # Check events
        events = bridge.get_events()
        assert any(e.event_type == SyncEventType.ROLLBACK_STARTED for e in events)
        assert any(e.event_type == SyncEventType.ROLLBACK_COMPLETED for e in events)

    @pytest.mark.asyncio
    async def test_rollback_saga_only(self):
        """Rollback works with only saga available."""
        bridge = OrchestratorSyncBridge()

        mock_saga = AsyncMock()
        mock_saga.task_id = "task_saga"
        mock_saga.checkpointed_phases = ["analysis"]
        mock_saga.rollback_to = AsyncMock(return_value=True)
        bridge.set_saga_manager(mock_saga)

        result = await bridge.coordinated_rollback(task_id="task_saga", target_phase="analysis")

        assert result is True

    @pytest.mark.asyncio
    async def test_rollback_handles_errors(self):
        """Rollback records errors but continues."""
        bridge = OrchestratorSyncBridge()

        mock_saga = AsyncMock()
        mock_saga.task_id = "task_error"
        mock_saga.checkpointed_phases = ["analysis"]
        mock_saga.rollback_to = AsyncMock(side_effect=Exception("Saga error"))
        bridge.set_saga_manager(mock_saga)

        result = await bridge.coordinated_rollback(task_id="task_error", target_phase="analysis")

        assert result is False
        events = bridge.get_events()
        completed = [e for e in events if e.event_type == SyncEventType.ROLLBACK_COMPLETED][0]
        assert "Saga error" in str(completed.data["errors"])


class TestValidation:
    """Test cross-system validation."""

    def setup_method(self):
        reset_sync_bridge()

    def test_validate_both_systems_consistent(self):
        """Validation passes when both systems agree."""
        bridge = OrchestratorSyncBridge()

        # Mock consistent state
        mock_saga = Mock()
        mock_saga.task_id = "task_valid"
        mock_saga.checkpointed_phases = ["analysis", "debate"]
        mock_saga.recovery_point = "consolidation"
        mock_saga.context = Mock()
        mock_saga.context.to_dict.return_value = {}
        bridge.set_saga_manager(mock_saga)

        mock_session = Mock()
        mock_task = Mock()
        mock_task.status = Mock()
        mock_task.status.value = "completed"
        mock_task.roles = {}
        mock_task.metadata = {"checkpoints": {"cp_1": {}}}
        mock_session.get_task.return_value = mock_task
        bridge.set_session_manager(mock_session)

        result = bridge.validate_consistency("task_valid")

        assert result["consistent"] is True
        assert result["issues"] == []

    def test_validate_detects_status_mismatch(self):
        """Validation detects status mismatch."""
        bridge = OrchestratorSyncBridge()

        # Saga says not complete
        mock_saga = Mock()
        mock_saga.task_id = "task_mismatch"
        mock_saga.checkpointed_phases = ["analysis"]
        mock_saga.recovery_point = "analysis"
        mock_saga.context = Mock()
        mock_saga.context.to_dict.return_value = {}
        bridge.set_saga_manager(mock_saga)

        # Swarm says completed
        mock_session = Mock()
        mock_task = Mock()
        mock_task.status = Mock()
        mock_task.status.value = "completed"
        mock_task.roles = {}
        mock_task.metadata = {}
        mock_session.get_task.return_value = mock_task
        bridge.set_session_manager(mock_session)

        result = bridge.validate_consistency("task_mismatch")

        assert result["consistent"] is False
        assert any("Swarm completed but Saga" in issue for issue in result["issues"])

    def test_validate_missing_task_in_swarm(self):
        """Validation detects missing task in Swarm."""
        bridge = OrchestratorSyncBridge()

        mock_session = Mock()
        mock_session.get_task.return_value = None
        bridge.set_session_manager(mock_session)

        result = bridge.validate_consistency("task_missing")

        assert result["consistent"] is False
        assert "not found in SwarmSessionManager" in result["issues"][0]


class TestEventManagement:
    """Test event recording and retrieval."""

    def setup_method(self):
        reset_sync_bridge()

    def test_events_recorded(self):
        """Events are recorded in history."""
        bridge = OrchestratorSyncBridge()

        bridge.create_unified_task("Task 1", "PARALLEL")
        bridge.create_unified_task("Task 2", "SEQUENTIAL")

        events = bridge.get_events()

        assert len(events) == 2
        assert all(e.event_type == SyncEventType.TASK_CREATED for e in events)

    def test_filter_events_by_task(self):
        """Events can be filtered by task ID."""
        bridge = OrchestratorSyncBridge()

        task1 = bridge.create_unified_task("Task 1", "PARALLEL")
        bridge.create_unified_task("Task 2", "SEQUENTIAL")

        events = bridge.get_events(task_id=task1)

        assert len(events) == 1
        assert events[0].task_id == task1

    def test_filter_events_by_type(self):
        """Events can be filtered by type."""
        bridge = OrchestratorSyncBridge()
        bridge.create_unified_task("Task", "PARALLEL")

        events = bridge.get_events(event_type=SyncEventType.TASK_CREATED)

        assert len(events) == 1
        assert events[0].event_type == SyncEventType.TASK_CREATED

    def test_clear_events(self):
        """Events can be cleared."""
        bridge = OrchestratorSyncBridge()
        bridge.create_unified_task("Task 1", "PARALLEL")
        bridge.create_unified_task("Task 2", "SEQUENTIAL")

        count = bridge.clear_events()

        assert count == 2
        assert len(bridge.get_events()) == 0

    def test_on_sync_callback(self):
        """Callbacks are invoked for events."""
        bridge = OrchestratorSyncBridge()
        events_received = []

        def callback(event):
            events_received.append(event)

        bridge.on_sync(callback)
        bridge.create_unified_task("Task", "PARALLEL")

        assert len(events_received) == 1
        assert events_received[0].event_type == SyncEventType.TASK_CREATED


class TestGlobalSingleton:
    """Test global singleton functions."""

    def setup_method(self):
        reset_sync_bridge()

    def test_get_sync_bridge_creates_singleton(self):
        """get_sync_bridge creates singleton on first call."""
        bridge1 = get_sync_bridge()
        bridge2 = get_sync_bridge()

        assert bridge1 is bridge2

    def test_reset_sync_bridge(self):
        """reset_sync_bridge clears the singleton."""
        bridge1 = get_sync_bridge()
        reset_sync_bridge()
        bridge2 = get_sync_bridge()

        assert bridge1 is not bridge2


class TestStatus:
    """Test status reporting."""

    def setup_method(self):
        reset_sync_bridge()

    def test_get_status_empty(self):
        """Status returned when empty."""
        bridge = OrchestratorSyncBridge()

        status = bridge.get_status()

        assert status["saga_connected"] is False
        assert status["session_connected"] is False
        assert status["total_events"] == 0

    def test_get_status_with_managers(self):
        """Status shows connected managers."""
        bridge = OrchestratorSyncBridge()

        mock_saga = Mock()
        mock_saga.task_id = "task_123"
        bridge.set_saga_manager(mock_saga)

        mock_session = Mock()
        mock_session.get_stats.return_value = {"total_tasks": 5}
        bridge.set_session_manager(mock_session)

        bridge.create_unified_task("Task", "PARALLEL")

        status = bridge.get_status()

        assert status["saga_connected"] is True
        assert status["session_connected"] is True
        assert status["total_events"] == 1
        assert "task_123" in status["saga_task_id"]

    def test_repr(self):
        """Repr shows connection state."""
        bridge = OrchestratorSyncBridge()
        repr_str = repr(bridge)

        assert "saga=None" in repr_str
        assert "session=None" in repr_str
