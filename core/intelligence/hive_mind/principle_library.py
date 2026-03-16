"""
NEXUS V12.4 - EvolveR Principle Library

Self-distilled lessons from task outcomes with dynamic scoring.
Based on:
- EvolveR (arxiv:2510.16079): Principle library with s(p) = (success+1)/(usage+2)

The library stores principles (lessons learned) extracted from successful and
failed task executions. Each principle has a dynamic Bayesian score that
reflects its reliability. Principles are retrieved by tag similarity and
injected into prompts to guide future decisions.

Lifecycle:
1. Phase 7 (consolidation): Extract principles from task outcome
2. Principle scored: s(p) = (success_count + 1) / (usage_count + 2)
3. Phase 1 (analysis): Retrieve relevant principles by task tags
4. Principles injected into agent prompts for guided analysis

Usage:
    library = PrincipleLibrary()
    library.add_principle(
        text="Always verify file paths before writing",
        tags=["coding", "file_operations"],
        source_task="Fix bug in auth module",
    )
    library.record_usage("principle_id", success=True)
    relevant = library.retrieve(tags=["coding"], top_k=3)
"""

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Principle:
    """A single learned principle with dynamic scoring."""

    id: str
    text: str
    tags: list[str]
    source_task: str
    created_at: str
    usage_count: int = 0
    success_count: int = 0
    last_used: str | None = None

    @property
    def score(self) -> float:
        """
        Dynamic Bayesian score: s(p) = (success + 1) / (usage + 2).

        This is a Laplace-smoothed success rate:
        - New principle (0 uses): 0.5 (neutral prior)
        - After 1 success: 0.67
        - After 1 failure: 0.33
        - Converges to true success rate with more data
        """
        return (self.success_count + 1) / (self.usage_count + 2)

    def record_usage(self, success: bool) -> None:
        """Record that this principle was used in a task."""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.last_used = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "tags": self.tags,
            "source_task": self.source_task,
            "created_at": self.created_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "last_used": self.last_used,
            "score": round(self.score, 3),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Principle":
        return cls(
            id=data["id"],
            text=data["text"],
            tags=data.get("tags", []),
            source_task=data.get("source_task", ""),
            created_at=data.get("created_at", ""),
            usage_count=data.get("usage_count", 0),
            success_count=data.get("success_count", 0),
            last_used=data.get("last_used"),
        )


class PrincipleLibrary:
    """
    Stores and retrieves learned principles with dynamic scoring.

    Principles are extracted from task outcomes and scored using a Bayesian
    approach. High-scoring principles are retrieved for future task guidance.
    """

    def __init__(self, persist_path: Path | None = None, max_principles: int = 200):
        self._principles: dict[str, Principle] = {}
        self._persist_path = persist_path
        self._max_principles = max_principles

        # Load from disk if path provided
        if persist_path and persist_path.exists():
            self._load()

    def add_principle(
        self,
        text: str,
        tags: list[str],
        source_task: str = "",
    ) -> Principle:
        """
        Add a new principle to the library.

        Deduplicates by checking for similar text (first 50 chars).

        Args:
            text: The principle text
            tags: Categorization tags
            source_task: Task that generated this principle

        Returns:
            The created or existing Principle
        """
        # Deduplicate by text prefix
        text_prefix = text[:50].lower().strip()
        for existing in self._principles.values():
            if existing.text[:50].lower().strip() == text_prefix:
                # Merge tags
                existing.tags = list(set(existing.tags + tags))
                return existing

        principle = Principle(
            id=uuid.uuid4().hex[:8],
            text=text,
            tags=tags,
            source_task=source_task,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._principles[principle.id] = principle

        # Evict low-scoring principles if at capacity
        if len(self._principles) > self._max_principles:
            self._evict_lowest()

        logger.debug(f"PrincipleLibrary: Added '{text[:50]}...' with tags {tags}")
        return principle

    def record_usage(self, principle_id: str, success: bool) -> bool:
        """
        Record that a principle was used in a task.

        Args:
            principle_id: ID of the principle
            success: Whether the task succeeded

        Returns:
            True if principle was found and updated
        """
        if principle_id not in self._principles:
            return False
        self._principles[principle_id].record_usage(success)
        return True

    def retrieve(
        self,
        tags: list[str] | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[Principle]:
        """
        Retrieve relevant principles sorted by relevance and score.

        Args:
            tags: Filter by these tags (any match counts)
            top_k: Maximum number of principles to return
            min_score: Minimum score threshold

        Returns:
            List of Principle sorted by (tag_overlap * score) descending
        """
        candidates = []
        tag_set = set(tags) if tags else set()

        for p in self._principles.values():
            if p.score < min_score:
                continue

            # Calculate relevance: tag overlap ratio * score
            if tag_set:
                p_tags = set(p.tags)
                overlap = len(tag_set & p_tags)
                if overlap == 0:
                    continue
                relevance = (overlap / len(tag_set)) * p.score
            else:
                relevance = p.score

            candidates.append((relevance, p))

        # Sort by relevance descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in candidates[:top_k]]

    def get_principle(self, principle_id: str) -> Principle | None:
        """Get a specific principle by ID."""
        return self._principles.get(principle_id)

    def get_all(self) -> list[Principle]:
        """Get all principles sorted by score."""
        return sorted(self._principles.values(), key=lambda p: p.score, reverse=True)

    def format_for_prompt(
        self,
        tags: list[str] | None = None,
        top_k: int = 3,
    ) -> str:
        """
        Format relevant principles for injection into an LLM prompt.

        Args:
            tags: Filter tags
            top_k: Max principles to include

        Returns:
            Formatted string for prompt injection
        """
        principles = self.retrieve(tags=tags, top_k=top_k, min_score=0.3)
        if not principles:
            return ""

        lines = ["LEARNED PRINCIPLES (from past experience):"]
        for i, p in enumerate(principles, 1):
            lines.append(f"  {i}. [{p.score:.0%} reliable] {p.text}")
        return "\n".join(lines)

    def _evict_lowest(self) -> None:
        """Remove the lowest-scoring principle to make room."""
        if not self._principles:
            return
        lowest = min(self._principles.values(), key=lambda p: p.score)
        del self._principles[lowest.id]
        logger.debug(f"PrincipleLibrary: Evicted '{lowest.text[:30]}...' (score={lowest.score:.2f})")

    def save(self) -> None:
        """Persist library to disk."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": "1.0",
                "principles": [p.to_dict() for p in self._principles.values()],
            }
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.debug(f"PrincipleLibrary: Saved {len(self._principles)} principles")
        except Exception as e:
            logger.warning(f"PrincipleLibrary save failed: {e}")

    def _load(self) -> None:
        """Load library from disk."""
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for p_data in data.get("principles", []):
                p = Principle.from_dict(p_data)
                self._principles[p.id] = p
            logger.debug(f"PrincipleLibrary: Loaded {len(self._principles)} principles")
        except Exception as e:
            logger.warning(f"PrincipleLibrary load failed: {e}")

    def get_stats(self) -> dict:
        """Get library statistics."""
        if not self._principles:
            return {
                "total_principles": 0,
                "avg_score": 0.0,
                "total_usages": 0,
                "high_confidence": 0,
            }
        scores = [p.score for p in self._principles.values()]
        return {
            "total_principles": len(self._principles),
            "avg_score": sum(scores) / len(scores),
            "total_usages": sum(p.usage_count for p in self._principles.values()),
            "high_confidence": sum(1 for s in scores if s >= 0.7),
            "top_tags": self._get_top_tags(5),
        }

    def _get_top_tags(self, n: int) -> list[str]:
        """Get the N most common tags."""
        tag_counts: dict[str, int] = {}
        for p in self._principles.values():
            for tag in p.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        return [tag for tag, _ in sorted_tags[:n]]

    def reset(self) -> None:
        """Clear all principles."""
        self._principles.clear()


# Module-level singleton
_library: PrincipleLibrary | None = None
_library_lock = threading.Lock()


def get_principle_library(persist_path: Path | None = None) -> PrincipleLibrary:
    """Get or create the global PrincipleLibrary instance."""
    global _library
    if _library is None:
        with _library_lock:
            if _library is None:
                _library = PrincipleLibrary(persist_path=persist_path)
    return _library


def reset_principle_library() -> None:
    """Reset the global PrincipleLibrary instance."""
    global _library
    _library = None
