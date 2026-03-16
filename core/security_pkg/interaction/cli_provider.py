"""
CLIProvider - Interactive Command-Line Interaction Provider.

NEXUS V9.8 DETOX - Headless Refactoring

This provider uses run_in_executor to prevent input() from blocking
the async event loop. This is critical for:
- Async REPL operations
- Concurrent task handling
- Signal handling (Ctrl+C)

Author: Claude (NEXUS DETOX)
Date: 2025-12-13
"""

import asyncio
import sys

from .base import Choice, InteractionLevel, InteractionProvider


class CLIProvider(InteractionProvider):
    """
    Interactive CLI provider using run_in_executor.

    This provider wraps blocking input() calls in run_in_executor
    to prevent them from blocking the async event loop.

    Usage:
        provider = CLIProvider()
        name = await provider.ask("What's your name?", default="User")
        if await provider.confirm("Continue?", default=True):
            await provider.announce("Proceeding...")
    """

    def __init__(self, prefix: str = ""):
        """
        Initialize CLI provider.

        Args:
            prefix: Optional prefix for prompts (e.g., "nexus7> ")
        """
        self.prefix = prefix

    async def ask(
        self, prompt: str, default: str | None = None, timeout: float | None = None, required: bool = False
    ) -> str:
        """Ask user for input via terminal."""
        # V12.4 FIX F19: Use get_running_loop() instead of deprecated get_event_loop()
        loop = asyncio.get_running_loop()

        # Build display prompt
        display = f"{self.prefix}{prompt}"
        if default:
            display += f" [{default}]"
        display += ": "

        try:
            if timeout:
                result = await asyncio.wait_for(loop.run_in_executor(None, input, display), timeout=timeout)
            else:
                result = await loop.run_in_executor(None, input, display)

            result = result.strip()

            # Return input or default
            if result:
                return result
            elif default is not None:
                return default
            elif required:
                # Re-ask if required and empty
                print("  [Input required, please enter a value]")
                return await self.ask(prompt, default, timeout, required)
            else:
                return ""

        except TimeoutError:
            if default is not None:
                print(f"\n  [Timeout, using default: {default}]")
                return default
            raise

        except EOFError:
            # Handle Ctrl+D
            if default is not None:
                return default
            return ""

    async def confirm(self, prompt: str, default: bool = False, timeout: float | None = None) -> bool:
        """Ask for yes/no confirmation."""
        hint = "[Y/n]" if default else "[y/N]"
        response = await self.ask(f"{prompt} {hint}", timeout=timeout)

        if not response:
            return default

        return response.lower() in ("y", "yes", "oui", "o", "1", "true")

    async def choose(
        self, prompt: str, choices: list[Choice], default: str | None = None, timeout: float | None = None
    ) -> str:
        """Present numbered choices to user."""
        # Display choices
        print(f"\n{self.prefix}{prompt}")
        for i, choice in enumerate(choices, 1):
            marker = "*" if choice.key == default else " "
            desc = f" - {choice.description}" if choice.description else ""
            print(f"  {marker}[{i}] {choice.label}{desc}")

        # Build valid keys map
        valid_keys = {str(i): c.key for i, c in enumerate(choices, 1)}
        valid_keys.update({c.key.lower(): c.key for c in choices})

        while True:
            response = await self.ask("Enter choice (number or key)", default=default, timeout=timeout)

            key = valid_keys.get(response.lower())
            if key:
                return key

            if default and not response:
                return default

            print(f"  [Invalid choice. Options: {', '.join(valid_keys.keys())}]")

    async def announce(self, message: str, level: InteractionLevel = InteractionLevel.INFO) -> None:
        """Print message to console with level prefix."""
        prefix_map = {
            InteractionLevel.DEBUG: "[DEBUG]",
            InteractionLevel.INFO: "[INFO]",
            InteractionLevel.WARNING: "[WARN]",
            InteractionLevel.ERROR: "[ERROR]",
            InteractionLevel.CRITICAL: "[CRITICAL]",
        }

        prefix = prefix_map.get(level, "")
        output = sys.stderr if level in (InteractionLevel.ERROR, InteractionLevel.CRITICAL) else sys.stdout

        print(f"{prefix} {message}" if prefix else message, file=output)

    async def progress(self, message: str, current: int, total: int) -> None:
        """Display progress bar."""
        if total <= 0:
            return

        pct = current / total * 100
        bar_width = 30
        filled = int(bar_width * current / total)
        bar = "=" * filled + "-" * (bar_width - filled)

        print(f"\r[{bar}] {pct:5.1f}% - {message}", end="", flush=True)

        if current >= total:
            print()  # Newline at completion

    @property
    def is_interactive(self) -> bool:
        """CLI provider is interactive."""
        return True
