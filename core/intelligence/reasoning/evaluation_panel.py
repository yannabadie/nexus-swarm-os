"""
NEXUS V12.4 - Multi-Dimensional Evaluation Panel

Based on CRM (arxiv:2511.16202) - Multi-Agent Collaborative Reward Design.

Replaces single-scorer reasoning quality with a panel of specialist evaluators.
Each evaluator assesses one dimension of output quality, and an aggregator
fuses scores with configurable weights into a composite reward.

Dimensions:
  - FACTUAL: Factual correctness (grounding, evidence)
  - REASONING: Logical validity (consistency, coherence of argument)
  - HELPFULNESS: Task relevance and usefulness
  - COHERENCE: Structural quality and clarity

Usage:
    panel = EvaluationPanel()

    # Evaluate an output
    result = panel.evaluate(
        output="The auth bug is in token.py line 42 due to missing expiry check",
        context="Task: Find auth bugs. Module: token.py",
    )
    # result.composite_score = 0.82
    # result.dimension_scores = {FACTUAL: 0.9, REASONING: 0.8, ...}
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Evaluation Dimensions
# =============================================================================


class EvalDimension(str, Enum):
    """Evaluation quality dimensions."""

    FACTUAL = "factual"  # Factual correctness
    REASONING = "reasoning"  # Logical validity
    HELPFULNESS = "helpfulness"  # Task relevance
    COHERENCE = "coherence"  # Structural clarity


# Default weights per dimension (sum = 1.0)
DEFAULT_WEIGHTS: dict[EvalDimension, float] = {
    EvalDimension.FACTUAL: 0.30,
    EvalDimension.REASONING: 0.30,
    EvalDimension.HELPFULNESS: 0.25,
    EvalDimension.COHERENCE: 0.15,
}


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""

    dimension: EvalDimension
    score: float  # 0.0 to 1.0
    evidence: list[str] = field(default_factory=list)
    penalty_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension.value,
            "score": round(self.score, 3),
            "evidence_count": len(self.evidence),
            "penalties": len(self.penalty_reasons),
        }


@dataclass
class PanelResult:
    """Aggregated evaluation result from all dimensions."""

    dimension_scores: dict[EvalDimension, DimensionScore]
    composite_score: float
    agreement_level: float  # Cross-evaluator agreement (0-1)
    weakest_dimension: EvalDimension
    strongest_dimension: EvalDimension

    def to_dict(self) -> dict:
        return {
            "composite_score": round(self.composite_score, 3),
            "agreement_level": round(self.agreement_level, 3),
            "weakest": self.weakest_dimension.value,
            "strongest": self.strongest_dimension.value,
            "dimensions": {dim.value: ds.to_dict() for dim, ds in self.dimension_scores.items()},
        }


@dataclass
class PanelStats:
    """Panel statistics."""

    evaluations_run: int = 0
    avg_composite: float = 0.0
    dimension_averages: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "evaluations_run": self.evaluations_run,
            "avg_composite": round(self.avg_composite, 3),
            "dimension_averages": {k: round(v, 3) for k, v in self.dimension_averages.items()},
        }


# =============================================================================
# Specialist Evaluators
# =============================================================================


class FactualEvaluator:
    """Evaluates factual correctness signals."""

    EVIDENCE_PATTERNS = [
        r"\bline\s+\d+\b",  # Line references
        r"\bfile\s+\S+\.\w+\b",  # File references
        r"\b\d+\.\d+\%",  # Percentages
        r"\berror\s*:\s*\S+",  # Error messages
        r"\baccording\s+to\b",  # Attribution
        r"\bversion\s+\d",  # Version refs
        r"\bdocumentation\b",  # Documentation refs
    ]

    HALLUCINATION_SIGNALS = [
        r"\bprobably\b",
        r"\bmight\s+be\b",
        r"\bI\s+think\b",
        r"\bpossibly\b",
        r"\bnot\s+sure\b",
        r"\bassuming\b",
    ]

    def evaluate(self, output: str, context: str = "") -> DimensionScore:
        score = 0.5
        evidence = []
        penalties = []

        output_lower = output.lower()

        # Positive: Evidence of grounding
        for pattern in self.EVIDENCE_PATTERNS:
            matches = re.findall(pattern, output_lower)
            if matches:
                score += 0.08
                evidence.append(f"Grounding: {pattern}")

        # Negative: Hedging/uncertainty signals
        for pattern in self.HALLUCINATION_SIGNALS:
            if re.search(pattern, output_lower):
                score -= 0.05
                penalties.append(f"Uncertainty: {pattern}")

        # Bonus for specific technical detail
        if re.search(r"\b[a-zA-Z_]\w*\.\w+\b", output):  # dotted names (module.func)
            score += 0.05
            evidence.append("Technical specificity detected")

        return DimensionScore(
            dimension=EvalDimension.FACTUAL,
            score=max(0.0, min(1.0, score)),
            evidence=evidence,
            penalty_reasons=penalties,
        )


class ReasoningEvaluator:
    """Evaluates logical reasoning quality."""

    REASONING_SIGNALS = [
        r"\bbecause\b",
        r"\btherefore\b",
        r"\bsince\b",
        r"\bconsequently\b",
        r"\bimplies\b",
        r"\bif\s+.+\s+then\b",
        r"\bdue\s+to\b",
        r"\bcaused\s+by\b",
    ]

    CONTRADICTION_SIGNALS = [
        r"\bbut\s+also\b.*\bnot\b",
        r"\bhowever\b.*\bcontradicts\b",
    ]

    STRUCTURE_SIGNALS = [
        r"\b(first|1[\.\)])\b",
        r"\b(second|2[\.\)])\b",
        r"\b(finally|conclusion|summary)\b",
    ]

    def evaluate(self, output: str, context: str = "") -> DimensionScore:
        score = 0.5
        evidence = []
        penalties = []

        output_lower = output.lower()

        # Positive: Causal reasoning signals
        reasoning_count = 0
        for pattern in self.REASONING_SIGNALS:
            if re.search(pattern, output_lower):
                reasoning_count += 1
        if reasoning_count > 0:
            score += min(0.3, reasoning_count * 0.07)
            evidence.append(f"{reasoning_count} reasoning connectors found")

        # Positive: Structured argument
        structure_count = sum(1 for p in self.STRUCTURE_SIGNALS if re.search(p, output_lower))
        if structure_count >= 2:
            score += 0.1
            evidence.append("Structured argument detected")

        # Negative: Very short output (lacks reasoning)
        words = len(output.split())
        if words < 10:
            score -= 0.15
            penalties.append("Too brief for meaningful reasoning")
        elif words < 30:
            score -= 0.05
            penalties.append("Short output may lack depth")

        return DimensionScore(
            dimension=EvalDimension.REASONING,
            score=max(0.0, min(1.0, score)),
            evidence=evidence,
            penalty_reasons=penalties,
        )


class HelpfulnessEvaluator:
    """Evaluates task relevance and usefulness."""

    ACTION_SIGNALS = [
        r"\b(fix|solve|implement|create|update|add|remove|change)\b",
        r"\b(recommend|suggest|propose|try)\b",
        r"\b(step\s+\d|first|then|next|finally)\b",
    ]

    def evaluate(self, output: str, context: str = "") -> DimensionScore:
        score = 0.5
        evidence = []
        penalties = []

        output_lower = output.lower()

        # Positive: Actionable content
        action_count = 0
        for pattern in self.ACTION_SIGNALS:
            if re.search(pattern, output_lower):
                action_count += 1
        if action_count > 0:
            score += min(0.25, action_count * 0.06)
            evidence.append(f"{action_count} actionable signals")

        # Positive: Context alignment (shared keywords)
        if context:
            context_words = set(context.lower().split())
            output_words = set(output_lower.split())
            overlap = len(context_words & output_words)
            if overlap > 3:
                score += 0.1
                evidence.append(f"Context alignment: {overlap} shared terms")

        # Negative: Generic/vague output
        vague_patterns = [r"\bit\s+depends\b", r"\bmore\s+information\b", r"\bneed\s+more\s+context\b"]
        for pattern in vague_patterns:
            if re.search(pattern, output_lower):
                score -= 0.1
                penalties.append("Vague/deflecting language")

        # Length-based utility
        words = len(output.split())
        if words > 50:
            score += 0.05
            evidence.append("Substantial response")

        return DimensionScore(
            dimension=EvalDimension.HELPFULNESS,
            score=max(0.0, min(1.0, score)),
            evidence=evidence,
            penalty_reasons=penalties,
        )


class CoherenceEvaluator:
    """Evaluates structural quality and clarity."""

    def evaluate(self, output: str, context: str = "") -> DimensionScore:
        score = 0.6  # Slightly higher base (most outputs are coherent)
        evidence = []
        penalties = []

        # Sentence count and quality
        sentences = re.split(r"[.!?]+", output.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = len(sentences)

        if sentence_count == 0:
            return DimensionScore(
                dimension=EvalDimension.COHERENCE,
                score=0.1,
                evidence=[],
                penalty_reasons=["Empty output"],
            )

        # Positive: Multiple well-formed sentences
        if sentence_count >= 3:
            score += 0.1
            evidence.append(f"{sentence_count} sentences (well-structured)")

        # Positive: Paragraph structure
        if "\n\n" in output or "\n- " in output or "\n1." in output:
            score += 0.1
            evidence.append("Structured formatting detected")

        # Negative: Very long single sentences (run-on)
        avg_words = len(output.split()) / max(1, sentence_count)
        if avg_words > 60:
            score -= 0.1
            penalties.append("Possible run-on sentences")

        # Negative: Repetition detection
        words = output.lower().split()
        if len(words) > 10:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < 0.4:
                score -= 0.15
                penalties.append("High word repetition")

        return DimensionScore(
            dimension=EvalDimension.COHERENCE,
            score=max(0.0, min(1.0, score)),
            evidence=evidence,
            penalty_reasons=penalties,
        )


# =============================================================================
# Evaluation Panel
# =============================================================================


class EvaluationPanel:
    """
    Multi-dimensional evaluation panel (CRM-inspired).

    Runs specialist evaluators and aggregates scores with configurable weights.
    """

    def __init__(
        self,
        weights: dict[EvalDimension, float] | None = None,
    ):
        self._weights = weights or dict(DEFAULT_WEIGHTS)
        self._evaluators = {
            EvalDimension.FACTUAL: FactualEvaluator(),
            EvalDimension.REASONING: ReasoningEvaluator(),
            EvalDimension.HELPFULNESS: HelpfulnessEvaluator(),
            EvalDimension.COHERENCE: CoherenceEvaluator(),
        }
        self._history: list[float] = []
        self._dimension_history: dict[EvalDimension, list[float]] = {d: [] for d in EvalDimension}
        self._lock = threading.Lock()

    def evaluate(self, output: str, context: str = "") -> PanelResult:
        """
        Evaluate an output across all dimensions.

        Args:
            output: The output text to evaluate
            context: Task context for relevance scoring

        Returns:
            PanelResult with dimension scores and composite
        """
        # Run all specialist evaluators
        dimension_scores: dict[EvalDimension, DimensionScore] = {}
        for dim, evaluator in self._evaluators.items():
            dimension_scores[dim] = evaluator.evaluate(output, context)

        # Compute weighted composite
        composite = 0.0
        for dim, weight in self._weights.items():
            composite += weight * dimension_scores[dim].score

        # Agreement level: std dev of scores (lower = more agreement)
        scores = [ds.score for ds in dimension_scores.values()]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std_dev = variance**0.5
        agreement = 1.0 - min(1.0, std_dev * 2)  # Scale: 0 std = 1.0 agreement

        # Find strongest/weakest
        weakest = min(dimension_scores, key=lambda d: dimension_scores[d].score)
        strongest = max(dimension_scores, key=lambda d: dimension_scores[d].score)

        # Record history
        with self._lock:
            self._history.append(composite)
            for dim, ds in dimension_scores.items():
                self._dimension_history[dim].append(ds.score)

        return PanelResult(
            dimension_scores=dimension_scores,
            composite_score=composite,
            agreement_level=agreement,
            weakest_dimension=weakest,
            strongest_dimension=strongest,
        )

    def get_stats(self) -> PanelStats:
        """Get panel statistics."""
        with self._lock:
            if not self._history:
                return PanelStats()
            dim_avgs = {}
            for dim, scores in self._dimension_history.items():
                if scores:
                    dim_avgs[dim.value] = sum(scores) / len(scores)
            return PanelStats(
                evaluations_run=len(self._history),
                avg_composite=sum(self._history) / len(self._history),
                dimension_averages=dim_avgs,
            )

    def reset(self) -> None:
        """Reset evaluation history."""
        with self._lock:
            self._history.clear()
            for dim in self._dimension_history:
                self._dimension_history[dim].clear()

    @property
    def evaluation_count(self) -> int:
        return len(self._history)


# =============================================================================
# Singleton
# =============================================================================

_panel: EvaluationPanel | None = None
_panel_lock = threading.Lock()


def get_evaluation_panel() -> EvaluationPanel:
    """Get or create the global EvaluationPanel."""
    global _panel
    if _panel is None:
        with _panel_lock:
            if _panel is None:
                _panel = EvaluationPanel()
    return _panel


def reset_evaluation_panel() -> None:
    """Reset the global EvaluationPanel."""
    global _panel
    _panel = None
