"""
NEXUS V12.4 - Meta-Policy Memory (MPR)

Consolidates MARS reflections into reusable, predicate-like rules that prevent
the same class of error across future unrelated tasks.

Based on: Meta-Policy Reflexion (arXiv:2509.03990)

Two enforcement mechanisms:
1. Soft Memory-Guided Retrieval - retrieved rules bias agent action choice
2. Hard Admissibility Check (HAC) - domain constraints block invalid actions

Storage: workspace/.nexus/meta_policy_rules.jsonl

Usage:
    mpm = get_meta_policy_memory()

    # After MARS reflection in Phase 5:
    rule = mpm.consolidate(mars_result, mast_codes=["COMM_001"])

    # Before step execution in Phase 4:
    applicable = mpm.retrieve_applicable(task_type="debugging", context="timeout on API call")
    blocked = mpm.check_admissibility("call external API without timeout")
    if blocked.is_blocked:
        # Use blocked.suggested_alternative instead
        ...

    # After Phase 7 outcome:
    mpm.record_outcome(rule.id, success=True)
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.intelligence.hive_mind.failure_taxonomy import TriplePathwayResult

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class RuleCategory(str, Enum):
    """Categories for policy rules."""

    TIMEOUT = "timeout"
    VALIDATION = "validation"
    COMMUNICATION = "communication"
    RESOURCE = "resource"
    RETRY = "retry"
    SAFETY = "safety"
    GENERAL = "general"


@dataclass
class PolicyRule:
    """A single reusable policy rule derived from a MARS reflection."""

    id: str
    predicate: str  # When condition: "external_api_call AND no_timeout"
    action: str  # Then action: "set timeout=10s with backoff"
    category: str  # RuleCategory value
    source_task: str  # Origin task description (truncated)
    failure_type: str  # MAST failure type that spawned this rule
    mast_codes: list[str]  # MAST codes associated
    tags: list[str]
    created_at: float
    usage_count: int = 0
    success_count: int = 0
    last_used: float | None = None
    confidence: float = 0.5  # Initial confidence

    @property
    def score(self) -> float:
        """Bayesian score: (success + 1) / (usage + 2)."""
        return (self.success_count + 1) / (self.usage_count + 2)

    def record_usage(self, success: bool) -> None:
        """Record rule application outcome."""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.last_used = time.time()
        # Update confidence via EMA
        outcome = 1.0 if success else 0.0
        self.confidence = 0.8 * self.confidence + 0.2 * outcome

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdmissibilityResult:
    """Result of a hard admissibility check."""

    is_blocked: bool
    blocking_rules: list[PolicyRule] = field(default_factory=list)
    suggested_alternative: str = ""
    reason: str = ""


@dataclass
class RetrievalResult:
    """Result of soft memory-guided retrieval."""

    rules: list[PolicyRule]
    prompt_injection: str  # Formatted text to inject into agent prompt


@dataclass
class MPMStats:
    """Statistics for the meta-policy memory."""

    total_rules: int
    active_rules: int  # score > threshold
    categories: dict[str, int]
    avg_score: float
    total_activations: int


# =============================================================================
# Meta-Policy Memory
# =============================================================================

# Keywords that map to rule categories
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    RuleCategory.TIMEOUT.value: ["timeout", "deadline", "latency", "slow", "hang", "unresponsive"],
    RuleCategory.VALIDATION.value: ["validate", "check", "verify", "assertion", "type", "schema", "format"],
    RuleCategory.COMMUNICATION.value: ["message", "protocol", "parse", "json", "response", "request"],
    RuleCategory.RESOURCE.value: ["memory", "disk", "cpu", "token", "budget", "quota", "limit"],
    RuleCategory.RETRY.value: ["retry", "backoff", "fallback", "recovery", "circuit"],
    RuleCategory.SAFETY.value: ["security", "injection", "permission", "access", "auth"],
}

# Hard admissibility patterns: (pattern_keywords, blocked_reason)
_DEFAULT_HAC_PATTERNS: list[tuple[list[str], str]] = [
    (["no timeout", "without timeout"], "External calls must have timeout set"),
    (["retry without backoff", "immediate retry"], "Retries must use exponential backoff"),
    (["ignore error", "suppress exception"], "Errors must be logged, not suppressed"),
    (["unbounded loop", "infinite retry"], "Loops and retries must have max iterations"),
]


class MetaPolicyMemory:
    """
    Persistent, searchable rule store built from MARS reflections.

    Implements two enforcement mechanisms from MPR (arXiv:2509.03990):
    1. Soft memory-guided retrieval: bias agent actions with relevant rules
    2. Hard admissibility checks: block actions violating accumulated rules
    """

    SCORE_THRESHOLD = 0.3  # Rules below this are considered inactive
    MAX_RULES = 500  # Cap to prevent unbounded growth
    DECAY_HALFLIFE_DAYS = 30  # Rules decay if unused

    def __init__(self, storage_path: Path | None = None):
        self._storage_path = storage_path or Path("workspace/.nexus/meta_policy_rules.jsonl")
        self._rules: dict[str, PolicyRule] = {}
        self._lock = threading.Lock()
        self._load()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def consolidate(
        self,
        mars_result: "TriplePathwayResult",
        mast_codes: list[str] | None = None,
        source_task: str = "",
    ) -> PolicyRule:
        """
        Convert a MARS triple-pathway reflection into a reusable policy rule.

        Args:
            mars_result: Output from TriplePathwayReflector.reflect()
            mast_codes: MAST failure codes from classification
            source_task: Original task description (will be truncated)

        Returns:
            The new PolicyRule (also persisted to storage)
        """
        # Extract predicate from principle (the "when" condition)
        predicate = mars_result.principle if hasattr(mars_result, "principle") else str(mars_result)

        # Extract action from procedure + synthesis (the "then" action)
        procedure = mars_result.procedure if hasattr(mars_result, "procedure") else ""
        synthesis = mars_result.synthesis if hasattr(mars_result, "synthesis") else ""
        action = synthesis or procedure

        # Determine category
        failure_type = mars_result.failure_type if hasattr(mars_result, "failure_type") else "unknown"
        category = self._categorize(predicate, action, failure_type)

        # Build tags from mast codes + failure type
        tags = list(mast_codes or [])
        if failure_type:
            tags.append(failure_type)
        tags.append(category)

        # Check for duplicate (same predicate prefix)
        existing = self._find_duplicate(predicate)
        if existing:
            # Strengthen existing rule instead of creating duplicate
            existing.usage_count += 1
            existing.confidence = min(1.0, existing.confidence + 0.1)
            self._persist()
            logger.debug(f"MPM: Strengthened existing rule {existing.id[:8]}")
            return existing

        rule = PolicyRule(
            id=str(uuid.uuid4()),
            predicate=predicate[:500],
            action=action[:500],
            category=category,
            source_task=source_task[:200],
            failure_type=failure_type,
            mast_codes=mast_codes or [],
            tags=tags,
            created_at=time.time(),
        )

        with self._lock:
            self._rules[rule.id] = rule
            self._enforce_cap()
        self._persist()

        logger.info(f"MPM: Consolidated new rule {rule.id[:8]} [{category}]: {predicate[:80]}")
        return rule

    def retrieve_applicable(
        self,
        task_type: str = "",
        context: str = "",
        tags: list[str] | None = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        """
        Soft retrieval: find rules relevant to the current execution context.

        Args:
            task_type: Current task type for tag matching
            context: Free-text context to match against predicates
            tags: Optional specific tags to filter by
            top_k: Maximum number of rules to return

        Returns:
            RetrievalResult with ranked rules and formatted prompt injection
        """
        scored: list[tuple[float, PolicyRule]] = []
        context_lower = context.lower()
        task_lower = task_type.lower()

        for rule in self._rules.values():
            if rule.score < self.SCORE_THRESHOLD:
                continue

            # Score by relevance
            relevance = 0.0

            # Tag overlap
            if tags:
                tag_overlap = len(set(tags) & set(rule.tags))
                relevance += tag_overlap * 0.3

            # Context keyword overlap
            if context_lower:
                predicate_words = set(rule.predicate.lower().split())
                context_words = set(context_lower.split())
                overlap = len(predicate_words & context_words)
                relevance += min(overlap * 0.15, 0.6)

            # Task type match
            if task_lower and task_lower in rule.tags:
                relevance += 0.2

            # Category match with context
            for cat, keywords in _CATEGORY_KEYWORDS.items():
                if cat == rule.category and any(kw in context_lower for kw in keywords):
                    relevance += 0.2
                    break

            # Bayesian score boost
            relevance += rule.score * 0.3

            if relevance > 0.1:
                scored.append((relevance, rule))

        # Sort by relevance descending
        scored.sort(key=lambda x: x[0], reverse=True)
        top_rules = [rule for _, rule in scored[:top_k]]

        # Format for prompt injection
        prompt_text = self._format_for_prompt(top_rules)

        return RetrievalResult(rules=top_rules, prompt_injection=prompt_text)

    def check_admissibility(self, proposed_action: str) -> AdmissibilityResult:
        """
        Hard admissibility check: block actions that violate accumulated rules.

        Args:
            proposed_action: Description of the proposed agent action

        Returns:
            AdmissibilityResult indicating if blocked and why
        """
        action_lower = proposed_action.lower()
        blocking = []
        reasons = []

        # Check against learned rules with high confidence
        for rule in self._rules.values():
            if rule.score < 0.5 or rule.confidence < 0.6:
                continue

            # Check if proposed action matches the rule's predicate (violation condition)
            predicate_words = set(rule.predicate.lower().split())
            action_words = set(action_lower.split())
            overlap = len(predicate_words & action_words)

            if overlap >= 3:  # Significant overlap suggests violation
                blocking.append(rule)
                reasons.append(f"Rule [{rule.category}]: {rule.action[:100]}")

        # Check against default HAC patterns
        for pattern_keywords, reason in _DEFAULT_HAC_PATTERNS:
            if any(kw in action_lower for kw in pattern_keywords):
                reasons.append(f"Default HAC: {reason}")

        if blocking or reasons:
            # Build suggested alternative from blocking rules' actions
            alternatives = [r.action for r in blocking[:3]]
            suggested = "; ".join(alternatives) if alternatives else "Review and fix the proposed action."

            return AdmissibilityResult(
                is_blocked=len(blocking) > 0,
                blocking_rules=blocking,
                suggested_alternative=suggested,
                reason="; ".join(reasons),
            )

        return AdmissibilityResult(is_blocked=False)

    def record_outcome(self, rule_id: str, success: bool) -> bool:
        """
        Record outcome when a rule was applied.

        Args:
            rule_id: ID of the rule that was applied
            success: Whether the task succeeded after applying this rule

        Returns:
            True if rule found and updated
        """
        rule = self._rules.get(rule_id)
        if not rule:
            return False

        rule.record_usage(success)
        self._persist()
        return True

    # -------------------------------------------------------------------------
    # Statistics & Info
    # -------------------------------------------------------------------------

    def get_stats(self) -> MPMStats:
        """Get memory statistics."""
        categories: dict[str, int] = {}
        total_activations = 0
        total_score = 0.0
        active = 0

        for rule in self._rules.values():
            categories[rule.category] = categories.get(rule.category, 0) + 1
            total_activations += rule.usage_count
            total_score += rule.score
            if rule.score >= self.SCORE_THRESHOLD:
                active += 1

        n = len(self._rules)
        return MPMStats(
            total_rules=n,
            active_rules=active,
            categories=categories,
            avg_score=total_score / n if n > 0 else 0.0,
            total_activations=total_activations,
        )

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _categorize(self, predicate: str, action: str, failure_type: str) -> str:
        """Infer rule category from content."""
        combined = f"{predicate} {action} {failure_type}".lower()
        best_category = RuleCategory.GENERAL.value
        best_score = 0

        for category, keywords in _CATEGORY_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in combined)
            if hits > best_score:
                best_score = hits
                best_category = category

        return best_category

    def _find_duplicate(self, predicate: str) -> PolicyRule | None:
        """Find existing rule with similar predicate (prefix match)."""
        prefix = predicate[:80].lower()
        for rule in self._rules.values():
            if rule.predicate[:80].lower() == prefix:
                return rule
        return None

    def _enforce_cap(self) -> None:
        """Remove lowest-scoring rules if over capacity."""
        if len(self._rules) <= self.MAX_RULES:
            return

        # Sort by score ascending
        sorted_rules = sorted(self._rules.values(), key=lambda r: r.score)
        to_remove = len(self._rules) - self.MAX_RULES
        for rule in sorted_rules[:to_remove]:
            del self._rules[rule.id]

        logger.debug(f"MPM: Pruned {to_remove} low-scoring rules")

    def _format_for_prompt(self, rules: list[PolicyRule]) -> str:
        """Format rules for injection into an agent prompt."""
        if not rules:
            return ""

        lines = ["[LEARNED RULES - Apply these to avoid past mistakes]"]
        for i, rule in enumerate(rules, 1):
            score_str = f"{rule.score:.0%}"
            lines.append(
                f"  {i}. [{rule.category}] (reliability: {score_str}) "
                f"WHEN: {rule.predicate[:120]} -> THEN: {rule.action[:120]}"
            )
        lines.append("[END LEARNED RULES]")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _load(self) -> None:
        """Load rules from JSONL file."""
        if not self._storage_path.exists():
            return

        try:
            with open(self._storage_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    rule = PolicyRule(**data)
                    self._rules[rule.id] = rule
            logger.debug(f"MPM: Loaded {len(self._rules)} rules from {self._storage_path}")
        except Exception as e:
            logger.warning(f"MPM: Failed to load rules: {e}")

    def _persist(self) -> None:
        """Save all rules to JSONL file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                for rule in self._rules.values():
                    f.write(json.dumps(rule.to_dict()) + "\n")
        except Exception as e:
            logger.warning(f"MPM: Failed to persist rules: {e}")


# =============================================================================
# Singleton
# =============================================================================

_instance: MetaPolicyMemory | None = None
_instance_lock = threading.Lock()


def get_meta_policy_memory() -> MetaPolicyMemory:
    """Get or create the singleton MetaPolicyMemory instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MetaPolicyMemory()
    return _instance


def reset_meta_policy_memory() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
