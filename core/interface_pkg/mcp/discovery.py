"""
MCP Tool Discovery - Unified tool discovery across MCP servers.

V12.4 COGNITIVE BOOST - Task #24

Provides:
- DiscoveredTool: Structured representation of a discovered MCP tool
- ToolDiscoveryResult: Aggregated results from a discovery run
- MCPToolDiscovery: Discovers and validates tools across all configured servers

Usage:
    from core.interface_pkg.interface_pkg.mcp.discovery import MCPToolDiscovery

    discovery = MCPToolDiscovery(registry)
    result = discovery.discover_all()

    for tool in result.tools:
        print(f"{tool.qualified_name}: {tool.description} (valid={tool.schema_valid})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .protocol import MCPTool, MCPToolInputSchema

_logger = logging.getLogger(__name__)


# =============================================================================
# Schema Validation
# =============================================================================

_VALID_JSON_SCHEMA_TYPES = {"object", "string", "number", "integer", "boolean", "array", "null"}


def validate_input_schema(schema: MCPToolInputSchema | None) -> list[str]:
    """
    Validate an MCP tool input schema for well-formedness.

    Checks:
    - Root type must be "object"
    - Properties must be a dict
    - Required fields must reference existing properties
    - Property definitions must be dicts with valid types

    Args:
        schema: MCPToolInputSchema to validate

    Returns:
        List of validation error strings (empty = valid)
    """
    if schema is None:
        return []  # No schema = no constraints = valid

    errors: list[str] = []

    # Root type must be "object" for tool input
    if schema.type != "object":
        errors.append(f"Root type must be 'object', got '{schema.type}'")

    # Properties must be a dict
    if not isinstance(schema.properties, dict):
        errors.append(f"Properties must be a dict, got {type(schema.properties).__name__}")
        return errors  # Can't validate further

    # Required must reference existing properties
    for req_field in schema.required:
        if req_field not in schema.properties:
            errors.append(f"Required field '{req_field}' not in properties")

    # Each property must be a dict with a type
    for prop_name, prop_def in schema.properties.items():
        if not isinstance(prop_def, dict):
            errors.append(f"Property '{prop_name}' must be a dict")
            continue
        prop_type = prop_def.get("type")
        if prop_type and prop_type not in _VALID_JSON_SCHEMA_TYPES:
            errors.append(f"Property '{prop_name}' has invalid type '{prop_type}'")

    return errors


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class DiscoveredTool:
    """
    A discovered MCP tool with server context and validation status.

    Attributes:
        server_name: Name of the MCP server providing this tool
        tool_name: Original tool name on the server
        qualified_name: NEXUS-qualified name (mcp_{server}_{tool})
        description: Tool description from server
        input_schema: Input parameter schema (if provided)
        schema_valid: Whether the input schema passed validation
        schema_errors: List of schema validation errors
        server_version: Server version (if known)
        discovered_at: Timestamp of discovery
    """

    server_name: str
    tool_name: str
    qualified_name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None
    schema_valid: bool = True
    schema_errors: list[str] = field(default_factory=list)
    server_version: str = ""
    discovered_at: str = ""

    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(UTC).isoformat()

    @property
    def has_schema(self) -> bool:
        """Whether this tool has an input schema."""
        return self.input_schema is not None and len(self.input_schema) > 0

    @property
    def required_params(self) -> list[str]:
        """Get list of required parameter names."""
        if self.input_schema is None:
            return []
        return self.input_schema.get("required", [])

    @property
    def param_names(self) -> list[str]:
        """Get list of all parameter names."""
        if self.input_schema is None:
            return []
        return list(self.input_schema.get("properties", {}).keys())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "schema_valid": self.schema_valid,
            "schema_errors": self.schema_errors,
            "server_version": self.server_version,
            "discovered_at": self.discovered_at,
        }


@dataclass
class ServerDiscoveryStatus:
    """Status of discovery for a single server."""

    server_name: str
    success: bool
    tool_count: int = 0
    error: str = ""
    server_version: str = ""


@dataclass
class ToolDiscoveryResult:
    """
    Aggregated results from a tool discovery run.

    Attributes:
        tools: All discovered tools
        server_statuses: Per-server discovery status
        total_tools: Total number of tools discovered
        valid_tools: Number of tools with valid schemas
        invalid_tools: Number of tools with schema errors
        servers_contacted: Number of servers successfully contacted
        servers_failed: Number of servers that failed
        discovered_at: Timestamp of discovery run
    """

    tools: list[DiscoveredTool] = field(default_factory=list)
    server_statuses: list[ServerDiscoveryStatus] = field(default_factory=list)
    discovered_at: str = ""

    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(UTC).isoformat()

    @property
    def total_tools(self) -> int:
        return len(self.tools)

    @property
    def valid_tools(self) -> int:
        return sum(1 for t in self.tools if t.schema_valid)

    @property
    def invalid_tools(self) -> int:
        return sum(1 for t in self.tools if not t.schema_valid)

    @property
    def servers_contacted(self) -> int:
        return sum(1 for s in self.server_statuses if s.success)

    @property
    def servers_failed(self) -> int:
        return sum(1 for s in self.server_statuses if not s.success)

    def get_tools_by_server(self, server_name: str) -> list[DiscoveredTool]:
        """Get tools discovered from a specific server."""
        return [t for t in self.tools if t.server_name == server_name]

    def get_invalid_tools(self) -> list[DiscoveredTool]:
        """Get tools with schema validation errors."""
        return [t for t in self.tools if not t.schema_valid]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for reporting."""
        return {
            "total_tools": self.total_tools,
            "valid_tools": self.valid_tools,
            "invalid_tools": self.invalid_tools,
            "servers_contacted": self.servers_contacted,
            "servers_failed": self.servers_failed,
            "discovered_at": self.discovered_at,
            "tools": [t.to_dict() for t in self.tools],
            "server_statuses": [
                {
                    "server_name": s.server_name,
                    "success": s.success,
                    "tool_count": s.tool_count,
                    "error": s.error,
                }
                for s in self.server_statuses
            ],
        }


# =============================================================================
# Discovery Engine
# =============================================================================


class MCPToolDiscovery:
    """
    Discovers and validates tools across all configured MCP servers.

    Usage:
        from core.interface_pkg.interface_pkg.mcp.registry import MCPRegistry
        from core.interface_pkg.interface_pkg.mcp.discovery import MCPToolDiscovery

        registry = MCPRegistry(workspace_path)
        discovery = MCPToolDiscovery(registry)
        result = discovery.discover_all()

        print(f"Found {result.total_tools} tools across {result.servers_contacted} servers")
    """

    def __init__(self, registry: Any):
        """
        Initialize discovery engine.

        Args:
            registry: MCPRegistry instance for server access
        """
        self._registry = registry

    def discover_all(self, validate_schemas: bool = True) -> ToolDiscoveryResult:
        """
        Discover tools from all enabled MCP servers.

        Args:
            validate_schemas: Whether to validate tool input schemas

        Returns:
            ToolDiscoveryResult with all discovered tools
        """
        result = ToolDiscoveryResult()
        servers = self._registry.get_servers()

        if not servers:
            _logger.debug("No MCP servers configured for discovery")
            return result

        _logger.info(f"Discovering tools from {len(servers)} MCP server(s)")

        for server_config in servers:
            if not server_config.enabled:
                continue

            server_tools = self._discover_server(
                server_config.name,
                validate_schemas=validate_schemas,
            )
            status = server_tools[0]
            tools = server_tools[1]

            result.server_statuses.append(status)
            result.tools.extend(tools)

        _logger.info(
            f"Discovery complete: {result.total_tools} tools from "
            f"{result.servers_contacted} servers "
            f"({result.valid_tools} valid, {result.invalid_tools} invalid)"
        )

        return result

    def discover_server(self, server_name: str, validate_schemas: bool = True) -> list[DiscoveredTool]:
        """
        Discover tools from a specific server.

        Args:
            server_name: Server name to query
            validate_schemas: Whether to validate tool input schemas

        Returns:
            List of discovered tools
        """
        _, tools = self._discover_server(server_name, validate_schemas)
        return tools

    def _discover_server(self, server_name: str, validate_schemas: bool = True) -> tuple:
        """
        Internal: discover tools from a single server.

        Returns:
            Tuple of (ServerDiscoveryStatus, List[DiscoveredTool])
        """
        try:
            client = self._registry.get_client(server_name)
            if client is None:
                status = ServerDiscoveryStatus(
                    server_name=server_name,
                    success=False,
                    error="Could not connect to server",
                )
                return status, []

            # Get server version if available
            server_version = ""
            if client._state.server_info:
                si = client._state.server_info.get("serverInfo", {})
                server_version = si.get("version", "")

            # List tools
            mcp_tools = client.list_tools()

            discovered: list[DiscoveredTool] = []
            for mcp_tool in mcp_tools:
                tool = self._process_tool(
                    server_name=server_name,
                    mcp_tool=mcp_tool,
                    server_version=server_version,
                    validate_schema=validate_schemas,
                )
                discovered.append(tool)

            status = ServerDiscoveryStatus(
                server_name=server_name,
                success=True,
                tool_count=len(discovered),
                server_version=server_version,
            )

            _logger.info(f"Discovered {len(discovered)} tools from server '{server_name}'")
            return status, discovered

        except Exception as e:
            _logger.warning(f"Failed to discover tools from server '{server_name}': {e}")
            status = ServerDiscoveryStatus(
                server_name=server_name,
                success=False,
                error=str(e),
            )
            return status, []

    def _process_tool(
        self,
        server_name: str,
        mcp_tool: MCPTool,
        server_version: str = "",
        validate_schema: bool = True,
    ) -> DiscoveredTool:
        """
        Process a single MCP tool into a DiscoveredTool.

        Args:
            server_name: Originating server name
            mcp_tool: Raw MCP tool definition
            server_version: Server version string
            validate_schema: Whether to validate the schema

        Returns:
            DiscoveredTool with validation results
        """
        qualified_name = f"mcp_{server_name}_{mcp_tool.name}"

        # Extract schema as dict
        input_schema: dict[str, Any] | None = None
        if mcp_tool.inputSchema is not None:
            input_schema = mcp_tool.inputSchema.to_dict()

        # Validate schema
        schema_valid = True
        schema_errors: list[str] = []

        if validate_schema and mcp_tool.inputSchema is not None:
            schema_errors = validate_input_schema(mcp_tool.inputSchema)
            schema_valid = len(schema_errors) == 0

            if schema_errors:
                _logger.debug(f"Schema validation errors for {qualified_name}: {schema_errors}")

        return DiscoveredTool(
            server_name=server_name,
            tool_name=mcp_tool.name,
            qualified_name=qualified_name,
            description=mcp_tool.description,
            input_schema=input_schema,
            schema_valid=schema_valid,
            schema_errors=schema_errors,
            server_version=server_version,
        )
