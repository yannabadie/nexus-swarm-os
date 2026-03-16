"""
NEXUS V12.4 - Tool Execution State Handler

Handles EXECUTING_TOOL state.
"""

import sys

from core.fsm.handlers.base import BaseHandler
from core.fsm.states import OrchestratorState
from core.synapse.protocol_v7 import ToolUse


class ExecutingToolHandler(BaseHandler):
    """Handler for EXECUTING_TOOL state."""

    def handle_executing_tool(self) -> dict:
        """
        Handle EXECUTING_TOOL state - execute requested tool.

        Returns:
            Result dict
        """
        # Get tool from last message
        last_message = self._orch.memory.get_last_message()
        tool_request = ToolUse(**last_message["tool_use"])

        # Execute (synchronous)
        result = self._orch.tool_manager.execute(tool_request)
        self._orch.pending_tool_result = result

        # Switch to OTHER agent for CFL validation (V8.4.0: via registry)
        requesting_agent = self._orch.active_agent
        self._orch.active_agent = self._registry.get_alternate(self._orch.active_agent) or self._orch.active_agent
        if self._orch.config.ui_verbose:
            print(
                f"[CFL] {self._registry.get_display_name(requesting_agent)} tool -> {self._registry.get_display_name(self._orch.active_agent)} validates",
                file=sys.stderr,
            )

        # Transition to CFL validation
        self._orch._transition_to(OrchestratorState.VALIDATING_CFL)

        return self._make_result("VALIDATING_CFL", self._orch._format_tool_result(result), requesting_agent, False)
