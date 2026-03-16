"""
NEXUS V7.8 - Agent-as-Tool Tests (Phase 15: Vision Fractale)

Tests for the AgentToolRegistry that enables spawned agents
to be invoked as callable tools.

Test Layers:
1. Unit Tests - AgentToolRegistry in isolation (no LLM)
2. Integration Tests - With mock agents
3. Stress Tests - Concurrent tool invocations

Run: pytest tests/test_agent_as_tool.py -v
"""

import shutil

# Import modules under test
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.execution.agent_tools import AgentToolRegistry, AgentToolResult
from core.intelligence.swarm.agent_metrics import AgentPool, AgentProfile

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    workspace = Path(tempfile.mkdtemp())
    agents_dir = workspace / "agents"
    agents_dir.mkdir(parents=True)
    yield workspace
    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def mock_agent_pool():
    """Create a mock AgentPool with spawned agents."""
    pool = AgentPool()

    # Add core agents
    pool.register(
        AgentProfile(
            agent_id="gemini_primary",
            provider="gemini",
            model="gemini-3-pro-preview",
            capabilities=["reasoning", "coding"],
        )
    )
    pool.register(
        AgentProfile(
            agent_id="claude_opus",
            provider="claude",
            model="claude-opus-4-5",
            capabilities=["brainstorm", "creativity"],
        )
    )

    # Add spawned agents
    pool.register(
        AgentProfile(
            agent_id="security_expert",
            provider="spawned",
            model="spawned_security_expert",
            capabilities=["security", "audit", "vulnerability"],
        )
    )
    pool.register(
        AgentProfile(
            agent_id="sql_specialist",
            provider="spawned",
            model="spawned_sql_specialist",
            capabilities=["database", "sql", "optimization"],
        )
    )

    return pool


@pytest.fixture
def mock_agent_invoker():
    """Create a mock AgentInvoker."""
    invoker = Mock()
    invoker.invoke_spawned_agent = Mock(return_value="Task completed successfully.")
    return invoker


@pytest.fixture
def mock_agent_loader(temp_workspace):
    """Create a mock SpawnedAgentLoader."""
    loader = Mock()

    # Mock config for security_expert
    security_config = Mock()
    security_config.mission = "Analyze code for security vulnerabilities"
    security_config.domains = ["security", "audit"]

    # Mock config for sql_specialist
    sql_config = Mock()
    sql_config.mission = "Optimize SQL queries and database design"
    sql_config.domains = ["database", "sql"]

    def load_config(agent_id):
        configs = {"security_expert": security_config, "sql_specialist": sql_config}
        return configs.get(agent_id)

    loader.load_agent_config = load_config
    return loader


@pytest.fixture
def registry(temp_workspace, mock_agent_pool, mock_agent_invoker, mock_agent_loader):
    """Create an AgentToolRegistry with mocked dependencies."""
    reg = AgentToolRegistry(
        workspace_path=temp_workspace,
        agent_pool=mock_agent_pool,
        agent_invoker=mock_agent_invoker,
        agent_loader=mock_agent_loader,
    )
    reg.refresh()
    return reg


# =============================================================================
# Unit Tests - AgentToolRegistry
# =============================================================================


class TestAgentToolRegistryInit:
    """Test AgentToolRegistry initialization."""

    def test_init_with_all_dependencies(self, temp_workspace, mock_agent_pool, mock_agent_invoker, mock_agent_loader):
        """Test initialization with all dependencies."""
        reg = AgentToolRegistry(
            workspace_path=temp_workspace,
            agent_pool=mock_agent_pool,
            agent_invoker=mock_agent_invoker,
            agent_loader=mock_agent_loader,
        )

        assert reg.workspace_path == temp_workspace
        assert reg._agent_pool == mock_agent_pool
        assert reg._agent_invoker == mock_agent_invoker
        assert reg._agent_loader == mock_agent_loader

    def test_init_without_dependencies(self, temp_workspace):
        """Test initialization without dependencies (lazy init)."""
        reg = AgentToolRegistry(workspace_path=temp_workspace)

        assert reg.workspace_path == temp_workspace
        assert reg._agent_pool is None
        assert reg._agent_invoker is None
        assert reg._agent_loader is None

    def test_set_dependencies_later(self, temp_workspace, mock_agent_pool, mock_agent_invoker, mock_agent_loader):
        """Test setting dependencies after initialization."""
        reg = AgentToolRegistry(workspace_path=temp_workspace)

        reg.set_dependencies(
            agent_pool=mock_agent_pool, agent_invoker=mock_agent_invoker, agent_loader=mock_agent_loader
        )

        assert reg._agent_pool == mock_agent_pool
        assert reg._agent_invoker == mock_agent_invoker
        assert reg._agent_loader == mock_agent_loader


class TestAgentToolRegistryRefresh:
    """Test AgentToolRegistry refresh functionality."""

    def test_refresh_discovers_spawned_agents(self, registry):
        """Test that refresh discovers all spawned agents."""
        # Should have 2 spawned agents (security_expert, sql_specialist)
        tools = registry.list_agent_tools()
        assert len(tools) == 2

        tool_names = [t.tool_name for t in tools]
        assert "agent_security_expert" in tool_names
        assert "agent_sql_specialist" in tool_names

    def test_refresh_skips_core_agents(self, registry):
        """Test that refresh skips non-spawned agents."""
        tools = registry.list_agent_tools()
        tool_names = [t.tool_name for t in tools]

        # Should NOT include core agents
        assert "agent_gemini_primary" not in tool_names
        assert "agent_claude_opus" not in tool_names

    def test_refresh_returns_count(self, temp_workspace, mock_agent_pool, mock_agent_invoker, mock_agent_loader):
        """Test that refresh returns correct count."""
        reg = AgentToolRegistry(
            workspace_path=temp_workspace,
            agent_pool=mock_agent_pool,
            agent_invoker=mock_agent_invoker,
            agent_loader=mock_agent_loader,
        )

        count = reg.refresh()
        assert count == 2

    def test_refresh_with_no_pool_returns_zero(self, temp_workspace):
        """Test refresh with no agent pool."""
        reg = AgentToolRegistry(workspace_path=temp_workspace)
        count = reg.refresh()
        assert count == 0


class TestAgentToolDefinition:
    """Test tool definition creation."""

    def test_tool_definition_structure(self, registry):
        """Test that tool definitions have correct structure."""
        tool = registry.get_tool_definition("agent_security_expert")

        assert tool is not None
        assert tool.tool_name == "agent_security_expert"
        assert tool.agent_id == "security_expert"
        assert "security" in tool.description.lower() or "vulnerabilities" in tool.description.lower()
        assert "security" in tool.capabilities

    def test_tool_definition_to_dict(self, registry):
        """Test tool definition dictionary conversion."""
        tool = registry.get_tool_definition("agent_security_expert")
        tool_dict = tool.to_dict()

        assert "name" in tool_dict
        assert "description" in tool_dict
        assert "parameters" in tool_dict
        assert tool_dict["parameters"]["type"] == "object"
        assert "task" in tool_dict["parameters"]["properties"]


class TestAgentToolExecution:
    """Test agent tool execution."""

    def test_execute_valid_tool(self, registry, mock_agent_invoker):
        """Test executing a valid agent tool."""
        result = registry.execute_agent_tool("agent_security_expert", {"task": "Analyze this code for SQL injection"})

        assert result.success is True
        assert result.agent_id == "security_expert"
        assert result.output == "Task completed successfully."
        mock_agent_invoker.invoke_spawned_agent.assert_called_once()

    def test_execute_with_context(self, registry, mock_agent_invoker):
        """Test executing with additional context."""
        result = registry.execute_agent_tool(
            "agent_sql_specialist", {"task": "Optimize this query", "context": "SELECT * FROM users WHERE id = 1"}
        )

        assert result.success is True
        # Check that context was included in the call
        call_args = mock_agent_invoker.invoke_spawned_agent.call_args
        assert "Optimize this query" in call_args.kwargs.get(
            "context", call_args.args[2] if len(call_args.args) > 2 else ""
        )

    def test_execute_unknown_tool_fails(self, registry):
        """Test executing unknown tool fails gracefully."""
        result = registry.execute_agent_tool("agent_nonexistent", {"task": "Do something"})

        assert result.success is False
        assert "Unknown agent tool" in result.error

    def test_execute_without_task_fails(self, registry):
        """Test executing without task parameter fails."""
        result = registry.execute_agent_tool("agent_security_expert", {"context": "some context but no task"})

        assert result.success is False
        assert "task" in result.error.lower()

    def test_execute_without_invoker_fails(self, temp_workspace, mock_agent_pool, mock_agent_loader):
        """Test execution fails gracefully without invoker."""
        reg = AgentToolRegistry(
            workspace_path=temp_workspace,
            agent_pool=mock_agent_pool,
            agent_invoker=None,  # No invoker
            agent_loader=mock_agent_loader,
        )
        reg.refresh()

        result = reg.execute_agent_tool("agent_security_expert", {"task": "Analyze code"})

        assert result.success is False
        assert "not configured" in result.error.lower()

    def test_execute_handles_invoker_exception(self, registry, mock_agent_invoker):
        """Test that invoker exceptions are handled."""
        mock_agent_invoker.invoke_spawned_agent.side_effect = Exception("Network timeout")

        result = registry.execute_agent_tool("agent_security_expert", {"task": "Analyze code"})

        assert result.success is False
        assert "Network timeout" in result.error


class TestToolManagerIntegration:
    """Test integration with ToolManager."""

    def test_create_tool_handler(self, registry):
        """Test creating a ToolManager-compatible handler."""
        handler = registry.create_tool_handler("agent_security_expert")

        assert callable(handler)

    def test_is_agent_tool(self, registry):
        """Test checking if tool name is an agent tool."""
        assert registry.is_agent_tool("agent_security_expert") is True
        assert registry.is_agent_tool("agent_sql_specialist") is True
        assert registry.is_agent_tool("bash") is False
        assert registry.is_agent_tool("read") is False


class TestDomainFiltering:
    """Test domain-based tool filtering."""

    def test_get_tools_for_security_domain(self, registry):
        """Test getting tools for security domain."""
        tools = registry.get_tools_for_domain("security")

        assert len(tools) == 1
        assert tools[0].agent_id == "security_expert"

    def test_get_tools_for_database_domain(self, registry):
        """Test getting tools for database domain."""
        tools = registry.get_tools_for_domain("database")

        assert len(tools) == 1
        assert tools[0].agent_id == "sql_specialist"

    def test_get_tools_for_unknown_domain(self, registry):
        """Test getting tools for unknown domain returns empty."""
        tools = registry.get_tools_for_domain("quantum_computing")

        assert len(tools) == 0


class TestRegistrySummary:
    """Test registry summary functionality."""

    def test_get_summary(self, registry):
        """Test getting registry summary."""
        summary = registry.get_summary()

        assert summary["total_tools"] == 2
        assert len(summary["tools"]) == 2

        tool_ids = [t["agent_id"] for t in summary["tools"]]
        assert "security_expert" in tool_ids
        assert "sql_specialist" in tool_ids


# =============================================================================
# Stress Tests
# =============================================================================


class TestAgentToolStress:
    """Stress tests for concurrent agent tool operations."""

    def test_concurrent_tool_execution(self, registry, mock_agent_invoker):
        """Test concurrent tool executions."""
        import threading

        results = []
        errors = []

        def execute_tool(tool_name, task):
            try:
                result = registry.execute_agent_tool(tool_name, {"task": task})
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(10):
            tool_name = "agent_security_expert" if i % 2 == 0 else "agent_sql_specialist"
            t = threading.Thread(target=execute_tool, args=(tool_name, f"Task {i}"))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Errors during concurrent execution: {errors}"
        assert len(results) == 10
        assert all(r.success for r in results)

    def test_rapid_refresh_cycles(self, temp_workspace, mock_agent_pool, mock_agent_invoker, mock_agent_loader):
        """Test rapid refresh cycles don't cause issues."""
        reg = AgentToolRegistry(
            workspace_path=temp_workspace,
            agent_pool=mock_agent_pool,
            agent_invoker=mock_agent_invoker,
            agent_loader=mock_agent_loader,
        )

        for _ in range(50):
            count = reg.refresh()
            assert count == 2


# =============================================================================
# Agent Tool Result Tests
# =============================================================================


class TestAgentToolResult:
    """Test AgentToolResult dataclass."""

    def test_success_result(self):
        """Test successful result creation."""
        result = AgentToolResult(
            success=True, agent_id="security_expert", output="Found 3 vulnerabilities", duration_seconds=1.5
        )

        assert result.success is True
        assert result.error is None
        assert result.duration_seconds == 1.5

    def test_failure_result(self):
        """Test failure result creation."""
        result = AgentToolResult(success=False, agent_id="security_expert", output="", error="Connection timeout")

        assert result.success is False
        assert result.error == "Connection timeout"

    def test_result_to_dict(self):
        """Test result dictionary conversion."""
        result = AgentToolResult(
            success=True, agent_id="sql_specialist", output="Query optimized", duration_seconds=0.8
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["agent_id"] == "sql_specialist"
        assert result_dict["output"] == "Query optimized"
        assert result_dict["duration_seconds"] == 0.8


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
