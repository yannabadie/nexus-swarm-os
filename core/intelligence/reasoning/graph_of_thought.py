"""
Graph of Thought (GoT) - Advanced reasoning for complex problem-solving.

V12.4 COGNITIVE BOOST - Non-linear exploration with branching and merging.

Implements graph-based reasoning where thoughts form a DAG:
- ThoughtNode: Individual reasoning step
- ThoughtGraph: DAG of connected thoughts with dependency tracking
- GraphOfThought: Orchestrator that decomposes, executes, and aggregates

Patterns supported:
- Sequential chains (like Chain of Thought)
- Parallel exploration (like Tree of Thought)
- Decision trees (evaluate options)
- Custom DAGs (any dependency structure)

Usage:
    got = GraphOfThought()
    graph = got.decompose_problem(
        "Fix the bug",
        ["Read code", "Find issue", "Implement fix"]
    )

    def executor(node: ThoughtNode) -> str:
        return llm.invoke(node.question)

    result = got.execute(graph, executor)
    print(result.get_final_answer())
"""

from __future__ import annotations

import contextlib
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# =============================================================================
# Enums
# =============================================================================


class ThoughtStatus(Enum):
    """Status of a thought node."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ThoughtType(Enum):
    """Type of reasoning step."""

    ANALYZE = "analyze"
    GENERATE = "generate"
    EVALUATE = "evaluate"
    DECISION = "decision"
    AGGREGATE = "aggregate"
    ROOT = "root"


# =============================================================================
# ThoughtNode
# =============================================================================


@dataclass
class ThoughtNode:
    """
    A single reasoning step in the thought graph.

    Attributes:
        id: Unique identifier (8 char hex)
        name: Human-readable name
        question: The question or task for this node
        thought_type: Type of reasoning
        status: Current execution status
        dependencies: IDs of nodes that must complete before this one
        children: IDs of nodes that depend on this one
        answer: Result after execution
        confidence: Confidence score (0.0-1.0)
        reasoning: Explanation of the answer
        attempts: Number of execution attempts
        max_attempts: Maximum retry attempts
        completed_at: Timestamp of completion
    """

    id: str = ""
    name: str = ""
    question: str = ""
    thought_type: ThoughtType = ThoughtType.ANALYZE
    status: ThoughtStatus = ThoughtStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    answer: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    attempts: int = 0
    max_attempts: int = 3
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]

    def is_ready(self, completed_ids: set[str]) -> bool:
        """Check if all dependencies are satisfied."""
        if not self.dependencies:
            return True
        return all(dep in completed_ids for dep in self.dependencies)

    def mark_completed(
        self,
        answer: str,
        confidence: float = 1.0,
        reasoning: str = "",
    ) -> None:
        """Mark this node as completed with an answer."""
        self.status = ThoughtStatus.COMPLETED
        self.answer = answer
        self.confidence = confidence
        self.reasoning = reasoning
        self.completed_at = datetime.now(UTC).isoformat()

    def mark_failed(self, reason: str = "") -> None:
        """Mark this node as failed."""
        self.status = ThoughtStatus.FAILED
        self.reasoning = reason

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": self.id,
            "name": self.name,
            "question": self.question,
            "thought_type": self.thought_type.value,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "children": self.children,
            "answer": self.answer,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "attempts": self.attempts,
            "completed_at": self.completed_at,
        }


# =============================================================================
# ThoughtGraph
# =============================================================================


class ThoughtGraph:
    """
    Directed acyclic graph of thought nodes.

    Manages node relationships, dependency tracking, and execution ordering.
    """

    def __init__(self, name: str = "thought_graph"):
        self.name = name
        self.nodes: dict[str, ThoughtNode] = {}
        self.created_at: str = datetime.now(UTC).isoformat()

    def add_node(self, node: ThoughtNode) -> str:
        """
        Add a node to the graph.

        Automatically updates parent-child relationships.

        Returns:
            Node ID
        """
        self.nodes[node.id] = node

        # Update parent's children list
        for dep_id in node.dependencies:
            if dep_id in self.nodes:
                parent = self.nodes[dep_id]
                if node.id not in parent.children:
                    parent.children.append(node.id)

        return node.id

    def create_node(
        self,
        question: str,
        name: str = "",
        thought_type: ThoughtType = ThoughtType.ANALYZE,
        dependencies: list[str] | None = None,
    ) -> ThoughtNode:
        """
        Create and add a node to the graph.

        Returns:
            The created ThoughtNode
        """
        node = ThoughtNode(
            name=name,
            question=question,
            thought_type=thought_type,
            dependencies=dependencies or [],
        )
        self.add_node(node)
        return node

    @property
    def root_nodes(self) -> list[str]:
        """Get IDs of nodes with no dependencies."""
        return [nid for nid, node in self.nodes.items() if not node.dependencies]

    @property
    def leaf_nodes(self) -> list[str]:
        """Get IDs of nodes with no children."""
        return [nid for nid, node in self.nodes.items() if not node.children]

    def get_ready_nodes(self) -> list[ThoughtNode]:
        """Get nodes whose dependencies are all satisfied and are still pending."""
        completed_ids = {
            nid for nid, node in self.nodes.items() if node.status in (ThoughtStatus.COMPLETED, ThoughtStatus.FAILED)
        }
        return [
            node
            for node in self.nodes.values()
            if node.status == ThoughtStatus.PENDING and node.is_ready(completed_ids)
        ]

    def get_execution_order(self) -> list[str]:
        """
        Get topological execution order (Kahn's algorithm).

        Returns:
            List of node IDs in dependency-respecting order
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for child_id in node.children:
                if child_id in in_degree:
                    in_degree[child_id] += 1

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for child_id in self.nodes[nid].children:
                if child_id in in_degree:
                    in_degree[child_id] -= 1
                    if in_degree[child_id] == 0:
                        queue.append(child_id)

        return order

    def is_complete(self) -> bool:
        """Check if all nodes are processed (completed or failed)."""
        return all(
            node.status in (ThoughtStatus.COMPLETED, ThoughtStatus.FAILED, ThoughtStatus.SKIPPED)
            for node in self.nodes.values()
        )

    def get_completed_count(self) -> int:
        """Count completed nodes."""
        return sum(
            1
            for node in self.nodes.values()
            if node.status in (ThoughtStatus.COMPLETED, ThoughtStatus.FAILED, ThoughtStatus.SKIPPED)
        )

    def get_failed_count(self) -> int:
        """Count failed nodes."""
        return sum(1 for node in self.nodes.values() if node.status == ThoughtStatus.FAILED)

    def get_final_answer(self) -> str:
        """
        Aggregate answers from leaf nodes.

        Returns:
            Combined answer string
        """
        leaf_answers = []
        for nid in self.leaf_nodes:
            node = self.nodes[nid]
            if node.answer:
                leaf_answers.append(node.answer)

        return "\n".join(leaf_answers) if leaf_answers else ""

    def visualize_ascii(self) -> str:
        """
        Generate ASCII visualization of the graph.

        Returns:
            Multi-line ASCII art string
        """
        lines = [f"Graph: {self.name}", "=" * (len(self.name) + 7)]

        status_icons = {
            ThoughtStatus.PENDING: "⏳",
            ThoughtStatus.IN_PROGRESS: "🔄",
            ThoughtStatus.COMPLETED: "[OK]",
            ThoughtStatus.FAILED: "[NO]",
            ThoughtStatus.SKIPPED: "⏭️",
        }

        for nid in self.get_execution_order():
            node = self.nodes[nid]
            icon = status_icons.get(node.status, "?")
            depth = self._get_depth(nid)
            indent = "  " * depth
            name = node.name or nid
            lines.append(f"{indent}{icon} {name}")
            if node.children:
                for child_id in node.children:
                    child_name = self.nodes[child_id].name or child_id
                    lines.append(f"{indent}  +-> {child_name}")

        return "\n".join(lines)

    def _get_depth(self, node_id: str) -> int:
        """Get depth of a node (distance from root)."""
        depth = 0
        visited = set()
        current = node_id
        while current in self.nodes:
            deps = self.nodes[current].dependencies
            if not deps or current in visited:
                break
            visited.add(current)
            current = deps[0]
            depth += 1
        return depth

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph to dict."""
        return {
            "name": self.name,
            "node_count": len(self.nodes),
            "created_at": self.created_at,
            "is_complete": self.is_complete(),
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }


# =============================================================================
# GraphOfThought Orchestrator
# =============================================================================


class GraphOfThought:
    """
    Orchestrator for graph-based reasoning.

    Provides high-level methods for:
    - Problem decomposition into graphs
    - Decision tree creation
    - Sequential and parallel execution
    - Progress tracking and visualization
    """

    def decompose_problem(
        self,
        main_problem: str,
        sub_problems: list[str],
        parallel_groups: list[list[int]] | None = None,
        name: str = "problem_graph",
    ) -> ThoughtGraph:
        """
        Decompose a problem into a graph of sub-problems.

        Creates: root -> steps (with optional parallel groups) -> aggregation

        Args:
            main_problem: The main problem statement
            sub_problems: List of sub-problem descriptions
            parallel_groups: Lists of step indices to execute in parallel
            name: Graph name

        Returns:
            ThoughtGraph ready for execution
        """
        graph = ThoughtGraph(name=name)

        # Root node
        root = graph.create_node(
            question=main_problem,
            name="main_problem",
            thought_type=ThoughtType.ROOT,
        )

        # Build parallel group lookup: step_index -> group_id
        parallel_lookup: dict[int, int] = {}
        if parallel_groups:
            for group_id, group in enumerate(parallel_groups):
                for idx in group:
                    parallel_lookup[idx] = group_id

        # Step nodes
        step_nodes: list[ThoughtNode] = []
        prev_node_id = root.id

        # Track which steps share the same dependency (parallel)
        # For parallel groups: all members depend on the node before the group
        group_deps: dict[int, str] = {}  # group_id -> dependency node id

        for i, sub_problem in enumerate(sub_problems):
            step_name = f"step_{i + 1}"

            if i in parallel_lookup:
                group_id = parallel_lookup[i]
                if group_id not in group_deps:
                    # First member of this group: dep is the last sequential node
                    group_deps[group_id] = prev_node_id
                deps = [group_deps[group_id]]
            else:
                # Sequential: depends on previous
                deps = [prev_node_id]

            step = graph.create_node(
                question=sub_problem,
                name=step_name,
                thought_type=ThoughtType.ANALYZE,
                dependencies=deps,
            )
            step_nodes.append(step)

            # Only advance prev_node_id for non-parallel steps
            if i not in parallel_lookup:
                prev_node_id = step.id
            else:
                # After a parallel group ends, next sequential depends on all group members
                group_id = parallel_lookup[i]
                [
                    step_nodes[j]
                    for j in range(len(step_nodes))
                    if j in parallel_lookup and parallel_lookup[j] == group_id
                ]
                # Update prev to be the last member (next step will handle deps)
                if all(
                    idx in parallel_lookup and parallel_lookup[idx] == group_id
                    for idx in range(i, min(i + 1, len(sub_problems)))
                ):
                    prev_node_id = step.id

        # Aggregation node depends on all leaf steps
        leaf_step_ids = [s.id for s in step_nodes if s.id in graph.leaf_nodes]
        if not leaf_step_ids:
            leaf_step_ids = [step_nodes[-1].id] if step_nodes else [root.id]

        graph.create_node(
            question=f"Aggregate results for: {main_problem}",
            name="aggregate",
            thought_type=ThoughtType.AGGREGATE,
            dependencies=leaf_step_ids,
        )

        return graph

    def create_decision_tree(
        self,
        question: str,
        options: list[str],
        evaluation_criteria: str = "",
    ) -> ThoughtGraph:
        """
        Create a decision tree: evaluate options then decide.

        Structure: root -> [evaluate each option] -> decision

        Args:
            question: The decision question
            options: List of options to evaluate
            evaluation_criteria: Criteria for evaluation

        Returns:
            ThoughtGraph with decision structure
        """
        graph = ThoughtGraph(name="decision_tree")

        # Root
        root = graph.create_node(
            question=question,
            name="question",
            thought_type=ThoughtType.ROOT,
        )

        # Evaluation nodes (parallel)
        eval_ids = []
        for _i, option in enumerate(options):
            eval_q = f"Evaluate option '{option}'"
            if evaluation_criteria:
                eval_q += f" against criteria: {evaluation_criteria}"

            eval_node = graph.create_node(
                question=eval_q,
                name=f"evaluate_{option.lower().replace(' ', '_')}",
                thought_type=ThoughtType.EVALUATE,
                dependencies=[root.id],
            )
            eval_ids.append(eval_node.id)

        # Decision node
        graph.create_node(
            question=f"Based on evaluations, decide: {question}",
            name="decision",
            thought_type=ThoughtType.DECISION,
            dependencies=eval_ids,
        )

        return graph

    def execute(
        self,
        graph: ThoughtGraph,
        executor: Callable[[ThoughtNode], str],
        on_progress: Callable | None = None,
    ) -> ThoughtGraph:
        """
        Execute graph sequentially in topological order.

        Args:
            graph: ThoughtGraph to execute
            executor: Function that takes a ThoughtNode and returns answer string
            on_progress: Optional callback(graph, node, event)

        Returns:
            The executed graph (same object, mutated)
        """
        order = graph.get_execution_order()

        for nid in order:
            node = graph.nodes[nid]
            if node.status != ThoughtStatus.PENDING:
                continue

            # Check dependencies
            completed_ids = {
                n for n, nd in graph.nodes.items() if nd.status in (ThoughtStatus.COMPLETED, ThoughtStatus.FAILED)
            }
            if not node.is_ready(completed_ids):
                node.mark_failed("Dependencies not met")
                continue

            node.status = ThoughtStatus.IN_PROGRESS
            if on_progress:
                on_progress(graph, node, "started")

            # Attempt execution with retries
            success = False
            for attempt in range(node.max_attempts):
                node.attempts = attempt + 1
                try:
                    answer = executor(node)
                    node.mark_completed(answer)
                    success = True
                    break
                except Exception as e:
                    if attempt == node.max_attempts - 1:
                        node.mark_failed(str(e))

            if on_progress:
                event = "completed" if success else "failed"
                on_progress(graph, node, event)

        return graph

    def execute_parallel(
        self,
        graph: ThoughtGraph,
        executor: Callable[[ThoughtNode], str],
        max_workers: int = 4,
        on_progress: Callable | None = None,
    ) -> ThoughtGraph:
        """
        Execute graph with parallel execution of independent nodes.

        Args:
            graph: ThoughtGraph to execute
            executor: Function that takes a ThoughtNode and returns answer string
            max_workers: Maximum parallel threads
            on_progress: Optional callback(graph, node, event)

        Returns:
            The executed graph
        """
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while not graph.is_complete():
                ready = graph.get_ready_nodes()
                if not ready:
                    # No ready nodes but not complete = deadlock or all in progress
                    # Mark remaining pending as failed
                    for node in graph.nodes.values():
                        if node.status == ThoughtStatus.PENDING:
                            node.mark_failed("No ready nodes (possible deadlock)")
                    break

                futures = {}
                for node in ready:
                    node.status = ThoughtStatus.IN_PROGRESS
                    if on_progress:
                        on_progress(graph, node, "started")
                    futures[pool.submit(self._execute_node, node, executor)] = node

                for future in as_completed(futures):
                    node = futures[future]
                    with contextlib.suppress(Exception):
                        future.result()
                    if on_progress:
                        event = "completed" if node.status == ThoughtStatus.COMPLETED else "failed"
                        on_progress(graph, node, event)

        return graph

    def _execute_node(
        self,
        node: ThoughtNode,
        executor: Callable[[ThoughtNode], str],
    ) -> None:
        """Execute a single node with retry logic."""
        for attempt in range(node.max_attempts):
            node.attempts = attempt + 1
            try:
                answer = executor(node)
                node.mark_completed(answer)
                return
            except Exception as e:
                if attempt == node.max_attempts - 1:
                    node.mark_failed(str(e))

    def get_execution_progress(self, graph: ThoughtGraph) -> dict[str, Any]:
        """
        Get execution progress metrics.

        Returns:
            Dict with total, completed, failed, pending, percentage, is_complete
        """
        total = len(graph.nodes)
        completed = sum(1 for n in graph.nodes.values() if n.status == ThoughtStatus.COMPLETED)
        failed = graph.get_failed_count()
        pending = sum(1 for n in graph.nodes.values() if n.status == ThoughtStatus.PENDING)
        in_progress = sum(1 for n in graph.nodes.values() if n.status == ThoughtStatus.IN_PROGRESS)

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "in_progress": in_progress,
            "percentage": (completed / total * 100) if total > 0 else 0,
            "is_complete": graph.is_complete(),
        }

    def visualize_progress(self, graph: ThoughtGraph) -> str:
        """
        Generate progress visualization string.

        Returns:
            Multi-line progress visualization
        """
        progress = self.get_execution_progress(graph)
        pct = progress["percentage"]

        status_icons = {
            ThoughtStatus.PENDING: "⏳",
            ThoughtStatus.IN_PROGRESS: "🔄",
            ThoughtStatus.COMPLETED: "[OK]",
            ThoughtStatus.FAILED: "[NO]",
            ThoughtStatus.SKIPPED: "⏭️",
        }

        lines = [
            f"Graph: {graph.name}",
            f"Progress: {pct:.0f}% ({progress['completed']}/{progress['total']})",
            "",
        ]

        for nid in graph.get_execution_order():
            node = graph.nodes[nid]
            icon = status_icons.get(node.status, "?")
            name = node.name or nid
            line = f"  {icon} {name}"
            if node.answer:
                preview = node.answer[:50]
                if len(node.answer) > 50:
                    preview += "..."
                line += f" -> {preview}"
            lines.append(line)

        return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================


def create_simple_chain(steps: list[str]) -> ThoughtGraph:
    """
    Create a sequential chain of thought steps.

    Args:
        steps: List of step descriptions (first is the main problem)

    Returns:
        ThoughtGraph with sequential dependencies
    """
    if not steps:
        return ThoughtGraph("empty_chain")

    got = GraphOfThought()
    return got.decompose_problem(
        main_problem=steps[0],
        sub_problems=steps[1:] if len(steps) > 1 else [],
        name="simple_chain",
    )


def create_parallel_exploration(
    question: str,
    approaches: list[str],
) -> ThoughtGraph:
    """
    Create parallel exploration branches that merge into aggregation.

    Structure: root -> [approach_1, approach_2, ...] -> aggregate

    Args:
        question: The main question
        approaches: Different approaches to explore

    Returns:
        ThoughtGraph with parallel branches
    """
    graph = ThoughtGraph("parallel_exploration")

    # Root
    root = graph.create_node(
        question=question,
        name="root",
        thought_type=ThoughtType.ROOT,
    )

    # Parallel approach nodes
    approach_ids = []
    for approach in approaches:
        node = graph.create_node(
            question=f"Explore approach: {approach}",
            name=f"approach_{approach.lower().replace(' ', '_')}",
            thought_type=ThoughtType.GENERATE,
            dependencies=[root.id],
        )
        approach_ids.append(node.id)

    # Aggregation
    graph.create_node(
        question=f"Aggregate findings for: {question}",
        name="aggregate",
        thought_type=ThoughtType.AGGREGATE,
        dependencies=approach_ids,
    )

    return graph
