"""
Tests for FSM State Transitions - NEXUS V7

Tests the OrchestratorState enum and TransitionGuard logic.
Verifies the TRANSITION_MATRIX is correctly defined.
"""

import sys
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fsm.states import TRANSITION_MATRIX, OrchestratorState, TransitionGuard


class TestOrchestratorStates:
    """Test OrchestratorState enum definition."""

    def test_all_states_defined(self):
        """Verify all expected states exist."""
        expected_states = [
            "IDLE",
            "BRAINSTORMING",
            "EXECUTING_TOOL",
            "VALIDATING_CFL",
            "EVOLUTION_BRAINSTORM",
            "WAITING_USER",
            "ERROR",
            "PANIC",
            "SWARM_ANALYZING",
            "SWARM_NEGOTIATING",
            "SWARM_EXECUTING",
        ]

        actual_states = [s.name for s in OrchestratorState]

        for state in expected_states:
            assert state in actual_states, f"Missing state: {state}"

    def test_state_count(self):
        """Verify total number of states."""
        assert len(OrchestratorState) == 12, "Expected 12 FSM states"

    def test_initial_state_is_idle(self):
        """IDLE should be first state (initial)."""
        states = list(OrchestratorState)
        assert states[0] == OrchestratorState.IDLE

    def test_panic_has_recovery_transition(self):
        """
        V9.3 ISSUE-002: PANIC state now has recovery transition.

        Before V9.3: PANIC was a dead-end, user had to restart session.
        After V9.3: User can recover via /reset command.
        """
        panic_transitions = TRANSITION_MATRIX.get(OrchestratorState.PANIC, {})
        assert "recovery" in panic_transitions, "PANIC should have recovery transition"
        assert panic_transitions["recovery"] == OrchestratorState.IDLE


class TestTransitionGuard:
    """Test TransitionGuard static methods."""

    def test_can_start_brainstorming_valid_input(self):
        """Valid user input should allow brainstorming."""
        assert TransitionGuard.can_start_brainstorming("Hello NEXUS")
        assert TransitionGuard.can_start_brainstorming("Fix the bug")

    def test_can_start_brainstorming_empty_input(self):
        """Empty input should not allow brainstorming."""
        assert not TransitionGuard.can_start_brainstorming("")
        assert not TransitionGuard.can_start_brainstorming("   ")
        assert not TransitionGuard.can_start_brainstorming(None)

    def test_can_execute_tool_valid_message(self):
        """Valid tool use message should allow execution."""
        message = {"action_type": "TOOL_USE", "tool_use": {"tool_name": "read", "arguments": {"path": "file.py"}}}
        assert TransitionGuard.can_execute_tool(message)

    def test_can_execute_tool_invalid_message(self):
        """Invalid messages should not allow tool execution."""
        # Missing action_type
        assert not TransitionGuard.can_execute_tool({})

        # Wrong action_type
        assert not TransitionGuard.can_execute_tool({"action_type": "TALK"})

        # Missing tool_use
        assert not TransitionGuard.can_execute_tool({"action_type": "TOOL_USE"})

        # None tool_use
        assert not TransitionGuard.can_execute_tool({"action_type": "TOOL_USE", "tool_use": None})

    def test_is_task_finished(self):
        """Correctly identify finished tasks."""
        assert TransitionGuard.is_task_finished({"status": "FINISHED"})
        assert not TransitionGuard.is_task_finished({"status": "IN_PROGRESS"})
        assert not TransitionGuard.is_task_finished({})

    def test_should_switch_agent(self):
        """Correctly identify agent switch requests."""
        # Should switch
        assert TransitionGuard.should_switch_agent({"next_agent": "Claude"}, "Gemini")

        # Should NOT switch (same agent)
        assert not TransitionGuard.should_switch_agent({"next_agent": "Gemini"}, "Gemini")

        # Should NOT switch (no next_agent) - returns falsy (None)
        result = TransitionGuard.should_switch_agent({}, "Gemini")
        assert not result  # None is falsy

    def test_is_brainstorm_message(self):
        """Correctly identify brainstorm messages."""
        assert TransitionGuard.is_brainstorm_message({"action_type": "TALK"})
        assert TransitionGuard.is_brainstorm_message({"action_type": "DELEGATE"})
        assert not TransitionGuard.is_brainstorm_message({"action_type": "TOOL_USE"})
        assert not TransitionGuard.is_brainstorm_message({})


class TestTransitionMatrix:
    """Test TRANSITION_MATRIX structure and validity."""

    def test_all_states_in_matrix(self):
        """All states (except EVOLUTION_BRAINSTORM) should be keys in transition matrix.

        Note: EVOLUTION_BRAINSTORM is a special mode that doesn't participate in
        the normal FSM transition matrix - it's handled separately.
        """
        # EVOLUTION_BRAINSTORM is intentionally excluded from the matrix
        excluded_states = {OrchestratorState.EVOLUTION_BRAINSTORM}

        for state in OrchestratorState:
            if state not in excluded_states:
                assert state in TRANSITION_MATRIX, f"State {state} not in TRANSITION_MATRIX"

    def test_idle_transitions(self):
        """IDLE should transition to BRAINSTORMING on user input."""
        idle_transitions = TRANSITION_MATRIX[OrchestratorState.IDLE]
        assert "user_input" in idle_transitions
        assert idle_transitions["user_input"] == OrchestratorState.BRAINSTORMING

    def test_brainstorming_transitions(self):
        """BRAINSTORMING should have tool_use, finished, stagnation transitions."""
        bs_transitions = TRANSITION_MATRIX[OrchestratorState.BRAINSTORMING]

        assert "tool_use" in bs_transitions
        assert bs_transitions["tool_use"] == OrchestratorState.EXECUTING_TOOL

        assert "finished" in bs_transitions
        assert bs_transitions["finished"] == OrchestratorState.WAITING_USER

        assert "stagnation" in bs_transitions
        assert bs_transitions["stagnation"] == OrchestratorState.ERROR

    def test_executing_tool_transitions(self):
        """EXECUTING_TOOL should transition to VALIDATING_CFL."""
        et_transitions = TRANSITION_MATRIX[OrchestratorState.EXECUTING_TOOL]

        assert "tool_completed" in et_transitions
        assert et_transitions["tool_completed"] == OrchestratorState.VALIDATING_CFL

    def test_validating_cfl_transitions(self):
        """VALIDATING_CFL should have success, failure, stalemate transitions."""
        cfl_transitions = TRANSITION_MATRIX[OrchestratorState.VALIDATING_CFL]

        assert "success" in cfl_transitions
        assert cfl_transitions["success"] == OrchestratorState.IDLE

        assert "failure" in cfl_transitions
        assert cfl_transitions["failure"] == OrchestratorState.BRAINSTORMING

        assert "stalemate" in cfl_transitions
        assert cfl_transitions["stalemate"] == OrchestratorState.ERROR

    def test_error_transitions(self):
        """ERROR should have reset and timeout transitions."""
        error_transitions = TRANSITION_MATRIX[OrchestratorState.ERROR]

        assert "reset" in error_transitions
        assert error_transitions["reset"] == OrchestratorState.IDLE

        assert "timeout" in error_transitions
        assert error_transitions["timeout"] == OrchestratorState.PANIC

    def test_swarm_analyzing_transitions(self):
        """SWARM_ANALYZING should have analysis_complete, skip, error."""
        sa_transitions = TRANSITION_MATRIX[OrchestratorState.SWARM_ANALYZING]

        assert "analysis_complete" in sa_transitions
        assert sa_transitions["analysis_complete"] == OrchestratorState.SWARM_NEGOTIATING

        assert "skip_negotiation" in sa_transitions
        assert sa_transitions["skip_negotiation"] == OrchestratorState.SWARM_EXECUTING

    def test_swarm_negotiating_transitions(self):
        """SWARM_NEGOTIATING should have consensus and timeout."""
        sn_transitions = TRANSITION_MATRIX[OrchestratorState.SWARM_NEGOTIATING]

        assert "consensus" in sn_transitions
        assert sn_transitions["consensus"] == OrchestratorState.SWARM_EXECUTING

        assert "timeout" in sn_transitions
        assert sn_transitions["timeout"] == OrchestratorState.SWARM_EXECUTING

    def test_swarm_executing_transitions(self):
        """SWARM_EXECUTING should have execution_complete and continue."""
        se_transitions = TRANSITION_MATRIX[OrchestratorState.SWARM_EXECUTING]

        assert "execution_complete" in se_transitions
        assert se_transitions["execution_complete"] == OrchestratorState.VALIDATING_CFL

        assert "continue" in se_transitions
        assert se_transitions["continue"] == OrchestratorState.SWARM_EXECUTING

    def test_no_transitions_to_invalid_states(self):
        """All transition targets should be valid states."""
        for state, transitions in TRANSITION_MATRIX.items():
            for trigger, target in transitions.items():
                if target is None:
                    continue
                assert isinstance(target, OrchestratorState), f"Invalid target {target} for {state}->{trigger}"


class TestStateFlows:
    """Test common state flow sequences."""

    def test_simple_task_flow(self):
        """Test: IDLE -> BRAINSTORMING -> EXECUTING_TOOL -> VALIDATING_CFL -> IDLE"""
        flow = [
            (OrchestratorState.IDLE, "user_input", OrchestratorState.BRAINSTORMING),
            (OrchestratorState.BRAINSTORMING, "tool_use", OrchestratorState.EXECUTING_TOOL),
            (OrchestratorState.EXECUTING_TOOL, "tool_completed", OrchestratorState.VALIDATING_CFL),
            (OrchestratorState.VALIDATING_CFL, "success", OrchestratorState.IDLE),
        ]

        for from_state, trigger, expected_to_state in flow:
            transitions = TRANSITION_MATRIX[from_state]
            assert trigger in transitions, f"Missing trigger {trigger} from {from_state}"
            assert transitions[trigger] == expected_to_state

    def test_task_finished_flow(self):
        """Test: BRAINSTORMING -> WAITING_USER (finished without tools)"""
        transitions = TRANSITION_MATRIX[OrchestratorState.BRAINSTORMING]
        assert transitions["finished"] == OrchestratorState.WAITING_USER

    def test_error_recovery_flow(self):
        """Test: ERROR -> IDLE (reset)"""
        transitions = TRANSITION_MATRIX[OrchestratorState.ERROR]
        assert transitions["reset"] == OrchestratorState.IDLE

    def test_swarm_flow(self):
        """Test: SWARM_ANALYZING -> SWARM_NEGOTIATING -> SWARM_EXECUTING -> VALIDATING_CFL"""
        flow = [
            (OrchestratorState.SWARM_ANALYZING, "analysis_complete", OrchestratorState.SWARM_NEGOTIATING),
            (OrchestratorState.SWARM_NEGOTIATING, "consensus", OrchestratorState.SWARM_EXECUTING),
            (OrchestratorState.SWARM_EXECUTING, "execution_complete", OrchestratorState.VALIDATING_CFL),
        ]

        for from_state, trigger, expected_to_state in flow:
            transitions = TRANSITION_MATRIX[from_state]
            assert trigger in transitions
            assert transitions[trigger] == expected_to_state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
