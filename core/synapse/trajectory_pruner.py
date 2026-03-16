"""
V12.4 COGNITIVE BOOST: AgentDiet Trajectory Pruner (arXiv:2509.23586)

Inference-time trajectory reduction that identifies and removes useless,
redundant, and expired information from agent message histories before
sending to LLMs. Achieves 40-60% input token reduction without
performance degradation.

Three pruning strategies:
1. Staleness: Remove messages whose information has been superseded
2. Redundancy: Collapse near-duplicate messages into summaries
3. Irrelevance: Remove messages that don't contribute to current task

Reference: "Improving the Efficiency of LLM Agent Systems through
Trajectory Reduction" (arXiv:2509.23586)
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class PruneReason(str, Enum):
    """Why a message was pruned."""

    STALE = "stale"  # Superseded by newer info
    REDUNDANT = "redundant"  # Near-duplicate of another message
    IRRELEVANT = "irrelevant"  # Low relevance to current task context
    EXPIRED = "expired"  # TTL exceeded
    EMPTY = "empty"  # No useful content


@dataclass
class TrajectoryMessage:
    """Single message in an agent trajectory."""

    content: str
    role: str = "assistant"  # user / assistant / system / tool
    agent_id: str = ""
    timestamp: float = 0.0
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if self.token_estimate == 0:
            # Rough estimate: ~4 chars per token
            self.token_estimate = max(1, len(self.content) // 4)


@dataclass
class PruneDecision:
    """Decision about a single message."""

    index: int
    keep: bool
    reason: PruneReason | None = None
    confidence: float = 1.0


@dataclass
class PruneResult:
    """Result of pruning a trajectory."""

    original_count: int
    pruned_count: int
    kept_count: int
    original_tokens: int
    pruned_tokens: int
    token_reduction_pct: float
    decisions: list[PruneDecision] = field(default_factory=list)
    kept_messages: list[TrajectoryMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_count": self.original_count,
            "pruned_count": self.pruned_count,
            "kept_count": self.kept_count,
            "original_tokens": self.original_tokens,
            "pruned_tokens": self.pruned_tokens,
            "token_reduction_pct": round(self.token_reduction_pct, 2),
        }


@dataclass
class PrunerStats:
    """Aggregate statistics for the pruner."""

    total_calls: int = 0
    total_messages_seen: int = 0
    total_messages_pruned: int = 0
    total_tokens_saved: int = 0
    avg_reduction_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_messages_seen": self.total_messages_seen,
            "total_messages_pruned": self.total_messages_pruned,
            "total_tokens_saved": self.total_tokens_saved,
            "avg_reduction_pct": round(self.avg_reduction_pct, 2),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Similarity threshold for redundancy detection (Jaccard on word trigrams)
REDUNDANCY_THRESHOLD: float = 0.65

# Messages older than this (seconds) are candidates for staleness pruning
STALENESS_WINDOW: float = 300.0  # 5 minutes

# Minimum message length (chars) to keep — shorter are irrelevance candidates
MIN_CONTENT_LENGTH: int = 15

# Maximum trajectory length before aggressive pruning kicks in
MAX_TRAJECTORY_LENGTH: int = 50

# Recency weight: recent messages are harder to prune
RECENCY_WEIGHT: float = 0.3

# Role protection: system/user messages are harder to prune
PROTECTED_ROLES = frozenset({"system", "user"})

# Patterns that indicate tool output (often large, good prune candidates)
TOOL_OUTPUT_PATTERNS = [
    re.compile(r"^```[\s\S]{500,}```$", re.MULTILINE),
    re.compile(r"^\s*\d+\s*(?:->|→|\|)\s", re.MULTILINE),  # Line-numbered output
    re.compile(r"(File|Directory|Path):\s+[/\\]"),
]

# Patterns indicating superseded information
SUPERSEDE_PATTERNS = [
    re.compile(r"(?:updated?|changed?|fixed|replaced|corrected)", re.IGNORECASE),
    re.compile(r"(?:actually|instead|rather|correction)", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Core: TrajectoryPruner
# ---------------------------------------------------------------------------


class TrajectoryPruner:
    """
    AgentDiet-inspired trajectory pruner.

    Removes useless, redundant, and expired messages from agent
    conversation histories before sending to LLMs.

    Usage:
        pruner = TrajectoryPruner()
        result = pruner.prune(messages, task_context="Fix auth bug")
        # Use result.kept_messages for the LLM call
    """

    def __init__(
        self,
        redundancy_threshold: float = REDUNDANCY_THRESHOLD,
        staleness_window: float = STALENESS_WINDOW,
        max_trajectory: int = MAX_TRAJECTORY_LENGTH,
        min_content_length: int = MIN_CONTENT_LENGTH,
    ) -> None:
        self._redundancy_threshold = redundancy_threshold
        self._staleness_window = staleness_window
        self._max_trajectory = max_trajectory
        self._min_content_length = min_content_length
        self._lock = threading.Lock()
        self._stats = PrunerStats()

    # -- public API --

    def prune(
        self,
        messages: Sequence[TrajectoryMessage],
        task_context: str = "",
        token_budget: int = 0,
    ) -> PruneResult:
        """
        Prune a trajectory of messages.

        Args:
            messages: Ordered list of trajectory messages.
            task_context: Current task description (for relevance scoring).
            token_budget: If > 0, prune until total tokens <= budget.

        Returns:
            PruneResult with kept messages and statistics.
        """
        if not messages:
            return PruneResult(
                original_count=0,
                pruned_count=0,
                kept_count=0,
                original_tokens=0,
                pruned_tokens=0,
                token_reduction_pct=0.0,
                kept_messages=[],
            )

        msgs = list(messages)
        original_count = len(msgs)
        original_tokens = sum(m.token_estimate for m in msgs)
        now = time.time()

        decisions: list[PruneDecision] = []

        # Phase 1: Mark empty/tiny messages
        for i, msg in enumerate(msgs):
            if len(msg.content.strip()) < self._min_content_length and msg.role not in PROTECTED_ROLES:
                decisions.append(PruneDecision(index=i, keep=False, reason=PruneReason.EMPTY, confidence=0.95))
                continue
            decisions.append(PruneDecision(index=i, keep=True))

        # Phase 2: Staleness — older messages superseded by newer corrections
        self._mark_stale(msgs, decisions, now)

        # Phase 3: Redundancy — near-duplicate detection via trigram Jaccard
        self._mark_redundant(msgs, decisions)

        # Phase 4: Irrelevance — low relevance to current task context
        if task_context:
            self._mark_irrelevant(msgs, decisions, task_context)

        # Phase 5: Token budget enforcement (if requested)
        if token_budget > 0:
            self._enforce_budget(msgs, decisions, token_budget)

        # Phase 6: Aggressive pruning if trajectory too long
        kept = [d for d in decisions if d.keep]
        if len(kept) > self._max_trajectory:
            self._aggressive_prune(msgs, decisions)

        # Build result
        kept_messages = []
        pruned_tokens = 0
        for d in decisions:
            if d.keep:
                kept_messages.append(msgs[d.index])
            else:
                pruned_tokens += msgs[d.index].token_estimate

        kept_count = len(kept_messages)
        pruned_count = original_count - kept_count
        reduction_pct = (pruned_tokens / original_tokens * 100) if original_tokens > 0 else 0.0

        result = PruneResult(
            original_count=original_count,
            pruned_count=pruned_count,
            kept_count=kept_count,
            original_tokens=original_tokens,
            pruned_tokens=pruned_tokens,
            token_reduction_pct=reduction_pct,
            decisions=decisions,
            kept_messages=kept_messages,
        )

        # Update stats
        with self._lock:
            self._stats.total_calls += 1
            self._stats.total_messages_seen += original_count
            self._stats.total_messages_pruned += pruned_count
            self._stats.total_tokens_saved += pruned_tokens
            if self._stats.total_calls > 0:
                self._stats.avg_reduction_pct = (
                    self._stats.avg_reduction_pct * (self._stats.total_calls - 1) + reduction_pct
                ) / self._stats.total_calls

        logger.debug(
            "TrajectoryPruner: %d->%d messages (%.1f%% token reduction)",
            original_count,
            kept_count,
            reduction_pct,
        )

        return result

    def get_stats(self) -> PrunerStats:
        """Return aggregate pruning statistics."""
        with self._lock:
            return PrunerStats(
                total_calls=self._stats.total_calls,
                total_messages_seen=self._stats.total_messages_seen,
                total_messages_pruned=self._stats.total_messages_pruned,
                total_tokens_saved=self._stats.total_tokens_saved,
                avg_reduction_pct=self._stats.avg_reduction_pct,
            )

    def reset(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = PrunerStats()

    # -- private helpers --

    def _mark_stale(
        self,
        msgs: list[TrajectoryMessage],
        decisions: list[PruneDecision],
        now: float,
    ) -> None:
        """Mark messages that have been superseded by later corrections."""
        for i, msg in enumerate(msgs):
            d = decisions[i]
            if not d.keep or msg.role in PROTECTED_ROLES:
                continue

            age = now - msg.timestamp if msg.timestamp > 0 else 0

            # Check if a later message explicitly supersedes this one
            if age > self._staleness_window:
                for j in range(i + 1, len(msgs)):
                    later = msgs[j]
                    if later.agent_id == msg.agent_id:
                        for pat in SUPERSEDE_PATTERNS:
                            if pat.search(later.content[:200]):
                                # Later message corrects this one
                                overlap = self._word_overlap(msg.content, later.content)
                                if overlap > 0.3:
                                    decisions[i] = PruneDecision(
                                        index=i,
                                        keep=False,
                                        reason=PruneReason.STALE,
                                        confidence=min(0.9, 0.5 + overlap),
                                    )
                                    break
                    if not decisions[i].keep:
                        break

    def _mark_redundant(
        self,
        msgs: list[TrajectoryMessage],
        decisions: list[PruneDecision],
    ) -> None:
        """Mark near-duplicate messages using trigram Jaccard similarity."""
        # Build trigram sets for kept messages
        trigrams_cache: dict[int, frozenset] = {}
        for i, d in enumerate(decisions):
            if d.keep:
                trigrams_cache[i] = self._trigrams(msgs[i].content)

        # Compare pairs (O(n^2) but n is bounded by max_trajectory)
        indices = sorted(trigrams_cache.keys())
        for idx_a in range(len(indices)):
            i = indices[idx_a]
            if not decisions[i].keep:
                continue
            for idx_b in range(idx_a + 1, len(indices)):
                j = indices[idx_b]
                if not decisions[j].keep:
                    continue
                # Same role messages are more likely to be redundant
                if msgs[i].role != msgs[j].role:
                    continue
                sim = self._jaccard(trigrams_cache[i], trigrams_cache[j])
                if sim >= self._redundancy_threshold:
                    # Keep the newer one, prune the older
                    older = i if msgs[i].timestamp <= msgs[j].timestamp else j
                    if msgs[older].role not in PROTECTED_ROLES:
                        decisions[older] = PruneDecision(
                            index=older,
                            keep=False,
                            reason=PruneReason.REDUNDANT,
                            confidence=sim,
                        )

    def _mark_irrelevant(
        self,
        msgs: list[TrajectoryMessage],
        decisions: list[PruneDecision],
        task_context: str,
    ) -> None:
        """Mark messages with low relevance to the current task."""
        task_words = set(self._normalize(task_context).split())
        if not task_words:
            return

        for i, d in enumerate(decisions):
            if not d.keep or msgs[i].role in PROTECTED_ROLES:
                continue

            msg_words = set(self._normalize(msgs[i].content).split())
            if not msg_words:
                continue

            overlap = len(task_words & msg_words) / max(len(task_words), 1)

            # Messages with very low task relevance AND are tool outputs
            is_tool_output = any(pat.search(msgs[i].content) for pat in TOOL_OUTPUT_PATTERNS)

            if overlap < 0.05 and is_tool_output and msgs[i].token_estimate > 200:
                decisions[i] = PruneDecision(
                    index=i,
                    keep=False,
                    reason=PruneReason.IRRELEVANT,
                    confidence=0.7,
                )

    def _enforce_budget(
        self,
        msgs: list[TrajectoryMessage],
        decisions: list[PruneDecision],
        budget: int,
    ) -> None:
        """Prune lowest-priority messages until within token budget."""
        current_tokens = sum(msgs[d.index].token_estimate for d in decisions if d.keep)
        if current_tokens <= budget:
            return

        # Score each kept message by priority (lower = prune first)
        scored: list[tuple[float, int]] = []
        for d in decisions:
            if not d.keep:
                continue
            msg = msgs[d.index]
            priority = self._message_priority(msg, len(msgs), d.index)
            scored.append((priority, d.index))

        scored.sort(key=lambda x: x[0])

        for _priority, idx in scored:
            if current_tokens <= budget:
                break
            msg = msgs[idx]
            if msg.role in PROTECTED_ROLES:
                continue
            decisions[idx] = PruneDecision(
                index=idx,
                keep=False,
                reason=PruneReason.IRRELEVANT,
                confidence=0.6,
            )
            current_tokens -= msg.token_estimate

    def _aggressive_prune(
        self,
        msgs: list[TrajectoryMessage],
        decisions: list[PruneDecision],
    ) -> None:
        """Aggressively prune when trajectory exceeds max length."""
        kept_indices = [d.index for d in decisions if d.keep]
        excess = len(kept_indices) - self._max_trajectory

        if excess <= 0:
            return

        # Score and prune lowest priority
        scored = [
            (self._message_priority(msgs[i], len(msgs), i), i)
            for i in kept_indices
            if msgs[i].role not in PROTECTED_ROLES
        ]
        scored.sort(key=lambda x: x[0])

        for _, idx in scored[:excess]:
            decisions[idx] = PruneDecision(
                index=idx,
                keep=False,
                reason=PruneReason.EXPIRED,
                confidence=0.5,
            )

    def _message_priority(self, msg: TrajectoryMessage, total: int, index: int) -> float:
        """Compute priority score for a message (higher = more important)."""
        score = 0.0

        # Recency: newer messages are more important
        recency = index / max(total - 1, 1)
        score += recency * RECENCY_WEIGHT

        # Role importance
        role_weights = {"system": 1.0, "user": 0.9, "assistant": 0.5, "tool": 0.3}
        score += role_weights.get(msg.role, 0.4) * 0.4

        # Content density: shorter messages are more likely summaries
        if msg.token_estimate < 50:
            score += 0.15
        elif msg.token_estimate > 500:
            score -= 0.1  # Long messages are prune candidates

        return score

    @staticmethod
    def _trigrams(text: str) -> frozenset:
        """Extract word-level trigrams from text."""
        words = text.lower().split()[:100]  # Cap for performance
        if len(words) < 3:
            return frozenset(words)
        return frozenset((words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2))

    @staticmethod
    def _jaccard(a: frozenset, b: frozenset) -> float:
        """Jaccard similarity between two sets."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    @staticmethod
    def _word_overlap(text_a: str, text_b: str) -> float:
        """Word overlap ratio between two texts."""
        words_a = set(text_a.lower().split()[:100])
        words_b = set(text_b.lower().split()[:100])
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / min(len(words_a), len(words_b))

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison."""
        return re.sub(r"[^a-z0-9\s]", "", text.lower().strip())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: TrajectoryPruner | None = None
_instance_lock = threading.Lock()


def get_trajectory_pruner() -> TrajectoryPruner:
    """Get or create the global TrajectoryPruner singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TrajectoryPruner()
    return _instance


def reset_trajectory_pruner() -> None:
    """Reset the global TrajectoryPruner singleton."""
    global _instance
    with _instance_lock:
        _instance = None
