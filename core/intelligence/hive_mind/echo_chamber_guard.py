"""
NEXUS V12.4 - Echo Chamber Guard

Detects and prevents sycophantic convergence in multi-agent debate.
Based on:
- EchoChamberGuard (arxiv:2509.05396): Sycophantic flip detection
- Multi-Agent Sycophancy (arxiv:2511.07784): Independence checkpoints

Three mechanisms:
1. **Flip Detection**: Flags agents that switch from OPPOSE to SUPPORT/CONCEDE
   without providing substantial new evidence (sycophantic capitulation).
2. **Independence Checkpoints**: Every N turns, injects a reminder for agents
   to evaluate their position independently of social pressure.
3. **Devil's Advocate Forcing**: When premature consensus is detected (both
   agents agree before min_turns), forces one agent to argue the counter-position.

Usage:
    guard = EchoChamberGuard()
    action = guard.check_turn(agent_id="gemini", position="CONCEDE",
                              evidence=[], turn_number=2)
    if action.action_type == "FLAG_SYCOPHANCY":
        # Inject counter-pressure prompt
        ...
"""

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class GuardActionType(str, Enum):
    """Actions the guard can recommend."""

    ALLOW = "ALLOW"
    FLAG_SYCOPHANCY = "FLAG_SYCOPHANCY"
    INJECT_INDEPENDENCE = "INJECT_INDEPENDENCE"
    FORCE_DEVIL_ADVOCATE = "FORCE_DEVIL_ADVOCATE"


@dataclass
class GuardAction:
    """Action recommended by the EchoChamberGuard."""

    action_type: GuardActionType
    reason: str
    agent_id: str
    turn_number: int
    prompt_injection: str | None = None  # Extra prompt text to inject


@dataclass
class AgentPositionHistory:
    """Tracks an agent's position changes through debate."""

    agent_id: str
    positions: list[str] = field(default_factory=list)
    evidence_counts: list[int] = field(default_factory=list)
    turns: list[int] = field(default_factory=list)

    def record(self, position: str, evidence_count: int, turn: int) -> None:
        self.positions.append(position)
        self.evidence_counts.append(evidence_count)
        self.turns.append(turn)

    @property
    def last_position(self) -> str | None:
        return self.positions[-1] if self.positions else None

    @property
    def flip_count(self) -> int:
        """Count how many times agent flipped from OPPOSE to agreeing."""
        flips = 0
        for i in range(1, len(self.positions)):
            if self.positions[i - 1] == "OPPOSE" and self.positions[i] in ("SUPPORT", "CONCEDE"):
                flips += 1
        return flips


# Independence checkpoint prompt injected into debate
INDEPENDENCE_PROMPT = (
    "INDEPENDENCE CHECK: Before responding, evaluate your position independently. "
    "Are you agreeing because of genuine reasoning, or because of social pressure? "
    "If your original analysis was sound, defend it with evidence. "
    "Good debate requires genuine disagreement when warranted."
)

# Devil's advocate prompt
DEVIL_ADVOCATE_PROMPT = (
    "DEVIL'S ADVOCATE MODE: The current consensus may be premature. "
    "You must argue AGAINST the emerging consensus, even if you partially agree. "
    "Identify weaknesses, edge cases, or overlooked alternatives. "
    "This ensures the final solution is robust and well-tested."
)

# Minimum evidence items to not be considered sycophantic
MIN_EVIDENCE_FOR_FLIP = 2

# Default interval for independence checkpoints (every N turns)
DEFAULT_CHECKPOINT_INTERVAL = 2

# Minimum turns before consensus is considered valid
DEFAULT_MIN_TURNS_FOR_CONSENSUS = 3


class EchoChamberGuard:
    """
    Monitors debate for sycophantic patterns and enforces intellectual independence.

    Three layers of protection:
    1. Flip detection - flags position changes without evidence
    2. Independence checkpoints - periodic reminders
    3. Devil's advocate - forces counter-arguments on premature consensus
    """

    def __init__(
        self,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
        min_turns_for_consensus: int = DEFAULT_MIN_TURNS_FOR_CONSENSUS,
        min_evidence_for_flip: int = MIN_EVIDENCE_FOR_FLIP,
    ):
        self._checkpoint_interval = checkpoint_interval
        self._min_turns_for_consensus = min_turns_for_consensus
        self._min_evidence_for_flip = min_evidence_for_flip
        self._agents: dict[str, AgentPositionHistory] = {}
        self._actions: list[GuardAction] = []
        self._devil_advocate_forced: bool = False

    def reset(self) -> None:
        """Reset guard state for a new debate."""
        self._agents.clear()
        self._actions.clear()
        self._devil_advocate_forced = False

    def check_turn(
        self,
        agent_id: str,
        position: str,
        evidence: list[str],
        turn_number: int,
    ) -> GuardAction:
        """
        Check a debate turn for sycophantic patterns.

        Args:
            agent_id: The agent making the argument
            position: SUPPORT, OPPOSE, or CONCEDE
            evidence: List of evidence items provided
            turn_number: Current debate turn number

        Returns:
            GuardAction with recommended action
        """
        # Initialize agent history if needed
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentPositionHistory(agent_id=agent_id)

        history = self._agents[agent_id]
        evidence_count = len(evidence) if evidence else 0

        # Check 1: Sycophantic flip detection
        if (
            history.last_position == "OPPOSE"
            and position in ("SUPPORT", "CONCEDE")
            and evidence_count < self._min_evidence_for_flip
        ):
            action = GuardAction(
                action_type=GuardActionType.FLAG_SYCOPHANCY,
                reason=(
                    f"{agent_id} flipped from OPPOSE to {position} "
                    f"with only {evidence_count} evidence items "
                    f"(minimum {self._min_evidence_for_flip} required)"
                ),
                agent_id=agent_id,
                turn_number=turn_number,
                prompt_injection=INDEPENDENCE_PROMPT,
            )
            history.record(position, evidence_count, turn_number)
            self._actions.append(action)
            logger.warning(f"EchoChamberGuard: Sycophantic flip by {agent_id} at turn {turn_number}")
            return action

        # Record the position
        history.record(position, evidence_count, turn_number)

        # Check 2: Premature consensus / devil's advocate (higher priority than checkpoint)
        if (
            not self._devil_advocate_forced
            and turn_number < self._min_turns_for_consensus
            and self._all_agents_agreeing()
            and len(self._agents) >= 2
        ):
            action = GuardAction(
                action_type=GuardActionType.FORCE_DEVIL_ADVOCATE,
                reason=(
                    f"Premature consensus at turn {turn_number} "
                    f"(minimum {self._min_turns_for_consensus} turns required)"
                ),
                agent_id=agent_id,
                turn_number=turn_number,
                prompt_injection=DEVIL_ADVOCATE_PROMPT,
            )
            self._devil_advocate_forced = True
            self._actions.append(action)
            logger.warning(f"EchoChamberGuard: Forcing devil's advocate at turn {turn_number}")
            return action

        # Check 3: Independence checkpoint (every N turns)
        if turn_number > 1 and turn_number % self._checkpoint_interval == 0:
            action = GuardAction(
                action_type=GuardActionType.INJECT_INDEPENDENCE,
                reason=f"Independence checkpoint at turn {turn_number}",
                agent_id=agent_id,
                turn_number=turn_number,
                prompt_injection=INDEPENDENCE_PROMPT,
            )
            self._actions.append(action)
            logger.info(f"EchoChamberGuard: Independence checkpoint for {agent_id} at turn {turn_number}")
            return action

        # Default: allow
        return GuardAction(
            action_type=GuardActionType.ALLOW,
            reason="No sycophantic patterns detected",
            agent_id=agent_id,
            turn_number=turn_number,
        )

    def _all_agents_agreeing(self) -> bool:
        """Check if all tracked agents are currently in agreement."""
        agreeing = {"SUPPORT", "CONCEDE"}
        for history in self._agents.values():
            if history.last_position and history.last_position not in agreeing:
                return False
        return True

    def get_agent_flip_count(self, agent_id: str) -> int:
        """Get the number of sycophantic flips for an agent."""
        if agent_id in self._agents:
            return self._agents[agent_id].flip_count
        return 0

    def get_all_actions(self) -> list[GuardAction]:
        """Get all guard actions taken during this debate."""
        return self._actions.copy()

    def get_sycophancy_score(self) -> float:
        """
        Calculate an overall sycophancy score for the debate.

        Returns:
            0.0 (no sycophancy) to 1.0 (highly sycophantic)
        """
        if not self._actions:
            return 0.0

        sycophancy_actions = sum(1 for a in self._actions if a.action_type == GuardActionType.FLAG_SYCOPHANCY)
        devil_advocate = sum(1 for a in self._actions if a.action_type == GuardActionType.FORCE_DEVIL_ADVOCATE)

        # Weight: sycophancy flags count double
        weighted = sycophancy_actions * 2 + devil_advocate
        # Normalize against total turns tracked
        total_turns = sum(len(h.turns) for h in self._agents.values())
        if total_turns == 0:
            return 0.0

        return min(1.0, weighted / max(total_turns, 1))

    def get_stats(self) -> dict:
        """Get guard statistics."""
        return {
            "agents_tracked": len(self._agents),
            "total_actions": len(self._actions),
            "sycophancy_flags": sum(1 for a in self._actions if a.action_type == GuardActionType.FLAG_SYCOPHANCY),
            "independence_checks": sum(
                1 for a in self._actions if a.action_type == GuardActionType.INJECT_INDEPENDENCE
            ),
            "devil_advocate_forced": self._devil_advocate_forced,
            "sycophancy_score": self.get_sycophancy_score(),
            "agent_flips": {aid: h.flip_count for aid, h in self._agents.items()},
        }


# Module-level singleton
_guard: EchoChamberGuard | None = None
_guard_lock = threading.Lock()


def get_echo_chamber_guard() -> EchoChamberGuard:
    """Get or create the global EchoChamberGuard instance."""
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = EchoChamberGuard()
    return _guard


def reset_echo_chamber_guard() -> None:
    """Reset the global EchoChamberGuard instance."""
    global _guard
    _guard = None
