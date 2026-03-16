"""
Workflow Dependency Graph - DAG topology for workflow steps.

V12.4 COGNITIVE BOOST

Provides directed acyclic graph (DAG) analysis for workflow steps:
- Define steps with dependencies
- Detect cycles (reject invalid workflows)
- Compute execution order (topological sort)
- Identify parallelizable groups
- Find critical path

Usage:
    from core.workflow.dependency_graph import get_dependency_graph

    graph = get_dependency_graph()
    graph.add_node("fetch_data")
    graph.add_node("transform", depends_on=["fetch_data"])
    graph.add_node("validate", depends_on=["fetch_data"])
    graph.add_node("store", depends_on=["transform", "validate"])

    order = graph.execution_order()
    groups = graph.parallel_groups()
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_NODES = 10000
MAX_EDGES = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class WorkflowNode:
    """A step in a workflow DAG."""

    node_id: str
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    estimated_duration: float = 0.0  # seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label or self.node_id,
            "estimated_duration": self.estimated_duration,
            "metadata": self.metadata,
        }


@dataclass
class WorkflowEdge:
    """A dependency edge: source must complete before target."""

    source: str  # dependency (must finish first)
    target: str  # dependent (waits for source)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target}


@dataclass
class ExecutionOrder:
    """Result of topological sort."""

    steps: list[str]
    parallel_groups: list[list[str]]  # Groups that can run concurrently
    critical_path: list[str]
    critical_path_duration: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "parallel_groups": self.parallel_groups,
            "critical_path": self.critical_path,
            "critical_path_duration": self.critical_path_duration,
        }


@dataclass
class GraphStats:
    """Graph statistics."""

    node_count: int
    edge_count: int
    root_count: int
    leaf_count: int
    max_depth: int
    has_cycle: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "root_count": self.root_count,
            "leaf_count": self.leaf_count,
            "max_depth": self.max_depth,
            "has_cycle": self.has_cycle,
        }


# =============================================================================
# Dependency Graph
# =============================================================================


class WorkflowDependencyGraph:
    """
    DAG for workflow step dependencies.

    Features:
    - Add/remove nodes and edges
    - Cycle detection
    - Topological sort (execution order)
    - Parallel group identification
    - Critical path analysis
    - Thread-safe
    """

    def __init__(self):
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: dict[str, set[str]] = {}  # node_id -> set of dependencies (predecessors)
        self._reverse_edges: dict[str, set[str]] = {}  # node_id -> set of dependents (successors)
        self._lock = threading.Lock()

    # =========================================================================
    # Node Operations
    # =========================================================================

    def add_node(
        self,
        node_id: str,
        *,
        label: str = "",
        depends_on: list[str] | None = None,
        estimated_duration: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Add a node to the graph.

        Args:
            node_id: Unique identifier
            label: Human-readable label
            depends_on: List of node IDs this node depends on
            estimated_duration: Estimated execution time in seconds
            metadata: Arbitrary metadata

        Returns:
            True if added, False if already exists or at limit
        """
        with self._lock:
            if node_id in self._nodes:
                return False
            if len(self._nodes) >= MAX_NODES:
                return False

            node = WorkflowNode(
                node_id=node_id,
                label=label or node_id,
                estimated_duration=estimated_duration,
                metadata=metadata or {},
            )
            self._nodes[node_id] = node
            self._edges[node_id] = set()
            self._reverse_edges.setdefault(node_id, set())

            # Add dependency edges
            for dep in depends_on or []:
                if dep in self._nodes:
                    self._edges[node_id].add(dep)
                    self._reverse_edges.setdefault(dep, set()).add(node_id)

            return True

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges."""
        with self._lock:
            if node_id not in self._nodes:
                return False

            # Remove from other nodes' dependency lists
            for dep in self._edges.get(node_id, set()):
                self._reverse_edges.get(dep, set()).discard(node_id)

            # Remove nodes that depend on this one
            for dependent in self._reverse_edges.get(node_id, set()):
                self._edges.get(dependent, set()).discard(node_id)

            del self._nodes[node_id]
            self._edges.pop(node_id, None)
            self._reverse_edges.pop(node_id, None)
            return True

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def get_node(self, node_id: str) -> WorkflowNode | None:
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[str]:
        """List all node IDs (sorted)."""
        return sorted(self._nodes.keys())

    # =========================================================================
    # Edge Operations
    # =========================================================================

    def add_edge(self, source: str, target: str) -> bool:
        """
        Add a dependency: target depends on source (source must finish before target).

        Returns False if either node doesn't exist or edge already exists.
        """
        with self._lock:
            if source not in self._nodes or target not in self._nodes:
                return False
            if source == target:
                return False
            if source in self._edges.get(target, set()):
                return False  # Already exists

            self._edges[target].add(source)
            self._reverse_edges.setdefault(source, set()).add(target)
            return True

    def remove_edge(self, source: str, target: str) -> bool:
        """Remove a dependency edge."""
        with self._lock:
            if source not in self._edges.get(target, set()):
                return False
            self._edges[target].discard(source)
            self._reverse_edges.get(source, set()).discard(target)
            return True

    def get_dependencies(self, node_id: str) -> list[str]:
        """Get direct dependencies (predecessors) of a node."""
        return sorted(self._edges.get(node_id, set()))

    def get_dependents(self, node_id: str) -> list[str]:
        """Get direct dependents (successors) of a node."""
        return sorted(self._reverse_edges.get(node_id, set()))

    # =========================================================================
    # Graph Analysis
    # =========================================================================

    def get_roots(self) -> list[str]:
        """Get nodes with no dependencies (entry points)."""
        return sorted(nid for nid in self._nodes if not self._edges.get(nid, set()))

    def get_leaves(self) -> list[str]:
        """Get nodes with no dependents (exit points)."""
        return sorted(nid for nid in self._nodes if not self._reverse_edges.get(nid, set()))

    def has_cycle(self) -> bool:
        """Check if the graph contains a cycle."""
        # Kahn's algorithm: if topo sort doesn't include all nodes, there's a cycle
        in_degree = {nid: len(deps) for nid, deps in self._edges.items()}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            for dependent in self._reverse_edges.get(node, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return visited < len(self._nodes)

    def execution_order(self) -> ExecutionOrder | None:
        """
        Compute execution order via topological sort.

        Returns None if the graph has a cycle.
        """
        # Kahn's algorithm for topological sort
        in_degree = {nid: len(deps) for nid, deps in self._edges.items()}
        queue = sorted(nid for nid, deg in in_degree.items() if deg == 0)
        order: list[str] = []
        groups: list[list[str]] = []

        while queue:
            # Current group = all nodes with in_degree 0
            groups.append(sorted(queue))
            next_queue = []
            for node in queue:
                order.append(node)
                for dependent in self._reverse_edges.get(node, set()):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_queue.append(dependent)
            queue = sorted(next_queue)

        if len(order) < len(self._nodes):
            return None  # Cycle detected

        # Compute critical path
        crit_path, crit_duration = self._compute_critical_path(order)

        return ExecutionOrder(
            steps=order,
            parallel_groups=groups,
            critical_path=crit_path,
            critical_path_duration=crit_duration,
        )

    def _compute_critical_path(self, topo_order: list[str]) -> tuple[list[str], float]:
        """Compute the critical path (longest path by estimated_duration)."""
        if not topo_order:
            return [], 0.0

        # dist[node] = longest distance to reach this node
        dist: dict[str, float] = {}
        predecessor: dict[str, str] = {}

        for node_id in topo_order:
            node = self._nodes[node_id]
            deps = self._edges.get(node_id, set())
            if not deps:
                dist[node_id] = node.estimated_duration
                predecessor[node_id] = ""
            else:
                max_dep_dist = 0.0
                max_dep = ""
                for dep in deps:
                    if dist.get(dep, 0.0) > max_dep_dist:
                        max_dep_dist = dist[dep]
                        max_dep = dep
                dist[node_id] = max_dep_dist + node.estimated_duration
                predecessor[node_id] = max_dep

        if not dist:
            return [], 0.0

        # Find the end node with maximum distance
        end_node = max(dist, key=lambda n: dist[n])
        crit_duration = dist[end_node]

        # Trace back the path
        path = []
        current = end_node
        while current:
            path.append(current)
            current = predecessor.get(current, "")
        path.reverse()

        return path, crit_duration

    def parallel_groups(self) -> list[list[str]] | None:
        """Get groups of nodes that can execute in parallel. Returns None if cycle."""
        result = self.execution_order()
        if result is None:
            return None
        return result.parallel_groups

    def depth(self, node_id: str) -> int:
        """Get the depth of a node (longest path from a root)."""
        if node_id not in self._nodes:
            return -1
        deps = self._edges.get(node_id, set())
        if not deps:
            return 0
        return 1 + max(self.depth(dep) for dep in deps)

    def max_depth(self) -> int:
        """Get the maximum depth of the graph."""
        if not self._nodes:
            return 0
        return max(self.depth(nid) for nid in self._nodes)

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> GraphStats:
        edge_count = sum(len(deps) for deps in self._edges.values())
        return GraphStats(
            node_count=len(self._nodes),
            edge_count=edge_count,
            root_count=len(self.get_roots()),
            leaf_count=len(self.get_leaves()),
            max_depth=self.max_depth(),
            has_cycle=self.has_cycle(),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(deps) for deps in self._edges.values())

    def clear(self) -> None:
        """Clear all nodes and edges."""
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
            self._reverse_edges.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_graph: WorkflowDependencyGraph | None = None
_graph_lock = threading.Lock()


def get_dependency_graph() -> WorkflowDependencyGraph:
    """Get or create the global dependency graph."""
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = WorkflowDependencyGraph()
    return _graph


def reset_dependency_graph() -> None:
    """Reset the global dependency graph (for testing)."""
    global _graph
    _graph = None
