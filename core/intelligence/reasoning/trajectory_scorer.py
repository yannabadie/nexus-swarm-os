"""
NEXUS V12.4 - Trajectory Scorer (arXiv:2509.11035, FREE-MAD)

Evaluates multi-agent debate trajectories to select the best-quality
reasoning path. Instead of multi-round consensus until agreement,
scores the entire debate trajectory using evidence quality, position
evolution, and anti-conformity analysis.

Based on: "FREE-MAD: Consensus-Free Multi-Agent Debate" (arXiv:2509.11035)

Key insight: Evaluating the trajectory of reasoning (not just the final
answer) produces better decisions. Anti-conformity prevents agents from
being swayed by majority-but-wrong positions.

This module:
1. Scores individual agent trajectories through a debate
2. Detects conformity pressure (social influence without evidence)
3. Computes trajectory quality from evidence, coherence, independence
4. Selects best-trajectory agent's position as the debate winner

Usage:
    scorer = get_trajectory_scorer()

    result = scorer.score_debate(
        debate_history=[...],  # List of DebateArgument-like dicts
        agents=["claude", "gemini"],
    )
    # result.best_agent, result.trajectory_scores, result.conformity_penalty
"""

import logging
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class AgentTrajectory:
    """Trajectory analysis for a single agent through a debate."""

    agent_id: str
    total_turns: int
    evidence_score: float  # Quality of evidence provided (0-1)
    coherence_score: float  # Consistency of reasoning (0-1)
    independence_score: float  # Resistance to conformity pressure (0-1)
    depth_score: float  # Depth of analysis (0-1)
    trajectory_score: float  # Weighted composite (0-1)
    position_changes: int  # Number of position changes
    concessions_made: int
    evidence_items: int  # Total evidence items across turns


@dataclass
class ConformityAnalysis:
    """Analysis of conformity pressure in the debate."""

    conformity_detected: bool
    conformity_agent: str  # Agent that conformed
    conformity_turn: int  # Turn where conformity occurred
    evidence_at_flip: int  # Evidence provided when position changed
    penalty_applied: float  # Score reduction applied


@dataclass
class TrajectoryResult:
    """Result of trajectory-based debate evaluation."""

    best_agent: str  # Agent with highest trajectory score
    trajectory_scores: dict[str, float]  # agent_id -> score
    agent_trajectories: dict[str, AgentTrajectory]
    conformity_analysis: list[ConformityAnalysis]
    debate_quality: float  # Overall debate quality (0-1)
    recommendation: str  # "accept_best", "re-debate", "escalate"

    @property
    def winning_margin(self) -> float:
        """Margin between best and second-best trajectory."""
        scores = sorted(self.trajectory_scores.values(), reverse=True)
        if len(scores) < 2:
            return 1.0
        return scores[0] - scores[1]


@dataclass
class ScorerStats:
    """Statistics for the trajectory scorer."""

    total_debates_scored: int
    avg_debate_quality: float
    conformity_detections: int
    agent_win_rates: dict[str, float]


# =============================================================================
# Evidence Quality Heuristics
# =============================================================================

# Indicators of strong evidence
STRONG_EVIDENCE_PATTERNS = [
    r"according to",
    r"based on",
    r"as shown in",
    r"the code shows",
    r"line \d+",
    r"file.*\.py",
    r"specifically",
    r"for example",
    r"the error message",
    r"the stack trace",
    r"documentation states",
]

# Indicators of weak/no evidence
WEAK_EVIDENCE_PATTERNS = [
    r"i think",
    r"i believe",
    r"probably",
    r"might be",
    r"seems like",
    r"i feel",
    r"in my opinion",
    r"usually",
    r"generally",
]

_STRONG_RE = [re.compile(p, re.IGNORECASE) for p in STRONG_EVIDENCE_PATTERNS]
_WEAK_RE = [re.compile(p, re.IGNORECASE) for p in WEAK_EVIDENCE_PATTERNS]


# =============================================================================
# Trajectory Scorer
# =============================================================================


class TrajectoryScorer:
    """
    Evaluates debate trajectories to select the best reasoning path.

    Scores agents on evidence quality, reasoning coherence, independence
    from conformity pressure, and analytical depth. Applies anti-conformity
    penalties when agents change positions without sufficient evidence.

    No LLM calls — uses pattern matching and trajectory analysis.
    """

    # Scoring weights
    EVIDENCE_WEIGHT = 0.30
    COHERENCE_WEIGHT = 0.25
    INDEPENDENCE_WEIGHT = 0.25
    DEPTH_WEIGHT = 0.20

    # Anti-conformity parameters
    MIN_EVIDENCE_FOR_FLIP = 2  # Minimum evidence items to justify position change
    CONFORMITY_PENALTY = 0.15  # Score reduction for conformity without evidence
    MIN_DEBATE_QUALITY = 0.4  # Below this -> recommend re-debate

    def __init__(self):
        self._total_scored = 0
        self._quality_sum = 0.0
        self._conformity_count = 0
        self._agent_wins: Counter = Counter()
        self._agent_debates: Counter = Counter()
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def score_debate(
        self,
        debate_history: list[dict],
        agents: list[str] | None = None,
    ) -> TrajectoryResult:
        """
        Score a debate trajectory and select the best agent position.

        Args:
            debate_history: List of debate turn dicts with keys:
                - agent_id: str
                - position: str ("SUPPORT", "OPPOSE", "CONCEDE")
                - argument: str
                - evidence: List[str]
                - concession: Optional[str]
                - turn_number: int
            agents: Optional list of agent IDs (inferred from history if not given)

        Returns:
            TrajectoryResult with scores, conformity analysis, and recommendation
        """
        if not debate_history:
            return TrajectoryResult(
                best_agent="",
                trajectory_scores={},
                agent_trajectories={},
                conformity_analysis=[],
                debate_quality=0.0,
                recommendation="escalate",
            )

        # Infer agents from history
        if not agents:
            agents = list({t.get("agent_id", "unknown") for t in debate_history})

        # Build per-agent trajectories
        agent_turns: dict[str, list[dict]] = defaultdict(list)
        for turn in debate_history:
            aid = turn.get("agent_id", "unknown")
            agent_turns[aid].append(turn)

        # Score each agent's trajectory
        trajectories: dict[str, AgentTrajectory] = {}
        for aid in agents:
            turns = agent_turns.get(aid, [])
            trajectories[aid] = self._score_agent_trajectory(aid, turns)

        # Detect conformity
        conformity_analysis = self._detect_conformity(debate_history, agents)

        # Apply conformity penalties
        for ca in conformity_analysis:
            if ca.conformity_detected and ca.conformity_agent in trajectories:
                t = trajectories[ca.conformity_agent]
                # Rebuild with penalty
                penalized_score = max(0.0, t.trajectory_score - ca.penalty_applied)
                trajectories[ca.conformity_agent] = AgentTrajectory(
                    agent_id=t.agent_id,
                    total_turns=t.total_turns,
                    evidence_score=t.evidence_score,
                    coherence_score=t.coherence_score,
                    independence_score=max(0.0, t.independence_score - ca.penalty_applied),
                    depth_score=t.depth_score,
                    trajectory_score=penalized_score,
                    position_changes=t.position_changes,
                    concessions_made=t.concessions_made,
                    evidence_items=t.evidence_items,
                )

        # Compute scores and find best
        scores = {aid: t.trajectory_score for aid, t in trajectories.items()}
        best_agent = max(scores, key=scores.get) if scores else ""

        # Overall debate quality
        avg_score = sum(scores.values()) / max(len(scores), 1)
        debate_quality = min(1.0, avg_score * 1.2)  # Slight boost

        # Recommendation
        if debate_quality < self.MIN_DEBATE_QUALITY:
            recommendation = "re-debate"
        elif not conformity_analysis or not any(c.conformity_detected for c in conformity_analysis):
            recommendation = "accept_best"
        else:
            recommendation = "accept_best"  # Still accept but with conformity noted

        result = TrajectoryResult(
            best_agent=best_agent,
            trajectory_scores=scores,
            agent_trajectories=trajectories,
            conformity_analysis=conformity_analysis,
            debate_quality=debate_quality,
            recommendation=recommendation,
        )

        # Update stats
        with self._lock:
            self._total_scored += 1
            self._quality_sum += debate_quality
            self._conformity_count += sum(1 for c in conformity_analysis if c.conformity_detected)
            if best_agent:
                self._agent_wins[best_agent] += 1
            for aid in agents:
                self._agent_debates[aid] += 1

        return result

    def get_stats(self) -> ScorerStats:
        """Get trajectory scorer statistics."""
        with self._lock:
            avg_quality = self._quality_sum / max(self._total_scored, 1)
            win_rates = {aid: self._agent_wins[aid] / max(self._agent_debates[aid], 1) for aid in self._agent_debates}

        return ScorerStats(
            total_debates_scored=self._total_scored,
            avg_debate_quality=avg_quality,
            conformity_detections=self._conformity_count,
            agent_win_rates=win_rates,
        )

    # -------------------------------------------------------------------------
    # Internal: Agent Trajectory Scoring
    # -------------------------------------------------------------------------

    def _score_agent_trajectory(self, agent_id: str, turns: list[dict]) -> AgentTrajectory:
        """Score a single agent's trajectory through the debate."""
        if not turns:
            return AgentTrajectory(
                agent_id=agent_id,
                total_turns=0,
                evidence_score=0.0,
                coherence_score=0.0,
                independence_score=1.0,
                depth_score=0.0,
                trajectory_score=0.0,
                position_changes=0,
                concessions_made=0,
                evidence_items=0,
            )

        evidence_score = self._score_evidence(turns)
        coherence_score = self._score_coherence(turns)
        independence_score = self._score_independence(turns)
        depth_score = self._score_depth(turns)

        trajectory_score = (
            self.EVIDENCE_WEIGHT * evidence_score
            + self.COHERENCE_WEIGHT * coherence_score
            + self.INDEPENDENCE_WEIGHT * independence_score
            + self.DEPTH_WEIGHT * depth_score
        )

        position_changes = self._count_position_changes(turns)
        concessions = sum(1 for t in turns if t.get("concession"))
        total_evidence = sum(len(t.get("evidence", [])) for t in turns)

        return AgentTrajectory(
            agent_id=agent_id,
            total_turns=len(turns),
            evidence_score=evidence_score,
            coherence_score=coherence_score,
            independence_score=independence_score,
            depth_score=depth_score,
            trajectory_score=trajectory_score,
            position_changes=position_changes,
            concessions_made=concessions,
            evidence_items=total_evidence,
        )

    def _score_evidence(self, turns: list[dict]) -> float:
        """Score the quality and quantity of evidence provided."""
        if not turns:
            return 0.0

        total_evidence_items = 0
        strong_signals = 0
        weak_signals = 0

        for turn in turns:
            evidence = turn.get("evidence", [])
            total_evidence_items += len(evidence)

            argument = turn.get("argument", "")
            strong_signals += sum(1 for p in _STRONG_RE if p.search(argument))
            weak_signals += sum(1 for p in _WEAK_RE if p.search(argument))

            # Evidence items themselves
            for ev in evidence:
                strong_signals += sum(1 for p in _STRONG_RE if p.search(ev))

        # Normalize
        evidence_density = min(1.0, total_evidence_items / max(len(turns) * 2, 1))
        signal_ratio = strong_signals / max(strong_signals + weak_signals, 1)

        return evidence_density * 0.6 + signal_ratio * 0.4

    def _score_coherence(self, turns: list[dict]) -> float:
        """Score reasoning consistency across turns."""
        if len(turns) < 2:
            return 1.0  # Single turn is trivially coherent

        # Check for position consistency
        positions = [t.get("position", "UNKNOWN") for t in turns]
        len(set(positions))

        # More position changes = lower coherence
        changes = self._count_position_changes(turns)
        stability = 1.0 - (changes / max(len(turns) - 1, 1))

        # Check for contradictions (opposing then supporting without evidence)
        contradiction_penalty = 0.0
        for i in range(1, len(turns)):
            prev_pos = turns[i - 1].get("position", "")
            curr_pos = turns[i].get("position", "")
            curr_evidence = turns[i].get("evidence", [])

            if (
                prev_pos == "OPPOSE"
                and curr_pos in ("SUPPORT", "CONCEDE")
                and len(curr_evidence) < self.MIN_EVIDENCE_FOR_FLIP
            ):
                contradiction_penalty += 0.2

        return max(0.0, stability - contradiction_penalty)

    def _score_independence(self, turns: list[dict]) -> float:
        """Score resistance to conformity pressure."""
        if not turns:
            return 1.0

        # High independence = maintaining position with evidence
        # Low independence = changing position without evidence
        flip_without_evidence = 0
        total_flips = 0

        for i in range(1, len(turns)):
            prev_pos = turns[i - 1].get("position", "")
            curr_pos = turns[i].get("position", "")
            if prev_pos != curr_pos:
                total_flips += 1
                curr_evidence = turns[i].get("evidence", [])
                if len(curr_evidence) < self.MIN_EVIDENCE_FOR_FLIP:
                    flip_without_evidence += 1

        if total_flips == 0:
            return 1.0  # Never changed position = fully independent

        return 1.0 - (flip_without_evidence / max(total_flips, 1))

    def _score_depth(self, turns: list[dict]) -> float:
        """Score analytical depth from argument length and structure."""
        if not turns:
            return 0.0

        total_length = 0
        has_modification = 0

        for turn in turns:
            arg = turn.get("argument", "")
            total_length += len(arg)
            if turn.get("proposed_modification"):
                has_modification += 1

        avg_length = total_length / len(turns)

        # Longer, more detailed arguments indicate deeper analysis
        length_score = min(1.0, avg_length / 500)  # 500 chars = full score

        # Proposing modifications shows constructive depth
        mod_score = min(1.0, has_modification / max(len(turns), 1) * 2)

        return length_score * 0.7 + mod_score * 0.3

    # -------------------------------------------------------------------------
    # Internal: Conformity Detection
    # -------------------------------------------------------------------------

    def _detect_conformity(
        self,
        debate_history: list[dict],
        agents: list[str],
    ) -> list[ConformityAnalysis]:
        """Detect conformity pressure in the debate."""
        results = []

        agent_turns: dict[str, list[dict]] = defaultdict(list)
        for turn in debate_history:
            agent_turns[turn.get("agent_id", "unknown")].append(turn)

        for agent_id in agents:
            turns = agent_turns.get(agent_id, [])
            for i in range(1, len(turns)):
                prev = turns[i - 1]
                curr = turns[i]

                prev_pos = prev.get("position", "")
                curr_pos = curr.get("position", "")
                evidence = curr.get("evidence", [])
                turn_num = curr.get("turn_number", i)

                # Conformity: changed from OPPOSE to SUPPORT/CONCEDE
                # with insufficient evidence
                if (
                    prev_pos == "OPPOSE"
                    and curr_pos in ("SUPPORT", "CONCEDE")
                    and len(evidence) < self.MIN_EVIDENCE_FOR_FLIP
                ):
                    results.append(
                        ConformityAnalysis(
                            conformity_detected=True,
                            conformity_agent=agent_id,
                            conformity_turn=turn_num,
                            evidence_at_flip=len(evidence),
                            penalty_applied=self.CONFORMITY_PENALTY,
                        )
                    )

        return results

    def _count_position_changes(self, turns: list[dict]) -> int:
        """Count the number of position changes in a trajectory."""
        changes = 0
        for i in range(1, len(turns)):
            if turns[i].get("position") != turns[i - 1].get("position"):
                changes += 1
        return changes


# =============================================================================
# Singleton
# =============================================================================

_instance: TrajectoryScorer | None = None
_instance_lock = threading.Lock()


def get_trajectory_scorer() -> TrajectoryScorer:
    """Get or create the singleton TrajectoryScorer instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TrajectoryScorer()
    return _instance


def reset_trajectory_scorer() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
