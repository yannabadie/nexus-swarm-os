"""
Governance Decision Logger - Record decisions with rationale for audit.

V12.4 COGNITIVE BOOST

Records all governance-level decisions:
- Collaboration mode choices (why PARALLEL vs SPECIALIST?)
- Agent spawn decisions (approved/rejected, rationale)
- Policy violations and remediations
- Phase routing decisions

Usage:
    from core.security_pkg.governance.decision_logger import get_decision_logger

    logger = get_decision_logger()
    logger.record_mode_choice(
        session_id="sess_1", proposed_mode="PARALLEL",
        accepted_mode="LEAD_SUPPORT", reasoning="Lead has more context",
        agents=["claude", "gemini"],
    )
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_ENTRIES = 50000
DECISION_TYPES = {"mode_choice", "spawn_decision", "policy_violation", "phase_routing"}


# =============================================================================
# Types
# =============================================================================


@dataclass
class GovernanceDecision:
    """A recorded governance decision."""

    decision_id: str
    decision_type: str  # mode_choice, spawn_decision, policy_violation, phase_routing
    session_id: str = ""
    agent_id: str = ""
    reasoning: str = ""
    outcome: str = ""  # approved, rejected, accepted, remediated
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "reasoning": self.reasoning,
            "outcome": self.outcome,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class DecisionPattern:
    """Aggregated pattern from decision history."""

    decision_type: str
    outcome: str
    count: int
    frequency: float  # proportion of total decisions of this type

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type,
            "outcome": self.outcome,
            "count": self.count,
            "frequency": round(self.frequency, 4),
        }


@dataclass
class DecisionLogStats:
    """Decision log statistics."""

    total_decisions: int
    mode_choices: int
    spawn_decisions: int
    policy_violations: int
    phase_routings: int
    unique_sessions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_decisions": self.total_decisions,
            "mode_choices": self.mode_choices,
            "spawn_decisions": self.spawn_decisions,
            "policy_violations": self.policy_violations,
            "phase_routings": self.phase_routings,
            "unique_sessions": self.unique_sessions,
        }


# =============================================================================
# Decision Logger
# =============================================================================


class GovernanceDecisionLog:
    """
    Append-only log of governance decisions with analytics.

    Features:
    - Record decisions by type (mode choice, spawn, violation, routing)
    - Query by session, agent, type, and time range
    - Pattern analysis (most common outcomes per type)
    - Thread-safe, bounded history
    """

    def __init__(self, *, max_entries: int = MAX_ENTRIES):
        self._max_entries = max_entries
        self._entries: list[GovernanceDecision] = []
        self._next_id = 1
        self._lock = threading.Lock()

    def _gen_id(self) -> str:
        """Generate a sequential decision ID."""
        did = f"gd_{self._next_id:06d}"
        self._next_id += 1
        return did

    # =========================================================================
    # Recording Methods
    # =========================================================================

    def record_mode_choice(
        self,
        *,
        session_id: str = "",
        proposed_mode: str = "",
        accepted_mode: str = "",
        reasoning: str = "",
        agents: list[str] | None = None,
    ) -> GovernanceDecision:
        """Record a collaboration mode choice decision."""
        return self._record(
            decision_type="mode_choice",
            session_id=session_id,
            reasoning=reasoning,
            outcome=accepted_mode,
            metadata={
                "proposed_mode": proposed_mode,
                "accepted_mode": accepted_mode,
                "agents": agents or [],
            },
        )

    def record_spawn_decision(
        self,
        *,
        session_id: str = "",
        agent_id: str = "",
        agent_spec: str = "",
        approved: bool = True,
        reasoning: str = "",
    ) -> GovernanceDecision:
        """Record an agent spawn decision."""
        return self._record(
            decision_type="spawn_decision",
            session_id=session_id,
            agent_id=agent_id,
            reasoning=reasoning,
            outcome="approved" if approved else "rejected",
            metadata={"agent_spec": agent_spec},
        )

    def record_policy_violation(
        self,
        *,
        session_id: str = "",
        agent_id: str = "",
        violation_type: str = "",
        severity: str = "medium",
        remediation: str = "",
    ) -> GovernanceDecision:
        """Record a policy violation and remediation."""
        return self._record(
            decision_type="policy_violation",
            session_id=session_id,
            agent_id=agent_id,
            reasoning=violation_type,
            outcome=remediation or "none",
            metadata={"severity": severity, "violation_type": violation_type},
        )

    def record_phase_routing(
        self,
        *,
        session_id: str = "",
        from_phase: str = "",
        to_phase: str = "",
        reasoning: str = "",
    ) -> GovernanceDecision:
        """Record a phase routing decision."""
        return self._record(
            decision_type="phase_routing",
            session_id=session_id,
            reasoning=reasoning,
            outcome=to_phase,
            metadata={"from_phase": from_phase, "to_phase": to_phase},
        )

    def _record(
        self,
        *,
        decision_type: str,
        session_id: str = "",
        agent_id: str = "",
        reasoning: str = "",
        outcome: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GovernanceDecision:
        """Internal: create and append a decision entry."""
        with self._lock:
            entry = GovernanceDecision(
                decision_id=self._gen_id(),
                decision_type=decision_type,
                session_id=session_id,
                agent_id=agent_id,
                reasoning=reasoning,
                outcome=outcome,
                metadata=metadata or {},
            )
            self._entries.append(entry)
            while len(self._entries) > self._max_entries:
                self._entries.pop(0)
            return entry

    # =========================================================================
    # Queries
    # =========================================================================

    def query_by_session(self, session_id: str, *, limit: int = 100) -> list[GovernanceDecision]:
        return self._filter(lambda e: e.session_id == session_id, limit)

    def query_by_agent(self, agent_id: str, *, limit: int = 100) -> list[GovernanceDecision]:
        return self._filter(lambda e: e.agent_id == agent_id, limit)

    def query_by_type(self, decision_type: str, *, limit: int = 100) -> list[GovernanceDecision]:
        return self._filter(lambda e: e.decision_type == decision_type, limit)

    def query_by_outcome(self, outcome: str, *, limit: int = 100) -> list[GovernanceDecision]:
        return self._filter(lambda e: e.outcome == outcome, limit)

    def get_recent(self, limit: int = 50) -> list[GovernanceDecision]:
        return list(reversed(self._entries[-limit:]))

    def get_violations(self, *, limit: int = 100) -> list[GovernanceDecision]:
        return self.query_by_type("policy_violation", limit=limit)

    def _filter(self, predicate, limit: int) -> list[GovernanceDecision]:
        results = []
        for entry in reversed(self._entries):
            if predicate(entry):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    # =========================================================================
    # Analytics
    # =========================================================================

    def analyze_patterns(self, decision_type: str) -> list[DecisionPattern]:
        """Analyze outcome patterns for a decision type."""
        type_entries = [e for e in self._entries if e.decision_type == decision_type]
        if not type_entries:
            return []

        outcome_counts: dict[str, int] = {}
        for e in type_entries:
            outcome_counts[e.outcome] = outcome_counts.get(e.outcome, 0) + 1

        total = len(type_entries)
        patterns = []
        for outcome, count in sorted(outcome_counts.items(), key=lambda x: -x[1]):
            patterns.append(
                DecisionPattern(
                    decision_type=decision_type,
                    outcome=outcome,
                    count=count,
                    frequency=count / total,
                )
            )
        return patterns

    def mode_success_summary(self) -> dict[str, int]:
        """Get count of each accepted mode."""
        counts: dict[str, int] = {}
        for e in self._entries:
            if e.decision_type == "mode_choice":
                mode = e.outcome
                counts[mode] = counts.get(mode, 0) + 1
        return counts

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> DecisionLogStats:
        mode_choices = sum(1 for e in self._entries if e.decision_type == "mode_choice")
        spawn_decisions = sum(1 for e in self._entries if e.decision_type == "spawn_decision")
        violations = sum(1 for e in self._entries if e.decision_type == "policy_violation")
        phase_routings = sum(1 for e in self._entries if e.decision_type == "phase_routing")
        sessions = {e.session_id for e in self._entries if e.session_id}
        return DecisionLogStats(
            total_decisions=len(self._entries),
            mode_choices=mode_choices,
            spawn_decisions=spawn_decisions,
            policy_violations=violations,
            phase_routings=phase_routings,
            unique_sessions=len(sessions),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def size(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._next_id = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_entries": self._max_entries,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_log: GovernanceDecisionLog | None = None
_log_lock = threading.Lock()


def get_decision_logger() -> GovernanceDecisionLog:
    """Get or create the global decision logger."""
    global _log
    if _log is None:
        with _log_lock:
            if _log is None:
                _log = GovernanceDecisionLog()
    return _log


def reset_decision_logger() -> None:
    """Reset the global decision logger (for testing)."""
    global _log
    _log = None
