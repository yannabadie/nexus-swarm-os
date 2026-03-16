"""
Phase Coordinator - Manage hive mind phase transitions.

V12.4 COGNITIVE BOOST - Task #65

Tracks phase transitions, validates entry conditions,
and manages phase lifecycle for hive mind sessions.

Usage:
    from core.intelligence.hive_mind.phase_coordinator import get_phase_coordinator

    coord = get_phase_coordinator()

    # Start a session
    coord.start_session("sess1")

    # Transition phases
    coord.transition("sess1", "analysis")
    coord.transition("sess1", "debate")

    # Check current phase
    phase = coord.current_phase("sess1")  # "debate"

    # Check if phase can be skipped
    can_skip = coord.can_skip("sess1", "debate")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

PHASE_ORDER = [
    "analysis",
    "debate",
    "architecture",
    "execution",
    "diagnosis",
    "retry",
    "consolidation",
]

# Valid transitions (from -> set of allowed targets)
VALID_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"analysis"},
    "analysis": {"debate", "architecture", "execution"},  # Can skip debate
    "debate": {"architecture", "execution"},  # Can skip architecture
    "architecture": {"execution"},
    "execution": {"diagnosis", "consolidation"},  # Success or failure
    "diagnosis": {"retry", "consolidation"},
    "retry": {"execution", "consolidation"},  # Retry or give up
    "consolidation": {"idle"},
}

SKIPPABLE_PHASES = {"debate", "architecture", "diagnosis", "retry"}


# =============================================================================
# Types
# =============================================================================


@dataclass
class PhaseTransition:
    """A recorded phase transition."""

    from_phase: str
    to_phase: str
    session_id: str
    timestamp: float = 0.0
    reason: str = ""

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_phase,
            "to": self.to_phase,
            "reason": self.reason,
        }


@dataclass
class PhaseState:
    """Current state of a session's phase progression."""

    session_id: str
    current_phase: str = "idle"
    started_at: float = 0.0
    phase_entered_at: float = 0.0
    transitions: list[PhaseTransition] = field(default_factory=list)
    completed_phases: list[str] = field(default_factory=list)

    @property
    def phase_duration(self) -> float:
        if self.phase_entered_at == 0.0:
            return 0.0
        return time.monotonic() - self.phase_entered_at

    @property
    def total_duration(self) -> float:
        if self.started_at == 0.0:
            return 0.0
        return time.monotonic() - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "current_phase": self.current_phase,
            "phase_duration_s": round(self.phase_duration, 2),
            "total_duration_s": round(self.total_duration, 2),
            "transition_count": len(self.transitions),
            "completed_phases": self.completed_phases,
        }


@dataclass
class TransitionResult:
    """Result of a phase transition attempt."""

    success: bool
    from_phase: str = ""
    to_phase: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "from": self.from_phase,
            "to": self.to_phase,
            "error": self.error,
        }


@dataclass
class CoordinatorStats:
    """Phase coordinator statistics."""

    active_sessions: int
    total_transitions: int
    phase_distribution: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_sessions": self.active_sessions,
            "total_transitions": self.total_transitions,
            "phase_distribution": self.phase_distribution,
        }


# =============================================================================
# Phase Coordinator
# =============================================================================


class PhaseCoordinator:
    """
    Manages hive mind phase transitions.

    Features:
    - Phase lifecycle management (7 phases)
    - Transition validation (only valid transitions allowed)
    - Phase skipping for trivial tasks
    - Transition history tracking
    - Phase duration tracking
    - Multi-session support
    """

    def __init__(self):
        self._sessions: dict[str, PhaseState] = {}
        self._lock = threading.Lock()

    # =========================================================================
    # Session Lifecycle
    # =========================================================================

    def start_session(self, session_id: str) -> PhaseState:
        """Start tracking a new session."""
        now = time.monotonic()
        state = PhaseState(
            session_id=session_id,
            current_phase="idle",
            started_at=now,
            phase_entered_at=now,
        )
        with self._lock:
            self._sessions[session_id] = state
        return state

    def end_session(self, session_id: str) -> bool:
        """End a session."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    # =========================================================================
    # Transitions
    # =========================================================================

    def transition(
        self,
        session_id: str,
        target_phase: str,
        *,
        reason: str = "",
    ) -> TransitionResult:
        """
        Transition a session to a new phase.

        Args:
            session_id: Session identifier
            target_phase: Phase to transition to
            reason: Reason for transition

        Returns:
            TransitionResult indicating success/failure
        """
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return TransitionResult(
                    success=False,
                    error=f"Session '{session_id}' not found",
                )

            current = state.current_phase
            valid_targets = VALID_TRANSITIONS.get(current, set())

            if target_phase not in valid_targets:
                return TransitionResult(
                    success=False,
                    from_phase=current,
                    to_phase=target_phase,
                    error=f"Invalid transition: {current} -> {target_phase}",
                )

            # Record transition
            transition = PhaseTransition(
                from_phase=current,
                to_phase=target_phase,
                session_id=session_id,
                reason=reason,
            )
            state.transitions.append(transition)

            # Update completed phases
            if current != "idle" and current not in state.completed_phases:
                state.completed_phases.append(current)

            state.current_phase = target_phase
            state.phase_entered_at = time.monotonic()

            return TransitionResult(
                success=True,
                from_phase=current,
                to_phase=target_phase,
            )

    # =========================================================================
    # Queries
    # =========================================================================

    def current_phase(self, session_id: str) -> str | None:
        """Get current phase for a session."""
        state = self._sessions.get(session_id)
        return state.current_phase if state else None

    def get_state(self, session_id: str) -> PhaseState | None:
        """Get full phase state for a session."""
        return self._sessions.get(session_id)

    def get_transitions(self, session_id: str) -> list[PhaseTransition]:
        """Get transition history for a session."""
        state = self._sessions.get(session_id)
        return list(state.transitions) if state else []

    def next_phases(self, session_id: str) -> list[str]:
        """Get valid next phases for a session."""
        state = self._sessions.get(session_id)
        if state is None:
            return []
        return sorted(VALID_TRANSITIONS.get(state.current_phase, set()))

    def can_transition(self, session_id: str, target: str) -> bool:
        """Check if a transition is valid without performing it."""
        state = self._sessions.get(session_id)
        if state is None:
            return False
        return target in VALID_TRANSITIONS.get(state.current_phase, set())

    def can_skip(self, session_id: str, phase: str) -> bool:
        """Check if a phase can be skipped."""
        if phase not in SKIPPABLE_PHASES:
            return False
        state = self._sessions.get(session_id)
        if state is None:
            return False
        # Can skip if valid transitions from current phase bypass the target
        valid = VALID_TRANSITIONS.get(state.current_phase, set())
        # Can skip if there's a valid transition that goes past the target
        phase_idx = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else -1
        for target in valid:
            target_idx = PHASE_ORDER.index(target) if target in PHASE_ORDER else -1
            if target_idx > phase_idx:
                return True
        return False

    def has_completed(self, session_id: str, phase: str) -> bool:
        """Check if a phase has been completed."""
        state = self._sessions.get(session_id)
        if state is None:
            return False
        return phase in state.completed_phases

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> CoordinatorStats:
        """Get coordinator statistics."""
        phase_dist: dict[str, int] = defaultdict(int)
        total_transitions = 0
        with self._lock:
            for state in self._sessions.values():
                phase_dist[state.current_phase] += 1
                total_transitions += len(state.transitions)
        return CoordinatorStats(
            active_sessions=len(self._sessions),
            total_transitions=total_transitions,
            phase_distribution=dict(phase_dist),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def clear(self) -> None:
        """Clear all sessions."""
        with self._lock:
            self._sessions.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_coordinator: PhaseCoordinator | None = None
_coordinator_lock = threading.Lock()


def get_phase_coordinator() -> PhaseCoordinator:
    """Get or create the global phase coordinator."""
    global _coordinator
    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                _coordinator = PhaseCoordinator()
    return _coordinator


def reset_phase_coordinator() -> None:
    """Reset the global phase coordinator (for testing)."""
    global _coordinator
    _coordinator = None
