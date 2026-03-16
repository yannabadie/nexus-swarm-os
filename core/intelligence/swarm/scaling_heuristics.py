"""
V12.4 COGNITIVE BOOST: Scaling Heuristics (arXiv:2512.08296)

Empirically-validated scaling laws for multi-agent coordination.
Provides heuristic decision boundaries for when to use centralized
vs decentralized coordination, and when multi-agent degrades
performance.

Key findings integrated:
- Centralized coordination excels for parallelizable tasks (+80.8%)
- Decentralized better for web navigation (+9.2%)
- Multi-agent degrades sequential reasoning by 39-70%
- Predictive framework correct for 87% of configurations

Reference: "Towards a Science of Scaling Agent Systems"
(arXiv:2512.08296)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class CoordinationType(str, Enum):
    """Recommended coordination strategy."""

    CENTRALIZED = "centralized"  # One lead, others support
    DECENTRALIZED = "decentralized"  # Agents coordinate autonomously
    SINGLE_AGENT = "single_agent"  # Use only one agent (SPECIALIST)
    PARALLEL = "parallel"  # Independent parallel work
    SEQUENTIAL = "sequential"  # Ordered pipeline


class TaskCharacteristic(str, Enum):
    """Task characteristics that influence scaling behavior."""

    PARALLELIZABLE = "parallelizable"  # Can be split into independent parts
    SEQUENTIAL_REASONING = "sequential"  # Requires chain-of-thought
    WEB_NAVIGATION = "web_navigation"  # Web browsing/research
    CODE_GENERATION = "code_generation"  # Writing code
    CODE_REVIEW = "code_review"  # Reviewing/debugging code
    CREATIVE = "creative"  # Creative/brainstorming tasks
    ANALYTICAL = "analytical"  # Data analysis/reasoning
    MIXED = "mixed"  # Combination of characteristics


@dataclass
class ScalingRecommendation:
    """Recommendation from scaling heuristics."""

    coordination: CoordinationType
    max_agents: int = 2
    confidence: float = 0.5
    reasoning: str = ""
    characteristic: TaskCharacteristic = TaskCharacteristic.MIXED
    expected_benefit_pct: float = 0.0  # Expected improvement from multi-agent
    degradation_risk: float = 0.0  # Risk of multi-agent degradation

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordination": self.coordination.value,
            "max_agents": self.max_agents,
            "confidence": round(self.confidence, 3),
            "characteristic": self.characteristic.value,
            "expected_benefit_pct": round(self.expected_benefit_pct, 1),
            "degradation_risk": round(self.degradation_risk, 3),
            "reasoning": self.reasoning,
        }


@dataclass
class ScalingStats:
    """Aggregate statistics."""

    total_recommendations: int = 0
    coordination_counts: dict[str, int] = field(default_factory=dict)
    single_agent_overrides: int = 0
    avg_confidence: float = 0.0
    outcomes: list[tuple[str, bool]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_recommendations": self.total_recommendations,
            "coordination_counts": dict(self.coordination_counts),
            "single_agent_overrides": self.single_agent_overrides,
            "avg_confidence": round(self.avg_confidence, 3),
        }


# ---------------------------------------------------------------------------
# Constants: Scaling Law Parameters (from arXiv:2512.08296)
# ---------------------------------------------------------------------------

# Task characteristic -> expected multi-agent benefit (positive = benefit)
SCALING_BENEFIT: dict[TaskCharacteristic, float] = {
    TaskCharacteristic.PARALLELIZABLE: 0.808,  # +80.8% for parallelizable
    TaskCharacteristic.WEB_NAVIGATION: 0.092,  # +9.2% for web nav
    TaskCharacteristic.CODE_REVIEW: 0.45,  # +45% for reviews (adversarial)
    TaskCharacteristic.CREATIVE: 0.35,  # +35% for brainstorming
    TaskCharacteristic.ANALYTICAL: 0.20,  # +20% for analysis
    TaskCharacteristic.CODE_GENERATION: 0.10,  # +10% marginal for code gen
    TaskCharacteristic.SEQUENTIAL_REASONING: -0.50,  # -50% DEGRADATION for sequential
    TaskCharacteristic.MIXED: 0.15,  # +15% average for mixed
}

# Degradation risk per characteristic
DEGRADATION_RISK: dict[TaskCharacteristic, float] = {
    TaskCharacteristic.PARALLELIZABLE: 0.05,
    TaskCharacteristic.WEB_NAVIGATION: 0.15,
    TaskCharacteristic.CODE_REVIEW: 0.10,
    TaskCharacteristic.CREATIVE: 0.10,
    TaskCharacteristic.ANALYTICAL: 0.20,
    TaskCharacteristic.CODE_GENERATION: 0.25,
    TaskCharacteristic.SEQUENTIAL_REASONING: 0.70,
    TaskCharacteristic.MIXED: 0.20,
}

# Recommended coordination per characteristic
COORDINATION_MAP: dict[TaskCharacteristic, CoordinationType] = {
    TaskCharacteristic.PARALLELIZABLE: CoordinationType.PARALLEL,
    TaskCharacteristic.WEB_NAVIGATION: CoordinationType.DECENTRALIZED,
    TaskCharacteristic.CODE_REVIEW: CoordinationType.CENTRALIZED,
    TaskCharacteristic.CREATIVE: CoordinationType.DECENTRALIZED,
    TaskCharacteristic.ANALYTICAL: CoordinationType.CENTRALIZED,
    TaskCharacteristic.CODE_GENERATION: CoordinationType.SINGLE_AGENT,
    TaskCharacteristic.SEQUENTIAL_REASONING: CoordinationType.SINGLE_AGENT,
    TaskCharacteristic.MIXED: CoordinationType.CENTRALIZED,
}

# Keywords for task characteristic detection
CHARACTERISTIC_KEYWORDS: dict[TaskCharacteristic, list[str]] = {
    TaskCharacteristic.PARALLELIZABLE: [
        "parallel",
        "independent",
        "simultaneously",
        "each",
        "all",
        "separate",
        "multiple",
        "batch",
        "concurrent",
    ],
    TaskCharacteristic.SEQUENTIAL_REASONING: [
        "step by step",
        "chain",
        "sequence",
        "derive",
        "prove",
        "calculate",
        "solve",
        "reason",
        "deduce",
        "logic",
        "mathematical",
        "theorem",
        "infer",
    ],
    TaskCharacteristic.WEB_NAVIGATION: [
        "search",
        "browse",
        "find online",
        "web",
        "url",
        "website",
        "internet",
        "google",
        "look up",
        "fetch",
    ],
    TaskCharacteristic.CODE_GENERATION: [
        "write",
        "implement",
        "create",
        "build",
        "code",
        "develop",
        "function",
        "class",
        "module",
        "feature",
    ],
    TaskCharacteristic.CODE_REVIEW: [
        "review",
        "check",
        "audit",
        "security",
        "bug",
        "fix",
        "debug",
        "test",
        "validate",
        "verify",
    ],
    TaskCharacteristic.CREATIVE: [
        "brainstorm",
        "design",
        "ideate",
        "creative",
        "innovate",
        "propose",
        "suggest",
        "imagine",
        "architect",
    ],
    TaskCharacteristic.ANALYTICAL: [
        "analyze",
        "compare",
        "evaluate",
        "assess",
        "measure",
        "benchmark",
        "profile",
        "optimize",
        "performance",
    ],
}

# Complexity -> agent count recommendation
COMPLEXITY_AGENT_MAP: dict[str, int] = {
    "trivial": 1,
    "simple": 1,
    "moderate": 2,
    "complex": 2,
    "expert": 2,
}

# Threshold: below this benefit, recommend single agent
SINGLE_AGENT_THRESHOLD: float = 0.05


# ---------------------------------------------------------------------------
# Core: ScalingHeuristicEvaluator
# ---------------------------------------------------------------------------


class ScalingHeuristicEvaluator:
    """
    Scaling law heuristic evaluator.

    Classifies tasks by characteristic and recommends coordination
    strategy based on empirically-validated scaling laws.

    Usage:
        evaluator = ScalingHeuristicEvaluator()
        rec = evaluator.evaluate(
            task_text="Write a function to sort a list",
            complexity="simple",
        )
        if rec.coordination == CoordinationType.SINGLE_AGENT:
            # Use SPECIALIST swarm mode
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats = ScalingStats()
        self._outcome_history: list[tuple[TaskCharacteristic, CoordinationType, bool]] = []

    # -- public API --

    def evaluate(
        self,
        task_text: str,
        complexity: str = "moderate",
        domains: list[str] | None = None,
    ) -> ScalingRecommendation:
        """
        Evaluate a task and recommend scaling strategy.

        Args:
            task_text: The task description.
            complexity: TRIVIAL/SIMPLE/MODERATE/COMPLEX/EXPERT.
            domains: Optional list of task domains (CODING, RESEARCH, etc.).

        Returns:
            ScalingRecommendation with coordination type and confidence.
        """
        # 1. Classify task characteristic
        characteristic = self._classify_characteristic(task_text, domains)

        # 2. Look up scaling parameters
        benefit = SCALING_BENEFIT.get(characteristic, 0.15)
        risk = DEGRADATION_RISK.get(characteristic, 0.20)
        base_coordination = COORDINATION_MAP.get(characteristic, CoordinationType.CENTRALIZED)
        max_agents = COMPLEXITY_AGENT_MAP.get(complexity.lower(), 2)

        # 3. Adjust based on complexity
        if complexity.lower() in ("trivial", "simple") and benefit < 0.30:
            # Simple tasks don't benefit from multi-agent
            base_coordination = CoordinationType.SINGLE_AGENT
            max_agents = 1
            benefit = 0.0

        # 4. Override to single agent if benefit too low
        if benefit < SINGLE_AGENT_THRESHOLD:
            base_coordination = CoordinationType.SINGLE_AGENT
            max_agents = 1

        # 5. Historical adjustment
        historical_adj = self._get_historical_adjustment(characteristic)
        adjusted_benefit = benefit + historical_adj

        # 6. Compute confidence
        confidence = self._compute_confidence(characteristic, complexity, adjusted_benefit, risk)

        reasoning = self._build_reasoning(characteristic, base_coordination, adjusted_benefit, risk, complexity)

        result = ScalingRecommendation(
            coordination=base_coordination,
            max_agents=max_agents,
            confidence=confidence,
            reasoning=reasoning,
            characteristic=characteristic,
            expected_benefit_pct=adjusted_benefit * 100,
            degradation_risk=risk,
        )

        # Update stats
        with self._lock:
            self._stats.total_recommendations += 1
            key = base_coordination.value
            self._stats.coordination_counts[key] = self._stats.coordination_counts.get(key, 0) + 1
            if base_coordination == CoordinationType.SINGLE_AGENT:
                self._stats.single_agent_overrides += 1
            n = self._stats.total_recommendations
            self._stats.avg_confidence = (self._stats.avg_confidence * (n - 1) + confidence) / n

        logger.debug(
            "ScalingHeuristic: %s -> %s (benefit=%.1f%%, risk=%.1f%%, confidence=%.2f)",
            characteristic.value,
            base_coordination.value,
            adjusted_benefit * 100,
            risk * 100,
            confidence,
        )

        return result

    def record_outcome(
        self,
        characteristic: TaskCharacteristic,
        coordination: CoordinationType,
        success: bool,
    ) -> None:
        """Record outcome for historical adjustment."""
        with self._lock:
            self._outcome_history.append((characteristic, coordination, success))
            if len(self._outcome_history) > 100:
                self._outcome_history = self._outcome_history[-50:]
            self._stats.outcomes.append((coordination.value, success))

    def get_mode_suggestion(
        self,
        recommendation: ScalingRecommendation,
    ) -> str:
        """
        Map scaling recommendation to NEXUS swarm mode name.

        Returns one of: PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG,
        SPECIALIST, RED_BLUE.
        """
        mapping = {
            CoordinationType.CENTRALIZED: "LEAD_SUPPORT",
            CoordinationType.DECENTRALIZED: "PING_PONG",
            CoordinationType.SINGLE_AGENT: "SPECIALIST",
            CoordinationType.PARALLEL: "PARALLEL",
            CoordinationType.SEQUENTIAL: "SEQUENTIAL",
        }
        mode = mapping.get(recommendation.coordination, "LEAD_SUPPORT")

        # Override for specific characteristics
        if recommendation.characteristic == TaskCharacteristic.CODE_REVIEW:
            mode = "RED_BLUE"
        elif recommendation.characteristic == TaskCharacteristic.CREATIVE:
            mode = "PING_PONG"

        return mode

    def get_stats(self) -> ScalingStats:
        """Return aggregate statistics."""
        with self._lock:
            return ScalingStats(
                total_recommendations=self._stats.total_recommendations,
                coordination_counts=dict(self._stats.coordination_counts),
                single_agent_overrides=self._stats.single_agent_overrides,
                avg_confidence=self._stats.avg_confidence,
            )

    def reset(self) -> None:
        """Reset statistics and history."""
        with self._lock:
            self._stats = ScalingStats()
            self._outcome_history.clear()

    # -- private helpers --

    def _classify_characteristic(
        self,
        task_text: str,
        domains: list[str] | None,
    ) -> TaskCharacteristic:
        """Classify task by its dominant characteristic."""
        text_lower = task_text.lower()
        scores: dict[TaskCharacteristic, float] = {}

        for char, keywords in CHARACTERISTIC_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw in text_lower:
                    score += 1.0
            scores[char] = score

        # Domain-based boosting
        if domains:
            domain_map = {
                "CODING": TaskCharacteristic.CODE_GENERATION,
                "RESEARCH": TaskCharacteristic.WEB_NAVIGATION,
                "SECURITY": TaskCharacteristic.CODE_REVIEW,
                "ARCHITECTURE": TaskCharacteristic.CREATIVE,
                "ANALYSIS": TaskCharacteristic.ANALYTICAL,
            }
            for d in domains:
                char = domain_map.get(d.upper())
                if char:
                    scores[char] = scores.get(char, 0) + 2.0

        if not scores or max(scores.values()) == 0:
            return TaskCharacteristic.MIXED

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        return best

    def _get_historical_adjustment(
        self,
        characteristic: TaskCharacteristic,
    ) -> float:
        """Get adjustment based on historical outcomes."""
        with self._lock:
            relevant = [success for char, coord, success in self._outcome_history if char == characteristic]

        if len(relevant) < 3:
            return 0.0

        success_rate = sum(relevant) / len(relevant)
        # Adjust benefit: if historical success is low, reduce benefit
        return (success_rate - 0.5) * 0.2

    def _compute_confidence(
        self,
        characteristic: TaskCharacteristic,
        complexity: str,
        benefit: float,
        risk: float,
    ) -> float:
        """Compute confidence in the recommendation."""
        # Base confidence from how clear the signal is
        signal_strength = abs(benefit)
        confidence = min(0.9, 0.4 + signal_strength)

        # Reduce confidence for high-risk recommendations
        confidence -= risk * 0.2

        # Boost for well-studied characteristics
        well_studied = {
            TaskCharacteristic.PARALLELIZABLE,
            TaskCharacteristic.SEQUENTIAL_REASONING,
        }
        if characteristic in well_studied:
            confidence += 0.1

        # Reduce for ambiguous complexity
        if complexity.lower() in ("moderate",):
            confidence -= 0.05

        return max(0.1, min(0.95, confidence))

    def _build_reasoning(
        self,
        characteristic: TaskCharacteristic,
        coordination: CoordinationType,
        benefit: float,
        risk: float,
        complexity: str,
    ) -> str:
        """Build human-readable reasoning for the recommendation."""
        parts = [
            f"Task classified as {characteristic.value}.",
        ]

        if benefit > 0:
            parts.append(f"Expected multi-agent benefit: +{benefit * 100:.1f}%.")
        else:
            parts.append(f"Multi-agent expected to DEGRADE performance by {abs(benefit) * 100:.1f}%.")

        if risk > 0.3:
            parts.append(f"High degradation risk ({risk * 100:.0f}%).")

        if coordination == CoordinationType.SINGLE_AGENT:
            parts.append("Recommending single-agent (SPECIALIST) mode.")
        else:
            parts.append(f"Recommending {coordination.value} coordination.")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: ScalingHeuristicEvaluator | None = None
_instance_lock = threading.Lock()


def get_scaling_heuristics() -> ScalingHeuristicEvaluator:
    """Get or create the global ScalingHeuristicEvaluator singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ScalingHeuristicEvaluator()
    return _instance


def reset_scaling_heuristics() -> None:
    """Reset the global ScalingHeuristicEvaluator singleton."""
    global _instance
    with _instance_lock:
        _instance = None
