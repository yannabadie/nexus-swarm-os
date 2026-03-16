"""
Tests for Tool Manager - NEXUS V7

Tests all 11 tools, security layers (bash blacklist, PathGuardian), and evolution mode.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.execution.tool_manager import (
    ToolManager,
    ToolResult,
)
from core.security_pkg.security.execution_policy import ExecutionPolicy

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    workspace = Path(tempfile.mkdtemp()).resolve() / "workspace"
    workspace.mkdir(parents=True)

    # Create .nexus directory
    (workspace / ".nexus").mkdir()

    # Create some test files
    (workspace / "test_file.txt").write_text("Hello World")
    (workspace / "test_file.py").write_text("print('test')")
    (workspace / "subdir").mkdir()
    (workspace / "subdir" / "nested.txt").write_text("Nested content")

    yield workspace

    # Cleanup
    shutil.rmtree(workspace.parent, ignore_errors=True)


@pytest.fixture
def tool_manager(temp_workspace):
    """Create a ToolManager instance with temp workspace."""
    return ToolManager(temp_workspace)


@pytest.fixture
def mock_tool_request():
    """Factory for creating mock tool requests."""

    class MockToolRequest:
        def __init__(self, tool_name: str, arguments: dict):
            self.tool_name = tool_name
            self.arguments = arguments

    return MockToolRequest


# ============================================================================
# ToolResult Tests
# ============================================================================


class TestToolResult:
    """Test ToolResult data class."""

    def test_init_success(self):
        """Test ToolResult initialization."""
        result = ToolResult(tool_name="read", status="SUCCESS", output="File content here", error="")

        assert result.tool_name == "read"
        assert result.status == "SUCCESS"
        assert result.output == "File content here"
        assert result.error == ""

    def test_init_failure(self):
        """Test ToolResult with failure."""
        result = ToolResult(tool_name="write", status="FAILURE", output="", error="File not found")

        assert result.status == "FAILURE"
        assert result.error == "File not found"

    def test_to_dict(self):
        """Test ToolResult serialization."""
        result = ToolResult(tool_name="bash", status="SUCCESS", output="output text", error="stderr text")

        d = result.to_dict()

        assert d["tool_name"] == "bash"
        assert d["status"] == "SUCCESS"
        assert d["output"] == "output text"
        assert d["error"] == "stderr text"

    def test_default_error(self):
        """Test default empty error."""
        result = ToolResult(tool_name="test", status="SUCCESS", output="out")

        assert result.error == ""


# ============================================================================
# Bash Blacklist Security Tests
# ============================================================================


class TestBashBlacklist:
    """Test bash command security (via ExecutionPolicy)."""

    def test_execution_policy_patterns_exist(self):
        """Verify ExecutionPolicy has blocked patterns and executables."""
        assert len(ExecutionPolicy.BLOCKED_PATTERNS) > 0
        assert len(ExecutionPolicy.BLOCKED_EXECUTABLES) > 0

    def test_deep_traversal_blocked(self, tool_manager, mock_tool_request):
        """Deep path traversal (../../../) should be blocked."""
        request = mock_tool_request("bash", {"command": "cat ../../../etc/passwd"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        # Blocked by either path traversal or password file pattern
        assert "blocked" in result.error.lower()

    def test_rm_rf_parent_blocked(self, tool_manager, mock_tool_request):
        """rm -rf on parent directory should be blocked."""
        request = mock_tool_request("bash", {"command": "rm -rf ../core"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        assert "rm" in result.error.lower() or "parent" in result.error.lower()

    def test_git_push_blocked(self, tool_manager, mock_tool_request):
        """git push should be blocked via bash (use git tool instead)."""
        request = mock_tool_request("bash", {"command": "git push origin main"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        assert "git" in result.error.lower()

    def test_git_commit_blocked(self, tool_manager, mock_tool_request):
        """git commit should be blocked via bash (use git tool instead)."""
        request = mock_tool_request("bash", {"command": "git commit -m 'test'"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        assert "git" in result.error.lower()

    def test_git_add_blocked(self, tool_manager, mock_tool_request):
        """git add should be blocked via bash (use git tool instead)."""
        request = mock_tool_request("bash", {"command": "git add ."})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        assert "git" in result.error.lower()

    def test_redirect_to_parent_blocked(self, tool_manager, mock_tool_request):
        """Redirect output to parent directory should be blocked."""
        request = mock_tool_request("bash", {"command": "echo 'hack' > ../malicious.py"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        assert "redirect" in result.error.lower() or "parent" in result.error.lower()

    def test_python_parent_file_not_blocked(self, tool_manager, mock_tool_request):
        """Python execution of parent file is not inherently dangerous.

        Note: This was previously blocked but is now allowed because:
        1. python is not a blocked executable
        2. Reading parent files is allowed (needed for evolution mode)
        3. The script may not exist (FAILURE) but isn't BLOCKED
        """
        request = mock_tool_request("bash", {"command": "python ../test.py"})
        result = tool_manager.execute(request)

        # Not BLOCKED - may FAIL because file doesn't exist, but that's OK
        assert result.status != "BLOCKED"

    def test_safe_commands_allowed(self, tool_manager, mock_tool_request):
        """Safe commands should be allowed."""
        # List directory
        request = mock_tool_request("bash", {"command": "ls -la"})
        result = tool_manager.execute(request)
        assert result.status != "BLOCKED"

        # Python version
        request = mock_tool_request("bash", {"command": "python --version"})
        result = tool_manager.execute(request)
        assert result.status != "BLOCKED"


# ============================================================================
# Read Tool Tests
# ============================================================================


class TestReadTool:
    """Test read tool functionality."""

    def test_read_existing_file(self, tool_manager, mock_tool_request, temp_workspace):
        """Read an existing file."""
        request = mock_tool_request("read", {"file_path": "test_file.txt"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert result.output == "Hello World"

    def test_read_nested_file(self, tool_manager, mock_tool_request):
        """Read a nested file."""
        request = mock_tool_request("read", {"file_path": "subdir/nested.txt"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert result.output == "Nested content"

    def test_read_nonexistent_file(self, tool_manager, mock_tool_request):
        """Read a file that doesn't exist."""
        request = mock_tool_request("read", {"file_path": "does_not_exist.txt"})
        result = tool_manager.execute(request)

        assert result.status == "FAILURE"
        assert "not found" in result.error.lower()


# ============================================================================
# Write Tool Tests
# ============================================================================


class TestWriteTool:
    """Test write tool functionality."""

    def test_write_new_file(self, tool_manager, mock_tool_request, temp_workspace):
        """Write a new file."""
        request = mock_tool_request("write", {"file_path": "new_file.txt", "content": "New content"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert (temp_workspace / "new_file.txt").read_text() == "New content"

    def test_write_creates_directories(self, tool_manager, mock_tool_request, temp_workspace):
        """Write should create parent directories."""
        request = mock_tool_request("write", {"file_path": "new_dir/sub_dir/file.txt", "content": "Deep content"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert (temp_workspace / "new_dir" / "sub_dir" / "file.txt").exists()

    def test_write_overwrite_existing(self, tool_manager, mock_tool_request, temp_workspace):
        """Write should overwrite existing file."""
        request = mock_tool_request("write", {"file_path": "test_file.txt", "content": "Updated content"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert (temp_workspace / "test_file.txt").read_text() == "Updated content"


# ============================================================================
# Edit Tool Tests
# ============================================================================


class TestEditTool:
    """Test edit tool functionality."""

    def test_edit_replace_string(self, tool_manager, mock_tool_request, temp_workspace):
        """Edit should replace string in file."""
        request = mock_tool_request(
            "edit", {"file_path": "test_file.txt", "old_string": "Hello", "new_string": "Goodbye"}
        )
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert (temp_workspace / "test_file.txt").read_text() == "Goodbye World"

    def test_edit_string_not_found(self, tool_manager, mock_tool_request):
        """Edit should fail if string not found."""
        request = mock_tool_request(
            "edit", {"file_path": "test_file.txt", "old_string": "NONEXISTENT", "new_string": "replacement"}
        )
        result = tool_manager.execute(request)

        assert result.status == "FAILURE"
        assert "not found" in result.error.lower()

    def test_edit_file_not_found(self, tool_manager, mock_tool_request):
        """Edit should fail if file not found."""
        request = mock_tool_request("edit", {"file_path": "nonexistent.txt", "old_string": "x", "new_string": "y"})
        result = tool_manager.execute(request)

        assert result.status == "FAILURE"


# ============================================================================
# List Dir Tool Tests
# ============================================================================


class TestListDirTool:
    """Test list_dir tool functionality."""

    def test_list_workspace(self, tool_manager, mock_tool_request):
        """List workspace directory."""
        request = mock_tool_request("list_dir", {"path": "."})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "test_file.txt" in result.output
        assert "subdir" in result.output

    def test_list_subdirectory(self, tool_manager, mock_tool_request):
        """List subdirectory."""
        request = mock_tool_request("list_dir", {"path": "subdir"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "nested.txt" in result.output

    def test_list_nonexistent(self, tool_manager, mock_tool_request):
        """List nonexistent directory."""
        request = mock_tool_request("list_dir", {"path": "nonexistent"})
        result = tool_manager.execute(request)

        assert result.status == "FAILURE"


# ============================================================================
# Git Tool Tests
# ============================================================================


class TestGitTool:
    """Test git tool functionality."""

    def test_git_status_allowed(self, tool_manager, mock_tool_request):
        """git status should be allowed (read-only)."""
        request = mock_tool_request("git", {"operation": "status"})
        result = tool_manager.execute(request)

        # May fail if not in git repo, but shouldn't be BLOCKED
        assert result.status != "BLOCKED"

    def test_git_log_allowed(self, tool_manager, mock_tool_request):
        """git log should be allowed (read-only)."""
        request = mock_tool_request("git", {"operation": "log", "args": "-1"})
        result = tool_manager.execute(request)

        assert result.status != "BLOCKED"

    def test_git_diff_allowed(self, tool_manager, mock_tool_request):
        """git diff should be allowed (read-only)."""
        request = mock_tool_request("git", {"operation": "diff"})
        result = tool_manager.execute(request)

        assert result.status != "BLOCKED"

    def test_git_push_blocked(self, tool_manager, mock_tool_request):
        """git push should be blocked."""
        request = mock_tool_request("git", {"operation": "push"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"
        assert "SECURITY" in result.error or "READ-ONLY" in result.error

    def test_git_commit_blocked(self, tool_manager, mock_tool_request):
        """git commit should be blocked."""
        request = mock_tool_request("git", {"operation": "commit", "args": "-m 'test'"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"

    def test_git_add_blocked(self, tool_manager, mock_tool_request):
        """git add should be blocked."""
        request = mock_tool_request("git", {"operation": "add", "args": "."})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"

    def test_git_reset_blocked(self, tool_manager, mock_tool_request):
        """git reset should be blocked."""
        request = mock_tool_request("git", {"operation": "reset"})
        result = tool_manager.execute(request)

        assert result.status == "BLOCKED"

    def test_git_invalid_operation(self, tool_manager, mock_tool_request):
        """Invalid git operation should error."""
        request = mock_tool_request("git", {"operation": "invalid_op"})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "Invalid git operation" in result.error


# ============================================================================
# Web Search Tool Tests
# ============================================================================


class TestWebSearchTool:
    """Test web_search tool functionality."""

    def test_web_search_requires_query(self, tool_manager, mock_tool_request):
        """web_search should require query parameter."""
        request = mock_tool_request("web_search", {})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "query" in result.error.lower()

    @patch("subprocess.run")
    def test_web_search_success(self, mock_run, tool_manager, mock_tool_request):
        """web_search should call Gemini CLI."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Search results here", stderr="")

        request = mock_tool_request("web_search", {"query": "Python asyncio"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        mock_run.assert_called_once()


# ============================================================================
# Web Fetch Tool Tests
# ============================================================================


class TestWebFetchTool:
    """Test web_fetch tool functionality."""

    def test_web_fetch_requires_url(self, tool_manager, mock_tool_request):
        """web_fetch should require URL parameter."""
        request = mock_tool_request("web_fetch", {})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "url" in result.error.lower()

    def test_web_fetch_validates_url_scheme(self, tool_manager, mock_tool_request):
        """web_fetch should validate URL scheme."""
        request = mock_tool_request("web_fetch", {"url": "ftp://example.com"})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "http" in result.error.lower()

    def test_web_fetch_rejects_invalid_url(self, tool_manager, mock_tool_request):
        """web_fetch should reject invalid URLs."""
        request = mock_tool_request("web_fetch", {"url": "not-a-url"})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"


# ============================================================================
# Glob Tool Tests
# ============================================================================


class TestGlobTool:
    """Test glob tool functionality."""

    def test_glob_requires_pattern(self, tool_manager, mock_tool_request):
        """glob should require pattern parameter."""
        request = mock_tool_request("glob", {})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "pattern" in result.error.lower()

    def test_glob_finds_files(self, tool_manager, mock_tool_request):
        """glob should find matching files."""
        request = mock_tool_request("glob", {"pattern": "*.txt"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "test_file.txt" in result.output

    def test_glob_finds_python_files(self, tool_manager, mock_tool_request):
        """glob should find Python files."""
        request = mock_tool_request("glob", {"pattern": "*.py"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "test_file.py" in result.output

    def test_glob_no_matches(self, tool_manager, mock_tool_request):
        """glob should handle no matches gracefully."""
        request = mock_tool_request("glob", {"pattern": "*.nonexistent"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "no files found" in result.output.lower()

    def test_glob_evolution_mode(self, tool_manager, mock_tool_request, temp_workspace):
        """glob should support evolution mode (access parent)."""
        # Setup parent structure
        parent = temp_workspace.parent
        (parent / "core").mkdir(exist_ok=True)
        (parent / "core" / "parent_file.py").write_text("content")

        # Enable evolution mode
        tool_manager.evolution_mode = True

        # Test allowed access
        request = mock_tool_request("glob", {"pattern": "*.py", "path": "../core"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS", f"Glob failed: {result.error}"
        assert "parent_file.py" in result.output

        # Test forbidden access
        (parent / "forbidden").mkdir(exist_ok=True)
        request = mock_tool_request("glob", {"pattern": "*", "path": "../forbidden"})
        result = tool_manager.execute(request)

        assert result.status == "FAILURE"
        assert "not allowed" in result.error


# ============================================================================
# Grep Tool Tests
# ============================================================================


class TestGrepTool:
    """Test grep tool functionality."""

    def test_grep_requires_pattern(self, tool_manager, mock_tool_request):
        """grep should require pattern parameter."""
        request = mock_tool_request("grep", {})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "pattern" in result.error.lower()

    def test_grep_finds_content(self, tool_manager, mock_tool_request):
        """grep should find matching content."""
        request = mock_tool_request("grep", {"pattern": "Hello"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "test_file.txt" in result.output or "Hello" in result.output

    def test_grep_regex_pattern(self, tool_manager, mock_tool_request):
        """grep should support regex patterns."""
        request = mock_tool_request("grep", {"pattern": "print.*test"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "test_file.py" in result.output

    def test_grep_invalid_regex(self, tool_manager, mock_tool_request):
        """grep should handle invalid regex."""
        request = mock_tool_request("grep", {"pattern": "[invalid"})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "invalid regex" in result.error.lower()

    def test_grep_case_insensitive(self, tool_manager, mock_tool_request):
        """grep should support case-insensitive search."""
        request = mock_tool_request("grep", {"pattern": "HELLO", "case_sensitive": False})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        # Should find "Hello World" despite case mismatch

    def test_grep_evolution_mode(self, tool_manager, mock_tool_request, temp_workspace):
        """grep should support evolution mode (access parent)."""
        # Setup parent structure
        parent = temp_workspace.parent
        (parent / "core").mkdir(exist_ok=True)
        (parent / "core" / "parent_file.py").write_text("def target_function(): pass")

        # Enable evolution mode
        tool_manager.evolution_mode = True

        # Test allowed access
        request = mock_tool_request("grep", {"pattern": "target_function", "path": "../core"})
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS", f"Grep failed: {result.error}"
        assert "parent_file.py" in result.output
        assert "target_function" in result.output

        # Test forbidden access
        (parent / "forbidden").mkdir(exist_ok=True)
        request = mock_tool_request("grep", {"pattern": "target", "path": "../forbidden"})
        result = tool_manager.execute(request)

        assert result.status == "FAILURE"
        assert "not allowed" in result.error


# ============================================================================
# Todo Write Tool Tests
# ============================================================================


class TestTodoWriteTool:
    """Test todo_write tool functionality."""

    def test_todo_write_requires_list(self, tool_manager, mock_tool_request):
        """todo_write should require todos as list."""
        request = mock_tool_request("todo_write", {"todos": "not a list"})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "list" in result.error.lower()

    def test_todo_write_creates_file(self, tool_manager, mock_tool_request, temp_workspace):
        """todo_write should create plan file."""
        request = mock_tool_request(
            "todo_write",
            {
                "todos": [
                    {"id": 1, "description": "Task 1", "status": "pending"},
                    {"id": 2, "description": "Task 2", "status": "in_progress"},
                ]
            },
        )
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert (temp_workspace / ".nexus" / "plan.json").exists()

    def test_todo_write_formats_output(self, tool_manager, mock_tool_request):
        """todo_write should format output correctly."""
        request = mock_tool_request(
            "todo_write",
            {
                "todos": [
                    {"id": 1, "description": "First task", "status": "completed"},
                    {"id": 2, "description": "Second task", "status": "pending"},
                ]
            },
        )
        result = tool_manager.execute(request)

        assert result.status == "SUCCESS"
        assert "First task" in result.output
        assert "Second task" in result.output


# ============================================================================
# Unknown Tool Tests
# ============================================================================


class TestUnknownTool:
    """Test handling of unknown tools."""

    def test_unknown_tool_error(self, tool_manager, mock_tool_request):
        """Unknown tool should return error."""
        request = mock_tool_request("unknown_tool", {"arg": "value"})
        result = tool_manager.execute(request)

        assert result.status == "ERROR"
        assert "unknown tool" in result.error.lower()


# ============================================================================
# Tool Manager Initialization Tests
# ============================================================================


class TestToolManagerInit:
    """Test ToolManager initialization."""

    def test_all_tools_registered(self, tool_manager):
        """All 11 tools should be registered."""
        expected_tools = [
            "bash",
            "read",
            "write",
            "edit",
            "list_dir",
            "git",
            "web_search",
            "web_fetch",
            "glob",
            "grep",
            "todo_write",
        ]

        for tool in expected_tools:
            assert tool in tool_manager.tools, f"Missing tool: {tool}"

        assert len(tool_manager.tools) == 16  # V8.3.1: swarm_delegate added

    def test_evolution_mode_disabled_by_default(self, tool_manager):
        """Evolution mode should be disabled by default."""
        assert not tool_manager.evolution_mode

    def test_paths_computed_correctly(self, temp_workspace):
        """Paths should be computed correctly from workspace."""
        manager = ToolManager(temp_workspace)

        assert manager.workspace_path == temp_workspace
        assert manager.parent_path == temp_workspace.parent


# ============================================================================
# Evolution Mode Tests
# ============================================================================


class TestEvolutionMode:
    """Test evolution mode restrictions."""

    def test_evolution_mode_can_be_enabled(self, tool_manager):
        """Evolution mode can be toggled."""
        assert not tool_manager.evolution_mode

        tool_manager.evolution_mode = True
        assert tool_manager.evolution_mode

        tool_manager.evolution_mode = False
        assert not tool_manager.evolution_mode


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
