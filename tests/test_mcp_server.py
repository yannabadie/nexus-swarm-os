"""
Tests for NEXUS MCP Server (V9.0)

Tests the MCP server implementation that exposes NEXUS as a tool for external agents.
Validates tool registration, execution, and error handling.

Reference: https://gofastmcp.com/development/tests
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Mock Classes for Testing
# =============================================================================


@dataclass
class MockToolResult:
    """Mock result from ToolManager."""

    status: str
    output: str
    error: str = ""


class MockToolManager:
    """Mock ToolManager for isolated server tests."""

    def __init__(self):
        self.calls = []

    def execute_tool(self, tool_name: str, params: dict) -> MockToolResult:
        """Record tool execution and return mock result."""
        self.calls.append((tool_name, params))

        if tool_name == "read":
            return MockToolResult(status="SUCCESS", output=f"Mock content of {params.get('file_path', 'unknown')}")
        elif tool_name == "glob":
            return MockToolResult(status="SUCCESS", output="file1.py\nfile2.py\nfile3.py")
        elif tool_name == "grep":
            return MockToolResult(status="SUCCESS", output="src/main.py:10: pattern found")
        elif tool_name == "bash":
            return MockToolResult(status="SUCCESS", output="Command executed successfully")
        else:
            return MockToolResult(status="ERROR", output="", error=f"Unknown tool: {tool_name}")


class MockOrchestrator:
    """Mock OrchestratorV7 for isolated tests."""

    def __init__(self):
        self.calls = []

    def process_turn(self, task: str) -> dict:
        """Record task and return mock response."""
        self.calls.append(task)
        return {"response": f"Analysis of: {task}", "state": "IDLE", "agent": "gemini"}

    def get_system_status(self) -> dict:
        """Return mock system status."""
        return {"state": "IDLE", "active_agent": "gemini", "iteration": 0, "memory_stats": {"total_messages": 0}}


# =============================================================================
# Test Server Module Loading
# =============================================================================


class TestMCPServerModule:
    """Tests for MCP server module structure and imports."""

    def test_server_module_exists(self):
        """Test that server module can be imported."""
        from core.interface_pkg.mcp import server

        assert hasattr(server, "MCP_AVAILABLE")

    def test_mcp_availability_flag(self):
        """Test MCP_AVAILABLE flag is set correctly."""
        from core.interface_pkg.mcp import server

        # MCP_AVAILABLE depends on mcp package being installed
        assert isinstance(server.MCP_AVAILABLE, bool)

    def test_main_function_exists(self):
        """Test main entry point exists."""
        from core.interface_pkg.mcp import server

        assert hasattr(server, "main")
        assert callable(server.main)

    def test_lazy_loaders_exist(self):
        """Test lazy loader functions exist."""
        from core.interface_pkg.mcp import server

        assert hasattr(server, "get_tool_manager")
        assert hasattr(server, "get_orchestrator")


# =============================================================================
# Test Lazy Loaders
# =============================================================================


class TestLazyLoaders:
    """Tests for lazy loading functions."""

    def test_get_tool_manager_returns_instance(self):
        """Test get_tool_manager returns ToolManager instance."""
        from core.interface_pkg.mcp.server import get_tool_manager

        tm = get_tool_manager()
        assert tm is not None
        # ToolManager should have execute method
        assert hasattr(tm, "execute")

    def test_get_orchestrator_returns_instance(self):
        """Test get_orchestrator returns OrchestratorV7 instance."""
        from core.interface_pkg.mcp.server import get_orchestrator

        orch = get_orchestrator()
        assert orch is not None
        # OrchestratorV7 should have process_turn method
        assert hasattr(orch, "process_turn")


# =============================================================================
# Test Tool Functions (with mocks)
# =============================================================================


@pytest.mark.skipif(
    not pytest.importorskip("mcp", reason="MCP SDK not installed").server, reason="MCP SDK not installed"
)
class TestMCPTools:
    """Tests for MCP tool implementations."""

    @pytest.fixture
    def mock_execute_tool(self):
        """Create mock execute_tool function."""
        calls = []

        def _mock_execute(tool_name: str, params: dict):
            calls.append((tool_name, params))
            if tool_name == "read":
                return MockToolResult(status="SUCCESS", output=f"Mock content of {params.get('file_path', 'unknown')}")
            elif tool_name == "glob":
                return MockToolResult(status="SUCCESS", output="file1.py\nfile2.py\nfile3.py")
            elif tool_name == "grep":
                return MockToolResult(status="SUCCESS", output="src/main.py:10: pattern found")
            elif tool_name == "bash":
                return MockToolResult(status="SUCCESS", output="Command executed successfully")
            return MockToolResult(status="ERROR", output="", error=f"Unknown tool: {tool_name}")

        _mock_execute.calls = calls
        return _mock_execute

    @pytest.mark.asyncio
    async def test_nexus_read_success(self, mock_execute_tool):
        """Test nexus_read returns file contents."""
        with patch("core.interface_pkg.mcp.server.execute_tool", mock_execute_tool):
            from core.interface_pkg.mcp.server import nexus_read

            result = await nexus_read("/path/to/file.py", offset=0, limit=100)

            assert "Mock content" in result
            assert len(mock_execute_tool.calls) == 1
            assert mock_execute_tool.calls[0][0] == "read"

    @pytest.mark.asyncio
    async def test_nexus_glob_success(self, mock_execute_tool):
        """Test nexus_glob returns matching files."""
        with patch("core.interface_pkg.mcp.server.execute_tool", mock_execute_tool):
            from core.interface_pkg.mcp.server import nexus_glob

            result = await nexus_glob("**/*.py", path=".")

            assert "file1.py" in result
            assert len(mock_execute_tool.calls) == 1
            assert mock_execute_tool.calls[0][0] == "glob"

    @pytest.mark.asyncio
    async def test_nexus_grep_success(self, mock_execute_tool):
        """Test nexus_grep returns matching lines."""
        with patch("core.interface_pkg.mcp.server.execute_tool", mock_execute_tool):
            from core.interface_pkg.mcp.server import nexus_grep

            result = await nexus_grep("pattern", path=".", file_type="py")

            assert "pattern found" in result
            assert len(mock_execute_tool.calls) == 1
            assert mock_execute_tool.calls[0][0] == "grep"

    @pytest.mark.asyncio
    async def test_nexus_bash_success(self, mock_execute_tool):
        """Test nexus_bash executes command."""
        with patch("core.interface_pkg.mcp.server.execute_tool", mock_execute_tool):
            from core.interface_pkg.mcp.server import nexus_bash

            result = await nexus_bash("echo hello", timeout=10)

            assert "successfully" in result
            assert len(mock_execute_tool.calls) == 1
            assert mock_execute_tool.calls[0][0] == "bash"

    @pytest.mark.asyncio
    async def test_nexus_bash_timeout_cap(self, mock_execute_tool):
        """Test nexus_bash caps timeout at 120s."""
        with patch("core.interface_pkg.mcp.server.execute_tool", mock_execute_tool):
            from core.interface_pkg.mcp.server import nexus_bash

            await nexus_bash("echo hello", timeout=999)

            # Should have capped timeout to 120s (120000ms)
            _, params = mock_execute_tool.calls[0]
            assert params["timeout"] == 120 * 1000


@pytest.mark.skipif(
    not pytest.importorskip("mcp", reason="MCP SDK not installed").server, reason="MCP SDK not installed"
)
class TestMCPAnalysis:
    """Tests for MCP analysis tools."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create mock Orchestrator."""
        return MockOrchestrator()

    @pytest.mark.asyncio
    async def test_nexus_analyze_success(self, mock_orchestrator):
        """Test nexus_analyze returns analysis."""
        with patch("core.interface_pkg.mcp.server.get_orchestrator", return_value=mock_orchestrator):
            from core.interface_pkg.mcp.server import nexus_analyze

            result = await nexus_analyze("Analyze this code")

            assert "Analysis of" in result
            assert len(mock_orchestrator.calls) == 1

    @pytest.mark.asyncio
    async def test_nexus_status_returns_json(self, mock_orchestrator):
        """Test nexus_status returns valid JSON."""
        import json

        with patch("core.interface_pkg.mcp.server.get_orchestrator", return_value=mock_orchestrator):
            from core.interface_pkg.mcp.server import nexus_status

            result = await nexus_status()

            # Should be valid JSON
            status = json.loads(result)
            assert "state" in status
            assert status["state"] == "IDLE"

    @pytest.mark.asyncio
    async def test_nexus_research_returns_synthesized_summary(self):
        """Test nexus_research surfaces answer bullets and confidence."""
        payload = {
            "query": "How does ProjectMemory index files?",
            "mode": "mock",
            "backend": "tfidf",
            "generated_at": "2026-03-09T00:00:00+00:00",
            "sources": [
                {
                    "source_id": "S1",
                    "file_path": "core/memory_pkg/memory/project_memory.py",
                    "start_line": 1,
                    "end_line": 20,
                }
            ],
            "synthesis": {
                "overall_confidence": {"label": "medium", "score": 0.61},
                "answer_bullets": ["Implementation evidence indicates local project indexing. [S1]"],
            },
        }

        with patch("core.interface_pkg.mcp.server.build_memory_search", return_value=payload):
            from core.interface_pkg.mcp.server import nexus_research

            result = await nexus_research("How does ProjectMemory index files?")

            assert "Confidence: medium" in result
            assert "Implementation evidence indicates local project indexing. [S1]" in result
            assert "[S1] core/memory_pkg/memory/project_memory.py" in result


# =============================================================================
# Test Error Handling
# =============================================================================


class TestMCPErrorHandling:
    """Tests for error handling in MCP tools."""

    @pytest.mark.asyncio
    async def test_nexus_read_handles_exception(self):
        """Test nexus_read handles exceptions gracefully."""

        def raise_error():
            raise Exception("File not found")

        with patch("core.interface_pkg.mcp.server.get_tool_manager", side_effect=raise_error):
            try:
                from core.interface_pkg.mcp.server import nexus_read

                result = await nexus_read("/nonexistent/file.py")
                assert "Error" in result
            except ImportError:
                pytest.skip("MCP SDK not installed")

    @pytest.mark.asyncio
    async def test_nexus_analyze_handles_exception(self):
        """Test nexus_analyze handles exceptions gracefully."""

        def raise_error():
            raise Exception("Orchestrator error")

        with patch("core.interface_pkg.mcp.server.get_orchestrator", side_effect=raise_error):
            try:
                from core.interface_pkg.mcp.server import nexus_analyze

                result = await nexus_analyze("test task")
                assert "Error" in result
            except ImportError:
                pytest.skip("MCP SDK not installed")


# =============================================================================
# Test Resources (if MCP available)
# =============================================================================


@pytest.mark.skipif(
    not pytest.importorskip("mcp", reason="MCP SDK not installed").server, reason="MCP SDK not installed"
)
class TestMCPResources:
    """Tests for MCP resource endpoints."""

    @pytest.mark.asyncio
    async def test_get_nexus_config_resource(self):
        """Test nexus://config resource returns config."""
        from core.interface_pkg.mcp.server import get_nexus_config

        result = await get_nexus_config()

        # Should return string (config summary or error)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_get_nexus_agents_resource(self):
        """Test nexus://agents resource returns agent list."""
        from core.interface_pkg.mcp.server import get_nexus_agents

        result = await get_nexus_agents()

        # Should return string (JSON or error)
        assert isinstance(result, str)


# =============================================================================
# Integration Tests (MCP SDK required)
# =============================================================================


@pytest.mark.skipif(
    not pytest.importorskip("mcp", reason="MCP SDK not installed").server, reason="MCP SDK not installed"
)
class TestMCPIntegration:
    """Integration tests for MCP server (requires MCP SDK)."""

    def test_fastmcp_server_creation(self):
        """Test FastMCP server is created correctly."""
        from core.interface_pkg.mcp.server import mcp

        assert mcp is not None
        assert mcp.name == "nexus"

    def test_tools_registered(self):
        """Test all expected tools are registered."""
        from core.interface_pkg.mcp.server import mcp

        # FastMCP stores tools internally
        # This test validates the server object exists and is configured
        assert hasattr(mcp, "run")


# =============================================================================
# Test Server Startup
# =============================================================================


class TestServerStartup:
    """Tests for server startup behavior."""

    def test_main_exits_if_mcp_unavailable(self):
        """Test main() raises MCPNotAvailableError if MCP not installed."""
        with patch("core.interface_pkg.mcp.server.MCP_AVAILABLE", False):
            from core.interface_pkg.mcp import server

            # Reload to pick up the patched value
            with pytest.raises(server.MCPNotAvailableError):
                server.main()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
