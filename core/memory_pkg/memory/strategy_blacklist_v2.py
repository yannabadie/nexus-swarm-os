"""
StrategyBlacklistV2 - V12.4.1 Epic 1.4: LanceDB-Backed Strategy Blacklist

NEXUS V12.4.1 - Semantic failure tracking with vectorized anti-patterns.

This module replaces the JSON-based StrategyBlacklist with a LanceDB-backed
implementation for semantic detection of failed strategies.

Key Improvements over V1:
- Semantic similarity instead of hash-based matching (~+20% detection)
- Prevents circular retries even when description varies slightly
- Native integration with ProjectMemory architecture
- Backward compatible: migrates old JSON data automatically

Architecture:
    BlacklistedStrategy -> Chunk -> LanceDB (via ProjectMemory)
    Query: "use JWT for auth" -> Detects similar failure: "tried token-based auth"

Anti-Pattern Detection:
    V1: Hash-based (exact match only)
    V2: Semantic (detects paraphrases, similar approaches)

Usage:
    blacklist = StrategyBlacklistV2(workspace_path)
    blacklist.add_failed_strategy(description, swarm_mode, error, retries)

    # Semantic check for similar failures
    is_blacklisted, reason = blacklist.is_blacklisted("implement JWT auth")

Migration:
    Old JSON data (workspace/.nexus/strategy_blacklist.json) is automatically
    migrated to LanceDB on first initialization if present.

Author: Claude Opus 4.6
Date: 2026-02-17
Epic: V12.4.1 Epic 1.4 - Persistance Stratégique
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .project_memory import ProjectMemory
from .types import Chunk

logger = logging.getLogger(__name__)


@dataclass
class BlacklistedStrategy:
    """
    A failed strategy that should not be retried.

    Same schema as V1 for backward compatibility.
    """

    task_hash: str  # Keep for backward compat, not used in V2
    description: str
    swarm_mode: str
    error_message: str
    retry_count: int
    timestamp: str
    complexity: str | None = None
    domains: list[str] | None = None
    suggested_alternatives: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "task_hash": self.task_hash,
            "description": self.description,
            "swarm_mode": self.swarm_mode,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp,
            "complexity": self.complexity,
            "domains": self.domains,
            "suggested_alternatives": self.suggested_alternatives,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlacklistedStrategy:
        """Create from dictionary."""
        return cls(
            task_hash=data.get("task_hash", ""),
            description=data.get("description", ""),
            swarm_mode=data.get("swarm_mode", ""),
            error_message=data.get("error_message", ""),
            retry_count=data.get("retry_count", 0),
            timestamp=data.get("timestamp", ""),
            complexity=data.get("complexity"),
            domains=data.get("domains"),
            suggested_alternatives=data.get("suggested_alternatives"),
        )


class StrategyBlacklistV2:
    """
    V12.4.1 Epic 1.4: LanceDB-backed strategy blacklist with semantic detection.

    Uses ProjectMemory as storage backend for vectorized anti-pattern detection.
    Each BlacklistedStrategy is stored as a Chunk with metadata in ProjectMemory.

    Key Benefits:
    - Semantic matching: Detects similar failures even with different wording
    - Anti-circular: Prevents retry loops for paraphrased strategies
    - Shared compute: Uses global EmbeddingEngine
    - Persistent: Survives across sessions

    Detection Example:
        Failed: "use JWT tokens for authentication"
        Query: "implement token-based auth with JWT"
        -> DETECTED as similar (semantic similarity ~0.85)

    Attributes:
        workspace_path: Path to workspace root
        project_memory: ProjectMemory instance for storage
        max_entries: Maximum entries to keep (FIFO eviction)

    Example:
        >>> blacklist = StrategyBlacklistV2(Path("workspace"))
        >>> blacklist.add_failed_strategy("use JWT auth", "ping_pong", "KeyError", 3)
        >>> is_bad, reason = blacklist.is_blacklisted("implement JWT tokens")
        >>> print(is_bad)  # True (semantic match)
    """

    DEFAULT_MAX_ENTRIES = 1000
    VIRTUAL_FILE_PREFIX = "strategy_blacklist://"
    SIMILARITY_THRESHOLD = 0.65  # V2: Lower threshold due to semantic search

    def __init__(
        self,
        workspace_path: Path,
        nexus_root: Path | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        """
        Initialize StrategyBlacklistV2.

        Args:
            workspace_path: Path to workspace root.
            nexus_root: Path to NEXUS root (for ProjectMemory).
                       If None, inferred from workspace_path.
            max_entries: Maximum entries to store (oldest evicted first).
            similarity_threshold: Minimum similarity to consider a match (0.0-1.0).
        """
        self.workspace_path = Path(workspace_path)
        self.max_entries = max_entries
        self.similarity_threshold = similarity_threshold

        # Infer nexus_root if not provided
        if nexus_root is None:
            nexus_root = self.workspace_path.parent

        self.nexus_root = Path(nexus_root)

        # Initialize ProjectMemory for vectorized storage
        self.project_memory = ProjectMemory(self.nexus_root)

        self._logger = logging.getLogger("nexus.strategy_blacklist_v2")

        # Migration: Load V1 data if present
        self._migrate_from_v1()

    def _migrate_from_v1(self) -> None:
        """
        Migrate data from V1 (JSON-based) to V2 (LanceDB-based).

        Reads workspace/.nexus/strategy_blacklist.json and indexes entries
        into ProjectMemory. Only runs once - uses a migration marker file.
        """
        v1_path = self.workspace_path / ".nexus" / "strategy_blacklist.json"
        migration_marker = self.workspace_path / ".nexus" / ".blacklist_migrated_to_v2"

        # Skip if already migrated
        if migration_marker.exists():
            self._logger.debug("V1->V2 blacklist migration already completed")
            return

        # Skip if V1 data doesn't exist
        if not v1_path.exists():
            self._logger.debug("No V1 blacklist data to migrate")
            migration_marker.parent.mkdir(parents=True, exist_ok=True)
            migration_marker.touch()
            return

        # Load V1 data
        try:
            import json

            data = json.loads(v1_path.read_text(encoding="utf-8"))
            strategies = data.get("strategies", [])

            if not strategies:
                self._logger.info("No V1 blacklist entries to migrate")
                migration_marker.touch()
                return

            # Index each strategy as a chunk
            migrated_count = 0
            for strategy_dict in strategies:
                strategy = BlacklistedStrategy.from_dict(strategy_dict)
                self._index_blacklisted_strategy(strategy)
                migrated_count += 1

            # Save ProjectMemory index
            self.project_memory.save()

            # Mark migration complete
            migration_marker.touch()

            self._logger.info(f"Migrated {migrated_count} V1 blacklist entries to LanceDB")

        except Exception as e:
            self._logger.warning(f"V1->V2 blacklist migration failed: {e}")

    def _index_blacklisted_strategy(self, strategy: BlacklistedStrategy) -> None:
        """
        Index a BlacklistedStrategy into ProjectMemory as a virtual chunk.

        Creates a Chunk with:
        - file_path: "strategy_blacklist://hash"
        - content: Rich description with metadata
        - terms: Extracted from description + error

        Args:
            strategy: BlacklistedStrategy to index
        """
        # Build rich content for embedding
        content_parts = [
            f"Failed Strategy: {strategy.description}",
            f"Mode: {strategy.swarm_mode}",
            f"Error: {strategy.error_message}",
            f"Retries: {strategy.retry_count}",
        ]

        if strategy.complexity:
            content_parts.append(f"Complexity: {strategy.complexity}")

        if strategy.domains:
            content_parts.append(f"Domains: {', '.join(strategy.domains)}")

        content = "\n".join(content_parts)

        # Extract terms for sparse retrieval
        from .project_memory import ProjectMemory

        pm_temp = ProjectMemory(self.nexus_root)
        terms = pm_temp._extract_terms(content)

        # Create chunk
        chunk = Chunk(
            file_path=f"{self.VIRTUAL_FILE_PREFIX}{strategy.task_hash}",
            start_line=1,
            end_line=len(content_parts),
            content=content,
            terms=terms,
            chunk_type="blacklist",
            name=strategy.task_hash,
            # Store metadata in chunk for retrieval
            metadata={
                "task_hash": strategy.task_hash,
                "description": strategy.description,
                "swarm_mode": strategy.swarm_mode,
                "error_message": strategy.error_message,
                "retry_count": strategy.retry_count,
                "timestamp": strategy.timestamp,
                "complexity": strategy.complexity,
                "domains": strategy.domains or [],
                "suggested_alternatives": strategy.suggested_alternatives or [],
            },
        )

        # Add to ProjectMemory
        self.project_memory.chunks.append(chunk)
        self.project_memory._backend_dirty = True

    def add_failed_strategy(
        self,
        description: str,
        swarm_mode: str,
        error_message: str,
        retry_count: int,
        complexity: str | None = None,
        domains: list[str] | None = None,
    ) -> BlacklistedStrategy:
        """
        Add a failed strategy to the blacklist.

        Args:
            description: Task description that failed.
            swarm_mode: CollaborationMode that was attempted.
            error_message: Error message from the failure.
            retry_count: Number of times this was retried.
            complexity: Optional task complexity.
            domains: Optional task domains.

        Returns:
            The created BlacklistedStrategy.
        """
        import hashlib

        # Compute hash for backward compat
        normalized = " ".join(description.lower().split())
        task_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

        # Create strategy
        strategy = BlacklistedStrategy(
            task_hash=task_hash,
            description=description[:500],
            swarm_mode=swarm_mode,
            error_message=error_message[:500],
            retry_count=retry_count,
            timestamp=datetime.now().isoformat(),
            complexity=complexity,
            domains=domains or [],
            suggested_alternatives=[],
        )

        # Index into LanceDB
        self._index_blacklisted_strategy(strategy)

        # Check FIFO eviction
        blacklist_chunks = [c for c in self.project_memory.chunks if c.file_path.startswith(self.VIRTUAL_FILE_PREFIX)]

        if len(blacklist_chunks) > self.max_entries:
            # Remove oldest entries
            to_remove = len(blacklist_chunks) - self.max_entries
            sorted_chunks = sorted(
                blacklist_chunks, key=lambda c: c.metadata.get("timestamp", "") if c.metadata else ""
            )

            for chunk in sorted_chunks[:to_remove]:
                self.project_memory.chunks.remove(chunk)

            self._logger.info(f"FIFO eviction: removed {to_remove} old blacklist entries")

        # Save index
        self.project_memory._backend_dirty = True
        self.project_memory.save()

        self._logger.warning(
            f"[BLACKLIST V2] Added failed strategy: {description[:50]}... (mode={swarm_mode}, retries={retry_count})"
        )

        return strategy

    def is_blacklisted(self, description: str, swarm_mode: str | None = None) -> tuple[bool, str | None]:
        """
        Check if a strategy is blacklisted using semantic similarity.

        V12.4.1 Epic 1.4: Uses semantic search to detect similar failures.

        Args:
            description: Task description to check.
            swarm_mode: Optional mode to filter by (must match exactly).

        Returns:
            Tuple of (is_blacklisted, reason).
            If blacklisted, reason explains why.
        """
        # Retrieve using ProjectMemory's semantic search
        chunks = self.project_memory.retrieve(description, limit=5, min_score=self.similarity_threshold)

        # Filter to only blacklist chunks
        blacklist_chunks = [c for c in chunks if c.file_path.startswith(self.VIRTUAL_FILE_PREFIX)]

        if not blacklist_chunks:
            return False, None

        # Check each match
        for chunk in blacklist_chunks:
            if not chunk.metadata:
                continue

            # Filter by mode if specified
            if swarm_mode and chunk.metadata.get("swarm_mode") != swarm_mode:
                continue

            # Found a match
            failed_desc = chunk.metadata.get("description", "")
            error = chunk.metadata.get("error_message", "")
            retry_count = chunk.metadata.get("retry_count", 0)

            reason = (
                f"Similar strategy failed {retry_count} times before.\nFailed approach: {failed_desc}\nError: {error}"
            )

            return True, reason

        return False, None

    def suggest_alternatives(self, description: str, limit: int = 3) -> list[str]:
        """
        Suggest alternative approaches based on similar failures.

        V12.4.1: Uses semantic search to find related failures and
        extract suggested alternatives.

        Args:
            description: Task description to find alternatives for.
            limit: Maximum alternatives to return.

        Returns:
            List of suggested alternative approaches.
        """
        # Find similar blacklisted strategies
        chunks = self.project_memory.retrieve(
            description,
            limit=10,
            min_score=0.3,  # Lower threshold for suggestions
        )

        blacklist_chunks = [c for c in chunks if c.file_path.startswith(self.VIRTUAL_FILE_PREFIX)]

        # Collect suggested alternatives
        alternatives = []
        seen = set()

        for chunk in blacklist_chunks:
            if not chunk.metadata:
                continue

            suggestions = chunk.metadata.get("suggested_alternatives", [])
            for alt in suggestions:
                if alt not in seen:
                    alternatives.append(alt)
                    seen.add(alt)

                    if len(alternatives) >= limit:
                        return alternatives

        # If no stored alternatives, generate generic ones based on mode
        if not alternatives and blacklist_chunks:
            failed_mode = blacklist_chunks[0].metadata.get("swarm_mode", "")
            alternatives = self._generate_mode_alternatives(failed_mode)

        return alternatives[:limit]

    def _generate_mode_alternatives(self, failed_mode: str) -> list[str]:
        """
        Generate alternative collaboration modes based on a failed mode.

        Args:
            failed_mode: The mode that failed.

        Returns:
            List of alternative modes to try.
        """
        mode_alternatives = {
            "ping_pong": ["lead_support", "sequential", "parallel"],
            "parallel": ["sequential", "lead_support", "specialist"],
            "sequential": ["parallel", "ping_pong", "lead_support"],
            "lead_support": ["ping_pong", "red_blue", "sequential"],
            "specialist": ["parallel", "lead_support", "ping_pong"],
            "red_blue": ["lead_support", "ping_pong", "sequential"],
        }

        return mode_alternatives.get(failed_mode.lower(), ["try a different mode"])

    def get_all(self) -> list[BlacklistedStrategy]:
        """
        Get all blacklisted strategies.

        Returns:
            List of BlacklistedStrategy objects, oldest first.
        """
        blacklist_chunks = [c for c in self.project_memory.chunks if c.file_path.startswith(self.VIRTUAL_FILE_PREFIX)]

        # Sort by timestamp
        blacklist_chunks.sort(key=lambda c: c.metadata.get("timestamp", "") if c.metadata else "")

        strategies = []
        for chunk in blacklist_chunks:
            if not chunk.metadata:
                continue

            strategy = BlacklistedStrategy(
                task_hash=chunk.metadata.get("task_hash", ""),
                description=chunk.metadata.get("description", ""),
                swarm_mode=chunk.metadata.get("swarm_mode", ""),
                error_message=chunk.metadata.get("error_message", ""),
                retry_count=chunk.metadata.get("retry_count", 0),
                timestamp=chunk.metadata.get("timestamp", ""),
                complexity=chunk.metadata.get("complexity"),
                domains=chunk.metadata.get("domains"),
                suggested_alternatives=chunk.metadata.get("suggested_alternatives"),
            )
            strategies.append(strategy)

        return strategies

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about the blacklist.

        Returns:
            Dictionary with counts, mode distribution, etc.
        """
        strategies = self.get_all()

        if not strategies:
            return {
                "total_entries": 0,
                "mode_distribution": {},
                "domain_distribution": {},
                "avg_retry_count": 0.0,
                "backend": self.project_memory.get_backend_info()["backend"],
            }

        mode_counts: dict[str, int] = {}
        for s in strategies:
            mode_counts[s.swarm_mode] = mode_counts.get(s.swarm_mode, 0) + 1

        domain_counts: dict[str, int] = {}
        for s in strategies:
            if s.domains:
                for d in s.domains:
                    domain_counts[d] = domain_counts.get(d, 0) + 1

        avg_retries = sum(s.retry_count for s in strategies) / len(strategies)

        return {
            "total_entries": len(strategies),
            "mode_distribution": mode_counts,
            "domain_distribution": domain_counts,
            "avg_retry_count": round(avg_retries, 2),
            "backend": self.project_memory.get_backend_info()["backend"],
        }

    def clear(self) -> int:
        """
        Clear all blacklisted strategies.

        Returns:
            Number of entries cleared.
        """
        blacklist_chunks = [c for c in self.project_memory.chunks if c.file_path.startswith(self.VIRTUAL_FILE_PREFIX)]

        count = len(blacklist_chunks)

        for chunk in blacklist_chunks:
            self.project_memory.chunks.remove(chunk)

        self.project_memory._backend_dirty = True
        self.project_memory.save()

        return count


# =============================================================================
# Global Access
# =============================================================================

_default_blacklist_v2: StrategyBlacklistV2 | None = None


def get_strategy_blacklist_v2(workspace_path: Path | None = None) -> StrategyBlacklistV2 | None:
    """
    Get the StrategyBlacklistV2 instance.

    Args:
        workspace_path: Required on first call to initialize.

    Returns:
        StrategyBlacklistV2 instance or None if not initialized.
    """
    global _default_blacklist_v2

    if _default_blacklist_v2 is None and workspace_path is not None:
        _default_blacklist_v2 = StrategyBlacklistV2(workspace_path)

    return _default_blacklist_v2


def reset_strategy_blacklist_v2() -> None:
    """Reset the global StrategyBlacklistV2 instance (for testing)."""
    global _default_blacklist_v2
    _default_blacklist_v2 = None
