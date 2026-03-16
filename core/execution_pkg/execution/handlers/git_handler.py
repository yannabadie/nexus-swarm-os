"""
Git Handler - Execute git operations.

NEXUS V9.6 Sprint 5.2b - Extracted from tool_manager.py

Supports: status, diff, log, show, branch, pull (read-only operations)
Blocked: push, commit, add, reset, checkout, merge, rebase (security)
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult


class GitHandler(BaseHandler):
    """
    Handler for git operations.

    Only read-only operations are allowed for security.
    """

    # Read-only operations (safe)
    SAFE_OPS = {"status", "diff", "log", "show", "branch"}

    # Write operations (blocked for security)
    BLOCKED_OPS = {"push", "commit", "add", "reset", "checkout", "merge", "rebase"}

    @property
    def tool_name(self) -> str:
        return "git"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Execute git operations.

        Args:
            args: {
                "operation": "add|commit|status|diff|log|push|pull",
                "args": "additional arguments (optional)"
            }

        Returns:
            ToolResult with git output

        Examples:
            {"operation": "status"}
            {"operation": "diff", "args": "HEAD~1"}
            {"operation": "log", "args": "--oneline -5"}
        """
        operation = args.get("operation", "")
        additional_args = args.get("args", "")

        # Security check: Block write operations
        if operation.lower() in self.BLOCKED_OPS:
            return ToolResult(
                tool_name=self.tool_name,
                status="BLOCKED",
                output="",
                error=f"[SECURITY] Git '{operation}' BLOCKED. Parent repo is READ-ONLY.",
            )

        # Validate operation
        allowed_ops = list(self.SAFE_OPS) + ["pull"]
        if operation.lower() not in allowed_ops:
            return self._error(f"Invalid git operation: {operation}. Allowed: {', '.join(allowed_ops)}")

        try:
            # Build git command
            command = ["git", operation]
            if additional_args:
                command.extend(shlex.split(additional_args))

            # Execute git command
            result = subprocess.run(
                command,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode == 0:
                return ToolResult(
                    tool_name=self.tool_name,
                    status="SUCCESS",
                    output=result.stdout or "(no output)",
                    error=result.stderr,
                )
            else:
                return ToolResult(
                    tool_name=self.tool_name,
                    status="FAILURE",
                    output=result.stdout,
                    error=result.stderr or f"Git command failed with return code {result.returncode}",
                )

        except subprocess.TimeoutExpired:
            return self._error(f"Git command timed out after 60s: git {operation} {additional_args}")
        except Exception as e:
            return self._error(f"Git execution error: {str(e)}")


def create_git_handler(workspace_path: Path, validation_service: Any = None) -> GitHandler:
    """
    Factory function to create GitHandler.

    Args:
        workspace_path: Workspace root path
        validation_service: Optional validation service

    Returns:
        GitHandler instance
    """
    return GitHandler(workspace_path, validation_service)
