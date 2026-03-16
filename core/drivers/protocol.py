"""
Driver Protocol - V11 Abstraction Layer for CLI/API Independence.

F31 Fix: Decouples orchestration from CLI-bound implementation.

This protocol defines the contract that ALL drivers must implement,
whether CLI-based (current) or API-based (future).

Benefits:
1. Orchestration code works with any driver implementation
2. Can swap CLI for API without changing HiveMind/Swarm/FSM code
3. Enables testing with mock drivers
4. Prepares for CEREBRO UI backend (needs API drivers for WebSocket)

Architecture:
```
                    +------------------+
                    |  DriverProtocol  | (ABC)
                    +--------+---------+
              +--------------+--------------+
              v              v              v
     +----------------+ +----------------+ +----------------+
     | AsyncCLIDriver | | AsyncAPIDriver | |   MockDriver   |
     |  (subprocess)  | |   (httpx)      | |   (testing)    |
     +----------------+ +----------------+ +----------------+
              |              |              |
     +--------+--------+    ...           ...
     v                 v
  Gemini CLI      Claude CLI
```

Usage:
    from core.drivers.protocol import DriverProtocol, DriverResponse

    # Any driver implementing DriverProtocol can be used
    async def run_agent(driver: DriverProtocol, prompt: str):
        response = await driver.invoke(prompt)
        return response.content

Author: Claude (NEXUS V11)
Date: 2025-12-15
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

# =============================================================================
# Response Types
# =============================================================================


class DriverResponseStatus(Enum):
    """Status of a driver response."""

    SUCCESS = auto()
    ERROR = auto()
    TIMEOUT = auto()
    CANCELLED = auto()
    RATE_LIMITED = auto()
    AUTHENTICATION_ERROR = auto()


@dataclass
class ToolCall:
    """Represents a tool/function call from the LLM."""

    name: str
    arguments: dict[str, Any]
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "id": self.id,
        }


@dataclass
class DriverResponse:
    """
    Unified response format from any driver implementation.

    Abstracts away CLI vs API response differences:
    - CLI: Parses JSON from stdout, extracts tool calls from message
    - API: Parses response JSON directly, tool calls in structured format

    Both result in the same DriverResponse for orchestration code.
    """

    # Core content
    content: str
    status: DriverResponseStatus = DriverResponseStatus.SUCCESS

    # Metadata
    model: str | None = None
    provider: str = "unknown"  # "gemini" or "claude"
    session_id: str | None = None

    # Tool calls (if any)
    tool_calls: list[ToolCall] = field(default_factory=list)

    # Timing and metrics
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    # Error information (if status != SUCCESS)
    error_message: str | None = None
    error_code: str | None = None

    # Extended fields (populated by SDK drivers)
    finish_reason: str | None = None
    cost_usd: float = 0.0

    # Raw response (for debugging)
    raw: dict[str, Any] | None = None

    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_success(self) -> bool:
        """Check if response was successful."""
        return self.status == DriverResponseStatus.SUCCESS

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "status": self.status.name,
            "model": self.model,
            "provider": self.provider,
            "session_id": self.session_id,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StreamChunk:
    """A chunk of streamed response."""

    content: str
    is_final: bool = False
    tool_call: ToolCall | None = None

    # Metadata (only populated in final chunk)
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    # Extended fields (populated by SDK drivers)
    finish_reason: str | None = None
    error: str | None = None


# =============================================================================
# Driver Protocol (ABC)
# =============================================================================


@runtime_checkable
class DriverProtocol(Protocol):
    """
    Protocol that ALL drivers must implement.

    This is the contract between orchestration code and driver implementations.
    Whether a driver uses CLI subprocess or direct API calls, it must implement
    these methods with the same signature.

    F31: This protocol enables CLI/API independence.
    """

    @property
    def provider(self) -> str:
        """
        Provider identifier ("gemini" or "claude").

        Used for routing, metrics, and logging.
        """
        ...

    @property
    def model(self) -> str:
        """
        Model identifier (e.g., "gemini-3.1-pro-preview", "claude-sonnet-4-6").

        Used for routing and metrics.
        """
        ...

    async def invoke(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        isolated_env: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> DriverResponse:
        """
        Invoke the LLM and return the complete response.

        Args:
            prompt: The user prompt/message to send
            session_id: Optional session ID for context persistence
            system_prompt: Optional system prompt override
            tools: Optional list of tools to make available
            isolated_env: Optional environment dict for CLI isolation (V9.7.1)
            timeout: Optional timeout override in seconds
            **kwargs: Additional driver-specific options

        Returns:
            DriverResponse with content, status, and metadata

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            asyncio.CancelledError: If cancelled (MUST be re-raised)
        """
        ...

    async def invoke_stream(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        isolated_env: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """
        Invoke the LLM and stream the response.

        Same parameters as invoke(), but yields StreamChunk objects
        as they become available.

        Yields:
            StreamChunk objects, with is_final=True on last chunk
        """
        ...
        yield  # Make this a generator

    async def cancel(self, session_id: str | None = None) -> bool:
        """
        Cancel an ongoing invocation.

        Args:
            session_id: If provided, cancel specific session.
                       If None, cancel all active invocations.

        Returns:
            True if cancellation was successful
        """
        ...

    async def health_check(self) -> bool:
        """
        Check if the driver/provider is healthy.

        Used by circuit breaker and monitoring.

        Returns:
            True if healthy and ready to accept requests
        """
        ...


# =============================================================================
# Session Protocol (F32 preparation)
# =============================================================================


@runtime_checkable
class SessionProtocol(Protocol):
    """
    Protocol for session management abstraction.

    F32: Decouples session handling from CLI-specific features like --resume.

    CLI sessions: Use --resume flag, session stored in ~/.gemini/tmp/
    API sessions: Use conversation_id in request body
    """

    @property
    def session_id(self) -> str:
        """Unique session identifier."""
        ...

    @property
    def is_active(self) -> bool:
        """Whether session is currently active."""
        ...

    async def start(self) -> str:
        """
        Start a new session.

        Returns:
            New session ID
        """
        ...

    async def resume(self, session_id: str) -> bool:
        """
        Resume an existing session.

        Args:
            session_id: Session to resume

        Returns:
            True if session was found and resumed
        """
        ...

    async def end(self) -> None:
        """End the current session."""
        ...

    def get_context_for_driver(self) -> dict[str, Any]:
        """
        Get session context in driver-appropriate format.

        CLI: Returns {"resume_flag": "--resume latest"} or similar
        API: Returns {"conversation_id": "..."} or similar
        """
        ...


# =============================================================================
# Tool Executor Protocol (F33 preparation)
# =============================================================================


@runtime_checkable
class ToolExecutorProtocol(Protocol):
    """
    Protocol for tool execution abstraction.

    F33: Decouples tool execution from CLI-provided tools.

    CLI: Tools like read_file, grep are executed by the CLI
    API: We must implement tool execution ourselves
    """

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        workspace_path: str | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute (e.g., "read_file")
            arguments: Tool arguments
            workspace_path: Working directory for file operations
            timeout: Maximum execution time

        Returns:
            Tool result as dictionary
        """
        ...

    def list_available_tools(self) -> list[str]:
        """
        List all available tools.

        Returns:
            List of tool names
        """
        ...

    def get_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """
        Get JSON schema for a tool.

        Args:
            tool_name: Tool to get schema for

        Returns:
            JSON schema dict, or None if tool not found
        """
        ...


# =============================================================================
# Abstract Base Classes (for implementation guidance)
# =============================================================================


class BaseAsyncDriver(abc.ABC):
    """
    Abstract base class for async drivers.

    Provides common functionality and enforces DriverProtocol.
    Implementations should inherit from this class.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        timeout: float = 300.0,
    ):
        self._provider = provider
        self._model = model
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @abc.abstractmethod
    async def invoke(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        isolated_env: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> DriverResponse:
        """Implement in subclass."""
        ...

    @abc.abstractmethod
    async def invoke_stream(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        isolated_env: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Implement in subclass."""
        ...
        yield  # pragma: no cover

    @abc.abstractmethod
    async def cancel(self, session_id: str | None = None) -> bool:
        """Implement in subclass."""
        ...

    async def health_check(self) -> bool:
        """
        Default health check - can be overridden.

        Returns True by default. Subclasses should implement
        actual health checking (API ping, etc.)
        """
        return True

    def _create_error_response(
        self,
        error_message: str,
        error_code: str = "DRIVER_ERROR",
        status: DriverResponseStatus = DriverResponseStatus.ERROR,
    ) -> DriverResponse:
        """Create a standardized error response."""
        return DriverResponse(
            content="",
            status=status,
            provider=self._provider,
            model=self._model,
            error_message=error_message,
            error_code=error_code,
        )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Response types
    "DriverResponseStatus",
    "DriverResponse",
    "ToolCall",
    "StreamChunk",
    # Protocols
    "DriverProtocol",
    "SessionProtocol",
    "ToolExecutorProtocol",
    # Base class
    "BaseAsyncDriver",
]
