"""
Alignment Journal - Track alignment verifications and violations.

V12.4 COGNITIVE BOOST

Provides persistent journaling of alignment checks:
- Record verifications (agent aligned with principle? pass/fail)
- Record violations (severity, remediation)
- Compute trust scores per agent
- Track alignment trends

Usage:
    from core.security_pkg.governance.alignment_journal import get_alignment_journal

    journal = get_alignment_journal()
    journal.record_verification("claude", principle="safety", passed=True, score=0.95)
    journal.record_violation("rogue", principle="transparency", severity="high",
                             remediation="Blocked output")
    trust = journal.get_trust_score("claude")
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
DEFAULT_TRUST_SCORE = 1.0
TRUST_DECAY_PER_VIOLATION = 0.1
TRUST_RECOVERY_PER_PASS = 0.02


# =============================================================================
# Types
# =============================================================================


@dataclass
class VerificationEntry:
    """Record of an alignment verification."""

    agent_id: str
    principle: str
    passed: bool
    score: float = 0.0  # 0.0-1.0, how well aligned
    timestamp: float = field(default_factory=time.monotonic)
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "principle": self.principle,
            "passed": self.passed,
            "score": round(self.score, 4),
            "details": self.details,
        }


@dataclass
class ViolationEntry:
    """Record of an alignment violation."""

    agent_id: str
    principle: str
    severity: str = "medium"  # low, medium, high, critical
    remediation: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "principle": self.principle,
            "severity": self.severity,
            "remediation": self.remediation,
            "details": self.details,
        }


@dataclass
class TrustScore:
    """Computed trust score for an agent."""

    agent_id: str
    score: float
    total_verifications: int
    total_violations: int
    passes: int
    fails: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "score": round(self.score, 4),
            "total_verifications": self.total_verifications,
            "total_violations": self.total_violations,
            "passes": self.passes,
            "fails": self.fails,
        }


@dataclass
class JournalStats:
    """Journal statistics."""

    total_verifications: int
    total_violations: int
    unique_agents: int
    unique_principles: int
    average_trust: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_verifications": self.total_verifications,
            "total_violations": self.total_violations,
            "unique_agents": self.unique_agents,
            "unique_principles": self.unique_principles,
            "average_trust": round(self.average_trust, 4),
        }


# =============================================================================
# Alignment Journal
# =============================================================================


class AlignmentJournal:
    """
    Persistent journal of alignment verifications and violations.

    Features:
    - Record pass/fail verifications per agent and principle
    - Record violations with severity and remediation
    - Compute trust scores (decays on violations, recovers on passes)
    - Query by agent, principle, severity
    - Thread-safe, bounded history
    """

    def __init__(self, *, max_entries: int = MAX_ENTRIES):
        self._max_entries = max_entries
        self._verifications: list[VerificationEntry] = []
        self._violations: list[ViolationEntry] = []
        self._trust_scores: dict[str, float] = {}  # agent_id -> trust score
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_verification(
        self,
        agent_id: str,
        *,
        principle: str,
        passed: bool,
        score: float = 0.0,
        details: str = "",
    ) -> VerificationEntry:
        """Record an alignment verification."""
        entry = VerificationEntry(
            agent_id=agent_id,
            principle=principle,
            passed=passed,
            score=max(0.0, min(1.0, score)),
            details=details,
        )
        with self._lock:
            self._verifications.append(entry)
            while len(self._verifications) > self._max_entries:
                self._verifications.pop(0)

            # Update trust
            if agent_id not in self._trust_scores:
                self._trust_scores[agent_id] = DEFAULT_TRUST_SCORE

            if passed:
                self._trust_scores[agent_id] = min(
                    1.0,
                    self._trust_scores[agent_id] + TRUST_RECOVERY_PER_PASS,
                )
            else:
                self._trust_scores[agent_id] = max(
                    0.0,
                    self._trust_scores[agent_id] - TRUST_DECAY_PER_VIOLATION,
                )

        return entry

    def record_violation(
        self,
        agent_id: str,
        *,
        principle: str,
        severity: str = "medium",
        remediation: str = "",
        details: str = "",
    ) -> ViolationEntry:
        """Record an alignment violation."""
        entry = ViolationEntry(
            agent_id=agent_id,
            principle=principle,
            severity=severity,
            remediation=remediation,
            details=details,
        )
        with self._lock:
            self._violations.append(entry)
            while len(self._violations) > self._max_entries:
                self._violations.pop(0)

            # Apply trust penalty based on severity
            if agent_id not in self._trust_scores:
                self._trust_scores[agent_id] = DEFAULT_TRUST_SCORE

            severity_multiplier = {"low": 0.5, "medium": 1.0, "high": 2.0, "critical": 3.0}
            decay = TRUST_DECAY_PER_VIOLATION * severity_multiplier.get(severity, 1.0)
            self._trust_scores[agent_id] = max(0.0, self._trust_scores[agent_id] - decay)

        return entry

    # =========================================================================
    # Trust Scores
    # =========================================================================

    def get_trust_score(self, agent_id: str) -> TrustScore | None:
        """Get the trust score for an agent."""
        if agent_id not in self._trust_scores:
            return None

        verifications = [v for v in self._verifications if v.agent_id == agent_id]
        violations = [v for v in self._violations if v.agent_id == agent_id]
        passes = sum(1 for v in verifications if v.passed)
        fails = sum(1 for v in verifications if not v.passed)

        return TrustScore(
            agent_id=agent_id,
            score=self._trust_scores[agent_id],
            total_verifications=len(verifications),
            total_violations=len(violations),
            passes=passes,
            fails=fails,
        )

    def get_all_trust_scores(self) -> list[TrustScore]:
        """Get trust scores for all agents, sorted by score ascending."""
        scores = []
        for agent_id in sorted(self._trust_scores.keys()):
            ts = self.get_trust_score(agent_id)
            if ts:
                scores.append(ts)
        return sorted(scores, key=lambda t: t.score)

    def get_untrusted_agents(self, threshold: float = 0.5) -> list[str]:
        """Get agents with trust score below threshold."""
        return sorted(aid for aid, score in self._trust_scores.items() if score < threshold)

    # =========================================================================
    # Queries
    # =========================================================================

    def get_verifications(
        self,
        *,
        agent_id: str | None = None,
        principle: str | None = None,
        limit: int = 100,
    ) -> list[VerificationEntry]:
        """Query verifications with optional filters."""
        results = []
        for entry in reversed(self._verifications):
            if agent_id and entry.agent_id != agent_id:
                continue
            if principle and entry.principle != principle:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_violations(
        self,
        *,
        agent_id: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[ViolationEntry]:
        """Query violations with optional filters."""
        results = []
        for entry in reversed(self._violations):
            if agent_id and entry.agent_id != agent_id:
                continue
            if severity and entry.severity != severity:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_agent_history(self, agent_id: str) -> dict[str, Any]:
        """Get complete alignment history for an agent."""
        verifications = [v for v in self._verifications if v.agent_id == agent_id]
        violations = [v for v in self._violations if v.agent_id == agent_id]
        return {
            "agent_id": agent_id,
            "trust_score": self._trust_scores.get(agent_id, DEFAULT_TRUST_SCORE),
            "verifications": len(verifications),
            "violations": len(violations),
            "passes": sum(1 for v in verifications if v.passed),
            "fails": sum(1 for v in verifications if not v.passed),
        }

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> JournalStats:
        agents = set()
        principles = set()
        for v in self._verifications:
            agents.add(v.agent_id)
            principles.add(v.principle)
        for v in self._violations:
            agents.add(v.agent_id)
            principles.add(v.principle)

        trust_values = list(self._trust_scores.values())
        avg_trust = sum(trust_values) / len(trust_values) if trust_values else 0.0

        return JournalStats(
            total_verifications=len(self._verifications),
            total_violations=len(self._violations),
            unique_agents=len(agents),
            unique_principles=len(principles),
            average_trust=avg_trust,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def verification_count(self) -> int:
        return len(self._verifications)

    @property
    def violation_count(self) -> int:
        return len(self._violations)

    def clear(self) -> None:
        with self._lock:
            self._verifications.clear()
            self._violations.clear()
            self._trust_scores.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_count": self.verification_count,
            "violation_count": self.violation_count,
            "agents_tracked": len(self._trust_scores),
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_journal: AlignmentJournal | None = None
_journal_lock = threading.Lock()


def get_alignment_journal() -> AlignmentJournal:
    """Get or create the global alignment journal."""
    global _journal
    if _journal is None:
        with _journal_lock:
            if _journal is None:
                _journal = AlignmentJournal()
    return _journal


def reset_alignment_journal() -> None:
    """Reset the global alignment journal (for testing)."""
    global _journal
    _journal = None
