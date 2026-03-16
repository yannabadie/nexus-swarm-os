"""
Consensus Tracker - Track agent agreement across hive mind phases.

V12.4 COGNITIVE BOOST - Task #60

Tracks positions taken by agents during debate and analysis phases,
measures consensus level, and identifies contentious points.

Usage:
    from core.intelligence.hive_mind.consensus_tracker import get_consensus_tracker

    tracker = get_consensus_tracker()

    # Record agent positions
    tracker.record("sess1", "analysis", "claude", "approach_A", confidence=0.9)
    tracker.record("sess1", "analysis", "gemini", "approach_A", confidence=0.8)

    # Check consensus
    score = tracker.get_consensus_score("sess1", "analysis")  # 1.0 (full agreement)

    # Identify disagreements
    disputes = tracker.get_disagreements("sess1")
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

DEFAULT_MIN_CONSENSUS = 0.8  # 80% agreement to conclude
MAX_SESSIONS = 1000


# =============================================================================
# Types
# =============================================================================


@dataclass
class Position:
    """An agent's position on a topic."""

    agent_id: str
    stance: str
    confidence: float = 1.0
    reasoning: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "stance": self.stance,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning[:200] if self.reasoning else "",
        }


@dataclass
class TopicConsensus:
    """Consensus state for a specific topic in a phase."""

    topic: str
    phase: str
    positions: list[Position] = field(default_factory=list)

    @property
    def agent_count(self) -> int:
        return len(self.positions)

    @property
    def unique_stances(self) -> set[str]:
        return set(p.stance for p in self.positions)

    @property
    def consensus_score(self) -> float:
        """0-1 score where 1.0 = full agreement."""
        if len(self.positions) < 2:
            return 1.0
        # Count most popular stance
        stance_counts: dict[str, int] = defaultdict(int)
        for p in self.positions:
            stance_counts[p.stance] += 1
        max_count = max(stance_counts.values())
        return max_count / len(self.positions)

    @property
    def weighted_consensus(self) -> float:
        """Consensus weighted by confidence."""
        if len(self.positions) < 2:
            return 1.0
        # Group by stance, sum confidence
        stance_conf: dict[str, float] = defaultdict(float)
        total_conf = 0.0
        for p in self.positions:
            stance_conf[p.stance] += p.confidence
            total_conf += p.confidence
        if total_conf == 0:
            return 0.0
        max_conf = max(stance_conf.values())
        return max_conf / total_conf

    @property
    def is_unanimous(self) -> bool:
        return len(self.unique_stances) <= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "phase": self.phase,
            "agent_count": self.agent_count,
            "unique_stances": len(self.unique_stances),
            "consensus_score": round(self.consensus_score, 4),
            "weighted_consensus": round(self.weighted_consensus, 4),
            "is_unanimous": self.is_unanimous,
        }


@dataclass
class Disagreement:
    """A point of disagreement between agents."""

    topic: str
    phase: str
    stances: dict[str, str]  # agent_id -> stance
    severity: float = 0.0  # 0 = minor, 1 = major

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "phase": self.phase,
            "stances": self.stances,
            "severity": round(self.severity, 3),
        }


@dataclass
class ConsensusReport:
    """Report on consensus state for a session."""

    session_id: str
    total_topics: int
    unanimous_topics: int
    disputed_topics: int
    overall_consensus: float
    phase_consensus: dict[str, float]
    top_disagreements: list[Disagreement]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_topics": self.total_topics,
            "unanimous_topics": self.unanimous_topics,
            "disputed_topics": self.disputed_topics,
            "overall_consensus": round(self.overall_consensus, 4),
            "phase_consensus": {k: round(v, 4) for k, v in self.phase_consensus.items()},
            "top_disagreements": [d.to_dict() for d in self.top_disagreements[:5]],
        }


# =============================================================================
# Consensus Tracker
# =============================================================================


class ConsensusTracker:
    """
    Tracks agent agreement across hive mind phases.

    Features:
    - Record agent positions with confidence
    - Per-topic and per-phase consensus scoring
    - Disagreement identification
    - Weighted consensus (by confidence)
    - Phase conclusion readiness check
    - Session-level consensus reports
    """

    def __init__(self, *, min_consensus: float = DEFAULT_MIN_CONSENSUS):
        # session_id -> phase -> topic -> TopicConsensus
        self._data: dict[str, dict[str, dict[str, TopicConsensus]]] = defaultdict(lambda: defaultdict(dict))
        self._min_consensus = min_consensus
        self._lock = threading.Lock()

    # =========================================================================
    # Record
    # =========================================================================

    def record(
        self,
        session_id: str,
        phase: str,
        agent_id: str,
        stance: str,
        *,
        topic: str = "default",
        confidence: float = 1.0,
        reasoning: str = "",
    ) -> Position:
        """
        Record an agent's position on a topic.

        Args:
            session_id: Session identifier
            phase: Phase name (analysis, debate, architecture, etc.)
            agent_id: Agent taking the position
            stance: The agent's stance/opinion
            topic: Topic being discussed
            confidence: Agent's confidence (0-1)
            reasoning: Optional reasoning

        Returns:
            The recorded Position
        """
        position = Position(
            agent_id=agent_id,
            stance=stance,
            confidence=max(0.0, min(1.0, confidence)),
            reasoning=reasoning,
        )
        with self._lock:
            tc = self._data[session_id][phase].get(topic)
            if tc is None:
                tc = TopicConsensus(topic=topic, phase=phase)
                self._data[session_id][phase][topic] = tc
            # Replace existing position from same agent
            tc.positions = [p for p in tc.positions if p.agent_id != agent_id]
            tc.positions.append(position)
        return position

    # =========================================================================
    # Consensus Queries
    # =========================================================================

    def get_consensus_score(
        self,
        session_id: str,
        phase: str,
        topic: str = "default",
    ) -> float:
        """Get consensus score for a specific topic (0-1)."""
        with self._lock:
            tc = self._data.get(session_id, {}).get(phase, {}).get(topic)
        if tc is None:
            return 0.0
        return tc.consensus_score

    def get_phase_consensus(self, session_id: str, phase: str) -> float:
        """Get average consensus across all topics in a phase."""
        with self._lock:
            topics = self._data.get(session_id, {}).get(phase, {})
            if not topics:
                return 0.0
            scores = [tc.consensus_score for tc in topics.values()]
        return sum(scores) / len(scores) if scores else 0.0

    def get_session_consensus(self, session_id: str) -> float:
        """Get overall consensus across all phases."""
        with self._lock:
            phases = self._data.get(session_id, {})
            if not phases:
                return 0.0
            all_scores = []
            for topics in phases.values():
                for tc in topics.values():
                    all_scores.append(tc.consensus_score)
        return sum(all_scores) / len(all_scores) if all_scores else 0.0

    def get_topic_consensus(
        self,
        session_id: str,
        phase: str,
        topic: str = "default",
    ) -> TopicConsensus | None:
        """Get full TopicConsensus object."""
        with self._lock:
            return self._data.get(session_id, {}).get(phase, {}).get(topic)

    # =========================================================================
    # Disagreements
    # =========================================================================

    def get_disagreements(
        self,
        session_id: str,
        *,
        phase: str | None = None,
    ) -> list[Disagreement]:
        """Get all topics where agents disagree."""
        disagreements = []
        with self._lock:
            phases = self._data.get(session_id, {})
            for p_name, topics in phases.items():
                if phase and p_name != phase:
                    continue
                for t_name, tc in topics.items():
                    if not tc.is_unanimous and tc.agent_count >= 2:
                        stances = {p.agent_id: p.stance for p in tc.positions}
                        severity = 1.0 - tc.consensus_score
                        disagreements.append(
                            Disagreement(
                                topic=t_name,
                                phase=p_name,
                                stances=stances,
                                severity=severity,
                            )
                        )
        disagreements.sort(key=lambda d: -d.severity)
        return disagreements

    # =========================================================================
    # Phase Control
    # =========================================================================

    def can_conclude_phase(
        self,
        session_id: str,
        phase: str,
        *,
        min_consensus: float | None = None,
    ) -> bool:
        """
        Check if a phase can be concluded based on consensus level.

        Returns True if average consensus >= threshold.
        """
        threshold = min_consensus if min_consensus is not None else self._min_consensus
        score = self.get_phase_consensus(session_id, phase)
        return score >= threshold

    def should_debate(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        """Check if a debate is needed (consensus too low)."""
        return not self.can_conclude_phase(session_id, phase)

    # =========================================================================
    # Report
    # =========================================================================

    def get_report(self, session_id: str) -> ConsensusReport:
        """Generate a consensus report for a session."""
        with self._lock:
            phases = self._data.get(session_id, {})
            all_topics = []
            phase_scores: dict[str, list[float]] = defaultdict(list)
            for p_name, topics in phases.items():
                for tc in topics.values():
                    all_topics.append(tc)
                    phase_scores[p_name].append(tc.consensus_score)

        unanimous = sum(1 for tc in all_topics if tc.is_unanimous)
        disputed = sum(1 for tc in all_topics if not tc.is_unanimous and tc.agent_count >= 2)
        overall = sum(tc.consensus_score for tc in all_topics) / len(all_topics) if all_topics else 0.0

        phase_avg = {p: sum(scores) / len(scores) if scores else 0.0 for p, scores in phase_scores.items()}

        disagreements = self.get_disagreements(session_id)

        return ConsensusReport(
            session_id=session_id,
            total_topics=len(all_topics),
            unanimous_topics=unanimous,
            disputed_topics=disputed,
            overall_consensus=overall,
            phase_consensus=phase_avg,
            top_disagreements=disagreements[:5],
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def session_count(self) -> int:
        return len(self._data)

    def topic_count(self, session_id: str) -> int:
        """Count topics across all phases for a session."""
        count = 0
        with self._lock:
            for topics in self._data.get(session_id, {}).values():
                count += len(topics)
        return count

    def clear_session(self, session_id: str) -> bool:
        """Clear all data for a session."""
        with self._lock:
            return self._data.pop(session_id, None) is not None

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._data.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "min_consensus": self._min_consensus,
        }


# =============================================================================
# Global Instance
# =============================================================================

_tracker: ConsensusTracker | None = None
_tracker_lock = threading.Lock()


def get_consensus_tracker() -> ConsensusTracker:
    """Get or create the global consensus tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ConsensusTracker()
    return _tracker


def reset_consensus_tracker() -> None:
    """Reset the global consensus tracker (for testing)."""
    global _tracker
    _tracker = None
