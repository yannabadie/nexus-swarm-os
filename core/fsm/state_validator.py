"""
FSM State Validator - Validate state transitions and invariants.

V12.4 COGNITIVE BOOST - Task #68

Validates FSM transitions against a configurable transition matrix,
checks state invariants, and provides detailed error reporting.

Usage:
    from core.fsm.state_validator import get_state_validator

    validator = get_state_validator()

    # Define allowed transitions
    validator.define_transition("idle", {"brainstorming", "swarm_analyzing"})

    # Validate
    result = validator.validate("idle", "brainstorming")
    assert result.valid
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_STATES = 500
MAX_INVARIANTS = 200


# =============================================================================
# Types
# =============================================================================


@dataclass
class ValidationResult:
    """Result of a state transition validation."""

    valid: bool
    from_state: str = ""
    to_state: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "error": self.error,
            "warnings": self.warnings,
        }


@dataclass
class Invariant:
    """A state invariant to check."""

    name: str
    state: str
    check: Callable[[dict[str, Any]], bool]
    description: str = ""


@dataclass
class ValidatorStats:
    """State validator statistics."""

    defined_states: int
    total_transitions_defined: int
    total_invariants: int
    total_validations: int
    total_valid: int
    total_invalid: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "defined_states": self.defined_states,
            "total_transitions_defined": self.total_transitions_defined,
            "total_invariants": self.total_invariants,
            "total_validations": self.total_validations,
            "total_valid": self.total_valid,
            "total_invalid": self.total_invalid,
        }


# =============================================================================
# State Validator
# =============================================================================


class StateValidator:
    """
    Validates FSM state transitions and invariants.

    Features:
    - Configurable transition matrix
    - State invariant checking
    - Detailed validation results with warnings
    - Strict vs lenient mode
    - Statistics tracking
    - Thread-safe
    """

    def __init__(self, *, strict: bool = True):
        self._transitions: dict[str, set[str]] = {}
        self._invariants: dict[str, list[Invariant]] = {}
        self._strict = strict
        self._total_validations = 0
        self._total_valid = 0
        self._total_invalid = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Transition Matrix
    # =========================================================================

    def define_transition(self, from_state: str, to_states: set[str]) -> None:
        """Define valid transitions from a state."""
        with self._lock:
            self._transitions[from_state] = set(to_states)

    def define_transitions(self, matrix: dict[str, set[str]]) -> None:
        """Define the full transition matrix at once."""
        with self._lock:
            self._transitions = {k: set(v) for k, v in matrix.items()}

    def add_transition(self, from_state: str, to_state: str) -> None:
        """Add a single valid transition."""
        with self._lock:
            if from_state not in self._transitions:
                self._transitions[from_state] = set()
            self._transitions[from_state].add(to_state)

    def remove_transition(self, from_state: str, to_state: str) -> bool:
        """Remove a transition."""
        with self._lock:
            targets = self._transitions.get(from_state)
            if targets is None or to_state not in targets:
                return False
            targets.discard(to_state)
            return True

    def get_valid_targets(self, from_state: str) -> set[str]:
        """Get valid target states from a state."""
        return set(self._transitions.get(from_state, set()))

    def get_all_states(self) -> set[str]:
        """Get all known states (sources and targets)."""
        states: set[str] = set()
        for source, targets in self._transitions.items():
            states.add(source)
            states.update(targets)
        return states

    # =========================================================================
    # Invariants
    # =========================================================================

    def add_invariant(
        self,
        name: str,
        state: str,
        check: Callable[[dict[str, Any]], bool],
        *,
        description: str = "",
    ) -> None:
        """Add an invariant that must hold for a state."""
        inv = Invariant(name=name, state=state, check=check, description=description)
        with self._lock:
            if state not in self._invariants:
                self._invariants[state] = []
            self._invariants[state].append(inv)

    def remove_invariant(self, name: str) -> bool:
        """Remove an invariant by name."""
        with self._lock:
            for _state, invs in self._invariants.items():
                for i, inv in enumerate(invs):
                    if inv.name == name:
                        invs.pop(i)
                        return True
            return False

    def check_invariants(self, state: str, context: dict[str, Any]) -> list[str]:
        """Check all invariants for a state. Returns list of violations."""
        violations = []
        invs = self._invariants.get(state, [])
        for inv in invs:
            try:
                if not inv.check(context):
                    violations.append(f"{inv.name}: {inv.description or 'Invariant violated'}")
            except Exception as e:
                violations.append(f"{inv.name}: Check raised error: {e}")
        return violations

    # =========================================================================
    # Validation
    # =========================================================================

    def validate(
        self,
        from_state: str,
        to_state: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate a state transition.

        Args:
            from_state: Current state
            to_state: Target state
            context: Optional context for invariant checking

        Returns:
            ValidationResult with details
        """
        with self._lock:
            self._total_validations += 1
            warnings: list[str] = []

            # Check if from_state has defined transitions
            valid_targets = self._transitions.get(from_state)
            if valid_targets is None:
                if self._strict:
                    self._total_invalid += 1
                    return ValidationResult(
                        valid=False,
                        from_state=from_state,
                        to_state=to_state,
                        error=f"No transitions defined for state '{from_state}'",
                    )
                else:
                    warnings.append(f"No transitions defined for state '{from_state}'")

            # Check if transition is valid
            if valid_targets is not None and to_state not in valid_targets:
                self._total_invalid += 1
                return ValidationResult(
                    valid=False,
                    from_state=from_state,
                    to_state=to_state,
                    error=f"Invalid transition: {from_state} -> {to_state}",
                )

            # Check invariants on target state
            if context is not None:
                violations = self.check_invariants(to_state, context)
                if violations:
                    if self._strict:
                        self._total_invalid += 1
                        return ValidationResult(
                            valid=False,
                            from_state=from_state,
                            to_state=to_state,
                            error=f"Invariant violations: {'; '.join(violations)}",
                            warnings=warnings,
                        )
                    else:
                        warnings.extend(violations)

            self._total_valid += 1
            return ValidationResult(
                valid=True,
                from_state=from_state,
                to_state=to_state,
                warnings=warnings,
            )

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Quick check if a transition is valid (no invariants)."""
        targets = self._transitions.get(from_state)
        if targets is None:
            return not self._strict
        return to_state in targets

    def is_terminal(self, state: str) -> bool:
        """Check if a state has no outgoing transitions."""
        targets = self._transitions.get(state)
        return targets is None or len(targets) == 0

    def get_reachable(self, from_state: str) -> set[str]:
        """Get all states reachable from a state (transitive closure)."""
        reachable: set[str] = set()
        visited: set[str] = set()
        queue = list(self._transitions.get(from_state, set()))
        reachable.update(queue)
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            targets = self._transitions.get(current, set())
            for t in targets:
                reachable.add(t)
                if t not in visited:
                    queue.append(t)
        return reachable

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> ValidatorStats:
        """Get validator statistics."""
        total_transitions = sum(len(t) for t in self._transitions.values())
        total_invariants = sum(len(v) for v in self._invariants.values())
        return ValidatorStats(
            defined_states=len(self._transitions),
            total_transitions_defined=total_transitions,
            total_invariants=total_invariants,
            total_validations=self._total_validations,
            total_valid=self._total_valid,
            total_invalid=self._total_invalid,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def state_count(self) -> int:
        return len(self._transitions)

    @property
    def strict(self) -> bool:
        return self._strict

    def clear(self) -> None:
        """Clear all transitions, invariants, and stats."""
        with self._lock:
            self._transitions.clear()
            self._invariants.clear()
            self._total_validations = 0
            self._total_valid = 0
            self._total_invalid = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_count": self.state_count,
            "strict": self._strict,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_validator: StateValidator | None = None
_validator_lock = threading.Lock()


def get_state_validator() -> StateValidator:
    """Get or create the global state validator."""
    global _validator
    if _validator is None:
        with _validator_lock:
            if _validator is None:
                _validator = StateValidator()
    return _validator


def reset_state_validator() -> None:
    """Reset the global state validator (for testing)."""
    global _validator
    _validator = None
