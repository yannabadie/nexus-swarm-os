"""
Todo Handler - Task/plan management.

NEXUS V9.6 Sprint 5.2b - Extracted from tool_manager.py

Provides:
- TodoWriteHandler: Update and persist task lists
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult


class TodoWriteHandler(BaseHandler):
    """
    Handler for task/plan management.

    Manages todo lists like Claude Code's TodoWrite, saving
    to workspace/.nexus/plan.json.
    """

    # Status icons for display
    STATUS_ICONS = {"pending": "⏳", "in_progress": "🔄", "completed": "[OK]", "failed": "[NO]"}

    @property
    def tool_name(self) -> str:
        return "todo_write"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Update task/plan list.

        Args:
            args: {
                "todos": [
                    {
                        "id": 1,
                        "description": "Implement authentication",
                        "status": "pending|in_progress|completed",
                        "assigned_agent": "Claude|Gemini"
                    }
                ]
            }

        Returns:
            ToolResult with updated plan

        Examples:
            {
                "todos": [
                    {"id": 1, "description": "Read auth.py", "status": "completed", "assigned_agent": "Claude"},
                    {"id": 2, "description": "Fix bug", "status": "in_progress", "assigned_agent": "Claude"}
                ]
            }
        """
        todos = args.get("todos", [])

        if not isinstance(todos, list):
            return self._error("'todos' must be a list")

        try:
            # Save to workspace
            todo_file = self.workspace_path / ".nexus" / "plan.json"
            todo_file.parent.mkdir(parents=True, exist_ok=True)

            # Format todos
            formatted_todos = self._format_todos(todos)

            # Save to file
            todo_file.write_text(json.dumps(formatted_todos, indent=2), encoding="utf-8")

            # Format output
            output = self._format_output(formatted_todos, todo_file)

            return ToolResult(tool_name=self.tool_name, status="SUCCESS", output=output)

        except Exception as e:
            return self._error(f"TodoWrite error: {str(e)}")

    def _format_todos(self, todos: list) -> list:
        """Format and normalize todo items."""
        formatted = []
        for todo in todos:
            if not isinstance(todo, dict):
                continue

            formatted.append(
                {
                    "id": todo.get("id", len(formatted) + 1),
                    "description": todo.get("description", ""),
                    "status": todo.get("status", "pending"),
                    "assigned_agent": todo.get("assigned_agent", "Claude"),
                }
            )

        return formatted

    def _format_output(self, todos: list, todo_file: Path) -> str:
        """Format todos for display output."""
        output = f"Plan updated ({len(todos)} tasks):\n\n"

        for todo in todos:
            icon = self.STATUS_ICONS.get(todo["status"], "❓")
            output += f"{icon} #{todo['id']}: {todo['description']} [{todo['assigned_agent']}] ({todo['status']})\n"

        output += f"\nPlan saved to: {todo_file}"
        return output


def create_todo_handler(workspace_path: Path, validation_service: Any = None) -> TodoWriteHandler:
    """
    Factory function to create TodoWriteHandler.

    Args:
        workspace_path: Workspace root path
        validation_service: Optional validation service

    Returns:
        TodoWriteHandler instance
    """
    return TodoWriteHandler(workspace_path, validation_service)
