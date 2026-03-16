"""
MCP Handler - Execute Model Context Protocol tools.

NEXUS V9.6 Sprint 5.2b - Extracted from tool_manager.py

Provides:
- MCPToolHandler: Execute tools from MCP servers
- MCP_AVAILABLE: Flag indicating MCP module availability
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult

# Optional import - MCP module may not be available
try:
    from core.interface_pkg.interface_pkg.mcp import MCPRegistry
    from core.interface_pkg.interface_pkg.mcp.client import MCPClientError, MCPServerError

    MCP_AVAILABLE = True
except ImportError:
    MCPRegistry = None  # type: ignore
    MCPClientError = Exception  # type: ignore
    MCPServerError = Exception  # type: ignore
    MCP_AVAILABLE = False


class MCPToolHandler(BaseHandler):
    """
    Handler for executing MCP (Model Context Protocol) tools.

    Delegates tool calls to registered MCP servers.
    """

    def __init__(
        self,
        workspace_path: Path,
        validation_service: Any = None,
        mcp_registry: Any | None = None,
        server_name: str = "",
        mcp_tool_name: str = "",
    ):
        super().__init__(workspace_path, validation_service)
        self._mcp_registry = mcp_registry
        self._server_name = server_name
        self._mcp_tool_name = mcp_tool_name

    @property
    def tool_name(self) -> str:
        """Return full MCP tool name (mcp_{server}_{tool})."""
        if self._server_name and self._mcp_tool_name:
            return f"mcp_{self._server_name}_{self._mcp_tool_name}"
        return "mcp_tool"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Execute an MCP tool.

        Args:
            args: Tool arguments to pass to the MCP server

        Returns:
            ToolResult with execution output
        """
        nexus_tool_name = self.tool_name

        if self._mcp_registry is None:
            return ToolResult(
                tool_name=nexus_tool_name, status="ERROR", output="", error="MCP registry not initialized"
            )

        try:
            client = self._mcp_registry.get_client(self._server_name)
            if client is None:
                return ToolResult(
                    tool_name=nexus_tool_name,
                    status="ERROR",
                    output="",
                    error=f"Failed to connect to MCP server: {self._server_name}",
                )

            # Call the tool
            result = client.call_tool(self._mcp_tool_name, args)

            if result.isError:
                return ToolResult(tool_name=nexus_tool_name, status="FAILURE", output="", error=result.text)

            return ToolResult(tool_name=nexus_tool_name, status="SUCCESS", output=result.text)

        except MCPServerError as e:
            return ToolResult(
                tool_name=nexus_tool_name, status="FAILURE", output="", error=f"MCP server error: {e.error.message}"
            )
        except MCPClientError as e:
            return ToolResult(tool_name=nexus_tool_name, status="ERROR", output="", error=f"MCP client error: {str(e)}")
        except Exception as e:
            return ToolResult(tool_name=nexus_tool_name, status="ERROR", output="", error=f"Unexpected error: {str(e)}")


def create_mcp_tool_handler(
    workspace_path: Path, mcp_registry: Any, server_name: str, tool_name: str, validation_service: Any = None
) -> MCPToolHandler:
    """
    Factory function to create an MCP tool handler.

    Args:
        workspace_path: Workspace root path
        mcp_registry: MCPRegistry instance
        server_name: Name of the MCP server
        tool_name: Name of the tool on the server
        validation_service: Optional validation service

    Returns:
        MCPToolHandler instance configured for the specific tool
    """
    return MCPToolHandler(
        workspace_path=workspace_path,
        validation_service=validation_service,
        mcp_registry=mcp_registry,
        server_name=server_name,
        mcp_tool_name=tool_name,
    )


def create_mcp_tool_executor(handler: MCPToolHandler) -> Callable[[dict], ToolResult]:
    """
    Create a callable executor for legacy ToolManager integration.

    This wraps the handler's execute method for compatibility with
    the ToolManager.tools dict pattern.

    Args:
        handler: MCPToolHandler instance

    Returns:
        Callable that executes the handler
    """

    def executor(args: dict) -> ToolResult:
        return handler.execute(args)

    return executor
