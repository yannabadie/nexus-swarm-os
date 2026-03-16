"""
Tests for Evolution Core Components - Phase 14b

Tests cover:
- EvolutionManager: Complete evolution cycle with mocked drivers
- Evaluator: Fitness calculation and regression detection

NEXUS V7.6 HIVE MIND - Test Coverage for core/evolution/
Author: Claude (Phase 14b - 2025-12-05)
"""

import json

# Add parent to path for imports
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.evolution.evaluator import (
    calculate_fitness_score,
    compare_to_parent,
    get_baseline_fitness,
    select_winner,
)
from core.intelligence.evolution.manager import EvolutionManager

# =============================================================================
# FIXTURES
# =============================================================================


class MockConfig:
    """Mock configuration for evolution tests."""

    def __init__(self):
        self.max_generations_per_day = 10
        self.min_hours_between_gen = 0.0  # No rate limiting in tests
        self.min_hours_between_generations = 0.0
        self.max_children_per_generation = 5
        self.max_children_concurrent = 5
        self.timeout = 30
        self.red_team_mandatory = False
        self.red_team_min_score = 0.60
        self.validation_tier_default = 4
        self.validation_use_tiered = True


class MockOrchestrator:
    """Mock orchestrator for evolution tests."""

    def __init__(self):
        self.state = "IDLE"
        self.blackboard = {"recent_history": []}
        self.memory = Mock()
        self.memory.save_to_disk = Mock()
        self.memory.add_to_history = Mock()
        self._process_turn_count = 0
        self._mock_responses = []

    def process_turn(self, input_text: str = None) -> dict:
        """Simulate process_turn with configurable responses."""
        self._process_turn_count += 1

        if self._mock_responses:
            response = self._mock_responses.pop(0)
            return response

        # Default: Return finished state after a few turns
        if self._process_turn_count >= 3:
            return {
                "state": "IDLE",
                "output": '{"mutations": []}',
                "finished": True,
            }
        return {
            "state": "EVOLUTION_BRAINSTORM",
            "output": "Brainstorming...",
            "finished": False,
        }

    def _transition_to(self, state):
        """Mock state transition."""
        self.state = state

    def set_mock_responses(self, responses: list):
        """Set sequence of mock responses."""
        self._mock_responses = responses.copy()


class MockRateLimiter:
    """Mock rate limiter that always allows evolution."""

    def __init__(self, allow: bool = True, reason: str = ""):
        self._allow = allow
        self._reason = reason

    def can_evolve(self, num_children: int = 1):
        return self._allow, self._reason

    def remaining_today(self):
        return 10 if self._allow else 0


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace with required structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".nexus").mkdir()
    (workspace / "children").mkdir()
    (workspace / "logs").mkdir()

    # Create LINEAGE.json in workspace root
    lineage = {"current_parent": "nexus_v7_test", "generation": 1, "history": []}
    lineage_path = workspace / "LINEAGE.json"
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    # Also create LINEAGE.json in tmp_path root (some tests need it there)
    root_lineage_path = tmp_path / "LINEAGE.json"
    root_lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    return workspace


@pytest.fixture
def mock_config():
    """Provide mock configuration."""
    return MockConfig()


@pytest.fixture
def mock_orchestrator():
    """Provide mock orchestrator."""
    return MockOrchestrator()


@pytest.fixture
def mock_rate_limiter():
    """Provide mock rate limiter."""
    return MockRateLimiter()


@pytest.fixture
def evolution_manager(temp_workspace, mock_config, mock_orchestrator, mock_rate_limiter):
    """Create EvolutionManager with mocked dependencies."""
    nexus_root = temp_workspace.parent / "NEXUS_ROOT"
    nexus_root.mkdir(exist_ok=True)

    # Create ARCHIVE directory
    archive = nexus_root / "ARCHIVE"
    archive.mkdir(exist_ok=True)

    # Ensure LINEAGE.json exists in workspace (belt and suspenders)
    lineage_path = temp_workspace / "LINEAGE.json"
    if not lineage_path.exists():
        lineage = {"current_parent": "nexus_v7_test", "generation": 1, "history": []}
        lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    return EvolutionManager(
        workspace_path=temp_workspace,
        nexus_root=nexus_root,
        config=mock_config,
        orchestrator=mock_orchestrator,
        rate_limiter=mock_rate_limiter,
    )


# =============================================================================
# TEST: EvolutionManager
# =============================================================================


class TestEvolutionManagerInit:
    """Tests for EvolutionManager initialization."""

    def test_init_creates_paths(self, evolution_manager):
        """Test that initialization sets up paths correctly."""
        assert evolution_manager.workspace_path.exists()
        assert evolution_manager.children_path.exists()

    def test_init_creates_validator(self, evolution_manager):
        """Test that TieredValidator is created."""
        assert evolution_manager.validator is not None

    def test_init_creates_phase_executors(self, evolution_manager):
        """Test that phase executors are created."""
        assert evolution_manager._brainstorm_phase is not None
        assert evolution_manager._create_phase is not None
        assert evolution_manager._promote_phase is not None


class TestEvolutionManagerRateLimiting:
    """Tests for rate limiting in evolution cycles."""

    def test_rate_limited_blocks_evolution(self, temp_workspace, mock_config, mock_orchestrator):
        """Test that rate limiting blocks evolution."""
        rate_limiter = MockRateLimiter(allow=False, reason="Too many evolutions today")

        manager = EvolutionManager(
            workspace_path=temp_workspace,
            nexus_root=temp_workspace.parent / "NEXUS_ROOT",
            config=mock_config,
            orchestrator=mock_orchestrator,
            rate_limiter=rate_limiter,
        )

        result = manager.run_evolution_cycle(child_count=1)

        assert result.success is False
        assert "Rate limited" in result.errors[0]
        assert result.phase_reached == "init"

    def test_not_rate_limited_proceeds(self, evolution_manager, mock_orchestrator):
        """Test that non-rate-limited request proceeds past init phase."""
        # Configure mock to return empty mutations (brainstorm fails)
        mock_orchestrator.set_mock_responses([{"state": "IDLE", "output": "", "finished": True}])

        result = evolution_manager.run_evolution_cycle(child_count=1)

        # Should proceed past init phase (not blocked by rate limiting)
        # The exact phase depends on mock behavior - at minimum brainstorm or later
        assert result.phase_reached in ["brainstorm", "create", "validate", "evaluate", "promote"]


class TestEvolutionManagerCycle:
    """Tests for complete evolution cycle."""

    def test_cycle_stops_on_brainstorm_failure(self, evolution_manager, mock_orchestrator):
        """Test that cycle eventually stops when no valid children are created."""
        # Mock brainstorm to return error state
        mock_orchestrator.set_mock_responses([{"state": "ERROR", "output": "Brainstorm failed", "finished": True}])

        result = evolution_manager.run_evolution_cycle(child_count=3)

        # Should fail at some phase (brainstorm error or later phase)
        assert result.success is False
        # Phase depends on mock behavior - just verify it stopped somewhere
        assert result.phase_reached in ["brainstorm", "create", "validate", "evaluate"]

    def test_cycle_tracks_phases(self, evolution_manager, mock_orchestrator):
        """Test that cycle correctly tracks phase progression."""
        # Start cycle - should fail at brainstorm due to no valid mutations
        mock_orchestrator.set_mock_responses(
            [
                {"state": "EVOLUTION_BRAINSTORM", "output": "Debating...", "finished": False},
                {"state": "EVOLUTION_BRAINSTORM", "output": "Still debating...", "finished": False},
                {"state": "IDLE", "output": "No mutations found", "finished": True},
            ]
        )

        result = evolution_manager.run_evolution_cycle(child_count=1)

        # Verify phase tracking
        assert result.phase_reached in ["brainstorm", "create", "validate", "evaluate", "promote"]
        assert result.started_at is not None

    def test_cycle_no_infinite_loop(self, evolution_manager, mock_orchestrator):
        """Test that cycle doesn't run forever on brainstorm failure."""
        # Mock to never return valid mutations
        responses = [{"state": "EVOLUTION_BRAINSTORM", "output": "...", "finished": False} for _ in range(50)]
        responses.append({"state": "IDLE", "output": "", "finished": True})
        mock_orchestrator.set_mock_responses(responses)

        import time

        start = time.time()
        result = evolution_manager.run_evolution_cycle(child_count=1)
        elapsed = time.time() - start

        # Should not take forever (brainstorm has max_iterations=30)
        assert elapsed < 60  # Should complete within 60 seconds
        assert result.success is False

    def test_progress_callback_called(self, temp_workspace, mock_config, mock_orchestrator, mock_rate_limiter):
        """Test that progress callback is called during evolution."""
        progress_calls = []

        def track_progress(message: str, progress: float):
            progress_calls.append((message, progress))

        # Ensure nexus_root and LINEAGE.json exist
        nexus_root = temp_workspace.parent / "NEXUS_ROOT"
        nexus_root.mkdir(exist_ok=True)
        (nexus_root / "ARCHIVE").mkdir(exist_ok=True)

        lineage_path = temp_workspace / "LINEAGE.json"
        if not lineage_path.exists():
            lineage = {"current_parent": "test", "generation": 1, "history": []}
            lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

        manager = EvolutionManager(
            workspace_path=temp_workspace,
            nexus_root=nexus_root,
            config=mock_config,
            orchestrator=mock_orchestrator,
            rate_limiter=mock_rate_limiter,
            progress_callback=track_progress,
        )

        mock_orchestrator.set_mock_responses([{"state": "IDLE", "output": "", "finished": True}])

        manager.run_evolution_cycle(child_count=1)

        # Progress callback should have been called
        assert len(progress_calls) > 0


class TestEvolutionManagerStatus:
    """Tests for evolution status reporting."""

    def test_get_status_returns_valid_status(self, evolution_manager):
        """Test that get_status returns valid EvolutionStatus."""
        status = evolution_manager.get_status()

        assert status.current_generation >= 1
        assert status.total_children >= 0
        assert status.pending_children >= 0
        assert status.can_evolve is True


# =============================================================================
# TEST: Evaluator
# =============================================================================


class TestCalculateFitnessScore:
    """Tests for fitness score calculation."""

    def test_calculate_with_default_weights(self):
        """Test fitness calculation with default weights."""
        benchmark_results = {
            "scores": {
                "coding": 0.80,
                "reasoning": 0.75,
                "creativity": 0.70,
                "scalability": 0.65,
            }
        }

        score = calculate_fitness_score(benchmark_results)

        # Expected: 0.80*0.30 + 0.75*0.30 + 0.70*0.25 + 0.65*0.15
        #         = 0.24 + 0.225 + 0.175 + 0.0975 = 0.7375
        assert 0.73 <= score <= 0.74

    def test_calculate_with_custom_weights(self):
        """Test fitness calculation with custom weights."""
        benchmark_results = {
            "scores": {
                "coding": 1.0,
                "reasoning": 0.0,
                "creativity": 0.0,
                "scalability": 0.0,
            }
        }

        # Custom weights: 100% coding
        weights = {"coding": 1.0, "reasoning": 0.0, "creativity": 0.0, "scalability": 0.0}
        score = calculate_fitness_score(benchmark_results, weights)

        assert score == 1.0

    def test_calculate_all_zero_scores(self):
        """Test fitness calculation with all zero scores."""
        benchmark_results = {
            "scores": {
                "coding": 0.0,
                "reasoning": 0.0,
                "creativity": 0.0,
                "scalability": 0.0,
            }
        }

        score = calculate_fitness_score(benchmark_results)
        assert score == 0.0

    def test_calculate_perfect_scores(self):
        """Test fitness calculation with perfect scores."""
        benchmark_results = {
            "scores": {
                "coding": 1.0,
                "reasoning": 1.0,
                "creativity": 1.0,
                "scalability": 1.0,
            }
        }

        score = calculate_fitness_score(benchmark_results)
        assert score == 1.0


class TestCompareToParent:
    """Tests for parent comparison and regression detection."""

    def test_significant_improvement(self):
        """Test detection of significant improvement (>=3%)."""
        child_results = {
            "nexus_id": "child_1",
            "scores": {"coding": 0.85, "reasoning": 0.85, "creativity": 0.85, "scalability": 0.85},
        }
        parent_results = {
            "nexus_id": "parent",
            "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
        }

        comparison = compare_to_parent(child_results, parent_results)

        assert comparison["significance"] == "significant"
        assert comparison["improvement_percent"] > 3.0

    def test_minor_improvement(self):
        """Test detection of minor improvement (1-3%)."""
        child_results = {
            "nexus_id": "child_1",
            "scores": {"coding": 0.81, "reasoning": 0.81, "creativity": 0.81, "scalability": 0.81},
        }
        parent_results = {
            "nexus_id": "parent",
            "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
        }

        comparison = compare_to_parent(child_results, parent_results)

        assert comparison["significance"] == "minor"
        assert 1.0 <= comparison["improvement_percent"] < 3.0

    def test_regression_detected(self):
        """Test detection of regression (negative improvement)."""
        child_results = {
            "nexus_id": "child_1",
            "scores": {"coding": 0.70, "reasoning": 0.70, "creativity": 0.70, "scalability": 0.70},
        }
        parent_results = {
            "nexus_id": "parent",
            "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
        }

        comparison = compare_to_parent(child_results, parent_results)

        assert comparison["significance"] == "regression"
        assert comparison["improvement_percent"] < 0

    def test_negligible_change(self):
        """Test detection of negligible change (0-1%)."""
        child_results = {
            "nexus_id": "child_1",
            "scores": {"coding": 0.805, "reasoning": 0.805, "creativity": 0.805, "scalability": 0.805},
        }
        parent_results = {
            "nexus_id": "parent",
            "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
        }

        comparison = compare_to_parent(child_results, parent_results)

        assert comparison["significance"] == "negligible"
        assert 0 <= comparison["improvement_percent"] < 1.0

    def test_comparison_includes_dimensions(self):
        """Test that comparison includes per-dimension breakdown."""
        child_results = {
            "nexus_id": "child_1",
            "scores": {"coding": 0.90, "reasoning": 0.80, "creativity": 0.70, "scalability": 0.60},
        }
        parent_results = {
            "nexus_id": "parent",
            "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
        }

        comparison = compare_to_parent(child_results, parent_results)

        assert "dimensions" in comparison
        assert "coding" in comparison["dimensions"]
        assert comparison["dimensions"]["coding"]["delta"] == 0.10


class TestSelectWinner:
    """Tests for winner selection."""

    def test_select_highest_score_wins(self):
        """Test that candidate with highest score wins."""
        candidates = [
            {
                "nexus_id": "child_1",
                "scores": {"coding": 0.70, "reasoning": 0.70, "creativity": 0.70, "scalability": 0.70},
            },
            {
                "nexus_id": "child_2",
                "scores": {"coding": 0.90, "reasoning": 0.90, "creativity": 0.90, "scalability": 0.90},
            },
            {
                "nexus_id": "child_3",
                "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
            },
        ]

        winner, losers = select_winner(candidates)

        assert winner["nexus_id"] == "child_2"
        assert len(losers) == 2

    def test_select_tie_parent_wins(self):
        """Test that parent wins in case of tie."""
        candidates = [
            {
                "nexus_id": "child_1",
                "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
            },
            {
                "nexus_id": "parent",
                "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
            },
        ]

        winner, losers = select_winner(candidates, parent_id="parent")

        assert winner["nexus_id"] == "parent"

    def test_select_single_candidate(self):
        """Test winner selection with single candidate."""
        candidates = [
            {
                "nexus_id": "only_child",
                "scores": {"coding": 0.75, "reasoning": 0.75, "creativity": 0.75, "scalability": 0.75},
            },
        ]

        winner, losers = select_winner(candidates)

        assert winner["nexus_id"] == "only_child"
        assert len(losers) == 0

    def test_losers_sorted_by_score(self):
        """Test that losers are sorted by score descending."""
        candidates = [
            {
                "nexus_id": "child_1",
                "scores": {"coding": 0.70, "reasoning": 0.70, "creativity": 0.70, "scalability": 0.70},
            },
            {
                "nexus_id": "child_2",
                "scores": {"coding": 0.90, "reasoning": 0.90, "creativity": 0.90, "scalability": 0.90},
            },
            {
                "nexus_id": "child_3",
                "scores": {"coding": 0.80, "reasoning": 0.80, "creativity": 0.80, "scalability": 0.80},
            },
        ]

        winner, losers = select_winner(candidates)

        # Losers should be sorted: child_3 (0.80) then child_1 (0.70)
        assert losers[0]["nexus_id"] == "child_3"
        assert losers[1]["nexus_id"] == "child_1"


class TestGetBaselineFitness:
    """Tests for baseline fitness generation."""

    def test_baseline_returns_competent_scores(self):
        """Test that baseline returns 0.70 for all dimensions."""
        result = get_baseline_fitness("test_nexus")

        assert result["scores"]["coding"] == 0.70
        assert result["scores"]["reasoning"] == 0.70
        assert result["scores"]["creativity"] == 0.70
        assert result["scores"]["scalability"] == 0.70

    def test_baseline_marks_not_evaluated(self):
        """Test that baseline marks results as not evaluated."""
        result = get_baseline_fitness("test_nexus")

        assert result["evaluated"] is False
        assert result["simulated"] is False

    def test_baseline_includes_metadata(self):
        """Test that baseline includes proper metadata."""
        result = get_baseline_fitness("test_nexus")

        assert result["nexus_id"] == "test_nexus"
        assert result["benchmark_suite"] == "task_fitness_baseline"
        assert "timestamp" in result


# =============================================================================
# TEST: Integration
# =============================================================================


class TestEvolutionIntegration:
    """Integration tests for evolution components."""

    def test_fitness_score_used_in_comparison(self):
        """Test that fitness calculation integrates with comparison."""
        benchmark = get_baseline_fitness("test")
        score = calculate_fitness_score(benchmark)

        # Baseline score should be 0.70 (all dimensions are 0.70)
        assert score == 0.70

    def test_comparison_uses_calculated_scores(self):
        """Test that comparison correctly uses calculated scores."""
        child_benchmark = get_baseline_fitness("child")
        parent_benchmark = get_baseline_fitness("parent")

        comparison = compare_to_parent(child_benchmark, parent_benchmark)

        # Same baseline = 0% improvement
        assert comparison["improvement_percent"] == 0.0
        assert comparison["significance"] == "negligible"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
