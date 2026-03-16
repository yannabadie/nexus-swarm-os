"""
Tests for Graph of Thought (GoT) - NEXUS V7

Tests the advanced reasoning module for complex problem-solving.

NOTE: These tests require the GoT module to be implemented.
If graph_of_thought.py doesn't exist, all tests will be skipped.
"""

import sys
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check if GoT is available before importing
from core.intelligence.reasoning import GOT_AVAILABLE

if not GOT_AVAILABLE:
    # Skip entire module if GoT not implemented
    pytest.skip(
        "Graph of Thought module not implemented yet (core/reasoning/graph_of_thought.py missing)",
        allow_module_level=True,
    )

# Only import if available (pytest.skip above will prevent reaching here if not available)
from core.intelligence.reasoning.graph_of_thought import (
    GraphOfThought,
    ThoughtGraph,
    ThoughtNode,
    ThoughtStatus,
    ThoughtType,
    create_parallel_exploration,
    create_simple_chain,
)

# ============================================================================
# ThoughtNode Tests
# ============================================================================


class TestThoughtNode:
    """Test ThoughtNode dataclass."""

    def test_default_values(self):
        """Node should have sensible defaults."""
        node = ThoughtNode()

        assert node.id is not None
        assert len(node.id) == 8
        assert node.status == ThoughtStatus.PENDING
        assert node.confidence == 0.0
        assert node.dependencies == []
        assert node.children == []

    def test_create_with_values(self):
        """Node should accept custom values."""
        node = ThoughtNode(name="test_node", question="What is 2+2?", thought_type=ThoughtType.ANALYZE)

        assert node.name == "test_node"
        assert node.question == "What is 2+2?"
        assert node.thought_type == ThoughtType.ANALYZE

    def test_is_ready_no_dependencies(self):
        """Node with no dependencies is always ready."""
        node = ThoughtNode()
        assert node.is_ready(set())
        assert node.is_ready({"other"})

    def test_is_ready_with_dependencies(self):
        """Node with dependencies needs them completed."""
        node = ThoughtNode(dependencies=["dep1", "dep2"])

        assert not node.is_ready(set())
        assert not node.is_ready({"dep1"})
        assert node.is_ready({"dep1", "dep2"})
        assert node.is_ready({"dep1", "dep2", "dep3"})

    def test_mark_completed(self):
        """Mark completed should update status and answer."""
        node = ThoughtNode(question="Test?")
        node.mark_completed("The answer", confidence=0.9, reasoning="Because...")

        assert node.status == ThoughtStatus.COMPLETED
        assert node.answer == "The answer"
        assert node.confidence == 0.9
        assert node.reasoning == "Because..."
        assert node.completed_at is not None

    def test_mark_failed(self):
        """Mark failed should update status."""
        node = ThoughtNode()
        node.mark_failed("Error occurred")

        assert node.status == ThoughtStatus.FAILED
        assert node.reasoning == "Error occurred"

    def test_to_dict(self):
        """Serialization should work."""
        node = ThoughtNode(name="test", question="What?", answer="42")
        d = node.to_dict()

        assert d["name"] == "test"
        assert d["question"] == "What?"
        assert d["answer"] == "42"
        assert "status" in d


# ============================================================================
# ThoughtGraph Tests
# ============================================================================


class TestThoughtGraph:
    """Test ThoughtGraph class."""

    def test_create_empty_graph(self):
        """Empty graph should initialize correctly."""
        graph = ThoughtGraph("test_graph")

        assert graph.name == "test_graph"
        assert len(graph.nodes) == 0
        assert graph.root_nodes == []
        assert graph.leaf_nodes == []

    def test_add_node(self):
        """Adding node should update graph."""
        graph = ThoughtGraph()
        node = ThoughtNode(name="node1", question="Q1")

        node_id = graph.add_node(node)

        assert node_id == node.id
        assert node.id in graph.nodes
        assert node.id in graph.root_nodes  # No dependencies = root
        assert node.id in graph.leaf_nodes  # No children = leaf

    def test_create_node(self):
        """Create node convenience method."""
        graph = ThoughtGraph()
        node = graph.create_node(question="What is X?", name="analyze_x", thought_type=ThoughtType.ANALYZE)

        assert node.name == "analyze_x"
        assert node.id in graph.nodes

    def test_dependency_tracking(self):
        """Dependencies should update children lists."""
        graph = ThoughtGraph()

        node1 = graph.create_node("Step 1", name="step1")
        node2 = graph.create_node("Step 2", name="step2", dependencies=[node1.id])

        assert node2.id in graph.nodes[node1.id].children
        assert node1.id in graph.root_nodes
        assert node1.id not in graph.leaf_nodes  # Has child now
        assert node2.id in graph.leaf_nodes

    def test_get_ready_nodes(self):
        """Should return nodes with satisfied dependencies."""
        graph = ThoughtGraph()

        node1 = graph.create_node("Step 1", name="step1")
        node2 = graph.create_node("Step 2", name="step2", dependencies=[node1.id])
        node3 = graph.create_node("Step 3", name="step3", dependencies=[node1.id])

        # Initially only node1 is ready
        ready = graph.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == node1.id

        # After completing node1, node2 and node3 are ready
        node1.status = ThoughtStatus.COMPLETED
        ready = graph.get_ready_nodes()
        assert len(ready) == 2
        ready_ids = {n.id for n in ready}
        assert node2.id in ready_ids
        assert node3.id in ready_ids

    def test_get_execution_order(self):
        """Should return topological order."""
        graph = ThoughtGraph()

        node1 = graph.create_node("Step 1", name="step1")
        node2 = graph.create_node("Step 2", name="step2", dependencies=[node1.id])
        node3 = graph.create_node("Step 3", name="step3", dependencies=[node2.id])

        order = graph.get_execution_order()

        assert order.index(node1.id) < order.index(node2.id)
        assert order.index(node2.id) < order.index(node3.id)

    def test_is_complete(self):
        """Should detect when all nodes are processed."""
        graph = ThoughtGraph()

        node1 = graph.create_node("Step 1")
        node2 = graph.create_node("Step 2", dependencies=[node1.id])

        assert not graph.is_complete()

        node1.status = ThoughtStatus.COMPLETED
        assert not graph.is_complete()

        node2.status = ThoughtStatus.COMPLETED
        assert graph.is_complete()

    def test_is_complete_with_failed(self):
        """Failed nodes count as complete."""
        graph = ThoughtGraph()

        node = graph.create_node("Step 1")
        node.status = ThoughtStatus.FAILED

        assert graph.is_complete()

    def test_get_final_answer(self):
        """Should aggregate leaf node answers."""
        graph = ThoughtGraph()

        node1 = graph.create_node("Step 1", name="step1")
        node2 = graph.create_node("Step 2", name="step2", dependencies=[node1.id])

        node1.mark_completed("Result 1")
        node2.mark_completed("Final result")

        answer = graph.get_final_answer()
        assert "Final result" in answer

    def test_visualize_ascii(self):
        """ASCII visualization should work."""
        graph = ThoughtGraph("test")

        node1 = graph.create_node("Step 1", name="step1")
        graph.create_node("Step 2", name="step2", dependencies=[node1.id])

        viz = graph.visualize_ascii()

        assert "test" in viz
        assert "step1" in viz
        assert "step2" in viz

    def test_to_dict(self):
        """Graph serialization should work."""
        graph = ThoughtGraph("test")
        graph.create_node("Step 1", name="step1")

        d = graph.to_dict()

        assert d["name"] == "test"
        assert d["node_count"] == 1
        assert "nodes" in d


# ============================================================================
# GraphOfThought Tests
# ============================================================================


class TestGraphOfThought:
    """Test main GraphOfThought class."""

    def test_decompose_problem(self):
        """Should decompose problem into graph."""
        got = GraphOfThought()

        graph = got.decompose_problem(
            main_problem="Fix the bug", sub_problems=["Read the code", "Identify issue", "Design fix", "Implement fix"]
        )

        # Should have: root + 4 steps + aggregation = 6 nodes
        assert len(graph.nodes) == 6

        # Check structure
        assert len(graph.root_nodes) == 1  # main_problem
        assert len(graph.leaf_nodes) == 1  # aggregate

    def test_decompose_with_parallel_groups(self):
        """Should support parallel execution groups."""
        got = GraphOfThought()

        graph = got.decompose_problem(
            main_problem="Analyze codebase",
            sub_problems=["Read frontend code", "Read backend code", "Analyze architecture", "Write report"],
            parallel_groups=[[0, 1]],  # First two steps parallel
        )

        # Get step nodes
        step1 = None
        step2 = None
        for node in graph.nodes.values():
            if node.name == "step_1":
                step1 = node
            elif node.name == "step_2":
                step2 = node

        # Both should depend on root (same dependencies = parallel)
        assert step1 is not None
        assert step2 is not None
        assert step1.dependencies == step2.dependencies

    def test_create_decision_tree(self):
        """Should create decision tree graph."""
        got = GraphOfThought()

        graph = got.create_decision_tree(
            question="Which framework?",
            options=["React", "Vue", "Angular"],
            evaluation_criteria="Performance and learning curve",
        )

        # Should have: root + 3 evaluations + final decision = 5 nodes
        assert len(graph.nodes) == 5

        # Find decision node
        decision_node = None
        for node in graph.nodes.values():
            if node.thought_type == ThoughtType.DECISION:
                decision_node = node
                break

        assert decision_node is not None
        assert len(decision_node.dependencies) == 3  # 3 evaluation nodes

    def test_execute_simple_graph(self):
        """Should execute graph with executor function."""
        got = GraphOfThought()

        graph = got.decompose_problem(main_problem="Calculate sum", sub_problems=["Get number 1", "Get number 2"])

        # Simple executor that returns canned answers
        def executor(node: ThoughtNode) -> str:
            if "number 1" in node.question:
                return "5"
            elif "number 2" in node.question:
                return "3"
            elif "Aggregate" in node.question:
                return "Sum is 8"
            return "Done"

        result = got.execute(graph, executor)

        assert result.is_complete()
        assert result.get_completed_count() == 4  # root + 2 steps + aggregate

    def test_execute_handles_failure(self):
        """Should handle executor failures."""
        got = GraphOfThought()

        graph = got.decompose_problem(main_problem="Test failure", sub_problems=["Failing step"])

        call_count = 0

        def failing_executor(node: ThoughtNode) -> str:
            nonlocal call_count
            call_count += 1
            if "Failing" in node.question:
                raise Exception("Simulated failure")
            return "OK"

        result = got.execute(graph, failing_executor)

        # Should have attempted retries
        failing_node = None
        for node in result.nodes.values():
            if "Failing" in node.question:
                failing_node = node
                break

        assert failing_node is not None
        assert failing_node.status == ThoughtStatus.FAILED
        assert failing_node.attempts == failing_node.max_attempts


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_create_simple_chain(self):
        """Should create sequential chain."""
        graph = create_simple_chain(["Main task", "Step 1", "Step 2", "Step 3"])

        assert len(graph.nodes) >= 3

    def test_create_parallel_exploration(self):
        """Should create parallel branches."""
        graph = create_parallel_exploration(
            question="How to optimize?", approaches=["Caching", "Indexing", "Parallelization"]
        )

        # Should have: root + 3 approaches + aggregate = 5 nodes
        assert len(graph.nodes) == 5

        # All approaches should depend on root
        approach_nodes = [n for n in graph.nodes.values() if n.thought_type == ThoughtType.GENERATE]
        assert len(approach_nodes) == 3

        # All should have same parent (root)
        parent_ids = set()
        for node in approach_nodes:
            parent_ids.update(node.dependencies)
        assert len(parent_ids) == 1  # All share same parent


# ============================================================================
# Parallel Execution Tests
# ============================================================================


class TestParallelExecution:
    """Test parallel execution features."""

    def test_execute_parallel_basic(self):
        """Should execute graph in parallel."""
        got = GraphOfThought()
        graph = got.decompose_problem("Test parallel", sub_problems=["Step 1", "Step 2", "Step 3"])

        def mock_executor(node: ThoughtNode) -> str:
            return f"Result for {node.name}"

        result = got.execute_parallel(graph, mock_executor, max_workers=2)

        assert result.is_complete()
        assert result.get_failed_count() == 0

    def test_execute_parallel_with_callback(self):
        """Should call progress callback."""
        got = GraphOfThought()
        graph = got.decompose_problem("Test callbacks", sub_problems=["Step 1"])

        events = []

        def on_progress(g, node, event):
            events.append((node.name, event))

        def mock_executor(node: ThoughtNode) -> str:
            return "Done"

        got.execute_parallel(graph, mock_executor, on_progress=on_progress)

        # Should have started and completed events
        assert any("started" in e[1] for e in events)
        assert any("completed" in e[1] for e in events)

    def test_execute_parallel_handles_failure(self):
        """Should handle node failures gracefully."""
        got = GraphOfThought()
        graph = got.decompose_problem("Test failure", sub_problems=["Failing step"])

        def failing_executor(node: ThoughtNode) -> str:
            if "Failing" in node.question:
                raise Exception("Simulated failure")
            return "Done"

        result = got.execute_parallel(graph, failing_executor)

        # Should complete (with failures)
        assert result.is_complete()

    def test_get_execution_progress(self):
        """Should return progress metrics."""
        got = GraphOfThought()
        graph = got.decompose_problem("Test progress", sub_problems=["Step 1", "Step 2"])

        # Before execution
        progress = got.get_execution_progress(graph)
        assert progress["total"] > 0
        assert progress["pending"] > 0
        assert progress["completed"] == 0

        # After execution
        def mock_executor(node: ThoughtNode) -> str:
            return "Done"

        got.execute(graph, mock_executor)
        progress = got.get_execution_progress(graph)

        assert progress["completed"] > 0
        assert progress["is_complete"]

    def test_visualize_progress(self):
        """Should generate progress visualization."""
        got = GraphOfThought()
        graph = got.decompose_problem("Test viz", sub_problems=["Step 1"], name="test_graph")

        viz = got.visualize_progress(graph)

        assert "test_graph" in viz  # Graph name in header
        assert "%" in viz  # Progress percentage
        assert "⏳" in viz or "[OK]" in viz  # Status icons
        assert "main_problem" in viz  # Node name


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for complex scenarios."""

    def test_full_workflow(self):
        """Test complete problem-solving workflow."""
        got = GraphOfThought()

        # 1. Decompose a complex problem
        graph = got.decompose_problem(
            main_problem="Refactor authentication module",
            sub_problems=[
                "Analyze current auth.py code",
                "Identify security vulnerabilities",
                "Design new JWT-based flow",
                "Implement token generation",
                "Implement token validation",
                "Add unit tests",
                "Update documentation",
            ],
            parallel_groups=[[3, 4], [5, 6]],  # Implement parallel, then test/doc parallel
        )

        # 2. Verify graph structure
        assert len(graph.nodes) >= 8  # 1 root + 7 steps + aggregation

        # 3. Execute with mock executor
        responses = {
            "Analyze": "Current code uses session-based auth",
            "Identify": "Found SQL injection risk in login",
            "Design": "Use JWT with RSA256",
            "generation": "Token generation implemented",
            "validation": "Token validation implemented",
            "tests": "15 tests added, all passing",
            "documentation": "README updated",
            "Aggregate": "Refactoring complete",
        }

        def mock_executor(node: ThoughtNode) -> str:
            for key, response in responses.items():
                if key.lower() in node.question.lower():
                    return response
            return "Done"

        result = got.execute(graph, mock_executor)

        # 4. Verify completion
        assert result.is_complete()
        assert result.get_failed_count() == 0

        # 5. Get final answer
        answer = result.get_final_answer()
        assert len(answer) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
