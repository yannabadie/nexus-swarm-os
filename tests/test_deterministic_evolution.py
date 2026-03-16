"""
Tests for deterministic evolution fitness function (V12.4).

Validates:
- Tier 3 deterministic pipeline replaces heuristic baselines
- SHA256 content hashing in lineage promotion
- Fitness scoring based on actual test/lint results
"""

import hashlib
from unittest.mock import MagicMock

import pytest

from core.intelligence.evolution.tiered_validator import TieredValidator, TierResult, ValidationTier


@pytest.fixture
def mock_child_path(tmp_path):
    """Create a mock child codebase for validation."""
    # Create some Python files
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "utils.py").write_text("def add(a, b):\n    return a + b\n")

    # Create tests directory
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_utils.py").write_text("def test_add():\n    from utils import add\n    assert add(1, 2) == 3\n")

    return tmp_path


@pytest.fixture
def validator(mock_child_path):
    """Create a TieredValidator for test child."""
    config = MagicMock()
    config.red_team_mandatory = False
    v = TieredValidator.__new__(TieredValidator)
    v.child_path = mock_child_path
    v.child_id = "test_child_001"
    v.config = config
    return v


class TestDeterministicTier3:
    """Test the V12.4 deterministic fitness pipeline."""

    def test_tier3_returns_tier_result(self, validator):
        """Tier 3 should return a TierResult."""
        result = validator._run_tier3_parallel_benchmark()
        assert isinstance(result, TierResult)
        assert result.tier == ValidationTier.BENCHMARK

    def test_tier3_details_has_gates(self, validator):
        """Tier 3 details should contain gate results."""
        result = validator._run_tier3_parallel_benchmark()
        assert "gates" in result.details
        assert "method" in result.details
        assert result.details["method"] == "deterministic_v12.4"

    def test_tier3_content_hash_present(self, validator):
        """Tier 3 should compute a content hash."""
        result = validator._run_tier3_parallel_benchmark()
        gates = result.details["gates"]
        assert "content_hash" in gates
        assert len(gates["content_hash"]) == 16  # Truncated SHA256

    def test_tier3_pytest_gate(self, validator, mock_child_path):
        """Tier 3 should run pytest on the child's test suite."""
        result = validator._run_tier3_parallel_benchmark()
        gates = result.details["gates"]
        assert "pytest" in gates

    def test_tier3_lint_gate(self, validator):
        """Tier 3 should run lint check."""
        result = validator._run_tier3_parallel_benchmark()
        gates = result.details["gates"]
        assert "lint" in gates

    def test_tier3_fitness_score(self, validator):
        """Tier 3 should compute a fitness score."""
        result = validator._run_tier3_parallel_benchmark()
        assert "fitness_score" in result.details
        assert 0.0 <= result.details["fitness_score"] <= 1.0


class TestLineageSHA256:
    """Test SHA256 content hashing in lineage."""

    def test_content_hash_deterministic(self, mock_child_path):
        """Same codebase should produce same content hash."""
        h1 = hashlib.sha256()
        h2 = hashlib.sha256()

        for py_file in sorted(mock_child_path.rglob("*.py")):
            data = py_file.read_bytes()
            h1.update(data)
            h2.update(data)

        assert h1.hexdigest() == h2.hexdigest()

    def test_content_hash_changes_on_modification(self, mock_child_path):
        """Content hash should change when code is modified."""
        h1 = hashlib.sha256()
        for py_file in sorted(mock_child_path.rglob("*.py")):
            h1.update(py_file.read_bytes())
        hash_before = h1.hexdigest()

        # Modify a file
        (mock_child_path / "main.py").write_text("print('modified')\n")

        h2 = hashlib.sha256()
        for py_file in sorted(mock_child_path.rglob("*.py")):
            h2.update(py_file.read_bytes())
        hash_after = h2.hexdigest()

        assert hash_before != hash_after

    def test_promote_child_adds_content_hash(self, mock_child_path):
        """promote_child_to_parent should add content_hash_sha256."""
        from core.intelligence.evolution.lineage import promote_child_to_parent

        lineage = {
            "current_parent": {
                "id": "parent_v1",
                "path": "/old/parent",
                "generation": 1,
                "fitness_score": 0.70,
                "activated_at": "2026-01-01T00:00:00",
                "status": "active_parent",
            },
            "lineage_tree": {
                "parent_v1": {
                    "generation": 1,
                    "parent": None,
                    "children": [],
                    "status": "active_parent",
                    "fitness_score": 0.70,
                }
            },
            "evolution_stats": {
                "total_generations": 1,
                "successful_promotions": 0,
                "stagnation_counter": 1,
            },
        }

        updated = promote_child_to_parent(
            lineage=lineage,
            child_id="child_v2",
            child_path=mock_child_path,
            fitness_score=0.85,
            birth_cert_path="/certs/child_v2.json",
            notable_features=["Improved fitness"],
        )

        # Check that content hash was added
        child_entry = updated["lineage_tree"]["child_v2"]
        assert "content_hash_sha256" in child_entry
        assert len(child_entry["content_hash_sha256"]) == 64  # Full SHA256

        # Check parent hash reference
        assert "parent_content_hash" in child_entry
