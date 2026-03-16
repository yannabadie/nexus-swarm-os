"""
V12.4 COGNITIVE BOOST: Runtime Waste Filter (arXiv:2510.26585)

LLM-free adaptive filter providing real-time oversight of multi-agent
execution. Monitors agent exchanges and triggers interventions at critical
moments to prevent token waste, redundant work, and error propagation.

Three intervention types:
1. Redundancy: Agents repeating the same work/conclusions
2. Divergence: Agents going off-topic or into unproductive loops
3. Stagnation: No progress despite continued exchanges

Operates without LLM calls — uses heuristic signals for low-overhead
runtime monitoring. ~30% additional token savings on top of AgentDiet.

Reference: "Stop Wasting Your Tokens: Towards Efficient Runtime
Multi-Agent Systems" (arXiv:2510.26585)
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class InterventionType(str, Enum):
    """Type of runtime intervention."""

    REDUNDANCY = "redundancy"  # Agents repeating work
    DIVERGENCE = "divergence"  # Going off-topic
    STAGNATION = "stagnation"  # No progress
    LOOP = "loop"  # Circular exchange pattern
    COST_LIMIT = "cost_limit"  # Token budget about to be exceeded


class InterventionAction(str, Enum):
    """Recommended action for an intervention."""

    CONTINUE = "continue"  # No intervention needed
    SKIP = "skip"  # Skip this exchange
    SUMMARIZE = "summarize"  # Compress and summarize before continuing
    REDIRECT = "redirect"  # Redirect agents to the task
    TERMINATE = "terminate"  # Stop the collaboration


@dataclass
class ExchangeRecord:
    """Record of a single agent exchange."""

    agent_id: str
    content_hash: str
    token_count: int
    timestamp: float
    topic_words: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "content_hash": self.content_hash[:8],
            "token_count": self.token_count,
        }


@dataclass
class Intervention:
    """A triggered intervention."""

    type: InterventionType
    action: InterventionAction
    confidence: float = 0.5
    reason: str = ""
    token_waste_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "token_waste_estimate": self.token_waste_estimate,
        }


@dataclass
class FilterStats:
    """Aggregate statistics."""

    total_exchanges: int = 0
    interventions_triggered: int = 0
    tokens_saved: int = 0
    intervention_counts: dict[str, int] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_exchanges": self.total_exchanges,
            "interventions_triggered": self.interventions_triggered,
            "tokens_saved": self.tokens_saved,
            "intervention_counts": dict(self.intervention_counts),
            "action_counts": dict(self.action_counts),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Content similarity threshold (hash collision -> redundancy)
REDUNDANCY_HASH_WINDOW: int = 10  # Look at last N exchanges

# Stagnation: max exchanges without new topic words
STAGNATION_WINDOW: int = 5

# Minimum new topic words per exchange to consider "progress"
MIN_NEW_WORDS: int = 3

# Loop detection: minimum repeat count for circular pattern
LOOP_THRESHOLD: int = 3

# Max consecutive same-agent exchanges before flagging
MAX_SAME_AGENT: int = 4

# Token budget warning threshold (fraction of budget remaining)
COST_WARNING_THRESHOLD: float = 0.15

# Divergence: max fraction of off-topic words
DIVERGENCE_THRESHOLD: float = 0.80

# Stop words to ignore in topic extraction
STOP_WORDS: frozenset = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "but",
        "and",
        "or",
        "if",
        "while",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "they",
        "them",
        "what",
        "which",
        "who",
        "whom",
    }
)


# ---------------------------------------------------------------------------
# Core: RuntimeWasteFilter
# ---------------------------------------------------------------------------


class RuntimeWasteFilter:
    """
    LLM-free runtime waste filter for multi-agent exchanges.

    Monitors agent communication in real-time and triggers
    interventions when it detects redundancy, divergence, stagnation,
    or loops.

    Usage:
        filter = RuntimeWasteFilter()
        filter.set_task_context("Fix the auth bug in login.py")

        # For each agent exchange:
        intervention = filter.check_exchange(
            agent_id="claude",
            content="I think the issue is in token validation...",
            token_count=150,
        )
        if intervention.action != InterventionAction.CONTINUE:
            # Apply intervention (skip, summarize, redirect, or terminate)
    """

    def __init__(
        self,
        stagnation_window: int = STAGNATION_WINDOW,
        loop_threshold: int = LOOP_THRESHOLD,
        cost_warning_threshold: float = COST_WARNING_THRESHOLD,
    ) -> None:
        self._stagnation_window = stagnation_window
        self._loop_threshold = loop_threshold
        self._cost_warning_threshold = cost_warning_threshold
        self._lock = threading.Lock()
        self._stats = FilterStats()

        # Exchange history
        self._exchanges: list[ExchangeRecord] = []
        self._task_words: set[str] = set()
        self._all_topic_words: set[str] = set()
        self._token_budget: int = 0
        self._tokens_used: int = 0

    # -- public API --

    def set_task_context(self, task_text: str, token_budget: int = 0) -> None:
        """Set the current task context for relevance checking."""
        self._task_words = self._extract_topic_words(task_text)
        self._token_budget = token_budget
        self._tokens_used = 0

    def check_exchange(
        self,
        agent_id: str,
        content: str,
        token_count: int = 0,
    ) -> Intervention:
        """
        Check an agent exchange for waste signals.

        Args:
            agent_id: The agent producing this exchange.
            content: The exchange content.
            token_count: Token count (estimated if 0).

        Returns:
            Intervention with recommended action.
        """
        if token_count == 0:
            token_count = max(1, len(content) // 4)

        content_hash = self._hash(content)
        topic_words = self._extract_topic_words(content)

        record = ExchangeRecord(
            agent_id=agent_id,
            content_hash=content_hash,
            token_count=token_count,
            timestamp=time.time(),
            topic_words=topic_words,
        )

        with self._lock:
            self._exchanges.append(record)
            self._tokens_used += token_count
            self._all_topic_words.update(topic_words)
            self._stats.total_exchanges += 1

        # Run checks in priority order
        checks = [
            self._check_redundancy(record),
            self._check_loop(),
            self._check_stagnation(topic_words),
            self._check_divergence(topic_words),
            self._check_cost_limit(),
        ]

        # Return the highest-priority intervention
        for intervention in checks:
            if intervention.action != InterventionAction.CONTINUE:
                with self._lock:
                    self._stats.interventions_triggered += 1
                    self._stats.tokens_saved += intervention.token_waste_estimate
                    key = intervention.type.value
                    self._stats.intervention_counts[key] = self._stats.intervention_counts.get(key, 0) + 1
                    akey = intervention.action.value
                    self._stats.action_counts[akey] = self._stats.action_counts.get(akey, 0) + 1
                logger.debug(
                    "RuntimeWasteFilter: %s -> %s (confidence=%.2f)",
                    intervention.type.value,
                    intervention.action.value,
                    intervention.confidence,
                )
                return intervention

        return Intervention(
            type=InterventionType.REDUNDANCY,
            action=InterventionAction.CONTINUE,
            confidence=1.0,
            reason="No waste signals detected.",
        )

    def get_stats(self) -> FilterStats:
        """Return aggregate statistics."""
        with self._lock:
            return FilterStats(
                total_exchanges=self._stats.total_exchanges,
                interventions_triggered=self._stats.interventions_triggered,
                tokens_saved=self._stats.tokens_saved,
                intervention_counts=dict(self._stats.intervention_counts),
                action_counts=dict(self._stats.action_counts),
            )

    def reset(self) -> None:
        """Reset all state."""
        with self._lock:
            self._stats = FilterStats()
            self._exchanges.clear()
            self._task_words.clear()
            self._all_topic_words.clear()
            self._token_budget = 0
            self._tokens_used = 0

    # -- private checks --

    def _check_redundancy(self, record: ExchangeRecord) -> Intervention:
        """Check if this exchange is redundant (near-duplicate of recent)."""
        recent = self._exchanges[-REDUNDANCY_HASH_WINDOW - 1 : -1]  # Exclude current
        for past in recent:
            if past.content_hash == record.content_hash:
                return Intervention(
                    type=InterventionType.REDUNDANCY,
                    action=InterventionAction.SKIP,
                    confidence=0.9,
                    reason=f"Duplicate content from {record.agent_id} (matches earlier exchange).",
                    token_waste_estimate=record.token_count,
                )
        return Intervention(type=InterventionType.REDUNDANCY, action=InterventionAction.CONTINUE)

    def _check_loop(self) -> Intervention:
        """Detect circular exchange patterns (A->B->A->B with same hashes)."""
        if len(self._exchanges) < self._loop_threshold * 2:
            return Intervention(type=InterventionType.LOOP, action=InterventionAction.CONTINUE)

        # Check for repeating agent-hash pairs
        recent = self._exchanges[-self._loop_threshold * 2 :]
        pairs = [(e.agent_id, e.content_hash) for e in recent]

        # Check if the pattern repeats
        half = len(pairs) // 2
        first_half = pairs[:half]
        second_half = pairs[half : half + len(first_half)]

        if first_half == second_half:
            total_waste = sum(e.token_count for e in recent[half:])
            return Intervention(
                type=InterventionType.LOOP,
                action=InterventionAction.REDIRECT,
                confidence=0.85,
                reason=f"Circular exchange pattern detected ({self._loop_threshold}+ repetitions).",
                token_waste_estimate=total_waste,
            )

        # Check for same-agent monologue
        recent_agents = [e.agent_id for e in self._exchanges[-MAX_SAME_AGENT:]]
        if len(set(recent_agents)) == 1 and len(recent_agents) >= MAX_SAME_AGENT:
            return Intervention(
                type=InterventionType.LOOP,
                action=InterventionAction.REDIRECT,
                confidence=0.7,
                reason=f"Agent '{recent_agents[0]}' monologue ({MAX_SAME_AGENT}+ consecutive exchanges).",
                token_waste_estimate=sum(e.token_count for e in self._exchanges[-MAX_SAME_AGENT:]),
            )

        return Intervention(type=InterventionType.LOOP, action=InterventionAction.CONTINUE)

    def _check_stagnation(self, current_words: set[str]) -> Intervention:
        """Check if agents are making progress (new topic words)."""
        if len(self._exchanges) < self._stagnation_window:
            return Intervention(type=InterventionType.STAGNATION, action=InterventionAction.CONTINUE)

        # Count new words in recent window
        window = self._exchanges[-self._stagnation_window :]
        window_words: set[str] = set()
        for e in window:
            window_words.update(e.topic_words)

        # Words that appeared before the window
        pre_window_words: set[str] = set()
        for e in self._exchanges[: -self._stagnation_window]:
            pre_window_words.update(e.topic_words)

        new_words = window_words - pre_window_words
        if len(new_words) < MIN_NEW_WORDS:
            total_waste = sum(e.token_count for e in window)
            return Intervention(
                type=InterventionType.STAGNATION,
                action=InterventionAction.SUMMARIZE,
                confidence=0.75,
                reason=(
                    f"Only {len(new_words)} new topic words in last "
                    f"{self._stagnation_window} exchanges (min: {MIN_NEW_WORDS})."
                ),
                token_waste_estimate=total_waste // 2,
            )

        return Intervention(type=InterventionType.STAGNATION, action=InterventionAction.CONTINUE)

    def _check_divergence(self, current_words: set[str]) -> Intervention:
        """Check if agents are diverging from the task."""
        if not self._task_words or not current_words:
            return Intervention(type=InterventionType.DIVERGENCE, action=InterventionAction.CONTINUE)

        # What fraction of current words are NOT related to the task?
        relevant = current_words & self._task_words
        if not current_words:
            return Intervention(type=InterventionType.DIVERGENCE, action=InterventionAction.CONTINUE)

        off_topic_ratio = 1.0 - (len(relevant) / len(current_words))

        if off_topic_ratio > DIVERGENCE_THRESHOLD and len(self._exchanges) > 3:
            return Intervention(
                type=InterventionType.DIVERGENCE,
                action=InterventionAction.REDIRECT,
                confidence=0.6 + off_topic_ratio * 0.2,
                reason=f"Exchange is {off_topic_ratio:.0%} off-topic from task context.",
                token_waste_estimate=self._exchanges[-1].token_count if self._exchanges else 0,
            )

        return Intervention(type=InterventionType.DIVERGENCE, action=InterventionAction.CONTINUE)

    def _check_cost_limit(self) -> Intervention:
        """Check if approaching token budget limit."""
        if self._token_budget <= 0:
            return Intervention(type=InterventionType.COST_LIMIT, action=InterventionAction.CONTINUE)

        remaining_ratio = 1.0 - (self._tokens_used / self._token_budget)

        if remaining_ratio <= 0:
            return Intervention(
                type=InterventionType.COST_LIMIT,
                action=InterventionAction.TERMINATE,
                confidence=1.0,
                reason=f"Token budget exhausted ({self._tokens_used}/{self._token_budget}).",
                token_waste_estimate=0,
            )

        if remaining_ratio <= self._cost_warning_threshold:
            return Intervention(
                type=InterventionType.COST_LIMIT,
                action=InterventionAction.SUMMARIZE,
                confidence=0.8,
                reason=(
                    f"Only {remaining_ratio:.0%} of token budget remaining ({self._tokens_used}/{self._token_budget})."
                ),
                token_waste_estimate=0,
            )

        return Intervention(type=InterventionType.COST_LIMIT, action=InterventionAction.CONTINUE)

    # -- utilities --

    @staticmethod
    def _extract_topic_words(text: str) -> set[str]:
        """Extract meaningful topic words from text."""
        words = set(re.findall(r"[a-z][a-z0-9_]+", text.lower()))
        return words - STOP_WORDS

    @staticmethod
    def _hash(content: str) -> str:
        """Hash content for comparison."""
        normalized = " ".join(content.lower().split())
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: RuntimeWasteFilter | None = None
_instance_lock = threading.Lock()


def get_runtime_waste_filter() -> RuntimeWasteFilter:
    """Get or create the global RuntimeWasteFilter singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RuntimeWasteFilter()
    return _instance


def reset_runtime_waste_filter() -> None:
    """Reset the global RuntimeWasteFilter singleton."""
    global _instance
    with _instance_lock:
        _instance = None
