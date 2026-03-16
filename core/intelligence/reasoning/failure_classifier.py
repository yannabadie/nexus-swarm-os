"""
NEXUS V12.4 - Failure Classifier (arXiv:2509.25370, AgentDebug)

Five-category root cause classification for agent failures.
Delivers targeted corrective feedback per failure category.

Based on: "Where LLM Agents Fail and How They Can Learn From
Failures" (arXiv:2509.25370)

Five root cause categories:
1. MEMORY: Lost context, forgot instructions, ignored prior results
2. REFLECTION: Failed to self-correct, missed own errors
3. PLANNING: Wrong decomposition, missed dependencies, bad ordering
4. ACTION: Wrong tool choice, incorrect parameters, execution errors
5. SYSTEM: External failures, timeouts, API errors, resource limits

Each category has targeted recovery strategies that can be used
by Phase 6 (Retry) to apply the right fix.

Usage:
    classifier = get_failure_classifier()

    classification = classifier.classify(
        failure_description="Agent generated SQL query but forgot
            to check table schema first",
        step_outputs=["Generated SQL: SELECT...", "Error: column not found"],
        issues=[{"issue_type": "error", "severity": "error"}],
    )
    # classification.category == FailureCategory.PLANNING
    # classification.recovery_strategy == "Re-decompose task with schema check first"
"""

import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class FailureCategory(Enum):
    """Five root cause categories from AgentDebug taxonomy."""

    MEMORY = "memory"  # Lost context, forgot instructions
    REFLECTION = "reflection"  # Failed self-correction
    PLANNING = "planning"  # Bad decomposition, dependencies
    ACTION = "action"  # Wrong tool, bad parameters
    SYSTEM = "system"  # External failures, timeouts


@dataclass
class Classification:
    """Result of failure classification."""

    category: FailureCategory
    confidence: float  # 0-1 confidence in classification
    evidence: list[str]  # Evidence supporting this classification
    recovery_strategy: str  # Targeted recovery suggestion
    secondary_category: FailureCategory | None = None
    signal_scores: dict[str, float] = field(default_factory=dict)

    @property
    def is_confident(self) -> bool:
        """Whether classification confidence is above threshold."""
        return self.confidence > 0.5


@dataclass
class ClassifierStats:
    """Statistics for the failure classifier."""

    total_classifications: int
    category_distribution: dict[str, int]
    avg_confidence: float
    most_common_category: str


# =============================================================================
# Category Signal Patterns
# =============================================================================

MEMORY_PATTERNS = [
    r"forgot",
    r"didn'?t remember",
    r"lost context",
    r"missing context",
    r"ignored.*previous",
    r"didn'?t consider",
    r"overlooked",
    r"failed to recall",
    r"not aware of",
    r"didn'?t use.*earlier",
    r"context.*lost",
    r"missing.*information",
]

REFLECTION_PATTERNS = [
    r"didn'?t notice",
    r"failed to.*correct",
    r"repeated.*same.*error",
    r"didn'?t.*self.*check",
    r"missed.*own.*mistake",
    r"no.*validation",
    r"didn'?t verify",
    r"blind spot",
    r"unaware of.*error",
    r"same.*mistake.*again",
]

PLANNING_PATTERNS = [
    r"wrong.*order",
    r"missed.*dependency",
    r"should have.*first",
    r"bad.*decomposition",
    r"incorrect.*sequence",
    r"skipped.*step",
    r"missing.*prerequisite",
    r"wrong.*approach",
    r"didn'?t.*plan",
    r"out of order",
    r"dependency.*missing",
    r"incomplete.*plan",
]

ACTION_PATTERNS = [
    r"wrong.*tool",
    r"incorrect.*parameter",
    r"bad.*argument",
    r"syntax.*error",
    r"type.*error",
    r"invalid.*input",
    r"malformed",
    r"wrong.*command",
    r"incorrect.*usage",
    r"wrong.*file",
    r"wrong.*path",
    r"permission.*denied",
]

SYSTEM_PATTERNS = [
    r"timeout",
    r"connection.*refused",
    r"api.*error",
    r"rate.*limit",
    r"server.*error",
    r"network.*error",
    r"resource.*limit",
    r"out.*of.*memory",
    r"disk.*full",
    r"service.*unavailable",
    r"503",
    r"429",
    r"500",
]

# Compiled patterns
_PATTERNS: dict[FailureCategory, list] = {
    FailureCategory.MEMORY: [re.compile(p, re.IGNORECASE) for p in MEMORY_PATTERNS],
    FailureCategory.REFLECTION: [re.compile(p, re.IGNORECASE) for p in REFLECTION_PATTERNS],
    FailureCategory.PLANNING: [re.compile(p, re.IGNORECASE) for p in PLANNING_PATTERNS],
    FailureCategory.ACTION: [re.compile(p, re.IGNORECASE) for p in ACTION_PATTERNS],
    FailureCategory.SYSTEM: [re.compile(p, re.IGNORECASE) for p in SYSTEM_PATTERNS],
}

# Recovery strategies per category
RECOVERY_STRATEGIES: dict[FailureCategory, str] = {
    FailureCategory.MEMORY: (
        "Re-inject relevant context from earlier steps. Summarize key findings and constraints before retrying."
    ),
    FailureCategory.REFLECTION: (
        "Add explicit self-verification step. Compare output against requirements before proceeding."
    ),
    FailureCategory.PLANNING: (
        "Re-decompose the task with dependency analysis. Verify prerequisites are met before each step."
    ),
    FailureCategory.ACTION: ("Review tool documentation and parameter requirements. Validate inputs before execution."),
    FailureCategory.SYSTEM: ("Retry with exponential backoff. Check system health and resource availability."),
}


# =============================================================================
# Failure Classifier
# =============================================================================


class FailureClassifier:
    """
    Five-category root cause classifier for agent failures.

    Uses pattern matching and signal aggregation to classify failures
    into memory, reflection, planning, action, or system categories.
    Each category maps to targeted recovery strategies.

    No LLM calls — pure heuristic classification.
    """

    def __init__(self):
        self._total = 0
        self._category_counts: Counter = Counter()
        self._confidence_sum = 0.0
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def classify(
        self,
        failure_description: str = "",
        step_outputs: list[str] | None = None,
        issues: list[dict] | None = None,
    ) -> Classification:
        """
        Classify a failure into one of five root cause categories.

        Args:
            failure_description: Text describing the failure
            step_outputs: List of step output strings
            issues: List of issue dicts with "issue_type" and "severity"

        Returns:
            Classification with category, confidence, and recovery strategy
        """
        # Combine all text for pattern matching
        all_text = failure_description or ""
        if step_outputs:
            all_text += " " + " ".join(str(s)[:500] for s in step_outputs)
        if issues:
            all_text += " " + " ".join(f"{i.get('issue_type', '')} {i.get('severity', '')}" for i in issues)

        if not all_text.strip():
            return Classification(
                category=FailureCategory.SYSTEM,
                confidence=0.0,
                evidence=["No failure information provided"],
                recovery_strategy=RECOVERY_STRATEGIES[FailureCategory.SYSTEM],
            )

        # Score each category
        scores: dict[FailureCategory, float] = {}
        evidence: dict[FailureCategory, list[str]] = {}

        for category, patterns in _PATTERNS.items():
            matches = []
            for p in patterns:
                found = p.findall(all_text)
                if found:
                    matches.extend(found)
            score = min(1.0, len(matches) / 3.0)  # 3 matches = max score
            scores[category] = score
            evidence[category] = matches[:5]  # Keep top 5 evidence items

        # Issue type boosting
        if issues:
            for issue in issues:
                itype = str(issue.get("issue_type", "")).lower()
                if "timeout" in itype or "connection" in itype:
                    scores[FailureCategory.SYSTEM] += 0.3
                elif "hallucination" in itype:
                    scores[FailureCategory.MEMORY] += 0.2
                    scores[FailureCategory.REFLECTION] += 0.1
                elif "error" in itype or "syntax" in itype:
                    scores[FailureCategory.ACTION] += 0.2
                elif "stagnation" in itype or "repeated" in itype:
                    scores[FailureCategory.REFLECTION] += 0.3

        # Find primary and secondary categories
        sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_cats[0][0]
        primary_score = sorted_cats[0][1]

        secondary = None
        if len(sorted_cats) > 1 and sorted_cats[1][1] > 0.2:
            secondary = sorted_cats[1][0]

        # Normalize confidence
        total_score = sum(scores.values())
        confidence = primary_score / max(total_score, 0.01) if total_score > 0 else 0.0
        confidence = min(1.0, confidence)

        # If no patterns matched, default to ACTION (most common failure)
        if primary_score == 0:
            primary = FailureCategory.ACTION
            confidence = 0.2

        result = Classification(
            category=primary,
            confidence=confidence,
            evidence=evidence.get(primary, []),
            recovery_strategy=RECOVERY_STRATEGIES[primary],
            secondary_category=secondary,
            signal_scores={cat.value: score for cat, score in scores.items()},
        )

        with self._lock:
            self._total += 1
            self._category_counts[primary.value] += 1
            self._confidence_sum += confidence

        return result

    def get_recovery_strategy(self, category: FailureCategory) -> str:
        """Get the recovery strategy for a specific failure category."""
        return RECOVERY_STRATEGIES.get(category, RECOVERY_STRATEGIES[FailureCategory.ACTION])

    def get_stats(self) -> ClassifierStats:
        """Get classifier statistics."""
        avg_conf = self._confidence_sum / max(self._total, 1)
        most_common = self._category_counts.most_common(1)
        mc = most_common[0][0] if most_common else ""

        return ClassifierStats(
            total_classifications=self._total,
            category_distribution=dict(self._category_counts),
            avg_confidence=avg_conf,
            most_common_category=mc,
        )


# =============================================================================
# Singleton
# =============================================================================

_instance: FailureClassifier | None = None
_instance_lock = threading.Lock()


def get_failure_classifier() -> FailureClassifier:
    """Get or create the singleton FailureClassifier instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FailureClassifier()
    return _instance


def reset_failure_classifier() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
