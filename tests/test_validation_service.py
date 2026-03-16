"""
Tests for core/execution/validation_service.py - V9.5

Validates path security and evolution mode checks.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.execution_pkg.execution.validation_service import ValidationService


@pytest.fixture
def workspace_path(tmp_path):
    """Create a temporary workspace structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create parent structure
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "core").mkdir()
    (parent / "prompts").mkdir()
    (parent / "benchmarks").mkdir()
    (parent / "README.md").write_text("# Test")

    # Create GENERATION_ACTIVE
    gen_active = tmp_path / "GENERATION_ACTIVE"
    gen_active.mkdir()
    (gen_active / "child1").mkdir()

    return workspace


@pytest.fixture
def validator(workspace_path, tmp_path):
    """Create ValidationService with mocked security layers."""
    parent = tmp_path / "parent"
    gen_active = tmp_path / "GENERATION_ACTIVE"

    with (
        patch("core.execution_pkg.execution.validation_service.PathGuardian") as mock_guardian,
        patch("core.execution_pkg.execution.validation_service.ExecutionPolicy") as mock_policy,
    ):
        # Mock PathGuardian
        mock_guardian_instance = MagicMock()
        mock_guardian_instance.validate_read.return_value = True
        mock_guardian_instance.validate_write.return_value = True
        mock_guardian.return_value = mock_guardian_instance

        # Mock ExecutionPolicy
        mock_policy_instance = MagicMock()
        mock_policy.return_value = mock_policy_instance

        service = ValidationService(
            workspace_path=workspace_path,
            parent_path=parent,
            generation_active=gen_active,
        )
        service.path_guardian = mock_guardian_instance
        return service


class TestEvolutionSafeRead:
    """Tests for is_evolution_safe_read."""

    def test_core_directory_allowed(self, validator, tmp_path):
        """core/ should be readable in evolution mode."""
        path = tmp_path / "parent" / "core" / "module.py"
        assert validator.is_evolution_safe_read(path) is True

    def test_prompts_directory_allowed(self, validator, tmp_path):
        """prompts/ should be readable in evolution mode."""
        path = tmp_path / "parent" / "prompts" / "system.md"
        assert validator.is_evolution_safe_read(path) is True

    def test_benchmarks_directory_allowed(self, validator, tmp_path):
        """benchmarks/ should be readable in evolution mode."""
        path = tmp_path / "parent" / "benchmarks" / "test.py"
        assert validator.is_evolution_safe_read(path) is True

    def test_readme_allowed(self, validator, tmp_path):
        """README.md should be readable in evolution mode."""
        path = tmp_path / "parent" / "README.md"
        assert validator.is_evolution_safe_read(path) is True

    def test_env_blocked(self, validator, tmp_path):
        """.env should be blocked (security)."""
        path = tmp_path / "parent" / ".env"
        assert validator.is_evolution_safe_read(path) is False

    def test_git_blocked(self, validator, tmp_path):
        """.git should be blocked."""
        path = tmp_path / "parent" / ".git" / "config"
        assert validator.is_evolution_safe_read(path) is False

    def test_pycache_blocked(self, validator, tmp_path):
        """__pycache__ should be blocked."""
        path = tmp_path / "parent" / "core" / "__pycache__" / "module.pyc"
        assert validator.is_evolution_safe_read(path) is False

    def test_outside_parent_blocked(self, validator, tmp_path):
        """Paths outside parent should be blocked."""
        path = tmp_path / "other" / "file.txt"
        assert validator.is_evolution_safe_read(path) is False


class TestEvolutionSafeList:
    """Tests for is_evolution_safe_list."""

    def test_core_directory_allowed(self, validator, tmp_path):
        """core/ should be listable in evolution mode."""
        path = tmp_path / "parent" / "core"
        assert validator.is_evolution_safe_list(path) is True

    def test_prompts_directory_allowed(self, validator, tmp_path):
        """prompts/ should be listable in evolution mode."""
        path = tmp_path / "parent" / "prompts"
        assert validator.is_evolution_safe_list(path) is True

    def test_git_blocked(self, validator, tmp_path):
        """.git should not be listable."""
        path = tmp_path / "parent" / ".git"
        assert validator.is_evolution_safe_list(path) is False


class TestEvolutionSafeWrite:
    """Tests for is_evolution_safe_write."""

    def test_generation_active_allowed(self, validator, tmp_path):
        """GENERATION_ACTIVE should be writable."""
        path = tmp_path / "GENERATION_ACTIVE" / "child1" / "file.py"
        assert validator.is_evolution_safe_write(path) is True

    def test_parent_blocked(self, validator, tmp_path):
        """Parent directory should NOT be writable."""
        path = tmp_path / "parent" / "core" / "file.py"
        assert validator.is_evolution_safe_write(path) is False

    def test_workspace_blocked(self, validator, workspace_path):
        """Workspace should NOT be writable via evolution."""
        path = workspace_path / "file.py"
        assert validator.is_evolution_safe_write(path) is False


class TestValidatePath:
    """Tests for unified validate_path method."""

    def test_read_delegates_to_guardian(self, validator):
        """Read should use PathGuardian."""
        validator.path_guardian.validate_read.return_value = True
        result = validator.validate_path(Path("/some/path"), "read")
        assert result is True

    def test_write_delegates_to_guardian(self, validator):
        """Write should use PathGuardian."""
        validator.path_guardian.validate_write.return_value = True
        result = validator.validate_path(Path("/some/path"), "write")
        assert result is True

    def test_evolution_mode_read(self, validator, tmp_path):
        """Evolution mode should check whitelist for reads."""
        validator.set_evolution_mode(True)
        path = tmp_path / "parent" / "core" / "file.py"
        result = validator.validate_path(path, "read", allow_parent_read=True)
        assert result is True


class TestSetEvolutionMode:
    """Tests for evolution mode toggle."""

    def test_enable_evolution_mode(self, validator):
        """Should enable evolution mode."""
        validator.set_evolution_mode(True)
        assert validator.evolution_mode is True

    def test_disable_evolution_mode(self, validator):
        """Should disable evolution mode."""
        validator.set_evolution_mode(True)
        validator.set_evolution_mode(False)
        assert validator.evolution_mode is False


class TestForbiddenPatterns:
    """Tests for forbidden pattern detection."""

    def test_nexus_v5_blocked(self, validator, tmp_path):
        """NEXUS_V5_PRAGMATIC should be blocked."""
        path = tmp_path / "parent" / "NEXUS_V5_PRAGMATIC" / "file.py"
        assert validator.is_evolution_safe_read(path) is False

    def test_pyc_blocked(self, validator, tmp_path):
        """.pyc files should be blocked."""
        path = tmp_path / "parent" / "core" / "module.pyc"
        assert validator.is_evolution_safe_read(path) is False
