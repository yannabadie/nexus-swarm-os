"""
CLI Driver Adapters - V11 Wrappers for Protocol Compliance.

F31 Fix: Adapts existing CLI drivers to implement DriverProtocol.

These adapters wrap AsyncGeminiDriver and AsyncClaudeDriver to provide
a unified interface that matches DriverProtocol. This enables:

1. Orchestration code to work with any DriverProtocol implementation
2. Future API drivers to be swapped in without changing orchestration
3. Standardized response format (DriverResponse) across all providers

Architecture:
```
    +-------------------------+
    |     DriverProtocol      |
    +------------+------------+
                 |
    +------------+------------+
    |    CLIDriverAdapter     | (this file)
    +------------+------------+
        +--------+--------+
        v                 v
  +---------------+ +---------------+
  | AsyncGemini   | | AsyncClaude   |
  | Driver (CLI)  | | Driver (CLI)  |
  +---------------+ +---------------+
```

Usage:
    from core.drivers.cli_adapter import GeminiCLIAdapter, ClaudeCLIAdapter

    # Create adapter (wraps existing CLI driver)
    gemini = GeminiCLIAdapter(config)

    # Use through DriverProtocol interface
    response = await gemini.invoke("Hello world")
    print(response.content)
    print(response.latency_ms)

Author: Claude (NEXUS V11)
Date: 2025-12-15
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .async_claude_driver import AsyncClaudeDriver, AsyncClaudeDriverConfig
from .async_gemini_driver import AsyncGeminiDriver, AsyncGeminiDriverConfig
from .protocol import (
    BaseAsyncDriver,
    DriverResponse,
    DriverResponseStatus,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Call Extractors
# =============================================================================


def extract_tool_calls_from_gemini(content: str) -> list[ToolCall]:
    """
    Extract tool calls from Gemini response content.

    Gemini CLI returns tool calls in JSON format with specific structure.
    """
    tool_calls = []

    # Gemini uses functionCall in its JSON responses
    try:
        data = json.loads(content) if isinstance(content, str) else content
        if isinstance(data, dict):
            # Check for function_call in response
            if "function_call" in data:
                fc = data["function_call"]
                tool_calls.append(
                    ToolCall(
                        name=fc.get("name", "unknown"),
                        arguments=fc.get("args", {}),
                        id=fc.get("id"),
                    )
                )
            # Check for parts with function calls
            if "parts" in data:
                for part in data.get("parts", []):
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        tool_calls.append(
                            ToolCall(
                                name=fc.get("name", "unknown"),
                                arguments=fc.get("args", {}),
                                id=fc.get("id"),
                            )
                        )
    except (json.JSONDecodeError, TypeError, KeyError):
        pass

    return tool_calls


def extract_tool_calls_from_claude(content: str) -> list[ToolCall]:
    """
    Extract tool calls from Claude response content.

    Claude uses XML-style <tool_use> tags or structured tool_use blocks.
    """
    tool_calls = []

    # Pattern 1: XML-style <tool_use name="...">...</tool_use>
    xml_pattern = r'<tool_use\s+name="([^"]+)"[^>]*>(.*?)</tool_use>'
    for match in re.finditer(xml_pattern, content, re.DOTALL):
        name = match.group(1)
        args_str = match.group(2).strip()
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {"raw": args_str}
        tool_calls.append(ToolCall(name=name, arguments=args))

    # Pattern 2: Claude API style tool_use blocks
    try:
        data = json.loads(content) if isinstance(content, str) else content
        if isinstance(data, dict) and "tool_use" in data:
            tu = data["tool_use"]
            tool_calls.append(
                ToolCall(
                    name=tu.get("name", "unknown"),
                    arguments=tu.get("input", {}),
                    id=tu.get("id"),
                )
            )
    except (json.JSONDecodeError, TypeError, KeyError):
        pass

    return tool_calls


# =============================================================================
# Gemini CLI Adapter
# =============================================================================


class GeminiCLIAdapter(BaseAsyncDriver):
    """
    Adapter wrapping AsyncGeminiDriver to implement DriverProtocol.

    Converts Gemini CLI subprocess output to standardized DriverResponse.
    """

    def __init__(
        self,
        config: AsyncGeminiDriverConfig | None = None,
        workspace_path: Path | None = None,
    ):
        """
        Initialize Gemini CLI adapter.

        Args:
            config: Optional driver config. If None, uses defaults.
            workspace_path: Optional workspace path override.
        """
        if config is None:
            config = AsyncGeminiDriverConfig()
            if workspace_path:
                config.workspace_path = workspace_path

        super().__init__(
            provider="gemini",
            model=config.model,
            timeout=config.timeout,
        )

        self._driver = AsyncGeminiDriver(config)
        self._config = config

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
        Invoke Gemini via CLI and return unified DriverResponse.
        """
        start_time = time.time()
        effective_timeout = timeout or self._timeout

        try:
            # Build context with optional system prompt
            context = prompt
            if system_prompt:
                context = f"System: {system_prompt}\n\nUser: {prompt}"

            # Call the underlying CLI driver
            result = await self._driver.invoke(
                context,
                session_uuid=session_id,
                isolated_env=isolated_env,
                timeout=effective_timeout,
                **kwargs,
            )

            latency_ms = (time.time() - start_time) * 1000

            # Parse the result
            if isinstance(result, dict):
                content = result.get("response", result.get("content", str(result)))
                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                raw = result
            else:
                content = str(result)
                input_tokens = 0
                output_tokens = 0
                raw = {"response": content}

            # Extract tool calls
            tool_calls = extract_tool_calls_from_gemini(content)

            return DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                model=self._model,
                provider=self._provider,
                session_id=session_id,
                tool_calls=tool_calls,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw=raw,
            )

        except TimeoutError:
            return self._create_error_response(
                f"Gemini CLI timeout after {effective_timeout}s",
                error_code="TIMEOUT",
                status=DriverResponseStatus.TIMEOUT,
            )
        except asyncio.CancelledError:
            # MUST re-raise CancelledError
            raise
        except Exception as e:
            logger.exception(f"GeminiCLIAdapter.invoke error: {e}")
            return self._create_error_response(
                str(e),
                error_code="CLI_ERROR",
            )

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
        Stream Gemini response via CLI.
        """
        start_time = time.time()

        try:
            context = prompt
            if system_prompt:
                context = f"System: {system_prompt}\n\nUser: {prompt}"

            full_content = ""
            async for chunk in self._driver.invoke_stream(
                context,
                session_uuid=session_id,
                isolated_env=isolated_env,
                **kwargs,
            ):
                full_content += chunk
                yield StreamChunk(content=chunk)

            # Final chunk with metadata
            latency_ms = (time.time() - start_time) * 1000
            tool_calls = extract_tool_calls_from_gemini(full_content)
            final_tool = tool_calls[0] if tool_calls else None

            yield StreamChunk(
                content="",
                is_final=True,
                tool_call=final_tool,
                latency_ms=latency_ms,
            )

        except asyncio.CancelledError:
            raise

    async def cancel(self, session_id: str | None = None) -> bool:
        """Cancel ongoing Gemini CLI invocation."""
        try:
            await self._driver.cancel(session_uuid=session_id)
            return True
        except Exception as e:
            logger.warning(f"GeminiCLIAdapter.cancel error: {e}")
            return False

    async def health_check(self) -> bool:
        """Check if Gemini CLI is available."""
        import shutil

        return shutil.which(self._config.cli_path) is not None


# =============================================================================
# Claude CLI Adapter
# =============================================================================


class ClaudeCLIAdapter(BaseAsyncDriver):
    """
    Adapter wrapping AsyncClaudeDriver to implement DriverProtocol.

    Converts Claude CLI subprocess output to standardized DriverResponse.
    """

    def __init__(
        self,
        config: AsyncClaudeDriverConfig | None = None,
        workspace_path: Path | None = None,
    ):
        """
        Initialize Claude CLI adapter.

        Args:
            config: Optional driver config. If None, uses defaults.
            workspace_path: Optional workspace path override.
        """
        if config is None:
            config = AsyncClaudeDriverConfig()
            if workspace_path:
                config.workspace_path = workspace_path

        super().__init__(
            provider="claude",
            model=config.model,
            timeout=config.timeout,
        )

        self._driver = AsyncClaudeDriver(config)
        self._config = config

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
        Invoke Claude via CLI and return unified DriverResponse.
        """
        start_time = time.time()
        effective_timeout = timeout or self._timeout

        try:
            context = prompt
            if system_prompt:
                context = f"System: {system_prompt}\n\nUser: {prompt}"

            result = await self._driver.invoke(
                context,
                session_uuid=session_id,
                timeout=effective_timeout,
                **kwargs,
            )

            latency_ms = (time.time() - start_time) * 1000

            # Parse the result
            if isinstance(result, dict):
                content = result.get("response", result.get("content", str(result)))
                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                raw = result
            else:
                content = str(result)
                input_tokens = 0
                output_tokens = 0
                raw = {"response": content}

            # Extract tool calls
            tool_calls = extract_tool_calls_from_claude(content)

            return DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                model=self._model,
                provider=self._provider,
                session_id=session_id,
                tool_calls=tool_calls,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw=raw,
            )

        except TimeoutError:
            return self._create_error_response(
                f"Claude CLI timeout after {effective_timeout}s",
                error_code="TIMEOUT",
                status=DriverResponseStatus.TIMEOUT,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"ClaudeCLIAdapter.invoke error: {e}")
            return self._create_error_response(
                str(e),
                error_code="CLI_ERROR",
            )

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
        Stream Claude response via CLI.
        """
        start_time = time.time()

        try:
            context = prompt
            if system_prompt:
                context = f"System: {system_prompt}\n\nUser: {prompt}"

            full_content = ""
            async for chunk in self._driver.invoke_stream(
                context,
                session_uuid=session_id,
                **kwargs,
            ):
                full_content += chunk
                yield StreamChunk(content=chunk)

            latency_ms = (time.time() - start_time) * 1000
            tool_calls = extract_tool_calls_from_claude(full_content)
            final_tool = tool_calls[0] if tool_calls else None

            yield StreamChunk(
                content="",
                is_final=True,
                tool_call=final_tool,
                latency_ms=latency_ms,
            )

        except asyncio.CancelledError:
            raise

    async def cancel(self, session_id: str | None = None) -> bool:
        """Cancel ongoing Claude CLI invocation."""
        try:
            await self._driver.cancel(session_uuid=session_id)
            return True
        except Exception as e:
            logger.warning(f"ClaudeCLIAdapter.cancel error: {e}")
            return False

    async def health_check(self) -> bool:
        """Check if Claude CLI is available."""
        import shutil

        return shutil.which(self._config.cli_path) is not None


# =============================================================================
# Unified Factory for CLI Adapters
# =============================================================================


def create_cli_adapter(
    provider: str,
    workspace_path: Path | None = None,
    **config_kwargs: Any,
) -> BaseAsyncDriver:
    """
    Factory function to create CLI adapters.

    Args:
        provider: "gemini" or "claude"
        workspace_path: Optional workspace path
        **config_kwargs: Additional config options

    Returns:
        CLIDriverAdapter instance implementing DriverProtocol

    Example:
        gemini = create_cli_adapter("gemini", workspace_path=Path("."))
        response = await gemini.invoke("Hello")
    """
    if provider.lower() == "gemini":
        config = AsyncGeminiDriverConfig(**config_kwargs)
        if workspace_path:
            config.workspace_path = workspace_path
        return GeminiCLIAdapter(config)

    elif provider.lower() == "claude":
        config = AsyncClaudeDriverConfig(**config_kwargs)
        if workspace_path:
            config.workspace_path = workspace_path
        return ClaudeCLIAdapter(config)

    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'gemini' or 'claude'.")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "GeminiCLIAdapter",
    "ClaudeCLIAdapter",
    "create_cli_adapter",
    "extract_tool_calls_from_gemini",
    "extract_tool_calls_from_claude",
]
