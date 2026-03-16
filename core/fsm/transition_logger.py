"""
FSM Transition Logger - Structured logging of FSM transitions.

V12.4 COGNITIVE BOOST - Task #71

Provides structured logging and querying of FSM state transitions
with timing, context, and statistics.

Usage:
    from core.fsm.transition_logger import get_transition_logger

    logger = get_transition_logger()

    # Log a transition
    logger.log("idle", "brainstorming", trigger="user_input")

    # Query recent transitions
    recent = logger.get_recent(limit=10)

    # Get stats for a state
    stats = logger.state_duration_stats("brainstorming")
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

MAX_ENTRIES = 50000
DEFAULT_RECENT_LIMIT = 100


# =============================================================================
# Types
# =============================================================================


@dataclass
class TransitionEntry:
    """A logged FSM transition."""

    from_state: str
    to_state: str
    trigger: str = ""
    session_id: str = ""
    duration_ms: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_state,
            "to": self.to_state,
            "trigger": self.trigger,
            "session_id": self.session_id,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class StateDurationStats:
    """Duration statistics for a state."""

    state: str
    count: int
    total_ms: float
    min_ms: float
    max_ms: float
    avg_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "count": self.count,
            "total_ms": round(self.total_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
        }


@dataclass
class TransitionFrequency:
    """Frequency of a specific transition."""

    from_state: str
    to_state: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_state,
            "to": self.to_state,
            "count": self.count,
        }


@dataclass
class LoggerStats:
    """Transition logger statistics."""

    total_entries: int
    unique_states: int
    unique_transitions: int
    entries_by_trigger: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "unique_states": self.unique_states,
            "unique_transitions": self.unique_transitions,
            "entries_by_trigger": self.entries_by_trigger,
        }


# =============================================================================
# Transition Logger
# =============================================================================


class TransitionLogger:
    """
    Structured FSM transition logger.

    Features:
    - Structured transition logging with context
    - Query by state, trigger, session, time range
    - State duration statistics
    - Transition frequency analysis
    - Bounded history (auto-eviction)
    - Thread-safe
    """

    def __init__(self, *, max_entries: int = MAX_ENTRIES):
        self._entries: list[TransitionEntry] = []
        self._max_entries = max_entries
        self._lock = threading.Lock()

    # =========================================================================
    # Logging
    # =========================================================================

    def log(
        self,
        from_state: str,
        to_state: str,
        *,
        trigger: str = "",
        session_id: str = "",
        duration_ms: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> TransitionEntry:
        """Log a state transition."""
        entry = TransitionEntry(
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            session_id=session_id,
            duration_ms=duration_ms,
            context=context or {},
        )
        with self._lock:
            self._entries.append(entry)
            # Evict oldest if over limit
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]
        return entry

    # =========================================================================
    # Queries
    # =========================================================================

    def get_recent(self, *, limit: int = DEFAULT_RECENT_LIMIT) -> list[TransitionEntry]:
        """Get most recent transitions."""
        return list(reversed(self._entries[-limit:]))

    def get_by_state(self, state: str) -> list[TransitionEntry]:
        """Get all transitions from or to a state."""
        return [e for e in self._entries if e.from_state == state or e.to_state == state]

    def get_by_from_state(self, state: str) -> list[TransitionEntry]:
        """Get all transitions from a state."""
        return [e for e in self._entries if e.from_state == state]

    def get_by_to_state(self, state: str) -> list[TransitionEntry]:
        """Get all transitions to a state."""
        return [e for e in self._entries if e.to_state == state]

    def get_by_trigger(self, trigger: str) -> list[TransitionEntry]:
        """Get all transitions with a specific trigger."""
        return [e for e in self._entries if e.trigger == trigger]

    def get_by_session(self, session_id: str) -> list[TransitionEntry]:
        """Get all transitions for a session."""
        return [e for e in self._entries if e.session_id == session_id]

    def get_by_time_range(self, start: float, end: float) -> list[TransitionEntry]:
        """Get transitions within a time range (monotonic timestamps)."""
        return [e for e in self._entries if start <= e.timestamp <= end]

    # =========================================================================
    # Analysis
    # =========================================================================

    def state_duration_stats(self, state: str) -> StateDurationStats | None:
        """Get duration statistics for transitions from a state."""
        durations = [e.duration_ms for e in self._entries if e.from_state == state and e.duration_ms > 0]
        if not durations:
            return None
        return StateDurationStats(
            state=state,
            count=len(durations),
            total_ms=sum(durations),
            min_ms=min(durations),
            max_ms=max(durations),
            avg_ms=sum(durations) / len(durations),
        )

    def transition_frequencies(self) -> list[TransitionFrequency]:
        """Get frequency of each unique transition."""
        counts: dict[tuple, int] = defaultdict(int)
        for e in self._entries:
            counts[(e.from_state, e.to_state)] += 1
        return sorted(
            [TransitionFrequency(from_state=k[0], to_state=k[1], count=v) for k, v in counts.items()],
            key=lambda f: f.count,
            reverse=True,
        )

    def most_common_transition(self) -> TransitionFrequency | None:
        """Get the most common transition."""
        freqs = self.transition_frequencies()
        return freqs[0] if freqs else None

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> LoggerStats:
        """Get logger statistics."""
        states: set = set()
        transitions: set = set()
        trigger_counts: dict[str, int] = defaultdict(int)
        for e in self._entries:
            states.add(e.from_state)
            states.add(e.to_state)
            transitions.add((e.from_state, e.to_state))
            if e.trigger:
                trigger_counts[e.trigger] += 1
        return LoggerStats(
            total_entries=len(self._entries),
            unique_states=len(states),
            unique_transitions=len(transitions),
            entries_by_trigger=dict(trigger_counts),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """Clear all logged entries."""
        with self._lock:
            self._entries.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_count": self.entry_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_logger_instance: TransitionLogger | None = None
_logger_lock = threading.Lock()


def get_transition_logger() -> TransitionLogger:
    """Get or create the global transition logger."""
    global _logger_instance
    if _logger_instance is None:
        with _logger_lock:
            if _logger_instance is None:
                _logger_instance = TransitionLogger()
    return _logger_instance


def reset_transition_logger() -> None:
    """Reset the global transition logger (for testing)."""
    global _logger_instance
    _logger_instance = None
