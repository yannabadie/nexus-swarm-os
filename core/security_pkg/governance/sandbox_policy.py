"""
Sandbox Policy - Tool execution permissions and security policies

Centralizes all tool blocking and permission logic that was previously
scattered across orchestration_v7.py and tool_manager.py.

## Security Levels

### SAFE_TOOLS
Tools that can be executed during any state, including brainstorming:
- read, read_file: File reading (safe)
- glob, grep: Search operations (safe)
- list_dir: Directory listing (safe)
- web_search, web_fetch: Web access (safe)

### BLOCKED_TOOLS
Tools that modify state and are blocked during brainstorming:
- write, write_file, edit: File modifications
- bash, run_shell_command: Shell execution
- git: Version control operations
- todo_write: Task management

### CONDITIONAL_TOOLS
Tools that may be allowed in certain contexts:
- git (read-only operations like status, log, diff)
"""

# ============================================================================
# SAFE TOOLS - Can be executed in any state
# ============================================================================
SAFE_TOOLS: set[str] = {
    "read",
    "read_file",  # File reading
    "glob",
    "grep",  # Search operations
    "list_dir",  # Directory listing
    "web_search",
    "web_fetch",  # Web access
}


# ============================================================================
# BLOCKED TOOLS - Never allowed during brainstorming
# ============================================================================
BLOCKED_TOOLS: set[str] = {
    "write",
    "write_file",  # File creation/modification
    "edit",  # File editing
    "bash",
    "run_shell_command",  # Shell execution
    "git",  # Git operations (write)
    "todo_write",  # Task management
}


# ============================================================================
# CONDITIONAL TOOLS - Allowed in some contexts
# ============================================================================
CONDITIONAL_TOOLS: set[str] = {
    "git"  # Read-only git operations (status, log, diff)
}


# ============================================================================
# TOOL ALIASES - Name normalization
# ============================================================================
TOOL_ALIASES: dict[str, str] = {"read_file": "read", "write_file": "write", "run_shell_command": "bash"}


class SandboxPolicy:
    """
    Centralized sandbox policy for tool execution permissions.
    """

    @staticmethod
    def is_tool_safe(tool_name: str) -> bool:
        """
        Check if a tool is safe to execute in any context.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool is safe, False otherwise
        """
        normalized_name = TOOL_ALIASES.get(tool_name, tool_name)
        return normalized_name in SAFE_TOOLS

    @staticmethod
    def is_tool_blocked(tool_name: str) -> bool:
        """
        Check if a tool is blocked during brainstorming state.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool is blocked, False otherwise
        """
        normalized_name = TOOL_ALIASES.get(tool_name, tool_name)
        return normalized_name in BLOCKED_TOOLS

    @staticmethod
    def is_tool_conditional(tool_name: str) -> bool:
        """
        Check if a tool is conditional (allowed in some contexts).

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool is conditional, False otherwise
        """
        normalized_name = TOOL_ALIASES.get(tool_name, tool_name)
        return normalized_name in CONDITIONAL_TOOLS

    @staticmethod
    def can_execute_tool(tool_name: str, context: str = "any") -> bool:
        """
        Check if a tool can be executed in the given context.

        Args:
            tool_name: Name of the tool to check
            context: Execution context ("brainstorming", "execution", "any")

        Returns:
            True if tool can be executed, False otherwise
        """
        if context == "brainstorming":
            return SandboxPolicy.is_tool_safe(tool_name)
        else:
            # In execution context, allow safe + conditional tools
            return SandboxPolicy.is_tool_safe(tool_name) or SandboxPolicy.is_tool_conditional(tool_name)

    @staticmethod
    def get_blocked_reason(tool_name: str) -> str:
        """
        Get the reason why a tool is blocked.

        Args:
            tool_name: Name of the blocked tool

        Returns:
            Human-readable reason for blocking
        """
        reasons = {
            "write": "File modification blocked during brainstorming",
            "write_file": "File creation blocked during brainstorming",
            "edit": "File editing blocked during brainstorming",
            "bash": "Shell execution blocked during brainstorming",
            "run_shell_command": "Shell execution blocked during brainstorming",
            "git": "Git write operations blocked during brainstorming",
            "todo_write": "Task management blocked during brainstorming",
        }
        normalized_name = TOOL_ALIASES.get(tool_name, tool_name)
        return reasons.get(normalized_name, f"Tool '{tool_name}' blocked by sandbox policy")
