"""
Prompt Template Optimizer - Analyze and improve prompt effectiveness.

V12.4 COGNITIVE BOOST - Task #52

Analyzes system prompts for inefficiencies, detects conflicts between
instructions, measures prompt efficacy, and tracks performance metrics
per prompt template.

Usage:
    from core.memory_pkg.prompts.template_optimizer import PromptOptimizer

    optimizer = PromptOptimizer()

    # Analyze a prompt
    analysis = optimizer.analyze("You are a helpful assistant...")

    # Record outcome for tracking
    optimizer.record_outcome("system_claude_v7", success=True, quality=0.9)

    # Get performance stats
    stats = optimizer.get_stats("system_claude_v7")

    # Detect conflicts between instructions
    conflicts = optimizer.detect_conflicts([
        "Always respond in JSON",
        "Use natural language for responses",
    ])
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_OUTCOMES = 1000
LEARNING_RATE = 0.15  # EMA learning rate for efficacy tracking

# Known anti-patterns in prompts
ANTI_PATTERNS = [
    (r"\bplease\b", "Politeness markers add tokens without improving output"),
    (r"(?:^|\n)\s*\n\s*\n\s*\n", "Excessive blank lines waste tokens"),
    (r"\b(very|really|extremely|absolutely)\b", "Intensifiers rarely improve instruction following"),
    (r"(?:do not|don't).*(?:do not|don't)", "Multiple negations can confuse models"),
]

# Conflict patterns (pairs of contradictory instructions)
CONFLICT_PAIRS = [
    (r"\bjson\b.*\bformat\b", r"\bnatural language\b"),
    (r"\bbrief\b|\bconcise\b|\bshort\b", r"\bdetailed\b|\bcomprehensive\b|\bthorough\b"),
    (r"\balways\b", r"\bnever\b"),
    (r"\bformal\b", r"\bcasual\b|\binformal\b"),
]


# =============================================================================
# Types
# =============================================================================


@dataclass
class PromptIssue:
    """An identified issue in a prompt."""

    severity: str  # "info", "warning", "error"
    category: str  # "redundancy", "conflict", "anti_pattern", "length"
    message: str
    line: int = 0
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "line": self.line,
            "suggestion": self.suggestion,
        }


@dataclass
class PromptAnalysis:
    """Analysis result for a prompt."""

    char_count: int
    word_count: int
    line_count: int
    estimated_tokens: int
    issues: list[PromptIssue] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_count": self.char_count,
            "word_count": self.word_count,
            "line_count": self.line_count,
            "estimated_tokens": self.estimated_tokens,
            "issue_count": self.issue_count,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "issues": [i.to_dict() for i in self.issues],
            "sections": self.sections,
        }


@dataclass
class PromptOutcome:
    """A recorded outcome for a prompt template."""

    template_name: str
    success: bool
    quality: float = 0.0  # 0.0 to 1.0
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()


@dataclass
class PromptStats:
    """Performance statistics for a prompt template."""

    template_name: str
    total_uses: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_quality: float = 0.0
    efficacy: float = 0.5  # EMA of success rate

    @property
    def success_rate(self) -> float:
        if self.total_uses == 0:
            return 0.0
        return self.success_count / self.total_uses

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_name": self.template_name,
            "total_uses": self.total_uses,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 4),
            "avg_quality": round(self.avg_quality, 4),
            "efficacy": round(self.efficacy, 4),
        }


@dataclass
class ConflictResult:
    """Result of conflict detection."""

    has_conflicts: bool
    conflicts: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_conflicts": self.has_conflicts,
            "conflict_count": len(self.conflicts),
            "conflicts": self.conflicts,
        }


# =============================================================================
# Prompt Optimizer
# =============================================================================


class PromptOptimizer:
    """
    Analyzes prompts and tracks their effectiveness.

    Features:
    - Static analysis for anti-patterns and redundancy
    - Conflict detection between instructions
    - Outcome tracking with EMA efficacy scoring
    - Section detection and token estimation
    - Performance statistics per template
    """

    def __init__(
        self,
        *,
        max_outcomes: int = MAX_OUTCOMES,
        learning_rate: float = LEARNING_RATE,
    ):
        self._outcomes: dict[str, deque[PromptOutcome]] = defaultdict(lambda: deque(maxlen=max_outcomes))
        self._stats: dict[str, PromptStats] = {}
        self._learning_rate = learning_rate
        self._lock = threading.Lock()

    # =========================================================================
    # Analysis
    # =========================================================================

    def analyze(self, prompt: str) -> PromptAnalysis:
        """
        Analyze a prompt for issues and metrics.

        Args:
            prompt: The prompt text to analyze

        Returns:
            PromptAnalysis with metrics and identified issues
        """
        lines = prompt.split("\n")
        words = prompt.split()

        analysis = PromptAnalysis(
            char_count=len(prompt),
            word_count=len(words),
            line_count=len(lines),
            estimated_tokens=self._estimate_tokens(prompt),
            sections=self._detect_sections(prompt),
        )

        # Check anti-patterns
        for pattern, message in ANTI_PATTERNS:
            matches = list(re.finditer(pattern, prompt, re.IGNORECASE | re.MULTILINE))
            if matches:
                # Find line number of first match
                line_num = prompt[: matches[0].start()].count("\n") + 1
                analysis.issues.append(
                    PromptIssue(
                        severity="info",
                        category="anti_pattern",
                        message=f"{message} (found {len(matches)} instance(s))",
                        line=line_num,
                    )
                )

        # Check for very long prompts
        if analysis.estimated_tokens > 4000:
            analysis.issues.append(
                PromptIssue(
                    severity="warning",
                    category="length",
                    message=f"Prompt is very long ({analysis.estimated_tokens} est. tokens). Consider trimming.",
                    suggestion="Remove redundant examples or consolidate instructions.",
                )
            )

        # Check for duplicate lines
        seen_lines = set()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped and len(stripped) > 20:
                if stripped in seen_lines:
                    analysis.issues.append(
                        PromptIssue(
                            severity="warning",
                            category="redundancy",
                            message="Duplicate line detected",
                            line=i,
                            suggestion="Remove duplicate instruction.",
                        )
                    )
                seen_lines.add(stripped)

        # Check for empty prompt
        if not prompt.strip():
            analysis.issues.append(
                PromptIssue(
                    severity="error",
                    category="empty",
                    message="Prompt is empty",
                )
            )

        return analysis

    # =========================================================================
    # Conflict Detection
    # =========================================================================

    def detect_conflicts(self, instructions: list[str]) -> ConflictResult:
        """
        Detect potentially conflicting instructions.

        Args:
            instructions: List of instruction strings

        Returns:
            ConflictResult with identified conflicts
        """
        conflicts = []
        full_text = " ".join(instructions)

        for pattern_a, pattern_b in CONFLICT_PAIRS:
            match_a = re.search(pattern_a, full_text, re.IGNORECASE)
            match_b = re.search(pattern_b, full_text, re.IGNORECASE)
            if match_a and match_b:
                conflicts.append(
                    {
                        "instruction_a": match_a.group(),
                        "instruction_b": match_b.group(),
                        "type": "contradictory",
                    }
                )

        return ConflictResult(
            has_conflicts=len(conflicts) > 0,
            conflicts=conflicts,
        )

    # =========================================================================
    # Outcome Tracking
    # =========================================================================

    def record_outcome(
        self,
        template_name: str,
        *,
        success: bool,
        quality: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record an outcome for a prompt template.

        Args:
            template_name: Template identifier
            success: Whether the prompt produced a good result
            quality: Quality score (0.0 to 1.0)
            metadata: Optional metadata
        """
        outcome = PromptOutcome(
            template_name=template_name,
            success=success,
            quality=max(0.0, min(1.0, quality)),
            metadata=metadata or {},
        )

        with self._lock:
            self._outcomes[template_name].append(outcome)
            self._update_stats(template_name, success, quality)

    def _update_stats(self, name: str, success: bool, quality: float) -> None:
        """Update running statistics for a template."""
        if name not in self._stats:
            self._stats[name] = PromptStats(template_name=name)
        stats = self._stats[name]
        stats.total_uses += 1
        if success:
            stats.success_count += 1
        else:
            stats.failure_count += 1

        # EMA for efficacy
        outcome_val = 1.0 if success else 0.0
        stats.efficacy = (1 - self._learning_rate) * stats.efficacy + self._learning_rate * outcome_val

        # Running average quality
        if quality > 0:
            if stats.avg_quality == 0:
                stats.avg_quality = quality
            else:
                stats.avg_quality = (1 - self._learning_rate) * stats.avg_quality + self._learning_rate * quality

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self, template_name: str) -> PromptStats | None:
        """Get performance stats for a template."""
        with self._lock:
            return self._stats.get(template_name)

    def get_all_stats(self) -> list[PromptStats]:
        """Get stats for all tracked templates."""
        with self._lock:
            return sorted(self._stats.values(), key=lambda s: s.template_name)

    def get_top_templates(self, *, limit: int = 10) -> list[PromptStats]:
        """Get the best performing templates by efficacy."""
        with self._lock:
            stats_list = list(self._stats.values())
        stats_list.sort(key=lambda s: s.efficacy, reverse=True)
        return stats_list[:limit]

    def get_worst_templates(self, *, limit: int = 10) -> list[PromptStats]:
        """Get the worst performing templates by efficacy."""
        with self._lock:
            stats_list = [s for s in self._stats.values() if s.total_uses >= 3]
        stats_list.sort(key=lambda s: s.efficacy)
        return stats_list[:limit]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (words * 1.3)."""
        word_count = len(text.split())
        return int(word_count * 1.3)

    @staticmethod
    def _detect_sections(text: str) -> list[str]:
        """Detect markdown-style sections in a prompt."""
        sections = []
        for line in text.split("\n"):
            stripped = line.strip()
            # Markdown headers
            if stripped.startswith("#"):
                header = stripped.lstrip("#").strip()
                if header:
                    sections.append(header)
            # ALL CAPS SECTIONS (common in system prompts)
            elif stripped.isupper() and len(stripped) > 3 and " " in stripped:
                sections.append(stripped)
        return sections

    # =========================================================================
    # State
    # =========================================================================

    @property
    def template_count(self) -> int:
        return len(self._stats)

    @property
    def total_outcomes(self) -> int:
        return sum(len(q) for q in self._outcomes.values())

    def clear(self) -> None:
        """Clear all tracked data."""
        with self._lock:
            self._outcomes.clear()
            self._stats.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_count": self.template_count,
            "total_outcomes": self.total_outcomes,
            "templates": {name: stats.to_dict() for name, stats in sorted(self._stats.items())},
        }


# =============================================================================
# Global Instance
# =============================================================================

_optimizer: PromptOptimizer | None = None
_optimizer_lock = threading.Lock()


def get_optimizer() -> PromptOptimizer:
    """Get or create the global prompt optimizer."""
    global _optimizer
    if _optimizer is None:
        with _optimizer_lock:
            if _optimizer is None:
                _optimizer = PromptOptimizer()
    return _optimizer


def reset_optimizer() -> None:
    """Reset the global optimizer (for testing)."""
    global _optimizer
    _optimizer = None
