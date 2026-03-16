"""
Command Parser - Structured command parsing with argument validation.

V12.4 COGNITIVE BOOST - Task #56

Parses slash commands with typed arguments, validates input,
and provides suggestions for autocomplete.

Usage:
    from core.interface_pkg.interface.command_parser import CommandParser

    parser = CommandParser()

    # Define commands
    parser.define("swarm", "Launch swarm mode", args=[
        Arg("task", ArgType.STRING, required=True, help="Task description"),
        Arg("mode", ArgType.ENUM, choices=["parallel", "ping_pong", "red_blue"]),
        Arg("depth", ArgType.INT, default=3),
    ])

    # Parse user input
    result = parser.parse("/swarm 'Fix auth bug' --mode ping_pong --depth 5")

    # Get suggestions
    suggestions = parser.suggest("/sw")
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


class ArgType(Enum):
    """Argument types."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    ENUM = "enum"
    PATH = "path"


@dataclass
class Arg:
    """A command argument definition."""

    name: str
    arg_type: ArgType = ArgType.STRING
    required: bool = False
    default: Any = None
    choices: list[str] = field(default_factory=list)
    help: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.arg_type.value,
            "required": self.required,
            "default": self.default,
            "choices": self.choices,
            "help": self.help,
        }


@dataclass
class CommandDef:
    """A command definition."""

    name: str
    description: str = ""
    category: str = "general"
    args: list[Arg] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    @property
    def positional_args(self) -> list[Arg]:
        return [a for a in self.args if a.required]

    @property
    def optional_args(self) -> list[Arg]:
        return [a for a in self.args if not a.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "args": [a.to_dict() for a in self.args],
            "aliases": self.aliases,
        }


@dataclass
class ParsedCommand:
    """Result of parsing a command string."""

    command: str
    args: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    raw_input: str = ""
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "args": self.args,
            "flags": self.flags,
            "is_valid": self.is_valid,
            "errors": self.errors,
        }


@dataclass
class Suggestion:
    """A command suggestion."""

    text: str
    description: str = ""
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "description": self.description,
            "score": round(self.score, 3),
        }


# =============================================================================
# Command Parser
# =============================================================================


class CommandParser:
    """
    Structured command parser with validation and suggestions.

    Features:
    - Typed argument parsing (string, int, float, bool, enum)
    - Required vs optional arguments
    - Flag support (--flag)
    - Named arguments (--name value)
    - Positional arguments
    - Command aliases
    - Autocomplete suggestions
    - Input validation
    """

    def __init__(self, *, prefix: str = "/"):
        self._commands: dict[str, CommandDef] = {}
        self._aliases: dict[str, str] = {}  # alias -> command name
        self._prefix = prefix

    # =========================================================================
    # Define Commands
    # =========================================================================

    def define(
        self,
        name: str,
        description: str = "",
        *,
        category: str = "general",
        args: list[Arg] | None = None,
        aliases: list[str] | None = None,
    ) -> CommandDef:
        """
        Define a command.

        Args:
            name: Command name (without prefix)
            description: Human-readable description
            category: Command category
            args: Argument definitions
            aliases: Alternative names
        """
        cmd = CommandDef(
            name=name,
            description=description,
            category=category,
            args=args or [],
            aliases=aliases or [],
        )
        self._commands[name] = cmd
        for alias in cmd.aliases:
            self._aliases[alias] = name
        return cmd

    def undefine(self, name: str) -> bool:
        """Remove a command definition."""
        cmd = self._commands.pop(name, None)
        if cmd is None:
            return False
        for alias in cmd.aliases:
            self._aliases.pop(alias, None)
        return True

    def is_defined(self, name: str) -> bool:
        """Check if a command is defined."""
        return name in self._commands or name in self._aliases

    def get_definition(self, name: str) -> CommandDef | None:
        """Get a command definition (resolves aliases)."""
        if name in self._aliases:
            name = self._aliases[name]
        return self._commands.get(name)

    # =========================================================================
    # Parse
    # =========================================================================

    def parse(self, input_text: str) -> ParsedCommand:
        """
        Parse a command string.

        Handles:
        - /command positional_arg --named value --flag
        - Quoted strings for values with spaces
        - Type coercion based on arg definitions

        Args:
            input_text: Raw user input

        Returns:
            ParsedCommand with parsed args and validation errors
        """
        input_text = input_text.strip()

        # Extract command name
        if not input_text.startswith(self._prefix):
            return ParsedCommand(
                command="",
                raw_input=input_text,
                is_valid=False,
                errors=[f"Command must start with '{self._prefix}'"],
            )

        # Tokenize
        try:
            tokens = shlex.split(input_text)
        except ValueError as e:
            return ParsedCommand(
                command="",
                raw_input=input_text,
                is_valid=False,
                errors=[f"Parse error: {e}"],
            )

        if not tokens:
            return ParsedCommand(command="", raw_input=input_text, is_valid=False, errors=["Empty command"])

        cmd_name = tokens[0].lstrip(self._prefix)
        remaining = tokens[1:]

        # Resolve aliases
        resolved_name = self._aliases.get(cmd_name, cmd_name)
        cmd_def = self._commands.get(resolved_name)

        if cmd_def is None:
            return ParsedCommand(
                command=cmd_name,
                raw_input=input_text,
                is_valid=False,
                errors=[f"Unknown command: {cmd_name}"],
            )

        # Parse args
        parsed_args: dict[str, Any] = {}
        parsed_flags: dict[str, bool] = {}
        errors: list[str] = []
        positional_idx = 0

        i = 0
        while i < len(remaining):
            token = remaining[i]

            if token.startswith("--"):
                key = token[2:]
                # Check if it's a boolean flag
                arg_def = self._find_arg(cmd_def, key)
                if arg_def and arg_def.arg_type == ArgType.BOOL:
                    parsed_flags[key] = True
                elif i + 1 < len(remaining):
                    i += 1
                    parsed_args[key] = remaining[i]
                else:
                    errors.append(f"Missing value for --{key}")
            else:
                # Positional argument
                positionals = cmd_def.positional_args
                if positional_idx < len(positionals):
                    parsed_args[positionals[positional_idx].name] = token
                    positional_idx += 1
                else:
                    # Extra positional - add to first string arg or ignore
                    optional_strings = [a for a in cmd_def.optional_args if a.arg_type == ArgType.STRING]
                    if optional_strings and optional_strings[0].name not in parsed_args:
                        parsed_args[optional_strings[0].name] = token
                    else:
                        errors.append(f"Unexpected argument: {token}")
            i += 1

        # Apply defaults
        for arg in cmd_def.args:
            if arg.name not in parsed_args and arg.name not in parsed_flags and arg.default is not None:
                parsed_args[arg.name] = arg.default

        # Validate
        errors.extend(self._validate_args(cmd_def, parsed_args, parsed_flags))

        # Type coerce
        for arg in cmd_def.args:
            if arg.name in parsed_args:
                coerced, err = self._coerce_type(parsed_args[arg.name], arg)
                if err:
                    errors.append(err)
                else:
                    parsed_args[arg.name] = coerced

        return ParsedCommand(
            command=resolved_name,
            args=parsed_args,
            flags=parsed_flags,
            raw_input=input_text,
            is_valid=len(errors) == 0,
            errors=errors,
        )

    def _find_arg(self, cmd: CommandDef, name: str) -> Arg | None:
        """Find an argument definition by name."""
        for arg in cmd.args:
            if arg.name == name:
                return arg
        return None

    def _validate_args(
        self,
        cmd: CommandDef,
        args: dict[str, Any],
        flags: dict[str, bool],
    ) -> list[str]:
        """Validate parsed arguments against definition."""
        errors = []
        for arg in cmd.args:
            if arg.required and arg.name not in args and arg.name not in flags:
                errors.append(f"Missing required argument: {arg.name}")
            if arg.choices and arg.name in args and str(args[arg.name]) not in arg.choices:
                errors.append(
                    f"Invalid value for {arg.name}: '{args[arg.name]}'. Must be one of: {', '.join(arg.choices)}"
                )
        return errors

    def _coerce_type(self, value: Any, arg: Arg) -> tuple:
        """Coerce a value to the expected type. Returns (value, error)."""
        if arg.arg_type == ArgType.INT:
            try:
                return int(value), None
            except (ValueError, TypeError):
                return value, f"Argument '{arg.name}' must be an integer, got: {value}"
        elif arg.arg_type == ArgType.FLOAT:
            try:
                return float(value), None
            except (ValueError, TypeError):
                return value, f"Argument '{arg.name}' must be a float, got: {value}"
        elif arg.arg_type == ArgType.BOOL:
            if isinstance(value, bool):
                return value, None
            if str(value).lower() in ("true", "1", "yes"):
                return True, None
            if str(value).lower() in ("false", "0", "no"):
                return False, None
            return value, f"Argument '{arg.name}' must be a boolean, got: {value}"
        return value, None

    # =========================================================================
    # Suggestions
    # =========================================================================

    def suggest(self, partial: str) -> list[Suggestion]:
        """
        Get command suggestions for partial input.

        Args:
            partial: Partial command input

        Returns:
            List of suggestions sorted by relevance
        """
        partial = partial.strip().lstrip(self._prefix).lower()
        suggestions = []

        for name, cmd in self._commands.items():
            if name.lower().startswith(partial):
                suggestions.append(
                    Suggestion(
                        text=f"{self._prefix}{name}",
                        description=cmd.description,
                        score=1.0 if name.lower() == partial else 0.8,
                    )
                )
            # Check aliases
            for alias in cmd.aliases:
                if alias.lower().startswith(partial) and alias != name:
                    suggestions.append(
                        Suggestion(
                            text=f"{self._prefix}{alias}",
                            description=f"{cmd.description} (alias for {name})",
                            score=0.7,
                        )
                    )

        suggestions.sort(key=lambda s: (-s.score, s.text))
        return suggestions

    # =========================================================================
    # Listing
    # =========================================================================

    def list_commands(self, *, category: str | None = None) -> list[CommandDef]:
        """List all defined commands."""
        cmds = list(self._commands.values())
        if category:
            cmds = [c for c in cmds if c.category == category]
        return sorted(cmds, key=lambda c: c.name)

    def list_categories(self) -> list[str]:
        """List all categories."""
        return sorted(set(c.category for c in self._commands.values()))

    def get_help(self, command_name: str) -> str | None:
        """Get help text for a command."""
        cmd = self.get_definition(command_name)
        if cmd is None:
            return None
        parts = [f"{self._prefix}{cmd.name} - {cmd.description}"]
        if cmd.aliases:
            parts.append(f"  Aliases: {', '.join(cmd.aliases)}")
        for arg in cmd.args:
            req = "(required)" if arg.required else f"(default: {arg.default})"
            choices = f" [{', '.join(arg.choices)}]" if arg.choices else ""
            parts.append(f"  --{arg.name} [{arg.arg_type.value}]{choices} {req}")
            if arg.help:
                parts.append(f"    {arg.help}")
        return "\n".join(parts)

    # =========================================================================
    # State
    # =========================================================================

    @property
    def command_count(self) -> int:
        return len(self._commands)

    @property
    def alias_count(self) -> int:
        return len(self._aliases)

    def clear(self) -> None:
        """Clear all commands."""
        self._commands.clear()
        self._aliases.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_count": self.command_count,
            "alias_count": self.alias_count,
            "commands": {name: cmd.to_dict() for name, cmd in sorted(self._commands.items())},
        }
