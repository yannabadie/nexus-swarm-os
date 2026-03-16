"""
NEXUS V9 Command System

This module provides:
1. Legacy slash command utilities (from slash_commands.py)
2. Strategy Pattern-based command dispatch system (V9)

Usage (V9 - New):
    from core.interface_pkg.interface.commands import get_initialized_registry, CommandContext

    registry = get_initialized_registry()
    context = CommandContext(orchestrator, console, config, extras={"repl": repl})
    result = registry.dispatch("/status", context)

Usage (Legacy):
    from core.interface_pkg.interface.commands import is_slash_command, parse_command
"""

# V9: Strategy Pattern command dispatch
# Legacy: Re-export from slash_commands.py for backward compatibility
from core.interface_pkg.interface.slash_commands import (
    COMMAND_CATEGORIES,
    SLASH_COMMANDS,
    get_category_for_command,
    get_help_message,
    is_exit_command,
    is_slash_command,
    parse_command,
)

from .agents import register_agent_commands
from .evolution import register_evolution_commands
from .memory import register_memory_commands
from .misc import register_misc_commands
from .registry import (
    Command,
    CommandContext,
    CommandRegistry,
    CommandResult,
    CommandStatus,
    get_registry,
    reset_registry,
)
from .swarm import register_swarm_commands

# V9: Command modules
from .system import register_system_commands
from .workspace import register_workspace_commands

# Track if registry has been initialized
_registry_initialized = False


def get_initialized_registry() -> CommandRegistry:
    """
    Get the global CommandRegistry with all commands registered.

    This is the main entry point for the V9 command system.
    Returns a singleton registry with all commands pre-registered.

    Returns:
        CommandRegistry with all NEXUS commands registered
    """
    global _registry_initialized

    registry = get_registry()

    if not _registry_initialized:
        # Register all command groups
        register_system_commands(registry)
        register_evolution_commands(registry)
        register_swarm_commands(registry)
        register_agent_commands(registry)
        register_workspace_commands(registry)
        register_memory_commands(registry)
        register_misc_commands(registry)

        _registry_initialized = True

    return registry


def reset_initialized_registry() -> None:
    """Reset the registry (for testing)."""
    global _registry_initialized
    reset_registry()
    _registry_initialized = False


__all__ = [
    # V9 Strategy Pattern
    "Command",
    "CommandContext",
    "CommandRegistry",
    "CommandResult",
    "CommandStatus",
    "get_registry",
    "reset_registry",
    "get_initialized_registry",
    "reset_initialized_registry",
    # Legacy
    "is_slash_command",
    "is_exit_command",
    "parse_command",
    "get_help_message",
    "get_category_for_command",
    "SLASH_COMMANDS",
    "COMMAND_CATEGORIES",
]
