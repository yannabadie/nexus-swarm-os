"""
Tool Handlers - NEXUS V9.6 Sprint 5.2b

Extracted from tool_manager.py for Single Responsibility.
Each handler focuses on one category of tools.

Modules:
- base: BaseHandler protocol and ToolResult
- bash_handler: bash command execution
- file_handlers: read, write, edit, list_dir
- search_handlers: glob, grep
- git_handler: git operations
- web_handlers: web_search, web_fetch
- todo_handler: todo_write
- dynamic_tools_handler: create, delete, list, run dynamic tools
- mcp_handler: MCP server tools
- swarm_handler: swarm delegation
"""

from pathlib import Path
from typing import Any

# Base classes
from .base import BaseHandler, ToolResult

# Handler imports
from .bash_handler import BashHandler, create_bash_handler
from .dynamic_tools_handler import (
    DYNAMIC_TOOLS_AVAILABLE,
    CreateToolHandler,
    DeleteToolHandler,
    ListDynamicToolsHandler,
    RunDynamicToolHandler,
    create_dynamic_tool_handlers,
)
from .file_handlers import (
    EditHandler,
    ListDirHandler,
    ReadHandler,
    WriteHandler,
    create_file_handlers,
)
from .git_handler import GitHandler, create_git_handler
from .mcp_handler import (
    MCP_AVAILABLE,
    MCPToolHandler,
    create_mcp_tool_executor,
    create_mcp_tool_handler,
)
from .search_handlers import (
    GlobHandler,
    GrepHandler,
    create_search_handlers,
)
from .swarm_handler import SwarmDelegateHandler, create_swarm_handler
from .todo_handler import TodoWriteHandler, create_todo_handler
from .web_handlers import (
    WebFetchHandler,
    WebSearchHandler,
    create_web_handlers,
)


def create_all_handlers(
    workspace_path: Path, validation_service: Any = None, dynamic_tool_manager: Any = None, swarm_bridge: Any = None
) -> dict[str, BaseHandler]:
    """
    Factory function to create all standard tool handlers.

    Args:
        workspace_path: Workspace root path
        validation_service: Optional validation service (PathGuardian)
        dynamic_tool_manager: Optional DynamicToolManager instance
        swarm_bridge: Optional SwarmBridge instance

    Returns:
        Dict mapping tool names to handler instances

    Note:
        MCP tools are NOT included here as they are dynamically
        registered based on server configuration. Use create_mcp_tool_handler()
        separately for MCP tools.
    """
    handlers: dict[str, BaseHandler] = {}

    # Bash handler
    handlers["bash"] = create_bash_handler(workspace_path, validation_service)

    # File handlers (read, write, edit, list_dir)
    handlers.update(create_file_handlers(workspace_path, validation_service))

    # Search handlers (glob, grep)
    handlers.update(create_search_handlers(workspace_path, validation_service))

    # Git handler
    handlers["git"] = create_git_handler(workspace_path, validation_service)

    # Web handlers (web_search, web_fetch)
    handlers.update(create_web_handlers(workspace_path, validation_service))

    # Todo handler
    handlers["todo_write"] = create_todo_handler(workspace_path, validation_service)

    # Dynamic tool handlers (create_tool, delete_tool, list_dynamic_tools, run_dynamic_tool)
    handlers.update(create_dynamic_tool_handlers(workspace_path, validation_service, dynamic_tool_manager))

    # Swarm delegate handler
    handlers["swarm_delegate"] = create_swarm_handler(workspace_path, validation_service, swarm_bridge)

    return handlers


__all__ = [
    # Base
    "BaseHandler",
    "ToolResult",
    # Handlers
    "BashHandler",
    "ReadHandler",
    "WriteHandler",
    "EditHandler",
    "ListDirHandler",
    "GlobHandler",
    "GrepHandler",
    "GitHandler",
    "WebSearchHandler",
    "WebFetchHandler",
    "TodoWriteHandler",
    "CreateToolHandler",
    "DeleteToolHandler",
    "ListDynamicToolsHandler",
    "RunDynamicToolHandler",
    "MCPToolHandler",
    "SwarmDelegateHandler",
    # Factory functions
    "create_bash_handler",
    "create_file_handlers",
    "create_search_handlers",
    "create_git_handler",
    "create_web_handlers",
    "create_todo_handler",
    "create_dynamic_tool_handlers",
    "create_mcp_tool_handler",
    "create_mcp_tool_executor",
    "create_swarm_handler",
    "create_all_handlers",
    # Availability flags
    "DYNAMIC_TOOLS_AVAILABLE",
    "MCP_AVAILABLE",
]
