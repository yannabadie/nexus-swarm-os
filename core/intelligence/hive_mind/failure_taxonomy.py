"""
NEXUS V12.4 - MAST Failure Taxonomy + MARS Triple-Pathway Reflection

Two complementary failure diagnosis enhancements:

1. MAST 14-Mode Taxonomy (arxiv:2503.13657):
   Structured classification of multi-agent failures across 3 categories.
   Maps NEXUS FailureType to fine-grained MAST codes for precise diagnosis.

2. MARS Triple-Pathway Reflection (arxiv:2601.11974):
   Metacognitive reflection generating structured fix instructions via:
   - Pathway 1: Principle extraction (what rules were violated)
   - Pathway 2: Procedural steps (what should have been done)
   - Pathway 3: Unified synthesis (actionable fix for retry)

Usage:
    classifier = MastClassifier()
    codes = classifier.classify(
        failure_context="Agent ignored other agent's analysis",
        failure_type="strategy_wrong",
    )
    # codes = [MastCode.IGNORED_INPUT, MastCode.PREMATURE_TERMINATION]

    reflector = TriplePathwayReflector()
    reflection = reflector.reflect(
        failure_context="Timeout after 60s",
        diagnosis="API call took too long",
        failure_type="timeout",
    )
    # reflection.principle = "Always set aggressive timeouts for external calls"
    # reflection.procedure = "1. Set 10s timeout. 2. Add retry with backoff."
    # reflection.synthesis = "Add 10s timeout with exponential backoff retry"
"""

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# MAST Failure Taxonomy (arxiv:2503.13657)
# =============================================================================


class MastCategory(str, Enum):
    """Top-level MAST failure categories."""

    SYSTEM_DESIGN = "system_design"
    INTER_AGENT = "inter_agent"
    TASK_VERIFICATION = "task_verification"


class MastCode(str, Enum):
    """
    14-mode MAST failure classification codes.

    System Design Issues (5):
    """

    # System Design Issues
    DISOBEY_TASK_SPEC = "disobey_task_spec"  # Agent doesn't follow task specification
    DISOBEY_ROLE_SPEC = "disobey_role_spec"  # Agent acts outside assigned role
    STEP_REPETITION = "step_repetition"  # Repeating the same step/action
    CONTEXT_LOSS = "context_loss"  # Lost conversation history
    UNAWARE_TERMINATION = "unaware_termination"  # Doesn't know when to stop

    # Inter-Agent Misalignment
    CONVERSATION_RESET = "conversation_reset"  # Agent starts over unexpectedly
    FAIL_CLARIFY = "fail_clarify"  # Doesn't ask for needed clarification
    TASK_DERAILMENT = "task_derailment"  # Goes off-track from original task
    INFORMATION_WITHHOLDING = "info_withholding"  # Agent withholds useful information
    IGNORED_INPUT = "ignored_input"  # Ignores other agent's input
    REASONING_ACTION_MISMATCH = "reasoning_mismatch"  # Says one thing, does another

    # Task Verification
    PREMATURE_TERMINATION = "premature_termination"  # Stops before task is complete
    NO_VERIFICATION = "no_verification"  # Doesn't verify the result
    INCORRECT_VERIFICATION = "incorrect_verification"  # Verifies but gets it wrong


# Category mapping
MAST_CATEGORIES: dict[MastCode, MastCategory] = {
    MastCode.DISOBEY_TASK_SPEC: MastCategory.SYSTEM_DESIGN,
    MastCode.DISOBEY_ROLE_SPEC: MastCategory.SYSTEM_DESIGN,
    MastCode.STEP_REPETITION: MastCategory.SYSTEM_DESIGN,
    MastCode.CONTEXT_LOSS: MastCategory.SYSTEM_DESIGN,
    MastCode.UNAWARE_TERMINATION: MastCategory.SYSTEM_DESIGN,
    MastCode.CONVERSATION_RESET: MastCategory.INTER_AGENT,
    MastCode.FAIL_CLARIFY: MastCategory.INTER_AGENT,
    MastCode.TASK_DERAILMENT: MastCategory.INTER_AGENT,
    MastCode.INFORMATION_WITHHOLDING: MastCategory.INTER_AGENT,
    MastCode.IGNORED_INPUT: MastCategory.INTER_AGENT,
    MastCode.REASONING_ACTION_MISMATCH: MastCategory.INTER_AGENT,
    MastCode.PREMATURE_TERMINATION: MastCategory.TASK_VERIFICATION,
    MastCode.NO_VERIFICATION: MastCategory.TASK_VERIFICATION,
    MastCode.INCORRECT_VERIFICATION: MastCategory.TASK_VERIFICATION,
}

# Keyword detection patterns for each MAST code
MAST_PATTERNS: dict[MastCode, list[str]] = {
    MastCode.DISOBEY_TASK_SPEC: ["wrong task", "not what was asked", "misunderstood", "off-spec"],
    MastCode.DISOBEY_ROLE_SPEC: ["wrong role", "not its job", "role violation", "unauthorized"],
    MastCode.STEP_REPETITION: ["repeated", "loop", "stuck", "same step", "again"],
    MastCode.CONTEXT_LOSS: ["lost context", "forgot", "no history", "amnesia", "context lost"],
    MastCode.UNAWARE_TERMINATION: ["didn't stop", "kept going", "no termination", "infinite"],
    MastCode.CONVERSATION_RESET: ["reset", "started over", "fresh start", "lost thread"],
    MastCode.FAIL_CLARIFY: ["unclear", "ambiguous", "should have asked", "assumed"],
    MastCode.TASK_DERAILMENT: ["off track", "derailed", "tangent", "unrelated"],
    MastCode.INFORMATION_WITHHOLDING: ["withheld", "didn't share", "hidden", "missing info"],
    MastCode.IGNORED_INPUT: ["ignored", "dismissed", "disregarded", "didn't use"],
    MastCode.REASONING_ACTION_MISMATCH: ["said but did", "mismatch", "inconsistent", "contradicted"],
    MastCode.PREMATURE_TERMINATION: ["too early", "incomplete", "premature", "partial"],
    MastCode.NO_VERIFICATION: ["no check", "unverified", "didn't validate", "skipped check"],
    MastCode.INCORRECT_VERIFICATION: ["wrong check", "false positive", "missed error", "bad validation"],
}

# FailureType to likely MAST codes mapping
FAILURE_TYPE_MAST_MAP: dict[str, list[MastCode]] = {
    "timeout": [MastCode.STEP_REPETITION, MastCode.UNAWARE_TERMINATION],
    "capability_missing": [MastCode.DISOBEY_ROLE_SPEC, MastCode.FAIL_CLARIFY],
    "hallucination": [MastCode.REASONING_ACTION_MISMATCH, MastCode.INCORRECT_VERIFICATION],
    "strategy_wrong": [MastCode.TASK_DERAILMENT, MastCode.DISOBEY_TASK_SPEC],
    "tool_error": [MastCode.NO_VERIFICATION, MastCode.DISOBEY_TASK_SPEC],
    "context_lost": [MastCode.CONTEXT_LOSS, MastCode.CONVERSATION_RESET],
    "budget_exceeded": [MastCode.STEP_REPETITION, MastCode.UNAWARE_TERMINATION],
    "memory_error": [MastCode.CONTEXT_LOSS, MastCode.INFORMATION_WITHHOLDING],
    "planning_error": [MastCode.TASK_DERAILMENT, MastCode.FAIL_CLARIFY],
    "unknown": [MastCode.NO_VERIFICATION],
}


@dataclass
class MastClassification:
    """Result of MAST classification."""

    codes: list[MastCode]
    primary_category: MastCategory
    confidence: float
    evidence: list[str]

    def get_categories(self) -> set[MastCategory]:
        return {MAST_CATEGORIES[code] for code in self.codes}

    def has_inter_agent_issues(self) -> bool:
        return MastCategory.INTER_AGENT in self.get_categories()

    def to_dict(self) -> dict:
        return {
            "codes": [c.value for c in self.codes],
            "primary_category": self.primary_category.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


class MastClassifier:
    """Classifies failures using the MAST 14-mode taxonomy."""

    def classify(
        self,
        failure_context: str,
        failure_type: str = "unknown",
        agent_diagnoses: list[str] | None = None,
    ) -> MastClassification:
        """
        Classify a failure into MAST codes.

        Args:
            failure_context: Description of the failure
            failure_type: NEXUS FailureType value
            agent_diagnoses: Optional agent diagnosis texts

        Returns:
            MastClassification with matched codes
        """
        combined = failure_context.lower()
        if agent_diagnoses:
            combined += " " + " ".join(str(d).lower() for d in agent_diagnoses)

        matched_codes: list[MastCode] = []
        evidence: list[str] = []

        # Pattern-based detection
        for code, patterns in MAST_PATTERNS.items():
            for pattern in patterns:
                if pattern in combined:
                    if code not in matched_codes:
                        matched_codes.append(code)
                        evidence.append(f"Pattern '{pattern}' matched for {code.value}")
                    break

        # FailureType-based mapping
        type_codes = FAILURE_TYPE_MAST_MAP.get(failure_type, [])
        for code in type_codes:
            if code not in matched_codes:
                matched_codes.append(code)
                evidence.append(f"FailureType '{failure_type}' maps to {code.value}")

        # Default fallback
        if not matched_codes:
            matched_codes = [MastCode.NO_VERIFICATION]
            evidence = ["No specific pattern matched; defaulting to no_verification"]

        # Determine primary category
        category_counts: dict[MastCategory, int] = {}
        for code in matched_codes:
            cat = MAST_CATEGORIES[code]
            category_counts[cat] = category_counts.get(cat, 0) + 1
        primary = max(category_counts, key=category_counts.get)

        # Confidence based on evidence strength
        confidence = min(1.0, len(evidence) * 0.25)

        return MastClassification(
            codes=matched_codes,
            primary_category=primary,
            confidence=confidence,
            evidence=evidence,
        )


# =============================================================================
# MARS Triple-Pathway Reflection (arxiv:2601.11974)
# =============================================================================


@dataclass
class TriplePathwayResult:
    """Result of MARS triple-pathway reflection."""

    principle: str  # What rule was violated
    procedure: str  # What steps should have been taken
    synthesis: str  # Unified actionable fix
    failure_type: str
    mast_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "principle": self.principle,
            "procedure": self.procedure,
            "synthesis": self.synthesis,
            "failure_type": self.failure_type,
            "mast_codes": self.mast_codes,
        }


class TriplePathwayReflector:
    """
    Generates structured fix instructions via three reflection pathways.

    Pathway 1 (Principle): Extracts normative rules for error avoidance
    Pathway 2 (Procedural): Derives step-by-step strategies
    Pathway 3 (Synthesis): Merges into a single actionable improvement
    """

    # Principle templates by failure type
    PRINCIPLE_MAP: dict[str, str] = {
        "timeout": "Always set explicit timeouts and implement progressive fallback strategies",
        "capability_missing": "Verify all required capabilities exist before starting execution",
        "hallucination": "Never trust LLM output without verification against ground truth",
        "strategy_wrong": "Validate strategy against task requirements before committing to execution",
        "tool_error": "Check tool availability and prerequisites before each tool invocation",
        "context_lost": "Checkpoint context periodically and use structured summaries for long tasks",
        "budget_exceeded": "Monitor budget consumption incrementally and set phase-level limits",
        "memory_error": "Maintain explicit state snapshots and verify memory integrity between phases",
        "planning_error": "Decompose complex plans into verifiable sub-steps with clear success criteria",
        "unknown": "When the failure mode is unclear, gather more diagnostic data before retrying",
    }

    # Procedure templates by failure type
    PROCEDURE_MAP: dict[str, str] = {
        "timeout": "1. Reduce operation scope. 2. Add aggressive timeouts (10s default). 3. Implement exponential backoff retry. 4. If still timing out, switch to simpler approach.",
        "capability_missing": "1. Identify the exact missing capability. 2. Check if an existing agent has it. 3. If not, spawn a specialist. 4. Verify capability before re-executing.",
        "hallucination": "1. Identify the hallucinated content. 2. Add explicit verification step. 3. Cross-validate with second agent. 4. Use tool-based grounding where possible.",
        "strategy_wrong": "1. Re-analyze the task with fresh perspective. 2. Identify why the strategy failed. 3. Consider alternative approaches from debate. 4. Test new strategy on a subset first.",
        "tool_error": "1. Check tool error message. 2. Validate input parameters. 3. Try alternative tool if available. 4. Fall back to manual approach if tools unreliable.",
        "context_lost": "1. Reload context from last checkpoint. 2. Summarize remaining task. 3. Continue with compressed context. 4. Add more frequent checkpoints.",
        "budget_exceeded": "1. Reduce remaining steps to essentials. 2. Use lighter model for non-critical steps. 3. Skip optional verification. 4. Compress prompts to reduce token usage.",
        "memory_error": "1. Clear corrupted memory entries. 2. Rebuild state from checkpoints. 3. Re-verify key facts. 4. Continue with validated state only.",
        "planning_error": "1. Decompose failed plan into smaller steps. 2. Verify each sub-step is feasible. 3. Add explicit dependency checks. 4. Get both agents to validate the plan.",
        "unknown": "1. Collect additional diagnostic data. 2. Run both agents independently on the failure. 3. Compare their analyses. 4. Escalate to user if still unclear.",
    }

    def reflect(
        self,
        failure_context: str,
        diagnosis: str,
        failure_type: str = "unknown",
        mast_codes: list[str] | None = None,
    ) -> TriplePathwayResult:
        """
        Generate triple-pathway reflection for a failure.

        Args:
            failure_context: Description of the failure
            diagnosis: Agent diagnosis text
            failure_type: NEXUS FailureType value
            mast_codes: Optional MAST classification codes

        Returns:
            TriplePathwayResult with principle, procedure, and synthesis
        """
        # Pathway 1: Principle extraction
        principle = self.PRINCIPLE_MAP.get(failure_type, self.PRINCIPLE_MAP["unknown"])

        # Enrich principle with context-specific details
        context_lower = failure_context.lower()
        if "agent" in context_lower and "ignored" in context_lower:
            principle += ". Ensure all agent inputs are acknowledged and addressed."
        if "repeated" in context_lower or "loop" in context_lower:
            principle += ". Detect repetition early and break out of loops."

        # Pathway 2: Procedural steps
        procedure = self.PROCEDURE_MAP.get(failure_type, self.PROCEDURE_MAP["unknown"])

        # Pathway 3: Unified synthesis
        synthesis = self._synthesize(principle, procedure, failure_context, diagnosis)

        return TriplePathwayResult(
            principle=principle,
            procedure=procedure,
            synthesis=synthesis,
            failure_type=failure_type,
            mast_codes=mast_codes or [],
        )

    def _synthesize(
        self,
        principle: str,
        procedure: str,
        failure_context: str,
        diagnosis: str,
    ) -> str:
        """Synthesize principle and procedure into actionable fix."""
        # Extract the first procedural step as the immediate action
        first_step = procedure.split(". ")[0] if ". " in procedure else procedure

        # Build concise synthesis
        synthesis = (
            f"Root principle: {principle[:100]}. "
            f"Immediate action: {first_step}. "
            f"Apply full {len(procedure.split('. '))} step procedure on retry."
        )
        return synthesis


# =============================================================================
# Module-level singletons
# =============================================================================

_classifier: MastClassifier | None = None
_reflector: TriplePathwayReflector | None = None
_lock = threading.Lock()


def get_mast_classifier() -> MastClassifier:
    """Get or create the global MastClassifier instance."""
    global _classifier
    if _classifier is None:
        with _lock:
            if _classifier is None:
                _classifier = MastClassifier()
    return _classifier


def get_triple_reflector() -> TriplePathwayReflector:
    """Get or create the global TriplePathwayReflector instance."""
    global _reflector
    if _reflector is None:
        with _lock:
            if _reflector is None:
                _reflector = TriplePathwayReflector()
    return _reflector


def reset_failure_taxonomy() -> None:
    """Reset both singletons."""
    global _classifier, _reflector
    _classifier = None
    _reflector = None
