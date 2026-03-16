"""
Comprehensive tests for core.hive_mind.task_graph module.

Covers: NodeStatus, TaskNode, GraphMetrics, GraphStats, EvaluatorStats,
TaskGraph (DAG operations), TaskGraphEvaluator (F1 metrics), and singleton pattern.

Target: ~90 tests across 21 test categories.
"""

import pytest

from core.intelligence.hive_mind.task_graph import (
    GraphMetrics,
    GraphStats,
    NodeStatus,
    TaskGraph,
    TaskGraphEvaluator,
    TaskNode,
    get_graph_evaluator,
    reset_graph_evaluator,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def empty_graph():
    """An empty TaskGraph."""
    return TaskGraph()


@pytest.fixture
def linear_graph():
    """A -> B -> C linear chain."""
    g = TaskGraph()
    g.add_node("A", description="Step A")
    g.add_node("B", description="Step B")
    g.add_node("C", description="Step C")
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    return g


@pytest.fixture
def diamond_graph():
    """
    Diamond shape:
        A
       / \\
      B   C
       \\ /
        D
    """
    g = TaskGraph()
    g.add_node("A", description="Root")
    g.add_node("B", description="Left")
    g.add_node("C", description="Right")
    g.add_node("D", description="Merge")
    g.add_edge("A", "B")
    g.add_edge("A", "C")
    g.add_edge("B", "D")
    g.add_edge("C", "D")
    return g


@pytest.fixture
def evaluator():
    """A fresh TaskGraphEvaluator."""
    return TaskGraphEvaluator()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the global evaluator singleton before each test."""
    reset_graph_evaluator()
    yield
    reset_graph_evaluator()


# =============================================================================
# 1. NodeStatus enum values
# =============================================================================


class TestNodeStatus:
    def test_pending_value(self):
        assert NodeStatus.PENDING.value == "pending"

    def test_ready_value(self):
        assert NodeStatus.READY.value == "ready"

    def test_in_progress_value(self):
        assert NodeStatus.IN_PROGRESS.value == "in_progress"

    def test_completed_value(self):
        assert NodeStatus.COMPLETED.value == "completed"

    def test_failed_value(self):
        assert NodeStatus.FAILED.value == "failed"

    def test_skipped_value(self):
        assert NodeStatus.SKIPPED.value == "skipped"

    def test_total_members(self):
        assert len(NodeStatus) == 6


# =============================================================================
# 2. TaskNode dataclass and is_terminal property
# =============================================================================


class TestTaskNode:
    def test_defaults(self):
        node = TaskNode(node_id="n1")
        assert node.node_id == "n1"
        assert node.description == ""
        assert node.agent_id == ""
        assert node.tool_name == ""
        assert node.estimated_duration == 0.0
        assert node.status == NodeStatus.PENDING
        assert node.priority == 0
        assert node.metadata == {}

    def test_with_all_fields(self):
        node = TaskNode(
            node_id="task1",
            description="Do something",
            agent_id="claude",
            tool_name="read",
            estimated_duration=3.5,
            status=NodeStatus.IN_PROGRESS,
            priority=5,
            metadata={"key": "val"},
        )
        assert node.node_id == "task1"
        assert node.description == "Do something"
        assert node.agent_id == "claude"
        assert node.tool_name == "read"
        assert node.estimated_duration == 3.5
        assert node.status == NodeStatus.IN_PROGRESS
        assert node.priority == 5
        assert node.metadata == {"key": "val"}

    def test_is_terminal_false_by_default(self):
        node = TaskNode(node_id="x")
        assert node.is_terminal is False

    def test_is_terminal_true_via_metadata(self):
        node = TaskNode(node_id="x", metadata={"is_terminal": True})
        assert node.is_terminal is True

    def test_is_terminal_false_via_metadata(self):
        node = TaskNode(node_id="x", metadata={"is_terminal": False})
        assert node.is_terminal is False


# =============================================================================
# 3. GraphMetrics - fields and is_good property
# =============================================================================


class TestGraphMetrics:
    def test_fields(self):
        m = GraphMetrics(node_f1=0.8, structural_similarity=0.7, tool_f1=0.9, composite=0.8)
        assert m.node_f1 == 0.8
        assert m.structural_similarity == 0.7
        assert m.tool_f1 == 0.9
        assert m.composite == 0.8

    def test_is_good_above_threshold(self):
        m = GraphMetrics(node_f1=1.0, structural_similarity=1.0, tool_f1=1.0, composite=0.61)
        assert m.is_good is True

    def test_is_good_at_threshold(self):
        m = GraphMetrics(node_f1=1.0, structural_similarity=1.0, tool_f1=1.0, composite=0.6)
        assert m.is_good is True

    def test_is_good_below_threshold(self):
        m = GraphMetrics(node_f1=1.0, structural_similarity=1.0, tool_f1=1.0, composite=0.59)
        assert m.is_good is False

    def test_is_good_zero(self):
        m = GraphMetrics(node_f1=0.0, structural_similarity=0.0, tool_f1=0.0, composite=0.0)
        assert m.is_good is False


# =============================================================================
# 4. GraphStats dataclass
# =============================================================================


class TestGraphStats:
    def test_fields(self):
        s = GraphStats(
            total_nodes=5,
            total_edges=4,
            max_depth=3,
            max_parallelism=2,
            critical_path_length=3,
            leaf_nodes=1,
            root_nodes=1,
        )
        assert s.total_nodes == 5
        assert s.total_edges == 4
        assert s.max_depth == 3
        assert s.max_parallelism == 2
        assert s.critical_path_length == 3
        assert s.leaf_nodes == 1
        assert s.root_nodes == 1


# =============================================================================
# 5. add_node: basic and with all fields
# =============================================================================


class TestAddNode:
    def test_basic_add(self, empty_graph):
        node = empty_graph.add_node("n1")
        assert isinstance(node, TaskNode)
        assert node.node_id == "n1"
        assert len(empty_graph) == 1

    def test_add_with_all_fields(self, empty_graph):
        node = empty_graph.add_node(
            "n1",
            description="Desc",
            agent_id="claude",
            tool_name="bash",
            priority=10,
        )
        assert node.description == "Desc"
        assert node.agent_id == "claude"
        assert node.tool_name == "bash"
        assert node.priority == 10

    def test_add_multiple_nodes(self, empty_graph):
        empty_graph.add_node("a")
        empty_graph.add_node("b")
        empty_graph.add_node("c")
        assert len(empty_graph) == 3

    def test_overwrite_existing_node(self, empty_graph):
        empty_graph.add_node("a", description="old")
        empty_graph.add_node("a", description="new")
        assert len(empty_graph) == 1
        assert empty_graph.nodes["a"].description == "new"

    def test_node_appears_in_nodes_property(self, empty_graph):
        empty_graph.add_node("x")
        assert "x" in empty_graph.nodes


# =============================================================================
# 6. add_edge: valid, self-loop, missing node
# =============================================================================


class TestAddEdge:
    def test_valid_edge(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        result = empty_graph.add_edge("A", "B")
        assert result is True
        assert ("A", "B") in empty_graph.edges

    def test_self_loop_rejected(self, empty_graph):
        empty_graph.add_node("A")
        result = empty_graph.add_edge("A", "A")
        assert result is False
        assert len(empty_graph.edges) == 0

    def test_missing_source_node(self, empty_graph):
        empty_graph.add_node("B")
        result = empty_graph.add_edge("A", "B")
        assert result is False

    def test_missing_target_node(self, empty_graph):
        empty_graph.add_node("A")
        result = empty_graph.add_edge("A", "B")
        assert result is False

    def test_both_nodes_missing(self, empty_graph):
        result = empty_graph.add_edge("X", "Y")
        assert result is False

    def test_duplicate_edge_accepted(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        empty_graph.add_edge("A", "B")
        result = empty_graph.add_edge("A", "B")
        assert result is True
        assert len(empty_graph.edges) == 1  # set deduplicates


# =============================================================================
# 7. Cycle detection
# =============================================================================


class TestCycleDetection:
    def test_direct_cycle_rejected(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        empty_graph.add_edge("A", "B")
        result = empty_graph.add_edge("B", "A")
        assert result is False
        assert ("B", "A") not in empty_graph.edges

    def test_three_node_cycle_rejected(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        empty_graph.add_node("C")
        empty_graph.add_edge("A", "B")
        empty_graph.add_edge("B", "C")
        result = empty_graph.add_edge("C", "A")
        assert result is False
        assert ("C", "A") not in empty_graph.edges

    def test_dag_remains_valid_after_cycle_rejection(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        empty_graph.add_node("C")
        empty_graph.add_edge("A", "B")
        empty_graph.add_edge("B", "C")
        empty_graph.add_edge("C", "A")  # rejected
        assert empty_graph.is_valid_dag() is True

    def test_valid_dag_returns_true(self, linear_graph):
        assert linear_graph.is_valid_dag() is True

    def test_empty_graph_is_valid_dag(self, empty_graph):
        assert empty_graph.is_valid_dag() is True

    def test_single_node_is_valid_dag(self, empty_graph):
        empty_graph.add_node("lonely")
        assert empty_graph.is_valid_dag() is True


# =============================================================================
# 8. remove_node
# =============================================================================


class TestRemoveNode:
    def test_remove_existing_node(self, empty_graph):
        empty_graph.add_node("A")
        result = empty_graph.remove_node("A")
        assert result is True
        assert len(empty_graph) == 0

    def test_remove_nonexistent_node(self, empty_graph):
        result = empty_graph.remove_node("ghost")
        assert result is False

    def test_remove_node_clears_outgoing_edges(self, linear_graph):
        linear_graph.remove_node("A")
        assert ("A", "B") not in linear_graph.edges

    def test_remove_node_clears_incoming_edges(self, linear_graph):
        linear_graph.remove_node("C")
        assert ("B", "C") not in linear_graph.edges

    def test_remove_middle_node(self, linear_graph):
        linear_graph.remove_node("B")
        assert len(linear_graph) == 2
        assert ("A", "B") not in linear_graph.edges
        assert ("B", "C") not in linear_graph.edges

    def test_graph_still_valid_after_removal(self, linear_graph):
        linear_graph.remove_node("B")
        assert linear_graph.is_valid_dag() is True


# =============================================================================
# 9. topological_sort
# =============================================================================


class TestTopologicalSort:
    def test_linear_chain(self, linear_graph):
        order = linear_graph.topological_sort()
        assert order == ["A", "B", "C"]

    def test_diamond_graph(self, diamond_graph):
        order = diamond_graph.topological_sort()
        assert order[0] == "A"
        assert order[-1] == "D"
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_empty_graph(self, empty_graph):
        assert empty_graph.topological_sort() == []

    def test_single_node(self, empty_graph):
        empty_graph.add_node("only")
        assert empty_graph.topological_sort() == ["only"]

    def test_priority_ordering(self, empty_graph):
        """Higher priority nodes should come first among equal-depth nodes."""
        empty_graph.add_node("low", priority=1)
        empty_graph.add_node("high", priority=10)
        order = empty_graph.topological_sort()
        assert order.index("high") < order.index("low")

    def test_priority_at_same_level(self, empty_graph):
        """Among nodes at the same topological level, priority matters."""
        empty_graph.add_node("root")
        empty_graph.add_node("lo", priority=1)
        empty_graph.add_node("hi", priority=10)
        empty_graph.add_edge("root", "lo")
        empty_graph.add_edge("root", "hi")
        order = empty_graph.topological_sort()
        assert order[0] == "root"
        # hi should come before lo due to higher priority
        assert order.index("hi") < order.index("lo")

    def test_disconnected_components(self, empty_graph):
        empty_graph.add_node("X")
        empty_graph.add_node("Y")
        order = empty_graph.topological_sort()
        assert set(order) == {"X", "Y"}


# =============================================================================
# 10. get_ready_nodes
# =============================================================================


class TestGetReadyNodes:
    def test_no_deps_all_pending(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        ready = empty_graph.get_ready_nodes()
        assert set(ready) == {"A", "B"}

    def test_deps_not_completed(self, linear_graph):
        ready = linear_graph.get_ready_nodes()
        assert ready == ["A"]

    def test_deps_completed(self, linear_graph):
        linear_graph._nodes["A"].status = NodeStatus.COMPLETED
        ready = linear_graph.get_ready_nodes()
        assert ready == ["B"]

    def test_all_completed_no_ready(self, linear_graph):
        for n in linear_graph._nodes.values():
            n.status = NodeStatus.COMPLETED
        ready = linear_graph.get_ready_nodes()
        assert ready == []

    def test_in_progress_not_ready(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph._nodes["A"].status = NodeStatus.IN_PROGRESS
        ready = empty_graph.get_ready_nodes()
        assert ready == []

    def test_diamond_ready_after_root_complete(self, diamond_graph):
        diamond_graph._nodes["A"].status = NodeStatus.COMPLETED
        ready = diamond_graph.get_ready_nodes()
        assert set(ready) == {"B", "C"}

    def test_diamond_merge_needs_both_parents(self, diamond_graph):
        diamond_graph._nodes["A"].status = NodeStatus.COMPLETED
        diamond_graph._nodes["B"].status = NodeStatus.COMPLETED
        # C still pending, so D is not ready
        ready = diamond_graph.get_ready_nodes()
        assert "D" not in ready
        assert "C" in ready

    def test_diamond_merge_ready_when_both_done(self, diamond_graph):
        diamond_graph._nodes["A"].status = NodeStatus.COMPLETED
        diamond_graph._nodes["B"].status = NodeStatus.COMPLETED
        diamond_graph._nodes["C"].status = NodeStatus.COMPLETED
        ready = diamond_graph.get_ready_nodes()
        assert ready == ["D"]


# =============================================================================
# 11. get_parallel_groups
# =============================================================================


class TestGetParallelGroups:
    def test_linear_chain_one_per_group(self, linear_graph):
        groups = linear_graph.get_parallel_groups()
        assert len(groups) == 3
        assert groups[0] == ["A"]
        assert groups[1] == ["B"]
        assert groups[2] == ["C"]

    def test_diamond_groups(self, diamond_graph):
        groups = diamond_graph.get_parallel_groups()
        assert len(groups) == 3
        assert groups[0] == ["A"]
        assert set(groups[1]) == {"B", "C"}
        assert groups[2] == ["D"]

    def test_independent_nodes_single_group(self, empty_graph):
        empty_graph.add_node("X")
        empty_graph.add_node("Y")
        empty_graph.add_node("Z")
        groups = empty_graph.get_parallel_groups()
        assert len(groups) == 1
        assert set(groups[0]) == {"X", "Y", "Z"}

    def test_empty_graph_no_groups(self, empty_graph):
        groups = empty_graph.get_parallel_groups()
        assert groups == []

    def test_single_node_one_group(self, empty_graph):
        empty_graph.add_node("solo")
        groups = empty_graph.get_parallel_groups()
        assert groups == [["solo"]]


# =============================================================================
# 12. get_critical_path
# =============================================================================


class TestGetCriticalPath:
    def test_linear_chain(self, linear_graph):
        path = linear_graph.get_critical_path()
        assert path == ["A", "B", "C"]

    def test_diamond_critical_path(self, diamond_graph):
        path = diamond_graph.get_critical_path()
        # Any path from A to D has length 3 (A -> B/C -> D)
        assert len(path) == 3
        assert path[0] == "A"
        assert path[-1] == "D"

    def test_empty_graph(self, empty_graph):
        path = empty_graph.get_critical_path()
        assert path == []

    def test_single_node(self, empty_graph):
        empty_graph.add_node("x")
        path = empty_graph.get_critical_path()
        assert path == ["x"]

    def test_longer_branch_is_critical(self, empty_graph):
        """
        A -> B -> C -> D  (length 4)
        A -> E            (length 2)
        Critical path should be A-B-C-D.
        """
        g = empty_graph
        g.add_node("A")
        g.add_node("B")
        g.add_node("C")
        g.add_node("D")
        g.add_node("E")
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "D")
        g.add_edge("A", "E")
        path = g.get_critical_path()
        assert path == ["A", "B", "C", "D"]

    def test_disconnected_nodes(self, empty_graph):
        empty_graph.add_node("X")
        empty_graph.add_node("Y")
        path = empty_graph.get_critical_path()
        # All distances are 0, picks one node
        assert len(path) == 1


# =============================================================================
# 13. get_stats
# =============================================================================


class TestGetStats:
    def test_linear_stats(self, linear_graph):
        s = linear_graph.get_stats()
        assert s.total_nodes == 3
        assert s.total_edges == 2
        assert s.max_depth == 3
        assert s.max_parallelism == 1
        assert s.critical_path_length == 3
        assert s.leaf_nodes == 1
        assert s.root_nodes == 1

    def test_diamond_stats(self, diamond_graph):
        s = diamond_graph.get_stats()
        assert s.total_nodes == 4
        assert s.total_edges == 4
        assert s.max_depth == 3
        assert s.max_parallelism == 2
        assert s.critical_path_length == 3
        assert s.leaf_nodes == 1
        assert s.root_nodes == 1

    def test_empty_stats(self, empty_graph):
        s = empty_graph.get_stats()
        assert s.total_nodes == 0
        assert s.total_edges == 0
        assert s.max_depth == 0
        assert s.max_parallelism == 0
        assert s.critical_path_length == 0
        assert s.leaf_nodes == 0
        assert s.root_nodes == 0

    def test_independent_nodes_stats(self, empty_graph):
        empty_graph.add_node("A")
        empty_graph.add_node("B")
        empty_graph.add_node("C")
        s = empty_graph.get_stats()
        assert s.total_nodes == 3
        assert s.total_edges == 0
        assert s.max_parallelism == 3
        assert s.root_nodes == 3
        assert s.leaf_nodes == 3


# =============================================================================
# 14. Evaluator: node_f1
# =============================================================================


class TestEvaluatorNodeF1:
    def test_perfect_match(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        for nid in ["A", "B", "C"]:
            pred.add_node(nid)
            ref.add_node(nid)
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == 1.0

    def test_completely_disjoint(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("X")
        ref.add_node("Y")
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == 0.0

    def test_partial_overlap(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A")
        pred.add_node("B")
        ref.add_node("A")
        ref.add_node("C")
        # tp=1 (A), fp=1 (B), fn=1 (C)
        # precision=0.5, recall=0.5
        # F1 = 2*0.5*0.5/(0.5+0.5) = 0.5
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == pytest.approx(0.5)

    def test_both_empty(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == 1.0

    def test_pred_empty_ref_nonempty(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        ref.add_node("A")
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == 0.0

    def test_pred_nonempty_ref_empty(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A")
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == 0.0

    def test_superset_prediction(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A")
        pred.add_node("B")
        pred.add_node("C")
        ref.add_node("A")
        # tp=1, fp=2, fn=0
        # precision=1/3, recall=1/1=1.0
        # F1 = 2*(1/3)*1/(1/3+1) = (2/3)/(4/3) = 0.5
        f1 = evaluator._compute_node_f1(pred, ref)
        assert f1 == pytest.approx(0.5)


# =============================================================================
# 15. Evaluator: structural_similarity
# =============================================================================


class TestEvaluatorStructuralSimilarity:
    def test_identical_edges(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        for nid in ["A", "B", "C"]:
            pred.add_node(nid)
            ref.add_node(nid)
        pred.add_edge("A", "B")
        pred.add_edge("B", "C")
        ref.add_edge("A", "B")
        ref.add_edge("B", "C")
        sim = evaluator._compute_structural_similarity(pred, ref)
        # edge_f1=1.0, depth_sim=1.0
        # 1.0*0.7 + 1.0*0.3 = 1.0
        assert sim == pytest.approx(1.0)

    def test_completely_different_edges(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        for nid in ["A", "B", "C", "D"]:
            pred.add_node(nid)
            ref.add_node(nid)
        pred.add_edge("A", "B")
        ref.add_edge("C", "D")
        sim = evaluator._compute_structural_similarity(pred, ref)
        # tp=0 (no shared edges), so precision=0, recall=0
        # Early return at precision+recall==0 => 0.0
        assert sim == pytest.approx(0.0)

    def test_both_no_edges(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A")
        ref.add_node("A")
        sim = evaluator._compute_structural_similarity(pred, ref)
        assert sim == 1.0

    def test_one_has_edges_other_not(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A")
        pred.add_node("B")
        pred.add_edge("A", "B")
        ref.add_node("A")
        ref.add_node("B")
        sim = evaluator._compute_structural_similarity(pred, ref)
        assert sim == 0.0

    def test_different_depth(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        for nid in ["A", "B", "C", "D"]:
            pred.add_node(nid)
            ref.add_node(nid)
        # pred: A->B->C->D (depth=4)
        pred.add_edge("A", "B")
        pred.add_edge("B", "C")
        pred.add_edge("C", "D")
        # ref: A->B, C->D (depth=2)
        ref.add_edge("A", "B")
        ref.add_edge("C", "D")
        # Shared edge: (A,B) => tp=1
        # fp=2 (B->C, C->D in pred), fn=1 (C->D in ref)
        # Wait: (C,D) is in both pred and ref
        # pred edges: {(A,B),(B,C),(C,D)}, ref edges: {(A,B),(C,D)}
        # tp=2, fp=1, fn=0
        # precision=2/3, recall=2/2=1.0
        # edge_f1 = 2*(2/3)*1/(2/3+1) = (4/3)/(5/3) = 4/5 = 0.8
        # pred depth=4, ref depth=2
        # depth_sim = 1 - |4-2|/max(4,2) = 1 - 2/4 = 0.5
        # result = 0.8*0.7 + 0.5*0.3 = 0.56 + 0.15 = 0.71
        sim = evaluator._compute_structural_similarity(pred, ref)
        assert sim == pytest.approx(0.71)


# =============================================================================
# 16. Evaluator: tool_f1
# =============================================================================


class TestEvaluatorToolF1:
    def test_matching_tools(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A", tool_name="read")
        pred.add_node("B", tool_name="write")
        ref.add_node("A", tool_name="read")
        ref.add_node("B", tool_name="write")
        f1 = evaluator._compute_tool_f1(pred, ref)
        assert f1 == 1.0

    def test_mismatched_tools(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A", tool_name="read")
        ref.add_node("A", tool_name="write")
        f1 = evaluator._compute_tool_f1(pred, ref)
        assert f1 == 0.0

    def test_no_tools_both_empty(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A", tool_name="")
        ref.add_node("A", tool_name="")
        f1 = evaluator._compute_tool_f1(pred, ref)
        assert f1 == 1.0

    def test_one_has_tool_other_not(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A", tool_name="read")
        ref.add_node("A", tool_name="")
        f1 = evaluator._compute_tool_f1(pred, ref)
        assert f1 == 0.0

    def test_no_common_nodes(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("X", tool_name="read")
        ref.add_node("Y", tool_name="read")
        f1 = evaluator._compute_tool_f1(pred, ref)
        assert f1 == 0.0

    def test_partial_tool_match(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A", tool_name="read")
        pred.add_node("B", tool_name="write")
        ref.add_node("A", tool_name="read")
        ref.add_node("B", tool_name="bash")
        f1 = evaluator._compute_tool_f1(pred, ref)
        # 1 match out of 2 common nodes
        assert f1 == pytest.approx(0.5)


# =============================================================================
# 17. Evaluator: composite score and is_good
# =============================================================================


class TestEvaluatorComposite:
    def test_perfect_composite(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        for nid in ["A", "B"]:
            pred.add_node(nid, tool_name="read")
            ref.add_node(nid, tool_name="read")
        pred.add_edge("A", "B")
        ref.add_edge("A", "B")
        metrics = evaluator.evaluate(pred, ref)
        assert metrics.node_f1 == pytest.approx(1.0)
        assert metrics.structural_similarity == pytest.approx(1.0)
        assert metrics.tool_f1 == pytest.approx(1.0)
        assert metrics.composite == pytest.approx(1.0)
        assert metrics.is_good is True

    def test_low_composite_disjoint_nodes(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("X", tool_name="read")
        ref.add_node("Y", tool_name="write")
        metrics = evaluator.evaluate(pred, ref)
        # node_f1 = 0.0 (disjoint), tool_f1 = 0.0 (no common nodes)
        # structural_similarity = 1.0 (both have no edges)
        # composite = 0.4*0 + 0.35*1.0 + 0.25*0 = 0.35
        assert metrics.composite == pytest.approx(0.35)
        assert metrics.is_good is False

    def test_composite_weight_formula(self, evaluator):
        """Verify composite = 0.4*node_f1 + 0.35*structural + 0.25*tool_f1."""
        pred = TaskGraph()
        ref = TaskGraph()
        # Build a scenario with known partial scores
        pred.add_node("A", tool_name="read")
        pred.add_node("B", tool_name="write")
        ref.add_node("A", tool_name="read")
        ref.add_node("C", tool_name="bash")
        metrics = evaluator.evaluate(pred, ref)
        expected = 0.4 * metrics.node_f1 + 0.35 * metrics.structural_similarity + 0.25 * metrics.tool_f1
        assert metrics.composite == pytest.approx(expected)

    def test_borderline_is_good(self, evaluator):
        """Check is_good threshold behavior at exactly 0.6."""
        m = GraphMetrics(node_f1=0.5, structural_similarity=0.5, tool_f1=0.5, composite=0.6)
        assert m.is_good is True
        m2 = GraphMetrics(node_f1=0.5, structural_similarity=0.5, tool_f1=0.5, composite=0.5999)
        assert m2.is_good is False


# =============================================================================
# 18. Evaluator: get_stats tracking
# =============================================================================


class TestEvaluatorStats:
    def test_initial_stats(self, evaluator):
        stats = evaluator.get_stats()
        assert stats.total_evaluations == 0
        assert stats.avg_node_f1 == 0.0
        assert stats.avg_structural_similarity == 0.0
        assert stats.avg_tool_f1 == 0.0

    def test_stats_after_one_evaluation(self, evaluator):
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A", tool_name="read")
        ref.add_node("A", tool_name="read")
        evaluator.evaluate(pred, ref)
        stats = evaluator.get_stats()
        assert stats.total_evaluations == 1
        assert stats.avg_node_f1 == pytest.approx(1.0)
        assert stats.avg_tool_f1 == pytest.approx(1.0)

    def test_stats_after_multiple_evaluations(self, evaluator):
        # Perfect match
        pred1 = TaskGraph()
        ref1 = TaskGraph()
        pred1.add_node("A")
        ref1.add_node("A")
        evaluator.evaluate(pred1, ref1)

        # Disjoint
        pred2 = TaskGraph()
        ref2 = TaskGraph()
        pred2.add_node("X")
        ref2.add_node("Y")
        evaluator.evaluate(pred2, ref2)

        stats = evaluator.get_stats()
        assert stats.total_evaluations == 2
        # (1.0 + 0.0) / 2 = 0.5
        assert stats.avg_node_f1 == pytest.approx(0.5)


# =============================================================================
# 19. Singleton pattern
# =============================================================================


class TestSingleton:
    def test_get_returns_evaluator(self):
        e = get_graph_evaluator()
        assert isinstance(e, TaskGraphEvaluator)

    def test_same_instance_returned(self):
        e1 = get_graph_evaluator()
        e2 = get_graph_evaluator()
        assert e1 is e2

    def test_reset_creates_new_instance(self):
        e1 = get_graph_evaluator()
        reset_graph_evaluator()
        e2 = get_graph_evaluator()
        assert e1 is not e2

    def test_reset_clears_stats(self):
        e = get_graph_evaluator()
        pred = TaskGraph()
        ref = TaskGraph()
        pred.add_node("A")
        ref.add_node("A")
        e.evaluate(pred, ref)
        assert e.get_stats().total_evaluations == 1

        reset_graph_evaluator()
        e2 = get_graph_evaluator()
        assert e2.get_stats().total_evaluations == 0


# =============================================================================
# 20. Empty graph handling
# =============================================================================


class TestEmptyGraph:
    def test_len_zero(self, empty_graph):
        assert len(empty_graph) == 0

    def test_nodes_empty(self, empty_graph):
        assert empty_graph.nodes == {}

    def test_edges_empty(self, empty_graph):
        assert empty_graph.edges == set()

    def test_topological_sort_empty(self, empty_graph):
        assert empty_graph.topological_sort() == []

    def test_ready_nodes_empty(self, empty_graph):
        assert empty_graph.get_ready_nodes() == []

    def test_parallel_groups_empty(self, empty_graph):
        assert empty_graph.get_parallel_groups() == []

    def test_critical_path_empty(self, empty_graph):
        assert empty_graph.get_critical_path() == []

    def test_is_valid_dag_empty(self, empty_graph):
        assert empty_graph.is_valid_dag() is True

    def test_stats_all_zero(self, empty_graph):
        s = empty_graph.get_stats()
        assert s.total_nodes == 0
        assert s.total_edges == 0
        assert s.max_depth == 0
        assert s.max_parallelism == 0
        assert s.critical_path_length == 0
        assert s.leaf_nodes == 0
        assert s.root_nodes == 0


# =============================================================================
# 21. Complex graph scenarios
# =============================================================================


class TestComplexGraphs:
    def test_fan_out(self, empty_graph):
        """
        Root fans out to many children:
          R -> A, R -> B, R -> C, R -> D
        """
        g = empty_graph
        g.add_node("R")
        for child in ["A", "B", "C", "D"]:
            g.add_node(child)
            g.add_edge("R", child)
        groups = g.get_parallel_groups()
        assert len(groups) == 2
        assert groups[0] == ["R"]
        assert set(groups[1]) == {"A", "B", "C", "D"}
        s = g.get_stats()
        assert s.max_parallelism == 4
        assert s.root_nodes == 1
        assert s.leaf_nodes == 4

    def test_fan_in(self, empty_graph):
        """
        Many parents converge to one child:
          A -> Z, B -> Z, C -> Z
        """
        g = empty_graph
        for parent in ["A", "B", "C"]:
            g.add_node(parent)
        g.add_node("Z")
        for parent in ["A", "B", "C"]:
            g.add_edge(parent, "Z")
        groups = g.get_parallel_groups()
        assert len(groups) == 2
        assert set(groups[0]) == {"A", "B", "C"}
        assert groups[1] == ["Z"]
        s = g.get_stats()
        assert s.max_parallelism == 3
        assert s.root_nodes == 3
        assert s.leaf_nodes == 1

    def test_wide_diamond(self, empty_graph):
        """
        Wide diamond:
              S
           / | \\
          A  B  C
           \\ | /
              E
        """
        g = empty_graph
        g.add_node("S")
        for mid in ["A", "B", "C"]:
            g.add_node(mid)
            g.add_edge("S", mid)
        g.add_node("E")
        for mid in ["A", "B", "C"]:
            g.add_edge(mid, "E")
        assert g.is_valid_dag() is True
        s = g.get_stats()
        assert s.total_nodes == 5
        assert s.total_edges == 6
        assert s.max_parallelism == 3
        assert s.critical_path_length == 3

    def test_multi_layer_pipeline(self, empty_graph):
        """
        L1: A, B -> L2: C, D -> L3: E
        """
        g = empty_graph
        g.add_node("A")
        g.add_node("B")
        g.add_node("C")
        g.add_node("D")
        g.add_node("E")
        g.add_edge("A", "C")
        g.add_edge("B", "D")
        g.add_edge("C", "E")
        g.add_edge("D", "E")
        groups = g.get_parallel_groups()
        assert len(groups) == 3
        assert set(groups[0]) == {"A", "B"}
        assert set(groups[1]) == {"C", "D"}
        assert groups[2] == ["E"]

    def test_large_linear_chain(self, empty_graph):
        """A chain of 20 nodes to stress basic operations."""
        g = empty_graph
        ids = [f"n{i}" for i in range(20)]
        for nid in ids:
            g.add_node(nid)
        for i in range(len(ids) - 1):
            g.add_edge(ids[i], ids[i + 1])
        assert g.is_valid_dag() is True
        order = g.topological_sort()
        assert order == ids
        s = g.get_stats()
        assert s.total_nodes == 20
        assert s.total_edges == 19
        assert s.max_depth == 20
        assert s.critical_path_length == 20
        assert s.max_parallelism == 1

    def test_nodes_property_is_copy(self, linear_graph):
        """Ensure nodes property returns a copy, not the internal dict."""
        nodes = linear_graph.nodes
        nodes["INTRUDER"] = TaskNode(node_id="INTRUDER")
        assert "INTRUDER" not in linear_graph.nodes

    def test_edges_property_is_copy(self, linear_graph):
        """Ensure edges property returns a copy, not the internal set."""
        edges = linear_graph.edges
        edges.add(("X", "Y"))
        assert ("X", "Y") not in linear_graph.edges

    def test_evaluator_with_complex_graphs(self, evaluator):
        """Evaluator handles graphs with varying topology correctly."""
        pred = TaskGraph()
        ref = TaskGraph()

        # pred: A -> B -> C
        for nid in ["A", "B", "C"]:
            pred.add_node(nid, tool_name="read")
        pred.add_edge("A", "B")
        pred.add_edge("B", "C")

        # ref: A -> B, A -> C (fan-out)
        for nid in ["A", "B", "C"]:
            ref.add_node(nid, tool_name="read")
        ref.add_edge("A", "B")
        ref.add_edge("A", "C")

        metrics = evaluator.evaluate(pred, ref)
        assert metrics.node_f1 == pytest.approx(1.0)  # Same nodes
        assert metrics.tool_f1 == pytest.approx(1.0)  # Same tools
        # Structural differs: shared edge (A,B), pred has (B,C), ref has (A,C)
        # tp=1, fp=1, fn=1 => edge_f1 = 2*(0.5)*(0.5)/1.0 = 0.5
        # pred depth=3 levels, ref depth=2 levels
        # depth_sim = 1 - |3-2|/max(3,2) = 1 - 1/3 = 2/3
        # structural = 0.5*0.7 + (2/3)*0.3 = 0.35 + 0.2 = 0.55
        assert metrics.structural_similarity == pytest.approx(0.55, abs=0.01)
        assert 0.0 < metrics.composite < 1.0

    def test_evaluator_both_empty_graphs(self, evaluator):
        """Evaluating two empty graphs should give perfect scores."""
        pred = TaskGraph()
        ref = TaskGraph()
        metrics = evaluator.evaluate(pred, ref)
        assert metrics.node_f1 == 1.0
        assert metrics.structural_similarity == 1.0
        assert metrics.tool_f1 == 0.0  # no common nodes => 0.0
        # composite = 0.4*1.0 + 0.35*1.0 + 0.25*0.0 = 0.75
        assert metrics.composite == pytest.approx(0.75)
