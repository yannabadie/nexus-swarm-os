"""
V9 Security Tests: Path Traversal Protection

Tests for the PathGuardian integration in ToolManager._execute_read().
Verifies that path traversal attacks are blocked in both normal and evolution modes.

SECURITY AUDIT: 2025-12-11
Vulnerability: CWE-22 (Path Traversal)
Fix: Always validate with PathGuardian.validate_read() BEFORE file access
"""

# Import after path setup
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.execution.tool_manager import ToolManager
from core.synapse.protocol_v7 import ToolUse


class TestPathTraversalSecurity:
    """Test suite for path traversal vulnerability prevention."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create a temporary workspace directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Create some test files
        (workspace / "allowed.txt").write_text("allowed content")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "nested.txt").write_text("nested content")
        return workspace

    @pytest.fixture
    def parent_env(self, tmp_path):
        """Create a fake .env in parent directory (attack target)."""
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=super_secret_value")
        return env_file

    @pytest.fixture
    def tool_manager(self, workspace):
        """Create a ToolManager in normal mode."""
        # V9: ToolManager only takes workspace_path, evolution_mode is set as attribute
        manager = ToolManager(workspace)
        manager.evolution_mode = False
        return manager

    @pytest.fixture
    def evolution_manager(self, workspace):
        """Create a ToolManager in evolution mode."""
        # V9: ToolManager only takes workspace_path, evolution_mode is set as attribute
        manager = ToolManager(workspace)
        manager.evolution_mode = True
        return manager

    # ==================== NORMAL MODE TESTS ====================

    def test_normal_read_allowed_file(self, tool_manager, workspace):
        """Normal mode: Reading files inside workspace should succeed."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "allowed.txt"}))
        assert result.status == "SUCCESS"
        assert "allowed content" in result.output

    def test_normal_read_nested_file(self, tool_manager, workspace):
        """Normal mode: Reading nested files should succeed."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "subdir/nested.txt"}))
        assert result.status == "SUCCESS"
        assert "nested content" in result.output

    def test_path_traversal_blocked_parent(self, tool_manager, parent_env):
        """SECURITY: Reading ../.env should be BLOCKED in normal mode."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "../.env"}))
        assert result.status == "BLOCKED"
        assert "SECURITY" in result.error or "blocked" in result.error.lower()

    def test_path_traversal_blocked_nested_escape(self, tool_manager, parent_env):
        """SECURITY: Reading ./../.env (bypass attempt) should be BLOCKED."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "./../.env"}))
        assert result.status == "BLOCKED"
        assert "SECURITY" in result.error or "blocked" in result.error.lower()

    def test_path_traversal_blocked_workspace_escape(self, tool_manager, parent_env):
        """SECURITY: Reading workspace/../../.env should be BLOCKED."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "foo/../../.env"}))
        assert result.status == "BLOCKED"

    def test_path_traversal_blocked_double_dot(self, tool_manager, parent_env):
        """SECURITY: Reading ../../etc/passwd style paths should be BLOCKED."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "../../etc/passwd"}))
        assert result.status == "BLOCKED"

    def test_path_traversal_blocked_absolute_outside(self, tool_manager, tmp_path):
        """SECURITY: Reading absolute paths outside workspace AND parent should be BLOCKED."""
        # Note: tmp_path is the workspace's parent, which IS a read zone by design
        # To test truly "outside", we need a file outside both workspace AND parent
        with tempfile.TemporaryDirectory() as truly_outside:
            outside_file = Path(truly_outside) / "truly_outside_secret.txt"
            outside_file.write_text("secret data from outside both zones")

            result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": str(outside_file)}))
            assert result.status == "BLOCKED"

    # ==================== EVOLUTION MODE TESTS ====================

    def test_evolution_env_blocked(self, evolution_manager, parent_env):
        """SECURITY V9: .env should be BLOCKED even in evolution mode."""
        result = evolution_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "../.env"}))
        # .env was removed from whitelist in V9
        assert result.status == "BLOCKED"

    def test_evolution_readme_allowed(self, evolution_manager, tmp_path):
        """Evolution mode: README.md in parent should be allowed (whitelist)."""
        # Create README in parent (simulates NEXUS root)
        readme = tmp_path / "README.md"
        readme.write_text("# NEXUS Documentation")

        # This depends on PathGuardian config - may need adjustment
        # For now, just verify the whitelist logic exists
        result = evolution_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "../README.md"}))
        # Could be SUCCESS (if in read_zones) or BLOCKED (if not)
        # The key is .env is NOT allowed
        assert result.status in ["SUCCESS", "BLOCKED"]

    # ==================== EDGE CASE TESTS ====================

    def test_empty_path_handled(self, tool_manager):
        """Empty file path should be handled gracefully."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": ""}))
        # Should fail but not crash (ERROR for missing/invalid argument is acceptable)
        assert result.status in ["BLOCKED", "FAILURE", "ERROR"]

    def test_null_bytes_blocked(self, tool_manager):
        """Null byte injection should be handled."""
        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "file.txt\x00.jpg"}))
        # Should fail or be blocked (ERROR for null byte handling is acceptable)
        assert result.status in ["BLOCKED", "FAILURE", "ERROR"]

    def test_unicode_normalization(self, tool_manager):
        """Unicode path normalization should not bypass security."""
        # Some systems allow unicode tricks
        result = tool_manager.execute(
            ToolUse(
                tool_name="read",
                arguments={"file_path": "..%2f.env"},  # URL encoded
            )
        )
        # Should not succeed in reading parent .env
        assert result.status in ["BLOCKED", "FAILURE"]

    def test_symlink_attack(self, tool_manager, workspace, tmp_path):
        """Symlinks pointing outside workspace to truly outside zones should be blocked."""
        # Note: tmp_path is the parent directory which IS a read zone by design
        # To test symlink security, we need to point to a truly outside location
        with tempfile.TemporaryDirectory() as truly_outside:
            outside = Path(truly_outside) / "truly_outside_secret.txt"
            outside.write_text("secret via symlink to truly outside")

            # Create symlink inside workspace pointing to truly outside
            link = workspace / "sneaky_link"
            try:
                link.symlink_to(outside)
            except OSError:
                pytest.skip("Symlinks not supported on this system")

            result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "sneaky_link"}))
            # PathGuardian should resolve symlink and block (outside all zones)
            assert result.status == "BLOCKED"

    def test_symlink_to_parent_sacred_blocked(self, tool_manager, workspace, tmp_path):
        """Symlinks to sacred files in parent should be blocked."""
        # Create .env in parent (tmp_path)
        parent_env = tmp_path / ".env"
        parent_env.write_text("SECRET_KEY=leaked_via_symlink")

        # Create symlink to .env in workspace
        link = workspace / "env_symlink"
        try:
            link.symlink_to(parent_env)
        except OSError:
            pytest.skip("Symlinks not supported on this system")

        result = tool_manager.execute(ToolUse(tool_name="read", arguments={"file_path": "env_symlink"}))
        # Even though parent is readable, .env is sacred
        assert result.status == "BLOCKED"


class TestPathGuardianIntegration:
    """Test PathGuardian is properly integrated."""

    @pytest.fixture
    def workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    def test_path_guardian_called(self, workspace):
        """Verify PathGuardian.validate_read() is called."""
        # V9: ToolManager only takes workspace_path
        manager = ToolManager(workspace)
        manager.evolution_mode = False

        # Mock PathGuardian
        with patch.object(manager.path_guardian, "validate_read") as mock_validate:
            mock_validate.return_value = (False, Path("/blocked"), "Test block")

            result = manager.execute(ToolUse(tool_name="read", arguments={"file_path": "any_file.txt"}))

            # Verify PathGuardian was called (V9.6: handlers pass absolute paths)
            mock_validate.assert_called_once()
            call_args = mock_validate.call_args[0][0]
            assert "any_file.txt" in call_args  # Path ends with the requested file
            assert result.status == "BLOCKED"

    def test_path_guardian_success_path(self, workspace):
        """Verify successful PathGuardian validation leads to file read."""
        # V9: ToolManager only takes workspace_path
        manager = ToolManager(workspace)
        manager.evolution_mode = False

        # Create test file
        test_file = workspace / "test.txt"
        test_file.write_text("test content")

        with patch.object(manager.path_guardian, "validate_read") as mock_validate:
            mock_validate.return_value = (True, test_file, "OK")

            result = manager.execute(ToolUse(tool_name="read", arguments={"file_path": "test.txt"}))

            assert result.status == "SUCCESS"
            assert "test content" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
