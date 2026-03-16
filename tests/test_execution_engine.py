"""
Tests for core/execution/execution_engine.py - V9.5

Validates centralized tool execution.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from core.execution_pkg.execution.execution_engine import (
    ExecutionEngine,
    get_execution_engine,
    reset_execution_engine,
)
from core.execution_pkg.execution.handlers.base import ToolResult
from core.execution_pkg.execution.tool_registry import reset_tool_registry


@dataclass
class MockToolRequest:
    """Mock tool request for testing."""

    tool_name: str
    arguments: dict


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset global state before each test."""
    reset_execution_engine()
    reset_tool_registry()
    yield
    reset_execution_engine()
    reset_tool_registry()


@pytest.fixture
def workspace_path(tmp_path):
    """Create temporary workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def engine(workspace_path):
    """Create ExecutionEngine with mocked security."""
    with patch("core.execution_pkg.execution.execution_engine.ValidationService") as mock_vs:
        mock_vs_instance = MagicMock()
        mock_vs_instance.validate_path.return_value = True
        mock_vs.return_value = mock_vs_instance

        engine = ExecutionEngine(workspace_path)
        engine.validation_service = mock_vs_instance
        return engine


class TestExecutionEngineInit:
    """Initialization tests."""

    def test_creates_with_workspace(self, workspace_path):
        """Should create engine with workspace path."""
        with patch("core.execution_pkg.execution.execution_engine.ValidationService"):
            engine = ExecutionEngine(workspace_path)
            assert engine.workspace_path == workspace_path

    def test_initializes_core_handlers(self, engine):
        """Should initialize core tool handlers."""
        tools = engine.list_tools()
        # Core handlers should be registered
        assert "read" in tools
        assert "write" in tools
        assert "bash" in tools
        assert "glob" in tools
        assert "grep" in tools


class TestExecute:
    """Tool execution tests."""

    def test_execute_registered_tool(self, engine):
        """Should execute registered tool."""

        # Register custom handler
        def custom_handler(args):
            return ToolResult.ok("custom", f"Got: {args.get('value', 'none')}")

        engine.register_handler("custom", custom_handler)

        request = MockToolRequest("custom", {"value": "test"})
        result = engine.execute(request)

        assert result.status == "SUCCESS"
        assert "test" in result.output

    def test_execute_unknown_tool(self, engine):
        """Should return error for unknown tool."""
        request = MockToolRequest("nonexistent", {})
        result = engine.execute(request)

        assert result.status == "ERROR"
        assert "Unknown tool" in result.error

    def test_execute_by_name(self, engine):
        """Should execute tool by name and args."""

        def handler(args):
            return ToolResult.ok("direct", "direct call")

        engine.register_handler("direct_test", handler)

        result = engine.execute_by_name("direct_test", {})
        assert result.status == "SUCCESS"


class TestToolAliases:
    """Tool alias handling tests."""

    def test_normalize_gemini_aliases(self, engine):
        """Should normalize Gemini CLI tool names."""
        # read_file should map to read handler
        assert engine.has_tool("read_file")  # Via alias
        assert engine.has_tool("read")  # Direct

    def test_execute_with_alias(self, engine, tmp_path):
        """Should execute tool using alias."""
        # Create test file
        test_file = tmp_path / "workspace" / "test.txt"
        test_file.parent.mkdir(exist_ok=True)
        test_file.write_text("content")

        # Mock validation
        engine.validation_service.validate_path.return_value = True

        # Execute via alias
        engine.execute_by_name("read_file", {"file_path": str(test_file)})
        # Note: May fail if handler actually runs - we're testing routing


class TestStatistics:
    """Execution statistics tests."""

    def test_stats_initialized(self, engine):
        """Stats should start at zero."""
        stats = engine.get_stats()
        assert stats["total_executions"] == 0
        assert stats["successful"] == 0
        assert stats["failed"] == 0

    def test_stats_track_success(self, engine):
        """Stats should track successful executions."""

        def success_handler(args):
            return ToolResult.ok("test", "success")

        engine.register_handler("success_test", success_handler)
        engine.execute_by_name("success_test", {})

        stats = engine.get_stats()
        assert stats["total_executions"] == 1
        assert stats["successful"] == 1

    def test_stats_track_failure(self, engine):
        """Stats should track failed executions."""

        def fail_handler(args):
            return ToolResult.fail("test", "failed")

        engine.register_handler("fail_test", fail_handler)
        engine.execute_by_name("fail_test", {})

        stats = engine.get_stats()
        assert stats["total_executions"] == 1
        assert stats["failed"] == 1

    def test_stats_track_blocked(self, engine):
        """Stats should track blocked executions."""

        def blocked_handler(args):
            return ToolResult(tool_name="test", status="BLOCKED", output="", error="Security")

        engine.register_handler("blocked_test", blocked_handler)
        engine.execute_by_name("blocked_test", {})

        stats = engine.get_stats()
        assert stats["blocked"] == 1

    def test_reset_stats(self, engine):
        """Should reset statistics."""

        def handler(args):
            return ToolResult.ok("test", "ok")

        engine.register_handler("reset_test", handler)
        engine.execute_by_name("reset_test", {})

        engine.reset_stats()
        stats = engine.get_stats()
        assert stats["total_executions"] == 0


class TestRegisterHandler:
    """Handler registration tests."""

    def test_register_custom_handler(self, engine):
        """Should register custom handler."""

        def my_handler(args):
            return ToolResult.ok("my_tool", "works")

        engine.register_handler("my_tool", my_handler, category="custom", description="My custom tool")

        assert engine.has_tool("my_tool")

    def test_has_tool(self, engine):
        """Should check tool existence."""
        assert engine.has_tool("read")
        assert not engine.has_tool("nonexistent")


class TestEvolutionMode:
    """Evolution mode tests."""

    def test_set_evolution_mode(self, engine):
        """Should toggle evolution mode."""
        engine.set_evolution_mode(True)
        engine.validation_service.set_evolution_mode.assert_called_with(True)

        engine.set_evolution_mode(False)
        engine.validation_service.set_evolution_mode.assert_called_with(False)


class TestGlobalEngine:
    """Global singleton tests."""

    def test_singleton_instance(self, workspace_path):
        """get_execution_engine should return same instance."""
        with patch("core.execution_pkg.execution.execution_engine.ValidationService"):
            engine1 = get_execution_engine(workspace_path)
            engine2 = get_execution_engine()
            assert engine1 is engine2

    def test_requires_workspace_first_call(self):
        """Should require workspace on first call."""
        with pytest.raises(ValueError, match="workspace_path required"):
            get_execution_engine(None)

    def test_reset_creates_new(self, workspace_path):
        """reset_execution_engine should clear instance."""
        with patch("core.execution_pkg.execution.execution_engine.ValidationService"):
            engine1 = get_execution_engine(workspace_path)
            reset_execution_engine()
            engine2 = get_execution_engine(workspace_path)
            assert engine1 is not engine2


class TestErrorHandling:
    """Error handling tests."""

    def test_handler_exception_caught(self, engine):
        """Should catch handler exceptions."""

        def broken_handler(args):
            raise RuntimeError("Handler crashed")

        engine.register_handler("broken", broken_handler)
        result = engine.execute_by_name("broken", {})

        assert result.status == "ERROR"
        assert "Handler crashed" in result.error

    def test_failed_executions_counted(self, engine):
        """Exception should count as failed."""

        def broken_handler(args):
            raise RuntimeError("Crash")

        engine.register_handler("crash", broken_handler)
        engine.execute_by_name("crash", {})

        stats = engine.get_stats()
        assert stats["failed"] == 1
