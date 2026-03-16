"""
NEXUS V12.4 - Evolution State Handler

Handles EVOLUTION_BRAINSTORM state - special debate mode for mutations.
"""

import time

from core.execution_pkg.routing.model_router import TaskType
from core.fsm.handlers.base import BaseHandler
from core.fsm.states import OrchestratorState

# V13.0 CEREBRO LIVE: Agent exchange telemetry
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak
from core.security_pkg.governance.sandbox_policy import SandboxPolicy
from core.synapse.protocol_v7 import ToolUse


class EvolutionHandler(BaseHandler):
    """Handler for EVOLUTION_BRAINSTORM state."""

    def handle_evolution_brainstorm(self, user_input: str | None = None) -> dict:
        """
        Handle EVOLUTION_BRAINSTORM state - special debate mode for mutations.

        Args:
            user_input: Optional new objective

        Returns:
            Result dict
        """
        # If user_input provided, set as objective
        if user_input:
            self._orch.blackboard["objective"] = user_input
            self._orch.blackboard["current_state"]["iteration"] = self._orch.iteration
            self._orch.memory.save_to_disk()

        # Check stagnation
        if self._orch.stagnation_detector.is_stagnant():
            return self._make_result(
                "EVOLUTION_BRAINSTORM", "Evolution debate may be stagnant", self._orch.active_agent, False
            )

        # Invoke agent
        context = self._build_context()
        invoke_start = time.time()

        try:
            response = self._invoke_agent(TaskType.EVOLUTION, context)
            invoke_duration = time.time() - invoke_start
            message = self._validate_message(response)
            self._orch.json_parse_failures = 0
            self._orch.panic_system.reset_errors()

            is_stagnant = self._orch.stagnation_detector.is_stagnant()
            quality = self._calculate_quality_score(message, True, is_stagnant)
            self._record_invocation(self._orch.active_agent, "evolution", True, invoke_duration, quality)

        except Exception as e:
            invoke_duration = time.time() - invoke_start
            self._orch.json_parse_failures += 1
            self._record_invocation(self._orch.active_agent, "evolution", False, invoke_duration, 0.0)
            return self._make_result(
                "EVOLUTION_BRAINSTORM", f"Evolution debate error: {e}", self._orch.active_agent, False, error=str(e)
            )

        # Save to history
        self._orch.memory.add_to_history(message)

        action_type = message.get("action_type")
        content = message.get("content", "")
        sender = message.get("sender", self._orch.active_agent)
        self._orch.stagnation_detector.add_message(content)

        # V13.0 CEREBRO LIVE: Emit agent exchange for evolution debate
        next_agent = self._registry.get_alternate(self._orch.active_agent) or "user"
        emit_agent_speak(sender, content, action_type or "TALK")
        emit_agent_exchange(sender, next_agent, content, exchange_type="evolution")

        # Check if finished with valid mutation
        if message.get("status") == "FINISHED":
            has_valid_json = self._detect_mutation_complete(content)
            if has_valid_json:
                self._orch._transition_to(OrchestratorState.IDLE)
                emit_agent_exchange(sender, "user", "Evolution complete!", exchange_type="finished")
                return self._make_result("FINISHED", content, sender, True)

        # FORCE alternation (V8.4.0: via registry)
        self._orch.active_agent = self._registry.get_alternate(self._orch.active_agent) or self._orch.active_agent
        self._orch.stagnation_detector.reset()

        # Handle TOOL_USE
        if action_type == "TOOL_USE":
            emit_agent_exchange(sender, "tool_executor", "Evolution tool call", exchange_type="tool")
            return self._handle_evolution_tool(message, sender, content)

        # Check for mutation JSON
        finished = self._detect_mutation_complete(content)
        if finished:
            self._logger.info("[EVOLUTION_BRAINSTORM] Valid mutation JSON detected - signaling finished")
        return self._make_result("EVOLUTION_BRAINSTORM", content, sender, finished)

    def _handle_evolution_tool(self, message: dict, sender: str, content: str) -> dict:
        """Handle tool use during evolution brainstorming."""
        tool_use = message.get("tool_use", {})
        tool_name = tool_use.get("tool_name", "unknown")

        # Check if tool is blocked
        if SandboxPolicy.is_tool_blocked(tool_name):
            reason = SandboxPolicy.get_blocked_reason(tool_name)
            return self._make_result(
                "EVOLUTION_BRAINSTORM",
                f"{content}\n\n[Blocked: {tool_name}] {reason}. Propose mutations in JSON format instead.",
                sender,
                False,
            )

        try:
            # Normalize and execute tool
            normalized_name = self._orch.tool_manager.TOOL_ALIASES.get(tool_name, tool_name)
            normalized_tool_use = {**tool_use, "tool_name": normalized_name}

            tool_request = ToolUse(**normalized_tool_use)
            result = self._orch.tool_manager.execute(tool_request)

            # Format result
            result_text = f"[{sender} executed: {tool_name}]\n"
            if result.status.lower() == "success":
                output = result.output[:3000] if len(result.output) > 3000 else result.output
                result_text += f"[OK] Result:\n{output}"
            else:
                result_text += f"[NO] Error: {result.error or 'Unknown error'}"

            # Add to history
            self._orch.memory.add_to_history({"sender": "System", "action_type": "TOOL_RESULT", "content": result_text})

            return self._make_result("EVOLUTION_BRAINSTORM", result_text, sender, False)

        except Exception as e:
            return self._make_result(
                "EVOLUTION_BRAINSTORM", f"{content}\n\n[Tool error: {tool_name}] {e}", sender, False
            )
