"""
V12.4 COGNITIVE BOOST: Dynamic Role Assigner (arXiv:2601.17152)

Meta-Debate pre-negotiation where agents submit capability proposals
for each role, then proposals are scored against task requirements
before committing to role assignments. Achieves up to 74.8% improvement
over uniform assignment.

Two-stage process:
1. Proposal: Each agent submits capability claims per role (lead/support)
2. Peer Review: Proposals scored against task domains and history

Reference: "Dynamic Role Assignment for Multi-Agent Debate"
(arXiv:2601.17152)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class RoleType(str, Enum):
    """Roles available for assignment."""

    LEAD = "lead"
    SUPPORT = "support"
    EQUAL = "equal"
    SPECIALIST = "specialist"


@dataclass
class CapabilityProposal:
    """Agent's capability claim for a specific role."""

    agent_id: str
    role: RoleType
    domain_strengths: list[str] = field(default_factory=list)
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "domain_strengths": self.domain_strengths,
            "confidence": round(self.confidence, 3),
            "evidence_count": len(self.evidence),
        }


@dataclass
class RoleScore:
    """Scored assignment for an agent-role pair."""

    agent_id: str
    role: RoleType
    domain_match: float = 0.0  # 0-1: how well domains match task
    historical_success: float = 0.5  # 0-1: past success in this role
    confidence_alignment: float = 0.5  # 0-1: calibration quality
    peer_score: float = 0.5  # 0-1: other agent's assessment
    total_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "domain_match": round(self.domain_match, 3),
            "historical_success": round(self.historical_success, 3),
            "total_score": round(self.total_score, 3),
        }


@dataclass
class RoleAssignmentResult:
    """Final role assignment from Meta-Debate."""

    assignments: dict[str, RoleType]  # agent_id -> role
    scores: list[RoleScore] = field(default_factory=list)
    method: str = "meta_debate"  # meta_debate | fallback | history
    confidence: float = 0.5
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": {k: v.value for k, v in self.assignments.items()},
            "method": self.method,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
        }


@dataclass
class AssignerStats:
    """Aggregate statistics."""

    total_assignments: int = 0
    meta_debate_count: int = 0
    fallback_count: int = 0
    lead_counts: dict[str, int] = field(default_factory=dict)
    avg_confidence: float = 0.0
    outcomes: list[tuple[str, bool]] = field(default_factory=list)  # (agent_as_lead, success)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_assignments": self.total_assignments,
            "meta_debate_count": self.meta_debate_count,
            "fallback_count": self.fallback_count,
            "lead_counts": dict(self.lead_counts),
            "avg_confidence": round(self.avg_confidence, 3),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Scoring weights
W_DOMAIN: float = 0.35  # Domain match weight
W_HISTORY: float = 0.30  # Historical success weight
W_CONFIDENCE: float = 0.15  # Confidence calibration weight
W_PEER: float = 0.20  # Peer assessment weight

# Domain capability profiles (default priors based on model strengths)
# V12.4 Multi-provider: Extended from 2 (claude/gemini) to all 7 providers
DEFAULT_DOMAIN_PROFILES: dict[str, dict[str, float]] = {
    "claude": {
        "coding": 0.85,
        "analysis": 0.80,
        "security": 0.85,
        "architecture": 0.80,
        "writing": 0.90,
        "research": 0.75,
        "debugging": 0.80,
        "review": 0.85,
    },
    "gemini": {
        "coding": 0.80,
        "analysis": 0.85,
        "security": 0.75,
        "architecture": 0.75,
        "writing": 0.80,
        "research": 0.90,
        "debugging": 0.75,
        "review": 0.80,
    },
    "openai": {
        "coding": 0.82,
        "analysis": 0.82,
        "security": 0.78,
        "architecture": 0.80,
        "writing": 0.85,
        "research": 0.80,
        "debugging": 0.78,
        "review": 0.82,
    },
    "deepseek": {
        "coding": 0.88,
        "analysis": 0.78,
        "security": 0.70,
        "architecture": 0.75,
        "writing": 0.70,
        "research": 0.65,
        "debugging": 0.82,
        "review": 0.75,
    },
    "kimi": {
        "coding": 0.78,
        "analysis": 0.80,
        "security": 0.68,
        "architecture": 0.72,
        "writing": 0.78,
        "research": 0.82,
        "debugging": 0.70,
        "review": 0.75,
    },
    "minimax": {
        "coding": 0.75,
        "analysis": 0.72,
        "security": 0.62,
        "architecture": 0.68,
        "writing": 0.75,
        "research": 0.72,
        "debugging": 0.65,
        "review": 0.70,
    },
    "ollama": {
        "coding": 0.65,
        "analysis": 0.60,
        "security": 0.50,
        "architecture": 0.55,
        "writing": 0.62,
        "research": 0.50,
        "debugging": 0.60,
        "review": 0.58,
    },
}

# Minimum score difference to justify non-equal assignment
MIN_SCORE_DIFF: float = 0.10

# History window: number of recent outcomes to consider
HISTORY_WINDOW: int = 20


# ---------------------------------------------------------------------------
# Core: DynamicRoleAssigner
# ---------------------------------------------------------------------------


class DynamicRoleAssigner:
    """
    Meta-Debate role assigner.

    Scores agent capability proposals against task requirements
    to determine optimal role assignments for collaboration.

    Usage:
        assigner = DynamicRoleAssigner()
        result = assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["claude", "gemini"],
            proposals={"claude": proposal_c, "gemini": proposal_g},
        )
    """

    def __init__(
        self,
        domain_profiles: dict[str, dict[str, float]] | None = None,
        history_window: int = HISTORY_WINDOW,
    ) -> None:
        self._profiles = domain_profiles or dict(DEFAULT_DOMAIN_PROFILES)
        self._history_window = history_window
        self._lock = threading.Lock()
        self._stats = AssignerStats()
        self._outcome_history: list[tuple[str, str, bool]] = []  # (task_type, lead_agent, success)

    # -- public API --

    def assign_roles(
        self,
        task_domains: list[str],
        agent_ids: list[str],
        proposals: dict[str, CapabilityProposal] | None = None,
        task_complexity: str = "moderate",
    ) -> RoleAssignmentResult:
        """
        Assign roles to agents via Meta-Debate scoring.

        Args:
            task_domains: Domain keywords for the task (e.g., ["coding", "security"]).
            agent_ids: List of agent IDs to assign roles.
            proposals: Optional capability proposals from each agent.
            task_complexity: TRIVIAL/SIMPLE/MODERATE/COMPLEX/EXPERT.

        Returns:
            RoleAssignmentResult with scored assignments.
        """
        if len(agent_ids) < 2:
            # Single agent -> specialist
            assignments = {agent_ids[0]: RoleType.SPECIALIST} if agent_ids else {}
            return RoleAssignmentResult(
                assignments=assignments,
                method="single_agent",
                confidence=1.0,
                reasoning="Single agent, no role negotiation needed.",
            )

        # Score each agent for lead and support roles
        all_scores: list[RoleScore] = []

        for agent_id in agent_ids:
            proposal = proposals.get(agent_id) if proposals else None

            for role in [RoleType.LEAD, RoleType.SUPPORT]:
                score = self._score_agent_role(
                    agent_id=agent_id,
                    role=role,
                    task_domains=task_domains,
                    proposal=proposal,
                    other_agents=[a for a in agent_ids if a != agent_id],
                )
                all_scores.append(score)

        # Select optimal assignment
        result = self._select_assignment(agent_ids, all_scores, task_complexity)

        # Update stats
        with self._lock:
            self._stats.total_assignments += 1
            if result.method == "meta_debate":
                self._stats.meta_debate_count += 1
            else:
                self._stats.fallback_count += 1

            for agent_id, role in result.assignments.items():
                if role == RoleType.LEAD:
                    self._stats.lead_counts[agent_id] = self._stats.lead_counts.get(agent_id, 0) + 1

            n = self._stats.total_assignments
            self._stats.avg_confidence = (self._stats.avg_confidence * (n - 1) + result.confidence) / n

        logger.debug(
            "DynamicRoleAssigner: %s (confidence=%.2f, method=%s)",
            {k: v.value for k, v in result.assignments.items()},
            result.confidence,
            result.method,
        )

        return result

    def record_outcome(
        self,
        task_type: str,
        lead_agent: str,
        success: bool,
    ) -> None:
        """Record the outcome of a role assignment for future learning."""
        with self._lock:
            self._outcome_history.append((task_type, lead_agent, success))
            if len(self._outcome_history) > self._history_window * 2:
                self._outcome_history = self._outcome_history[-self._history_window :]
            self._stats.outcomes.append((lead_agent, success))

    def get_stats(self) -> AssignerStats:
        """Return assignment statistics."""
        with self._lock:
            return AssignerStats(
                total_assignments=self._stats.total_assignments,
                meta_debate_count=self._stats.meta_debate_count,
                fallback_count=self._stats.fallback_count,
                lead_counts=dict(self._stats.lead_counts),
                avg_confidence=self._stats.avg_confidence,
            )

    def reset(self) -> None:
        """Reset statistics and history."""
        with self._lock:
            self._stats = AssignerStats()
            self._outcome_history.clear()

    # -- private scoring --

    def _score_agent_role(
        self,
        agent_id: str,
        role: RoleType,
        task_domains: list[str],
        proposal: CapabilityProposal | None,
        other_agents: list[str],
    ) -> RoleScore:
        """Score an agent for a specific role."""
        score = RoleScore(agent_id=agent_id, role=role)

        # 1. Domain match
        profile = self._profiles.get(agent_id, {})
        if task_domains and profile:
            domain_scores = [profile.get(d.lower(), 0.5) for d in task_domains]
            score.domain_match = sum(domain_scores) / len(domain_scores)
        else:
            score.domain_match = 0.5

        # Boost from proposal evidence
        if proposal and proposal.domain_strengths:
            proposal_match = sum(
                1 for d in proposal.domain_strengths if d.lower() in {td.lower() for td in task_domains}
            ) / max(len(task_domains), 1)
            score.domain_match = (score.domain_match + proposal_match) / 2

        # 2. Historical success
        score.historical_success = self._get_historical_success(agent_id, role)

        # 3. Confidence alignment
        if proposal:
            # Penalize extreme confidence (overconfident or underconfident)
            score.confidence_alignment = 1.0 - abs(proposal.confidence - 0.7)
        else:
            score.confidence_alignment = 0.5

        # 4. Peer score (based on complementarity with other agents)
        score.peer_score = self._compute_peer_score(agent_id, role, other_agents, task_domains)

        # Weighted total
        score.total_score = (
            W_DOMAIN * score.domain_match
            + W_HISTORY * score.historical_success
            + W_CONFIDENCE * score.confidence_alignment
            + W_PEER * score.peer_score
        )

        return score

    def _get_historical_success(self, agent_id: str, role: RoleType) -> float:
        """Get historical success rate for this agent in this role."""
        with self._lock:
            relevant = [
                success
                for _, lead, success in self._outcome_history[-self._history_window :]
                if (role == RoleType.LEAD and lead == agent_id) or (role == RoleType.SUPPORT and lead != agent_id)
            ]

        if not relevant:
            return 0.5  # Prior

        return sum(relevant) / len(relevant)

    def _compute_peer_score(
        self,
        agent_id: str,
        role: RoleType,
        other_agents: list[str],
        task_domains: list[str],
    ) -> float:
        """
        Compute complementarity: if this agent takes `role`, how well
        do the other agents complement the remaining roles?
        """
        if not other_agents:
            return 0.5

        # If agent is lead, check if others are good supports (and vice versa)

        total_complement = 0.0
        for other in other_agents:
            other_profile = self._profiles.get(other, {})
            if task_domains and other_profile:
                avg_fit = sum(other_profile.get(d.lower(), 0.5) for d in task_domains) / len(task_domains)
            else:
                avg_fit = 0.5
            total_complement += avg_fit

        return total_complement / len(other_agents)

    def _select_assignment(
        self,
        agent_ids: list[str],
        scores: list[RoleScore],
        task_complexity: str,
    ) -> RoleAssignmentResult:
        """Select the optimal assignment from scored options."""
        # Find best lead score per agent
        lead_scores: dict[str, float] = {}
        for s in scores:
            if s.role == RoleType.LEAD:
                lead_scores[s.agent_id] = s.total_score

        if not lead_scores:
            # Fallback: equal roles
            return RoleAssignmentResult(
                assignments={a: RoleType.EQUAL for a in agent_ids},
                scores=scores,
                method="fallback",
                confidence=0.3,
                reasoning="No lead scores computed, using equal roles.",
            )

        # Sort agents by lead score
        sorted_agents = sorted(lead_scores.items(), key=lambda x: x[1], reverse=True)
        best_lead, best_score = sorted_agents[0]
        second_best_score = sorted_agents[1][1] if len(sorted_agents) > 1 else 0.0

        score_diff = best_score - second_best_score

        # For trivial/simple tasks or near-equal scores, use equal mode
        if task_complexity.lower() in ("trivial", "simple") or score_diff < MIN_SCORE_DIFF:
            return RoleAssignmentResult(
                assignments={a: RoleType.EQUAL for a in agent_ids},
                scores=scores,
                method="meta_debate",
                confidence=0.5 + score_diff,
                reasoning=(
                    f"Score difference too small ({score_diff:.3f} < {MIN_SCORE_DIFF}) "
                    f"or task too simple — using equal roles."
                ),
            )

        # Assign lead to best scorer, support to others
        assignments: dict[str, RoleType] = {}
        for agent_id in agent_ids:
            if agent_id == best_lead:
                assignments[agent_id] = RoleType.LEAD
            else:
                assignments[agent_id] = RoleType.SUPPORT

        return RoleAssignmentResult(
            assignments=assignments,
            scores=scores,
            method="meta_debate",
            confidence=min(0.95, 0.5 + score_diff * 2),
            reasoning=(
                f"{best_lead} scored highest for lead ({best_score:.3f} vs "
                f"{second_best_score:.3f}, diff={score_diff:.3f})."
            ),
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: DynamicRoleAssigner | None = None
_instance_lock = threading.Lock()


def get_dynamic_role_assigner() -> DynamicRoleAssigner:
    """Get or create the global DynamicRoleAssigner singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DynamicRoleAssigner()
    return _instance


def reset_dynamic_role_assigner() -> None:
    """Reset the global DynamicRoleAssigner singleton."""
    global _instance
    with _instance_lock:
        _instance = None
