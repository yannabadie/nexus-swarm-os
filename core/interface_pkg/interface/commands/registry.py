"""
V9 Command Registry - Strategy Pattern for REPL commands.

This module provides:
- Command: Abstract base class for all commands
- CommandContext: Context passed to command execution
- CommandRegistry: Central registry with dispatch logic
- CommandResult: Structured result from command execution

The goal is to replace the 26-branch elif in repl.py with a clean,
extensible, testable command dispatch system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config
    from core.interface_pkg.interface.console_v7 import ConsoleV7
    from core.orchestration_v7 import OrchestratorV7


class CommandStatus(Enum):
    """Status of command execution."""

    SUCCESS = "success"
    ERROR = "error"
    HELP = "help"
    NOT_FOUND = "not_found"
    INVALID_ARGS = "invalid_args"


@dataclass
class CommandResult:
    """
    Result from command execution.

    Attributes:
        status: Execution status
        message: Human-readable message to display
        data: Optional structured data from command
        continue_session: If False, REPL should exit
    """

    status: CommandStatus
    message: str
    data: dict[str, Any] | None = None
    continue_session: bool = True


@dataclass
class CommandContext:
    """
    Context passed to commands during execution.

    Provides access to orchestrator, console, and config without
    commands needing to know about the REPL internals.
    """

    orchestrator: "OrchestratorV7"
    console: "ConsoleV7"
    config: "Config"
    # Optional extras that some commands may need
    extras: dict[str, Any] = field(default_factory=dict)


class Command(ABC):
    """
    Abstract base class for REPL commands.

    Subclasses must implement:
    - name: The primary command name (e.g., "/status")
    - execute: The command logic

    Optional overrides:
    - aliases: Alternative names for the command
    - description: Help text for the command
    - usage: Usage examples
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Primary command name.

        Must start with "/" for slash commands.
        Example: "/status"
        """
        pass

    @abstractmethod
    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """
        Execute the command.

        Args:
            args: Arguments string (everything after the command name)
            context: Execution context with orchestrator, console, config

        Returns:
            CommandResult with status and message
        """
        pass

    @property
    def aliases(self) -> list[str]:
        """
        Alternative names for this command.

        Default: no aliases
        Example: ["/s"] for "/status"
        """
        return []

    @property
    def description(self) -> str:
        """Short description for help text."""
        return "No description available."

    @property
    def usage(self) -> str:
        """Usage examples for help text."""
        return f"{self.name}"


class CommandRegistry:
    """
    Central registry for all REPL commands.

    Provides:
    - Command registration with alias support
    - Dispatch by command name
    - Help generation
    - Listing available commands
    """

    def __init__(self):
        """Initialize empty registry."""
        self._commands: dict[str, Command] = {}
        self._primary_names: list[str] = []

    def register(self, command: Command) -> None:
        """
        Register a command with the registry.

        Args:
            command: Command instance to register

        Raises:
            ValueError: If command name conflicts with existing
        """
        name = command.name.lower()

        if name in self._commands:
            raise ValueError(f"Command '{name}' already registered")

        self._commands[name] = command
        self._primary_names.append(name)

        # Register aliases
        for alias in command.aliases:
            alias_lower = alias.lower()
            if alias_lower in self._commands:
                raise ValueError(f"Alias '{alias_lower}' conflicts with existing command")
            self._commands[alias_lower] = command

    def dispatch(self, input_str: str, context: CommandContext) -> CommandResult:
        """
        Dispatch input to the appropriate command handler.

        Args:
            input_str: Full input string (e.g., "/status detail")
            context: Execution context

        Returns:
            CommandResult from command execution
        """
        if not input_str.strip():
            return CommandResult(status=CommandStatus.INVALID_ARGS, message="Empty command")

        parts = input_str.strip().split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd_name not in self._commands:
            return CommandResult(
                status=CommandStatus.NOT_FOUND,
                message=f"Unknown command: {cmd_name}. Type /help for available commands.",
            )

        try:
            return self._commands[cmd_name].execute(args, context)
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Command error: {e}")

    def get_command(self, name: str) -> Command | None:
        """Get command by name or alias."""
        return self._commands.get(name.lower())

    def list_commands(self) -> list[str]:
        """List all primary command names (not aliases)."""
        return sorted(self._primary_names)

    def get_help_text(self) -> str:
        """Generate help text for all registered commands."""
        lines = ["Available commands:", ""]

        for name in sorted(self._primary_names):
            cmd = self._commands[name]
            aliases_str = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  {name}{aliases_str}")
            lines.append(f"    {cmd.description}")
            lines.append("")

        return "\n".join(lines)

    def __len__(self) -> int:
        """Return number of primary commands."""
        return len(self._primary_names)

    def __contains__(self, name: str) -> bool:
        """Check if command is registered."""
        return name.lower() in self._commands


# =============================================================================
# V10 PRISM: Multi-Tenant Command Registry Access
# =============================================================================
import threading  # noqa: E402  # singleton setup after class definition

_registry_instance: CommandRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> CommandRegistry:
    """
    Get the command registry for the current tenant context.

    V10 PRISM: Returns tenant-scoped registry via ServiceFactory.
    Falls back to global singleton if no context is active.

    Thread-safe with double-checked locking.

    Returns:
        CommandRegistry instance scoped to current tenant
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ...context import has_active_session

        if has_active_session():
            from ...factory import ServiceFactory

            return ServiceFactory.get_command_registry()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    global _registry_instance

    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = CommandRegistry()

    return _registry_instance


def reset_registry() -> None:
    """
    Reset the global command registry (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _registry_instance
    with _registry_lock:
        _registry_instance = None

    # V10: Also clear factory cache
    try:
        from ...context import get_current_session_or_none
        from ...factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
