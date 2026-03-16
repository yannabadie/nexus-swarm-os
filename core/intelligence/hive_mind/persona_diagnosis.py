"""
NEXUS V12.4 - Multi-Persona Failure Diagnosis

Enhances Phase 5 diagnosis by analyzing failures from multiple expert perspectives.
Based on:
- MAR Multi-Agent Reflexion (arxiv:2512.20845): Cross-agent persona diversity
- MARS Metacognitive Reflection (arxiv:2601.11974): Failure taxonomy + typed enhancement

Instead of a single diagnosis prompt, failures are analyzed through specialized
personas (Architect, Debugger, Security Reviewer, Performance Analyst) that each
bring a different lens. A final synthesis merges persona findings into a unified
diagnosis with richer root cause coverage.

Usage:
    diagnoser = MultiPersonaDiagnoser()
    result = diagnoser.analyze(
        failure_context="Step 3 failed: timeout after 30s",
        gemini_diagnosis="Timeout due to large input",
        claude_diagnosis="API rate limit hit",
    )
    # result.persona_insights has per-persona analysis
    # result.synthesis merges all perspectives
"""

import logging
import threading
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PersonaType(str, Enum):
    """Expert personas for multi-angle diagnosis."""

    ARCHITECT = "architect"
    DEBUGGER = "debugger"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class PersonaLens:
    """A persona's analysis lens with prompt guidance."""

    persona: PersonaType
    name: str
    focus: str
    prompt_prefix: str
    weight: float = 1.0  # Importance weight for synthesis


# Pre-defined persona lenses
PERSONA_LENSES: dict[PersonaType, PersonaLens] = {
    PersonaType.ARCHITECT: PersonaLens(
        persona=PersonaType.ARCHITECT,
        name="System Architect",
        focus="structural and design issues",
        prompt_prefix=(
            "As a System Architect, analyze this failure from a STRUCTURAL perspective. "
            "Focus on: design flaws, missing abstractions, incorrect component interactions, "
            "architectural anti-patterns, and whether the execution plan was fundamentally sound."
        ),
        weight=1.2,
    ),
    PersonaType.DEBUGGER: PersonaLens(
        persona=PersonaType.DEBUGGER,
        name="Expert Debugger",
        focus="runtime errors and logic bugs",
        prompt_prefix=(
            "As an Expert Debugger, analyze this failure from a RUNTIME perspective. "
            "Focus on: stack traces, error propagation, edge cases, incorrect assumptions, "
            "off-by-one errors, null references, and state corruption."
        ),
        weight=1.0,
    ),
    PersonaType.SECURITY: PersonaLens(
        persona=PersonaType.SECURITY,
        name="Security Reviewer",
        focus="security vulnerabilities and trust issues",
        prompt_prefix=(
            "As a Security Reviewer, analyze this failure from a SECURITY perspective. "
            "Focus on: input validation failures, injection risks, privilege escalation, "
            "data exposure, hallucination-based vulnerabilities, and prompt injection."
        ),
        weight=0.8,
    ),
    PersonaType.PERFORMANCE: PersonaLens(
        persona=PersonaType.PERFORMANCE,
        name="Performance Analyst",
        focus="resource usage and efficiency",
        prompt_prefix=(
            "As a Performance Analyst, analyze this failure from a RESOURCE perspective. "
            "Focus on: timeouts, memory pressure, token budget overruns, unnecessary "
            "API calls, context bloat, and optimization opportunities."
        ),
        weight=0.9,
    ),
}


@dataclass
class PersonaInsight:
    """Analysis from a single persona."""

    persona: PersonaType
    root_cause_hypothesis: str
    contributing_factors: list[str]
    recommended_changes: list[str]
    confidence: float
    missed_by_others: str | None = None  # Unique insight this persona caught


@dataclass
class MultiPersonaResult:
    """Combined result from multi-persona analysis."""

    persona_insights: list[PersonaInsight]
    synthesis: str
    primary_root_cause: str
    all_contributing_factors: list[str]
    all_recommended_changes: list[str]
    confidence: float
    consensus_level: float  # How much personas agree (0-1)

    def get_unique_insights(self) -> list[str]:
        """Get insights that were unique to specific personas."""
        return [f"[{i.persona.value}] {i.missed_by_others}" for i in self.persona_insights if i.missed_by_others]


class MultiPersonaDiagnoser:
    """
    Analyzes failures from multiple expert perspectives.

    Takes the raw failure context plus existing agent diagnoses and
    generates per-persona analyses, then synthesizes into a unified
    multi-perspective diagnosis.
    """

    def __init__(
        self,
        personas: list[PersonaType] | None = None,
    ):
        self._personas = personas or list(PersonaType)
        self._results: list[MultiPersonaResult] = []

    def analyze(
        self,
        failure_context: str,
        gemini_diagnosis: str,
        claude_diagnosis: str,
        failure_type: str = "unknown",
    ) -> MultiPersonaResult:
        """
        Run multi-persona analysis on a failure.

        This is a synchronous analysis that examines the existing diagnoses
        through different persona lenses without additional LLM calls.
        Each persona highlights aspects the others might miss.

        Args:
            failure_context: Description of what failed and how
            gemini_diagnosis: Gemini's raw diagnosis text
            claude_diagnosis: Claude's raw diagnosis text
            failure_type: Classified failure type

        Returns:
            MultiPersonaResult with per-persona insights and synthesis
        """
        insights = []
        for persona_type in self._personas:
            lens = PERSONA_LENSES[persona_type]
            insight = self._analyze_with_persona(
                lens, failure_context, gemini_diagnosis, claude_diagnosis, failure_type
            )
            insights.append(insight)

        result = self._synthesize(insights, failure_context)
        self._results.append(result)
        return result

    def _analyze_with_persona(
        self,
        lens: PersonaLens,
        failure_context: str,
        gemini_diagnosis: str,
        claude_diagnosis: str,
        failure_type: str,
    ) -> PersonaInsight:
        """Generate a persona-specific analysis from existing diagnoses."""
        context_lower = failure_context.lower()
        gemini_lower = str(gemini_diagnosis).lower()
        claude_lower = str(claude_diagnosis).lower()
        combined = context_lower + " " + gemini_lower + " " + claude_lower

        factors = []
        changes = []
        hypothesis = ""
        unique_insight = None
        confidence = 0.5

        if lens.persona == PersonaType.ARCHITECT:
            hypothesis, factors, changes, unique_insight, confidence = self._architect_analysis(combined, failure_type)

        elif lens.persona == PersonaType.DEBUGGER:
            hypothesis, factors, changes, unique_insight, confidence = self._debugger_analysis(combined, failure_type)

        elif lens.persona == PersonaType.SECURITY:
            hypothesis, factors, changes, unique_insight, confidence = self._security_analysis(combined, failure_type)

        elif lens.persona == PersonaType.PERFORMANCE:
            hypothesis, factors, changes, unique_insight, confidence = self._performance_analysis(
                combined, failure_type
            )

        return PersonaInsight(
            persona=lens.persona,
            root_cause_hypothesis=hypothesis or f"Failure type: {failure_type}",
            contributing_factors=factors,
            recommended_changes=changes,
            confidence=confidence,
            missed_by_others=unique_insight,
        )

    def _architect_analysis(self, combined: str, failure_type: str):
        """Architect persona focuses on structural issues."""
        factors = []
        changes = []
        unique = None
        hypothesis = "Possible structural design issue"
        confidence = 0.5

        if "strategy_wrong" in failure_type or "strategy" in combined:
            hypothesis = "Execution strategy was architecturally unsound"
            factors.append("Incorrect task decomposition")
            changes.append("Re-analyze task structure before retrying")
            confidence = 0.7

        if any(w in combined for w in ["dependency", "depends", "order", "sequence"]):
            factors.append("Dependency ordering may be incorrect")
            changes.append("Verify step dependency graph")
            unique = "Dependency ordering issue detected"

        if any(w in combined for w in ["component", "module", "integration"]):
            factors.append("Component integration failure")
            changes.append("Check inter-component contracts")
            confidence = max(confidence, 0.6)

        if any(w in combined for w in ["missing", "not found", "undefined"]):
            factors.append("Missing component or capability")
            changes.append("Verify all required components are available")

        if not factors:
            factors.append("No obvious structural issues detected")

        return hypothesis, factors, changes, unique, confidence

    def _debugger_analysis(self, combined: str, failure_type: str):
        """Debugger persona focuses on runtime errors."""
        factors = []
        changes = []
        unique = None
        hypothesis = "Runtime execution error"
        confidence = 0.5

        if any(w in combined for w in ["error", "exception", "traceback", "stack"]):
            hypothesis = "Unhandled runtime exception"
            factors.append("Exception not properly caught or handled")
            changes.append("Add targeted error handling for the failure point")
            confidence = 0.7

        if any(w in combined for w in ["null", "none", "undefined", "missing key"]):
            factors.append("Null/None reference in data path")
            changes.append("Add null checks at data boundaries")
            unique = "Potential null reference in execution path"

        if any(w in combined for w in ["type", "cast", "conversion", "format"]):
            factors.append("Type mismatch or conversion error")
            changes.append("Validate data types before operations")

        if any(w in combined for w in ["state", "stale", "corrupt", "inconsistent"]):
            factors.append("Corrupted or inconsistent state")
            changes.append("Reset state before retry")
            confidence = max(confidence, 0.6)

        if not factors:
            factors.append("No obvious runtime errors detected")

        return hypothesis, factors, changes, unique, confidence

    def _security_analysis(self, combined: str, failure_type: str):
        """Security persona focuses on safety issues."""
        factors = []
        changes = []
        unique = None
        hypothesis = "No security-specific concerns"
        confidence = 0.4

        if "hallucination" in failure_type or any(w in combined for w in ["hallucin", "fabricat", "incorrect fact"]):
            hypothesis = "Hallucination-based failure compromises output integrity"
            factors.append("LLM generated incorrect information")
            changes.append("Add fact verification step before acting on LLM output")
            unique = "Hallucination risk - verify all LLM outputs before execution"
            confidence = 0.8

        if any(w in combined for w in ["inject", "prompt", "escape", "bypass"]):
            factors.append("Possible prompt injection or input manipulation")
            changes.append("Sanitize inputs before passing to LLM")
            confidence = max(confidence, 0.7)

        if any(w in combined for w in ["permission", "access", "denied", "forbidden", "auth"]):
            factors.append("Permission or access control issue")
            changes.append("Verify execution permissions before retry")

        if any(w in combined for w in ["sensitive", "secret", "credential", "token", "key"]):
            factors.append("Potential sensitive data exposure risk")
            changes.append("Ensure sensitive data is not logged or exposed")
            unique = "Sensitive data handling concern in failure context"

        if not factors:
            factors.append("No security-specific concerns identified")

        return hypothesis, factors, changes, unique, confidence

    def _performance_analysis(self, combined: str, failure_type: str):
        """Performance persona focuses on resource issues."""
        factors = []
        changes = []
        unique = None
        hypothesis = "Resource or efficiency issue"
        confidence = 0.5

        if "timeout" in failure_type or any(w in combined for w in ["timeout", "timed out", "slow", "latency"]):
            hypothesis = "Operation exceeded time budget"
            factors.append("Execution took longer than expected")
            changes.append("Increase timeout or break into smaller steps")
            confidence = 0.8

        if "budget" in failure_type or any(w in combined for w in ["budget", "token", "cost", "expensive"]):
            factors.append("Token or cost budget overrun")
            changes.append("Reduce prompt size or use more efficient model")
            unique = "Budget pressure detected - consider model downgrade for non-critical steps"
            confidence = max(confidence, 0.7)

        if any(w in combined for w in ["memory", "oom", "overflow", "large", "bloat"]):
            factors.append("Memory or context size pressure")
            changes.append("Compress context before retry")

        if any(w in combined for w in ["retry", "repeated", "loop", "stuck"]):
            factors.append("Repeated failed attempts waste resources")
            changes.append("Try alternative approach instead of retrying same strategy")
            unique = "Retry loop detected - switch strategy rather than retry"

        if not factors:
            factors.append("No performance-specific concerns detected")

        return hypothesis, factors, changes, unique, confidence

    def _synthesize(
        self,
        insights: list[PersonaInsight],
        failure_context: str,
    ) -> MultiPersonaResult:
        """Synthesize persona insights into unified diagnosis."""
        # Collect all unique factors and changes
        all_factors = []
        all_changes = []
        seen_factors = set()
        seen_changes = set()

        # Weight by persona importance and confidence
        weighted_hypotheses = []
        for insight in insights:
            lens = PERSONA_LENSES[insight.persona]
            weight = lens.weight * insight.confidence

            for f in insight.contributing_factors:
                if f not in seen_factors and "no " not in f.lower()[:5]:
                    all_factors.append(f)
                    seen_factors.add(f)

            for c in insight.recommended_changes:
                if c not in seen_changes:
                    all_changes.append(c)
                    seen_changes.add(c)

            weighted_hypotheses.append((weight, insight.root_cause_hypothesis))

        # Primary root cause = highest weighted hypothesis
        weighted_hypotheses.sort(key=lambda x: x[0], reverse=True)
        primary_root_cause = weighted_hypotheses[0][1] if weighted_hypotheses else "Unknown"

        # Confidence = weighted average
        total_weight = sum(PERSONA_LENSES[i.persona].weight for i in insights)
        avg_confidence = (
            sum(PERSONA_LENSES[i.persona].weight * i.confidence for i in insights) / total_weight
            if total_weight > 0
            else 0.5
        )

        # Consensus = how similar are the hypotheses (simple: fraction with same type)
        hypothesis_types = [i.root_cause_hypothesis for i in insights]
        unique_hypotheses = len(set(hypothesis_types))
        consensus = 1.0 - (unique_hypotheses - 1) / max(len(hypothesis_types), 1)

        synthesis = (
            f"Multi-persona analysis ({len(insights)} perspectives): "
            f"Primary cause: {primary_root_cause}. "
            f"Consensus: {consensus:.0%}. "
            f"Contributing factors: {len(all_factors)}. "
            f"Recommended changes: {len(all_changes)}."
        )

        return MultiPersonaResult(
            persona_insights=insights,
            synthesis=synthesis,
            primary_root_cause=primary_root_cause,
            all_contributing_factors=all_factors,
            all_recommended_changes=all_changes,
            confidence=avg_confidence,
            consensus_level=consensus,
        )

    def get_last_result(self) -> MultiPersonaResult | None:
        """Get the most recent analysis result."""
        return self._results[-1] if self._results else None

    def get_stats(self) -> dict:
        """Get diagnoser statistics."""
        return {
            "analyses_run": len(self._results),
            "personas_active": len(self._personas),
            "avg_confidence": (sum(r.confidence for r in self._results) / len(self._results) if self._results else 0.0),
            "avg_consensus": (
                sum(r.consensus_level for r in self._results) / len(self._results) if self._results else 0.0
            ),
        }

    def reset(self) -> None:
        """Reset diagnoser state."""
        self._results.clear()


# Module-level singleton
_diagnoser: MultiPersonaDiagnoser | None = None
_diagnoser_lock = threading.Lock()


def get_persona_diagnoser() -> MultiPersonaDiagnoser:
    """Get or create the global MultiPersonaDiagnoser instance."""
    global _diagnoser
    if _diagnoser is None:
        with _diagnoser_lock:
            if _diagnoser is None:
                _diagnoser = MultiPersonaDiagnoser()
    return _diagnoser


def reset_persona_diagnoser() -> None:
    """Reset the global MultiPersonaDiagnoser instance."""
    global _diagnoser
    _diagnoser = None
