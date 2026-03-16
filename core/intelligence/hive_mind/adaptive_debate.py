"""
NEXUS V8.0 - Adaptive Debate Configuration

Dynamically adjusts debate parameters based on:
- Task complexity
- Historical error rates
- Disagreement severity
- Agent performance metrics

User Decision: Debate turns are ADAPTIVE (3-10 turns based on context)

Usage:
    config = AdaptiveDebateConfig()

    # Get debate parameters for a task
    params = config.get_debate_params(
        complexity="COMPLEX",
        initial_disagreement=0.6,
        error_history=[True, True, False]  # 2 errors in last 3 tasks
    )

    print(params.max_turns)  # e.g., 8
    print(params.consensus_threshold)  # e.g., 0.75
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """Task complexity levels."""

    TRIVIAL = "trivial"
    MODERATE = "moderate"
    COMPLEX = "complex"
    EXPERT = "expert"


@dataclass
class DebateParams:
    """Parameters for a debate session."""

    min_turns: int = 2
    max_turns: int = 6
    consensus_threshold: float = 0.8
    early_exit_threshold: float = 0.95  # Exit early if consensus exceeds this
    timeout_per_turn: int = 30  # seconds
    allow_concessions: bool = True
    require_evidence: bool = True
    force_vote_after: int = 10  # Force vote if no consensus after N turns


@dataclass
class AgentDebateMetrics:
    """Metrics for an agent's debate performance."""

    agent_id: str
    total_debates: int = 0
    arguments_made: int = 0
    concessions_made: int = 0
    positions_defended: int = 0
    positions_changed: int = 0
    average_satisfaction: float = 0.5
    win_rate: float = 0.5  # How often their position was adopted

    @property
    def flexibility_score(self) -> float:
        """How willing to change position (0-1)."""
        if self.arguments_made == 0:
            return 0.5
        return self.concessions_made / self.arguments_made

    @property
    def conviction_score(self) -> float:
        """How strongly they defend positions (0-1)."""
        if self.positions_defended + self.positions_changed == 0:
            return 0.5
        return self.positions_defended / (self.positions_defended + self.positions_changed)


class AdaptiveDebateConfig:
    """
    Manages adaptive debate configuration.

    Adjusts debate parameters dynamically based on multiple factors:
    - Task complexity
    - Historical error rates
    - Agent disagreement level
    - Previous debate outcomes
    """

    # Base turn ranges by complexity
    COMPLEXITY_TURNS = {
        TaskComplexity.TRIVIAL: (2, 3),
        TaskComplexity.MODERATE: (3, 6),
        TaskComplexity.COMPLEX: (5, 8),
        TaskComplexity.EXPERT: (6, 10),
    }

    # Consensus thresholds by complexity
    COMPLEXITY_CONSENSUS = {
        TaskComplexity.TRIVIAL: 0.9,  # High threshold = quick agreement needed
        TaskComplexity.MODERATE: 0.8,
        TaskComplexity.COMPLEX: 0.75,
        TaskComplexity.EXPERT: 0.7,  # Lower threshold = harder to agree
    }

    def __init__(self):
        """Initialize adaptive debate config."""
        self._debate_history: list[dict] = []
        self._agent_metrics: dict[str, AgentDebateMetrics] = {}
        self._error_history: list[bool] = []  # True = error occurred

    def get_debate_params(
        self,
        complexity: TaskComplexity,
        initial_disagreement: float = 0.5,
        error_history: list[bool] = None,
        domain_tags: list[str] = None,
    ) -> DebateParams:
        """
        Get debate parameters adapted to context.

        Args:
            complexity: Task complexity level
            initial_disagreement: Initial disagreement score (0-1)
            error_history: Recent error history
            domain_tags: Task domain tags

        Returns:
            Adapted DebateParams
        """
        # Base parameters from complexity
        min_turns, max_turns = self.COMPLEXITY_TURNS[complexity]
        consensus_threshold = self.COMPLEXITY_CONSENSUS[complexity]

        # Adjust for initial disagreement
        # Higher disagreement = more turns needed
        if initial_disagreement > 0.7:
            max_turns = min(max_turns + 2, 10)
            consensus_threshold = max(consensus_threshold - 0.05, 0.65)
        elif initial_disagreement < 0.3:
            min_turns = max(min_turns - 1, 1)
            consensus_threshold = min(consensus_threshold + 0.05, 0.95)

        # Adjust for error history
        error_history = error_history or self._error_history[-5:]
        if error_history:
            error_rate = sum(error_history) / len(error_history)
            if error_rate > 0.5:
                # High error rate = need more careful debate
                max_turns = min(max_turns + 1, 10)
                consensus_threshold = max(consensus_threshold - 0.05, 0.65)
                logger.info(f"Increased debate turns due to error rate: {error_rate:.0%}")

        # Adjust for domain complexity
        if domain_tags:
            complex_domains = {"security", "architecture", "concurrency", "distributed"}
            if any(tag in complex_domains for tag in domain_tags):
                min_turns = max(min_turns + 1, 3)
                consensus_threshold = max(consensus_threshold - 0.05, 0.65)

        params = DebateParams(
            min_turns=min_turns,
            max_turns=max_turns,
            consensus_threshold=consensus_threshold,
            early_exit_threshold=0.95,
            timeout_per_turn=30 if complexity != TaskComplexity.EXPERT else 45,
            allow_concessions=True,
            require_evidence=complexity in (TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
            force_vote_after=max_turns + 2,
        )

        logger.info(
            f"Debate params: {min_turns}-{max_turns} turns, "
            f"consensus={consensus_threshold:.0%} "
            f"(complexity={complexity.value}, disagreement={initial_disagreement:.0%})"
        )

        return params

    def record_debate_outcome(
        self,
        task_id: str,
        complexity: TaskComplexity,
        turns_used: int,
        final_consensus: float,
        was_forced_vote: bool,
        gemini_satisfaction: float,
        claude_satisfaction: float,
        task_success: bool,
    ):
        """
        Record a debate outcome for learning.

        Args:
            task_id: Task identifier
            complexity: Task complexity
            turns_used: Number of turns used
            final_consensus: Final consensus score achieved
            was_forced_vote: Whether vote was forced
            gemini_satisfaction: Gemini's satisfaction (0-1)
            claude_satisfaction: Claude's satisfaction (0-1)
            task_success: Whether task succeeded
        """
        outcome = {
            "task_id": task_id,
            "complexity": complexity.value,
            "turns_used": turns_used,
            "final_consensus": final_consensus,
            "was_forced_vote": was_forced_vote,
            "gemini_satisfaction": gemini_satisfaction,
            "claude_satisfaction": claude_satisfaction,
            "task_success": task_success,
            "timestamp": datetime.now().isoformat(),
        }
        self._debate_history.append(outcome)
        self._error_history.append(not task_success)

        # Keep only last 20 entries
        if len(self._debate_history) > 20:
            self._debate_history = self._debate_history[-20:]
        if len(self._error_history) > 10:
            self._error_history = self._error_history[-10:]

        logger.debug(f"Recorded debate outcome for {task_id}")

    def record_agent_argument(
        self,
        agent_id: str,
        made_concession: bool = False,
        defended_position: bool = True,
        changed_position: bool = False,
    ):
        """
        Record an agent's debate behavior.

        Args:
            agent_id: Agent identifier
            made_concession: Whether they conceded a point
            defended_position: Whether they defended their position
            changed_position: Whether they changed their position
        """
        if agent_id not in self._agent_metrics:
            self._agent_metrics[agent_id] = AgentDebateMetrics(agent_id=agent_id)

        metrics = self._agent_metrics[agent_id]
        metrics.arguments_made += 1
        if made_concession:
            metrics.concessions_made += 1
        if defended_position:
            metrics.positions_defended += 1
        if changed_position:
            metrics.positions_changed += 1

    def update_agent_satisfaction(self, agent_id: str, satisfaction: float, won_debate: bool):
        """
        Update agent's satisfaction and win rate.

        Args:
            agent_id: Agent identifier
            satisfaction: Satisfaction score (0-1)
            won_debate: Whether their position was adopted
        """
        if agent_id not in self._agent_metrics:
            self._agent_metrics[agent_id] = AgentDebateMetrics(agent_id=agent_id)

        metrics = self._agent_metrics[agent_id]
        metrics.total_debates += 1

        # Rolling average for satisfaction
        metrics.average_satisfaction = (
            metrics.average_satisfaction * (metrics.total_debates - 1) + satisfaction
        ) / metrics.total_debates

        # Rolling average for win rate
        metrics.win_rate = (
            metrics.win_rate * (metrics.total_debates - 1) + (1.0 if won_debate else 0.0)
        ) / metrics.total_debates

    def get_optimal_strategy(self, agent_id: str, opponent_id: str, topic: str) -> dict:
        """
        Get optimal debate strategy based on agent metrics.

        Args:
            agent_id: Agent getting advice
            opponent_id: Opponent agent
            topic: Debate topic

        Returns:
            Strategy recommendations
        """
        agent_metrics = self._agent_metrics.get(agent_id)
        opponent_metrics = self._agent_metrics.get(opponent_id)

        strategy = {"approach": "balanced", "concession_willingness": 0.5, "evidence_requirement": "medium", "tips": []}

        if opponent_metrics:
            # Adjust based on opponent's flexibility
            if opponent_metrics.flexibility_score > 0.6:
                strategy["approach"] = "firm"
                strategy["tips"].append("Opponent is flexible - maintain your position firmly")
            elif opponent_metrics.flexibility_score < 0.3:
                strategy["approach"] = "collaborative"
                strategy["concession_willingness"] = 0.7
                strategy["tips"].append("Opponent is rigid - look for common ground")

            # Adjust based on opponent's win rate
            if opponent_metrics.win_rate > 0.7:
                strategy["evidence_requirement"] = "high"
                strategy["tips"].append("Opponent often wins - bring strong evidence")

        # Adjust based on own metrics
        if agent_metrics and agent_metrics.average_satisfaction < 0.4:
            strategy["tips"].append("Your satisfaction has been low - consider new approaches")

        return strategy

    def should_force_vote(self, turns_completed: int, consensus_progress: list[float], params: DebateParams) -> bool:
        """
        Determine if vote should be forced.

        Args:
            turns_completed: Turns completed so far
            consensus_progress: Consensus scores over time
            params: Current debate parameters

        Returns:
            True if vote should be forced
        """
        # Always force after max allowed
        if turns_completed >= params.force_vote_after:
            return True

        # Check if consensus is stalled
        if len(consensus_progress) >= 3:
            recent = consensus_progress[-3:]
            variance = max(recent) - min(recent)
            if variance < 0.05:
                logger.info(f"Consensus stalled at {recent[-1]:.0%} - forcing vote")
                return True

        # Check if consensus is regressing
        if len(consensus_progress) >= 2 and consensus_progress[-1] < consensus_progress[-2] - 0.1:
            logger.info("Consensus regressing - forcing vote")
            return True

        return False

    def calculate_final_decision(
        self,
        gemini_position: str,
        claude_position: str,
        gemini_confidence: float,
        claude_confidence: float,
        gemini_satisfaction: float,
        claude_satisfaction: float,
    ) -> dict:
        """
        Calculate final decision when forced vote is needed.

        Args:
            gemini_position: Gemini's final position
            claude_position: Claude's final position
            gemini_confidence: Gemini's confidence (0-1)
            claude_confidence: Claude's confidence (0-1)
            gemini_satisfaction: Gemini's satisfaction with outcome
            claude_satisfaction: Claude's satisfaction with outcome

        Returns:
            Decision dict with winner and reasoning
        """
        # Weight by confidence and satisfaction
        gemini_score = gemini_confidence * 0.7 + gemini_satisfaction * 0.3
        claude_score = claude_confidence * 0.7 + claude_satisfaction * 0.3

        # Also consider historical win rates
        gemini_metrics = self._agent_metrics.get("gemini")
        claude_metrics = self._agent_metrics.get("claude")

        if gemini_metrics and claude_metrics:
            # Slight boost based on historical success
            gemini_score += gemini_metrics.win_rate * 0.1
            claude_score += claude_metrics.win_rate * 0.1

        if gemini_score > claude_score + 0.1:
            winner = "gemini"
            winning_position = gemini_position
            reason = f"Gemini's position selected (score: {gemini_score:.2f} vs {claude_score:.2f})"
        elif claude_score > gemini_score + 0.1:
            winner = "claude"
            winning_position = claude_position
            reason = f"Claude's position selected (score: {claude_score:.2f} vs {gemini_score:.2f})"
        else:
            # Tie - merge positions
            winner = "merged"
            winning_position = f"MERGED: {gemini_position} + {claude_position}"
            reason = "Positions merged due to similar scores"

        return {
            "winner": winner,
            "position": winning_position,
            "reason": reason,
            "gemini_score": gemini_score,
            "claude_score": claude_score,
            "was_tie": winner == "merged",
        }

    def get_stats(self) -> dict:
        """Get debate statistics."""
        if not self._debate_history:
            return {
                "total_debates": 0,
                "average_turns": 0,
                "average_consensus": 0,
                "forced_vote_rate": 0,
                "success_rate": 0,
            }

        total = len(self._debate_history)
        forced_votes = sum(1 for d in self._debate_history if d["was_forced_vote"])
        successes = sum(1 for d in self._debate_history if d["task_success"])

        return {
            "total_debates": total,
            "average_turns": sum(d["turns_used"] for d in self._debate_history) / total,
            "average_consensus": sum(d["final_consensus"] for d in self._debate_history) / total,
            "forced_vote_rate": forced_votes / total,
            "success_rate": successes / total,
            "agent_metrics": {
                agent_id: {
                    "flexibility": m.flexibility_score,
                    "conviction": m.conviction_score,
                    "win_rate": m.win_rate,
                    "satisfaction": m.average_satisfaction,
                }
                for agent_id, m in self._agent_metrics.items()
            },
        }
