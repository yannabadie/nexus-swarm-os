"""
Tests for Phase 12.3: MCP Client (CORTEX)

Verifies:
1. Protocol types serialization/deserialization
2. MCPClient lifecycle (start, initialize, close)
3. Tool listing and execution
4. Error handling
5. Registry configuration
6. ToolManager integration
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.interface_pkg.mcp.client import (
    MCPClient,
    MCPClientError,
    MCPConnectionError,
)
from core.interface_pkg.mcp.protocol import (
    MCPRequest,
    MCPResponse,
    MCPTool,
    MCPToolResult,
)
from core.interface_pkg.mcp.registry import (
    MCPRegistry,
    MCPServerConfig,
    create_default_config,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_server_command():
    """Command to run the mock MCP server."""
    mock_server_path = Path(__file__).parent / "fixtures" / "mock_mcp_server.py"
    return [sys.executable, str(mock_server_path)]


@pytest.fixture
def mcp_client(mock_server_command):
    """Create and cleanup an MCP client."""
    client = MCPClient(command=mock_server_command)
    yield client
    client.close()


@pytest.fixture
def initialized_client(mock_server_command):
    """Create an initialized MCP client."""
    client = MCPClient(command=mock_server_command)
    client.start()
    client.initialize()
    yield client
    client.close()


@pytest.fixture
def registry_workspace(tmp_path):
    """Create a workspace with MCP configuration."""
    # Create config directory
    config_dir = tmp_path / ".nexus"
    config_dir.mkdir()

    # Create mock server config
    mock_server_path = Path(__file__).parent / "fixtures" / "mock_mcp_server.py"
    config = {
        "servers": {
            "mock": {
                "command": [sys.executable, str(mock_server_path)],
                "enabled": True,
                "description": "Mock MCP server for testing",
            },
            "disabled": {"command": ["echo", "disabled"], "enabled": False, "description": "Disabled server"},
        }
    }

    config_file = config_dir / "mcp_servers.json"
    config_file.write_text(json.dumps(config))

    return tmp_path


# =============================================================================
# Protocol Tests
# =============================================================================


class TestMCPRequest:
    """Tests for MCPRequest."""

    def test_create_request(self):
        """Can create a request."""
        req = MCPRequest(method="tools/list", id=1)
        assert req.method == "tools/list"
        assert req.id == 1
        assert req.jsonrpc == "2.0"

    def test_request_with_params(self):
        """Request with params."""
        req = MCPRequest(method="tools/call", id=2, params={"name": "echo", "arguments": {"message": "hello"}})
        assert req.params["name"] == "echo"

    def test_to_json(self):
        """Serialize to JSON."""
        req = MCPRequest(method="initialize", id=1, params={"foo": "bar"})
        json_str = req.to_json()
        parsed = json.loads(json_str)

        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "initialize"
        assert parsed["id"] == 1
        assert parsed["params"]["foo"] == "bar"

    def test_from_dict(self):
        """Deserialize from dict."""
        data = {"jsonrpc": "2.0", "method": "shutdown", "id": 99, "params": {}}
        req = MCPRequest.from_dict(data)
        assert req.method == "shutdown"
        assert req.id == 99


class TestMCPResponse:
    """Tests for MCPResponse."""

    def test_success_response(self):
        """Parse success response."""
        data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        resp = MCPResponse.from_dict(data)

        assert resp.is_success
        assert not resp.is_error
        assert resp.result["tools"] == []

    def test_error_response(self):
        """Parse error response."""
        data = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
        resp = MCPResponse.from_dict(data)

        assert resp.is_error
        assert not resp.is_success
        assert resp.error.code == -32601
        assert resp.error.message == "Method not found"

    def test_from_json(self):
        """Parse from JSON string."""
        json_str = '{"jsonrpc":"2.0","id":1,"result":{"status":"ok"}}'
        resp = MCPResponse.from_json(json_str)
        assert resp.result["status"] == "ok"


class TestMCPTool:
    """Tests for MCPTool."""

    def test_from_dict(self):
        """Parse tool definition."""
        data = {
            "name": "read_file",
            "description": "Read a file",
            "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "read_file"
        assert tool.description == "Read a file"
        assert tool.inputSchema is not None
        assert "path" in tool.inputSchema.properties

    def test_to_dict(self):
        """Serialize tool definition."""
        from core.interface_pkg.mcp.protocol import MCPToolInputSchema

        tool = MCPTool(
            name="echo",
            description="Echo message",
            inputSchema=MCPToolInputSchema(properties={"message": {"type": "string"}}, required=["message"]),
        )
        data = tool.to_dict()

        assert data["name"] == "echo"
        assert "inputSchema" in data


class TestMCPToolResult:
    """Tests for MCPToolResult."""

    def test_success_result(self):
        """Parse success result."""
        data = {"content": [{"type": "text", "text": "Hello, world!"}], "isError": False}
        result = MCPToolResult.from_dict(data)

        assert not result.isError
        assert result.text == "Hello, world!"

    def test_error_result(self):
        """Parse error result."""
        data = {"content": [{"type": "text", "text": "Something went wrong"}], "isError": True}
        result = MCPToolResult.from_dict(data)

        assert result.isError
        assert "went wrong" in result.text

    def test_multiple_content(self):
        """Multiple content items."""
        data = {"content": [{"type": "text", "text": "Line 1"}, {"type": "text", "text": "Line 2"}], "isError": False}
        result = MCPToolResult.from_dict(data)

        assert result.text == "Line 1\nLine 2"


# =============================================================================
# Client Lifecycle Tests
# =============================================================================


class TestMCPClientLifecycle:
    """Tests for MCPClient lifecycle."""

    def test_start_and_close(self, mcp_client):
        """Can start and close client."""
        mcp_client.start()
        assert mcp_client.is_connected
        assert not mcp_client.is_initialized

        mcp_client.close()
        assert not mcp_client.is_connected

    def test_initialize(self, mcp_client):
        """Can initialize client."""
        mcp_client.start()
        result = mcp_client.initialize()

        assert mcp_client.is_initialized
        assert result.serverInfo is not None
        assert result.serverInfo.name == "mock-mcp-server"

    def test_context_manager(self, mock_server_command):
        """Context manager starts and initializes."""
        with MCPClient(command=mock_server_command) as client:
            assert client.is_connected
            assert client.is_initialized

        assert not client.is_connected

    def test_connection_error_invalid_command(self):
        """Connection error for invalid command."""
        client = MCPClient(command=["nonexistent_command_xyz"])
        with pytest.raises(MCPConnectionError):
            client.start()


# =============================================================================
# Tool Operation Tests
# =============================================================================


class TestMCPClientTools:
    """Tests for MCPClient tool operations."""

    def test_list_tools(self, initialized_client):
        """Can list tools."""
        tools = initialized_client.list_tools()

        assert len(tools) >= 2
        tool_names = [t.name for t in tools]
        assert "echo" in tool_names
        assert "add" in tool_names

    def test_call_echo_tool(self, initialized_client):
        """Can call echo tool."""
        result = initialized_client.call_tool("echo", {"message": "Hello MCP!"})

        assert not result.isError
        assert "Hello MCP!" in result.text

    def test_call_add_tool(self, initialized_client):
        """Can call add tool."""
        result = initialized_client.call_tool("add", {"a": 5, "b": 3})

        assert not result.isError
        assert result.text == "8"

    def test_call_failing_tool(self, initialized_client):
        """Failing tool returns error result."""
        result = initialized_client.call_tool("fail", {})

        assert result.isError

    def test_get_tool(self, initialized_client):
        """Can get specific tool."""
        tool = initialized_client.get_tool("echo")

        assert tool is not None
        assert tool.name == "echo"
        assert "message" in tool.description.lower() or tool.inputSchema is not None

    def test_get_nonexistent_tool(self, initialized_client):
        """Returns None for nonexistent tool."""
        tool = initialized_client.get_tool("nonexistent")
        assert tool is None


# =============================================================================
# Registry Tests
# =============================================================================


class TestMCPRegistry:
    """Tests for MCPRegistry."""

    def test_load_config(self, registry_workspace):
        """Can load configuration."""
        registry = MCPRegistry(registry_workspace)
        servers = registry.get_servers()

        assert len(servers) == 1  # Only enabled
        assert servers[0].name == "mock"

    def test_get_all_servers(self, registry_workspace):
        """Can get all servers including disabled."""
        registry = MCPRegistry(registry_workspace)
        servers = registry.get_servers(include_disabled=True)

        assert len(servers) == 2

    def test_get_server_by_name(self, registry_workspace):
        """Can get server by name."""
        registry = MCPRegistry(registry_workspace)
        server = registry.get_server("mock")

        assert server is not None
        assert server.name == "mock"
        assert server.enabled

    def test_create_client(self, registry_workspace):
        """Can create client from config."""
        registry = MCPRegistry(registry_workspace)
        client = registry.create_client("mock", auto_initialize=True)

        try:
            assert client is not None
            assert client.is_initialized
        finally:
            client.close()

    def test_get_client_cached(self, registry_workspace):
        """get_client returns cached client."""
        registry = MCPRegistry(registry_workspace)

        client1 = registry.get_client("mock")
        client2 = registry.get_client("mock")

        try:
            assert client1 is client2
        finally:
            registry.close_all()

    def test_empty_config(self, tmp_path):
        """Works with no config file."""
        registry = MCPRegistry(tmp_path)
        servers = registry.get_servers()

        assert len(servers) == 0

    def test_create_default_config(self, tmp_path):
        """Can create default config."""
        config_path = create_default_config(tmp_path)

        assert config_path.exists()
        with open(config_path) as f:
            config = json.load(f)
        assert "servers" in config


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""

    def test_from_dict(self):
        """Can create from dict."""
        data = {
            "name": "test",
            "command": ["python", "server.py"],
            "env": {"DEBUG": "1"},
            "enabled": True,
            "description": "Test server",
            "args": ["--port", "8080"],
        }
        config = MCPServerConfig.from_dict(data)

        assert config.name == "test"
        assert config.command == ["python", "server.py"]
        assert config.env["DEBUG"] == "1"
        assert config.args == ["--port", "8080"]

    def test_full_command(self):
        """full_command includes args."""
        config = MCPServerConfig(name="test", command=["python", "server.py"], args=["--verbose"])

        assert config.full_command == ["python", "server.py", "--verbose"]


# =============================================================================
# Integration Tests
# =============================================================================


class TestToolManagerMCPIntegration:
    """Tests for ToolManager MCP integration."""

    def test_mcp_tools_loaded(self, registry_workspace):
        """MCP tools are loaded into ToolManager."""
        from core.execution_pkg.execution.tool_manager import ToolManager

        manager = ToolManager(workspace_path=registry_workspace)

        # Check MCP tools were registered
        mcp_tools = manager.get_mcp_tools()
        assert len(mcp_tools) >= 2

        # Should have mock server tools
        assert any("mcp_mock_echo" in t for t in mcp_tools)
        assert any("mcp_mock_add" in t for t in mcp_tools)

        # Cleanup
        manager.close_mcp()

    def test_execute_mcp_tool(self, registry_workspace):
        """Can execute MCP tool via ToolManager."""
        from dataclasses import dataclass

        from core.execution_pkg.execution.tool_manager import ToolManager

        @dataclass
        class MockToolRequest:
            tool_name: str
            arguments: dict[str, Any]

        manager = ToolManager(workspace_path=registry_workspace)

        try:
            # Execute echo tool
            request = MockToolRequest(tool_name="mcp_mock_echo", arguments={"message": "Integration test!"})
            result = manager.execute(request)

            assert result.status == "SUCCESS"
            assert "Integration test!" in result.output

            # Execute add tool
            request = MockToolRequest(tool_name="mcp_mock_add", arguments={"a": 10, "b": 20})
            result = manager.execute(request)

            assert result.status == "SUCCESS"
            assert result.output == "30"

        finally:
            manager.close_mcp()

    def test_reload_mcp_tools(self, registry_workspace):
        """Can reload MCP tools."""
        from core.execution_pkg.execution.tool_manager import ToolManager

        manager = ToolManager(workspace_path=registry_workspace)

        try:
            original_count = len(manager.get_mcp_tools())
            assert original_count > 0

            # Reload
            new_count = manager.reload_mcp_tools()
            assert new_count == original_count

        finally:
            manager.close_mcp()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestMCPErrorHandling:
    """Tests for error handling."""

    def test_uninitialized_call(self, mcp_client):
        """Error when calling before initialize."""
        mcp_client.start()

        with pytest.raises(MCPClientError, match="not initialized"):
            mcp_client.list_tools()

    def test_unknown_method(self, initialized_client):
        """Server returns error for unknown method."""
        response = initialized_client._send_request("unknown/method", {})

        assert response.is_error
        assert response.error.code == -32601  # Method not found


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
