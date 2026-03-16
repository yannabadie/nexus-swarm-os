"""
Mutation Tracker - Record and query agent mutation genealogy.

V12.4 COGNITIVE BOOST - Task #61

Tracks all agent mutations including parent-child relationships,
mutation strategies used, and performance comparisons between variants.

Usage:
    from core.intelligence.evolution.mutation_tracker import get_mutation_tracker

    tracker = get_mutation_tracker()

    # Record a mutation
    tracker.record_mutation(
        parent_id="claude_v1",
        child_id="claude_v1a",
        strategy="code_specialist",
        metadata={"domain": "python"},
    )

    # Query lineage
    children = tracker.get_children("claude_v1")
    ancestors = tracker.get_ancestors("claude_v1a")

    # Record performance
    tracker.record_performance("claude_v1a", task_success=True, score=0.92)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_MUTATIONS = 10000
LEARNING_RATE = 0.1  # EMA for performance tracking


# =============================================================================
# Types
# =============================================================================


@dataclass
class MutationRecord:
    """A single mutation event."""

    parent_id: str
    child_id: str
    strategy: str
    generation: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "strategy": self.strategy,
            "generation": self.generation,
            "metadata": self.metadata,
        }


@dataclass
class AgentPerformance:
    """Performance metrics for an agent."""

    agent_id: str
    total_tasks: int = 0
    successful_tasks: int = 0
    avg_score: float = 0.0
    scores: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks

    @property
    def latest_score(self) -> float:
        return self.scores[-1] if self.scores else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": round(self.success_rate, 4),
            "avg_score": round(self.avg_score, 4),
            "latest_score": round(self.latest_score, 4),
        }


@dataclass
class LineageNode:
    """A node in the mutation tree."""

    agent_id: str
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    strategy: str = ""
    generation: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "parent_id": self.parent_id,
            "children": self.children,
            "strategy": self.strategy,
            "generation": self.generation,
        }


@dataclass
class VariantComparison:
    """Comparison between sibling variants."""

    parent_id: str
    variants: dict[str, float]  # agent_id -> avg_score
    best_variant: str
    worst_variant: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "variants": {k: round(v, 4) for k, v in self.variants.items()},
            "best_variant": self.best_variant,
            "worst_variant": self.worst_variant,
        }


@dataclass
class TrackerStats:
    """Mutation tracker statistics."""

    total_mutations: int
    total_agents: int
    root_agents: int
    max_generation: int
    total_performance_records: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_mutations": self.total_mutations,
            "total_agents": self.total_agents,
            "root_agents": self.root_agents,
            "max_generation": self.max_generation,
            "total_performance_records": self.total_performance_records,
        }


# =============================================================================
# Mutation Tracker
# =============================================================================


class MutationTracker:
    """
    Tracks agent mutation genealogy and performance.

    Features:
    - Parent-child mutation recording
    - Lineage tree traversal (ancestors, descendants)
    - Per-agent performance tracking
    - Sibling variant comparison
    - Generation tracking
    - Rollback version lookup
    """

    def __init__(self, *, max_mutations: int = MAX_MUTATIONS):
        self._mutations: list[MutationRecord] = []
        self._nodes: dict[str, LineageNode] = {}
        self._performance: dict[str, AgentPerformance] = {}
        self._max_mutations = max_mutations
        self._lock = threading.Lock()

    # =========================================================================
    # Record Mutations
    # =========================================================================

    def record_mutation(
        self,
        parent_id: str,
        child_id: str,
        strategy: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> MutationRecord:
        """
        Record a mutation event.

        Args:
            parent_id: Parent agent identifier
            child_id: Child agent identifier
            strategy: Mutation strategy used
            metadata: Additional mutation context

        Returns:
            The recorded MutationRecord
        """
        with self._lock:
            # Ensure parent node exists
            if parent_id not in self._nodes:
                self._nodes[parent_id] = LineageNode(agent_id=parent_id, generation=0)

            parent_node = self._nodes[parent_id]
            generation = parent_node.generation + 1

            record = MutationRecord(
                parent_id=parent_id,
                child_id=child_id,
                strategy=strategy,
                generation=generation,
                metadata=metadata or {},
            )

            self._mutations.append(record)

            # Update parent
            if child_id not in parent_node.children:
                parent_node.children.append(child_id)

            # Create/update child node
            self._nodes[child_id] = LineageNode(
                agent_id=child_id,
                parent_id=parent_id,
                strategy=strategy,
                generation=generation,
            )

            # Enforce limit
            while len(self._mutations) > self._max_mutations:
                self._mutations.pop(0)

        return record

    # =========================================================================
    # Lineage Queries
    # =========================================================================

    def get_children(self, agent_id: str) -> list[str]:
        """Get direct children of an agent."""
        with self._lock:
            node = self._nodes.get(agent_id)
            return list(node.children) if node else []

    def get_parent(self, agent_id: str) -> str | None:
        """Get parent of an agent."""
        with self._lock:
            node = self._nodes.get(agent_id)
            return node.parent_id if node else None

    def get_ancestors(self, agent_id: str) -> list[str]:
        """Get all ancestors (oldest first)."""
        ancestors = []
        with self._lock:
            current = agent_id
            visited: set[str] = set()
            while current in self._nodes:
                node = self._nodes[current]
                if node.parent_id is None or node.parent_id in visited:
                    break
                visited.add(node.parent_id)
                ancestors.append(node.parent_id)
                current = node.parent_id
        ancestors.reverse()
        return ancestors

    def get_descendants(self, agent_id: str) -> list[str]:
        """Get all descendants (breadth-first)."""
        descendants = []
        with self._lock:
            queue = list(self._nodes.get(agent_id, LineageNode(agent_id=agent_id)).children)
            visited: set[str] = set()
            while queue:
                child = queue.pop(0)
                if child in visited:
                    continue
                visited.add(child)
                descendants.append(child)
                child_node = self._nodes.get(child)
                if child_node:
                    queue.extend(child_node.children)
        return descendants

    def get_siblings(self, agent_id: str) -> list[str]:
        """Get sibling agents (same parent, excluding self)."""
        with self._lock:
            node = self._nodes.get(agent_id)
            if not node or not node.parent_id:
                return []
            parent = self._nodes.get(node.parent_id)
            if not parent:
                return []
            return [c for c in parent.children if c != agent_id]

    def get_generation(self, agent_id: str) -> int:
        """Get the generation number of an agent."""
        with self._lock:
            node = self._nodes.get(agent_id)
            return node.generation if node else -1

    def get_lineage_node(self, agent_id: str) -> LineageNode | None:
        """Get the lineage node for an agent."""
        return self._nodes.get(agent_id)

    def get_root_agents(self) -> list[str]:
        """Get agents with no parent (root of lineage trees)."""
        with self._lock:
            return sorted(aid for aid, node in self._nodes.items() if node.parent_id is None)

    # =========================================================================
    # Performance
    # =========================================================================

    def record_performance(
        self,
        agent_id: str,
        *,
        task_success: bool = True,
        score: float = 0.0,
    ) -> None:
        """Record a task performance outcome for an agent."""
        with self._lock:
            perf = self._performance.get(agent_id)
            if perf is None:
                perf = AgentPerformance(agent_id=agent_id)
                self._performance[agent_id] = perf

            perf.total_tasks += 1
            if task_success:
                perf.successful_tasks += 1

            perf.scores.append(score)
            if len(perf.scores) > 100:
                perf.scores = perf.scores[-100:]

            # EMA update
            if perf.avg_score == 0.0:
                perf.avg_score = score
            else:
                perf.avg_score = (1 - LEARNING_RATE) * perf.avg_score + LEARNING_RATE * score

    def get_performance(self, agent_id: str) -> AgentPerformance | None:
        """Get performance metrics for an agent."""
        return self._performance.get(agent_id)

    def compare_variants(self, parent_id: str) -> VariantComparison | None:
        """Compare performance of sibling variants from the same parent."""
        children = self.get_children(parent_id)
        if not children:
            return None

        variants: dict[str, float] = {}
        for child_id in children:
            perf = self._performance.get(child_id)
            if perf and perf.total_tasks > 0:
                variants[child_id] = perf.avg_score

        if not variants:
            return None

        best = max(variants, key=variants.get)
        worst = min(variants, key=variants.get)

        return VariantComparison(
            parent_id=parent_id,
            variants=variants,
            best_variant=best,
            worst_variant=worst,
        )

    def get_rollback_version(self, agent_id: str) -> str | None:
        """Get the stable ancestor to roll back to if this agent fails."""
        parent = self.get_parent(agent_id)
        if parent is None:
            return None
        # Check if parent has performance data and is stable
        perf = self._performance.get(parent)
        if perf and perf.success_rate >= 0.5:
            return parent
        # Otherwise try grandparent
        grandparent = self.get_parent(parent)
        return grandparent

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> TrackerStats:
        """Get tracker statistics."""
        with self._lock:
            max_gen = max(
                (n.generation for n in self._nodes.values()),
                default=0,
            )
            root_count = sum(1 for n in self._nodes.values() if n.parent_id is None)
            total_perf = sum(p.total_tasks for p in self._performance.values())

        return TrackerStats(
            total_mutations=len(self._mutations),
            total_agents=len(self._nodes),
            root_agents=root_count,
            max_generation=max_gen,
            total_performance_records=total_perf,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def mutation_count(self) -> int:
        return len(self._mutations)

    @property
    def agent_count(self) -> int:
        return len(self._nodes)

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._mutations.clear()
            self._nodes.clear()
            self._performance.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_count": self.mutation_count,
            "agent_count": self.agent_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_tracker: MutationTracker | None = None
_tracker_lock = threading.Lock()


def get_mutation_tracker() -> MutationTracker:
    """Get or create the global mutation tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = MutationTracker()
    return _tracker


def reset_mutation_tracker() -> None:
    """Reset the global mutation tracker (for testing)."""
    global _tracker
    _tracker = None
