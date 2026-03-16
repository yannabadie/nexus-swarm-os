"""
AdaptiveMemoryOrganizer - Zettelkasten-Inspired Dynamic Memory Organization.

NEXUS V12.4 COGNITIVE BOOST - Based on A-MEM (arXiv:2502.12110)

Key Ideas from A-MEM:
- Agentic memory that self-organizes into structured notes
- Each note has: content, keywords, tags, and inter-note links
- Memories evolve as new information arrives
- Automatic indexing and retrieval via keyword/tag overlap

NEXUS Adaptation:
- Pure Python implementation (no graph database required)
- Uses trigram overlap for note linking (like TrajectoryPruner)
- Integrates with existing Blackboard/SuccessMemory
- Thread-safe singleton pattern

Architecture:
    +-----------------------------------------+
    |         AdaptiveMemoryOrganizer         |
    |  +--------+  +--------+  +----------+  |
    |  | Notes  |--| Index  |--| Linker   |  |
    |  | Store  |  | (tags) |  | (trigram) |  |
    |  +--------+  +--------+  +----------+  |
    +-----------------------------------------+

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-17
Reference: arXiv:2502.12110 (A-MEM: Agentic Memory for LLM Agents)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Minimum trigram overlap for automatic linking
LINK_THRESHOLD = 0.25

# Maximum number of links per note
MAX_LINKS_PER_NOTE = 10

# Maximum notes before compaction
MAX_NOTES = 500

# Tag extraction: minimum word length to consider
MIN_TAG_WORD_LENGTH = 3

# Stop words to exclude from tags
STOP_WORDS: set[str] = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "are",
    "was",
    "were",
    "been",
    "have",
    "has",
    "had",
    "but",
    "not",
    "can",
    "will",
    "all",
    "each",
    "which",
    "when",
    "what",
    "how",
    "its",
    "they",
    "their",
    "also",
    "into",
    "only",
    "more",
    "than",
    "very",
    "just",
    "about",
    "over",
    "such",
    "some",
    "any",
    "then",
    "our",
    "your",
    "them",
    "these",
    "those",
    "being",
    "other",
}


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class MemoryNote:
    """
    A structured memory note (Zettelkasten-inspired).

    Each note contains:
    - content: The actual information
    - keywords: Auto-extracted significant terms
    - tags: Higher-level categories
    - links: IDs of related notes
    - metadata: Creation time, source, access count
    """

    note_id: str
    content: str
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    source: str = "unknown"  # e.g., "task_outcome", "user_feedback", "consolidation"
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5  # 0.0 = trivial, 1.0 = critical

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "note_id": self.note_id,
            "content": self.content,
            "keywords": self.keywords,
            "tags": self.tags,
            "links": self.links,
            "source": self.source,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryNote:
        """Deserialize from dict."""
        return cls(
            note_id=data["note_id"],
            content=data["content"],
            keywords=data.get("keywords", []),
            tags=data.get("tags", []),
            links=data.get("links", []),
            source=data.get("source", "unknown"),
            created_at=data.get("created_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            access_count=data.get("access_count", 0),
            importance=data.get("importance", 0.5),
        )


@dataclass
class RetrievalResult:
    """Result of a memory retrieval query."""

    notes: list[MemoryNote]
    scores: list[float]  # Relevance scores for each note
    query_keywords: list[str]
    total_scanned: int


@dataclass
class OrganizerStats:
    """Statistics about the memory organizer."""

    total_notes: int
    total_links: int
    total_tags: int
    unique_tags: int
    avg_links_per_note: float
    avg_keywords_per_note: float
    oldest_note_age_hours: float
    most_accessed_note_id: str | None


# =============================================================================
# Trigram Utilities (shared concept with TrajectoryPruner)
# =============================================================================


def _extract_trigrams(text: str) -> set[str]:
    """Extract character trigrams from text."""
    text = text.lower().strip()
    if len(text) < 3:
        return {text} if text else set()
    return {text[i : i + 3] for i in range(len(text) - 2)}


def _trigram_similarity(text_a: str, text_b: str) -> float:
    """
    Compute Jaccard similarity between trigram sets.

    Returns:
        Float between 0.0 (no overlap) and 1.0 (identical).
    """
    trigrams_a = _extract_trigrams(text_a)
    trigrams_b = _extract_trigrams(text_b)

    if not trigrams_a or not trigrams_b:
        return 0.0

    intersection = len(trigrams_a & trigrams_b)
    union = len(trigrams_a | trigrams_b)

    return intersection / union if union > 0 else 0.0


# =============================================================================
# Tag & Keyword Extraction
# =============================================================================


def _extract_keywords(text: str, max_keywords: int = 10) -> list[str]:
    """
    Extract significant keywords from text.

    Uses word frequency after stop word removal.

    Args:
        text: Input text
        max_keywords: Maximum keywords to extract

    Returns:
        List of keywords sorted by frequency
    """
    # Tokenize: split on non-alphanumeric
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())

    # Filter
    filtered = [w for w in words if len(w) >= MIN_TAG_WORD_LENGTH and w not in STOP_WORDS]

    # Count and sort by frequency
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(max_keywords)]


def _infer_tags(content: str, keywords: list[str]) -> list[str]:
    """
    Infer higher-level tags from content and keywords.

    Uses simple rule-based classification.

    Args:
        content: Note content
        keywords: Extracted keywords

    Returns:
        List of inferred tags
    """
    tags: list[str] = []
    content_lower = content.lower()
    keyword_set = set(keywords)

    # Domain tags
    domain_indicators = {
        "coding": {
            "code",
            "function",
            "class",
            "method",
            "variable",
            "bug",
            "error",
            "syntax",
            "implement",
            "refactor",
            "test",
            "debug",
        },
        "research": {
            "paper",
            "study",
            "finding",
            "evidence",
            "hypothesis",
            "result",
            "analysis",
            "conclusion",
            "experiment",
        },
        "architecture": {
            "design",
            "pattern",
            "structure",
            "module",
            "component",
            "interface",
            "abstraction",
            "layer",
            "pipeline",
        },
        "security": {
            "vulnerability",
            "attack",
            "defense",
            "injection",
            "authentication",
            "authorization",
            "encryption",
            "kernel",
        },
        "performance": {
            "latency",
            "throughput",
            "optimization",
            "cache",
            "memory",
            "bottleneck",
            "profile",
            "benchmark",
        },
        "collaboration": {"agent", "swarm", "negotiate", "consensus", "debate", "delegate", "parallel", "sequential"},
    }

    for tag, indicators in domain_indicators.items():
        if keyword_set & indicators or any(ind in content_lower for ind in indicators):
            tags.append(tag)

    # Outcome tags
    if any(w in content_lower for w in ["success", "passed", "completed", "resolved"]):
        tags.append("success")
    if any(w in content_lower for w in ["failure", "failed", "error", "crash"]):
        tags.append("failure")
    if any(w in content_lower for w in ["lesson", "learned", "insight", "takeaway"]):
        tags.append("lesson")

    return tags[:5]  # Cap at 5 tags


# =============================================================================
# AdaptiveMemoryOrganizer
# =============================================================================


class AdaptiveMemoryOrganizer:
    """
    Zettelkasten-inspired adaptive memory organization.

    Key operations:
    1. add_note: Store new information with auto-tagging and linking
    2. retrieve: Find relevant notes by query
    3. evolve_note: Update existing note with new information
    4. compact: Remove low-importance notes when over capacity
    5. get_connected: Get notes connected to a given note (graph traversal)

    Thread-safe via RLock.
    """

    def __init__(
        self,
        persistence_path: Path | None = None,
        link_threshold: float = LINK_THRESHOLD,
        max_notes: int = MAX_NOTES,
    ):
        """
        Initialize the organizer.

        Args:
            persistence_path: Optional JSONL file for persistence
            link_threshold: Trigram overlap threshold for auto-linking
            max_notes: Maximum notes before compaction triggers
        """
        self._notes: dict[str, MemoryNote] = {}
        self._tag_index: dict[str, set[str]] = defaultdict(set)  # tag -> note_ids
        self._keyword_index: dict[str, set[str]] = defaultdict(set)  # keyword -> note_ids
        self._persistence_path = persistence_path
        self._link_threshold = link_threshold
        self._max_notes = max_notes
        self._lock = threading.RLock()
        self._next_id = 1

        # Load persisted notes
        if persistence_path and persistence_path.exists():
            self._load()

    def _generate_id(self) -> str:
        """Generate a unique note ID."""
        note_id = f"note_{self._next_id:06d}"
        self._next_id += 1
        return note_id

    def add_note(
        self,
        content: str,
        source: str = "unknown",
        tags: list[str] | None = None,
        importance: float = 0.5,
    ) -> MemoryNote:
        """
        Add a new memory note with automatic keyword extraction, tagging, and linking.

        Args:
            content: The information to store
            source: Origin of the information (e.g., "task_outcome", "user_feedback")
            tags: Optional explicit tags (auto-inferred if not provided)
            importance: Importance score (0.0-1.0)

        Returns:
            The created MemoryNote
        """
        with self._lock:
            note_id = self._generate_id()

            # Extract keywords
            keywords = _extract_keywords(content)

            # Infer tags if not provided
            if tags is None:
                tags = _infer_tags(content, keywords)

            # Create note
            note = MemoryNote(
                note_id=note_id,
                content=content,
                keywords=keywords,
                tags=tags,
                source=source,
                importance=max(0.0, min(1.0, importance)),
            )

            # Auto-link to related notes
            note.links = self._find_links(note)

            # Store
            self._notes[note_id] = note

            # Update indices
            for tag in tags:
                self._tag_index[tag].add(note_id)
            for kw in keywords:
                self._keyword_index[kw].add(note_id)

            # Add back-links (bidirectional linking)
            for linked_id in note.links:
                if linked_id in self._notes:
                    linked_note = self._notes[linked_id]
                    if note_id not in linked_note.links and len(linked_note.links) < MAX_LINKS_PER_NOTE:
                        linked_note.links.append(note_id)

            # Compact if over capacity
            if len(self._notes) > self._max_notes:
                self._compact()

            # Persist
            self._save()

            logger.debug(
                f"[A-MEM] Added note {note_id}: {len(keywords)} keywords, {len(tags)} tags, {len(note.links)} links"
            )
            return note

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        tags_filter: list[str] | None = None,
        min_score: float = 0.1,
    ) -> RetrievalResult:
        """
        Retrieve relevant notes by query.

        Scoring combines:
        1. Keyword overlap (40%)
        2. Trigram similarity (40%)
        3. Tag match bonus (20%)

        Args:
            query: Search query
            top_k: Maximum notes to return
            tags_filter: Optional tags to filter by
            min_score: Minimum relevance score

        Returns:
            RetrievalResult with ranked notes
        """
        with self._lock:
            query_keywords = _extract_keywords(query)

            candidates: list[tuple[str, float]] = []

            # Pre-filter by tags if specified
            if tags_filter:
                candidate_ids: set[str] = set()
                for tag in tags_filter:
                    candidate_ids |= self._tag_index.get(tag, set())
            else:
                candidate_ids = set(self._notes.keys())

            for note_id in candidate_ids:
                note = self._notes[note_id]

                # 1. Keyword overlap score (Jaccard)
                query_kw_set = set(query_keywords)
                note_kw_set = set(note.keywords)
                kw_intersection = len(query_kw_set & note_kw_set)
                kw_union = len(query_kw_set | note_kw_set)
                keyword_score = kw_intersection / kw_union if kw_union > 0 else 0.0

                # 2. Trigram similarity
                trigram_score = _trigram_similarity(query, note.content[:500])

                # 3. Tag match bonus
                if tags_filter:
                    tag_matches = len(set(tags_filter) & set(note.tags))
                    tag_score = tag_matches / len(tags_filter) if tags_filter else 0.0
                else:
                    # Infer query tags and compare
                    query_tags = _infer_tags(query, query_keywords)
                    if query_tags:
                        tag_matches = len(set(query_tags) & set(note.tags))
                        tag_score = tag_matches / len(query_tags)
                    else:
                        tag_score = 0.0

                # Combined score
                score = keyword_score * 0.4 + trigram_score * 0.4 + tag_score * 0.2

                # Importance boost
                score *= 0.5 + 0.5 * note.importance

                if score >= min_score:
                    candidates.append((note_id, score))

            # Sort by score descending
            candidates.sort(key=lambda x: x[1], reverse=True)
            top = candidates[:top_k]

            # Update access stats
            result_notes = []
            result_scores = []
            for note_id, score in top:
                note = self._notes[note_id]
                note.last_accessed = time.time()
                note.access_count += 1
                result_notes.append(note)
                result_scores.append(round(score, 4))

            return RetrievalResult(
                notes=result_notes,
                scores=result_scores,
                query_keywords=query_keywords,
                total_scanned=len(candidate_ids),
            )

    def evolve_note(
        self,
        note_id: str,
        additional_content: str,
        boost_importance: float = 0.1,
    ) -> MemoryNote | None:
        """
        Evolve an existing note with new information.

        The note's content is appended, keywords re-extracted,
        and links re-computed.

        Args:
            note_id: ID of note to evolve
            additional_content: New content to append
            boost_importance: How much to increase importance

        Returns:
            Updated note, or None if not found
        """
        with self._lock:
            if note_id not in self._notes:
                return None

            note = self._notes[note_id]

            # Remove from old indices
            for tag in note.tags:
                self._tag_index[tag].discard(note_id)
            for kw in note.keywords:
                self._keyword_index[kw].discard(note_id)

            # Update content
            note.content = f"{note.content}\n---\n{additional_content}"

            # Re-extract keywords and tags
            note.keywords = _extract_keywords(note.content)
            note.tags = _infer_tags(note.content, note.keywords)

            # Boost importance
            note.importance = min(1.0, note.importance + boost_importance)

            # Re-compute links
            note.links = self._find_links(note)

            # Update indices
            for tag in note.tags:
                self._tag_index[tag].add(note_id)
            for kw in note.keywords:
                self._keyword_index[kw].add(note_id)

            self._save()
            logger.debug(f"[A-MEM] Evolved note {note_id}: importance={note.importance:.2f}")
            return note

    def get_connected(
        self,
        note_id: str,
        max_depth: int = 2,
    ) -> list[MemoryNote]:
        """
        Get notes connected to a given note via links (BFS).

        Args:
            note_id: Starting note ID
            max_depth: Maximum link depth to traverse

        Returns:
            List of connected notes (excluding the starting note)
        """
        with self._lock:
            if note_id not in self._notes:
                return []

            visited: set[str] = {note_id}
            queue: list[tuple[str, int]] = [(note_id, 0)]
            connected: list[MemoryNote] = []

            while queue:
                current_id, depth = queue.pop(0)
                if depth >= max_depth:
                    continue

                current = self._notes.get(current_id)
                if not current:
                    continue

                for linked_id in current.links:
                    if linked_id not in visited and linked_id in self._notes:
                        visited.add(linked_id)
                        connected.append(self._notes[linked_id])
                        queue.append((linked_id, depth + 1))

            return connected

    def get_note(self, note_id: str) -> MemoryNote | None:
        """Get a single note by ID."""
        with self._lock:
            return self._notes.get(note_id)

    def get_notes_by_tag(self, tag: str) -> list[MemoryNote]:
        """Get all notes with a given tag."""
        with self._lock:
            note_ids = self._tag_index.get(tag, set())
            return [self._notes[nid] for nid in note_ids if nid in self._notes]

    def remove_note(self, note_id: str) -> bool:
        """Remove a note and clean up indices and links."""
        with self._lock:
            if note_id not in self._notes:
                return False

            note = self._notes[note_id]

            # Remove from indices
            for tag in note.tags:
                self._tag_index[tag].discard(note_id)
            for kw in note.keywords:
                self._keyword_index[kw].discard(note_id)

            # Remove back-links from other notes
            for linked_id in note.links:
                if linked_id in self._notes:
                    linked = self._notes[linked_id]
                    if note_id in linked.links:
                        linked.links.remove(note_id)

            del self._notes[note_id]
            self._save()
            return True

    def get_stats(self) -> OrganizerStats:
        """Get statistics about the memory organizer."""
        with self._lock:
            if not self._notes:
                return OrganizerStats(
                    total_notes=0,
                    total_links=0,
                    total_tags=0,
                    unique_tags=0,
                    avg_links_per_note=0.0,
                    avg_keywords_per_note=0.0,
                    oldest_note_age_hours=0.0,
                    most_accessed_note_id=None,
                )

            total_links = sum(len(n.links) for n in self._notes.values())
            all_tags = [tag for n in self._notes.values() for tag in n.tags]
            total_keywords = sum(len(n.keywords) for n in self._notes.values())

            now = time.time()
            oldest_age = max((now - n.created_at) for n in self._notes.values()) / 3600.0

            most_accessed = max(self._notes.values(), key=lambda n: n.access_count)

            return OrganizerStats(
                total_notes=len(self._notes),
                total_links=total_links,
                total_tags=len(all_tags),
                unique_tags=len(set(all_tags)),
                avg_links_per_note=round(total_links / len(self._notes), 2),
                avg_keywords_per_note=round(total_keywords / len(self._notes), 2),
                oldest_note_age_hours=round(oldest_age, 2),
                most_accessed_note_id=most_accessed.note_id,
            )

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _find_links(self, note: MemoryNote) -> list[str]:
        """
        Find related notes using trigram similarity.

        Args:
            note: The note to find links for

        Returns:
            List of related note IDs
        """
        candidates: list[tuple[str, float]] = []

        for other_id, other in self._notes.items():
            if other_id == note.note_id:
                continue

            # Compute similarity
            sim = _trigram_similarity(note.content[:300], other.content[:300])
            if sim >= self._link_threshold:
                candidates.append((other_id, sim))

        # Sort by similarity, take top links
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [nid for nid, _ in candidates[:MAX_LINKS_PER_NOTE]]

    def _compact(self) -> int:
        """
        Remove least important notes when over capacity.

        Compaction strategy:
        1. Score each note: importance * recency * access_frequency
        2. Remove bottom 20% of notes

        Returns:
            Number of notes removed
        """
        if len(self._notes) <= self._max_notes:
            return 0

        now = time.time()
        scored: list[tuple[str, float]] = []

        for note_id, note in self._notes.items():
            # Recency factor (exponential decay, half-life = 24h)
            age_hours = (now - note.last_accessed) / 3600.0
            recency = 2 ** (-age_hours / 24.0)

            # Access frequency (log scale)
            frequency = 1.0 + (0.1 * note.access_count)

            # Combined score
            score = note.importance * recency * frequency
            scored.append((note_id, score))

        # Sort ascending (lowest scores first)
        scored.sort(key=lambda x: x[1])

        # Remove bottom 20%
        to_remove = max(1, len(scored) // 5)
        removed = 0

        for note_id, _ in scored[:to_remove]:
            if self.remove_note(note_id):
                removed += 1

        logger.info(f"[A-MEM] Compacted: removed {removed} notes, {len(self._notes)} remaining")
        return removed

    def _save(self) -> None:
        """Persist notes to JSONL file."""
        if not self._persistence_path:
            return

        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persistence_path, "w", encoding="utf-8") as f:
                for note in self._notes.values():
                    f.write(json.dumps(note.to_dict()) + "\n")
        except Exception as e:
            logger.warning(f"[A-MEM] Failed to save: {e}")

    def _load(self) -> None:
        """Load notes from JSONL file."""
        if not self._persistence_path or not self._persistence_path.exists():
            return

        try:
            max_id = 0
            with open(self._persistence_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    note = MemoryNote.from_dict(data)
                    self._notes[note.note_id] = note

                    # Update indices
                    for tag in note.tags:
                        self._tag_index[tag].add(note.note_id)
                    for kw in note.keywords:
                        self._keyword_index[kw].add(note.note_id)

                    # Track max ID for generation
                    try:
                        num = int(note.note_id.split("_")[1])
                        max_id = max(max_id, num)
                    except (IndexError, ValueError):
                        pass

            self._next_id = max_id + 1
            logger.info(f"[A-MEM] Loaded {len(self._notes)} notes")

        except Exception as e:
            logger.warning(f"[A-MEM] Failed to load: {e}")


# =============================================================================
# Singleton
# =============================================================================

_organizer: AdaptiveMemoryOrganizer | None = None
_organizer_lock = threading.Lock()


def get_adaptive_memory_organizer(
    persistence_path: Path | None = None,
) -> AdaptiveMemoryOrganizer:
    """Get or create the global AdaptiveMemoryOrganizer instance."""
    global _organizer
    if _organizer is None:
        with _organizer_lock:
            if _organizer is None:
                _organizer = AdaptiveMemoryOrganizer(
                    persistence_path=persistence_path,
                )
    return _organizer


def reset_adaptive_memory_organizer() -> None:
    """Reset the global instance (for testing)."""
    global _organizer
    _organizer = None
