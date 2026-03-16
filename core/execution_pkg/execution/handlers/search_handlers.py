"""
Search Handlers - glob and grep.

NEXUS V9.5 Refactoring - Sprint 2

Extracted from tool_manager.py for Single Responsibility.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult


class GlobHandler(BaseHandler):
    """
    Handler for finding files by pattern (like Claude Code's Glob tool).

    Patterns:
        * - matches any characters except /
        ** - matches any characters including /
        ? - matches single character
        [abc] - matches one of a, b, c
    """

    @property
    def tool_name(self) -> str:
        return "glob"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Find files matching a pattern.

        Args:
            args: {
                "pattern": "**/*.py" (glob pattern),
                "path": "./src" (optional, default: workspace root),
                "max_results": 100 (optional, default: 100)
            }

        Returns:
            ToolResult with matching file paths
        """
        pattern = args.get("pattern", "")
        search_path_str = args.get("path", ".")
        max_results = args.get("max_results", 100)

        if not pattern:
            return self._error("Pattern parameter is required")

        try:
            # Resolve search path
            search_path = self._resolve_path(search_path_str)

            # Validate path
            if not self._validate_path(search_path, "list"):
                return ToolResult(
                    tool_name=self.tool_name,
                    status="BLOCKED",
                    output="",
                    error=f"[SECURITY] Search not allowed for: {search_path}",
                )

            if not search_path.exists():
                return self._fail(f"Search path does not exist: {search_path}")

            # Find matching files
            matches = []
            for file_path in search_path.rglob("*"):
                if file_path.is_file():
                    # Check if matches pattern
                    if file_path.match(pattern):
                        try:
                            rel_path = file_path.relative_to(search_path)
                        except ValueError:
                            rel_path = file_path.relative_to(self.workspace_path)
                        matches.append(str(rel_path))

                    if len(matches) >= max_results:
                        break

            # Sort matches
            matches.sort()

            if matches:
                output = f"Found {len(matches)} files matching '{pattern}':\n\n"
                output += "\n".join(matches)

                if len(matches) >= max_results:
                    output += f"\n\n[Limited to {max_results} results]"

                return self._ok(output)
            else:
                return self._ok(f"No files found matching '{pattern}'")

        except Exception as e:
            return self._error(f"Glob error: {str(e)}")


class GrepHandler(BaseHandler):
    """
    Handler for searching code by pattern (like Claude Code's Grep tool).
    """

    @property
    def tool_name(self) -> str:
        return "grep"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Search code for patterns.

        Args:
            args: {
                "pattern": "def.*async" (regex pattern),
                "path": "./src" (optional, default: workspace root),
                "file_pattern": "*.py" (optional, filter files),
                "case_sensitive": true (optional, default: true),
                "max_results": 100 (optional, default: 100)
            }

        Returns:
            ToolResult with matching lines
        """
        pattern = args.get("pattern", "")
        search_path_str = args.get("path", ".")
        file_pattern = args.get("file_pattern", "*")
        case_sensitive = args.get("case_sensitive", True)
        max_results = args.get("max_results", 100)

        if not pattern:
            return self._error("Pattern parameter is required")

        try:
            # Resolve search path
            search_path = self._resolve_path(search_path_str)

            # Validate path
            if not self._validate_path(search_path, "list"):
                return ToolResult(
                    tool_name=self.tool_name,
                    status="BLOCKED",
                    output="",
                    error=f"[SECURITY] Search not allowed for: {search_path}",
                )

            if not search_path.exists():
                return self._fail(f"Search path does not exist: {search_path}")

            # Compile regex pattern
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return self._error(f"Invalid regex pattern: {e}")

            # Search files
            matches = []
            files_searched = 0

            for file_path in search_path.rglob(file_pattern):
                if not file_path.is_file():
                    continue

                files_searched += 1

                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    lines = content.split("\n")

                    for line_num, line in enumerate(lines, start=1):
                        if regex.search(line):
                            try:
                                rel_path = file_path.relative_to(self.workspace_path)
                            except ValueError:
                                rel_path = file_path

                            matches.append(f"{rel_path}:{line_num}: {line.strip()}")

                            if len(matches) >= max_results:
                                break

                except (UnicodeDecodeError, PermissionError):
                    continue

                if len(matches) >= max_results:
                    break

            # Format output
            if matches:
                output = f"Found {len(matches)} matches for '{pattern}' in {files_searched} files:\n\n"
                output += "\n".join(matches)

                if len(matches) >= max_results:
                    output += f"\n\n[Limited to {max_results} results]"

                return self._ok(output)
            else:
                return self._ok(f"No matches found for '{pattern}' in {files_searched} files")

        except Exception as e:
            return self._error(f"Grep error: {str(e)}")


# Factory function
def create_search_handlers(
    workspace_path: Path,
    validation_service: Any | None = None,
) -> dict[str, BaseHandler]:
    """
    Create search handlers.

    Args:
        workspace_path: Workspace root
        validation_service: Optional ValidationService

    Returns:
        Dict mapping tool names to handlers
    """
    return {
        "glob": GlobHandler(workspace_path, validation_service),
        "grep": GrepHandler(workspace_path, validation_service),
    }
