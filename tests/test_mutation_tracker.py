"""
Tests for V12.4 Mutation Tracker.

Validates:
- MutationRecord creation and to_dict
- AgentPerformance metrics (success_rate, avg_score)
- LineageNode to_dict
- VariantComparison to_dict
- TrackerStats to_dict
- Record mutations
- Lineage queries (children, parent, ancestors, descendants, siblings)
- Generation tracking
- Root agents
- Performance recording and EMA
- Variant comparison
- Rollback version lookup
- Max mutations enforcement
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.evolution.mutation_tracker import (
    AgentPerformance,
    LineageNode,
    MutationRecord,
    MutationTracker,
    get_mutation_tracker,
    reset_mutation_tracker,
)

# =============================================================================
# MutationRecord Tests
# =============================================================================


class TestMutationRecord:
    """Test MutationRecord dataclass."""

    def test_basic(self):
        r = MutationRecord(parent_id="p", child_id="c", strategy="specialize")
        assert r.parent_id == "p"
        assert r.child_id == "c"
        assert r.strategy == "specialize"

    def test_auto_timestamp(self):
        r = MutationRecord(parent_id="p", child_id="c", strategy="s")
        assert r.timestamp > 0

    def test_to_dict(self):
        r = MutationRecord(parent_id="p", child_id="c", strategy="s", generation=2)
        d = r.to_dict()
        assert d["parent_id"] == "p"
        assert d["generation"] == 2


# =============================================================================
# AgentPerformance Tests
# =============================================================================


class TestAgentPerformance:
    """Test AgentPerformance dataclass."""

    def test_success_rate(self):
        p = AgentPerformance(agent_id="a", total_tasks=10, successful_tasks=8)
        assert p.success_rate == 0.8

    def test_success_rate_zero(self):
        p = AgentPerformance(agent_id="a")
        assert p.success_rate == 0.0

    def test_latest_score(self):
        p = AgentPerformance(agent_id="a", scores=[0.5, 0.7, 0.9])
        assert p.latest_score == 0.9

    def test_latest_score_empty(self):
        p = AgentPerformance(agent_id="a")
        assert p.latest_score == 0.0

    def test_to_dict(self):
        p = AgentPerformance(agent_id="a", total_tasks=5, avg_score=0.75)
        d = p.to_dict()
        assert d["agent_id"] == "a"
        assert d["avg_score"] == 0.75


# =============================================================================
# LineageNode Tests
# =============================================================================


class TestLineageNode:
    """Test LineageNode dataclass."""

    def test_to_dict(self):
        n = LineageNode(agent_id="a", parent_id="p", children=["c1", "c2"])
        d = n.to_dict()
        assert d["agent_id"] == "a"
        assert d["parent_id"] == "p"
        assert len(d["children"]) == 2


# =============================================================================
# Record Mutation Tests
# =============================================================================


class TestRecordMutation:
    """Test mutation recording."""

    def test_record(self):
        t = MutationTracker()
        rec = t.record_mutation("parent", "child", "specialize")
        assert rec.parent_id == "parent"
        assert rec.child_id == "child"
        assert t.mutation_count == 1

    def test_record_sets_generation(self):
        t = MutationTracker()
        t.record_mutation("root", "gen1", "s")
        t.record_mutation("gen1", "gen2", "s")
        assert t.get_generation("gen2") == 2

    def test_record_with_metadata(self):
        t = MutationTracker()
        rec = t.record_mutation("p", "c", "s", metadata={"domain": "security"})
        assert rec.metadata["domain"] == "security"

    def test_auto_creates_parent_node(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        assert t.get_lineage_node("root") is not None

    def test_creates_child_node(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        node = t.get_lineage_node("child")
        assert node is not None
        assert node.parent_id == "root"


# =============================================================================
# Lineage Query Tests
# =============================================================================


class TestLineageQueries:
    """Test lineage traversal."""

    def test_get_children(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_mutation("root", "b", "s")
        children = t.get_children("root")
        assert sorted(children) == ["a", "b"]

    def test_get_children_empty(self):
        t = MutationTracker()
        assert t.get_children("missing") == []

    def test_get_parent(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        assert t.get_parent("child") == "root"

    def test_get_parent_root(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        assert t.get_parent("root") is None

    def test_get_ancestors(self):
        t = MutationTracker()
        t.record_mutation("root", "gen1", "s")
        t.record_mutation("gen1", "gen2", "s")
        t.record_mutation("gen2", "gen3", "s")
        ancestors = t.get_ancestors("gen3")
        assert ancestors == ["root", "gen1", "gen2"]

    def test_get_ancestors_root(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        assert t.get_ancestors("root") == []

    def test_get_descendants(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_mutation("root", "b", "s")
        t.record_mutation("a", "a1", "s")
        desc = t.get_descendants("root")
        assert set(desc) == {"a", "b", "a1"}

    def test_get_descendants_leaf(self):
        t = MutationTracker()
        t.record_mutation("root", "leaf", "s")
        assert t.get_descendants("leaf") == []

    def test_get_siblings(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_mutation("root", "b", "s")
        t.record_mutation("root", "c", "s")
        siblings = t.get_siblings("a")
        assert sorted(siblings) == ["b", "c"]

    def test_get_siblings_no_parent(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        assert t.get_siblings("root") == []

    def test_get_generation(self):
        t = MutationTracker()
        t.record_mutation("root", "g1", "s")
        t.record_mutation("g1", "g2", "s")
        assert t.get_generation("root") == 0
        assert t.get_generation("g1") == 1
        assert t.get_generation("g2") == 2

    def test_get_generation_unknown(self):
        t = MutationTracker()
        assert t.get_generation("missing") == -1

    def test_get_root_agents(self):
        t = MutationTracker()
        t.record_mutation("root1", "a", "s")
        t.record_mutation("root2", "b", "s")
        roots = t.get_root_agents()
        assert sorted(roots) == ["root1", "root2"]


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Test performance tracking."""

    def test_record_performance(self):
        t = MutationTracker()
        t.record_performance("a", task_success=True, score=0.9)
        perf = t.get_performance("a")
        assert perf is not None
        assert perf.total_tasks == 1
        assert perf.successful_tasks == 1

    def test_record_multiple(self):
        t = MutationTracker()
        t.record_performance("a", task_success=True, score=0.9)
        t.record_performance("a", task_success=False, score=0.3)
        perf = t.get_performance("a")
        assert perf.total_tasks == 2
        assert perf.successful_tasks == 1
        assert perf.success_rate == 0.5

    def test_ema_score(self):
        t = MutationTracker()
        t.record_performance("a", score=1.0)
        t.record_performance("a", score=0.0)
        perf = t.get_performance("a")
        # EMA: 1.0 -> 0.9*1.0 + 0.1*0.0 = 0.9
        assert abs(perf.avg_score - 0.9) < 0.01

    def test_get_performance_not_found(self):
        t = MutationTracker()
        assert t.get_performance("missing") is None


# =============================================================================
# Variant Comparison Tests
# =============================================================================


class TestVariantComparison:
    """Test variant comparison."""

    def test_compare_variants(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_mutation("root", "b", "s")
        t.record_performance("a", score=0.9)
        t.record_performance("b", score=0.5)
        comp = t.compare_variants("root")
        assert comp is not None
        assert comp.best_variant == "a"
        assert comp.worst_variant == "b"

    def test_compare_no_children(self):
        t = MutationTracker()
        assert t.compare_variants("root") is None

    def test_compare_no_performance(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        assert t.compare_variants("root") is None

    def test_comparison_to_dict(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_performance("a", score=0.8)
        comp = t.compare_variants("root")
        d = comp.to_dict()
        assert "parent_id" in d
        assert "best_variant" in d


# =============================================================================
# Rollback Tests
# =============================================================================


class TestRollback:
    """Test rollback version lookup."""

    def test_rollback_to_parent(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        t.record_performance("root", task_success=True, score=0.8)
        assert t.get_rollback_version("child") == "root"

    def test_rollback_no_parent(self):
        t = MutationTracker()
        t.record_mutation("root", "child", "s")
        assert t.get_rollback_version("root") is None

    def test_rollback_grandparent(self):
        t = MutationTracker()
        t.record_mutation("root", "gen1", "s")
        t.record_mutation("gen1", "gen2", "s")
        # gen1 has low success, falls through to grandparent
        t.record_performance("gen1", task_success=False, score=0.1)
        rollback = t.get_rollback_version("gen2")
        assert rollback == "root"


# =============================================================================
# Max Mutations Tests
# =============================================================================


class TestMaxMutations:
    """Test max mutations enforcement."""

    def test_eviction(self):
        t = MutationTracker(max_mutations=3)
        for i in range(5):
            t.record_mutation("root", f"c{i}", "s")
        assert t.mutation_count == 3


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = MutationTracker()
        stats = t.get_stats()
        assert stats.total_mutations == 0
        assert stats.total_agents == 0

    def test_stats_after_mutations(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_mutation("a", "b", "s")
        t.record_performance("a", score=0.8)
        stats = t.get_stats()
        assert stats.total_mutations == 2
        assert stats.total_agents == 3
        assert stats.root_agents == 1
        assert stats.max_generation == 2
        assert stats.total_performance_records == 1

    def test_stats_to_dict(self):
        t = MutationTracker()
        d = t.get_stats().to_dict()
        assert "total_mutations" in d
        assert "max_generation" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_mutation_count(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        assert t.mutation_count == 1

    def test_agent_count(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        assert t.agent_count == 2  # root + child

    def test_clear(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        t.record_performance("a", score=0.8)
        t.clear()
        assert t.mutation_count == 0
        assert t.agent_count == 0

    def test_to_dict(self):
        t = MutationTracker()
        t.record_mutation("root", "a", "s")
        d = t.to_dict()
        assert d["mutation_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global mutation tracker."""

    def test_get_mutation_tracker(self):
        reset_mutation_tracker()
        tracker = get_mutation_tracker()
        assert isinstance(tracker, MutationTracker)

    def test_singleton(self):
        reset_mutation_tracker()
        t1 = get_mutation_tracker()
        t2 = get_mutation_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_mutation_tracker()
        t1 = get_mutation_tracker()
        reset_mutation_tracker()
        t2 = get_mutation_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_evolution_package(self):
        from core.intelligence.evolution import (
            AgentPerformance,
            LineageNode,
            MutationRecord,
            MutationTracker,
            get_mutation_tracker,
            reset_mutation_tracker,
        )

        assert all(
            [
                MutationTracker,
                MutationRecord,
                AgentPerformance,
                LineageNode,
                get_mutation_tracker,
                reset_mutation_tracker,
            ]
        )

    def test_from_module(self):
        from core.intelligence.evolution.mutation_tracker import (
            LEARNING_RATE,
            MAX_MUTATIONS,
        )

        assert MAX_MUTATIONS == 10000
        assert LEARNING_RATE == 0.1
