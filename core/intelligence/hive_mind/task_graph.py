"""
NEXUS V12.4 - Task Graph Decomposer (arXiv:2410.22457)

DAG-based task decomposition with evaluation metrics for multi-agent
orchestration. Breaks complex tasks into subtask graphs and measures
decomposition quality.

Based on: "Advancing Agentic Systems: Dynamic Task Decomposition,
Tool Integration and Evaluation" (arXiv:2410.22457)

Three evaluation metrics:
1. Node F1: Node-level accuracy (are the right subtasks identified?)
2. Structural Similarity Index: Topology matching
3. Tool F1: Tool selection accuracy

Usage:
    graph = TaskGraph()
    graph.add_node("analyze", description="Analyze codebase structure")
    graph.add_node("plan", description="Plan architecture changes")
    graph.add_node("implement", description="Implement changes")
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "implement")

    # Validate DAG properties
    assert graph.is_valid_dag()

    # Get execution order
    order = graph.topological_sort()

    # Evaluate decomposition quality
    evaluator = get_graph_evaluator()
    metrics = evaluator.evaluate(graph, reference_graph)
"""

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class NodeStatus(Enum):
    """Status of a task graph node."""

    PENDING = "pending"
    READY = "ready"  # All dependencies satisfied
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """A node in the task decomposition graph."""

    node_id: str
    description: str = ""
    agent_id: str = ""  # Assigned agent
    tool_name: str = ""  # Primary tool needed
    estimated_duration: float = 0.0
    status: NodeStatus = NodeStatus.PENDING
    priority: int = 0  # Higher = more important
    metadata: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """Whether this node has no outgoing edges (set externally)."""
        return self.metadata.get("is_terminal", False)


@dataclass
class GraphMetrics:
    """Evaluation metrics for task graph decomposition."""

    node_f1: float  # Node-level F1 score
    structural_similarity: float  # Topology similarity index
    tool_f1: float  # Tool selection F1 score
    composite: float  # Weighted combination

    @property
    def is_good(self) -> bool:
        """Whether the decomposition quality is acceptable."""
        return self.composite >= 0.6


@dataclass
class GraphStats:
    """Statistics about a task graph."""

    total_nodes: int
    total_edges: int
    max_depth: int
    max_parallelism: int  # Max nodes executable in parallel
    critical_path_length: int  # Length of longest path
    leaf_nodes: int
    root_nodes: int


@dataclass
class EvaluatorStats:
    """Statistics for the graph evaluator."""

    total_evaluations: int
    avg_node_f1: float
    avg_structural_similarity: float
    avg_tool_f1: float


# =============================================================================
# Task Graph (DAG)
# =============================================================================


class TaskGraph:
    """
    Directed Acyclic Graph for task decomposition.

    Nodes represent subtasks, edges represent dependencies.
    Supports topological sorting, parallelism analysis, and
    critical path computation.
    """

    def __init__(self):
        self._nodes: dict[str, TaskNode] = {}
        self._edges: set[tuple[str, str]] = set()  # (from, to)
        self._adjacency: dict[str, set[str]] = defaultdict(set)
        self._reverse_adj: dict[str, set[str]] = defaultdict(set)

    # -------------------------------------------------------------------------
    # Graph Construction
    # -------------------------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        description: str = "",
        agent_id: str = "",
        tool_name: str = "",
        priority: int = 0,
    ) -> TaskNode:
        """Add a node (subtask) to the graph."""
        node = TaskNode(
            node_id=node_id,
            description=description,
            agent_id=agent_id,
            tool_name=tool_name,
            priority=priority,
        )
        self._nodes[node_id] = node
        return node

    def add_edge(self, from_id: str, to_id: str) -> bool:
        """
        Add a dependency edge (from_id must complete before to_id).

        Returns False if the edge would create a cycle.
        """
        if from_id not in self._nodes or to_id not in self._nodes:
            return False

        if from_id == to_id:
            return False

        # Check if adding this edge creates a cycle
        self._edges.add((from_id, to_id))
        self._adjacency[from_id].add(to_id)
        self._reverse_adj[to_id].add(from_id)

        if not self.is_valid_dag():
            # Rollback
            self._edges.discard((from_id, to_id))
            self._adjacency[from_id].discard(to_id)
            self._reverse_adj[to_id].discard(from_id)
            return False

        return True

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges."""
        if node_id not in self._nodes:
            return False

        # Remove edges
        edges_to_remove = [(f, t) for f, t in self._edges if f == node_id or t == node_id]
        for f, t in edges_to_remove:
            self._edges.discard((f, t))
            self._adjacency[f].discard(t)
            self._reverse_adj[t].discard(f)

        del self._nodes[node_id]
        self._adjacency.pop(node_id, None)
        self._reverse_adj.pop(node_id, None)

        return True

    # -------------------------------------------------------------------------
    # Graph Analysis
    # -------------------------------------------------------------------------

    def is_valid_dag(self) -> bool:
        """Check if the graph is a valid DAG (no cycles)."""
        # Kahn's algorithm
        in_degree = {nid: 0 for nid in self._nodes}
        for _, to_id in self._edges:
            in_degree[to_id] = in_degree.get(to_id, 0) + 1

        queue = deque(nid for nid, d in in_degree.items() if d == 0)
        visited = 0

        temp_in = dict(in_degree)
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in self._adjacency.get(node, set()):
                temp_in[neighbor] -= 1
                if temp_in[neighbor] == 0:
                    queue.append(neighbor)

        return visited == len(self._nodes)

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order (dependency-respecting)."""
        in_degree = {nid: 0 for nid in self._nodes}
        for _, to_id in self._edges:
            in_degree[to_id] = in_degree.get(to_id, 0) + 1

        queue = deque(
            sorted(
                (nid for nid, d in in_degree.items() if d == 0),
                key=lambda x: self._nodes[x].priority,
                reverse=True,
            )
        )
        result = []
        temp_in = dict(in_degree)

        while queue:
            node = queue.popleft()
            result.append(node)
            neighbors = sorted(
                self._adjacency.get(node, set()),
                key=lambda x: self._nodes[x].priority,
                reverse=True,
            )
            for neighbor in neighbors:
                temp_in[neighbor] -= 1
                if temp_in[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def get_ready_nodes(self) -> list[str]:
        """Get nodes whose dependencies are all completed."""
        ready = []
        for nid, node in self._nodes.items():
            if node.status != NodeStatus.PENDING:
                continue
            deps = self._reverse_adj.get(nid, set())
            if all(self._nodes[d].status == NodeStatus.COMPLETED for d in deps if d in self._nodes):
                ready.append(nid)
        return ready

    def get_parallel_groups(self) -> list[list[str]]:
        """Get groups of nodes that can execute in parallel (levels)."""
        order = self.topological_sort()
        if not order:
            return []

        # Assign levels: level of node = max(level of predecessors) + 1
        levels: dict[str, int] = {}
        for nid in order:
            deps = self._reverse_adj.get(nid, set())
            if not deps:
                levels[nid] = 0
            else:
                levels[nid] = max(levels.get(d, 0) for d in deps) + 1

        # Group by level
        groups: dict[int, list[str]] = defaultdict(list)
        for nid, level in levels.items():
            groups[level].append(nid)

        return [groups[i] for i in sorted(groups.keys())]

    def get_critical_path(self) -> list[str]:
        """Get the longest path through the graph (critical path)."""
        order = self.topological_sort()
        if not order:
            return []

        # Longest path using topological order
        dist: dict[str, int] = {nid: 0 for nid in self._nodes}
        parent: dict[str, str | None] = {nid: None for nid in self._nodes}

        for nid in order:
            for neighbor in self._adjacency.get(nid, set()):
                if dist[nid] + 1 > dist[neighbor]:
                    dist[neighbor] = dist[nid] + 1
                    parent[neighbor] = nid

        # Find end of critical path
        end_node = max(dist, key=dist.get)
        path = []
        current: str | None = end_node
        while current is not None:
            path.append(current)
            current = parent[current]
        path.reverse()

        return path

    def get_stats(self) -> GraphStats:
        """Get graph statistics."""
        root_nodes = [nid for nid in self._nodes if not self._reverse_adj.get(nid)]
        leaf_nodes = [nid for nid in self._nodes if not self._adjacency.get(nid)]
        groups = self.get_parallel_groups()
        max_parallel = max((len(g) for g in groups), default=0)
        critical = self.get_critical_path()

        return GraphStats(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            max_depth=len(groups),
            max_parallelism=max_parallel,
            critical_path_length=len(critical),
            leaf_nodes=len(leaf_nodes),
            root_nodes=len(root_nodes),
        )

    @property
    def nodes(self) -> dict[str, TaskNode]:
        return dict(self._nodes)

    @property
    def edges(self) -> set[tuple[str, str]]:
        return set(self._edges)

    def __len__(self) -> int:
        return len(self._nodes)


# =============================================================================
# Graph Evaluator
# =============================================================================


class TaskGraphEvaluator:
    """
    Evaluates task decomposition quality using three metrics
    from arXiv:2410.22457.

    1. Node F1: Measures if the right subtasks were identified
    2. Structural Similarity: Measures topology matching
    3. Tool F1: Measures tool assignment accuracy
    """

    NODE_F1_WEIGHT = 0.4
    STRUCTURAL_WEIGHT = 0.35
    TOOL_F1_WEIGHT = 0.25

    def __init__(self):
        self._total_evaluations = 0
        self._node_f1_sum = 0.0
        self._structural_sum = 0.0
        self._tool_f1_sum = 0.0
        self._lock = threading.Lock()

    def evaluate(
        self,
        predicted: TaskGraph,
        reference: TaskGraph,
    ) -> GraphMetrics:
        """
        Evaluate a predicted task graph against a reference.

        Args:
            predicted: The generated task decomposition
            reference: The ground-truth decomposition

        Returns:
            GraphMetrics with F1 scores and structural similarity
        """
        node_f1 = self._compute_node_f1(predicted, reference)
        structural = self._compute_structural_similarity(predicted, reference)
        tool_f1 = self._compute_tool_f1(predicted, reference)

        composite = self.NODE_F1_WEIGHT * node_f1 + self.STRUCTURAL_WEIGHT * structural + self.TOOL_F1_WEIGHT * tool_f1

        with self._lock:
            self._total_evaluations += 1
            self._node_f1_sum += node_f1
            self._structural_sum += structural
            self._tool_f1_sum += tool_f1

        return GraphMetrics(
            node_f1=node_f1,
            structural_similarity=structural,
            tool_f1=tool_f1,
            composite=composite,
        )

    def get_stats(self) -> EvaluatorStats:
        """Get evaluator statistics."""
        n = max(self._total_evaluations, 1)
        return EvaluatorStats(
            total_evaluations=self._total_evaluations,
            avg_node_f1=self._node_f1_sum / n,
            avg_structural_similarity=self._structural_sum / n,
            avg_tool_f1=self._tool_f1_sum / n,
        )

    # -------------------------------------------------------------------------
    # Metric Computation
    # -------------------------------------------------------------------------

    def _compute_node_f1(self, predicted: TaskGraph, reference: TaskGraph) -> float:
        """Compute Node F1 score (node-level accuracy)."""
        pred_ids = set(predicted.nodes.keys())
        ref_ids = set(reference.nodes.keys())

        if not pred_ids and not ref_ids:
            return 1.0
        if not pred_ids or not ref_ids:
            return 0.0

        tp = len(pred_ids & ref_ids)
        fp = len(pred_ids - ref_ids)
        fn = len(ref_ids - pred_ids)

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)

        if precision + recall == 0:
            return 0.0

        return 2 * precision * recall / (precision + recall)

    def _compute_structural_similarity(self, predicted: TaskGraph, reference: TaskGraph) -> float:
        """Compute Structural Similarity Index (topology matching)."""
        pred_edges = predicted.edges
        ref_edges = reference.edges

        if not pred_edges and not ref_edges:
            return 1.0
        if not pred_edges or not ref_edges:
            return 0.0

        # Edge-level F1
        tp = len(pred_edges & ref_edges)
        fp = len(pred_edges - ref_edges)
        fn = len(ref_edges - pred_edges)

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)

        if precision + recall == 0:
            return 0.0

        edge_f1 = 2 * precision * recall / (precision + recall)

        # Depth similarity
        pred_groups = predicted.get_parallel_groups()
        ref_groups = reference.get_parallel_groups()
        depth_sim = 1.0 - abs(len(pred_groups) - len(ref_groups)) / max(len(pred_groups), len(ref_groups), 1)

        return edge_f1 * 0.7 + depth_sim * 0.3

    def _compute_tool_f1(self, predicted: TaskGraph, reference: TaskGraph) -> float:
        """Compute Tool F1 score (tool selection accuracy)."""
        # Match tools for nodes that exist in both graphs
        common_nodes = set(predicted.nodes.keys()) & set(reference.nodes.keys())

        if not common_nodes:
            return 0.0

        matches = 0
        total = len(common_nodes)

        for nid in common_nodes:
            pred_tool = predicted.nodes[nid].tool_name
            ref_tool = reference.nodes[nid].tool_name
            if pred_tool and ref_tool and pred_tool == ref_tool:
                matches += 1
            elif not pred_tool and not ref_tool:
                matches += 1  # Both have no tool = match

        return matches / max(total, 1)


# =============================================================================
# Singleton
# =============================================================================

_evaluator_instance: TaskGraphEvaluator | None = None
_evaluator_lock = threading.Lock()


def get_graph_evaluator() -> TaskGraphEvaluator:
    """Get or create the singleton TaskGraphEvaluator instance."""
    global _evaluator_instance
    if _evaluator_instance is None:
        with _evaluator_lock:
            if _evaluator_instance is None:
                _evaluator_instance = TaskGraphEvaluator()
    return _evaluator_instance


def reset_graph_evaluator() -> None:
    """Reset the singleton (for testing)."""
    global _evaluator_instance
    _evaluator_instance = None
