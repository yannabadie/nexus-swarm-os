"""
Tests for V12.4 Workflow Performance Analyzer.

Validates:
- WorkflowRunRecord to_dict / properties
- WorkflowProfile to_dict / properties
- PerformanceStats to_dict
- Recording runs
- Profile updates
- Queries (all profiles, best workflow, recent, list workflows)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.workflow.workflow_performance_analyzer import (
    MAX_WORKFLOW_RECORDS,
    PerformanceStats,
    WorkflowPerformanceAnalyzer,
    WorkflowProfile,
    WorkflowRunRecord,
    get_workflow_analyzer,
    reset_workflow_analyzer,
)

# =============================================================================
# WorkflowRunRecord Tests
# =============================================================================


class TestWorkflowRunRecord:
    """Test WorkflowRunRecord dataclass."""

    def test_completion_rate(self):
        r = WorkflowRunRecord(steps_total=10, steps_completed=8)
        assert abs(r.completion_rate - 0.8) < 0.01

    def test_completion_rate_zero(self):
        r = WorkflowRunRecord()
        assert r.completion_rate == 0.0

    def test_to_dict(self):
        r = WorkflowRunRecord(workflow_name="pipeline", steps_total=10, steps_completed=8)
        d = r.to_dict()
        assert "completion_rate" in d
        assert d["workflow_name"] == "pipeline"


# =============================================================================
# WorkflowProfile Tests
# =============================================================================


class TestWorkflowProfile:
    """Test WorkflowProfile dataclass."""

    def test_avg_completion_rate(self):
        p = WorkflowProfile(
            workflow_name="pipeline",
            total_steps_completed=8,
            total_steps_attempted=10,
        )
        assert abs(p.avg_completion_rate - 0.8) < 0.01

    def test_avg_completion_rate_zero(self):
        p = WorkflowProfile(workflow_name="pipeline")
        assert p.avg_completion_rate == 0.0

    def test_avg_duration(self):
        p = WorkflowProfile(workflow_name="pipeline", total_runs=4, total_duration_ms=4000.0)
        assert abs(p.avg_duration_ms - 1000.0) < 0.01

    def test_avg_duration_zero(self):
        p = WorkflowProfile(workflow_name="pipeline")
        assert p.avg_duration_ms == 0.0

    def test_avg_parallel_efficiency(self):
        p = WorkflowProfile(workflow_name="pipeline", total_runs=4, total_parallel_efficiency=3.2)
        assert abs(p.avg_parallel_efficiency - 0.8) < 0.01

    def test_avg_parallel_efficiency_zero(self):
        p = WorkflowProfile(workflow_name="pipeline")
        assert p.avg_parallel_efficiency == 0.0

    def test_to_dict(self):
        p = WorkflowProfile(workflow_name="pipeline", total_runs=5)
        d = p.to_dict()
        assert "avg_completion_rate" in d
        assert "avg_duration_ms" in d
        assert "avg_parallel_efficiency" in d


# =============================================================================
# PerformanceStats Tests
# =============================================================================


class TestPerformanceStats:
    """Test PerformanceStats dataclass."""

    def test_to_dict(self):
        s = PerformanceStats(total_runs=20, unique_workflows=3)
        d = s.to_dict()
        assert d["total_runs"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test run recording."""

    def test_record_basic(self):
        a = WorkflowPerformanceAnalyzer()
        r = a.record_run("pipeline", steps_total=10, steps_completed=8)
        assert r.run_id == "wr_000001"
        assert a.run_count == 1

    def test_profile_updates(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("pipeline", steps_total=10, steps_completed=8, total_duration_ms=1000, parallel_efficiency=0.8)
        a.record_run("pipeline", steps_total=5, steps_completed=5, total_duration_ms=500, parallel_efficiency=0.9)
        p = a.get_workflow_profile("pipeline")
        assert p is not None
        assert p.total_runs == 2
        assert p.total_steps_completed == 13

    def test_multiple_workflows(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("pipeline_a")
        a.record_run("pipeline_b")
        assert len(a.get_all_profiles()) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        a = WorkflowPerformanceAnalyzer()
        assert a.get_workflow_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("once")
        a.record_run("twice")
        a.record_run("twice")
        profiles = a.get_all_profiles()
        assert profiles[0].workflow_name == "twice"  # 2 > 1

    def test_best_workflow(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("good", steps_total=10, steps_completed=9)
        a.record_run("bad", steps_total=10, steps_completed=3)
        assert a.get_best_workflow() == "good"

    def test_best_workflow_empty(self):
        a = WorkflowPerformanceAnalyzer()
        assert a.get_best_workflow() is None

    def test_recent_runs(self):
        a = WorkflowPerformanceAnalyzer()
        for _i in range(5):
            a.record_run("pipeline")
        recent = a.get_recent_runs(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("alpha")
        a.record_run("beta")
        a.record_run("alpha")
        recent = a.get_recent_runs(workflow_name="alpha")
        assert len(recent) == 2

    def test_list_workflows(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("zeta")
        a.record_run("alpha")
        assert a.list_workflows() == ["alpha", "zeta"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded run history."""

    def test_eviction(self):
        a = WorkflowPerformanceAnalyzer(max_records=5)
        for _i in range(10):
            a.record_run("pipeline")
        assert a.run_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analyzer statistics."""

    def test_initial_stats(self):
        a = WorkflowPerformanceAnalyzer()
        stats = a.get_stats()
        assert stats.total_runs == 0

    def test_stats_after_recording(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("pipeline_a", steps_total=10, steps_completed=8)
        a.record_run("pipeline_b", steps_total=5, steps_completed=5)
        stats = a.get_stats()
        assert stats.total_runs == 2
        assert stats.unique_workflows == 2

    def test_stats_to_dict(self):
        a = WorkflowPerformanceAnalyzer()
        d = a.get_stats().to_dict()
        assert "total_runs" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("pipeline")
        assert a.run_count == 1

    def test_clear(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("pipeline")
        a.clear()
        assert a.run_count == 0
        assert a.get_workflow_profile("pipeline") is None

    def test_to_dict(self):
        a = WorkflowPerformanceAnalyzer()
        a.record_run("pipeline")
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global workflow analyzer."""

    def test_get(self):
        reset_workflow_analyzer()
        a = get_workflow_analyzer()
        assert isinstance(a, WorkflowPerformanceAnalyzer)

    def test_singleton(self):
        reset_workflow_analyzer()
        a1 = get_workflow_analyzer()
        a2 = get_workflow_analyzer()
        assert a1 is a2

    def test_reset(self):
        reset_workflow_analyzer()
        a1 = get_workflow_analyzer()
        reset_workflow_analyzer()
        a2 = get_workflow_analyzer()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_workflow_package(self):
        from core.workflow import (
            WorkflowPerformanceAnalyzer,
            WorkflowPerformanceStats,
            WorkflowProfile,
            WorkflowRunRecord,
            get_workflow_analyzer,
            reset_workflow_analyzer,
        )

        assert all(
            [
                WorkflowPerformanceAnalyzer,
                WorkflowRunRecord,
                WorkflowProfile,
                WorkflowPerformanceStats,
                get_workflow_analyzer,
                reset_workflow_analyzer,
            ]
        )

    def test_constants(self):
        assert MAX_WORKFLOW_RECORDS == 50000
