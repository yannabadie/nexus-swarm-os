"""
ExecutionEngine - Centralized Tool Execution Orchestrator.

NEXUS V9.5 Refactoring - Sprint 2

Coordinates:
- ToolRegistry for handler lookup
- ValidationService for security
- Individual handlers for execution
- Error handling and logging

This is the main entry point for tool execution in NEXUS.

Usage:
    engine = ExecutionEngine(workspace_path)
    result = engine.execute(tool_request)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .handlers.base import ToolResult
from .handlers.bash_handler import create_bash_handler
from .handlers.file_handlers import create_file_handlers
from .handlers.search_handlers import create_search_handlers
from .tool_registry import ToolRegistry, get_tool_registry
from .validation_service import ValidationService

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Centralized tool execution engine.

    Responsibilities:
    - Route tool requests to appropriate handlers
    - Apply security validation
    - Handle errors gracefully
    - Track execution metrics
    """

    def __init__(
        self,
        workspace_path: Path,
        registry: ToolRegistry | None = None,
        validation_service: ValidationService | None = None,
    ):
        """
        Initialize execution engine.

        Args:
            workspace_path: Workspace root path
            registry: Optional ToolRegistry (uses global if None)
            validation_service: Optional ValidationService (created if None)
        """
        self.workspace_path = Path(workspace_path)
        self.registry = registry or get_tool_registry()
        self.validation_service = validation_service or ValidationService(
            workspace_path=self.workspace_path,
            parent_path=self.workspace_path.parent,
            generation_active=self.workspace_path.parent.parent / "GENERATION_ACTIVE",
        )

        # Statistics
        self._stats = {
            "total_executions": 0,
            "successful": 0,
            "failed": 0,
            "blocked": 0,
        }

        # Initialize core handlers
        self._initialize_handlers()

    def _initialize_handlers(self) -> None:
        """Initialize and register core tool handlers."""
        # File handlers
        file_handlers = create_file_handlers(
            self.workspace_path,
            self.validation_service,
        )
        for name, handler in file_handlers.items():
            self.registry.register(
                name,
                handler.execute,
                category="core",
                description=handler.__class__.__doc__ or "",
            )

        # Bash handler
        bash_handler = create_bash_handler(
            self.workspace_path,
            self.validation_service,
        )
        self.registry.register(
            "bash",
            bash_handler.execute,
            category="core",
            description="Execute shell commands",
        )

        # Search handlers
        search_handlers = create_search_handlers(
            self.workspace_path,
            self.validation_service,
        )
        for name, handler in search_handlers.items():
            self.registry.register(
                name,
                handler.execute,
                category="core",
                description=handler.__class__.__doc__ or "",
            )

        logger.debug(f"Initialized {len(self.registry.list_tools())} core handlers")

    def execute(self, tool_request: Any) -> ToolResult:
        """
        Execute a tool request.

        Args:
            tool_request: Object with tool_name and arguments attributes

        Returns:
            ToolResult with execution outcome
        """
        tool_name = getattr(tool_request, "tool_name", "")
        arguments = getattr(tool_request, "arguments", {})

        return self.execute_by_name(tool_name, arguments)

    def execute_by_name(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name.

        Args:
            tool_name: Tool name (will be normalized)
            arguments: Tool arguments

        Returns:
            ToolResult with execution outcome
        """
        self._stats["total_executions"] += 1

        # Normalize tool name
        normalized_name = self.registry.normalize_name(tool_name)

        # Get handler
        handler = self.registry.get_handler(normalized_name)
        if handler is None:
            self._stats["failed"] += 1
            return ToolResult.make_error(tool_name, f"Unknown tool: {tool_name}")

        try:
            result = handler(arguments)

            # Track statistics
            if result.status == "SUCCESS":
                self._stats["successful"] += 1
            elif result.status == "BLOCKED":
                self._stats["blocked"] += 1
            else:
                self._stats["failed"] += 1

            return result

        except Exception as e:
            self._stats["failed"] += 1
            logger.error(f"Tool execution error: {tool_name}: {e}")
            return ToolResult.make_error(tool_name, str(e))

    def register_handler(
        self,
        name: str,
        handler: Callable[[dict[str, Any]], ToolResult],
        *,
        category: str = "custom",
        description: str = "",
    ) -> None:
        """
        Register a custom tool handler.

        Args:
            name: Tool name
            handler: Handler function
            category: Tool category
            description: Tool description
        """
        self.registry.register(
            name,
            handler,
            category=category,
            description=description,
        )
        logger.debug(f"Registered custom handler: {name}")

    def has_tool(self, name: str) -> bool:
        """Check if tool exists."""
        return self.registry.has_tool(name)

    def list_tools(self) -> list[str]:
        """List all available tools."""
        return self.registry.list_tools()

    def set_evolution_mode(self, enabled: bool) -> None:
        """Enable or disable evolution mode."""
        self.validation_service.set_evolution_mode(enabled)

    def get_stats(self) -> dict[str, int]:
        """Get execution statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset execution statistics."""
        self._stats = {
            "total_executions": 0,
            "successful": 0,
            "failed": 0,
            "blocked": 0,
        }


# =============================================================================
# V10 PRISM: Multi-Tenant Execution Engine Access
# =============================================================================
_engine_instance: ExecutionEngine | None = None


def get_execution_engine(workspace_path: Path | None = None) -> ExecutionEngine:
    """
    Get the execution engine for the current tenant context.

    V10 PRISM: Returns tenant-scoped engine via ServiceFactory.
    Falls back to global singleton if no context is active.

    Args:
        workspace_path: Workspace path (required on first call in legacy mode)

    Returns:
        ExecutionEngine instance scoped to current tenant
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_execution_engine()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    global _engine_instance
    if _engine_instance is None:
        if workspace_path is None:
            raise ValueError("workspace_path required for first initialization")
        _engine_instance = ExecutionEngine(workspace_path)
    return _engine_instance


def reset_execution_engine() -> None:
    """
    Reset the global execution engine (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _engine_instance
    _engine_instance = None

    # V10: Also clear factory cache
    try:
        from ..context import get_current_session_or_none
        from ..factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
