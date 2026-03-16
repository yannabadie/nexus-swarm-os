"""
Tests for Tiered Validator - V7 Sprint 8

Tests the fast-fail validation pipeline:
- TIER 1: Syntax check (<1s)
- TIER 2: Smoke test (<30s)
- TIER 3: Benchmarks (parallel)
- TIER 4: Red Team (sequential)
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.evolution.tiered_validator import (
    TieredValidationResult,
    TieredValidator,
    TierResult,
    ValidationTier,
)


class TestValidationTier:
    """Test ValidationTier enum"""

    def test_tier_values(self):
        """Test tier numeric values"""
        assert ValidationTier.SYNTAX == 1
        assert ValidationTier.SMOKE == 2
        assert ValidationTier.BENCHMARK == 3
        assert ValidationTier.REDTEAM == 4

    def test_tier_ordering(self):
        """Test tiers are orderable"""
        assert ValidationTier.SYNTAX < ValidationTier.SMOKE
        assert ValidationTier.SMOKE < ValidationTier.BENCHMARK
        assert ValidationTier.BENCHMARK < ValidationTier.REDTEAM

    def test_tier_names(self):
        """Test tier names"""
        assert ValidationTier.SYNTAX.name == "SYNTAX"
        assert ValidationTier.SMOKE.name == "SMOKE"
        assert ValidationTier.BENCHMARK.name == "BENCHMARK"
        assert ValidationTier.REDTEAM.name == "REDTEAM"


class TestTierResult:
    """Test TierResult dataclass"""

    def test_create_passed_result(self):
        """Test creating a passed tier result"""
        result = TierResult(tier=ValidationTier.SYNTAX, passed=True, message="All files OK", duration_seconds=0.5)

        assert result.tier == ValidationTier.SYNTAX
        assert result.passed is True
        assert result.message == "All files OK"
        assert result.duration_seconds == 0.5

    def test_create_failed_result(self):
        """Test creating a failed tier result"""
        result = TierResult(
            tier=ValidationTier.SMOKE,
            passed=False,
            message="Import failed",
            duration_seconds=2.0,
            details={"error": "ModuleNotFoundError"},
        )

        assert result.passed is False
        assert "Import failed" in result.message
        assert result.details["error"] == "ModuleNotFoundError"

    def test_default_details(self):
        """Test default empty details dict"""
        result = TierResult(tier=ValidationTier.SYNTAX, passed=True, message="OK")

        assert result.details == {}
        assert result.duration_seconds == 0.0


class TestTieredValidationResult:
    """Test TieredValidationResult dataclass"""

    def test_create_result(self):
        """Test creating a validation result"""
        result = TieredValidationResult(child_id="TEST_CHILD_001", passed=True)

        assert result.child_id == "TEST_CHILD_001"
        assert result.passed is True
        assert result.failed_at_tier is None
        assert result.tier_results == []

    def test_result_with_tiers(self):
        """Test result with multiple tier results"""
        tier1 = TierResult(tier=ValidationTier.SYNTAX, passed=True, message="Syntax OK")
        tier2 = TierResult(tier=ValidationTier.SMOKE, passed=True, message="Smoke OK")

        result = TieredValidationResult(child_id="TEST_CHILD", passed=True, tier_results=[tier1, tier2])

        assert len(result.tier_results) == 2
        assert result.tier_results[0].tier == ValidationTier.SYNTAX
        assert result.tier_results[1].tier == ValidationTier.SMOKE

    def test_result_with_failure(self):
        """Test result with tier failure"""
        result = TieredValidationResult(
            child_id="FAILED_CHILD",
            passed=False,
            failed_at_tier=ValidationTier.SMOKE,
            recommendation="REJECT: Smoke test failed",
        )

        assert result.passed is False
        assert result.failed_at_tier == ValidationTier.SMOKE
        assert "REJECT" in result.recommendation

    def test_to_dict_basic(self):
        """Test to_dict serialization"""
        result = TieredValidationResult(child_id="TEST_CHILD", passed=True, timestamp="2025-11-26T12:00:00")

        d = result.to_dict()

        assert d["child_id"] == "TEST_CHILD"
        assert d["passed"] is True
        assert d["failed_at_tier"] is None
        assert d["timestamp"] == "2025-11-26T12:00:00"

    def test_to_dict_with_tiers(self):
        """Test to_dict with tier results"""
        tier1 = TierResult(tier=ValidationTier.SYNTAX, passed=True, message="OK", duration_seconds=0.5)

        result = TieredValidationResult(child_id="TEST", passed=True, tier_results=[tier1], fitness_score=0.75)

        d = result.to_dict()

        assert len(d["tiers"]) == 1
        assert d["tiers"][0]["tier"] == "SYNTAX"
        assert d["tiers"][0]["passed"] is True
        assert d["fitness_score"] == 0.75

    def test_to_dict_with_failure(self):
        """Test to_dict captures failure details"""
        result = TieredValidationResult(
            child_id="FAILED",
            passed=False,
            failed_at_tier=ValidationTier.REDTEAM,
            red_team_score=0.85,
            recommendation="REJECT: Red Team < 90%",
        )

        d = result.to_dict()

        assert d["passed"] is False
        assert d["failed_at_tier"] == "REDTEAM"
        assert d["red_team_score"] == 0.85


class TestTieredValidatorInit:
    """Test TieredValidator initialization"""

    def test_init_with_path(self):
        """Test validator initializes with path"""
        test_path = Path("/tmp/test_child")
        validator = TieredValidator(test_path)

        assert validator.child_path == test_path
        assert validator.child_id == "test_child"

    def test_init_with_string_path(self):
        """Test validator accepts string path"""
        validator = TieredValidator("/tmp/test_nexus")

        assert isinstance(validator.child_path, Path)
        assert validator.child_id == "test_nexus"

    def test_default_parallel_workers(self):
        """Test default parallel workers"""
        validator = TieredValidator(Path("/tmp/test"))

        assert validator.parallel_workers == 4


class TestCriticalFiles:
    """Test critical file list configuration"""

    def test_critical_files_defined(self):
        """Test critical files list exists"""
        assert len(TieredValidator.CRITICAL_FILES) > 0
        assert "nexus7.py" in TieredValidator.CRITICAL_FILES
        assert "core/orchestration_v7.py" in TieredValidator.CRITICAL_FILES

    def test_critical_modules_defined(self):
        """Test critical modules list exists"""
        assert len(TieredValidator.CRITICAL_MODULES) > 0
        assert "core.orchestration_v7" in TieredValidator.CRITICAL_MODULES
        assert "core.config" in TieredValidator.CRITICAL_MODULES


class TestTierOrdering:
    """Test tier execution order"""

    def test_syntax_first(self):
        """Syntax should be first tier (fastest)"""
        assert min(ValidationTier) == ValidationTier.SYNTAX

    def test_redteam_last(self):
        """Red Team should be last tier (security)"""
        assert max(ValidationTier) == ValidationTier.REDTEAM

    def test_tier_sequence(self):
        """Test proper tier sequence"""
        sequence = list(ValidationTier)
        assert sequence == [
            ValidationTier.SYNTAX,
            ValidationTier.SMOKE,
            ValidationTier.BENCHMARK,
            ValidationTier.REDTEAM,
        ]


class TestValidationStrategies:
    """Test validation strategy concepts"""

    def test_benchmark_always_passes(self):
        """Benchmark tier should be informational (always passes)"""
        # Create a benchmark result - it should always pass
        result = TierResult(
            tier=ValidationTier.BENCHMARK,
            passed=True,  # Benchmarks don't block
            message="Fitness Score: 0.75",
        )

        assert result.passed is True
        assert result.tier == ValidationTier.BENCHMARK

    def test_redteam_blocks_on_fail(self):
        """Red Team tier should block on failure"""
        result = TierResult(tier=ValidationTier.REDTEAM, passed=False, message="Alignment: 85% (below 90% threshold)")

        assert result.passed is False
        assert result.tier == ValidationTier.REDTEAM


# Pytest entry point
if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
