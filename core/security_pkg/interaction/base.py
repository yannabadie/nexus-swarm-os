"""
InteractionProvider - Abstract Base for User Interaction.

NEXUS V9.8 DETOX - Headless Refactoring

This module provides an abstraction layer between NEXUS core logic
and user interaction (input/output). This enables:
- CLI mode: Interactive terminal with input()
- Headless mode: Non-blocking with defaults (for servers)
- Queue mode: Future support for async message queues

Author: Claude (NEXUS DETOX)
Date: 2025-12-13
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class InteractionLevel(Enum):
    """Log levels for announcements."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InteractionRequiredError(Exception):
    """
    Raised when headless mode cannot answer a critical question.

    This exception should be caught at the API boundary and
    converted to an appropriate HTTP response (e.g., 422 Unprocessable).
    """

    def __init__(self, prompt: str, context: str | None = None):
        self.prompt = prompt
        self.context = context
        message = f"User interaction required: {prompt}"
        if context:
            message += f" (context: {context})"
        super().__init__(message)


@dataclass
class Choice:
    """A choice option for multiple-choice prompts."""

    key: str
    label: str
    description: str | None = None


class InteractionProvider(ABC):
    """
    Abstract base class for all interaction providers.

    Implementations:
    - CLIProvider: Interactive terminal (uses run_in_executor for async safety)
    - HeadlessProvider: Non-blocking with defaults (for servers/daemons)

    All methods are async to support non-blocking I/O in async contexts.
    """

    @abstractmethod
    async def ask(
        self, prompt: str, default: str | None = None, timeout: float | None = None, required: bool = False
    ) -> str:
        """
        Ask user for text input.

        Args:
            prompt: The question to ask
            default: Default value if no input (or headless mode)
            timeout: Timeout in seconds (None = no timeout)
            required: If True and headless with no default, raise error

        Returns:
            User input string, or default if applicable

        Raises:
            InteractionRequiredError: If required=True and no input possible
            asyncio.TimeoutError: If timeout exceeded
        """
        pass

    @abstractmethod
    async def confirm(self, prompt: str, default: bool = False, timeout: float | None = None) -> bool:
        """
        Ask for yes/no confirmation.

        Args:
            prompt: The confirmation question
            default: Default value if no input
            timeout: Timeout in seconds

        Returns:
            True for yes, False for no
        """
        pass

    @abstractmethod
    async def choose(
        self, prompt: str, choices: list[Choice], default: str | None = None, timeout: float | None = None
    ) -> str:
        """
        Present multiple choices to user.

        Args:
            prompt: The question
            choices: List of Choice objects
            default: Default choice key
            timeout: Timeout in seconds

        Returns:
            Key of selected choice
        """
        pass

    @abstractmethod
    async def announce(self, message: str, level: InteractionLevel = InteractionLevel.INFO) -> None:
        """
        Announce a message to the user.

        Args:
            message: Message content
            level: Importance level (affects display/logging)
        """
        pass

    @abstractmethod
    async def progress(self, message: str, current: int, total: int) -> None:
        """
        Report progress to user.

        Args:
            message: Progress description
            current: Current step number
            total: Total steps
        """
        pass

    @property
    @abstractmethod
    def is_interactive(self) -> bool:
        """Returns True if this provider supports real user interaction."""
        pass
