"""
Tests for StateHandler - P5.1 Phase 4 Extraction

Validates state management logic extracted from OrchestratorV7.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.orchestration.state_handler import StateHandler
from core.fsm.states import OrchestratorState


class TestStateHandler:
    """Test StateHandler state management."""

    @pytest.fixture
    def mock_orch(self):
        """Create mock orchestrator."""
        orch = Mock()
        orch.state = OrchestratorState.IDLE
        orch.iteration = 0
        orch._event_count = 0
        orch._session_uuid = "test-session"
        orch.config = Mock()
        orch.config.ui_verbose = False
        orch.memory = Mock()
        orch.tool_manager = Mock()
        orch.tool_manager.evolution_mode = False
        orch._snapshot_manager = Mock()
        orch._snapshot_manager.should_snapshot.return_value = False
        orch.stagnation_detector = Mock()
        orch.stalemate_counter = 0
        orch.pending_tool_result = None
        orch.json_parse_failures = 0
        orch.panic_system = Mock()
        orch.plan_health = Mock()
        orch.blackboard = {}
        return orch

    @pytest.fixture
    def handler(self, mock_orch):
        """Create StateHandler instance."""
        return StateHandler(mock_orch)

    # =========================================================================
    # Property tests
    # =========================================================================

    def test_current_state_property(self, handler, mock_orch):
        """current_state should return orchestrator's state."""
        mock_orch.state = OrchestratorState.BRAINSTORMING
        assert handler.current_state == OrchestratorState.BRAINSTORMING

    # =========================================================================
    # transition_to() tests
    # =========================================================================

    def test_transition_to_basic(self, handler, mock_orch):
        """transition_to should change orchestrator state."""
        handler.transition_to(OrchestratorState.BRAINSTORMING)

        assert mock_orch.state == OrchestratorState.BRAINSTORMING
        mock_orch.memory.save_to_disk.assert_called_once()

    def test_transition_to_verbose_output(self, handler, mock_orch, capsys):
        """transition_to should print if ui_verbose enabled."""
        mock_orch.config.ui_verbose = True

        handler.transition_to(OrchestratorState.EXECUTING_TOOL)

        captured = capsys.readouterr()
        assert "[FSM]" in captured.out
        assert "IDLE" in captured.out
        assert "EXECUTING_TOOL" in captured.out

    @patch("core.execution_pkg.orchestration.state_handler.get_tracer")
    def test_transition_to_otel_span(self, mock_get_tracer, handler, mock_orch):
        """transition_to should create OTel span if tracer available."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_get_tracer.return_value = mock_tracer

        handler.transition_to(OrchestratorState.BRAINSTORMING)

        mock_span.set_attribute.assert_any_call("nexus.from_state", "IDLE")
        mock_span.set_attribute.assert_any_call("nexus.to_state", "BRAINSTORMING")

    @patch("core.execution_pkg.orchestration.state_handler.record_transition")
    def test_transition_to_event_sourcing(self, mock_record, handler, mock_orch):
        """transition_to should record transition event."""
        handler.transition_to(OrchestratorState.VALIDATING_CFL)

        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["from_state"] == "IDLE"
        assert call_kwargs["to_state"] == "VALIDATING_CFL"
        assert call_kwargs["trigger"] == "fsm_transition"

    def test_transition_to_increments_event_count(self, handler, mock_orch):
        """transition_to should increment event counter."""
        initial_count = mock_orch._event_count

        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.transition_to(OrchestratorState.BRAINSTORMING)

        assert mock_orch._event_count == initial_count + 1

    @patch("core.execution_pkg.orchestration.state_handler.record_transition")
    def test_transition_to_creates_snapshot(self, mock_record, handler, mock_orch):
        """transition_to should create snapshot periodically."""
        mock_orch._snapshot_manager.should_snapshot.return_value = True
        mock_orch._snapshot_manager.create_snapshot.return_value = {"snapshot": "data"}

        handler.transition_to(OrchestratorState.BRAINSTORMING)

        mock_orch._snapshot_manager.create_snapshot.assert_called_once()
        call_args = mock_orch._snapshot_manager.create_snapshot.call_args
        fsm_state = call_args.args[0]
        assert fsm_state["current_state"] == "BRAINSTORMING"
        assert fsm_state["previous_state"] == "IDLE"

    def test_transition_to_panic_creates_backup(self, handler, mock_orch):
        """transition_to PANIC should create memory backup."""
        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.transition_to(OrchestratorState.PANIC)

        mock_orch.memory.create_backup.assert_called_once_with(reason="transition_panic")

    def test_transition_to_error_creates_backup(self, handler, mock_orch):
        """transition_to ERROR should create memory backup."""
        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.transition_to(OrchestratorState.ERROR)

        mock_orch.memory.create_backup.assert_called_once_with(reason="transition_error")

    def test_transition_to_evolution_mode_enabled(self, handler, mock_orch):
        """transition_to EVOLUTION_BRAINSTORM should enable evolution mode."""
        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.transition_to(OrchestratorState.EVOLUTION_BRAINSTORM)

        assert mock_orch.tool_manager.evolution_mode is True

    def test_transition_to_evolution_mode_disabled(self, handler, mock_orch):
        """leaving EVOLUTION_BRAINSTORM should disable evolution mode."""
        # First enter evolution mode
        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.transition_to(OrchestratorState.EVOLUTION_BRAINSTORM)

        assert mock_orch.tool_manager.evolution_mode is True

        # Then leave it
        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.transition_to(OrchestratorState.IDLE)

        assert mock_orch.tool_manager.evolution_mode is False

    # =========================================================================
    # reset_to_idle() tests
    # =========================================================================

    def test_reset_to_idle_transitions(self, handler, mock_orch):
        """reset_to_idle should transition to IDLE."""
        mock_orch.state = OrchestratorState.ERROR

        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.reset_to_idle()

        assert mock_orch.state == OrchestratorState.IDLE

    def test_reset_to_idle_clears_state(self, handler, mock_orch):
        """reset_to_idle should clear execution state."""
        mock_orch.stalemate_counter = 5
        mock_orch.pending_tool_result = {"some": "result"}
        mock_orch.json_parse_failures = 3

        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.reset_to_idle()

        mock_orch.stagnation_detector.reset.assert_called_once()
        mock_orch.panic_system.clear_panic.assert_called_once()
        mock_orch.plan_health.reset.assert_called_once()
        assert mock_orch.stalemate_counter == 0
        assert mock_orch.pending_tool_result is None
        assert mock_orch.json_parse_failures == 0

    def test_reset_to_idle_clears_task(self, handler, mock_orch):
        """reset_to_idle with clear_task=True should clear blackboard."""
        mock_orch.blackboard = {
            "objective": "Some task",
            "strategic_plan": ["step1", "step2"],
            "recent_history": ["msg1", "msg2"],
        }

        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.reset_to_idle(clear_task=True)

        assert mock_orch.blackboard["objective"] == ""
        assert mock_orch.blackboard["strategic_plan"] == []
        assert mock_orch.blackboard["recent_history"] == []
        assert mock_orch.memory.save_to_disk.call_count == 2  # transition + reset

    def test_reset_to_idle_preserves_task(self, handler, mock_orch):
        """reset_to_idle with clear_task=False should preserve blackboard."""
        mock_orch.blackboard = {"objective": "Some task", "strategic_plan": ["step1"], "recent_history": ["msg1"]}

        with patch("core.execution_pkg.orchestration.state_handler.record_transition"):
            handler.reset_to_idle(clear_task=False)

        # Blackboard should not be modified
        assert mock_orch.blackboard["objective"] == "Some task"
        assert mock_orch.blackboard["strategic_plan"] == ["step1"]

    # =========================================================================
    # can_transition() tests
    # =========================================================================

    @patch(
        "core.execution_pkg.orchestration.state_handler.TRANSITION_MATRIX",
        {
            OrchestratorState.IDLE: {OrchestratorState.BRAINSTORMING, OrchestratorState.WAITING_USER},
            OrchestratorState.BRAINSTORMING: {OrchestratorState.EXECUTING_TOOL, OrchestratorState.VALIDATING_CFL},
        },
    )
    def test_can_transition_allowed(self, handler):
        """can_transition should return True for allowed transitions."""
        assert handler.can_transition(OrchestratorState.IDLE, OrchestratorState.BRAINSTORMING)

    @patch(
        "core.execution_pkg.orchestration.state_handler.TRANSITION_MATRIX",
        {OrchestratorState.IDLE: {OrchestratorState.BRAINSTORMING}},
    )
    def test_can_transition_not_allowed(self, handler):
        """can_transition should return False for disallowed transitions."""
        assert not handler.can_transition(
            OrchestratorState.IDLE,
            OrchestratorState.EXECUTING_TOOL,  # Not in allowed set
        )

    def test_can_transition_fallback(self, handler):
        """can_transition should allow all if TRANSITION_MATRIX unavailable."""
        with patch("core.execution_pkg.orchestration.state_handler.TRANSITION_MATRIX", None):
            # Should allow any transition as fallback
            result = handler.can_transition(OrchestratorState.IDLE, OrchestratorState.PANIC)
            assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
