"""
Negotiation Tracker - Track swarm mode negotiation outcomes.

V12.4 COGNITIVE BOOST

Tracks all swarm negotiation rounds including per-turn proposals,
final agreed modes, convergence rates, and timing metrics.
Enables data-driven analysis of negotiation effectiveness.

Usage:
    from core.intelligence.swarm.negotiation_tracker import get_negotiation_tracker

    tracker = get_negotiation_tracker()

    # Record a completed negotiation
    record = tracker.record_negotiation(
        task_domain="coding",
        complexity="moderate",
        initial_mode="PARALLEL",
        final_mode="LEAD_SUPPORT",
        turns=[
            {"turn_number": 1, "agent_id": "claude", "proposed_mode": "PARALLEL"},
            {"turn_number": 2, "agent_id": "gemini", "proposed_mode": "LEAD_SUPPORT"},
        ],
        turn_count=2,
        duration_ms=340.5,
        converged=True,
        participating_agents=["claude", "gemini"],
    )

    # Query statistics
    stats = tracker.get_stats()
    rate = tracker.get_convergence_rate()
    ranking = tracker.get_mode_proposal_ranking()
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_NEGOTIATIONS = 50000


# =============================================================================
# Helpers
# =============================================================================


def _utc_iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# =============================================================================
# Types
# =============================================================================


@dataclass
class NegotiationTurn:
    """A single turn in a negotiation."""

    turn_number: int = 0
    agent_id: str = ""
    proposed_mode: str = ""
    reasoning: str = ""
    accepted: bool = False
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _utc_iso_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "agent_id": self.agent_id,
            "proposed_mode": self.proposed_mode,
            "reasoning": self.reasoning,
            "accepted": self.accepted,
            "timestamp": self.timestamp,
        }


@dataclass
class NegotiationRecord:
    """Complete record of a single negotiation."""

    negotiation_id: str = ""
    task_domain: str = ""
    complexity: str = ""
    initial_mode: str = ""
    final_mode: str = ""
    turns: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    duration_ms: float = 0.0
    converged: bool = True
    participating_agents: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _utc_iso_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "negotiation_id": self.negotiation_id,
            "task_domain": self.task_domain,
            "complexity": self.complexity,
            "initial_mode": self.initial_mode,
            "final_mode": self.final_mode,
            "turns": list(self.turns),
            "turn_count": self.turn_count,
            "duration_ms": round(self.duration_ms, 2),
            "converged": self.converged,
            "participating_agents": list(self.participating_agents),
            "timestamp": self.timestamp,
        }


@dataclass
class NegotiationStats:
    """Aggregated negotiation statistics."""

    total_negotiations: int = 0
    converged_count: int = 0
    failed_count: int = 0
    avg_turns: float = 0.0
    avg_duration_ms: float = 0.0
    most_proposed_mode: str = ""
    most_agreed_mode: str = ""

    @property
    def convergence_rate(self) -> float:
        if self.total_negotiations > 0:
            return self.converged_count / self.total_negotiations
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_negotiations": self.total_negotiations,
            "converged_count": self.converged_count,
            "failed_count": self.failed_count,
            "avg_turns": round(self.avg_turns, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "most_proposed_mode": self.most_proposed_mode,
            "most_agreed_mode": self.most_agreed_mode,
            "convergence_rate": round(self.convergence_rate, 4),
        }


# =============================================================================
# Negotiation Tracker
# =============================================================================


class NegotiationTracker:
    """
    Tracks swarm mode negotiation outcomes.

    Features:
    - Record negotiation rounds with per-turn detail
    - Convergence rate tracking
    - Mode proposal and agreement rankings
    - Domain-based negotiation filtering
    - Failed negotiation analysis
    - Bounded history with FIFO eviction
    - Thread-safe operations
    """

    def __init__(self, max_negotiations: int = MAX_NEGOTIATIONS) -> None:
        self._records: list[NegotiationRecord] = []
        self._mode_proposals: dict[str, int] = {}
        self._mode_agreements: dict[str, int] = {}
        self._max_negotiations = max_negotiations
        self._lock = threading.Lock()
        self._counter = 0

    # =========================================================================
    # Recording
    # =========================================================================

    def record_negotiation(
        self,
        task_domain: str = "",
        complexity: str = "",
        initial_mode: str = "",
        final_mode: str = "",
        turns: list[dict[str, Any]] | None = None,
        turn_count: int = 0,
        duration_ms: float = 0.0,
        converged: bool = True,
        participating_agents: list[str] | None = None,
    ) -> NegotiationRecord:
        """
        Record a completed negotiation.

        Args:
            task_domain: Domain of the task being negotiated
            complexity: Task complexity level
            initial_mode: First mode proposed
            final_mode: Mode agreed upon (or last proposed if not converged)
            turns: List of turn dicts with negotiation details
            turn_count: Number of negotiation turns
            duration_ms: Total negotiation duration in milliseconds
            converged: Whether agents reached consensus
            participating_agents: List of agent identifiers involved

        Returns:
            The recorded NegotiationRecord
        """
        with self._lock:
            self._counter += 1
            negotiation_id = f"neg_{self._counter:06d}"

            record = NegotiationRecord(
                negotiation_id=negotiation_id,
                task_domain=task_domain,
                complexity=complexity,
                initial_mode=initial_mode,
                final_mode=final_mode,
                turns=turns if turns is not None else [],
                turn_count=turn_count,
                duration_ms=duration_ms,
                converged=converged,
                participating_agents=participating_agents if participating_agents is not None else [],
            )

            # Track mode proposals
            if initial_mode:
                self._mode_proposals[initial_mode] = self._mode_proposals.get(initial_mode, 0) + 1

            # Track mode agreements (only if converged)
            if converged and final_mode:
                self._mode_agreements[final_mode] = self._mode_agreements.get(final_mode, 0) + 1

            self._records.append(record)

            # FIFO eviction
            while len(self._records) > self._max_negotiations:
                self._records.pop(0)

        return record

    # =========================================================================
    # Convergence Analysis
    # =========================================================================

    def get_convergence_rate(self) -> float:
        """Get the overall convergence rate (converged / total)."""
        with self._lock:
            total = len(self._records)
            if total == 0:
                return 0.0
            converged = sum(1 for r in self._records if r.converged)
            return converged / total

    # =========================================================================
    # Mode Rankings
    # =========================================================================

    def get_mode_proposal_ranking(self) -> list[tuple[str, int]]:
        """
        Get modes ranked by how often they are proposed first.

        Returns:
            List of (mode, count) tuples sorted by count descending
        """
        with self._lock:
            items = list(self._mode_proposals.items())
        items.sort(key=lambda x: x[1], reverse=True)
        return items

    def get_mode_agreement_ranking(self) -> list[tuple[str, int]]:
        """
        Get modes ranked by how often they are agreed upon.

        Returns:
            List of (mode, count) tuples sorted by count descending
        """
        with self._lock:
            items = list(self._mode_agreements.items())
        items.sort(key=lambda x: x[1], reverse=True)
        return items

    # =========================================================================
    # Queries
    # =========================================================================

    def get_recent_negotiations(self, limit: int = 20) -> list[NegotiationRecord]:
        """
        Get the most recent negotiation records.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of NegotiationRecord (newest first)
        """
        with self._lock:
            records = list(self._records[-limit:])
        records.reverse()
        return records

    def get_failed_negotiations(self, limit: int = 20) -> list[NegotiationRecord]:
        """
        Get negotiations that did not converge.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of non-converged NegotiationRecord (newest first)
        """
        with self._lock:
            failed = [r for r in self._records if not r.converged]
        failed.reverse()
        return failed[:limit]

    def get_negotiations_by_domain(self, domain: str) -> list[NegotiationRecord]:
        """
        Get all negotiations for a specific task domain.

        Args:
            domain: Task domain to filter by

        Returns:
            List of NegotiationRecord matching the domain
        """
        with self._lock:
            return [r for r in self._records if r.task_domain == domain]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> NegotiationStats:
        """Get aggregated negotiation statistics."""
        with self._lock:
            total = len(self._records)
            if total == 0:
                return NegotiationStats()

            converged = sum(1 for r in self._records if r.converged)
            failed = total - converged

            total_turns = sum(r.turn_count for r in self._records)
            avg_turns = total_turns / total

            total_duration = sum(r.duration_ms for r in self._records)
            avg_duration = total_duration / total

            most_proposed = ""
            if self._mode_proposals:
                most_proposed = max(
                    self._mode_proposals,
                    key=self._mode_proposals.get,  # type: ignore[arg-type]
                )

            most_agreed = ""
            if self._mode_agreements:
                most_agreed = max(
                    self._mode_agreements,
                    key=self._mode_agreements.get,  # type: ignore[arg-type]
                )

        return NegotiationStats(
            total_negotiations=total,
            converged_count=converged,
            failed_count=failed,
            avg_turns=avg_turns,
            avg_duration_ms=avg_duration,
            most_proposed_mode=most_proposed,
            most_agreed_mode=most_agreed,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def negotiation_count(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        """Clear all tracked data."""
        with self._lock:
            self._records.clear()
            self._mode_proposals.clear()
            self._mode_agreements.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        # CRITICAL: call get_stats() BEFORE acquiring self._lock
        # to avoid deadlock (get_stats also acquires the lock).
        stats = self.get_stats()
        with self._lock:
            return {
                "negotiation_count": len(self._records),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_tracker: NegotiationTracker | None = None
_tracker_lock = threading.Lock()


def get_negotiation_tracker() -> NegotiationTracker:
    """Get or create the global negotiation tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = NegotiationTracker()
    return _tracker


def reset_negotiation_tracker() -> None:
    """Reset the global negotiation tracker (for testing)."""
    global _tracker
    _tracker = None
