"""
NEXUS V12.4 - Error State Handlers

Handles ERROR and PANIC states.
"""

from core.fsm.handlers.base import BaseHandler


class ErrorHandler(BaseHandler):
    """Handler for ERROR and PANIC states."""

    def handle_error(self) -> dict:
        """Handle ERROR state."""
        return self._make_result("ERROR", "System in error state. Use /reset", None, False, error="ERROR")

    def handle_panic(self) -> dict:
        """
        Handle PANIC state.

        V9.3 ISSUE-002: Now recoverable via /reset command.
        Before V9.3, PANIC had no exit - user had to restart session.
        """
        return self._make_result(
            "PANIC",
            "Fatal error detected. Use /reset to recover or restart session.",
            None,
            False,  # V9.3: finished=False allows /reset to work
            error="PANIC",
            recoverable=True,  # V9.3: Signal to UI that recovery is possible
        )
