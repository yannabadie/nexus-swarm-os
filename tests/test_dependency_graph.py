"""
Tests for V12.4 Workflow Dependency Graph.

Validates:
- WorkflowNode to_dict
- WorkflowEdge to_dict
- ExecutionOrder to_dict
- GraphStats to_dict
- Node operations (add, remove, has, get, list)
- Edge operations (add, remove, dependencies, dependents)
- Graph analysis (roots, leaves, cycle detection)
- Execution order (topological sort)
- Parallel groups
- Critical path
- Depth calculation
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.workflow.dependency_graph import (
    MAX_EDGES,
    MAX_NODES,
    ExecutionOrder,
    GraphStats,
    WorkflowDependencyGraph,
    WorkflowEdge,
    WorkflowNode,
    get_dependency_graph,
    reset_dependency_graph,
)

# =============================================================================
# WorkflowNode Tests
# =============================================================================


class TestWorkflowNode:
    """Test WorkflowNode dataclass."""

    def test_basic(self):
        n = WorkflowNode(node_id="step1", label="Fetch Data")
        assert n.node_id == "step1"
        assert n.label == "Fetch Data"

    def test_to_dict(self):
        n = WorkflowNode(node_id="step1", estimated_duration=5.0)
        d = n.to_dict()
        assert d["node_id"] == "step1"
        assert d["estimated_duration"] == 5.0


# =============================================================================
# WorkflowEdge Tests
# =============================================================================


class TestWorkflowEdge:
    """Test WorkflowEdge dataclass."""

    def test_to_dict(self):
        e = WorkflowEdge(source="a", target="b")
        d = e.to_dict()
        assert d["source"] == "a"
        assert d["target"] == "b"


# =============================================================================
# ExecutionOrder Tests
# =============================================================================


class TestExecutionOrder:
    """Test ExecutionOrder dataclass."""

    def test_to_dict(self):
        o = ExecutionOrder(
            steps=["a", "b"],
            parallel_groups=[["a"], ["b"]],
            critical_path=["a", "b"],
            critical_path_duration=10.0,
        )
        d = o.to_dict()
        assert d["steps"] == ["a", "b"]
        assert d["critical_path_duration"] == 10.0


# =============================================================================
# GraphStats Tests
# =============================================================================


class TestGraphStats:
    """Test GraphStats dataclass."""

    def test_to_dict(self):
        s = GraphStats(node_count=5, edge_count=4, root_count=1, leaf_count=1, max_depth=3, has_cycle=False)
        d = s.to_dict()
        assert d["node_count"] == 5
        assert d["has_cycle"] is False


# =============================================================================
# Node Operations Tests
# =============================================================================


class TestNodeOperations:
    """Test node add, remove, has, get, list."""

    def test_add_node(self):
        g = WorkflowDependencyGraph()
        assert g.add_node("step1") is True
        assert g.node_count == 1

    def test_add_duplicate(self):
        g = WorkflowDependencyGraph()
        g.add_node("step1")
        assert g.add_node("step1") is False

    def test_add_with_label(self):
        g = WorkflowDependencyGraph()
        g.add_node("step1", label="Fetch Data")
        node = g.get_node("step1")
        assert node.label == "Fetch Data"

    def test_add_with_dependencies(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        assert g.get_dependencies("b") == ["a"]

    def test_remove_node(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        assert g.remove_node("a") is True
        assert g.node_count == 0

    def test_remove_not_found(self):
        g = WorkflowDependencyGraph()
        assert g.remove_node("missing") is False

    def test_remove_cleans_edges(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.remove_node("a")
        assert g.get_dependencies("b") == []

    def test_has_node(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        assert g.has_node("a") is True
        assert g.has_node("missing") is False

    def test_get_node(self):
        g = WorkflowDependencyGraph()
        g.add_node("a", estimated_duration=5.0)
        node = g.get_node("a")
        assert node is not None
        assert node.estimated_duration == 5.0

    def test_get_node_not_found(self):
        g = WorkflowDependencyGraph()
        assert g.get_node("missing") is None

    def test_list_nodes(self):
        g = WorkflowDependencyGraph()
        g.add_node("c")
        g.add_node("a")
        g.add_node("b")
        assert g.list_nodes() == ["a", "b", "c"]


# =============================================================================
# Edge Operations Tests
# =============================================================================


class TestEdgeOperations:
    """Test edge operations."""

    def test_add_edge(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        assert g.add_edge("a", "b") is True
        assert g.get_dependencies("b") == ["a"]

    def test_add_edge_missing_node(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        assert g.add_edge("a", "missing") is False

    def test_add_self_edge(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        assert g.add_edge("a", "a") is False

    def test_add_duplicate_edge(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b")
        assert g.add_edge("a", "b") is False

    def test_remove_edge(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b")
        assert g.remove_edge("a", "b") is True
        assert g.get_dependencies("b") == []

    def test_remove_edge_not_found(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        assert g.remove_edge("a", "b") is False

    def test_get_dependents(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["a"])
        assert g.get_dependents("a") == ["b", "c"]

    def test_edge_count(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["a"])
        assert g.edge_count == 2


# =============================================================================
# Graph Analysis Tests
# =============================================================================


class TestGraphAnalysis:
    """Test graph analysis methods."""

    def test_get_roots(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c")
        assert g.get_roots() == ["a", "c"]

    def test_get_leaves(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["a"])
        assert g.get_leaves() == ["b", "c"]

    def test_no_cycle(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["b"])
        assert g.has_cycle() is False

    def test_has_cycle(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_node("c")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")  # Creates cycle
        assert g.has_cycle() is True


# =============================================================================
# Execution Order Tests
# =============================================================================


class TestExecutionOrderGraph:
    """Test topological sort and execution order."""

    def test_linear_chain(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["b"])
        order = g.execution_order()
        assert order is not None
        assert order.steps == ["a", "b", "c"]

    def test_diamond(self):
        g = WorkflowDependencyGraph()
        g.add_node("fetch")
        g.add_node("transform", depends_on=["fetch"])
        g.add_node("validate", depends_on=["fetch"])
        g.add_node("store", depends_on=["transform", "validate"])
        order = g.execution_order()
        assert order is not None
        assert order.steps[0] == "fetch"
        assert order.steps[-1] == "store"
        # transform and validate should be in middle
        middle = set(order.steps[1:3])
        assert middle == {"transform", "validate"}

    def test_parallel_groups_diamond(self):
        g = WorkflowDependencyGraph()
        g.add_node("fetch")
        g.add_node("transform", depends_on=["fetch"])
        g.add_node("validate", depends_on=["fetch"])
        g.add_node("store", depends_on=["transform", "validate"])
        order = g.execution_order()
        assert len(order.parallel_groups) == 3
        assert order.parallel_groups[0] == ["fetch"]
        assert set(order.parallel_groups[1]) == {"transform", "validate"}
        assert order.parallel_groups[2] == ["store"]

    def test_returns_none_on_cycle(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        assert g.execution_order() is None

    def test_empty_graph(self):
        g = WorkflowDependencyGraph()
        order = g.execution_order()
        assert order is not None
        assert order.steps == []

    def test_single_node(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        order = g.execution_order()
        assert order.steps == ["a"]
        assert order.parallel_groups == [["a"]]


# =============================================================================
# Critical Path Tests
# =============================================================================


class TestCriticalPath:
    """Test critical path computation."""

    def test_linear_critical_path(self):
        g = WorkflowDependencyGraph()
        g.add_node("a", estimated_duration=2.0)
        g.add_node("b", estimated_duration=3.0)
        g.add_node("c", estimated_duration=1.0)
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        order = g.execution_order()
        assert order.critical_path == ["a", "b", "c"]
        assert order.critical_path_duration == 6.0

    def test_diamond_critical_path(self):
        g = WorkflowDependencyGraph()
        g.add_node("fetch", estimated_duration=1.0)
        g.add_node("transform", estimated_duration=5.0)
        g.add_node("validate", estimated_duration=2.0)
        g.add_node("store", estimated_duration=1.0)
        g.add_edge("fetch", "transform")
        g.add_edge("fetch", "validate")
        g.add_edge("transform", "store")
        g.add_edge("validate", "store")
        order = g.execution_order()
        # Critical path: fetch -> transform -> store = 7.0
        assert order.critical_path_duration == 7.0
        assert "transform" in order.critical_path


# =============================================================================
# Depth Tests
# =============================================================================


class TestDepth:
    """Test depth calculation."""

    def test_root_depth(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        assert g.depth("a") == 0

    def test_chain_depth(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["b"])
        assert g.depth("c") == 2

    def test_depth_unknown(self):
        g = WorkflowDependencyGraph()
        assert g.depth("missing") == -1

    def test_max_depth(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["b"])
        assert g.max_depth() == 2

    def test_max_depth_empty(self):
        g = WorkflowDependencyGraph()
        assert g.max_depth() == 0


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test graph statistics."""

    def test_initial_stats(self):
        g = WorkflowDependencyGraph()
        stats = g.get_stats()
        assert stats.node_count == 0
        assert stats.edge_count == 0

    def test_stats_after_building(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.add_node("c", depends_on=["a"])
        stats = g.get_stats()
        assert stats.node_count == 3
        assert stats.edge_count == 2
        assert stats.root_count == 1
        assert stats.leaf_count == 2
        assert stats.has_cycle is False

    def test_stats_to_dict(self):
        g = WorkflowDependencyGraph()
        d = g.get_stats().to_dict()
        assert "node_count" in d
        assert "has_cycle" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_node_count(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b")
        assert g.node_count == 2

    def test_edge_count(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        assert g.edge_count == 1

    def test_clear(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        g.add_node("b", depends_on=["a"])
        g.clear()
        assert g.node_count == 0
        assert g.edge_count == 0

    def test_to_dict(self):
        g = WorkflowDependencyGraph()
        g.add_node("a")
        d = g.to_dict()
        assert d["node_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global dependency graph."""

    def test_get(self):
        reset_dependency_graph()
        g = get_dependency_graph()
        assert isinstance(g, WorkflowDependencyGraph)

    def test_singleton(self):
        reset_dependency_graph()
        g1 = get_dependency_graph()
        g2 = get_dependency_graph()
        assert g1 is g2

    def test_reset(self):
        reset_dependency_graph()
        g1 = get_dependency_graph()
        reset_dependency_graph()
        g2 = get_dependency_graph()
        assert g1 is not g2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_workflow_package(self):
        from core.workflow import (
            ExecutionOrder,
            GraphStats,
            WorkflowDependencyGraph,
            WorkflowEdge,
            WorkflowNode,
            get_dependency_graph,
            reset_dependency_graph,
        )

        assert all(
            [
                WorkflowDependencyGraph,
                WorkflowNode,
                WorkflowEdge,
                ExecutionOrder,
                GraphStats,
                get_dependency_graph,
                reset_dependency_graph,
            ]
        )

    def test_constants(self):
        assert MAX_NODES == 10000
        assert MAX_EDGES == 50000
