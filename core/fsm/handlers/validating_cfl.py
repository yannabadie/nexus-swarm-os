"""
NEXUS V12.4 - CFL Validation State Handler

Handles VALIDATING_CFL state - Cognitive Feedback Loop validation.
"""

import sys

from core.execution_pkg.routing.model_router import TaskType
from core.fsm.handlers.base import BaseHandler
from core.fsm.states import OrchestratorState


class ValidatingCFLHandler(BaseHandler):
    """Handler for VALIDATING_CFL state."""

    def handle_validating_cfl(self) -> dict:
        """
        Handle VALIDATING_CFL state - validate tool execution result.

        Returns:
            Result dict
        """
        # Use lightweight context for fast validation
        context = self._build_context_with_tool_result()

        try:
            cfl_timeout = getattr(self._orch.config, "cfl_timeout", 60)

            if self._orch.active_agent == "claude":  # V9.3: lowercase normalized
                driver = self._get_claude_driver(TaskType.VALIDATION, timeout_override=cfl_timeout)
                response = driver.invoke(context)
            else:
                response = self._orch.gemini_driver.invoke(context)

            message = self._validate_message(response, expect_heavy=True)
        except Exception as e:
            if self._orch.panic_system.record_error("CFL_VALIDATION", str(e)):
                return self._orch._trigger_panic(f"CFL validation errors: {e}")
            return self._orch._handle_error(f"CFL validation failed: {e}")

        content = message.get("content", "")
        action_type = message.get("action_type")
        status = message.get("status", "")

        # Check if task finished
        task_finished = (
            status == "FINISHED"
            or action_type == "FINISHED"
            or "task complete" in content.lower()
            or "tâche terminée" in content.lower()
        )

        # Determine validation success
        if "[OK]" in content or "success" in content.lower() or "successfully" in content.lower():
            validation_success = True
        elif "[NO]" in content or "error" in content.lower() or "failed" in content.lower():
            validation_success = False
        else:
            # V10 FIX F8: Conservative default - ambiguity = failure
            validation_success = False
            self._logger.warning("CFL validation ambiguous (no success/error markers), defaulting to failure")

        # Reset pending result
        self._orch.pending_tool_result = None

        if task_finished:
            self._orch.stalemate_counter = 0
            self._orch.panic_system.reset_stalemate()
            self._orch.panic_system.reset_errors()
            self._orch._transition_to(OrchestratorState.IDLE)
            return self._make_result("FINISHED", f"[OK] {content}", self._orch.active_agent, True)

        elif validation_success:
            self._orch.stalemate_counter = 0
            self._orch.panic_system.reset_stalemate()
            self._orch.panic_system.reset_errors()

            # V8.4.0: Use registry for alternation
            previous_agent = self._orch.active_agent
            self._orch.active_agent = self._registry.get_alternate(self._orch.active_agent) or self._orch.active_agent
            if self._orch.config.ui_verbose:
                print(
                    f"[CFL SUCCESS] {self._registry.get_display_name(previous_agent)} -> {self._registry.get_display_name(self._orch.active_agent)}",
                    file=sys.stderr,
                )

            self._orch._transition_to(OrchestratorState.BRAINSTORMING)
            return self._make_result("BRAINSTORMING", f"[OK] {content}", previous_agent, False)

        else:
            # V9.3 ISSUE-004 FIX: Removed duplicate increment
            # BEFORE: Both self._orch.stalemate_counter AND panic_system.stalemate_counter
            # were incremented, causing stalemate detection at half the expected threshold.
            # NOW: Only panic_system tracks stalemate counter (single source of truth)

            if self._orch.panic_system.check_stalemate():
                return self._orch._trigger_panic(f"Stalemate: {self._orch.panic_system.stalemate_counter} failures")

            # V8.4.0: Use registry for alternation
            previous_agent = self._orch.active_agent
            self._orch.active_agent = self._registry.get_alternate(self._orch.active_agent) or self._orch.active_agent

            self._orch._transition_to(OrchestratorState.BRAINSTORMING)
            return self._make_result("BRAINSTORMING", f"[NO] {content}", previous_agent, False)
