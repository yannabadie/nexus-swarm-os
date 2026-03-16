"""
V12.4 COGNITIVE BOOST: Multi-Agent Reflexion (arXiv:2512.20845)

Cross-agent reflection after failures to break the "degeneration of thought"
problem where a single LLM repeats the same errors despite knowing they are
wrong. Multiple persona-agents provide diverse correction signals.

Key insight: Single-agent reflexion degenerates because the same model produces
the same biased reflection. Cross-agent reflexion breaks this by having agents
with different perspectives reflect independently, then synthesizing.

Three reflection modes:
1. Independent: Each agent reflects separately, merge insights
2. Adversarial: Agents challenge each other's diagnoses
3. Constructive: Agents build on each other's insights

Reference: "MAR: Multi-Agent Reflexion Improves Reasoning Abilities in LLMs"
(arXiv:2512.20845)
"""

from __future__ import annotations

import hashlib
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


class ReflexionMode(str, Enum):
    """Mode of cross-agent reflection."""

    INDEPENDENT = "independent"  # Agents reflect separately
    ADVERSARIAL = "adversarial"  # Agents challenge each other
    CONSTRUCTIVE = "constructive"  # Agents build on each other


@dataclass
class AgentReflection:
    """Single agent's reflection on a failure."""

    agent_id: str
    root_cause: str
    evidence: list[str] = field(default_factory=list)
    proposed_fix: str = ""
    confidence: float = 0.5
    novel_insight: bool = False  # Whether this adds new info
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "root_cause": self.root_cause[:200],
            "evidence_count": len(self.evidence),
            "proposed_fix": self.proposed_fix[:200],
            "confidence": round(self.confidence, 3),
            "novel_insight": self.novel_insight,
        }


@dataclass
class ReflexionSynthesis:
    """Synthesized multi-agent reflection."""

    consensus_cause: str
    consensus_evidence: list[str]
    diverse_insights: list[str]  # Unique insights from different agents
    proposed_strategy: str
    agreement_level: float  # 0-1: how much agents agreed
    degeneration_detected: bool = False  # True if repeated failure pattern
    mode_used: ReflexionMode = ReflexionMode.INDEPENDENT
    reflection_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "consensus_cause": self.consensus_cause[:200],
            "evidence_count": len(self.consensus_evidence),
            "diverse_insights_count": len(self.diverse_insights),
            "agreement_level": round(self.agreement_level, 3),
            "degeneration_detected": self.degeneration_detected,
            "mode_used": self.mode_used.value,
        }


@dataclass
class ReflexionStats:
    """Aggregate statistics."""

    total_reflexions: int = 0
    degeneration_detections: int = 0
    avg_agreement: float = 0.0
    mode_counts: dict[str, int] = field(default_factory=dict)
    insight_counts: dict[str, int] = field(default_factory=dict)  # agent -> novel insights

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_reflexions": self.total_reflexions,
            "degeneration_detections": self.degeneration_detections,
            "avg_agreement": round(self.avg_agreement, 3),
            "mode_counts": dict(self.mode_counts),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Agreement threshold below which we flag degeneration
AGREEMENT_THRESHOLD: float = 0.3

# Maximum number of failure signatures to track for degeneration detection
MAX_FAILURE_HISTORY: int = 50

# Minimum reflections needed for synthesis
MIN_REFLECTIONS: int = 2

# Word overlap threshold for "same root cause" detection
CAUSE_SIMILARITY_THRESHOLD: float = 0.5

# When to switch to adversarial mode (consecutive same-cause failures)
ADVERSARIAL_TRIGGER: int = 2

# Weight for diverse vs consensus insights
DIVERSITY_WEIGHT: float = 0.4


# ---------------------------------------------------------------------------
# Core: MultiAgentReflexion
# ---------------------------------------------------------------------------


class MultiAgentReflexion:
    """
    MAR-inspired cross-agent reflection system.

    After a failure, each agent independently reflects on the root cause.
    Reflections are synthesized to break degeneration-of-thought loops
    and produce diverse correction signals.

    Usage:
        mar = MultiAgentReflexion()
        synthesis = mar.synthesize(
            reflections=[claude_reflection, gemini_reflection],
            failure_context="Auth token validation failed",
            attempt_number=2,
        )
    """

    def __init__(
        self,
        adversarial_trigger: int = ADVERSARIAL_TRIGGER,
        max_history: int = MAX_FAILURE_HISTORY,
    ) -> None:
        self._adversarial_trigger = adversarial_trigger
        self._max_history = max_history
        self._lock = threading.Lock()
        self._stats = ReflexionStats()
        self._failure_history: list[str] = []  # Fingerprints of past failure causes
        self._cause_history: list[tuple[str, str]] = []  # (task_fingerprint, cause)

    # -- public API --

    def synthesize(
        self,
        reflections: list[AgentReflection],
        failure_context: str = "",
        attempt_number: int = 1,
        force_mode: ReflexionMode | None = None,
    ) -> ReflexionSynthesis:
        """
        Synthesize multi-agent reflections into actionable insight.

        Args:
            reflections: List of independent agent reflections.
            failure_context: Description of the failure scenario.
            attempt_number: Which retry attempt this is (1-based).
            force_mode: Override automatic mode selection.

        Returns:
            ReflexionSynthesis with consensus and diverse insights.
        """
        if not reflections:
            return ReflexionSynthesis(
                consensus_cause="No reflections provided",
                consensus_evidence=[],
                diverse_insights=[],
                proposed_strategy="Retry with default approach",
                agreement_level=0.0,
                reflection_count=0,
            )

        # Select reflexion mode
        mode = force_mode or self._select_mode(failure_context, attempt_number)

        # Detect degeneration
        degeneration = self._detect_degeneration(reflections, failure_context)

        # Synthesize based on mode
        if mode == ReflexionMode.ADVERSARIAL:
            synthesis = self._adversarial_synthesis(reflections, degeneration)
        elif mode == ReflexionMode.CONSTRUCTIVE:
            synthesis = self._constructive_synthesis(reflections)
        else:
            synthesis = self._independent_synthesis(reflections)

        synthesis.degeneration_detected = degeneration
        synthesis.mode_used = mode
        synthesis.reflection_count = len(reflections)

        # If degeneration detected, force diverse strategy
        if degeneration:
            synthesis.proposed_strategy = self._generate_anti_degeneration_strategy(
                reflections, failure_context, attempt_number
            )

        # Record in history
        self._record_failure(failure_context, synthesis.consensus_cause)

        # Update stats
        with self._lock:
            self._stats.total_reflexions += 1
            if degeneration:
                self._stats.degeneration_detections += 1
            mode_key = mode.value
            self._stats.mode_counts[mode_key] = self._stats.mode_counts.get(mode_key, 0) + 1
            n = self._stats.total_reflexions
            self._stats.avg_agreement = (self._stats.avg_agreement * (n - 1) + synthesis.agreement_level) / n
            for r in reflections:
                if r.novel_insight:
                    self._stats.insight_counts[r.agent_id] = self._stats.insight_counts.get(r.agent_id, 0) + 1

        logger.debug(
            "MAR synthesis: mode=%s, agreement=%.2f, degeneration=%s, insights=%d",
            mode.value,
            synthesis.agreement_level,
            degeneration,
            len(synthesis.diverse_insights),
        )

        return synthesis

    def create_reflection(
        self,
        agent_id: str,
        diagnosis_text: str,
        failure_context: str = "",
    ) -> AgentReflection:
        """
        Create a structured reflection from raw diagnosis text.

        Parses natural language diagnosis into structured fields.
        """
        # Extract root cause (first sentence or line)
        lines = [ln.strip() for ln in diagnosis_text.strip().split("\n") if ln.strip()]
        root_cause = lines[0] if lines else "Unknown"

        # Extract evidence (lines that look like bullet points or data)
        evidence = [ln for ln in lines[1:] if ln.startswith(("-", "*", ">>", "Error:", "File:", "Line:"))]

        # Extract fix (lines with "fix", "should", "need to", "try")
        fix_keywords = {"fix", "should", "need", "try", "instead", "correct", "change"}
        fix_lines = [ln for ln in lines if any(kw in ln.lower() for kw in fix_keywords)]
        proposed_fix = fix_lines[0] if fix_lines else ""

        # Estimate confidence from language certainty
        high_conf = {"clearly", "definitely", "certainly", "obvious", "sure"}
        low_conf = {"might", "maybe", "possibly", "unclear", "unsure", "could"}
        text_lower = diagnosis_text.lower()
        high_count = sum(1 for w in high_conf if w in text_lower)
        low_count = sum(1 for w in low_conf if w in text_lower)
        confidence = 0.5 + (high_count - low_count) * 0.1
        confidence = max(0.1, min(0.95, confidence))

        # Check novelty against history
        novel = self._is_novel_insight(root_cause)

        return AgentReflection(
            agent_id=agent_id,
            root_cause=root_cause,
            evidence=evidence,
            proposed_fix=proposed_fix,
            confidence=confidence,
            novel_insight=novel,
        )

    def get_stats(self) -> ReflexionStats:
        """Return aggregate statistics."""
        with self._lock:
            return ReflexionStats(
                total_reflexions=self._stats.total_reflexions,
                degeneration_detections=self._stats.degeneration_detections,
                avg_agreement=self._stats.avg_agreement,
                mode_counts=dict(self._stats.mode_counts),
                insight_counts=dict(self._stats.insight_counts),
            )

    def reset(self) -> None:
        """Reset state and statistics."""
        with self._lock:
            self._stats = ReflexionStats()
            self._failure_history.clear()
            self._cause_history.clear()

    # -- private helpers --

    def _select_mode(self, failure_context: str, attempt_number: int) -> ReflexionMode:
        """Select the reflexion mode based on context."""
        fp = self._fingerprint(failure_context)

        # Count consecutive same-context failures
        consecutive = 0
        for past_fp in reversed(self._failure_history):
            if past_fp == fp:
                consecutive += 1
            else:
                break

        if consecutive >= self._adversarial_trigger:
            return ReflexionMode.ADVERSARIAL
        elif attempt_number > 2:
            return ReflexionMode.CONSTRUCTIVE
        else:
            return ReflexionMode.INDEPENDENT

    def _detect_degeneration(
        self,
        reflections: list[AgentReflection],
        failure_context: str,
    ) -> bool:
        """
        Detect degeneration-of-thought: all agents producing the same
        (likely wrong) diagnosis repeatedly.
        """
        if len(reflections) < MIN_REFLECTIONS:
            return False

        # Check if all reflections have the same root cause
        causes = [r.root_cause.lower().strip() for r in reflections]
        unique_causes = set()
        for c in causes:
            # Normalize by taking first N words
            words = c.split()[:10]
            unique_causes.add(" ".join(words))

        # If all agents say the same thing...
        if len(unique_causes) <= 1:
            # ...and we've seen this cause before for this context
            fp = self._fingerprint(failure_context)
            past_causes = [cause for past_fp, cause in self._cause_history if past_fp == fp]
            if past_causes:
                # Check if new cause matches past causes
                current = list(unique_causes)[0] if unique_causes else ""
                for past in past_causes[-3:]:
                    if self._word_overlap(current, past) > CAUSE_SIMILARITY_THRESHOLD:
                        return True

        return False

    def _independent_synthesis(
        self,
        reflections: list[AgentReflection],
    ) -> ReflexionSynthesis:
        """Synthesize independent reflections by finding consensus and diversity."""
        if len(reflections) == 1:
            r = reflections[0]
            return ReflexionSynthesis(
                consensus_cause=r.root_cause,
                consensus_evidence=list(r.evidence),
                diverse_insights=[],
                proposed_strategy=r.proposed_fix or "Apply the identified fix.",
                agreement_level=1.0,
            )

        # Find consensus: shared words across root causes
        all_cause_words = [set(r.root_cause.lower().split()) for r in reflections]
        consensus_words = all_cause_words[0]
        for words in all_cause_words[1:]:
            consensus_words = consensus_words & words

        # Build consensus cause from highest-confidence reflection
        best_reflection = max(reflections, key=lambda r: r.confidence)
        consensus_cause = best_reflection.root_cause

        # Merge evidence
        all_evidence: list[str] = []
        seen_evidence: set[str] = set()
        for r in reflections:
            for e in r.evidence:
                normalized = e.lower().strip()
                if normalized not in seen_evidence:
                    seen_evidence.add(normalized)
                    all_evidence.append(e)

        # Find diverse insights (unique to each agent)
        diverse: list[str] = []
        for i, r in enumerate(reflections):
            other_words = set()
            for j, r2 in enumerate(reflections):
                if i != j:
                    other_words.update(r2.root_cause.lower().split())

            unique_words = set(r.root_cause.lower().split()) - other_words
            if unique_words and len(unique_words) > 2:
                diverse.append(f"[{r.agent_id}] {r.root_cause}")

        # Agreement level
        if not all_cause_words[0]:
            agreement = 0.5
        else:
            pairwise = []
            for i in range(len(all_cause_words)):
                for j in range(i + 1, len(all_cause_words)):
                    a, b = all_cause_words[i], all_cause_words[j]
                    if a or b:
                        pairwise.append(len(a & b) / len(a | b) if (a | b) else 0.0)
            agreement = sum(pairwise) / len(pairwise) if pairwise else 0.5

        # Strategy: combine fixes
        fixes = [r.proposed_fix for r in reflections if r.proposed_fix]
        strategy = fixes[0] if fixes else "Apply consensus diagnosis."
        if len(fixes) > 1:
            strategy = f"{fixes[0]} Additionally: {fixes[1]}"

        return ReflexionSynthesis(
            consensus_cause=consensus_cause,
            consensus_evidence=all_evidence[:10],
            diverse_insights=diverse,
            proposed_strategy=strategy,
            agreement_level=agreement,
        )

    def _adversarial_synthesis(
        self,
        reflections: list[AgentReflection],
        degeneration: bool,
    ) -> ReflexionSynthesis:
        """
        Adversarial synthesis: agents' diagnoses challenge each other.
        Used when degeneration is detected or after repeated failures.
        """
        synthesis = self._independent_synthesis(reflections)

        if degeneration:
            # Explicitly note the degeneration
            synthesis.diverse_insights.insert(
                0, "WARNING: Repeated same diagnosis detected — agents may be stuck in a loop."
            )
            # Prefer the minority opinion if any
            for r in reflections:
                if r.novel_insight:
                    synthesis.consensus_cause = f"ALTERNATIVE: {r.root_cause} (novel insight from {r.agent_id})"
                    break

        # Lower agreement to signal challenge needed
        synthesis.agreement_level = max(0.0, synthesis.agreement_level - 0.2)

        return synthesis

    def _constructive_synthesis(
        self,
        reflections: list[AgentReflection],
    ) -> ReflexionSynthesis:
        """
        Constructive synthesis: agents build on each other's insights.
        Used for later retry attempts where more creative solutions are needed.
        """
        synthesis = self._independent_synthesis(reflections)

        # Combine all evidence and insights more aggressively
        all_fixes = [r.proposed_fix for r in reflections if r.proposed_fix]
        if len(all_fixes) > 1:
            combined = " → ".join(all_fixes[:3])
            synthesis.proposed_strategy = f"Multi-step approach: {combined}"

        # Boost agreement slightly for constructive mode
        synthesis.agreement_level = min(1.0, synthesis.agreement_level + 0.1)

        return synthesis

    def _generate_anti_degeneration_strategy(
        self,
        reflections: list[AgentReflection],
        failure_context: str,
        attempt_number: int,
    ) -> str:
        """Generate a strategy specifically to break degeneration loops."""
        strategies = [
            "Try a completely different approach — the previous diagnosis may be wrong.",
            "Focus on side effects and edge cases, not the obvious root cause.",
            "Re-examine assumptions: what if the error symptom is misleading?",
            "Use a different tool or method to validate the diagnosis.",
            "Break the problem into smaller parts and test each independently.",
        ]

        # Rotate through strategies based on attempt
        idx = (attempt_number - 1) % len(strategies)
        base = strategies[idx]

        # Add novel insights if any
        novel = [r for r in reflections if r.novel_insight]
        if novel:
            base += f" Consider: {novel[0].root_cause}"

        return base

    def _record_failure(self, failure_context: str, cause: str) -> None:
        """Record a failure for degeneration tracking."""
        fp = self._fingerprint(failure_context)
        with self._lock:
            self._failure_history.append(fp)
            self._cause_history.append((fp, cause.lower()[:100]))
            if len(self._failure_history) > self._max_history:
                self._failure_history = self._failure_history[-self._max_history :]
            if len(self._cause_history) > self._max_history:
                self._cause_history = self._cause_history[-self._max_history :]

    def _is_novel_insight(self, root_cause: str) -> bool:
        """Check if this root cause is novel compared to history."""
        cause_lower = root_cause.lower()[:100]
        with self._lock:
            for _, past_cause in self._cause_history[-10:]:
                if self._word_overlap(cause_lower, past_cause) > CAUSE_SIMILARITY_THRESHOLD:
                    return False
        return True

    @staticmethod
    def _fingerprint(text: str) -> str:
        """Create a fingerprint for context matching."""
        normalized = " ".join(text.lower().split()[:30])
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()[:12]

    @staticmethod
    def _word_overlap(a: str, b: str) -> float:
        """Word overlap ratio."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / min(len(words_a), len(words_b))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: MultiAgentReflexion | None = None
_instance_lock = threading.Lock()


def get_multi_agent_reflexion() -> MultiAgentReflexion:
    """Get or create the global MultiAgentReflexion singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MultiAgentReflexion()
    return _instance


def reset_multi_agent_reflexion() -> None:
    """Reset the global MultiAgentReflexion singleton."""
    global _instance
    with _instance_lock:
        _instance = None
