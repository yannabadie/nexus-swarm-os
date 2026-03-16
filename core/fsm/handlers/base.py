"""
NEXUS V12.4 - FSM Handler Base Class

Provides common infrastructure for all state handlers.
"""

import logging
from typing import TYPE_CHECKING

from core.execution_pkg.routing.model_router import TaskType
from core.foundation.agents.unified_registry import get_registry

if TYPE_CHECKING:
    from core.orchestration_v7 import OrchestratorV7


class BaseHandler:
    """
    Base class for FSM state handlers.

    Provides:
    - Access to orchestrator via self._orch
    - Delegation methods for common operations
    - Logging infrastructure
    """

    def __init__(self, orchestrator: "OrchestratorV7"):
        """
        Initialize handler with orchestrator reference.

        Args:
            orchestrator: Parent OrchestratorV7 instance
        """
        self._orch = orchestrator
        self._logger = logging.getLogger(f"nexus.fsm.{self.__class__.__name__}")
        self._registry = get_registry()

    # =========================================================================
    # Delegated Methods (orchestrator access)
    # =========================================================================

    def _make_result(self, state: str, output, agent, finished: bool, **kwargs) -> dict:
        """Delegate to orchestrator."""
        return self._orch._make_result(state, output, agent, finished, **kwargs)

    def _build_context(self) -> str:
        """Build context - delegate to context_builder or orchestrator."""
        if hasattr(self._orch, "context_builder"):
            return self._orch.context_builder.build_context()
        return self._orch._build_context()

    def _build_context_with_tool_result(self) -> str:
        """Build CFL context - delegate to context_builder or orchestrator."""
        if hasattr(self._orch, "context_builder"):
            return self._orch.context_builder.build_context_with_tool_result()
        return self._orch._build_context_with_tool_result()

    def _invoke_agent(self, task_type: TaskType, context: str) -> dict:
        """Invoke agent - delegate to agent_invoker or orchestrator."""
        if hasattr(self._orch, "agent_invoker"):
            return self._orch.agent_invoker.invoke_agent(task_type, context)
        return self._orch._invoke_agent(task_type, context)

    def _get_claude_driver(self, task_type: TaskType, timeout_override: int = None):
        """Get Claude driver - delegate to agent_invoker or orchestrator."""
        if hasattr(self._orch, "agent_invoker"):
            return self._orch.agent_invoker.get_claude_driver(task_type, timeout_override)
        return self._orch._get_claude_driver(task_type, timeout_override)

    def _validate_message(self, response: dict, expect_heavy: bool = False) -> dict:
        """Validate message - delegate to orchestrator."""
        return self._orch._validate_message(response, expect_heavy)

    def _calculate_quality_score(self, message: dict, validation_ok: bool, is_stagnant: bool) -> float:
        """Calculate quality - delegate to agent_invoker or orchestrator."""
        if hasattr(self._orch, "agent_invoker"):
            return self._orch.agent_invoker.calculate_quality_score(message, validation_ok, is_stagnant)
        return self._orch._calculate_quality_score(message, validation_ok, is_stagnant)

    def _record_invocation(self, agent_name: str, task_type: str, success: bool, duration: float, quality: float):
        """Record invocation - delegate to agent_invoker or orchestrator."""
        if hasattr(self._orch, "agent_invoker"):
            return self._orch.agent_invoker.record_invocation(agent_name, task_type, success, duration, quality)
        return self._orch._record_invocation(agent_name, task_type, success, duration, quality)

    def _detect_mutation_complete(self, content: str) -> bool:
        """Detect mutation - delegate to detectors or orchestrator."""
        if hasattr(self._orch, "mutation_detector"):
            return self._orch.mutation_detector.detect_mutation_complete(content)
        return self._orch._detect_mutation_complete(content)
