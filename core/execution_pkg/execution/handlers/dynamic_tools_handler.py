"""
Dynamic Tools Handler - Create, delete, list, run dynamic Python tools.

NEXUS V9.6 Sprint 5.2b - Extracted from tool_manager.py

Provides:
- CreateToolHandler: Create new dynamic tools
- DeleteToolHandler: Delete existing tools
- ListDynamicToolsHandler: List all available tools
- RunDynamicToolHandler: Execute a dynamic tool
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult

# Optional import - DynamicToolManager may not be available
try:
    from core.execution_pkg.execution.dynamic_tools import DynamicToolManager

    DYNAMIC_TOOLS_AVAILABLE = True
except ImportError:
    DynamicToolManager = None  # type: ignore
    DYNAMIC_TOOLS_AVAILABLE = False


class DynamicToolsHandlerBase(BaseHandler):
    """
    Base class for dynamic tool handlers.

    Manages lazy initialization of DynamicToolManager.
    """

    def __init__(self, workspace_path: Path, validation_service: Any = None, dynamic_tool_manager: Any | None = None):
        super().__init__(workspace_path, validation_service)
        self._dynamic_tool_manager = dynamic_tool_manager

    def _get_manager(self) -> Any | None:
        """Get or create DynamicToolManager."""
        if self._dynamic_tool_manager is not None:
            return self._dynamic_tool_manager

        if not DYNAMIC_TOOLS_AVAILABLE or DynamicToolManager is None:
            return None

        try:
            self._dynamic_tool_manager = DynamicToolManager(self.workspace_path)
            return self._dynamic_tool_manager
        except Exception:
            return None

    def _manager_not_available(self) -> ToolResult:
        """Return error when manager is not available."""
        return ToolResult(
            tool_name=self.tool_name, status="ERROR", output="", error="Dynamic Tool Manager not available"
        )


class CreateToolHandler(DynamicToolsHandlerBase):
    """
    Handler for creating new dynamic Python tools.

    Tools are sandboxed Python functions with restricted capabilities.
    """

    @property
    def tool_name(self) -> str:
        return "create_tool"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Create a new dynamic Python tool.

        Args:
            args: {
                "name": "tool_name",
                "code": "def run(x): return x * 2",
                "description": "Optional description"
            }

        Returns:
            ToolResult with creation status

        Example:
            {
                "name": "fibonacci",
                "code": "def run(n):\\n    if n <= 1: return n\\n    return run(n-1) + run(n-2)",
                "description": "Calculate fibonacci number"
            }
        """
        manager = self._get_manager()
        if manager is None:
            return self._manager_not_available()

        name = args.get("name", "")
        code = args.get("code", "")
        description = args.get("description", "")

        if not name:
            return self._error("Tool name is required")

        if not code:
            return self._error("Tool code is required")

        result = manager.create_tool(name, code, description)

        if result.success:
            return ToolResult(
                tool_name=self.tool_name,
                status="SUCCESS",
                output=(
                    f"Tool '{name}' created successfully at {result.tool_path}\n\n"
                    f"Use 'run_dynamic_tool' with name='{name}' to execute it."
                ),
            )
        else:
            error_msg = result.error or "Unknown error"
            if result.validation_violations:
                error_msg += "\n\nValidation violations:\n"
                error_msg += "\n".join(f"  - {v}" for v in result.validation_violations)

            return self._fail(error_msg)


class DeleteToolHandler(DynamicToolsHandlerBase):
    """Handler for deleting dynamic tools."""

    @property
    def tool_name(self) -> str:
        return "delete_tool"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Delete a dynamic tool.

        Args:
            args: {
                "name": "tool_name"
            }

        Returns:
            ToolResult with deletion status
        """
        manager = self._get_manager()
        if manager is None:
            return self._manager_not_available()

        name = args.get("name", "")

        if not name:
            return self._error("Tool name is required")

        success, message = manager.delete_tool(name)

        return ToolResult(
            tool_name=self.tool_name,
            status="SUCCESS" if success else "FAILURE",
            output=message if success else "",
            error="" if success else message,
        )


class ListDynamicToolsHandler(DynamicToolsHandlerBase):
    """Handler for listing all dynamic tools."""

    @property
    def tool_name(self) -> str:
        return "list_dynamic_tools"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        List all available dynamic tools.

        Args:
            args: {} (no arguments required)

        Returns:
            ToolResult with list of tools
        """
        manager = self._get_manager()
        if manager is None:
            return self._manager_not_available()

        tools = manager.list_tools()

        if not tools:
            return ToolResult(
                tool_name=self.tool_name,
                status="SUCCESS",
                output=("No dynamic tools found.\n\nUse 'create_tool' to create a new tool."),
            )

        output = f"Found {len(tools)} dynamic tool(s):\n\n"
        for tool in tools:
            output += f"  - {tool.name}: {tool.description}\n"
            output += f"    Created: {tool.created_at}\n"

        return ToolResult(tool_name=self.tool_name, status="SUCCESS", output=output)


class RunDynamicToolHandler(DynamicToolsHandlerBase):
    """Handler for executing dynamic tools."""

    @property
    def tool_name(self) -> str:
        return "run_dynamic_tool"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Execute a dynamic tool.

        Args:
            args: {
                "name": "tool_name",
                "args": {"arg1": value1, ...}  # Arguments for the tool
            }

        Returns:
            ToolResult with execution output

        Example:
            {
                "name": "fibonacci",
                "args": {"n": 10}
            }
        """
        manager = self._get_manager()
        if manager is None:
            return self._manager_not_available()

        name = args.get("name", "")
        tool_args = args.get("args", {})

        if not name:
            return self._error("Tool name is required")

        result = manager.execute_tool(name, tool_args)

        if result.timed_out:
            return ToolResult(tool_name=self.tool_name, status="TIMEOUT", output="", error=result.error)

        return ToolResult(
            tool_name=self.tool_name,
            status="SUCCESS" if result.success else "FAILURE",
            output=result.output,
            error=result.error,
        )


def create_dynamic_tool_handlers(
    workspace_path: Path, validation_service: Any = None, dynamic_tool_manager: Any = None
) -> dict[str, BaseHandler]:
    """
    Factory function to create all dynamic tool handlers.

    Args:
        workspace_path: Workspace root path
        validation_service: Optional validation service
        dynamic_tool_manager: Optional shared DynamicToolManager instance

    Returns:
        Dict mapping tool names to handlers
    """
    return {
        "create_tool": CreateToolHandler(workspace_path, validation_service, dynamic_tool_manager),
        "delete_tool": DeleteToolHandler(workspace_path, validation_service, dynamic_tool_manager),
        "list_dynamic_tools": ListDynamicToolsHandler(workspace_path, validation_service, dynamic_tool_manager),
        "run_dynamic_tool": RunDynamicToolHandler(workspace_path, validation_service, dynamic_tool_manager),
    }
