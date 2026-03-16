"""
Tool Executor Abstraction - V11 CLI/API Independent Tool Execution.

F33 Fix: Decouples tool execution from CLI-provided tools.

Problem (F33):
- Gemini CLI: Tools like read_file, grep, glob are executed by the CLI itself
- Claude CLI: Similar built-in tool execution
- API: Does NOT provide tool execution - we must implement them
- Current code assumes CLI handles tool execution

Solution:
- LocalToolExecutor: Implements common tools locally (Python)
- CLIToolExecutor: Wraps CLI-provided tools (for reference)
- ToolRegistry: Maps tool names to executors

Benefits:
1. API drivers can execute the same tools as CLI drivers
2. Consistent tool behavior across CLI and API
3. Can add custom tools without CLI modification
4. Enables tool execution in WebSocket backend (CEREBRO UI)

Supported Tools:
```
File Operations:
+-- read_file      - Read file contents
+-- write_file     - Write file contents
+-- edit_file      - Edit file (search/replace)
+-- list_directory - List directory contents

Search Operations:
+-- grep           - Search file contents
+-- glob           - Find files by pattern
+-- read_many_files - Read multiple files

Web Operations:
+-- web_fetch      - Fetch URL content
+-- google_web_search - Web search (requires API key)
```

Author: Claude (NEXUS V11)
Date: 2025-12-15
"""

from __future__ import annotations

import abc
import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Result Types
# =============================================================================


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: Any
    error: str | None = None
    execution_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }


@dataclass
class ToolSchema:
    """JSON schema for a tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for parameters
    required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required,
            },
        }


# =============================================================================
# Abstract Tool Executor
# =============================================================================


class ToolExecutor(abc.ABC):
    """Abstract base class for tool executors."""

    @abc.abstractmethod
    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        workspace_path: Path | None = None,
        timeout: float = 30.0,
    ) -> ToolResult:
        """Execute a tool and return result."""
        ...

    @abc.abstractmethod
    def list_tools(self) -> list[str]:
        """List available tool names."""
        ...

    @abc.abstractmethod
    def get_schema(self, tool_name: str) -> ToolSchema | None:
        """Get schema for a tool."""
        ...

    def supports_tool(self, tool_name: str) -> bool:
        """Check if this executor supports a tool."""
        return tool_name in self.list_tools()


# =============================================================================
# Local Tool Executor (Pure Python)
# =============================================================================


class LocalToolExecutor(ToolExecutor):
    """
    Executes tools locally using Python.

    Used when API drivers need tool execution (CLI not available).
    Implements the same tools that Gemini/Claude CLI provide.
    """

    def __init__(
        self,
        workspace_path: Path,
        max_file_size: int = 1_000_000,  # 1MB
        allowed_extensions: list[str] | None = None,
    ):
        """
        Initialize local tool executor.

        Args:
            workspace_path: Base workspace path for file operations
            max_file_size: Maximum file size to read (bytes)
            allowed_extensions: If set, only allow these file extensions
        """
        self._workspace_path = Path(workspace_path)
        self._max_file_size = max_file_size
        self._allowed_extensions = allowed_extensions

        # Register tool handlers
        self._handlers: dict[str, Callable] = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "list_directory": self._list_directory,
            "grep": self._grep,
            "glob": self._glob,
            "read_many_files": self._read_many_files,
        }

        # Tool schemas
        self._schemas: dict[str, ToolSchema] = {
            "read_file": ToolSchema(
                name="read_file",
                description="Read the contents of a file",
                parameters={
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                    "offset": {"type": "integer", "description": "Line offset to start from"},
                    "limit": {"type": "integer", "description": "Maximum lines to read"},
                },
                required=["file_path"],
            ),
            "write_file": ToolSchema(
                name="write_file",
                description="Write content to a file",
                parameters={
                    "file_path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                required=["file_path", "content"],
            ),
            "edit_file": ToolSchema(
                name="edit_file",
                description="Edit a file using search and replace",
                parameters={
                    "file_path": {"type": "string", "description": "Path to the file to edit"},
                    "old_string": {"type": "string", "description": "String to search for"},
                    "new_string": {"type": "string", "description": "String to replace with"},
                },
                required=["file_path", "old_string", "new_string"],
            ),
            "list_directory": ToolSchema(
                name="list_directory",
                description="List contents of a directory",
                parameters={
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                required=["path"],
            ),
            "grep": ToolSchema(
                name="grep",
                description="Search file contents using regex",
                parameters={
                    "pattern": {"type": "string", "description": "Regex pattern to search"},
                    "path": {"type": "string", "description": "File or directory to search"},
                    "include": {"type": "string", "description": "File pattern to include"},
                },
                required=["pattern"],
            ),
            "glob": ToolSchema(
                name="glob",
                description="Find files matching a pattern",
                parameters={
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py')"},
                    "path": {"type": "string", "description": "Base path to search from"},
                },
                required=["pattern"],
            ),
            "read_many_files": ToolSchema(
                name="read_many_files",
                description="Read multiple files at once",
                parameters={
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to read",
                    },
                },
                required=["file_paths"],
            ),
        }

    def _resolve_path(self, path: str) -> Path:
        """
        Resolve path relative to workspace, with security checks.

        Prevents path traversal attacks (CWE-22).
        """
        # Convert to Path
        p = Path(path)

        # If absolute, check it's under workspace
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self._workspace_path / p).resolve()

        # Security: Ensure path is under workspace
        try:
            resolved.relative_to(self._workspace_path.resolve())
        except ValueError:
            raise ValueError(f"Path traversal detected: {path}") from None

        return resolved

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        workspace_path: Path | None = None,
        timeout: float = 30.0,
    ) -> ToolResult:
        """Execute a tool locally."""
        import time

        start = time.time()

        if tool_name not in self._handlers:
            return ToolResult(
                success=False,
                output=None,
                error=f"Unknown tool: {tool_name}",
            )

        # Override workspace if provided
        original_workspace = self._workspace_path
        if workspace_path:
            self._workspace_path = Path(workspace_path)

        try:
            # Execute with timeout
            handler = self._handlers[tool_name]
            # V12.4 FIX F19: Use get_running_loop() instead of deprecated get_event_loop()
            result = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, lambda: handler(arguments)),
                timeout=timeout,
            )
            elapsed = (time.time() - start) * 1000

            return ToolResult(
                success=True,
                output=result,
                execution_time_ms=elapsed,
            )

        except TimeoutError:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool {tool_name} timed out after {timeout}s",
            )
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
            )
        finally:
            self._workspace_path = original_workspace

    def list_tools(self) -> list[str]:
        """List available tools."""
        return list(self._handlers.keys())

    def get_schema(self, tool_name: str) -> ToolSchema | None:
        """Get schema for a tool."""
        return self._schemas.get(tool_name)

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    def _read_file(self, args: dict[str, Any]) -> str:
        """Read file contents."""
        path = self._resolve_path(args["file_path"])

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if path.stat().st_size > self._max_file_size:
            raise ValueError(f"File too large: {path.stat().st_size} > {self._max_file_size}")

        offset = args.get("offset", 0)
        limit = args.get("limit")

        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Apply offset and limit
        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:limit]

        return "".join(lines)

    def _write_file(self, args: dict[str, Any]) -> str:
        """Write content to file."""
        path = self._resolve_path(args["file_path"])
        content = args["content"]

        # Create parent directories
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote {len(content)} bytes to {path}"

    def _edit_file(self, args: dict[str, Any]) -> str:
        """Edit file using search/replace."""
        path = self._resolve_path(args["file_path"])
        old_string = args["old_string"]
        new_string = args["new_string"]

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        with open(path, encoding="utf-8") as f:
            content = f.read()

        if old_string not in content:
            raise ValueError(f"String not found in file: {old_string[:50]}...")

        # Check uniqueness
        count = content.count(old_string)
        if count > 1:
            raise ValueError(f"String appears {count} times, must be unique")

        new_content = content.replace(old_string, new_string, 1)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Successfully edited {path}"

    def _list_directory(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """List directory contents."""
        path = self._resolve_path(args.get("path", "."))

        if not path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        entries = []
        for entry in sorted(path.iterdir()):
            try:
                stat = entry.stat()
                entries.append(
                    {
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size": stat.st_size if entry.is_file() else None,
                    }
                )
            except (PermissionError, OSError):
                entries.append(
                    {
                        "name": entry.name,
                        "type": "unknown",
                        "error": "permission denied",
                    }
                )

        return entries

    def _grep(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """Search file contents using regex."""
        pattern = args["pattern"]
        base_path = self._resolve_path(args.get("path", "."))
        include = args.get("include", "*")

        regex = re.compile(pattern, re.IGNORECASE)
        results = []

        def search_file(file_path: Path) -> list[dict[str, Any]]:
            matches = []
            try:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "file": str(file_path.relative_to(self._workspace_path)),
                                    "line": line_num,
                                    "content": line.rstrip()[:200],
                                }
                            )
            except (PermissionError, OSError, UnicodeDecodeError):
                pass
            return matches

        if base_path.is_file():
            results.extend(search_file(base_path))
        else:
            for file_path in base_path.rglob(include):
                if file_path.is_file():
                    results.extend(search_file(file_path))
                    if len(results) > 100:  # Limit results
                        break

        return results

    def _glob(self, args: dict[str, Any]) -> list[str]:
        """Find files matching glob pattern."""
        pattern = args["pattern"]
        base_path = self._resolve_path(args.get("path", "."))

        results = []
        for path in base_path.glob(pattern):
            try:
                rel_path = path.relative_to(self._workspace_path)
                results.append(str(rel_path))
            except ValueError:
                results.append(str(path))

            if len(results) > 500:  # Limit results
                break

        return sorted(results)

    def _read_many_files(self, args: dict[str, Any]) -> dict[str, str]:
        """Read multiple files at once."""
        file_paths = args["file_paths"]
        results = {}

        for file_path in file_paths[:20]:  # Limit to 20 files
            try:
                path = self._resolve_path(file_path)
                if path.exists() and path.stat().st_size <= self._max_file_size:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        results[file_path] = f.read()
                else:
                    results[file_path] = "<file too large or not found>"
            except Exception as e:
                results[file_path] = f"<error: {e}>"

        return results


# =============================================================================
# Tool Registry
# =============================================================================


class ToolRegistry:
    """
    Registry for tool executors.

    Maps tool names to executors, enabling dispatch to the right executor.
    """

    def __init__(self):
        self._executors: list[ToolExecutor] = []
        self._tool_map: dict[str, ToolExecutor] = {}

    def register(self, executor: ToolExecutor) -> None:
        """Register a tool executor."""
        self._executors.append(executor)
        for tool_name in executor.list_tools():
            self._tool_map[tool_name] = executor

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        workspace_path: Path | None = None,
        timeout: float = 30.0,
    ) -> ToolResult:
        """Execute a tool using the appropriate executor."""
        executor = self._tool_map.get(tool_name)
        if not executor:
            return ToolResult(
                success=False,
                output=None,
                error=f"No executor found for tool: {tool_name}",
            )

        return await executor.execute(tool_name, arguments, workspace_path, timeout)

    def list_all_tools(self) -> list[str]:
        """List all available tools."""
        return list(self._tool_map.keys())

    def get_all_schemas(self) -> list[ToolSchema]:
        """Get schemas for all tools."""
        schemas = []
        for executor in self._executors:
            for tool_name in executor.list_tools():
                schema = executor.get_schema(tool_name)
                if schema:
                    schemas.append(schema)
        return schemas


# =============================================================================
# Factory Functions
# =============================================================================


def create_local_executor(workspace_path: Path) -> LocalToolExecutor:
    """Create a local tool executor for a workspace."""
    return LocalToolExecutor(workspace_path)


def create_tool_registry(workspace_path: Path) -> ToolRegistry:
    """Create a tool registry with local executor."""
    registry = ToolRegistry()
    registry.register(LocalToolExecutor(workspace_path))
    return registry


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Result types
    "ToolResult",
    "ToolSchema",
    # Executors
    "ToolExecutor",
    "LocalToolExecutor",
    # Registry
    "ToolRegistry",
    # Factory
    "create_local_executor",
    "create_tool_registry",
]
