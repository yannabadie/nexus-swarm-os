"""Tests for AutoMemory - Pattern learning from successes and failures."""

import json
from pathlib import Path

from core.memory_pkg.memory.auto_memory import (
    AutoMemory,
    MemoryEntry,
    get_auto_memory,
    reset_auto_memory,
)

# =============================================================================
# MemoryEntry
# =============================================================================


class TestMemoryEntry:
    def test_creation(self):
        entry = MemoryEntry(
            timestamp="2025-01-01T00:00:00",
            task_type="code_review",
            task_description="Review auth module",
            swarm_mode="PING_PONG",
            lead_agent="claude",
            duration_seconds=120.0,
            outcome="success",
        )
        assert entry.task_type == "code_review"
        assert entry.outcome == "success"
        assert entry.reason is None
        assert entry.score is None

    def test_failure_entry(self):
        entry = MemoryEntry(
            timestamp="2025-01-01T00:00:00",
            task_type="debugging",
            task_description="Fix auth bug",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=300.0,
            outcome="failure",
            reason="timeout",
            score=0.0,
        )
        assert entry.outcome == "failure"
        assert entry.reason == "timeout"


# =============================================================================
# AutoMemory - Recording
# =============================================================================


class TestRecording:
    def setup_method(self, tmp_path_factory=None):
        self.tmp = Path("workspace_test_auto_memory")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.memory = AutoMemory(workspace_path=self.tmp)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_success(self):
        self.memory.record_success(
            task_type="code_review",
            task_description="Review auth",
            swarm_mode="PING_PONG",
            lead_agent="claude",
            duration_seconds=60.0,
        )
        assert len(self.memory._success_cache["code_review"]) == 1

    def test_record_failure(self):
        self.memory.record_failure(
            task_type="debugging",
            task_description="Fix bug",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=300.0,
            reason="timeout",
        )
        assert len(self.memory._failure_cache["debugging"]) == 1

    def test_success_persists_to_file(self):
        self.memory.record_success(
            task_type="test",
            task_description="test",
            swarm_mode="PARALLEL",
            lead_agent="claude",
            duration_seconds=10.0,
        )
        assert self.memory.successes_file.exists()
        with open(self.memory.successes_file) as f:
            data = json.loads(f.readline())
        assert data["task_type"] == "test"
        assert data["outcome"] == "success"

    def test_failure_persists_to_file(self):
        self.memory.record_failure(
            task_type="test",
            task_description="test",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=10.0,
            reason="error",
        )
        assert self.memory.failures_file.exists()

    def test_fitness_updated(self):
        self.memory.record_success(
            task_type="coding",
            task_description="write code",
            swarm_mode="SPECIALIST",
            lead_agent="claude",
            duration_seconds=30.0,
            score=0.9,
        )
        assert self.memory.fitness_file.exists()
        with open(self.memory.fitness_file) as f:
            data = json.load(f)
        assert "claude" in data
        assert data["claude"]["tasks"]["coding"]["avg"] == 0.9

    def test_multiple_records(self):
        for i in range(5):
            self.memory.record_success(
                task_type="coding",
                task_description=f"task {i}",
                swarm_mode="PING_PONG",
                lead_agent="claude",
                duration_seconds=10.0,
                score=0.8 + i * 0.02,
            )
        assert len(self.memory._success_cache["coding"]) == 5


# =============================================================================
# AutoMemory - Suggestions
# =============================================================================


class TestSuggestions:
    def setup_method(self):
        self.tmp = Path("workspace_test_auto_mem_suggest")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.memory = AutoMemory(workspace_path=self.tmp)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_suggest_mode_no_data(self):
        assert self.memory.suggest_mode("unknown_type") is None

    def test_suggest_mode_with_data(self):
        for _ in range(3):
            self.memory.record_success(
                task_type="review",
                task_description="review",
                swarm_mode="PING_PONG",
                lead_agent="claude",
                duration_seconds=10.0,
                score=0.9,
            )
        self.memory.record_success(
            task_type="review",
            task_description="review",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=10.0,
            score=0.5,
        )
        best = self.memory.suggest_mode("review")
        assert best == "PING_PONG"

    def test_suggest_lead_no_data(self):
        assert self.memory.suggest_lead("unknown") is None

    def test_suggest_lead_with_data(self):
        for _ in range(3):
            self.memory.record_success(
                task_type="coding",
                task_description="code",
                swarm_mode="SPECIALIST",
                lead_agent="claude",
                duration_seconds=10.0,
                score=0.95,
            )
        self.memory.record_success(
            task_type="coding",
            task_description="code",
            swarm_mode="SPECIALIST",
            lead_agent="gemini",
            duration_seconds=10.0,
            score=0.6,
        )
        best = self.memory.suggest_lead("coding")
        assert best == "claude"

    def test_suggest_mode_without_decay(self):
        self.memory.record_success(
            task_type="test",
            task_description="t",
            swarm_mode="RED_BLUE",
            lead_agent="claude",
            duration_seconds=10.0,
            score=0.9,
        )
        best = self.memory.suggest_mode("test", apply_decay=False)
        assert best == "RED_BLUE"


# =============================================================================
# AutoMemory - Avoidance
# =============================================================================


class TestAvoidance:
    def setup_method(self):
        self.tmp = Path("workspace_test_auto_mem_avoid")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.memory = AutoMemory(workspace_path=self.tmp)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_should_avoid_no_data(self):
        assert self.memory.should_avoid("unknown", "PARALLEL") is False

    def test_should_avoid_few_samples(self):
        self.memory.record_failure(
            task_type="test",
            task_description="t",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=10.0,
            reason="fail",
        )
        # Only 1 sample, threshold is 3
        assert self.memory.should_avoid("test", "PARALLEL") is False

    def test_should_avoid_high_failure(self):
        for _ in range(3):
            self.memory.record_failure(
                task_type="security",
                task_description="audit",
                swarm_mode="PARALLEL",
                lead_agent="gemini",
                duration_seconds=10.0,
                reason="fail",
            )
        self.memory.record_success(
            task_type="security",
            task_description="audit",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=10.0,
        )
        # 3 failures + 1 success = 75% failure rate > 50%
        assert self.memory.should_avoid("security", "PARALLEL") is True

    def test_should_not_avoid_low_failure(self):
        for _ in range(3):
            self.memory.record_success(
                task_type="coding",
                task_description="code",
                swarm_mode="PING_PONG",
                lead_agent="claude",
                duration_seconds=10.0,
            )
        self.memory.record_failure(
            task_type="coding",
            task_description="code",
            swarm_mode="PING_PONG",
            lead_agent="claude",
            duration_seconds=10.0,
            reason="minor",
        )
        # 1 failure + 3 success = 25% failure rate < 50%
        assert self.memory.should_avoid("coding", "PING_PONG") is False


# =============================================================================
# AutoMemory - Stats
# =============================================================================


class TestStats:
    def setup_method(self):
        self.tmp = Path("workspace_test_auto_mem_stats")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.memory = AutoMemory(workspace_path=self.tmp)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_stats(self):
        stats = self.memory.get_stats()
        assert stats["total_successes"] == 0
        assert stats["total_failures"] == 0
        assert stats["success_rate"] == 0

    def test_stats_with_data(self):
        self.memory.record_success(
            task_type="test",
            task_description="t",
            swarm_mode="PARALLEL",
            lead_agent="claude",
            duration_seconds=10.0,
        )
        self.memory.record_failure(
            task_type="test",
            task_description="t",
            swarm_mode="PARALLEL",
            lead_agent="gemini",
            duration_seconds=10.0,
            reason="err",
        )
        stats = self.memory.get_stats()
        assert stats["total_successes"] == 1
        assert stats["total_failures"] == 1
        assert stats["success_rate"] == 0.5
        assert "test" in stats["task_types_tracked"]


# =============================================================================
# AutoMemory - Recommendations
# =============================================================================


class TestRecommendation:
    def setup_method(self):
        self.tmp = Path("workspace_test_auto_mem_reco")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.memory = AutoMemory(workspace_path=self.tmp)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recommendation_empty(self):
        rec = self.memory.get_recommendation("unknown")
        assert rec["suggested_mode"] is None
        assert rec["suggested_lead"] is None
        assert rec["confidence"] == 0.0

    def test_recommendation_with_data(self):
        for _ in range(5):
            self.memory.record_success(
                task_type="coding",
                task_description="code",
                swarm_mode="SPECIALIST",
                lead_agent="claude",
                duration_seconds=10.0,
                score=0.9,
            )
        rec = self.memory.get_recommendation("coding")
        assert rec["suggested_mode"] == "SPECIALIST"
        assert rec["suggested_lead"] == "claude"
        assert rec["confidence"] == 0.5  # 5 samples / 10
        assert rec["based_on_samples"] == 5

    def test_recommendation_has_avoid_modes(self):
        for _ in range(4):
            self.memory.record_failure(
                task_type="security",
                task_description="audit",
                swarm_mode="PARALLEL",
                lead_agent="gemini",
                duration_seconds=10.0,
                reason="fail",
            )
        rec = self.memory.get_recommendation("security")
        assert "PARALLEL" in rec["modes_to_avoid"]


# =============================================================================
# AutoMemory - Time Decay
# =============================================================================


class TestTimeDecay:
    def setup_method(self):
        self.tmp = Path("workspace_test_auto_mem_decay")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.memory = AutoMemory(workspace_path=self.tmp)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recent_no_decay(self):
        from datetime import datetime

        now = datetime.now().isoformat()
        decayed = self.memory._apply_time_decay(1.0, now)
        assert decayed >= 0.99

    def test_old_decays(self):
        from datetime import datetime, timedelta

        old = (datetime.now() - timedelta(days=90)).isoformat()
        decayed = self.memory._apply_time_decay(1.0, old)
        assert decayed < 1.0

    def test_invalid_timestamp_no_decay(self):
        decayed = self.memory._apply_time_decay(0.8, "invalid")
        assert decayed == 0.8


# =============================================================================
# AutoMemory - Persistence Reload
# =============================================================================


class TestPersistence:
    def setup_method(self):
        self.tmp = Path("workspace_test_auto_mem_persist")
        self.tmp.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reload_from_files(self):
        # Write to files with first instance
        mem1 = AutoMemory(workspace_path=self.tmp)
        mem1.record_success(
            task_type="coding",
            task_description="code",
            swarm_mode="SPECIALIST",
            lead_agent="claude",
            duration_seconds=10.0,
            score=0.9,
        )

        # Create new instance — should reload from files
        mem2 = AutoMemory(workspace_path=self.tmp)
        assert len(mem2._success_cache["coding"]) == 1
        assert mem2.suggest_mode("coding") == "SPECIALIST"


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same(self):
        reset_auto_memory()
        m1 = get_auto_memory()
        m2 = get_auto_memory()
        assert m1 is m2

    def test_reset_creates_new(self):
        reset_auto_memory()
        m1 = get_auto_memory()
        reset_auto_memory()
        m2 = get_auto_memory()
        assert m1 is not m2
