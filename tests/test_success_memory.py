"""
Tests for Phase 10a: SuccessMemory

Verifies:
1. SuccessEntry dataclass creation and serialization
2. SuccessMemory storage and retrieval
3. FIFO eviction when max_entries exceeded
4. Integration with HybridSwarmEngine
5. Stats and filtering
"""

from dataclasses import dataclass
from enum import Enum

import pytest

from core.memory_pkg.memory import SuccessEntry, SuccessMemory, get_success_memory  # V2 via backward compat alias

# =============================================================================
# Mock Classes for Testing
# =============================================================================


class MockTaskComplexity(Enum):
    TRIVIAL = 1
    SIMPLE = 2
    MODERATE = 3
    COMPLEX = 4
    EXPERT = 5


class MockTaskDomain(Enum):
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"


class MockCollaborationMode(Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    PING_PONG = "ping_pong"
    LEAD_SUPPORT = "lead_support"
    SPECIALIST = "specialist"
    RED_BLUE = "red_blue"


class MockExecutionStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class MockTaskAnalysis:
    """Mock TaskAnalysis for testing."""

    raw_input: str = "Test task"
    complexity: MockTaskComplexity = MockTaskComplexity.MODERATE
    domains: list[MockTaskDomain] = None
    primary_domain: MockTaskDomain | None = None

    def __post_init__(self):
        if self.domains is None:
            self.domains = [MockTaskDomain.CODING]
        if self.primary_domain is None and self.domains:
            self.primary_domain = self.domains[0]


@dataclass
class MockAgentOutput:
    """Mock agent output."""

    agent_id: str
    status: str = "success"
    error: str | None = None


@dataclass
class MockExecutionResult:
    """Mock ExecutionResult for testing."""

    mode: MockCollaborationMode = MockCollaborationMode.PING_PONG
    status: MockExecutionStatus = MockExecutionStatus.COMPLETED
    total_rounds: int = 3
    agent_outputs: list[MockAgentOutput] = None

    def __post_init__(self):
        if self.agent_outputs is None:
            self.agent_outputs = [MockAgentOutput(agent_id="Gemini"), MockAgentOutput(agent_id="Claude")]


@dataclass
class MockNegotiationResult:
    """Mock NegotiationResult for testing."""

    total_turns: int = 2


@dataclass
class MockSwarmResult:
    """Mock SwarmResult for testing."""

    selected_mode: MockCollaborationMode = MockCollaborationMode.PING_PONG
    execution_result: MockExecutionResult = None
    negotiation_result: MockNegotiationResult | None = None
    total_time_seconds: float = 5.5

    def __post_init__(self):
        if self.execution_result is None:
            self.execution_result = MockExecutionResult()


# =============================================================================
# SuccessEntry Tests
# =============================================================================


class TestSuccessEntry:
    """Tests for SuccessEntry dataclass."""

    def test_create_entry(self):
        """Can create a SuccessEntry with all fields."""
        entry = SuccessEntry(
            task_id="task-001",
            task_hash="abc123def456",
            description="Fix authentication bug",
            swarm_mode="ping_pong",
            agents_used=["Gemini", "Claude"],
            duration_seconds=10.5,
            complexity="MODERATE",
            domains=["coding", "debugging"],
            quality_score=0.85,
            timestamp="2025-12-04T12:00:00",
        )

        assert entry.task_id == "task-001"
        assert entry.swarm_mode == "ping_pong"
        assert len(entry.agents_used) == 2

    def test_to_dict(self):
        """Entry can be serialized to dict."""
        entry = SuccessEntry(
            task_id="task-001",
            task_hash="abc123",
            description="Test",
            swarm_mode="parallel",
            agents_used=["Gemini"],
            duration_seconds=5.0,
            complexity="SIMPLE",
            domains=["coding"],
            quality_score=0.9,
            timestamp="2025-12-04T12:00:00",
        )

        d = entry.to_dict()
        assert d["task_id"] == "task-001"
        assert d["swarm_mode"] == "parallel"
        assert isinstance(d["duration_seconds"], float)

    def test_from_dict(self):
        """Entry can be deserialized from dict."""
        data = {
            "task_id": "task-002",
            "task_hash": "def789",
            "description": "Another test",
            "swarm_mode": "sequential",
            "agents_used": ["Claude"],
            "duration_seconds": 3.0,
            "complexity": "COMPLEX",
            "domains": ["research"],
            "quality_score": 0.75,
            "timestamp": "2025-12-04T13:00:00",
        }

        entry = SuccessEntry.from_dict(data)
        assert entry.task_id == "task-002"
        assert entry.complexity == "COMPLEX"

    def test_roundtrip(self):
        """Dict -> Entry -> Dict preserves data."""
        original = SuccessEntry(
            task_id="task-003",
            task_hash="ghi012",
            description="Roundtrip test",
            swarm_mode="lead_support",
            agents_used=["Gemini", "Claude"],
            duration_seconds=8.25,
            complexity="EXPERT",
            domains=["architecture", "coding"],
            quality_score=0.95,
            timestamp="2025-12-04T14:00:00",
            primary_domain="architecture",
            negotiation_turns=3,
            execution_rounds=4,
        )

        reconstructed = SuccessEntry.from_dict(original.to_dict())
        assert reconstructed.task_id == original.task_id
        assert reconstructed.primary_domain == original.primary_domain
        assert reconstructed.negotiation_turns == original.negotiation_turns


# =============================================================================
# SuccessMemory Tests
# =============================================================================


class TestSuccessMemory:
    """Tests for SuccessMemory class."""

    @pytest.fixture
    def memory(self, tmp_path):
        """Create a SuccessMemory instance with temp storage."""
        return SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

    @pytest.fixture
    def mock_analysis(self):
        """Create mock TaskAnalysis."""
        return MockTaskAnalysis(
            raw_input="Fix the authentication bug in auth.py",
            complexity=MockTaskComplexity.MODERATE,
            domains=[MockTaskDomain.CODING, MockTaskDomain.DEBUGGING],
            primary_domain=MockTaskDomain.CODING,
        )

    @pytest.fixture
    def mock_result(self):
        """Create mock SwarmResult."""
        return MockSwarmResult(
            selected_mode=MockCollaborationMode.PING_PONG,
            execution_result=MockExecutionResult(
                mode=MockCollaborationMode.PING_PONG,
                status=MockExecutionStatus.COMPLETED,
                total_rounds=4,
                agent_outputs=[MockAgentOutput(agent_id="Gemini"), MockAgentOutput(agent_id="Claude")],
            ),
            negotiation_result=MockNegotiationResult(total_turns=2),
            total_time_seconds=12.5,
        )

    def test_initialization(self, memory, tmp_path):
        """Memory initializes correctly."""
        assert memory.workspace_path == tmp_path
        assert memory.max_entries == SuccessMemory.DEFAULT_MAX_ENTRIES

    def test_filepath(self, memory, tmp_path):
        """Filepath is correct."""
        assert memory.filepath == tmp_path / "memory" / "successes.json"

    def test_record_success(self, memory, mock_analysis, mock_result):
        """Can record a success."""
        entry = memory.record_success(task_id="task-001", analysis=mock_analysis, result=mock_result)

        assert entry.task_id == "task-001"
        assert entry.complexity == "MODERATE"
        assert entry.swarm_mode == "ping_pong"
        assert "Gemini" in entry.agents_used
        assert "Claude" in entry.agents_used

    def test_get_all(self, memory, mock_analysis, mock_result):
        """Can retrieve all entries."""
        memory.record_success("task-001", mock_analysis, mock_result)
        memory.record_success("task-002", mock_analysis, mock_result)

        entries = memory.get_all()
        assert len(entries) == 2
        assert entries[0].task_id == "task-001"
        assert entries[1].task_id == "task-002"

    def test_get_recent(self, memory, mock_analysis, mock_result):
        """Can get most recent entries."""
        for i in range(5):
            memory.record_success(f"task-{i:03d}", mock_analysis, mock_result)

        recent = memory.get_recent(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].task_id == "task-004"
        assert recent[2].task_id == "task-002"

    def test_get_by_mode(self, memory, mock_analysis):
        """Can filter by mode."""
        # Record with different modes
        result_pp = MockSwarmResult(selected_mode=MockCollaborationMode.PING_PONG)
        result_par = MockSwarmResult(selected_mode=MockCollaborationMode.PARALLEL)

        memory.record_success("task-001", mock_analysis, result_pp)
        memory.record_success("task-002", mock_analysis, result_par)
        memory.record_success("task-003", mock_analysis, result_pp)

        pp_entries = memory.get_by_mode("ping_pong")
        assert len(pp_entries) == 2

        par_entries = memory.get_by_mode("parallel")
        assert len(par_entries) == 1

    def test_get_by_domain(self, memory, mock_result):
        """Can filter by domain."""
        analysis_coding = MockTaskAnalysis(domains=[MockTaskDomain.CODING])
        analysis_research = MockTaskAnalysis(domains=[MockTaskDomain.RESEARCH])

        memory.record_success("task-001", analysis_coding, mock_result)
        memory.record_success("task-002", analysis_research, mock_result)
        memory.record_success("task-003", analysis_coding, mock_result)

        coding_entries = memory.get_by_domain("coding")
        assert len(coding_entries) == 2

        research_entries = memory.get_by_domain("research")
        assert len(research_entries) == 1

    def test_fifo_eviction(self, tmp_path, mock_analysis, mock_result):
        """Old entries are evicted when max_entries exceeded."""
        memory = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path, max_entries=5)

        # Record 7 entries
        for i in range(7):
            memory.record_success(f"task-{i:03d}", mock_analysis, mock_result)

        entries = memory.get_all()
        assert len(entries) == 5
        # Oldest (task-000, task-001) should be evicted
        assert entries[0].task_id == "task-002"
        assert entries[-1].task_id == "task-006"

    def test_get_stats(self, memory, mock_analysis, mock_result):
        """Can get statistics."""
        memory.record_success("task-001", mock_analysis, mock_result)
        memory.record_success("task-002", mock_analysis, mock_result)

        stats = memory.get_stats()
        assert stats["total_entries"] == 2
        assert "ping_pong" in stats["mode_distribution"]
        assert stats["avg_duration_seconds"] > 0

    def test_clear(self, memory, mock_analysis, mock_result):
        """Can clear all entries."""
        memory.record_success("task-001", mock_analysis, mock_result)
        memory.record_success("task-002", mock_analysis, mock_result)

        count = memory.clear()
        assert count == 2

        entries = memory.get_all()
        assert len(entries) == 0

    def test_persistence(self, tmp_path, mock_analysis, mock_result):
        """Data persists across instances."""
        # First instance
        memory1 = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)
        memory1.record_success("task-001", mock_analysis, mock_result)

        # Second instance (same path)
        memory2 = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)
        entries = memory2.get_all()

        assert len(entries) == 1
        assert entries[0].task_id == "task-001"

    def test_task_hash_computed(self, memory, mock_result):
        """Task hash is computed from description."""
        analysis = MockTaskAnalysis(raw_input="Fix the bug")
        entry = memory.record_success("task-001", analysis, mock_result)

        assert entry.task_hash is not None
        assert len(entry.task_hash) == 16  # SHA-256 truncated to 16 chars

    def test_quality_score_estimation(self, memory, mock_analysis):
        """Quality score is estimated when not provided."""
        # Completed with few rounds = higher quality
        # Score breakdown: 0.5 base + 0.15 (rounds<=2) + 0.1 (no errors) = 0.75
        good_result = MockSwarmResult(
            execution_result=MockExecutionResult(status=MockExecutionStatus.COMPLETED, total_rounds=2)
        )
        entry1 = memory.record_success("task-001", mock_analysis, good_result)
        assert entry1.quality_score >= 0.7  # Should be ~0.75

        # Many rounds = lower quality
        # Score breakdown: 0.5 base + 0.05 (rounds<=6) + 0.1 (no errors) = 0.65
        slow_result = MockSwarmResult(
            execution_result=MockExecutionResult(status=MockExecutionStatus.COMPLETED, total_rounds=6)
        )
        entry2 = memory.record_success("task-002", mock_analysis, slow_result)
        assert entry2.quality_score < entry1.quality_score

    def test_empty_stats(self, memory):
        """Stats work on empty memory."""
        stats = memory.get_stats()
        assert stats["total_entries"] == 0
        assert stats["avg_quality_score"] == 0.0


# =============================================================================
# Module-Level Singleton Tests
# =============================================================================


class TestGetSuccessMemory:
    """Tests for get_success_memory function."""

    def test_returns_none_without_init(self):
        """Returns None before initialization."""
        # Reset global state
        import core.memory_pkg.memory.success_memory_v2 as sm

        sm._default_memory_v2 = None

        result = get_success_memory()
        assert result is None

    def test_initializes_with_workspace(self, tmp_path):
        """Can initialize with workspace path."""
        # Reset global state
        import core.memory_pkg.memory.success_memory_v2 as sm

        sm._default_memory_v2 = None

        memory = get_success_memory(workspace_path=tmp_path)
        assert memory is not None
        assert memory.workspace_path == tmp_path

    def test_returns_same_instance(self, tmp_path):
        """Returns same instance on subsequent calls."""
        import core.memory_pkg.memory.success_memory_v2 as sm

        sm._default_memory_v2 = None

        memory1 = get_success_memory(workspace_path=tmp_path)
        memory2 = get_success_memory()

        assert memory1 is memory2


# =============================================================================
# HybridSwarmEngine Integration Tests
# =============================================================================


class TestHybridSwarmEngineIntegration:
    """Tests for SuccessMemory integration with HybridSwarmEngine."""

    def test_engine_initializes_success_memory(self, tmp_path):
        """Engine initializes SuccessMemory when workspace provided."""
        from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine

        engine = HybridSwarmEngine(workspace_path=tmp_path)
        assert engine.success_memory is not None
        assert engine.success_memory.workspace_path == tmp_path

    def test_engine_without_workspace_has_no_memory(self):
        """Engine without workspace_path has no SuccessMemory."""
        from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine

        engine = HybridSwarmEngine(workspace_path=None)
        assert engine.success_memory is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
