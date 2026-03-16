"""
Tool Manager V9.6 - Thin Wrapper over Handler Registry

NEXUS V9.6 Sprint 5.2b - Refactored to delegate to handlers/

Outils disponibles (TOUS accessibles par Gemini ET Claude):
- bash: Execute shell commands
- read: Read file contents
- write: Create/overwrite file
- edit: Search and replace in file
- list_dir: List directory contents
- git: Git operations (status, diff, log, branch, pull)
- web_search: Search the web (via Gemini CLI)
- web_fetch: Fetch URL content
- glob: File pattern matching
- grep: Search code for patterns
- todo_write: Task/plan management
- mcp_*: Dynamic MCP tools from configured servers
- create_tool: Create a dynamic Python tool
- delete_tool: Delete a dynamic tool
- list_dynamic_tools: List all dynamic tools
- run_dynamic_tool: Execute a dynamic tool
- swarm_delegate: Delegate to Swarm Engine
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Security imports
from core.security_pkg.security import PathGuardian
from core.security_pkg.security.execution_policy import ExecutionPolicy

# Handler imports - V9.6 refactored
from .handlers import ToolResult, create_all_handlers

# V7.6 Phase 12.3: MCP Client imports (optional)
try:
    from core.interface_pkg.mcp import MCPRegistry
    from core.interface_pkg.mcp.client import MCPClientError, MCPServerError

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    MCPRegistry = None
    MCPClientError = Exception  # type: ignore
    MCPServerError = Exception  # type: ignore

# V7.8 Phase 12.5: Dynamic Tool Generation imports
try:
    from core.execution_pkg.execution.dynamic_tools import DynamicToolManager

    _DYNAMIC_TOOLS_AVAILABLE = True
except ImportError:
    _DYNAMIC_TOOLS_AVAILABLE = False
    DynamicToolManager = None


class ToolManager:
    """
    Centralized tool execution (OMTE - Orchestrated Multi-Tool Executor)

    V9.6: Refactored to thin wrapper over handlers/ registry.
    All tool execution delegated to BaseHandler subclasses.
    """

    # Tool name aliases (Gemini CLI names -> NEXUS names)
    TOOL_ALIASES = {
        "read_file": "read",
        "write_file": "write",
        "edit_file": "edit",
        "list_directory": "list_dir",
        "run_shell_command": "bash",
        "google_web_search": "web_search",
        "read_many_files": "read",
    }

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path

        # Evolution mode flag (enabled only during /evolve)
        self.evolution_mode = False

        # Compute paths for evolution permissions
        self.parent_path = workspace_path.parent
        self.project_root = workspace_path.parent.parent
        self.generation_active = self.project_root / "GENERATION_ACTIVE"

        # Initialize PathGuardian (security layer 2)
        self.path_guardian = PathGuardian(
            workspace_path=workspace_path, parent_path=self.parent_path, generation_active=self.generation_active
        )

        # Initialize ExecutionPolicy (security layer 1)
        self.execution_policy = ExecutionPolicy(workspace_path)

        # V8.3.1: SwarmBridge for swarm_delegate tool (set externally)
        self._swarm_bridge: Any | None = None

        # MCP Registry and tools
        self._mcp_registry: MCPRegistry | None = None
        self._mcp_tools: dict[str, tuple[str, str]] = {}
        self._logger = logging.getLogger("nexus.tools")

        # Dynamic Tool Manager
        self._dynamic_tool_manager: DynamicToolManager | None = None

        # Initialize subsystems BEFORE creating handlers
        if _MCP_AVAILABLE:
            self._init_mcp_tools()
        if _DYNAMIC_TOOLS_AVAILABLE:
            self._init_dynamic_tools()

        # Create all handlers with dependencies
        self._handlers = create_all_handlers(
            workspace_path=self.workspace_path,
            validation_service=self.path_guardian,
            dynamic_tool_manager=self._dynamic_tool_manager,
            swarm_bridge=self._swarm_bridge,
        )

        # Build dispatch table from handlers
        self.tools: dict[str, Any] = {}
        for name, handler in self._handlers.items():
            self.tools[name] = handler

        # Add MCP tools to dispatch table (dynamically registered)
        for mcp_tool_name, (server_name, tool_name) in self._mcp_tools.items():
            self.tools[mcp_tool_name] = self._create_mcp_tool_handler(server_name, tool_name)

    @property
    def swarm_bridge(self) -> Any | None:
        """Get the SwarmBridge instance."""
        return self._swarm_bridge

    @swarm_bridge.setter
    def swarm_bridge(self, bridge: Any) -> None:
        """Set SwarmBridge and propagate to handler."""
        self._swarm_bridge = bridge
        # Update swarm_delegate handler if it exists
        if "swarm_delegate" in self._handlers:
            self._handlers["swarm_delegate"].swarm_bridge = bridge

    def execute(self, tool_request) -> ToolResult:
        """
        Execute tool request.

        Args:
            tool_request: ToolUse object with tool_name and arguments

        Returns:
            ToolResult with status, output, and error
        """
        tool_name = tool_request.tool_name
        arguments = tool_request.arguments

        # Normalize tool name using alias if needed
        tool_name = self.TOOL_ALIASES.get(tool_name, tool_name)

        if tool_name not in self.tools:
            return ToolResult(tool_name=tool_name, status="ERROR", output="", error=f"Unknown tool: {tool_name}")

        # Evolution mode pre-validation for search tools accessing parent
        if tool_name in ("glob", "grep"):
            search_path = arguments.get("path", ".")
            if search_path.startswith(".."):
                # Resolve path relative to workspace
                resolved = (self.workspace_path / search_path).resolve()
                if not self._is_evolution_safe_list(resolved):
                    return ToolResult(
                        tool_name=tool_name,
                        status="FAILURE",
                        output="",
                        error=f"Path '{search_path}' is not allowed in evolution mode",
                    )

        try:
            handler = self.tools[tool_name]
            # Handler is a BaseHandler instance - call execute()
            if hasattr(handler, "execute"):
                return handler.execute(arguments)
            # Fallback for callable (MCP handlers)
            return handler(arguments)
        except Exception as e:
            return ToolResult(tool_name=tool_name, status="ERROR", output="", error=f"Tool execution error: {str(e)}")

    # =========================================================================
    # Evolution Mode Security Helpers
    # =========================================================================

    def _is_evolution_safe_read(self, path: Path) -> bool:
        """
        Check if path is allowed for evolution READ operations.

        Whitelist:
        - ../core/**/*.py (parent project code)
        - ../prompts/**/*.md (parent prompts)
        - ../README.md, ../nexus6.py (parent root files)

        Forbidden:
        - NEXUS_V5_PRAGMATIC
        - .env, .git, __pycache__

        V12.4 Security: Uses resolve() to prevent symlink-based path traversal.
        """
        try:
            # V12.4: Resolve symlinks and normalize path before validation
            resolved = path.resolve()
            parent_resolved = self.parent_path.resolve()

            relative = resolved.relative_to(parent_resolved)
            path_str = str(relative).replace("\\", "/")

            allowed_prefixes = ["core/", "prompts/", "benchmarks/"]
            allowed_root_files = ["README.md", "nexus6.py", "LINEAGE.json"]
            forbidden = ["NEXUS_V5_PRAGMATIC", "__pycache__", ".git", ".pyc"]

            if any(forb in path_str for forb in forbidden):
                return False
            if any(path_str.startswith(prefix) for prefix in allowed_prefixes):
                return True
            return path_str in allowed_root_files
        except (ValueError, OSError):
            return False

    def _is_evolution_safe_list(self, path: Path) -> bool:
        """
        Check if path is allowed for evolution LIST operations.

        Whitelist:
        - ../core/ (parent project code)
        - ../prompts/ (parent prompts)
        - ../benchmarks/ (benchmark scripts)

        V12.4 Security: Uses resolve() to prevent symlink-based path traversal.
        """
        try:
            # V12.4: Resolve symlinks and normalize path before validation
            resolved = path.resolve()
            parent_resolved = self.parent_path.resolve()

            relative = resolved.relative_to(parent_resolved)
            path_str = str(relative).replace("\\", "/")

            allowed_prefixes = ["core", "prompts", "benchmarks"]
            forbidden = ["NEXUS_V5_PRAGMATIC", ".git", "__pycache__"]

            if any(forb in path_str for forb in forbidden):
                return False
            return bool(any(path_str.startswith(prefix) or path_str == prefix for prefix in allowed_prefixes))
        except (ValueError, OSError):
            return False

    def _is_evolution_safe_write(self, path: Path) -> bool:
        """
        Check if path is allowed for evolution WRITE/EDIT operations.

        Whitelist:
        - ../../GENERATION_ACTIVE/** (children only)

        Everything else is FORBIDDEN.

        V12.4 Security: Uses resolve() to prevent symlink-based path traversal.
        """
        try:
            # V12.4: Resolve symlinks and normalize path before validation
            resolved = path.resolve()
            generation_resolved = self.generation_active.resolve()

            resolved.relative_to(generation_resolved)
            return True
        except (ValueError, OSError):
            return False

    # =========================================================================
    # V7.6 Phase 12.3: MCP Tool Integration (CORTEX)
    # =========================================================================

    def _init_mcp_tools(self) -> None:
        """Initialize MCP registry and register dynamic tools from servers."""
        try:
            self._mcp_registry = MCPRegistry(self.workspace_path)
            servers = self._mcp_registry.get_servers()

            if not servers:
                self._logger.debug("No MCP servers configured")
                return

            self._logger.info(f"Loading tools from {len(servers)} MCP server(s)")

            for server_config in servers:
                if not server_config.enabled:
                    continue
                try:
                    self._register_mcp_server_tools(server_config.name)
                except Exception as e:
                    self._logger.warning(f"Failed to load tools from MCP server '{server_config.name}': {e}")
        except Exception as e:
            self._logger.error(f"Failed to initialize MCP registry: {e}")

    def _register_mcp_server_tools(self, server_name: str) -> None:
        """Register tools from a specific MCP server."""
        if self._mcp_registry is None:
            return

        try:
            client = self._mcp_registry.get_client(server_name)
            if client is None:
                self._logger.warning(f"Could not connect to MCP server: {server_name}")
                return

            tools = client.list_tools()
            self._logger.info(f"MCP server '{server_name}' provides {len(tools)} tool(s)")

            for tool in tools:
                nexus_tool_name = f"mcp_{server_name}_{tool.name}"
                self._mcp_tools[nexus_tool_name] = (server_name, tool.name)
                self._logger.debug(f"Registered MCP tool: {nexus_tool_name}")

        except Exception as e:
            self._logger.error(f"Error registering tools from {server_name}: {e}")
            raise

    def _create_mcp_tool_handler(self, server_name: str, tool_name: str) -> Callable[[dict], ToolResult]:
        """Create a handler function for an MCP tool."""

        def handler(args: dict) -> ToolResult:
            return self._execute_mcp_tool(server_name, tool_name, args)

        return handler

    def _execute_mcp_tool(self, server_name: str, tool_name: str, args: dict) -> ToolResult:
        """Execute an MCP tool."""
        nexus_tool_name = f"mcp_{server_name}_{tool_name}"

        if self._mcp_registry is None:
            return ToolResult(
                tool_name=nexus_tool_name, status="ERROR", output="", error="MCP registry not initialized"
            )

        try:
            client = self._mcp_registry.get_client(server_name)
            if client is None:
                return ToolResult(
                    tool_name=nexus_tool_name,
                    status="ERROR",
                    output="",
                    error=f"Failed to connect to MCP server: {server_name}",
                )

            result = client.call_tool(tool_name, args)

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

    def get_mcp_tools(self) -> list[str]:
        """Get list of available MCP tools."""
        return list(self._mcp_tools.keys())

    def reload_mcp_tools(self) -> int:
        """Reload MCP tools from all configured servers."""
        # Clear existing MCP tools
        for tool_name in list(self._mcp_tools.keys()):
            if tool_name in self.tools:
                del self.tools[tool_name]
        self._mcp_tools.clear()

        # Close all clients
        if self._mcp_registry:
            self._mcp_registry.close_all()
            self._mcp_registry.reload()

        # Reinitialize
        if _MCP_AVAILABLE:
            self._init_mcp_tools()
            # Re-register handlers
            for mcp_tool_name, (server_name, tool_name) in self._mcp_tools.items():
                self.tools[mcp_tool_name] = self._create_mcp_tool_handler(server_name, tool_name)

        return len(self._mcp_tools)

    def close_mcp(self) -> None:
        """Close all MCP connections."""
        if self._mcp_registry:
            self._mcp_registry.close_all()

    # =========================================================================
    # V7.8 Phase 12.5: Dynamic Tool Generation
    # =========================================================================

    def _init_dynamic_tools(self) -> None:
        """Initialize the Dynamic Tool Manager."""
        try:
            self._dynamic_tool_manager = DynamicToolManager(self.workspace_path)
            tools_count = len(self._dynamic_tool_manager.list_tools())
            if tools_count > 0:
                self._logger.info(f"Loaded {tools_count} existing dynamic tool(s)")
        except Exception as e:
            self._logger.error(f"Failed to initialize Dynamic Tool Manager: {e}")
            self._dynamic_tool_manager = None

    def get_dynamic_tools(self) -> list[str]:
        """Get list of available dynamic tools."""
        if self._dynamic_tool_manager is None:
            return []
        return [t.name for t in self._dynamic_tool_manager.list_tools()]


# Re-export for backward compatibility
__all__ = ["ToolManager", "ToolResult"]
