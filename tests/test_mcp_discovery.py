"""
Tests for V12.4 MCP Tool Discovery and Auto-Registration.

Validates:
- DiscoveredTool dataclass (fields, properties, serialization)
- ToolDiscoveryResult aggregation (stats, filtering)
- Schema validation (well-formed, edge cases, errors)
- MCPToolDiscovery engine (mock servers, multi-server, failures)
- Registry integration (discover_all_tools, discover_server_tools)
- ToolRegistry schema passthrough (register_mcp_tool with schema)
- Module exports
"""

from datetime import datetime
from unittest.mock import MagicMock

from core.interface_pkg.mcp.discovery import (
    DiscoveredTool,
    MCPToolDiscovery,
    ServerDiscoveryStatus,
    ToolDiscoveryResult,
    validate_input_schema,
)
from core.interface_pkg.mcp.protocol import MCPTool, MCPToolInputSchema

# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestValidateInputSchema:
    """Test schema validation function."""

    def test_none_schema_is_valid(self):
        """No schema means no constraints - valid."""
        errors = validate_input_schema(None)
        assert errors == []

    def test_valid_object_schema(self):
        """Standard object schema should pass."""
        schema = MCPToolInputSchema(
            type="object",
            properties={"path": {"type": "string", "description": "File path"}},
            required=["path"],
        )
        errors = validate_input_schema(schema)
        assert errors == []

    def test_empty_properties_valid(self):
        """Object with no properties is valid (no-arg tool)."""
        schema = MCPToolInputSchema(type="object", properties={}, required=[])
        errors = validate_input_schema(schema)
        assert errors == []

    def test_wrong_root_type(self):
        """Root type must be 'object'."""
        schema = MCPToolInputSchema(type="string", properties={}, required=[])
        errors = validate_input_schema(schema)
        assert any("Root type" in e for e in errors)

    def test_required_field_not_in_properties(self):
        """Required field must exist in properties."""
        schema = MCPToolInputSchema(
            type="object",
            properties={"a": {"type": "string"}},
            required=["a", "b"],
        )
        errors = validate_input_schema(schema)
        assert any("'b' not in properties" in e for e in errors)
        assert len(errors) == 1  # Only 'b' is missing, 'a' exists

    def test_invalid_property_type(self):
        """Property with unknown type string should fail."""
        schema = MCPToolInputSchema(
            type="object",
            properties={"x": {"type": "foobar"}},
            required=[],
        )
        errors = validate_input_schema(schema)
        assert any("invalid type" in e for e in errors)

    def test_valid_property_types(self):
        """All standard JSON Schema types should pass."""
        props = {
            "s": {"type": "string"},
            "n": {"type": "number"},
            "i": {"type": "integer"},
            "b": {"type": "boolean"},
            "a": {"type": "array"},
            "o": {"type": "object"},
            "nil": {"type": "null"},
        }
        schema = MCPToolInputSchema(type="object", properties=props, required=[])
        errors = validate_input_schema(schema)
        assert errors == []

    def test_property_without_type_is_valid(self):
        """Property without explicit type is valid (any type)."""
        schema = MCPToolInputSchema(
            type="object",
            properties={"x": {"description": "no type specified"}},
            required=[],
        )
        errors = validate_input_schema(schema)
        assert errors == []

    def test_multiple_errors(self):
        """Should collect all errors, not just first."""
        schema = MCPToolInputSchema(
            type="array",  # error 1: wrong root type
            properties={"x": {"type": "badtype"}},  # error 2: invalid type
            required=["missing"],  # error 3: missing field
        )
        errors = validate_input_schema(schema)
        assert len(errors) == 3


# =============================================================================
# DiscoveredTool Tests
# =============================================================================


class TestDiscoveredTool:
    """Test DiscoveredTool dataclass."""

    def test_basic_creation(self):
        tool = DiscoveredTool(
            server_name="filesystem",
            tool_name="read_file",
            qualified_name="mcp_filesystem_read_file",
            description="Read a file",
        )
        assert tool.server_name == "filesystem"
        assert tool.tool_name == "read_file"
        assert tool.qualified_name == "mcp_filesystem_read_file"
        assert tool.schema_valid is True

    def test_auto_timestamp(self):
        """Should auto-set discovered_at."""
        tool = DiscoveredTool(server_name="s", tool_name="t", qualified_name="mcp_s_t")
        assert tool.discovered_at != ""
        # Should be ISO format
        datetime.fromisoformat(tool.discovered_at)

    def test_has_schema_false(self):
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
            input_schema=None,
        )
        assert tool.has_schema is False

    def test_has_schema_true(self):
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
            input_schema={"type": "object", "properties": {"a": {"type": "string"}}},
        )
        assert tool.has_schema is True

    def test_has_schema_empty_dict(self):
        """Empty dict should be falsy."""
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
            input_schema={},
        )
        assert tool.has_schema is False

    def test_required_params(self):
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
            input_schema={
                "type": "object",
                "properties": {"a": {}, "b": {}},
                "required": ["a"],
            },
        )
        assert tool.required_params == ["a"]

    def test_param_names(self):
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
            input_schema={
                "type": "object",
                "properties": {"path": {}, "encoding": {}},
            },
        )
        assert set(tool.param_names) == {"path", "encoding"}

    def test_param_names_no_schema(self):
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
        )
        assert tool.param_names == []

    def test_to_dict(self):
        tool = DiscoveredTool(
            server_name="fs",
            tool_name="read",
            qualified_name="mcp_fs_read",
            description="Read file",
            schema_valid=True,
        )
        d = tool.to_dict()
        assert d["server_name"] == "fs"
        assert d["tool_name"] == "read"
        assert d["qualified_name"] == "mcp_fs_read"
        assert d["description"] == "Read file"
        assert d["schema_valid"] is True

    def test_schema_errors_stored(self):
        tool = DiscoveredTool(
            server_name="s",
            tool_name="t",
            qualified_name="mcp_s_t",
            schema_valid=False,
            schema_errors=["Root type must be 'object'"],
        )
        assert not tool.schema_valid
        assert len(tool.schema_errors) == 1


# =============================================================================
# ToolDiscoveryResult Tests
# =============================================================================


class TestToolDiscoveryResult:
    """Test aggregated discovery results."""

    def _make_tools(self, count: int, valid: int = None) -> list:
        """Create a list of discovered tools."""
        if valid is None:
            valid = count
        tools = []
        for i in range(count):
            tools.append(
                DiscoveredTool(
                    server_name=f"server_{i % 2}",
                    tool_name=f"tool_{i}",
                    qualified_name=f"mcp_server_{i % 2}_tool_{i}",
                    schema_valid=(i < valid),
                )
            )
        return tools

    def test_empty_result(self):
        result = ToolDiscoveryResult()
        assert result.total_tools == 0
        assert result.valid_tools == 0
        assert result.invalid_tools == 0
        assert result.servers_contacted == 0
        assert result.servers_failed == 0

    def test_tool_counts(self):
        result = ToolDiscoveryResult(tools=self._make_tools(5, valid=3))
        assert result.total_tools == 5
        assert result.valid_tools == 3
        assert result.invalid_tools == 2

    def test_server_counts(self):
        result = ToolDiscoveryResult(
            server_statuses=[
                ServerDiscoveryStatus("a", success=True, tool_count=3),
                ServerDiscoveryStatus("b", success=True, tool_count=2),
                ServerDiscoveryStatus("c", success=False, error="timeout"),
            ]
        )
        assert result.servers_contacted == 2
        assert result.servers_failed == 1

    def test_get_tools_by_server(self):
        tools = self._make_tools(4)
        result = ToolDiscoveryResult(tools=tools)
        s0_tools = result.get_tools_by_server("server_0")
        s1_tools = result.get_tools_by_server("server_1")
        assert len(s0_tools) == 2
        assert len(s1_tools) == 2

    def test_get_invalid_tools(self):
        tools = self._make_tools(5, valid=3)
        result = ToolDiscoveryResult(tools=tools)
        invalid = result.get_invalid_tools()
        assert len(invalid) == 2
        assert all(not t.schema_valid for t in invalid)

    def test_to_dict(self):
        result = ToolDiscoveryResult(
            tools=self._make_tools(2),
            server_statuses=[ServerDiscoveryStatus("s", True, 2)],
        )
        d = result.to_dict()
        assert d["total_tools"] == 2
        assert d["valid_tools"] == 2
        assert len(d["tools"]) == 2
        assert len(d["server_statuses"]) == 1

    def test_auto_timestamp(self):
        result = ToolDiscoveryResult()
        assert result.discovered_at != ""


# =============================================================================
# MCPToolDiscovery Engine Tests
# =============================================================================


def _make_mock_registry(servers: dict) -> MagicMock:
    """
    Create a mock MCPRegistry.

    Args:
        servers: Dict of server_name -> list of (tool_name, description, schema_dict|None)
    """
    registry = MagicMock()

    # Build server configs
    configs = []
    for name in servers:
        cfg = MagicMock()
        cfg.name = name
        cfg.enabled = True
        configs.append(cfg)

    registry.get_servers.return_value = configs

    def mock_get_client(server_name):
        if server_name not in servers:
            return None
        client = MagicMock()
        client._state = MagicMock()
        client._state.server_info = {"serverInfo": {"version": "1.0.0"}}

        tools_data = servers[server_name]
        mcp_tools = []
        for tool_name, desc, schema_dict in tools_data:
            tool = MCPTool(
                name=tool_name,
                description=desc,
                inputSchema=MCPToolInputSchema.from_dict(schema_dict) if schema_dict else None,
            )
            mcp_tools.append(tool)

        client.list_tools.return_value = mcp_tools
        return client

    registry.get_client.side_effect = mock_get_client
    return registry


class TestMCPToolDiscovery:
    """Test discovery engine with mock servers."""

    def test_discover_empty_registry(self):
        """No servers configured."""
        registry = MagicMock()
        registry.get_servers.return_value = []
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()
        assert result.total_tools == 0

    def test_discover_single_server(self):
        """Single server with tools."""
        registry = _make_mock_registry(
            {
                "filesystem": [
                    (
                        "read_file",
                        "Read a file",
                        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                    ),
                    (
                        "write_file",
                        "Write a file",
                        {
                            "type": "object",
                            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["path", "content"],
                        },
                    ),
                ]
            }
        )
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.total_tools == 2
        assert result.servers_contacted == 1
        assert result.valid_tools == 2

        names = [t.qualified_name for t in result.tools]
        assert "mcp_filesystem_read_file" in names
        assert "mcp_filesystem_write_file" in names

    def test_discover_multiple_servers(self):
        """Multiple servers with tools."""
        registry = _make_mock_registry(
            {
                "filesystem": [
                    ("read_file", "Read", {"type": "object", "properties": {}, "required": []}),
                ],
                "github": [
                    (
                        "list_repos",
                        "List repos",
                        {"type": "object", "properties": {"org": {"type": "string"}}, "required": []},
                    ),
                    (
                        "get_issue",
                        "Get issue",
                        {"type": "object", "properties": {"number": {"type": "integer"}}, "required": ["number"]},
                    ),
                ],
            }
        )
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.total_tools == 3
        assert result.servers_contacted == 2
        fs_tools = result.get_tools_by_server("filesystem")
        gh_tools = result.get_tools_by_server("github")
        assert len(fs_tools) == 1
        assert len(gh_tools) == 2

    def test_discover_server_failure(self):
        """Server that fails to connect."""
        registry = MagicMock()
        cfg = MagicMock()
        cfg.name = "broken"
        cfg.enabled = True
        registry.get_servers.return_value = [cfg]
        registry.get_client.return_value = None

        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.total_tools == 0
        assert result.servers_failed == 1
        assert result.server_statuses[0].error == "Could not connect to server"

    def test_discover_server_exception(self):
        """Server that raises exception."""
        registry = MagicMock()
        cfg = MagicMock()
        cfg.name = "exploder"
        cfg.enabled = True
        registry.get_servers.return_value = [cfg]
        registry.get_client.side_effect = RuntimeError("Connection refused")

        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.total_tools == 0
        assert result.servers_failed == 1
        assert "Connection refused" in result.server_statuses[0].error

    def test_schema_validation_errors_recorded(self):
        """Tools with invalid schemas should be flagged."""
        registry = _make_mock_registry(
            {
                "bad_server": [
                    ("bad_tool", "Bad schema", {"type": "string", "properties": {}, "required": ["missing"]}),
                ]
            }
        )
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.total_tools == 1
        assert result.invalid_tools == 1
        tool = result.tools[0]
        assert not tool.schema_valid
        assert len(tool.schema_errors) > 0

    def test_skip_schema_validation(self):
        """Should skip validation when disabled."""
        registry = _make_mock_registry(
            {
                "server": [
                    ("tool", "desc", {"type": "string", "properties": {}, "required": ["x"]}),
                ]
            }
        )
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all(validate_schemas=False)

        assert result.total_tools == 1
        assert result.valid_tools == 1  # Not validated = assumed valid

    def test_tool_without_schema(self):
        """Tool with no input schema should be valid."""
        registry = _make_mock_registry({"server": [("no_args_tool", "No args", None)]})
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.total_tools == 1
        assert result.valid_tools == 1
        assert not result.tools[0].has_schema

    def test_server_version_captured(self):
        """Should capture server version from init result."""
        registry = _make_mock_registry({"versioned": [("t", "d", None)]})
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        assert result.tools[0].server_version == "1.0.0"
        assert result.server_statuses[0].server_version == "1.0.0"

    def test_discover_single_server_method(self):
        """Test discover_server() for a specific server."""
        registry = _make_mock_registry(
            {
                "fs": [("read", "Read", None), ("write", "Write", None)],
                "git": [("commit", "Commit", None)],
            }
        )
        discovery = MCPToolDiscovery(registry)
        tools = discovery.discover_server("fs")

        assert len(tools) == 2
        assert all(t.server_name == "fs" for t in tools)

    def test_disabled_servers_skipped(self):
        """Disabled servers should not be queried."""
        registry = MagicMock()
        enabled = MagicMock()
        enabled.name = "active"
        enabled.enabled = True
        disabled = MagicMock()
        disabled.name = "inactive"
        disabled.enabled = False
        registry.get_servers.return_value = [enabled, disabled]

        client = MagicMock()
        client._state = MagicMock()
        client._state.server_info = {}
        client.list_tools.return_value = []
        registry.get_client.return_value = client

        discovery = MCPToolDiscovery(registry)
        discovery.discover_all()

        # Only the enabled server should have been contacted
        registry.get_client.assert_called_once_with("active")


# =============================================================================
# Registry Integration Tests
# =============================================================================


class TestRegistryDiscovery:
    """Test MCPRegistry.discover_all_tools() and discover_server_tools()."""

    def test_discover_all_tools_method_exists(self):
        """Registry should have discover_all_tools method."""
        from core.interface_pkg.mcp.registry import MCPRegistry

        assert hasattr(MCPRegistry, "discover_all_tools")

    def test_discover_server_tools_method_exists(self):
        """Registry should have discover_server_tools method."""
        from core.interface_pkg.mcp.registry import MCPRegistry

        assert hasattr(MCPRegistry, "discover_server_tools")

    def test_discover_all_tools_returns_result(self, tmp_path):
        """Should return ToolDiscoveryResult."""
        from core.interface_pkg.mcp.registry import MCPRegistry

        registry = MCPRegistry(tmp_path)
        result = registry.discover_all_tools()
        assert isinstance(result, ToolDiscoveryResult)
        assert result.total_tools == 0  # No servers configured

    def test_discover_server_tools_returns_list(self, tmp_path):
        """Should return list."""
        from core.interface_pkg.mcp.registry import MCPRegistry

        registry = MCPRegistry(tmp_path)
        tools = registry.discover_server_tools("nonexistent")
        assert isinstance(tools, list)


# =============================================================================
# ToolRegistry Schema Passthrough Tests
# =============================================================================


class TestToolRegistrySchemaPassthrough:
    """Test that register_mcp_tool now accepts and stores schemas."""

    def test_register_mcp_tool_with_schema(self):
        """Schema should be stored in tool metadata."""
        from core.execution_pkg.execution.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        registry.register_mcp_tool(
            name="mcp_fs_read",
            handler=lambda args: None,
            server_name="fs",
            description="Read file",
            schema=schema,
        )

        meta = registry.get_metadata("mcp_fs_read")
        assert meta is not None
        assert meta.schema == schema
        assert meta.category == "mcp"

    def test_register_mcp_tool_without_schema(self):
        """Should still work without schema (backward compat)."""
        from core.execution_pkg.execution.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register_mcp_tool(
            name="mcp_fs_write",
            handler=lambda args: None,
            server_name="fs",
        )

        meta = registry.get_metadata("mcp_fs_write")
        assert meta is not None
        assert meta.schema == {}

    def test_mcp_server_tracked(self):
        """Server name should be tracked."""
        from core.execution_pkg.execution.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register_mcp_tool(
            name="mcp_github_list",
            handler=lambda args: None,
            server_name="github",
        )
        assert registry.get_mcp_server("mcp_github_list") == "github"


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that new types are importable."""

    def test_discovery_from_mcp_package(self):
        from core.interface_pkg.mcp import MCPToolDiscovery

        assert MCPToolDiscovery is not None

    def test_discovered_tool_from_mcp_package(self):
        from core.interface_pkg.mcp import DiscoveredTool

        assert DiscoveredTool is not None

    def test_discovery_result_from_mcp_package(self):
        from core.interface_pkg.mcp import ToolDiscoveryResult

        assert ToolDiscoveryResult is not None

    def test_validate_input_schema_from_mcp_package(self):
        from core.interface_pkg.mcp import validate_input_schema

        assert callable(validate_input_schema)

    def test_discovery_from_discovery_module(self):
        from core.interface_pkg.mcp.discovery import (
            DiscoveredTool,
            MCPToolDiscovery,
            ServerDiscoveryStatus,
            ToolDiscoveryResult,
            validate_input_schema,
        )

        assert all(
            [
                MCPToolDiscovery,
                DiscoveredTool,
                ToolDiscoveryResult,
                ServerDiscoveryStatus,
                validate_input_schema,
            ]
        )
