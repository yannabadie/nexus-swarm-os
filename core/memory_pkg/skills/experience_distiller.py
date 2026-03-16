"""
V12.4 COGNITIVE BOOST: Experience Distiller (arXiv:2510.16079)

EvolveR-inspired self-distillation that synthesizes interaction
trajectories into abstract, reusable strategic principles. During
online interaction, relevant principles are retrieved to guide decisions.

Two-stage closed loop:
1. Offline Distillation: Analyzes past task outcomes to extract principles
2. Online Retrieval: Retrieves applicable principles for current task

This closes the loop between SuccessMemory/session logs and planning.

Reference: "EvolveR: Self-Evolving LLM Agents through an
Experience-Driven Lifecycle" (arXiv:2510.16079)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class PrincipleCategory(str, Enum):
    """Category of distilled principle."""

    STRATEGY = "strategy"  # High-level approach
    TOOL_USE = "tool_use"  # Tool selection patterns
    ERROR_RECOVERY = "error_recovery"  # How to handle specific errors
    COLLABORATION = "collaboration"  # Agent coordination patterns
    OPTIMIZATION = "optimization"  # Performance/token optimization
    DOMAIN = "domain"  # Domain-specific knowledge


@dataclass
class StrategicPrinciple:
    """A distilled strategic principle from past experience."""

    principle_id: str
    text: str
    category: PrincipleCategory
    source_tasks: list[str] = field(default_factory=list)
    keywords: set[str] = field(default_factory=set)
    success_rate: float = 0.5
    usage_count: int = 0
    confidence: float = 0.5
    created_at: float = 0.0
    last_used: float = 0.0

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "principle_id": self.principle_id,
            "text": self.text,
            "category": self.category.value,
            "source_tasks": self.source_tasks[:5],
            "keywords": sorted(self.keywords)[:20],
            "success_rate": round(self.success_rate, 3),
            "usage_count": self.usage_count,
            "confidence": round(self.confidence, 3),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategicPrinciple:
        return cls(
            principle_id=d["principle_id"],
            text=d["text"],
            category=PrincipleCategory(d["category"]),
            source_tasks=d.get("source_tasks", []),
            keywords=set(d.get("keywords", [])),
            success_rate=d.get("success_rate", 0.5),
            usage_count=d.get("usage_count", 0),
            confidence=d.get("confidence", 0.5),
            created_at=d.get("created_at", 0.0),
            last_used=d.get("last_used", 0.0),
        )


@dataclass
class DistillationResult:
    """Result of distillation from a task outcome."""

    new_principles: list[StrategicPrinciple]
    updated_principles: list[str]  # IDs of updated principles
    total_principles: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_count": len(self.new_principles),
            "updated_count": len(self.updated_principles),
            "total_principles": self.total_principles,
        }


@dataclass
class RetrievalResult:
    """Result of principle retrieval for a task."""

    principles: list[StrategicPrinciple]
    total_scored: int
    threshold_used: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieved_count": len(self.principles),
            "total_scored": self.total_scored,
            "threshold_used": round(self.threshold_used, 3),
        }


@dataclass
class DistillerStats:
    """Aggregate statistics."""

    total_distillations: int = 0
    total_retrievals: int = 0
    principles_created: int = 0
    principles_updated: int = 0
    principles_retrieved: int = 0
    avg_retrieval_count: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_distillations": self.total_distillations,
            "total_retrievals": self.total_retrievals,
            "principles_created": self.principles_created,
            "principles_updated": self.principles_updated,
            "avg_retrieval_count": round(self.avg_retrieval_count, 3),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum keyword overlap for retrieval
RETRIEVAL_THRESHOLD: float = 0.15

# Maximum principles to retrieve per query
MAX_RETRIEVAL: int = 5

# Minimum principle confidence to retrieve
MIN_CONFIDENCE: float = 0.3

# Bayesian prior for success rate updates: (success+1)/(total+2)
BAYESIAN_ALPHA: float = 1.0
BAYESIAN_BETA: float = 2.0

# EMA smoothing for confidence updates
CONFIDENCE_EMA: float = 0.3

# Maximum total principles stored
MAX_PRINCIPLES: int = 200

# Persistence file path
DEFAULT_STORE_PATH: str = "workspace/.nexus/strategic_principles.jsonl"

# Category detection patterns
CATEGORY_PATTERNS: dict[PrincipleCategory, list[str]] = {
    PrincipleCategory.STRATEGY: [
        "approach",
        "plan",
        "strategy",
        "method",
        "architecture",
        "design",
    ],
    PrincipleCategory.TOOL_USE: [
        "tool",
        "command",
        "function",
        "api",
        "call",
        "execute",
    ],
    PrincipleCategory.ERROR_RECOVERY: [
        "error",
        "fix",
        "recover",
        "retry",
        "fallback",
        "handle",
    ],
    PrincipleCategory.COLLABORATION: [
        "agent",
        "collaborate",
        "negotiate",
        "swarm",
        "lead",
        "support",
    ],
    PrincipleCategory.OPTIMIZATION: [
        "optimize",
        "performance",
        "token",
        "speed",
        "efficient",
        "reduce",
    ],
    PrincipleCategory.DOMAIN: [
        "domain",
        "specific",
        "expert",
        "specialized",
    ],
}

# Stop words for keyword extraction
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
        "and",
        "or",
        "but",
        "not",
        "no",
        "so",
        "if",
        "then",
        "that",
        "this",
        "it",
        "its",
        "i",
        "we",
        "you",
        "they",
        "them",
    }
)


# ---------------------------------------------------------------------------
# Core: ExperienceDistiller
# ---------------------------------------------------------------------------


class ExperienceDistiller:
    """
    EvolveR-inspired experience distiller.

    Extracts strategic principles from task outcomes and retrieves
    applicable principles for new tasks.

    Usage:
        distiller = ExperienceDistiller()

        # After a task completes:
        result = distiller.distill(
            task_description="Fix auth bug in login.py",
            outcome="success",
            lessons=["Check token expiry before validation"],
        )

        # Before a new task:
        principles = distiller.retrieve(
            task_description="Debug token refresh issue",
            top_k=3,
        )
    """

    def __init__(
        self,
        store_path: str | None = None,
        max_principles: int = MAX_PRINCIPLES,
    ) -> None:
        self._store_path = Path(store_path or DEFAULT_STORE_PATH)
        self._max_principles = max_principles
        self._lock = threading.RLock()
        self._stats = DistillerStats()
        self._principles: dict[str, StrategicPrinciple] = {}
        self._load()

    # -- public API --

    def distill(
        self,
        task_description: str,
        outcome: str,
        lessons: list[str] | None = None,
        tools_used: list[str] | None = None,
        error_messages: list[str] | None = None,
    ) -> DistillationResult:
        """
        Distill experience from a completed task into principles.

        Args:
            task_description: What the task was.
            outcome: "success" or "failure" or description.
            lessons: Explicit lessons learned (from agent reflection).
            tools_used: Tools used during the task.
            error_messages: Errors encountered.

        Returns:
            DistillationResult with new and updated principles.
        """
        success = "success" in outcome.lower()
        self._fingerprint(task_description)
        new_principles: list[StrategicPrinciple] = []
        updated_ids: list[str] = []

        # 1. Extract principles from explicit lessons
        for lesson in lessons or []:
            pid = self._fingerprint(lesson)
            existing = self._principles.get(pid)

            if existing:
                # Update existing principle
                self._update_principle(existing, success, task_description)
                updated_ids.append(pid)
            else:
                # Create new principle
                principle = self._create_principle(
                    text=lesson,
                    task_description=task_description,
                    success=success,
                )
                new_principles.append(principle)

        # 2. Extract tool-use principles
        if tools_used and success:
            tool_lesson = f"For tasks like '{task_description[:50]}', use: {', '.join(tools_used[:5])}"
            pid = self._fingerprint(tool_lesson)
            if pid not in self._principles:
                principle = self._create_principle(
                    text=tool_lesson,
                    task_description=task_description,
                    success=True,
                    category=PrincipleCategory.TOOL_USE,
                )
                new_principles.append(principle)

        # 3. Extract error-recovery principles
        if error_messages and success:
            for err in error_messages[:3]:
                err_lesson = f"When encountering '{err[:80]}', the recovery approach succeeded."
                pid = self._fingerprint(err_lesson)
                if pid not in self._principles:
                    principle = self._create_principle(
                        text=err_lesson,
                        task_description=task_description,
                        success=True,
                        category=PrincipleCategory.ERROR_RECOVERY,
                    )
                    new_principles.append(principle)

        # Store new principles
        with self._lock:
            for p in new_principles:
                self._principles[p.principle_id] = p
                self._stats.principles_created += 1

            # Evict oldest if over limit
            self._evict_if_needed()
            self._stats.total_distillations += 1

        self._save()

        return DistillationResult(
            new_principles=new_principles,
            updated_principles=updated_ids,
            total_principles=len(self._principles),
        )

    def retrieve(
        self,
        task_description: str,
        top_k: int = MAX_RETRIEVAL,
        min_confidence: float = MIN_CONFIDENCE,
    ) -> RetrievalResult:
        """
        Retrieve applicable principles for a task.

        Args:
            task_description: The upcoming task description.
            top_k: Maximum principles to retrieve.
            min_confidence: Minimum confidence threshold.

        Returns:
            RetrievalResult with scored and filtered principles.
        """
        task_words = self._extract_keywords(task_description)

        scored: list[tuple[float, StrategicPrinciple]] = []
        with self._lock:
            for p in self._principles.values():
                if p.confidence < min_confidence:
                    continue
                score = self._relevance_score(task_words, p)
                if score >= RETRIEVAL_THRESHOLD:
                    scored.append((score, p))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        retrieved = []
        for _score, p in scored[:top_k]:
            # Mark as used
            with self._lock:
                p.usage_count += 1
                p.last_used = time.time()
            retrieved.append(p)

        with self._lock:
            self._stats.total_retrievals += 1
            self._stats.principles_retrieved += len(retrieved)
            n = self._stats.total_retrievals
            self._stats.avg_retrieval_count = (self._stats.avg_retrieval_count * (n - 1) + len(retrieved)) / n

        return RetrievalResult(
            principles=retrieved,
            total_scored=len(scored),
            threshold_used=RETRIEVAL_THRESHOLD,
        )

    def record_outcome(
        self,
        principle_id: str,
        success: bool,
    ) -> None:
        """Record whether using a principle led to success."""
        with self._lock:
            p = self._principles.get(principle_id)
            if p:
                self._update_principle(p, success)
        self._save()

    def get_all_principles(self) -> list[StrategicPrinciple]:
        """Return all stored principles."""
        with self._lock:
            return list(self._principles.values())

    def get_stats(self) -> DistillerStats:
        """Return aggregate statistics."""
        with self._lock:
            return DistillerStats(
                total_distillations=self._stats.total_distillations,
                total_retrievals=self._stats.total_retrievals,
                principles_created=self._stats.principles_created,
                principles_updated=self._stats.principles_updated,
                principles_retrieved=self._stats.principles_retrieved,
                avg_retrieval_count=self._stats.avg_retrieval_count,
            )

    def reset(self) -> None:
        """Reset all state."""
        with self._lock:
            self._stats = DistillerStats()
            self._principles.clear()

    # -- private helpers --

    def _create_principle(
        self,
        text: str,
        task_description: str,
        success: bool,
        category: PrincipleCategory | None = None,
    ) -> StrategicPrinciple:
        """Create a new strategic principle."""
        pid = self._fingerprint(text)
        cat = category or self._detect_category(text)
        keywords = self._extract_keywords(text) | self._extract_keywords(task_description)

        return StrategicPrinciple(
            principle_id=pid,
            text=text,
            category=cat,
            source_tasks=[task_description[:100]],
            keywords=keywords,
            success_rate=1.0 if success else 0.0,
            usage_count=0,
            confidence=0.5,
        )

    def _update_principle(
        self,
        principle: StrategicPrinciple,
        success: bool,
        task_description: str = "",
    ) -> None:
        """Update an existing principle with new outcome."""
        # Bayesian success rate update
        n = principle.usage_count + 1
        successes = principle.success_rate * principle.usage_count + (1 if success else 0)
        principle.success_rate = (successes + BAYESIAN_ALPHA) / (n + BAYESIAN_BETA)

        # EMA confidence update
        outcome_signal = 1.0 if success else 0.0
        principle.confidence = CONFIDENCE_EMA * outcome_signal + (1 - CONFIDENCE_EMA) * principle.confidence

        principle.usage_count = n

        if task_description and task_description[:100] not in principle.source_tasks:
            principle.source_tasks.append(task_description[:100])
            if len(principle.source_tasks) > 10:
                principle.source_tasks = principle.source_tasks[-10:]

        with self._lock:
            self._stats.principles_updated += 1

    def _relevance_score(
        self,
        task_words: set[str],
        principle: StrategicPrinciple,
    ) -> float:
        """Compute relevance score between task and principle."""
        if not task_words or not principle.keywords:
            return 0.0

        overlap = len(task_words & principle.keywords)
        max_possible = min(len(task_words), len(principle.keywords))

        keyword_score = overlap / max_possible if max_possible > 0 else 0.0

        # Boost by success rate and confidence
        quality_boost = principle.success_rate * 0.3 + principle.confidence * 0.2

        return keyword_score * 0.5 + quality_boost

    def _detect_category(self, text: str) -> PrincipleCategory:
        """Detect principle category from text."""
        text_lower = text.lower()
        scores: dict[PrincipleCategory, int] = {}

        for cat, patterns in CATEGORY_PATTERNS.items():
            score = sum(1 for p in patterns if p in text_lower)
            scores[cat] = score

        if scores and max(scores.values()) > 0:
            return max(scores, key=scores.get)  # type: ignore[arg-type]
        return PrincipleCategory.STRATEGY

    def _evict_if_needed(self) -> None:
        """Evict lowest-value principles if over limit."""
        if len(self._principles) <= self._max_principles:
            return

        # Score each principle: confidence * success_rate, penalize unused
        scored = []
        for pid, p in self._principles.items():
            score = p.confidence * p.success_rate
            if p.usage_count == 0:
                score *= 0.5
            scored.append((score, pid))

        scored.sort(key=lambda x: x[0])

        # Evict lowest 10%
        evict_count = max(1, len(scored) // 10)
        for _, pid in scored[:evict_count]:
            del self._principles[pid]

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        import re

        words = set(re.findall(r"[a-z][a-z0-9_]+", text.lower()))
        return words - STOP_WORDS

    @staticmethod
    def _fingerprint(text: str) -> str:
        """Create a stable fingerprint for text."""
        normalized = " ".join(text.lower().split()[:50])
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()[:12]

    def _load(self) -> None:
        """Load principles from disk."""
        if not self._store_path.exists():
            return
        try:
            with open(self._store_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        p = StrategicPrinciple.from_dict(d)
                        self._principles[p.principle_id] = p
            logger.debug("Loaded %d principles from %s", len(self._principles), self._store_path)
        except Exception as e:
            logger.debug("Failed to load principles: %s", e)

    def _save(self) -> None:
        """Save principles to disk."""
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                principles = list(self._principles.values())
            with open(self._store_path, "w", encoding="utf-8") as f:
                for p in principles:
                    f.write(json.dumps(p.to_dict()) + "\n")
        except Exception as e:
            logger.debug("Failed to save principles: %s", e)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: ExperienceDistiller | None = None
_instance_lock = threading.Lock()


def get_experience_distiller() -> ExperienceDistiller:
    """Get or create the global ExperienceDistiller singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExperienceDistiller()
    return _instance


def reset_experience_distiller() -> None:
    """Reset the global ExperienceDistiller singleton."""
    global _instance
    with _instance_lock:
        _instance = None
