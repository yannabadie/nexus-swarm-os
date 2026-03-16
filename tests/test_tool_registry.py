"""
Tests for core/execution/tool_registry.py - V9.5

Validates tool registration and discovery.
"""

import pytest

from core.execution_pkg.execution.handlers.base import ToolResult
from core.execution_pkg.execution.tool_registry import (
    ToolMetadata,
    ToolRegistry,
    get_tool_registry,
    reset_tool_registry,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset global registry before each test."""
    reset_tool_registry()
    yield
    reset_tool_registry()


class TestToolRegistry:
    """Basic ToolRegistry tests."""

    def test_create_registry(self):
        """Registry should be created empty."""
        registry = ToolRegistry()
        assert len(registry.list_tools()) == 0

    def test_normalize_name_alias(self):
        """Should normalize Gemini CLI aliases."""
        registry = ToolRegistry()
        assert registry.normalize_name("read_file") == "read"
        assert registry.normalize_name("write_file") == "write"
        assert registry.normalize_name("google_web_search") == "web_search"

    def test_normalize_name_passthrough(self):
        """Should pass through unknown names."""
        registry = ToolRegistry()
        assert registry.normalize_name("custom_tool") == "custom_tool"
        assert registry.normalize_name("read") == "read"


class TestToolRegistration:
    """Tool registration tests."""

    def test_register_tool(self):
        """Should register a tool handler."""
        registry = ToolRegistry()

        def dummy_handler(args):
            return ToolResult.ok("test", "output")

        registry.register("test_tool", dummy_handler)

        assert registry.has_tool("test_tool")
        assert registry.get_handler("test_tool") is not None

    def test_register_with_metadata(self):
        """Should store tool metadata."""
        registry = ToolRegistry()

        def handler(args):
            return ToolResult.ok("meta_test", "ok")

        registry.register(
            "meta_test",
            handler,
            description="Test tool",
            category="custom",
        )

        metadata = registry.get_metadata("meta_test")
        assert metadata is not None
        assert metadata.description == "Test tool"
        assert metadata.category == "custom"

    def test_unregister_tool(self):
        """Should unregister a tool."""
        registry = ToolRegistry()

        def handler(args):
            return ToolResult.ok("remove_test", "ok")

        registry.register("remove_test", handler)
        assert registry.has_tool("remove_test")

        result = registry.unregister("remove_test")
        assert result is True
        assert not registry.has_tool("remove_test")

    def test_unregister_nonexistent(self):
        """Should return False for nonexistent tool."""
        registry = ToolRegistry()
        result = registry.unregister("nonexistent")
        assert result is False


class TestToolListing:
    """Tool listing tests."""

    def test_list_all_tools(self):
        """Should list all registered tools."""
        registry = ToolRegistry()

        registry.register("tool1", lambda a: ToolResult.ok("t1", "ok"))
        registry.register("tool2", lambda a: ToolResult.ok("t2", "ok"))

        tools = registry.list_tools()
        assert "tool1" in tools
        assert "tool2" in tools

    def test_list_tools_by_category(self):
        """Should filter tools by category."""
        registry = ToolRegistry()

        registry.register("core_tool", lambda a: ToolResult.ok("c", "ok"), category="core")
        registry.register("custom_tool", lambda a: ToolResult.ok("x", "ok"), category="custom")

        core_tools = registry.list_tools(category="core")
        assert "core_tool" in core_tools
        assert "custom_tool" not in core_tools


class TestMCPTools:
    """MCP tool management tests."""

    def test_register_mcp_tool(self):
        """Should register MCP tool with server info."""
        registry = ToolRegistry()

        registry.register_mcp_tool(
            "mcp_test",
            lambda a: ToolResult.ok("mcp", "ok"),
            server_name="test_server",
        )

        assert registry.has_tool("mcp_test")
        assert registry.get_mcp_server("mcp_test") == "test_server"

    def test_list_mcp_tools(self):
        """Should list only MCP tools."""
        registry = ToolRegistry()

        registry.register("core_tool", lambda a: ToolResult.ok("c", "ok"), category="core")
        registry.register_mcp_tool("mcp_tool", lambda a: ToolResult.ok("m", "ok"), "server")

        mcp_tools = registry.list_mcp_tools()
        assert "mcp_tool" in mcp_tools
        assert "core_tool" not in mcp_tools


class TestDynamicTools:
    """Dynamic tool management tests."""

    def test_register_dynamic_tool(self):
        """Should register dynamic tool."""
        registry = ToolRegistry()

        registry.register_dynamic_tool(
            "dynamic_test",
            lambda a: ToolResult.ok("dyn", "ok"),
        )

        assert registry.has_tool("dynamic_test")
        assert registry.is_dynamic_tool("dynamic_test")

    def test_list_dynamic_tools(self):
        """Should list only dynamic tools."""
        registry = ToolRegistry()

        registry.register("core_tool", lambda a: ToolResult.ok("c", "ok"), category="core")
        registry.register_dynamic_tool("dyn_tool", lambda a: ToolResult.ok("d", "ok"))

        dyn_tools = registry.list_dynamic_tools()
        assert "dyn_tool" in dyn_tools
        assert "core_tool" not in dyn_tools


class TestGlobalRegistry:
    """Global singleton tests."""

    def test_singleton_instance(self):
        """get_tool_registry should return same instance."""
        registry1 = get_tool_registry()
        registry2 = get_tool_registry()
        assert registry1 is registry2

    def test_reset_creates_new(self):
        """reset_tool_registry should create new instance."""
        registry1 = get_tool_registry()
        reset_tool_registry()
        registry2 = get_tool_registry()
        assert registry1 is not registry2


class TestToolMetadata:
    """ToolMetadata dataclass tests."""

    def test_create_metadata(self):
        """Should create metadata with defaults."""
        meta = ToolMetadata(name="test")
        assert meta.name == "test"
        assert meta.description == ""
        assert meta.category == "core"
        assert meta.enabled is True

    def test_metadata_with_values(self):
        """Should create metadata with custom values."""
        meta = ToolMetadata(
            name="custom",
            description="Custom tool",
            category="mcp",
            enabled=False,
        )
        assert meta.name == "custom"
        assert meta.description == "Custom tool"
        assert meta.category == "mcp"
        assert meta.enabled is False


class TestRegistryExport:
    """Registry export tests."""

    def test_to_dict(self):
        """Should export registry state."""
        registry = ToolRegistry()

        registry.register("tool1", lambda a: ToolResult.ok("t", "ok"))
        registry.register_mcp_tool("mcp1", lambda a: ToolResult.ok("m", "ok"), "server")
        registry.register_dynamic_tool("dyn1", lambda a: ToolResult.ok("d", "ok"))

        export = registry.to_dict()

        assert "tools" in export
        assert "tool1" in export["tools"]
        assert "mcp_tools" in export
        assert "dyn1" in export["dynamic_tools"]
