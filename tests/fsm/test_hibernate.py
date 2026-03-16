"""
V12.2 IRONCLAD - HIBERNATE State Tests

Tests:
- HIBERNATE state exists in OrchestratorState
- State transitions to/from HIBERNATE
- HibernationManager persistence
- TTL expiration

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.infrastructure.db.engine import init_db, reset_engine


class TestHibernateState:
    """Tests for HIBERNATE FSM state definition."""

    def test_hibernate_state_exists(self):
        """Verify HIBERNATE state is defined."""
        from core.fsm.states import OrchestratorState

        assert hasattr(OrchestratorState, "HIBERNATE")

    def test_hibernate_in_transition_matrix(self):
        """Verify HIBERNATE transitions are defined."""
        from core.fsm.states import TRANSITION_MATRIX, OrchestratorState

        assert OrchestratorState.HIBERNATE in TRANSITION_MATRIX

        hibernate_transitions = TRANSITION_MATRIX[OrchestratorState.HIBERNATE]
        assert "ws_reconnect" in hibernate_transitions
        assert "timeout" in hibernate_transitions
        assert "user_cancel" in hibernate_transitions

    def test_hibernate_exit_transitions(self):
        """Verify HIBERNATE exits to correct states."""
        from core.fsm.states import TRANSITION_MATRIX, OrchestratorState

        hibernate_transitions = TRANSITION_MATRIX[OrchestratorState.HIBERNATE]

        # timeout and user_cancel should go to IDLE
        assert hibernate_transitions["timeout"] == OrchestratorState.IDLE
        assert hibernate_transitions["user_cancel"] == OrchestratorState.IDLE

        # ws_reconnect is dynamic (returns to previous state)
        assert hibernate_transitions["ws_reconnect"] is None

    def test_active_states_can_enter_hibernate(self):
        """Verify active states can transition to HIBERNATE."""
        from core.fsm.states import ACTIVE_STATES, TRANSITION_MATRIX, OrchestratorState

        for state in ACTIVE_STATES:
            transitions = TRANSITION_MATRIX.get(state, {})
            assert "ws_disconnect" in transitions, f"{state} should transition to HIBERNATE"
            assert transitions["ws_disconnect"] == OrchestratorState.HIBERNATE


class TestHibernationManager:
    """Tests for HibernationManager persistence."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_enter_hibernate(self):
        """Test entering hibernation saves state."""
        from core.fsm.hibernation_manager import HibernationManager

        tenant_id = uuid4()
        workspace_id = "test-workspace"

        result = await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            previous_state="BRAINSTORMING",
            fsm_context={"task": "test task"},
            active_agent="claude",
            turn_count=5,
        )

        assert result is not None
        assert result["tenant_id"] == tenant_id
        assert result["workspace_id"] == workspace_id
        assert result["previous_state"] == "BRAINSTORMING"

    @pytest.mark.asyncio
    async def test_get_hibernation(self):
        """Test retrieving hibernation state."""
        from core.fsm.hibernation_manager import HibernationManager

        tenant_id = uuid4()
        workspace_id = "test-workspace"

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            previous_state="EXECUTING_TOOL",
        )

        state = await HibernationManager.get_hibernation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        assert state is not None
        assert state["previous_state"] == "EXECUTING_TOOL"

    @pytest.mark.asyncio
    async def test_exit_hibernate(self):
        """Test exiting hibernation returns and clears state."""
        from core.fsm.hibernation_manager import HibernationManager

        tenant_id = uuid4()
        workspace_id = "test-workspace"

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            previous_state="VALIDATING_CFL",
            fsm_context={"result": "test"},
        )

        restored = await HibernationManager.exit_hibernate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        assert restored is not None
        assert restored["previous_state"] == "VALIDATING_CFL"
        assert restored["fsm_context"] == {"result": "test"}

        # Should be cleared now
        state = await HibernationManager.get_hibernation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        assert state is None

    @pytest.mark.asyncio
    async def test_no_hibernation_returns_none(self):
        """Test getting nonexistent hibernation returns None."""
        from core.fsm.hibernation_manager import HibernationManager

        state = await HibernationManager.get_hibernation(
            tenant_id=uuid4(),
            workspace_id="nonexistent",
        )

        assert state is None

    @pytest.mark.asyncio
    async def test_exit_nonexistent_returns_none(self):
        """Test exiting nonexistent hibernation returns None."""
        from core.fsm.hibernation_manager import HibernationManager

        restored = await HibernationManager.exit_hibernate(
            tenant_id=uuid4(),
            workspace_id="nonexistent",
        )

        assert restored is None

    @pytest.mark.asyncio
    async def test_new_hibernate_replaces_old(self):
        """Test entering hibernation replaces existing state."""
        from core.fsm.hibernation_manager import HibernationManager

        tenant_id = uuid4()
        workspace_id = "test-workspace"

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            previous_state="BRAINSTORMING",
        )

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            previous_state="EXECUTING_TOOL",
        )

        state = await HibernationManager.get_hibernation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        assert state["previous_state"] == "EXECUTING_TOOL"


class TestHibernationStateModel:
    """Tests for HibernationState SQLModel."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    def test_model_fields(self):
        """Test HibernationState has required fields."""
        from core.fsm.hibernation_manager import HibernationState

        state = HibernationState(
            tenant_id=uuid4(),
            workspace_id="test",
            previous_state="BRAINSTORMING",
        )

        assert state.previous_state == "BRAINSTORMING"
        assert state.is_active
        assert state.turn_count == 0

    def test_is_expired(self):
        """Test expiration detection."""
        from core.fsm.hibernation_manager import HibernationState

        state = HibernationState(
            tenant_id=uuid4(),
            workspace_id="test",
            previous_state="IDLE",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )

        assert state.is_expired()

    def test_not_expired(self):
        """Test non-expired state."""
        from core.fsm.hibernation_manager import HibernationState

        state = HibernationState(
            tenant_id=uuid4(),
            workspace_id="test",
            previous_state="IDLE",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        assert not state.is_expired()


class TestHibernationWorkspaceIsolation:
    """Tests for workspace isolation in hibernation."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_different_workspaces_independent(self):
        """Test that different workspaces have independent hibernation."""
        from core.fsm.hibernation_manager import HibernationManager

        tenant_id = uuid4()

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id="workspace-a",
            previous_state="BRAINSTORMING",
        )

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_id,
            workspace_id="workspace-b",
            previous_state="EXECUTING_TOOL",
        )

        state_a = await HibernationManager.get_hibernation(tenant_id, "workspace-a")
        state_b = await HibernationManager.get_hibernation(tenant_id, "workspace-b")

        assert state_a["previous_state"] == "BRAINSTORMING"
        assert state_b["previous_state"] == "EXECUTING_TOOL"

    @pytest.mark.asyncio
    async def test_different_tenants_independent(self):
        """Test that different tenants have independent hibernation."""
        from core.fsm.hibernation_manager import HibernationManager

        tenant_a = uuid4()
        tenant_b = uuid4()

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_a,
            workspace_id="default",
            previous_state="BRAINSTORMING",
        )

        await HibernationManager.enter_hibernate(
            tenant_id=tenant_b,
            workspace_id="default",
            previous_state="EXECUTING_TOOL",
        )

        state_a = await HibernationManager.get_hibernation(tenant_a, "default")
        state_b = await HibernationManager.get_hibernation(tenant_b, "default")

        assert state_a["previous_state"] == "BRAINSTORMING"
        assert state_b["previous_state"] == "EXECUTING_TOOL"
