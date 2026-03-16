"""
NEXUS V12.4 - Swarm State Handlers

Handles SWARM_ANALYZING, SWARM_NEGOTIATING, and SWARM_EXECUTING states.
"""

from core.fsm.handlers.base import BaseHandler
from core.fsm.states import OrchestratorState


class SwarmHandler(BaseHandler):
    """Handler for Swarm FSM states."""

    def handle_swarm_analyzing(self) -> dict:
        """Handle SWARM_ANALYZING state."""
        if not self._orch.swarm_engine:
            self._orch._transition_to(OrchestratorState.BRAINSTORMING)
            return self._make_result(
                "BRAINSTORMING", "Swarm disabled, using classic mode", self._orch.active_agent, False
            )

        analysis = self._orch.swarm_engine.start_analysis(self._orch.blackboard.get("objective", ""))

        if analysis.should_skip_negotiation:
            self._orch._transition_to(OrchestratorState.SWARM_EXECUTING)
            return self._make_result(
                "SWARM_EXECUTING",
                f"[Swarm] Task trivial - skipping negotiation\n"
                f"Complexity: {analysis.complexity.name}\n"
                f"Mode: {getattr(self._orch.config, 'swarm_default_mode', 'ping_pong')}",
                None,
                False,
            )

        self._orch._transition_to(OrchestratorState.SWARM_NEGOTIATING)
        return self._make_result(
            "SWARM_NEGOTIATING",
            f"[Swarm Analysis]\n"
            f"Complexity: {analysis.complexity.name}\n"
            f"Domains: {', '.join(d.value for d in analysis.domains[:3])}\n"
            f"Gemini fit: {analysis.gemini_fit_score:.0%}\n"
            f"Claude fit: {analysis.claude_fit_score:.0%}\n"
            f"Recommended lead: {analysis.recommended_lead}",
            None,
            False,
        )

    def handle_swarm_negotiating(self) -> dict:
        """Handle SWARM_NEGOTIATING state."""
        if not self._orch.swarm_engine:
            self._orch._transition_to(OrchestratorState.BRAINSTORMING)
            return self._make_result("BRAINSTORMING", "Swarm disabled", self._orch.active_agent, False)

        proposal = self._orch.swarm_engine.start_selection()
        negotiation_result = self._orch.swarm_engine.start_negotiation()

        self._orch._transition_to(OrchestratorState.SWARM_EXECUTING)

        if negotiation_result:
            return self._make_result(
                "SWARM_EXECUTING",
                f"[Swarm Negotiation]\n"
                f"Status: {negotiation_result.status.value}\n"
                f"Selected mode: {negotiation_result.selected_mode.value}\n"
                f"Consensus: {negotiation_result.consensus_confidence:.0%}\n"
                f"Turns: {negotiation_result.total_turns}",
                None,
                False,
            )
        else:
            return self._make_result(
                "SWARM_EXECUTING", f"[Swarm] Using initial proposal: {proposal.mode.value}", None, False
            )

    def handle_swarm_executing(self) -> dict:
        """Handle SWARM_EXECUTING state."""
        if not self._orch.swarm_engine:
            self._orch._transition_to(OrchestratorState.BRAINSTORMING)
            return self._make_result("BRAINSTORMING", "Swarm disabled", self._orch.active_agent, False)

        objective = self._orch.blackboard.get("objective", "")
        execution_result = self._orch.swarm_engine.execute_turn(objective, self._orch.blackboard)

        if execution_result.finished:
            formatted_output = (
                f"[Swarm] Mode: {execution_result.mode.value} | Rounds: {execution_result.total_rounds}\n"
            )
            for agent_output in execution_result.agent_outputs:
                # V8.4.0: Use registry for display name
                agent_name = self._registry.get_display_name(agent_output.agent_id)
                formatted_output += f"\n{agent_name}:\n{agent_output.content}\n---\n"

            self._orch._transition_to(OrchestratorState.VALIDATING_CFL)
            return self._make_result("VALIDATING_CFL", formatted_output, None, False)
        else:
            formatted_output = "[Swarm executing...]\n"
            for agent_output in execution_result.agent_outputs[-2:]:
                # V8.4.0: Use registry for display name
                agent_name = self._registry.get_display_name(agent_output.agent_id)
                formatted_output += f"\n{agent_name}:\n{agent_output.content[:300]}...\n"

            return self._make_result("SWARM_EXECUTING", formatted_output, None, False)
