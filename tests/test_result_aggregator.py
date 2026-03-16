"""
Tests for V12.4 Result Aggregator.

Validates:
- MergeStrategy enum values
- AgentResult creation
- Conflict detection and to_dict
- MergeResult to_dict
- Submit results from agents
- Query results (get, list, has)
- Conflict detection between agents
- Merge strategies (union, first, latest, longest, vote)
- Completeness validation
- Task removal
- Statistics tracking
- State management
- Global singleton
- Module exports
"""

from core.intelligence.swarm.result_aggregator import (
    AgentResult,
    Conflict,
    MergeStrategy,
    ResultAggregator,
    get_aggregator,
    reset_aggregator,
)

# =============================================================================
# MergeStrategy Tests
# =============================================================================


class TestMergeStrategy:
    """Test MergeStrategy enum."""

    def test_union(self):
        assert MergeStrategy.UNION.value == "union"

    def test_first(self):
        assert MergeStrategy.FIRST.value == "first"

    def test_latest(self):
        assert MergeStrategy.LATEST.value == "latest"

    def test_longest(self):
        assert MergeStrategy.LONGEST.value == "longest"

    def test_vote(self):
        assert MergeStrategy.VOTE.value == "vote"

    def test_count(self):
        assert len(MergeStrategy) == 5


# =============================================================================
# AgentResult Tests
# =============================================================================


class TestAgentResult:
    """Test AgentResult dataclass."""

    def test_basic(self):
        r = AgentResult(task_id="t1", agent_id="claude", data={"k": "v"})
        assert r.task_id == "t1"
        assert r.agent_id == "claude"
        assert r.data == {"k": "v"}

    def test_auto_timestamp(self):
        r = AgentResult(task_id="t1", agent_id="a", data={})
        assert r.timestamp > 0

    def test_confidence_default(self):
        r = AgentResult(task_id="t1", agent_id="a", data={})
        assert r.confidence == 1.0


# =============================================================================
# Conflict Tests
# =============================================================================


class TestConflict:
    """Test Conflict dataclass."""

    def test_creation(self):
        c = Conflict(key="analysis", values={"claude": "A", "gemini": "B"})
        assert c.key == "analysis"
        assert c.resolved is False

    def test_to_dict(self):
        c = Conflict(key="k", values={"a": 1, "b": 2})
        d = c.to_dict()
        assert d["key"] == "k"
        assert d["resolved"] is False


# =============================================================================
# Submit Tests
# =============================================================================


class TestSubmit:
    """Test result submission."""

    def test_submit(self):
        agg = ResultAggregator()
        r = agg.submit("t1", "claude", {"analysis": "found bug"})
        assert r.task_id == "t1"
        assert agg.task_count == 1

    def test_submit_multiple_agents(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"a": 1})
        agg.submit("t1", "gemini", {"b": 2})
        assert agg.task_count == 1
        assert len(agg.get_agents("t1")) == 2

    def test_submit_overwrite(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"v": 1})
        agg.submit("t1", "claude", {"v": 2})
        r = agg.get_result("t1", "claude")
        assert r.data["v"] == 2

    def test_confidence_clamped(self):
        agg = ResultAggregator()
        r = agg.submit("t1", "claude", {}, confidence=1.5)
        assert r.confidence == 1.0


# =============================================================================
# Query Tests
# =============================================================================


class TestQuery:
    """Test result queries."""

    def test_get_results(self):
        agg = ResultAggregator()
        agg.submit("t1", "a", {"k": 1})
        agg.submit("t1", "b", {"k": 2})
        results = agg.get_results("t1")
        assert len(results) == 2

    def test_get_results_empty(self):
        agg = ResultAggregator()
        assert agg.get_results("missing") == []

    def test_get_result(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"v": 42})
        r = agg.get_result("t1", "claude")
        assert r.data["v"] == 42

    def test_get_result_not_found(self):
        agg = ResultAggregator()
        assert agg.get_result("t1", "missing") is None

    def test_get_agents(self):
        agg = ResultAggregator()
        agg.submit("t1", "b_agent", {})
        agg.submit("t1", "a_agent", {})
        assert agg.get_agents("t1") == ["a_agent", "b_agent"]

    def test_has_result(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {})
        assert agg.has_result("t1", "claude") is True
        assert agg.has_result("t1", "gemini") is False


# =============================================================================
# Conflict Detection Tests
# =============================================================================


class TestConflictDetection:
    """Test conflict detection."""

    def test_no_conflict(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"analysis": "same"})
        agg.submit("t1", "gemini", {"analysis": "same"})
        conflicts = agg.detect_conflicts("t1")
        assert len(conflicts) == 0

    def test_conflict_detected(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"severity": "high"})
        agg.submit("t1", "gemini", {"severity": "medium"})
        conflicts = agg.detect_conflicts("t1")
        assert len(conflicts) == 1
        assert conflicts[0].key == "severity"

    def test_no_conflict_single_agent(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"k": "v"})
        assert agg.detect_conflicts("t1") == []

    def test_no_conflict_different_keys(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"a": 1})
        agg.submit("t1", "gemini", {"b": 2})
        assert agg.detect_conflicts("t1") == []

    def test_multiple_conflicts(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"severity": "high", "fix": "patch A"})
        agg.submit("t1", "gemini", {"severity": "low", "fix": "patch B"})
        conflicts = agg.detect_conflicts("t1")
        assert len(conflicts) == 2


# =============================================================================
# Merge Tests
# =============================================================================


class TestMerge:
    """Test result merging."""

    def test_merge_no_conflict(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"a": 1, "b": 2})
        agg.submit("t1", "gemini", {"a": 1, "c": 3})
        result = agg.merge("t1")
        assert result.merged_data["a"] == 1
        assert result.merged_data["b"] == 2
        assert result.merged_data["c"] == 3
        assert result.conflict_count == 0

    def test_merge_empty(self):
        agg = ResultAggregator()
        result = agg.merge("missing")
        assert result.merged_data == {}
        assert result.agent_count == 0

    def test_merge_union_lists(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"bugs": ["bug1", "bug2"]})
        agg.submit("t1", "gemini", {"bugs": ["bug2", "bug3"]})
        result = agg.merge("t1", strategy=MergeStrategy.UNION)
        assert len(result.merged_data["bugs"]) == 3

    def test_merge_longest(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"analysis": "short"})
        agg.submit("t1", "gemini", {"analysis": "much longer analysis"})
        result = agg.merge("t1", strategy=MergeStrategy.LONGEST)
        assert result.merged_data["analysis"] == "much longer analysis"

    def test_merge_to_dict(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"k": "v"})
        result = agg.merge("t1")
        d = result.to_dict()
        assert d["task_id"] == "t1"
        assert "merged_keys" in d

    def test_merge_strategy_in_result(self):
        agg = ResultAggregator()
        agg.submit("t1", "a", {"k": "v"})
        result = agg.merge("t1", strategy=MergeStrategy.LATEST)
        assert result.strategy == "latest"

    def test_merge_conflict_count(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"severity": "high"})
        agg.submit("t1", "gemini", {"severity": "low"})
        result = agg.merge("t1")
        assert result.conflict_count == 1


# =============================================================================
# Completeness Tests
# =============================================================================


class TestCompleteness:
    """Test completeness validation."""

    def test_is_complete(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {})
        agg.submit("t1", "gemini", {})
        assert agg.is_complete("t1", ["claude", "gemini"]) is True

    def test_not_complete(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {})
        assert agg.is_complete("t1", ["claude", "gemini"]) is False

    def test_missing_agents(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {})
        missing = agg.missing_agents("t1", ["claude", "gemini", "ollama"])
        assert missing == ["gemini", "ollama"]

    def test_missing_none(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {})
        assert agg.missing_agents("t1", ["claude"]) == []


# =============================================================================
# Cleanup Tests
# =============================================================================


class TestCleanup:
    """Test cleanup operations."""

    def test_remove_task(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {})
        assert agg.remove_task("t1") is True
        assert agg.task_count == 0

    def test_remove_task_not_found(self):
        agg = ResultAggregator()
        assert agg.remove_task("missing") is False

    def test_max_tasks(self):
        agg = ResultAggregator(max_tasks=3)
        for i in range(5):
            agg.submit(f"t{i}", "claude", {"i": i})
        assert agg.task_count <= 3


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test aggregator statistics."""

    def test_initial_stats(self):
        agg = ResultAggregator()
        stats = agg.get_stats()
        assert stats.total_tasks == 0
        assert stats.total_submissions == 0

    def test_stats_after_operations(self):
        agg = ResultAggregator()
        agg.submit("t1", "claude", {"s": "high"})
        agg.submit("t1", "gemini", {"s": "low"})
        agg.merge("t1")
        stats = agg.get_stats()
        assert stats.total_submissions == 2
        assert stats.total_merges == 1
        assert stats.total_conflicts == 1

    def test_stats_to_dict(self):
        agg = ResultAggregator()
        d = agg.get_stats().to_dict()
        assert "total_tasks" in d
        assert "total_merges" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_task_count(self):
        agg = ResultAggregator()
        agg.submit("t1", "a", {})
        agg.submit("t2", "a", {})
        assert agg.task_count == 2

    def test_clear(self):
        agg = ResultAggregator()
        agg.submit("t1", "a", {})
        agg.merge("t1")
        agg.clear()
        assert agg.task_count == 0
        stats = agg.get_stats()
        assert stats.total_submissions == 0

    def test_to_dict(self):
        agg = ResultAggregator()
        agg.submit("t1", "a", {})
        d = agg.to_dict()
        assert d["task_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global aggregator."""

    def test_get_aggregator(self):
        reset_aggregator()
        agg = get_aggregator()
        assert isinstance(agg, ResultAggregator)

    def test_singleton(self):
        reset_aggregator()
        a1 = get_aggregator()
        a2 = get_aggregator()
        assert a1 is a2

    def test_reset(self):
        reset_aggregator()
        a1 = get_aggregator()
        reset_aggregator()
        a2 = get_aggregator()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_swarm_package(self):
        from core.intelligence.swarm import (
            AggregatorStats,
            MergeResult,
            MergeStrategy,
            ResultAggregator,
            get_aggregator,
            reset_aggregator,
        )

        assert all(
            [
                ResultAggregator,
                MergeStrategy,
                MergeResult,
                AggregatorStats,
                get_aggregator,
                reset_aggregator,
            ]
        )

    def test_from_module(self):
        from core.intelligence.swarm.result_aggregator import (
            MAX_TASKS,
        )

        assert MAX_TASKS == 5000
