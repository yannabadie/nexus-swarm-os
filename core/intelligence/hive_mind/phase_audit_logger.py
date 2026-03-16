"""
Phase Audit Logger - Structured decision audit per HiveMind phase.

V12.4 COGNITIVE BOOST

Records and analyzes decisions made during each HiveMind phase,
with reasoning, timing, and pattern detection.

Usage:
    from core.intelligence.hive_mind.phase_audit_logger import get_phase_audit_logger

    logger = get_phase_audit_logger()

    # Record a decision
    audit = logger.record_decision(
        session_id="sess1",
        phase="ANALYSIS",
        decision="use_parallel_analysis",
        options_considered=["parallel", "sequential"],
        reasoning="Both agents available",
        agent_id="claude",
        duration_ms=120.5,
    )

    # Query by session
    audits = logger.query_by_session("sess1")

    # Get phase report
    report = logger.get_phase_report("ANALYSIS")

    # Detect patterns
    patterns = logger.detect_patterns()
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

MAX_AUDITS = 50000

PHASES: set[str] = {
    "ANALYSIS",
    "DEBATE",
    "ARCHITECTURE",
    "EXECUTION",
    "DIAGNOSIS",
    "RETRY",
    "CONSOLIDATION",
}


# =============================================================================
# Types
# =============================================================================


@dataclass
class DecisionAudit:
    """A single recorded decision from a HiveMind phase."""

    audit_id: str
    session_id: str = ""
    phase: str = ""
    decision: str = ""
    options_considered: list[str] = field(default_factory=list)
    reasoning: str = ""
    agent_id: str = ""
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "session_id": self.session_id,
            "phase": self.phase,
            "decision": self.decision,
            "options_considered": list(self.options_considered),
            "reasoning": self.reasoning,
            "agent_id": self.agent_id,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass
class PhaseAuditReport:
    """Aggregated report for a single phase."""

    phase: str
    total_decisions: int
    avg_duration_ms: float
    unique_agents: int
    most_common_decision: str
    decision_distribution: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "total_decisions": self.total_decisions,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "unique_agents": self.unique_agents,
            "most_common_decision": self.most_common_decision,
            "decision_distribution": dict(self.decision_distribution),
        }


@dataclass
class AuditPattern:
    """A detected pattern across audit data."""

    pattern_type: str
    phase: str
    description: str
    frequency: float
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "phase": self.phase,
            "description": self.description,
            "frequency": round(self.frequency, 4),
            "sample_count": self.sample_count,
        }


@dataclass
class AuditStats:
    """Overall statistics for the audit logger."""

    total_audits: int
    audits_by_phase: dict[str, int]
    unique_sessions: int
    unique_agents: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_audits": self.total_audits,
            "audits_by_phase": dict(self.audits_by_phase),
            "unique_sessions": self.unique_sessions,
            "unique_agents": self.unique_agents,
        }


# =============================================================================
# Phase Audit Logger
# =============================================================================


class PhaseAuditLogger:
    """
    Records and analyzes decisions made during each HiveMind phase.

    Features:
    - Thread-safe decision recording with auto-generated IDs
    - Bounded history with configurable maximum
    - Query by session, phase, or agent
    - Phase-level aggregate reports
    - Cross-phase pattern detection
    - Session timeline reconstruction
    """

    def __init__(self, *, max_audits: int = MAX_AUDITS):
        self._audits: list[DecisionAudit] = []
        self._counter: int = 0
        self._max_audits: int = max_audits
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_decision(
        self,
        *,
        session_id: str = "",
        phase: str = "",
        decision: str = "",
        options_considered: list[str] | None = None,
        reasoning: str = "",
        agent_id: str = "",
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionAudit:
        """
        Record a decision made during a HiveMind phase.

        Args:
            session_id: Session identifier.
            phase: Phase name (from PHASES).
            decision: What was decided.
            options_considered: Alternatives that were evaluated.
            reasoning: Why this decision was made.
            agent_id: Who made the decision.
            duration_ms: Time taken to reach the decision.
            metadata: Additional context.

        Returns:
            The recorded DecisionAudit.
        """
        with self._lock:
            self._counter += 1
            audit_id = f"pa_{self._counter:06d}"

            audit = DecisionAudit(
                audit_id=audit_id,
                session_id=session_id,
                phase=phase,
                decision=decision,
                options_considered=list(options_considered) if options_considered else [],
                reasoning=reasoning,
                agent_id=agent_id,
                duration_ms=duration_ms,
                metadata=dict(metadata) if metadata else {},
            )

            self._audits.append(audit)

            # Evict oldest if at capacity
            if len(self._audits) > self._max_audits:
                self._audits = self._audits[-self._max_audits :]

        _logger.debug(
            "Recorded decision %s: phase=%s decision=%s agent=%s",
            audit_id,
            phase,
            decision,
            agent_id,
        )
        return audit

    # =========================================================================
    # Queries
    # =========================================================================

    def query_by_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
    ) -> list[DecisionAudit]:
        """
        Query audits by session ID, most recent first.

        Args:
            session_id: Session identifier.
            limit: Maximum results to return.

        Returns:
            List of matching audits, most recent first.
        """
        with self._lock:
            matched = [a for a in self._audits if a.session_id == session_id]
        matched.reverse()
        return matched[:limit]

    def query_by_phase(
        self,
        phase: str,
        *,
        limit: int = 100,
    ) -> list[DecisionAudit]:
        """
        Query audits by phase, most recent first.

        Args:
            phase: Phase name.
            limit: Maximum results to return.

        Returns:
            List of matching audits, most recent first.
        """
        with self._lock:
            matched = [a for a in self._audits if a.phase == phase]
        matched.reverse()
        return matched[:limit]

    def query_by_agent(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[DecisionAudit]:
        """
        Query audits by agent ID, most recent first.

        Args:
            agent_id: Agent identifier.
            limit: Maximum results to return.

        Returns:
            List of matching audits, most recent first.
        """
        with self._lock:
            matched = [a for a in self._audits if a.agent_id == agent_id]
        matched.reverse()
        return matched[:limit]

    def get_recent(self, *, limit: int = 50) -> list[DecisionAudit]:
        """
        Get most recent audits.

        Args:
            limit: Maximum results to return.

        Returns:
            List of audits, most recent first.
        """
        with self._lock:
            snapshot = list(self._audits)
        snapshot.reverse()
        return snapshot[:limit]

    # =========================================================================
    # Analytics
    # =========================================================================

    def get_phase_report(self, phase: str) -> PhaseAuditReport | None:
        """
        Generate an aggregate report for a specific phase.

        Args:
            phase: Phase name.

        Returns:
            PhaseAuditReport, or None if no audits exist for the phase.
        """
        with self._lock:
            phase_audits = [a for a in self._audits if a.phase == phase]

        if not phase_audits:
            return None

        total = len(phase_audits)

        # Average duration
        durations = [a.duration_ms for a in phase_audits]
        avg_duration = sum(durations) / total

        # Unique agents
        agents: set[str] = set()
        for a in phase_audits:
            if a.agent_id:
                agents.add(a.agent_id)

        # Decision distribution
        distribution: dict[str, int] = defaultdict(int)
        for a in phase_audits:
            if a.decision:
                distribution[a.decision] += 1

        # Most common decision
        most_common = ""
        if distribution:
            most_common = max(distribution, key=lambda k: distribution[k])

        return PhaseAuditReport(
            phase=phase,
            total_decisions=total,
            avg_duration_ms=avg_duration,
            unique_agents=len(agents),
            most_common_decision=most_common,
            decision_distribution=dict(distribution),
        )

    def detect_patterns(
        self,
        *,
        min_frequency: float = 0.6,
    ) -> list[AuditPattern]:
        """
        Detect decision patterns across phases.

        Looks for:
        - consistent_routing: A single decision dominates a phase
          (>= min_frequency).
        - frequent_retry: RETRY phase has >= 3 audits.

        Args:
            min_frequency: Minimum frequency (0-1) for consistent routing.

        Returns:
            List of detected AuditPattern objects.
        """
        with self._lock:
            snapshot = list(self._audits)

        patterns: list[AuditPattern] = []

        # Group audits by phase
        by_phase: dict[str, list[DecisionAudit]] = defaultdict(list)
        for a in snapshot:
            if a.phase:
                by_phase[a.phase].append(a)

        # Check for consistent routing per phase
        for phase, audits in by_phase.items():
            if not audits:
                continue

            distribution: dict[str, int] = defaultdict(int)
            for a in audits:
                if a.decision:
                    distribution[a.decision] += 1

            total = len(audits)
            for decision, count in distribution.items():
                freq = count / total
                if freq >= min_frequency:
                    patterns.append(
                        AuditPattern(
                            pattern_type="consistent_routing",
                            phase=phase,
                            description=(f"Decision '{decision}' occurs {freq:.0%} of the time in {phase}"),
                            frequency=freq,
                            sample_count=total,
                        )
                    )

        # Check for frequent retry
        retry_audits = by_phase.get("RETRY", [])
        if len(retry_audits) >= 3:
            patterns.append(
                AuditPattern(
                    pattern_type="frequent_retry",
                    phase="RETRY",
                    description=(f"RETRY phase has {len(retry_audits)} audit entries"),
                    frequency=1.0,
                    sample_count=len(retry_audits),
                )
            )

        return patterns

    def get_session_timeline(
        self,
        session_id: str,
    ) -> list[DecisionAudit]:
        """
        Get all audits for a session ordered by timestamp ascending.

        Args:
            session_id: Session identifier.

        Returns:
            List of audits in timeline (chronological) order.
        """
        with self._lock:
            matched = [a for a in self._audits if a.session_id == session_id]
        matched.sort(key=lambda a: a.timestamp)
        return matched

    # =========================================================================
    # State
    # =========================================================================

    def _get_stats_unlocked(self) -> AuditStats:
        """Compute stats without acquiring the lock (caller must hold lock)."""
        by_phase: dict[str, int] = defaultdict(int)
        sessions: set[str] = set()
        agents: set[str] = set()

        for a in self._audits:
            if a.phase:
                by_phase[a.phase] += 1
            if a.session_id:
                sessions.add(a.session_id)
            if a.agent_id:
                agents.add(a.agent_id)

        return AuditStats(
            total_audits=len(self._audits),
            audits_by_phase=dict(by_phase),
            unique_sessions=len(sessions),
            unique_agents=len(agents),
        )

    def get_stats(self) -> AuditStats:
        """
        Get overall audit statistics.

        Returns:
            AuditStats with totals and breakdowns.
        """
        with self._lock:
            return self._get_stats_unlocked()

    @property
    def size(self) -> int:
        """Number of audits currently stored."""
        with self._lock:
            return len(self._audits)

    def clear(self) -> None:
        """Clear all audits and reset the counter."""
        with self._lock:
            self._audits.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize logger state to a dictionary."""
        stats = self.get_stats()
        with self._lock:
            max_audits = self._max_audits
        return {
            "max_audits": max_audits,
            "stats": stats.to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_logger_instance: PhaseAuditLogger | None = None
_logger_instance_lock = threading.Lock()


def get_phase_audit_logger() -> PhaseAuditLogger:
    """Get or create the global phase audit logger."""
    global _logger_instance
    if _logger_instance is None:
        with _logger_instance_lock:
            if _logger_instance is None:
                _logger_instance = PhaseAuditLogger()
    return _logger_instance


def reset_phase_audit_logger() -> None:
    """Reset the global phase audit logger (for testing)."""
    global _logger_instance
    _logger_instance = None
