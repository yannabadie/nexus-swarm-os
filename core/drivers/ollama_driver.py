"""
NEXUS V12.4 COGNITIVE BOOST - Ollama Local LLM Driver

Driver for local Ollama models, reducing vendor lock-in and enabling
offline/private operation. Uses Ollama's native REST API.

Features:
- Chat completions with conversation history
- Tool/function calling (Ollama 0.4+)
- Streaming responses
- Model listing and health checks
- Configurable endpoint (default: localhost:11434)

Usage:
    from core.drivers.ollama_driver import OllamaDriver

    driver = OllamaDriver(model="llama3.1")
    response = await driver.invoke("Hello, world!")

    # List available models
    models = await driver.list_models()

Requirements:
    - Ollama running locally (https://ollama.com)
    - httpx (async HTTP client): pip install httpx
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from .protocol import (
    BaseAsyncDriver,
    DriverResponse,
    DriverResponseStatus,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"
DEFAULT_TIMEOUT = 120.0


# =============================================================================
# Ollama Driver
# =============================================================================


class OllamaDriver(BaseAsyncDriver):
    """
    Ollama local LLM driver implementing DriverProtocol.

    Uses Ollama's native /api/chat endpoint for chat completions
    and /api/tags for model discovery. Supports tool calling for
    compatible models (Llama 3.1+, Mistral, etc.).
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        temperature: float = 0.7,
        num_ctx: int = 4096,
    ):
        """
        Initialize Ollama driver.

        Args:
            model: Ollama model name (e.g., "llama3.1", "codellama", "mistral")
            base_url: Ollama server URL (default: http://localhost:11434)
            timeout: Request timeout in seconds
            temperature: Sampling temperature (0.0-2.0)
            num_ctx: Context window size in tokens
        """
        super().__init__(provider="ollama", model=model, timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._num_ctx = num_ctx
        self._client = None

    def _get_client(self) -> Any:
        """Lazy-initialize the httpx async client."""
        if self._client is None:
            try:
                import httpx
            except ImportError:
                raise ImportError("httpx package required for Ollama driver. Install with: pip install httpx") from None
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

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
        Invoke Ollama model with a prompt.

        Args:
            prompt: User message
            session_id: Unused (Ollama is stateless per request)
            system_prompt: Optional system instruction
            tools: Optional tool definitions (OpenAI format)
            isolated_env: Unused
            timeout: Optional timeout override
            **kwargs: Extra options passed to Ollama (e.g., top_p, top_k)

        Returns:
            DriverResponse with content and metadata
        """
        start_time = time.monotonic()

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build request payload
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
            },
        }

        # Add extra options
        for key in ("top_p", "top_k", "seed", "repeat_penalty"):
            if key in kwargs:
                payload["options"][key] = kwargs[key]

        # Add tools if provided
        if tools:
            payload["tools"] = self._format_tools(tools)

        try:
            client = self._get_client()
            effective_timeout = timeout or self._timeout

            response = await asyncio.wait_for(
                client.post("/api/chat", json=payload),
                timeout=effective_timeout,
            )

            elapsed_ms = (time.monotonic() - start_time) * 1000

            if response.status_code != 200:
                return self._create_error_response(
                    error_message=f"Ollama returned status {response.status_code}: {response.text}",
                    error_code=f"HTTP_{response.status_code}",
                )

            data = response.json()
            return self._parse_response(data, elapsed_ms)

        except TimeoutError:
            return self._create_error_response(
                error_message=f"Ollama request timed out after {timeout or self._timeout}s",
                error_code="TIMEOUT",
                status=DriverResponseStatus.TIMEOUT,
            )
        except asyncio.CancelledError:
            raise  # Must re-raise per protocol
        except Exception as e:
            logger.error(f"Ollama invocation failed: {e}")
            return self._create_error_response(
                error_message=str(e),
                error_code="OLLAMA_ERROR",
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
        Stream response from Ollama model.

        Yields:
            StreamChunk objects as tokens arrive
        """
        start_time = time.monotonic()

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
            },
        }

        if tools:
            payload["tools"] = self._format_tools(tools)

        try:
            client = self._get_client()

            async with client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    yield StreamChunk(
                        content=f"Error: HTTP {response.status_code}",
                        is_final=True,
                    )
                    return

                accumulated = ""
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    is_done = data.get("done", False)

                    accumulated += content

                    if is_done:
                        elapsed_ms = (time.monotonic() - start_time) * 1000
                        # Extract token counts from final response
                        yield StreamChunk(
                            content=content,
                            is_final=True,
                            latency_ms=elapsed_ms,
                            input_tokens=data.get("prompt_eval_count", 0),
                            output_tokens=data.get("eval_count", 0),
                        )
                    else:
                        yield StreamChunk(content=content, is_final=False)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Ollama streaming failed: {e}")
            yield StreamChunk(
                content=f"Error: {e}",
                is_final=True,
            )

    async def cancel(self, session_id: str | None = None) -> bool:
        """
        Cancel ongoing request.

        Note: Ollama doesn't have a cancel API, but closing the client
        connection will abort the request.
        """
        if self._client:
            await self._client.aclose()
            self._client = None
            return True
        return False

    async def health_check(self) -> bool:
        """
        Check if Ollama server is running and responsive.

        Returns:
            True if Ollama is reachable
        """
        try:
            client = self._get_client()
            response = await asyncio.wait_for(
                client.get("/api/tags"),
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict[str, Any]]:
        """
        List available models on the Ollama server.

        Returns:
            List of model info dicts with name, size, etc.
        """
        try:
            client = self._get_client()
            response = await client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                return data.get("models", [])
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
        return []

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Format tools for Ollama's API.

        Ollama accepts tools in OpenAI-compatible format:
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": {...}
            }
        }
        """
        formatted = []
        for tool in tools:
            if "function" in tool:
                # Already in OpenAI format
                formatted.append(tool)
            elif "name" in tool:
                # Simple format -> OpenAI format
                formatted.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters", tool.get("input_schema", {})),
                        },
                    }
                )
            else:
                formatted.append(tool)
        return formatted

    def _parse_response(self, data: dict[str, Any], elapsed_ms: float) -> DriverResponse:
        """Parse Ollama response into DriverResponse."""
        message = data.get("message", {})
        content = message.get("content", "")

        # Extract tool calls if present
        tool_calls = []
        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            tool_calls.append(
                ToolCall(
                    name=func.get("name", ""),
                    arguments=func.get("arguments", {}),
                )
            )

        # Token counts
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return DriverResponse(
            content=content,
            status=DriverResponseStatus.SUCCESS,
            model=data.get("model", self._model),
            provider="ollama",
            tool_calls=tool_calls,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw=data,
            timestamp=datetime.now(UTC),
        )

    def __repr__(self) -> str:
        return f"OllamaDriver(model={self._model!r}, base_url={self._base_url!r})"
