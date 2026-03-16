"""
NEXUS V12.4 P5.1 - State Handler Module

Extracted from orchestration_v7.py (Phase 4 of decomposition).

Centralizes FSM state management including transitions, validation, and persistence.
Handles state transitions with event sourcing, snapshots, and evolution mode hooks.

Usage:
    handler = StateHandler(orchestrator)
    handler.transition_to(OrchestratorState.BRAINSTORMING)
    handler.reset_to_idle(clear_task=True)

Phase 4 extraction (medium-high risk, core FSM logic with side effects).
"""

import logging
import time

from core.fsm.states import (  # noqa: F401  # TRANSITION_MATRIX used by tests via mock.patch()
    TRANSITION_MATRIX,
    OrchestratorState,
)

# Module-level imports for mock.patch() support in tests
try:
    from core.fsm.event_sourcing import record_transition  # noqa: F401  # used by tests via mock.patch()
except ImportError:
    record_transition = None  # type: ignore[assignment]  # noqa: F841

try:
    from core.observability.telemetry.otel_provider import get_tracer  # noqa: F401  # used by tests via mock.patch()
except ImportError:
    get_tracer = None  # type: ignore[assignment]  # noqa: F841


class StateHandler:
    """
    FSM state management for orchestrator.

    Handles state transitions with full event sourcing, telemetry,
    and snapshot management for crash recovery.

    Responsibilities:
    - Execute state transitions with validation
    - Record transitions to event log
    - Create periodic snapshots for recovery
    - Manage evolution mode permissions
    - Handle memory backups on critical transitions
    - Reset orchestrator to IDLE state

    V8.8: Extracted from OrchestratorV7 as part of P5.1 decomposition.
    """

    def __init__(self, orchestrator):
        """
        Initialize state handler with orchestrator reference.

        Args:
            orchestrator: OrchestratorV7 instance (for state access)
        """
        self._orch = orchestrator
        self.logger = logging.getLogger("nexus.state_handler")

    @property
    def current_state(self) -> OrchestratorState:
        """Get current FSM state."""
        return self._orch.state

    def transition_to(self, new_state: OrchestratorState):
        """
        Transition FSM with event sourcing and OTel tracing.

        Performs complete state transition including:
        - OTel span creation for observability
        - Event sourcing (record to event log)
        - Periodic snapshot creation (every N events)
        - Memory backup on critical transitions (PANIC, ERROR)
        - Evolution mode permission management
        - Persistence to disk

        Args:
            new_state: Target FSM state

        Examples:
            >>> handler = StateHandler(orch)
            >>> handler.transition_to(OrchestratorState.BRAINSTORMING)
        """
        # UI verbose output
        if self._orch.config.ui_verbose:
            print(f"[FSM] {self._orch.state.name} -> {new_state.name}")

        # V12.4 PHASE 3: OTel span for FSM transition
        self._record_otel_span(self._orch.state, new_state)

        # V12.4: Record transition for crash recovery
        self._record_event_sourcing(self._orch.state, new_state)

        # Create backup before critical transitions
        if new_state in [OrchestratorState.PANIC, OrchestratorState.ERROR]:
            self._orch.memory.create_backup(reason=f"transition_{new_state.name.lower()}")

        # Evolution mode hooks
        self._manage_evolution_mode(new_state)

        # Perform state change
        self._orch.state = new_state
        self._orch.memory.save_to_disk()  # Backup after transition

    def _record_otel_span(self, from_state: OrchestratorState, to_state: OrchestratorState):
        """
        Record FSM transition as OTel span for observability.

        Args:
            from_state: Source state
            to_state: Target state
        """
        try:
            tracer = get_tracer() if get_tracer is not None else None
            if tracer:
                with tracer.start_as_current_span("fsm.transition") as span:
                    span.set_attribute("nexus.from_state", from_state.name)
                    span.set_attribute("nexus.to_state", to_state.name)
                    span.set_attribute("nexus.iteration", self._orch.iteration)
        except Exception as e:
            self.logger.debug("OTel span creation failed: %s", e)

    def _record_event_sourcing(self, from_state: OrchestratorState, to_state: OrchestratorState):
        """
        Record FSM transition to event log and create periodic snapshots.

        Args:
            from_state: Source state
            to_state: Target state
        """
        try:
            if record_transition is None:
                raise ImportError("record_transition not available")
            # Record transition event
            record_transition(
                from_state=from_state.name,
                to_state=to_state.name,
                trigger="fsm_transition",
                session_id=getattr(self._orch, "_session_uuid", None),
            )

            # Increment event counter
            self._orch._event_count += 1

            # V12.4.1: Create periodic snapshot for fast recovery
            if self._orch._snapshot_manager.should_snapshot(self._orch._event_count):
                fsm_state = {
                    "current_state": to_state.name,
                    "previous_state": from_state.name,
                    "session_id": getattr(self._orch, "_session_uuid", None),
                    "iteration": self._orch.iteration,
                    "timestamp": time.time(),
                }
                snapshot = self._orch._snapshot_manager.create_snapshot(
                    fsm_state, sequence_number=self._orch._event_count
                )
                if snapshot:
                    self.logger.debug(f"Created FSM snapshot at event #{self._orch._event_count}")
        except Exception as e:
            self.logger.debug("Telemetry record_transition failed: %s", e)

    def _manage_evolution_mode(self, new_state: OrchestratorState):
        """
        Manage evolution mode permissions based on state transitions.

        Args:
            new_state: Target state
        """
        # Enable evolution permissions when entering EVOLUTION_BRAINSTORM
        if new_state == OrchestratorState.EVOLUTION_BRAINSTORM:
            self._orch.tool_manager.evolution_mode = True
            self.logger.info("🧬 EVOLUTION MODE: Extended permissions enabled (READ parent, WRITE GENERATION_ACTIVE)")

        # Disable evolution permissions when leaving EVOLUTION_BRAINSTORM
        elif (
            self._orch.state == OrchestratorState.EVOLUTION_BRAINSTORM
            and new_state != OrchestratorState.EVOLUTION_BRAINSTORM
        ):
            self._orch.tool_manager.evolution_mode = False
            self.logger.info("🧬 EVOLUTION MODE: Permissions restored to normal (workspace only)")

    def reset_to_idle(self, clear_task: bool = True):
        """
        Reset orchestrator to IDLE state (for /reset command).

        Clears all execution state and optionally task context.

        Args:
            clear_task: If True, also clears objective and history

        Examples:
            >>> handler = StateHandler(orch)
            >>> handler.reset_to_idle(clear_task=True)
        """
        # Transition to IDLE
        self.transition_to(OrchestratorState.IDLE)

        # Reset execution state
        self._orch.stagnation_detector.reset()
        self._orch.stalemate_counter = 0
        self._orch.pending_tool_result = None
        self._orch.json_parse_failures = 0
        self._orch.panic_system.clear_panic()
        self._orch.plan_health.reset()

        # Clear task-related state to avoid stale objectives
        if clear_task:
            self._orch.blackboard["objective"] = ""
            self._orch.blackboard["strategic_plan"] = []
            self._orch.blackboard["recent_history"] = []
            self._orch.memory.save_to_disk()

    def can_transition(self, from_state: OrchestratorState, to_state: OrchestratorState) -> bool:
        """
        Check if transition is valid according to FSM rules.

        Args:
            from_state: Source state
            to_state: Target state

        Returns:
            True if transition is allowed, False otherwise

        Examples:
            >>> handler = StateHandler(orch)
            >>> can_go = handler.can_transition(OrchestratorState.IDLE, OrchestratorState.BRAINSTORMING)
        """
        # Use module-level TRANSITION_MATRIX
        try:
            allowed_transitions = TRANSITION_MATRIX.get(from_state, set())
            return to_state in allowed_transitions
        except (TypeError, AttributeError):
            # Fallback: allow all transitions if matrix not available
            self.logger.warning("TRANSITION_MATRIX not found, allowing all transitions")
            return True


# Module exports
__all__ = [
    "StateHandler",
]
