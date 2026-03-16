"""
NEXUS V12.4 - Fault Detector (arXiv:2511.10400, CP-WBFT)

Confidence-weighted Byzantine fault detection for multi-agent systems.
Detects when an agent produces unreliable outputs by tracking
confidence-outcome correlation and flagging systematic deviations.

Based on: "Rethinking the Reliability of Multi-agent System:
A Perspective from Byzantine Fault Tolerance" (arXiv:2511.10400)

Key insight: LLMs naturally show greater skepticism when processing
erroneous messages. Agents downweight suspicious inputs based on their
intrinsic discriminative capability.

This module:
1. Tracks per-agent reliability via confidence probing
2. Detects Byzantine behavior (agent consistently wrong with high confidence)
3. Computes trust scores for agent outputs
4. Flags agents that should be excluded from consensus

Usage:
    detector = get_fault_detector()

    # Record agent output with confidence
    detector.record_output(
        agent_id="claude",
        confidence=0.9,
        was_correct=True,
    )

    # Check if an agent is currently faulty
    status = detector.check_agent("claude")
    if status.is_faulty:
        # Exclude from consensus or re-verify outputs
        ...

    # Get trust-weighted vote
    trust = detector.get_trust_score("claude")
"""

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class AgentStatus(Enum):
    """Agent reliability status."""

    TRUSTED = "trusted"  # Reliable outputs
    SUSPECT = "suspect"  # Some reliability issues
    FAULTY = "faulty"  # Consistently unreliable
    UNKNOWN = "unknown"  # Not enough data


@dataclass
class OutputRecord:
    """A single agent output observation."""

    agent_id: str
    confidence: float
    was_correct: bool
    timestamp: float = field(default_factory=time.time)


@dataclass
class FaultStatus:
    """Current fault status for an agent."""

    agent_id: str
    status: AgentStatus
    trust_score: float  # 0-1, higher = more trusted
    fault_rate: float  # Fraction of faulty outputs
    overconfidence_score: float  # How overconfident the agent is
    observations: int
    reason: str

    @property
    def is_faulty(self) -> bool:
        return self.status == AgentStatus.FAULTY

    @property
    def is_trusted(self) -> bool:
        return self.status == AgentStatus.TRUSTED


@dataclass
class DetectorStats:
    """Statistics for the fault detector."""

    total_observations: int
    agents_tracked: list[str]
    faulty_agents: list[str]
    avg_trust_score: float


# =============================================================================
# Fault Detector
# =============================================================================


class FaultDetector:
    """
    Confidence-weighted Byzantine fault detection for multi-agent systems.

    Tracks per-agent reliability by correlating stated confidence with
    actual correctness. Agents that are consistently wrong despite
    high confidence are flagged as potentially faulty.

    No LLM calls — pure statistical analysis.
    """

    # Detection parameters
    MIN_OBSERVATIONS = 5  # Minimum observations before judging
    FAULT_THRESHOLD = 0.4  # Fault rate above this = faulty
    SUSPECT_THRESHOLD = 0.25  # Fault rate above this = suspect
    OVERCONFIDENCE_PENALTY = 0.3  # Penalty for high confidence + wrong
    TRUST_DECAY = 0.95  # Trust decay per observation window
    MAX_HISTORY = 100  # Max observations per agent

    def __init__(self):
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.MAX_HISTORY))
        self._total_observations = 0
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def record_output(
        self,
        agent_id: str,
        confidence: float,
        was_correct: bool,
    ) -> None:
        """
        Record an agent output with its confidence and correctness.

        Args:
            agent_id: Agent identifier
            confidence: Agent's stated confidence [0, 1]
            was_correct: Whether the output was actually correct
        """
        confidence = max(0.0, min(1.0, confidence))

        record = OutputRecord(
            agent_id=agent_id,
            confidence=confidence,
            was_correct=was_correct,
        )

        with self._lock:
            self._history[agent_id].append(record)
            self._total_observations += 1

    def check_agent(self, agent_id: str) -> FaultStatus:
        """
        Check the current fault status of an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            FaultStatus with trust score, fault rate, and status
        """
        with self._lock:
            records = list(self._history.get(agent_id, []))

        if len(records) < self.MIN_OBSERVATIONS:
            return FaultStatus(
                agent_id=agent_id,
                status=AgentStatus.UNKNOWN,
                trust_score=0.5,
                fault_rate=0.0,
                overconfidence_score=0.0,
                observations=len(records),
                reason="Insufficient observations",
            )

        # Compute fault rate
        incorrect = sum(1 for r in records if not r.was_correct)
        fault_rate = incorrect / len(records)

        # Compute overconfidence: high confidence on wrong outputs
        overconfidence = self._compute_overconfidence(records)

        # Compute trust score
        trust = self._compute_trust(records, fault_rate, overconfidence)

        # Determine status
        if fault_rate >= self.FAULT_THRESHOLD:
            status = AgentStatus.FAULTY
            reason = f"Fault rate {fault_rate:.0%} exceeds threshold {self.FAULT_THRESHOLD:.0%}"
        elif fault_rate >= self.SUSPECT_THRESHOLD:
            status = AgentStatus.SUSPECT
            reason = f"Fault rate {fault_rate:.0%} elevated (threshold {self.SUSPECT_THRESHOLD:.0%})"
        else:
            status = AgentStatus.TRUSTED
            reason = f"Fault rate {fault_rate:.0%} within acceptable range"

        # Overconfidence can escalate status
        if overconfidence > 0.5 and status == AgentStatus.SUSPECT:
            status = AgentStatus.FAULTY
            reason += f"; high overconfidence ({overconfidence:.2f})"

        result = FaultStatus(
            agent_id=agent_id,
            status=status,
            trust_score=trust,
            fault_rate=fault_rate,
            overconfidence_score=overconfidence,
            observations=len(records),
            reason=reason,
        )

        if result.is_faulty:
            logger.warning(
                f"FaultDetector: agent '{agent_id}' flagged as FAULTY "
                f"(fault_rate={fault_rate:.0%}, overconfidence={overconfidence:.2f})"
            )

        return result

    def get_trust_score(self, agent_id: str) -> float:
        """
        Get the trust score for an agent (0-1).

        Shorthand for check_agent().trust_score.
        """
        return self.check_agent(agent_id).trust_score

    def get_weighted_vote(
        self,
        votes: dict[str, str],
    ) -> dict[str, float]:
        """
        Weight agent votes by their trust scores.

        Args:
            votes: agent_id -> vote_value mapping

        Returns:
            vote_value -> weighted_score mapping (sum of trust scores per vote)
        """
        weighted: dict[str, float] = defaultdict(float)

        for agent_id, vote in votes.items():
            trust = self.get_trust_score(agent_id)
            weighted[vote] += trust

        return dict(weighted)

    def get_stats(self) -> DetectorStats:
        """Get detector statistics."""
        with self._lock:
            agents = list(self._history.keys())

        faulty = []
        trust_sum = 0.0
        for aid in agents:
            status = self.check_agent(aid)
            if status.is_faulty:
                faulty.append(aid)
            trust_sum += status.trust_score

        avg_trust = trust_sum / max(len(agents), 1)

        return DetectorStats(
            total_observations=self._total_observations,
            agents_tracked=agents,
            faulty_agents=faulty,
            avg_trust_score=avg_trust,
        )

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _compute_overconfidence(self, records: list[OutputRecord]) -> float:
        """
        Compute overconfidence score.

        High confidence on wrong outputs is a strong signal of Byzantine behavior.
        """
        wrong_records = [r for r in records if not r.was_correct]
        if not wrong_records:
            return 0.0

        # Average confidence on wrong outputs
        avg_wrong_conf = sum(r.confidence for r in wrong_records) / len(wrong_records)

        # Scale: 0.5 confidence on wrong = 0.0 overconfidence
        #        1.0 confidence on wrong = 1.0 overconfidence
        return max(0.0, (avg_wrong_conf - 0.5) * 2.0)

    def _compute_trust(
        self,
        records: list[OutputRecord],
        fault_rate: float,
        overconfidence: float,
    ) -> float:
        """
        Compute trust score (0-1) based on fault rate, recency, and overconfidence.
        """
        # Base trust from correctness rate
        base_trust = 1.0 - fault_rate

        # Overconfidence penalty
        penalty = overconfidence * self.OVERCONFIDENCE_PENALTY

        # Recency weighting: recent records matter more
        if len(records) >= 5:
            recent = records[-5:]
            recent_correct = sum(1 for r in recent if r.was_correct)
            recency_factor = recent_correct / 5.0
        else:
            recency_factor = base_trust

        # Combined trust
        trust = base_trust * 0.5 + recency_factor * 0.3 - penalty * 0.2

        return max(0.0, min(1.0, trust))


# =============================================================================
# Singleton
# =============================================================================

_instance: FaultDetector | None = None
_instance_lock = threading.Lock()


def get_fault_detector() -> FaultDetector:
    """Get or create the singleton FaultDetector instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FaultDetector()
    return _instance


def reset_fault_detector() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
