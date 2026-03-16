"""
NEXUS V7.8 - Swarm Bridge Module (Phase 14c)

Extracted from orchestration_v7.py to follow Single Responsibility Principle.

This module bridges the orchestrator with the HybridSwarmEngine:
- start_swarm_mode(): Initialize swarm for a task
- process_with_swarm(): Full swarm pipeline execution

Usage:
    bridge = SwarmBridge(orchestrator)
    result = bridge.process_with_swarm(task_input, force_mode=CollaborationMode.PARALLEL)
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from core.fsm.states import OrchestratorState
from core.intelligence.swarm import CollaborationMode, SwarmPhase

if TYPE_CHECKING:
    from core.orchestration_v7 import OrchestratorV7


class SwarmBridge:
    """
    Bridge between orchestrator and HybridSwarmEngine.

    Handles all swarm-related operations:
    - Mode initialization
    - Task processing
    - Result integration

    Phase 14c: Extracted from OrchestratorV7 for better maintainability.
    """

    def __init__(self, orchestrator: "OrchestratorV7"):
        """
        Initialize swarm bridge with orchestrator reference.

        Uses composition pattern - bridge accesses orchestrator state
        but doesn't own it.

        Args:
            orchestrator: Parent OrchestratorV7 instance
        """
        self._orch = orchestrator
        self._logger = logging.getLogger("nexus.swarm_bridge")

    @property
    def is_enabled(self) -> bool:
        """Check if swarm engine is enabled."""
        return self._orch.swarm_engine is not None

    def start_swarm_mode(self, objective: str, force_mode: CollaborationMode | None = None) -> dict:
        """
        Start Hybrid Swarm mode for a task (V7 Sprint 9).

        This bypasses the normal IDLE->BRAINSTORMING flow and uses
        the HybridSwarmEngine for dynamic mode negotiation.

        Args:
            objective: Task description
            force_mode: Optional mode to force (skip negotiation)

        Returns:
            Initial swarm result dict
        """
        if not self.is_enabled:
            return self._make_result("ERROR", "Swarm engine not enabled", None, False, error="SWARM_DISABLED")

        # Set objective
        self._orch.blackboard["objective"] = objective
        self._orch.blackboard["mode"] = "SWARM"

        # Transition to swarm analyzing
        self._orch._transition_to(OrchestratorState.SWARM_ANALYZING)

        return self._make_result(
            "SWARM_ANALYZING",
            f"[Swarm Mode Started]\nObjective: {objective}\nForce mode: {force_mode.value if force_mode else 'auto'}",
            None,
            False,
        )

    def process_with_swarm(
        self,
        task_input: str,
        force_mode: CollaborationMode | None = None,
        skip_negotiation: bool = False,
        on_negotiation_turn: Callable | None = None,
        on_execution_round: Callable | None = None,
    ) -> dict:
        """
        Process a task using HybridSwarmEngine directly (V7 Sprint 9).

        Runs the full swarm pipeline synchronously and returns the result.
        This is a convenience method for when you want to use swarm
        without going through the FSM states.

        Args:
            task_input: Task description
            force_mode: Force a specific collaboration mode
            skip_negotiation: Skip negotiation phase
            on_negotiation_turn: V7.5 callback for real-time negotiation display
            on_execution_round: V7.5 callback for real-time execution display

        Returns:
            Result dict with swarm output
        """
        if not self.is_enabled:
            return self._make_result("ERROR", "Swarm engine not enabled", None, False, error="SWARM_DISABLED")

        try:
            result = self._orch.swarm_engine.process_task(
                task_input=task_input,
                blackboard=self._orch.blackboard,
                force_mode=force_mode,
                skip_negotiation=skip_negotiation,
                on_negotiation_turn=on_negotiation_turn,
                on_execution_round=on_execution_round,
            )

            # Update history with swarm result
            self._orch.memory.add_to_history(
                {"sender": "Swarm", "action_type": "SWARM_RESULT", "content": result.final_output[:2000]}
            )

            return {
                "state": result.status.value,
                "output": result.final_output,
                "agent": "Swarm",  # V7 FIX: Add agent key for display_result
                "mode": result.selected_mode.value,
                "finished": result.status == SwarmPhase.COMPLETED,
                "analysis": result.task_analysis.to_dict(),
                "execution": result.execution_result.to_dict(),
            }

        except Exception as e:
            self._logger.error(f"Swarm processing failed: {e}")
            return self._make_result("ERROR", f"Swarm failed: {e}", None, False, error=str(e))

    def get_swarm_stats(self) -> dict | None:
        """
        Get current swarm engine statistics.

        Returns:
            Stats dict or None if swarm not enabled
        """
        if not self.is_enabled:
            return None
        return self._orch.swarm_engine.get_stats()

    def _make_result(self, state: str, output: str | None, agent: str | None, finished: bool, **kwargs) -> dict:
        """
        Create standardized result dictionary.

        Helper method matching OrchestratorV7._make_result signature.

        Args:
            state: Current state name
            output: Output content
            agent: Active agent name
            finished: Whether task is finished
            **kwargs: Additional fields (error, etc.)

        Returns:
            Result dict
        """
        result = {"state": state, "output": output, "agent": agent, "finished": finished}
        result.update(kwargs)
        return result
