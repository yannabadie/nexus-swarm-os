"""
NEXUS V12.4 - FSM State Handlers

Modular state handlers for the FSM orchestrator.

Usage:
    from core.fsm.handlers import FSMHandlers
    handlers = FSMHandlers(orchestrator)
    result = handlers.handle_idle(user_input)
"""

# V12.4: Legacy FSMHandlers import removed (modular handlers now complete)
from typing import TYPE_CHECKING

from core.fsm.handlers.base import BaseHandler
from core.fsm.handlers.brainstorming import BrainstormingHandler
from core.fsm.handlers.error import ErrorHandler
from core.fsm.handlers.evolution import EvolutionHandler
from core.fsm.handlers.executing_tool import ExecutingToolHandler
from core.fsm.handlers.idle_waiting import IdleWaitingHandler
from core.fsm.handlers.swarm import SwarmHandler
from core.fsm.handlers.validating_cfl import ValidatingCFLHandler

if TYPE_CHECKING:
    from core.orchestration_v7 import OrchestratorV7


class FSMHandlers:
    """
    Facade for all FSM state handlers.

    Delegates to specialized handler classes for each state.
    """

    def __init__(self, orchestrator: "OrchestratorV7"):
        """
        Initialize all handler modules.

        Args:
            orchestrator: Parent OrchestratorV7 instance
        """
        self._orch = orchestrator

        # Initialize modular handlers
        self.error_handler = ErrorHandler(orchestrator)
        self.brainstorming_handler = BrainstormingHandler(orchestrator)
        self.executing_tool_handler = ExecutingToolHandler(orchestrator)
        self.validating_cfl_handler = ValidatingCFLHandler(orchestrator)
        self.evolution_handler = EvolutionHandler(orchestrator)
        self.swarm_handler = SwarmHandler(orchestrator)
        self.idle_waiting_handler = IdleWaitingHandler(orchestrator)

    # =========================================================================
    # Public Handler Methods (FSM State Dispatch Interface)
    # =========================================================================

    def handle_idle(self, user_input: str | None) -> dict:
        """Handle IDLE state."""
        return self.idle_waiting_handler.handle_idle(user_input)

    def handle_waiting_user(self, user_input: str | None) -> dict:
        """Handle WAITING_USER state."""
        return self.idle_waiting_handler.handle_waiting_user(user_input)

    def handle_brainstorming(self) -> dict:
        """Handle BRAINSTORMING state."""
        return self.brainstorming_handler.handle_brainstorming()

    def handle_executing_tool(self) -> dict:
        """Handle EXECUTING_TOOL state."""
        return self.executing_tool_handler.handle_executing_tool()

    def handle_validating_cfl(self) -> dict:
        """Handle VALIDATING_CFL state."""
        return self.validating_cfl_handler.handle_validating_cfl()

    def handle_error(self) -> dict:
        """Handle ERROR state."""
        return self.error_handler.handle_error()

    def handle_panic(self) -> dict:
        """Handle PANIC state."""
        return self.error_handler.handle_panic()

    def handle_evolution_brainstorm(self, user_input: str | None = None) -> dict:
        """Handle EVOLUTION_BRAINSTORM state."""
        return self.evolution_handler.handle_evolution_brainstorm(user_input)

    def handle_swarm_analyzing(self) -> dict:
        """Handle SWARM_ANALYZING state."""
        return self.swarm_handler.handle_swarm_analyzing()

    def handle_swarm_negotiating(self) -> dict:
        """Handle SWARM_NEGOTIATING state."""
        return self.swarm_handler.handle_swarm_negotiating()

    def handle_swarm_executing(self) -> dict:
        """Handle SWARM_EXECUTING state."""
        return self.swarm_handler.handle_swarm_executing()

    # V8.4.4: Async handlers - always available in V12.4+
    @property
    def has_async_handlers(self) -> bool:
        """Check if async handlers are available."""
        return True  # V12.4: Always available with SDK drivers


__all__ = [
    "FSMHandlers",
    "BaseHandler",
    "ErrorHandler",
    "BrainstormingHandler",
    "ExecutingToolHandler",
    "ValidatingCFLHandler",
    "EvolutionHandler",
    "SwarmHandler",
]
