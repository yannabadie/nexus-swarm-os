"""
Collaboration Modes - Sprint 9 Hybrid Swarm Engine

Defines the 6 collaboration modes that agents can negotiate:
- PARALLEL: Simultaneous work, merge results
- SEQUENTIAL: One then other (ordered)
- LEAD_SUPPORT: 80% lead + 20% support
- PING_PONG: Rapid alternation, co-construction
- SPECIALIST: Single expert handles all
- RED_BLUE: Adversarial (propose/attack)

Each mode has characteristics that help the ModeSelector decide
which mode fits best for a given task.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CollaborationMode(Enum):
    """6 collaboration modes for Hybrid Swarm"""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    LEAD_SUPPORT = "lead_support"
    PING_PONG = "ping_pong"
    SPECIALIST = "specialist"
    RED_BLUE = "red_blue"

    @classmethod
    def from_string(cls, value: str) -> "CollaborationMode":
        """Parse mode from string, case-insensitive"""
        normalized = value.lower().replace("-", "_").replace(" ", "_")
        for mode in cls:
            if mode.value == normalized:
                return mode
        raise ValueError(f"Unknown collaboration mode: {value}")

    @property
    def fallback_mode(self) -> Optional["CollaborationMode"]:
        """
        Get the fallback mode for graceful degradation.

        V7.5 Phase 8: Self-Healing Swarm - Graceful Degradation

        Fallback chain:
        - PARALLEL -> SEQUENTIAL (simplify parallelism)
        - RED_BLUE -> LEAD_SUPPORT (remove adversarial)
        - LEAD_SUPPORT -> SPECIALIST (simplify to single agent)
        - PING_PONG -> SEQUENTIAL (simplify alternation)
        - SPECIALIST -> None (terminal, no further fallback)
        - SEQUENTIAL -> SPECIALIST (last resort)

        Returns:
            CollaborationMode for fallback, or None if no fallback exists
        """
        fallback_map = {
            CollaborationMode.PARALLEL: CollaborationMode.SEQUENTIAL,
            CollaborationMode.RED_BLUE: CollaborationMode.LEAD_SUPPORT,
            CollaborationMode.LEAD_SUPPORT: CollaborationMode.SPECIALIST,
            CollaborationMode.PING_PONG: CollaborationMode.SEQUENTIAL,
            CollaborationMode.SEQUENTIAL: CollaborationMode.SPECIALIST,
            CollaborationMode.SPECIALIST: None,  # Terminal - no fallback
        }
        return fallback_map.get(self)


@dataclass
class ModeCharacteristics:
    """
    Characteristics of a collaboration mode for selection scoring.

    Used by ModeSelector to match tasks to optimal modes.
    """

    mode: CollaborationMode

    # Task complexity affinity (0=trivial tasks, 1=expert tasks)
    complexity_affinity: float

    # Benefit from parallel execution (0=sequential, 1=fully parallel)
    parallelism_benefit: float

    # Whether mode is adversarial (RED_BLUE)
    adversarial: bool

    # Typical number of rounds/exchanges
    typical_rounds: int

    # Domains where Gemini excels in this mode
    gemini_strength_fit: list[str] = field(default_factory=list)

    # Domains where Claude excels in this mode
    claude_strength_fit: list[str] = field(default_factory=list)

    # Description for negotiation context
    description: str = ""

    # When to use (natural language)
    when_to_use: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "complexity_affinity": self.complexity_affinity,
            "parallelism_benefit": self.parallelism_benefit,
            "adversarial": self.adversarial,
            "typical_rounds": self.typical_rounds,
            "gemini_strength_fit": self.gemini_strength_fit,
            "claude_strength_fit": self.claude_strength_fit,
            "description": self.description,
            "when_to_use": self.when_to_use,
        }


# Pre-defined characteristics for each mode
MODE_CHARACTERISTICS: dict[CollaborationMode, ModeCharacteristics] = {
    CollaborationMode.PARALLEL: ModeCharacteristics(
        mode=CollaborationMode.PARALLEL,
        complexity_affinity=0.5,
        parallelism_benefit=1.0,
        adversarial=False,
        typical_rounds=1,
        gemini_strength_fit=["research", "web_search", "analysis"],
        claude_strength_fit=["coding", "architecture", "documentation"],
        description="Both agents work simultaneously on independent subtasks",
        when_to_use="Independent subtasks, time-critical situations",
    ),
    CollaborationMode.SEQUENTIAL: ModeCharacteristics(
        mode=CollaborationMode.SEQUENTIAL,
        complexity_affinity=0.6,
        parallelism_benefit=0.0,
        adversarial=False,
        typical_rounds=2,
        gemini_strength_fit=["research", "context_gathering"],
        claude_strength_fit=["implementation", "refinement"],
        description="First agent outputs, second agent refines/continues",
        when_to_use="Clear dependencies, pipeline tasks",
    ),
    CollaborationMode.LEAD_SUPPORT: ModeCharacteristics(
        mode=CollaborationMode.LEAD_SUPPORT,
        complexity_affinity=0.7,
        parallelism_benefit=0.3,
        adversarial=False,
        typical_rounds=3,
        gemini_strength_fit=["research", "fact_checking", "web_verification"],
        claude_strength_fit=["coding", "debugging", "complex_reasoning"],
        description="Lead agent (80%) drives, support agent (20%) reviews",
        when_to_use="Clear expertise dominance, complex coding tasks",
    ),
    CollaborationMode.PING_PONG: ModeCharacteristics(
        mode=CollaborationMode.PING_PONG,
        complexity_affinity=0.6,
        parallelism_benefit=0.2,
        adversarial=False,
        typical_rounds=6,
        gemini_strength_fit=["brainstorming", "idea_expansion"],
        claude_strength_fit=["creative_writing", "iteration", "refinement"],
        description="Rapid alternation, each builds on the other's output",
        when_to_use="Creative tasks, brainstorming, iterative refinement",
    ),
    CollaborationMode.SPECIALIST: ModeCharacteristics(
        mode=CollaborationMode.SPECIALIST,
        complexity_affinity=0.8,
        parallelism_benefit=0.0,
        adversarial=False,
        typical_rounds=1,
        gemini_strength_fit=["terminal_operations", "long_horizon_planning"],
        claude_strength_fit=["swe_bench_tasks", "sustained_autonomy"],
        description="Single expert handles everything, other observes",
        when_to_use="Exclusive expertise, highly specialized tasks",
    ),
    CollaborationMode.RED_BLUE: ModeCharacteristics(
        mode=CollaborationMode.RED_BLUE,
        complexity_affinity=1.0,
        parallelism_benefit=0.1,
        adversarial=True,
        typical_rounds=4,
        gemini_strength_fit=["security_analysis", "attack_vectors"],
        claude_strength_fit=["defense_strategies", "architectural_security"],
        description="Blue proposes, Red attacks/critiques, iterate to consensus",
        when_to_use="Security reviews, critical decisions, risk assessment",
    ),
}


def get_mode_characteristics(mode: CollaborationMode) -> ModeCharacteristics:
    """Get characteristics for a collaboration mode"""
    return MODE_CHARACTERISTICS[mode]


def get_all_modes() -> list[CollaborationMode]:
    """Get all collaboration modes in order"""
    return list(CollaborationMode)


def get_adversarial_modes() -> list[CollaborationMode]:
    """Get modes that are adversarial"""
    return [m for m, c in MODE_CHARACTERISTICS.items() if c.adversarial]


def get_parallel_modes() -> list[CollaborationMode]:
    """Get modes that benefit from parallelism"""
    return [m for m, c in MODE_CHARACTERISTICS.items() if c.parallelism_benefit >= 0.5]


def suggest_mode_for_complexity(complexity: int) -> list[CollaborationMode]:
    """
    Suggest modes based on task complexity (1-5).

    Args:
        complexity: 1=trivial, 5=expert

    Returns:
        List of suggested modes, sorted by affinity
    """
    target = complexity / 5.0  # Normalize to 0-1

    scored = [(mode, 1.0 - abs(char.complexity_affinity - target)) for mode, char in MODE_CHARACTERISTICS.items()]

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    return [mode for mode, _ in scored]
