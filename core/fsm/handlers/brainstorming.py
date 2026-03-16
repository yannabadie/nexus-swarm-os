"""
NEXUS V12.4 - Brainstorming State Handler

Handles BRAINSTORMING state - agent debate and tool consensus.
"""

import sys
import time

from core.execution_pkg.routing.model_router import TaskType
from core.fsm.handlers.base import BaseHandler
from core.fsm.states import OrchestratorState

# V13.0 CEREBRO LIVE: Agent exchange telemetry
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak


class BrainstormingHandler(BaseHandler):
    """Handler for BRAINSTORMING state."""

    def handle_brainstorming(self) -> dict:
        """
        Handle BRAINSTORMING state - agent debate and tool consensus.

        Returns:
            Result dict
        """
        # Check plan health (ZOMBIE detection)
        current_plan = self._orch.blackboard.get("strategic_plan", [])
        health = self._orch.plan_health.check_health(current_plan, self._orch.iteration)

        if health["status"] == "ZOMBIE":
            # Plan zombie -> Trigger panic
            self._orch.panic_system.trigger_panic_explicit(reason="ZOMBIE_PLAN", details=health["message"])
            return self._orch._trigger_panic(f"Plan zombie: {health['message']}")

        elif health["status"] in ["STAGNANT", "WARNING"]:
            # Log warning but continue
            if self._orch.config.ui_verbose:
                print(f"[PLAN HEALTH] {health['status']}: {health['message']}")

        # Check stagnation
        if self._orch.stagnation_detector.is_stagnant():
            return self._orch._handle_stagnation()

        # Invoke active agent
        context = self._build_context()
        invoke_start = time.time()

        try:
            response = self._invoke_agent(TaskType.BRAINSTORM, context)
            invoke_duration = time.time() - invoke_start
            message = self._validate_message(response)
            self._orch.json_parse_failures = 0
            self._orch.panic_system.reset_errors()

            # Calculate quality score
            is_stagnant = self._orch.stagnation_detector.is_stagnant()
            quality = self._calculate_quality_score(message, True, is_stagnant)
            self._record_invocation(self._orch.active_agent, "brainstorm", True, invoke_duration, quality)

        except Exception as e:
            invoke_duration = time.time() - invoke_start
            self._orch.json_parse_failures += 1
            self._record_invocation(self._orch.active_agent, "brainstorm", False, invoke_duration, 0.0)

            if self._orch.panic_system.record_error("AGENT_INVOCATION", str(e)):
                return self._orch._trigger_panic(f"Too many consecutive errors: {e}")

            if self._orch.json_parse_failures >= self._orch.max_parse_failures:
                return self._orch._trigger_panic(f"Agent consistently failing: {e}")

            return self._orch._handle_error(f"Agent invocation failed: {e}")

        # Save to history
        self._orch.memory.add_to_history(message)

        # Analyze action_type
        action_type = message.get("action_type")
        content = message.get("content", "")

        # V13.0 CEREBRO LIVE: Emit agent exchange for brainstorming
        sender = message.get("sender", self._orch.active_agent)
        next_agent = self._registry.get_alternate(self._orch.active_agent) or "user"
        emit_agent_speak(sender, content, action_type or "TALK")
        emit_agent_exchange(sender, next_agent, content, exchange_type="brainstorm")

        if action_type == "TOOL_USE":
            # Consensus reached -> Execute tool
            self._orch._transition_to(OrchestratorState.EXECUTING_TOOL)
            tool_name = message.get("tool_use", {}).get("tool_name", "unknown")
            emit_agent_exchange(sender, "tool_executor", f"Execute: {tool_name}", exchange_type="tool")
            return self._make_result("EXECUTING_TOOL", content, self._orch.active_agent, False, tool=tool_name)

        elif action_type in ["TALK", "DELEGATE"]:
            # Continue brainstorming
            self._orch.stagnation_detector.add_message(content)
            sender = message.get("sender", self._orch.active_agent)

            # FORCE alternance Gemini↔Claude (V8.4.0: via registry)
            previous_agent = self._orch.active_agent
            self._orch.active_agent = self._registry.get_alternate(self._orch.active_agent) or self._orch.active_agent
            self._orch.stagnation_detector.reset()
            if self._orch.config.ui_verbose:
                print(
                    f"[BRAINSTORM] {self._registry.get_display_name(previous_agent)} -> {self._registry.get_display_name(self._orch.active_agent)}",
                    file=sys.stderr,
                )

            return self._make_result("BRAINSTORMING", content, sender, False)

        elif message.get("status") == "FINISHED":
            # Task complete
            self._orch._transition_to(OrchestratorState.IDLE)
            return self._make_result("FINISHED", content, self._orch.active_agent, True)

        # Fallback
        return self._make_result("BRAINSTORMING", content, self._orch.active_agent, False)
