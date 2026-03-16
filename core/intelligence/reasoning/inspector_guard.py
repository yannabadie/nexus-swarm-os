"""
NEXUS V12.4 - Inspector Guard (arXiv:2408.00989)

Post-step verification layer that reviews agent outputs before they
propagate downstream. Catches errors, inconsistencies, and degradation
patterns that individual checks miss.

Based on: "On the Resilience of LLM-Based Multi-Agent Collaboration
with Faulty Agents" (arXiv:2408.00989)

Key insight: A dedicated Inspector agent that reviews outputs can
recover up to 96.4% of errors — highest ROI of any multi-agent
reliability technique.

This module implements a lightweight, non-LLM inspection that:
1. Correlates issues across steps (regression detection)
2. Computes risk scores per step using multiple signals
3. Detects cascading failure patterns
4. Decides whether to flag for immediate diagnosis

Usage:
    inspector = get_inspector_guard()

    inspection = inspector.inspect_step(
        step_name="Generate SQL query",
        step_output="SELECT * FROM users WHERE ...",
        step_status="success",
        step_issues=[...],
        previous_inspections=[...],
    )

    if inspection.requires_diagnosis:
        # Route to Phase 5 immediately
        ...
"""

import logging
import re
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class RiskLevel(Enum):
    """Risk classification for inspection results."""

    LOW = "low"  # No concerns
    MODERATE = "moderate"  # Minor issues, continue with caution
    HIGH = "high"  # Significant issues, may need correction
    CRITICAL = "critical"  # Immediate diagnosis required


class IssuePattern(Enum):
    """Patterns detected across steps."""

    REPEATED_ERROR = "repeated_error"  # Same error type recurring
    ESCALATING_SEVERITY = "escalating_severity"  # Issues getting worse
    CASCADING_FAILURE = "cascading_failure"  # Errors propagating between steps
    HALLUCINATION_CLUSTER = "hallucination_cluster"  # Multiple hallucinations
    OUTPUT_DEGRADATION = "output_degradation"  # Output quality declining
    STAGNATION = "stagnation"  # No progress being made


@dataclass
class InspectionResult:
    """Result of inspecting a single step."""

    step_name: str
    risk_level: RiskLevel
    risk_score: float  # 0.0 (safe) to 1.0 (critical)
    requires_diagnosis: bool  # Should trigger Phase 5?
    detected_patterns: list[IssuePattern]
    issues_found: int
    issue_summary: str
    suggestions: list[str]
    inspected_at: float = field(default_factory=time.time)

    @property
    def is_safe(self) -> bool:
        return self.risk_level == RiskLevel.LOW


@dataclass
class GuardStats:
    """Statistics for the inspector guard."""

    total_inspections: int
    total_flags: int  # Steps flagged for diagnosis
    risk_distribution: dict[str, int]  # risk_level -> count
    patterns_detected: dict[str, int]  # pattern -> count
    avg_risk_score: float


# =============================================================================
# Inspection Signals
# =============================================================================

# Patterns that indicate hallucination
HALLUCINATION_INDICATORS = [
    r"i cannot access",
    r"file not found",
    r"does not exist",
    r"no such file",
    r"unable to locate",
    r"i don'?t have access",
    r"i'?m unable to",
    r"as an ai",
    r"i apologize",
]

# Patterns that indicate errors
ERROR_INDICATORS = [
    r"error:",
    r"exception:",
    r"traceback",
    r"failed:",
    r"syntaxerror",
    r"typeerror",
    r"nameerror",
    r"keyerror",
    r"valueerror",
    r"importerror",
    r"attributeerror",
]

# Patterns indicating stagnation (no useful progress)
STAGNATION_INDICATORS = [
    r"let me try again",
    r"i'?ll attempt",
    r"trying a different approach",
    r"same result",
    r"still failing",
    r"no change",
]

# Compiled patterns for efficiency
_HALLUCINATION_RE = [re.compile(p, re.IGNORECASE) for p in HALLUCINATION_INDICATORS]
_ERROR_RE = [re.compile(p, re.IGNORECASE) for p in ERROR_INDICATORS]
_STAGNATION_RE = [re.compile(p, re.IGNORECASE) for p in STAGNATION_INDICATORS]


# =============================================================================
# Inspector Guard
# =============================================================================


class InspectorGuard:
    """
    Post-step verification layer for multi-agent execution.

    Inspects each step's output for quality signals, correlates issues
    across steps, and flags steps that require immediate diagnosis.

    Architecture-agnostic: works across all HiveMind phases and swarm modes.
    No LLM calls — uses pattern matching and statistical analysis.
    """

    # Risk thresholds
    DIAGNOSIS_THRESHOLD = 0.7  # Risk score above this triggers diagnosis
    HIGH_RISK_THRESHOLD = 0.5
    MODERATE_THRESHOLD = 0.3

    # Cascade detection
    MAX_HISTORY = 50  # Max inspections to keep in history
    CASCADE_WINDOW = 5  # Steps to look back for cascading patterns
    REPEAT_THRESHOLD = 3  # Same error N times = cascading

    def __init__(self, diagnosis_threshold: float = 0.0):
        self._threshold = diagnosis_threshold or self.DIAGNOSIS_THRESHOLD
        self._history: deque[InspectionResult] = deque(maxlen=self.MAX_HISTORY)
        self._issue_type_counts: Counter = Counter()
        self._total_inspections = 0
        self._total_flags = 0
        self._risk_counts: Counter = Counter()
        self._pattern_counts: Counter = Counter()
        self._score_sum = 0.0
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def inspect_step(
        self,
        step_name: str,
        step_output: str,
        step_status: str = "success",
        step_issues: list[dict] | None = None,
        previous_inspections: list[InspectionResult] | None = None,
    ) -> InspectionResult:
        """
        Inspect a step's output and produce a risk assessment.

        Args:
            step_name: Name of the execution step
            step_output: The step's output text
            step_status: Status ("success", "warning", "error")
            step_issues: List of issue dicts with "issue_type" and "severity"
            previous_inspections: Optional explicit history (otherwise uses internal)

        Returns:
            InspectionResult with risk level, score, and detected patterns
        """
        issues = step_issues or []
        history = previous_inspections or list(self._history)
        output = step_output or ""

        # Compute individual signal scores
        status_score = self._score_status(step_status)
        issue_score = self._score_issues(issues)
        hallucination_score = self._score_hallucinations(output)
        error_score = self._score_errors(output)
        stagnation_score = self._score_stagnation(output)
        cascade_score = self._score_cascade(issues, history)
        length_score = self._score_output_length(output, history)

        # Weighted composite risk score
        risk_score = (
            0.25 * status_score
            + 0.20 * issue_score
            + 0.15 * hallucination_score
            + 0.15 * error_score
            + 0.10 * stagnation_score
            + 0.10 * cascade_score
            + 0.05 * length_score
        )
        risk_score = min(1.0, max(0.0, risk_score))

        # Detect patterns
        patterns = self._detect_patterns(issues, output, history)

        # Boost risk if cascading patterns detected
        if IssuePattern.CASCADING_FAILURE in patterns:
            risk_score = min(1.0, risk_score + 0.2)
        if IssuePattern.ESCALATING_SEVERITY in patterns:
            risk_score = min(1.0, risk_score + 0.15)

        # Determine risk level
        if risk_score >= self._threshold:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= self.HIGH_RISK_THRESHOLD:
            risk_level = RiskLevel.HIGH
        elif risk_score >= self.MODERATE_THRESHOLD:
            risk_level = RiskLevel.MODERATE
        else:
            risk_level = RiskLevel.LOW

        requires_diagnosis = risk_score >= self._threshold

        # Build suggestions
        suggestions = self._generate_suggestions(patterns, risk_score)

        # Issue summary
        issue_summary = self._summarize_issues(issues, hallucination_score, error_score, patterns)

        result = InspectionResult(
            step_name=step_name,
            risk_level=risk_level,
            risk_score=risk_score,
            requires_diagnosis=requires_diagnosis,
            detected_patterns=patterns,
            issues_found=len(issues),
            issue_summary=issue_summary,
            suggestions=suggestions,
        )

        # Update internal state
        with self._lock:
            self._history.append(result)
            self._total_inspections += 1
            self._risk_counts[risk_level.value] += 1
            self._score_sum += risk_score
            for p in patterns:
                self._pattern_counts[p.value] += 1
            if requires_diagnosis:
                self._total_flags += 1

        if requires_diagnosis:
            logger.warning(
                f"InspectorGuard: FLAGGED step '{step_name}' "
                f"(risk={risk_score:.2f}, patterns={[p.value for p in patterns]})"
            )

        return result

    def get_stats(self) -> GuardStats:
        """Get inspector guard statistics."""
        avg = self._score_sum / max(self._total_inspections, 1)
        return GuardStats(
            total_inspections=self._total_inspections,
            total_flags=self._total_flags,
            risk_distribution=dict(self._risk_counts),
            patterns_detected=dict(self._pattern_counts),
            avg_risk_score=avg,
        )

    @property
    def threshold(self) -> float:
        return self._threshold

    # -------------------------------------------------------------------------
    # Signal Scoring (0.0 = safe, 1.0 = critical)
    # -------------------------------------------------------------------------

    def _score_status(self, status: str) -> float:
        """Score based on step execution status."""
        status_map = {
            "success": 0.0,
            "warning": 0.4,
            "error": 0.8,
            "timeout": 0.9,
            "failure": 1.0,
        }
        return status_map.get(status.lower(), 0.5)

    def _score_issues(self, issues: list[dict]) -> float:
        """Score based on number and severity of issues."""
        if not issues:
            return 0.0

        severity_weights = {
            "info": 0.1,
            "warning": 0.3,
            "error": 0.6,
            "critical": 1.0,
        }

        total_weight = sum(severity_weights.get(str(i.get("severity", "info")).lower(), 0.3) for i in issues)

        # Normalize: 3 critical issues = 1.0
        return min(1.0, total_weight / 3.0)

    def _score_hallucinations(self, output: str) -> float:
        """Score hallucination indicators in output."""
        if not output:
            return 0.0
        matches = sum(1 for p in _HALLUCINATION_RE if p.search(output))
        return min(1.0, matches / 3.0)

    def _score_errors(self, output: str) -> float:
        """Score error indicators in output."""
        if not output:
            return 0.0
        matches = sum(1 for p in _ERROR_RE if p.search(output))
        return min(1.0, matches / 4.0)

    def _score_stagnation(self, output: str) -> float:
        """Score stagnation indicators."""
        if not output:
            return 0.0
        matches = sum(1 for p in _STAGNATION_RE if p.search(output))
        return min(1.0, matches / 2.0)

    def _score_cascade(self, issues: list[dict], history: list[InspectionResult]) -> float:
        """Score cascading failure probability from recent history."""
        if not history:
            return 0.0

        recent = history[-self.CASCADE_WINDOW :]

        # Count recent high-risk results
        high_risk_count = sum(1 for r in recent if r.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL))

        # Repeated issue types
        {i.get("issue_type", "") for i in issues}
        overlap = 0
        for prev in recent:
            if any(
                p.value in str(prev.detected_patterns)
                for p in [IssuePattern.REPEATED_ERROR, IssuePattern.CASCADING_FAILURE]
            ):
                overlap += 1

        cascade_signal = (high_risk_count / max(len(recent), 1)) * 0.6
        cascade_signal += (overlap / max(len(recent), 1)) * 0.4

        return min(1.0, cascade_signal)

    def _score_output_length(self, output: str, history: list[InspectionResult]) -> float:
        """Score anomalous output length relative to history."""
        if not output or not history:
            return 0.0

        # Check if output is suspiciously short or empty compared to history
        current_len = len(output)
        if current_len < 10:
            return 0.6  # Very short output is suspicious

        return 0.0  # Normal length

    # -------------------------------------------------------------------------
    # Pattern Detection
    # -------------------------------------------------------------------------

    def _detect_patterns(
        self,
        issues: list[dict],
        output: str,
        history: list[InspectionResult],
    ) -> list[IssuePattern]:
        """Detect cross-step patterns from issues and history."""
        patterns = []
        recent = history[-self.CASCADE_WINDOW :] if history else []

        # 1. Repeated errors
        if issues:
            current_types = [i.get("issue_type", "unknown") for i in issues]
            for ctype in current_types:
                past_count = sum(1 for r in recent for _ in range(1) if ctype in r.issue_summary)
                if past_count >= self.REPEAT_THRESHOLD - 1:
                    patterns.append(IssuePattern.REPEATED_ERROR)
                    break

        # 2. Escalating severity
        if len(recent) >= 2:
            recent_scores = [r.risk_score for r in recent]
            if (
                all(recent_scores[i] < recent_scores[i + 1] for i in range(len(recent_scores) - 1))
                and len(recent_scores) >= 3
            ):
                patterns.append(IssuePattern.ESCALATING_SEVERITY)

        # 3. Cascading failure
        if len(recent) >= 3:
            high_risk_streak = sum(1 for r in recent[-3:] if r.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL))
            if high_risk_streak >= 3:
                patterns.append(IssuePattern.CASCADING_FAILURE)

        # 4. Hallucination cluster
        hallucination_count = sum(1 for p in _HALLUCINATION_RE if p.search(output))
        if hallucination_count >= 2:
            patterns.append(IssuePattern.HALLUCINATION_CLUSTER)

        # 5. Output degradation
        if len(recent) >= 3:
            [len(r.step_name) for r in recent]  # proxy
            if all(r.risk_score > 0.3 for r in recent[-3:]):
                patterns.append(IssuePattern.OUTPUT_DEGRADATION)

        # 6. Stagnation
        stagnation_hits = sum(1 for p in _STAGNATION_RE if p.search(output))
        if stagnation_hits >= 2:
            patterns.append(IssuePattern.STAGNATION)

        return patterns

    # -------------------------------------------------------------------------
    # Suggestions & Summary
    # -------------------------------------------------------------------------

    def _generate_suggestions(self, patterns: list[IssuePattern], risk_score: float) -> list[str]:
        """Generate actionable suggestions based on detected patterns."""
        suggestions = []

        if IssuePattern.CASCADING_FAILURE in patterns:
            suggestions.append(
                "Cascading failures detected — consider resetting execution context and retrying from a clean state"
            )
        if IssuePattern.REPEATED_ERROR in patterns:
            suggestions.append(
                "Repeated error type — check if the root cause was addressed in previous correction attempts"
            )
        if IssuePattern.HALLUCINATION_CLUSTER in patterns:
            suggestions.append("Multiple hallucination indicators — verify tool outputs against actual system state")
        if IssuePattern.ESCALATING_SEVERITY in patterns:
            suggestions.append("Issue severity is escalating — early diagnosis recommended before further degradation")
        if IssuePattern.STAGNATION in patterns:
            suggestions.append("No meaningful progress detected — consider alternative approach or task decomposition")
        if IssuePattern.OUTPUT_DEGRADATION in patterns:
            suggestions.append("Output quality declining — may indicate context pollution or agent fatigue")

        if risk_score >= 0.8 and not suggestions:
            suggestions.append("High risk score without clear pattern — manual review recommended")

        return suggestions

    def _summarize_issues(
        self,
        issues: list[dict],
        hallucination_score: float,
        error_score: float,
        patterns: list[IssuePattern],
    ) -> str:
        """Generate a concise issue summary."""
        parts = []

        if issues:
            types = Counter(i.get("issue_type", "unknown") for i in issues)
            parts.append(f"{len(issues)} issue(s): " + ", ".join(f"{t}({c})" for t, c in types.most_common(3)))

        if hallucination_score > 0.3:
            parts.append(f"hallucination signals ({hallucination_score:.1f})")

        if error_score > 0.3:
            parts.append(f"error signals ({error_score:.1f})")

        if patterns:
            parts.append("patterns: " + ", ".join(p.value for p in patterns))

        return "; ".join(parts) if parts else "No issues detected"


# =============================================================================
# Singleton
# =============================================================================

_instance: InspectorGuard | None = None
_instance_lock = threading.Lock()


def get_inspector_guard() -> InspectorGuard:
    """Get or create the singleton InspectorGuard instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = InspectorGuard()
    return _instance


def reset_inspector_guard() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
