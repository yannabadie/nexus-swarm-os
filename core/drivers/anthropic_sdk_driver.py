"""
NEXUS V12.4 COGNITIVE BOOST - Anthropic SDK Driver

Direct API driver using the official Anthropic Python SDK.
Replaces subprocess CLI execution with native SDK calls.

Features:
- Streaming responses (SSE-compatible for CEREBRO UI)
- Native function/tool calling
- Prompt caching (beta) for context efficiency
- Token counting in responses
- Proper error classification (rate limit, timeout, etc.)
- Structured outputs (GA) via messages.parse() + Pydantic models
- Raw JSON schema mode via output_config.format

Usage:
    from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

    driver = AnthropicSDKDriver(model="claude-sonnet-4-6")
    response = await driver.invoke("Hello, world!")

    # Structured output with Pydantic model:
    from pydantic import BaseModel
    class Result(BaseModel):
        answer: str
        confidence: float

    response = await driver.invoke_structured("What is 2+2?", Result)
    parsed = response.raw["parsed"]  # Result(answer="4", confidence=1.0)

Requirements:
    pip install anthropic>=0.70.0

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-15
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from core.observability.telemetry.otel_provider import trace_llm_call

from .protocol import (
    BaseAsyncDriver,
    DriverResponse,
    DriverResponseStatus,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)


class AnthropicSDKDriver(BaseAsyncDriver):
    """
    Anthropic SDK driver implementing DriverProtocol.

    Uses the official `anthropic` Python SDK for direct API communication.
    Supports both synchronous (invoke) and streaming (invoke_stream) modes.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        max_tokens: int = 8192,
        timeout: float = 300.0,
        enable_caching: bool = True,
        response_cache: Any | None = None,
    ):
        super().__init__(provider="claude", model=model, timeout=timeout)
        self._max_tokens = max_tokens
        self._enable_caching = enable_caching
        self._response_cache = response_cache
        self._budget_tracker = None
        self._health_monitor = None  # Injected by factory

        # Lazy import to avoid hard dependency at module level
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic") from None

        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("ANTHROPIC_API_KEY not found. Set it in environment or pass api_key.")

        self._client = anthropic.AsyncAnthropic(api_key=resolved_key)
        self._sync_client = anthropic.Anthropic(api_key=resolved_key)

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
        Invoke Claude via the Anthropic SDK.

        Args:
            prompt: User message content
            session_id: Unused for API driver (stateless per call)
            system_prompt: Optional system message
            tools: Optional tool definitions (Anthropic format)
            timeout: Override default timeout
            **kwargs: Extra params (temperature, top_p, etc.)
        """
        start_time = time.monotonic()
        effective_timeout = timeout or self._timeout

        # Response cache check (skip if tools present — non-deterministic)
        if self._response_cache and not tools:
            temperature = kwargs.get("temperature", 0.7)
            cached = self._response_cache.get(
                self._model,
                prompt,
                temperature=temperature,
                system_prompt=system_prompt or "",
            )
            if cached is not None:
                latency_ms = (time.monotonic() - start_time) * 1000
                logger.debug("Response cache HIT (%.1fms)", latency_ms)
                return DriverResponse(
                    content=cached,
                    status=DriverResponseStatus.SUCCESS,
                    provider=self._provider,
                    model=self._model,
                    latency_ms=latency_ms,
                    raw={"cached": True},
                )

        try:
            # Build request parameters
            request_params = self._build_request(prompt, system_prompt, tools, **kwargs)

            # OTel span wraps the API call
            agent_name = kwargs.pop("agent_name", "")
            agent_id = kwargs.pop("agent_id", "")
            with trace_llm_call(
                self._provider,
                self._model,
                "chat",
                agent_name=agent_name,
                agent_id=agent_id,
            ) as span:
                # Make the API call with timeout
                response = await asyncio.wait_for(
                    self._client.messages.create(**request_params),
                    timeout=effective_timeout,
                )

                latency_ms = (time.monotonic() - start_time) * 1000
                result = self._parse_response(response, latency_ms)

                # OTel: record token usage on span
                span.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
                span.set_attribute("gen_ai.response.model", result.model or self._model)

            # Auto-track cost via BudgetTracker (with cache metrics)
            if self._budget_tracker and result.is_success:
                # Extract cache metrics from raw response
                cache_creation = result.raw.get("cache_creation_input_tokens", 0) or 0
                cache_read = result.raw.get("cache_read_input_tokens", 0) or 0

                self._budget_tracker.track_cost(
                    self._model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                )

            # Record health event
            driver_id = f"{self._provider}/{self._model}"
            if self._health_monitor:
                total_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
                if result.is_success:
                    self._health_monitor.record_success(
                        driver_id,
                        latency_ms=latency_ms,
                        tokens=total_tokens,
                    )
                else:
                    self._health_monitor.record_failure(
                        driver_id,
                        error=result.error_message or "unknown",
                        latency_ms=latency_ms,
                    )

            # Store in response cache on success (no tool calls)
            if (
                self._response_cache
                and not tools
                and result.status == DriverResponseStatus.SUCCESS
                and not result.tool_calls
                and result.content
            ):
                total_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
                self._response_cache.put(
                    self._model,
                    prompt,
                    result.content,
                    temperature=kwargs.get("temperature", 0.7),
                    system_prompt=system_prompt or "",
                    tokens_used=total_tokens,
                )

            return result

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            if self._health_monitor:
                self._health_monitor.record_failure(
                    f"{self._provider}/{self._model}",
                    error="TIMEOUT",
                    latency_ms=latency_ms,
                )
            return DriverResponse(
                content="",
                status=DriverResponseStatus.TIMEOUT,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=f"Request timed out after {effective_timeout}s",
                error_code="TIMEOUT",
            )
        except asyncio.CancelledError:
            raise  # Must re-raise per protocol contract
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            status, error_code = self._classify_error(e)
            if self._health_monitor:
                self._health_monitor.record_failure(
                    f"{self._provider}/{self._model}",
                    error=error_code,
                    latency_ms=latency_ms,
                )
            return DriverResponse(
                content="",
                status=status,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=str(e),
                error_code=error_code,
            )

    async def invoke_structured(
        self,
        prompt: str,
        output_type: type,
        *,
        system_prompt: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> DriverResponse:
        """
        Invoke Claude with structured output using Pydantic model validation.

        Uses the Anthropic SDK's messages.parse() for guaranteed schema-conformant
        responses. The parsed Pydantic model instance is accessible via
        response.raw["parsed"].

        Args:
            prompt: User message content
            output_type: Pydantic BaseModel class defining the output schema
            system_prompt: Optional system message
            timeout: Override default timeout
            **kwargs: Extra params (temperature, top_p, etc.)

        Returns:
            DriverResponse with:
                - content: JSON string of the structured output
                - raw["parsed"]: The parsed Pydantic model instance
                - raw["output_type"]: The output type class name
        """
        start_time = time.monotonic()
        effective_timeout = timeout or self._timeout

        try:
            # Build params for messages.parse()
            params: dict[str, Any] = {
                "model": self._model,
                "max_tokens": kwargs.pop("max_tokens", self._max_tokens),
                "messages": [{"role": "user", "content": prompt}],
                "output_format": output_type,
            }

            # System prompt with optional caching
            if system_prompt:
                if self._enable_caching:
                    params["system"] = [
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                else:
                    params["system"] = system_prompt

            # Pass through additional kwargs
            for key in ("temperature", "top_p", "top_k", "stop_sequences"):
                if key in kwargs:
                    params[key] = kwargs[key]

            response = await asyncio.wait_for(
                self._client.messages.parse(**params),
                timeout=effective_timeout,
            )

            latency_ms = (time.monotonic() - start_time) * 1000

            # Extract text content (JSON string)
            content = ""
            if response.content:
                for block in response.content:
                    if hasattr(block, "text"):
                        content = block.text
                        break

            # Get parsed output
            parsed = getattr(response, "parsed_output", None)

            return DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                model=response.model,
                provider=self._provider,
                latency_ms=latency_ms,
                input_tokens=getattr(response.usage, "input_tokens", 0),
                output_tokens=getattr(response.usage, "output_tokens", 0),
                raw={
                    "id": response.id,
                    "stop_reason": response.stop_reason,
                    "model": response.model,
                    "parsed": parsed,
                    "output_type": output_type.__name__,
                },
                timestamp=datetime.now(UTC),
            )

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            return DriverResponse(
                content="",
                status=DriverResponseStatus.TIMEOUT,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=f"Structured output timed out after {effective_timeout}s",
                error_code="TIMEOUT",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            status, error_code = self._classify_error(e)
            return DriverResponse(
                content="",
                status=status,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=str(e),
                error_code=error_code,
            )

    async def invoke_json_schema(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        *,
        system_prompt: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> DriverResponse:
        """
        Invoke Claude with a raw JSON schema for structured output.

        Uses output_config.format with messages.create() for when you have
        a JSON schema dict rather than a Pydantic model. The response content
        is guaranteed-valid JSON matching your schema.

        Args:
            prompt: User message content
            json_schema: JSON Schema dict defining the output structure
            system_prompt: Optional system message
            timeout: Override default timeout
            **kwargs: Extra params (temperature, top_p, etc.)

        Returns:
            DriverResponse with content as valid JSON string
        """
        start_time = time.monotonic()
        effective_timeout = timeout or self._timeout

        try:
            request_params = self._build_request(prompt, system_prompt, None, **kwargs)

            # Add structured output config
            request_params["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": json_schema,
                }
            }

            response = await asyncio.wait_for(
                self._client.messages.create(**request_params),
                timeout=effective_timeout,
            )

            latency_ms = (time.monotonic() - start_time) * 1000
            return self._parse_response(response, latency_ms)

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            return DriverResponse(
                content="",
                status=DriverResponseStatus.TIMEOUT,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=f"JSON schema output timed out after {effective_timeout}s",
                error_code="TIMEOUT",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            status, error_code = self._classify_error(e)
            return DriverResponse(
                content="",
                status=status,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=str(e),
                error_code=error_code,
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
        Stream Claude's response token-by-token.

        Yields StreamChunk objects as tokens arrive.
        The final chunk has is_final=True with usage metadata.
        """
        start_time = time.monotonic()

        request_params = self._build_request(prompt, system_prompt, tools, **kwargs)

        try:
            async with self._client.messages.stream(**request_params) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(content=text)

                # Get final message for metadata
                final_message = await stream.get_final_message()
                latency_ms = (time.monotonic() - start_time) * 1000

                # Extract tool calls from final message
                tool_calls = self._extract_tool_calls(final_message)
                final_tool = tool_calls[0] if tool_calls else None

                yield StreamChunk(
                    content="",
                    is_final=True,
                    tool_call=final_tool,
                    latency_ms=latency_ms,
                    input_tokens=getattr(final_message.usage, "input_tokens", 0),
                    output_tokens=getattr(final_message.usage, "output_tokens", 0),
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            yield StreamChunk(
                content=f"[ERROR: {e}]",
                is_final=True,
                latency_ms=latency_ms,
            )

    async def cancel(self, session_id: str | None = None) -> bool:
        """Cancel is a no-op for API drivers (use asyncio cancellation)."""
        return True

    async def health_check(self) -> bool:
        """Check if the Anthropic API is reachable."""
        try:
            # Minimal request to verify connectivity
            response = await asyncio.wait_for(
                self._client.messages.create(
                    model=self._model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=10.0,
            )
            return response.stop_reason is not None
        except Exception as e:
            logger.debug("Health check failed: %s", e)
            return False

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _build_request(
        self,
        prompt: str,
        system_prompt: str | None,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build the messages.create() request parameters."""
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": kwargs.pop("max_tokens", self._max_tokens),
            "messages": [{"role": "user", "content": prompt}],
        }

        # System prompt with optional caching
        if system_prompt:
            if self._enable_caching:
                params["system"] = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                params["system"] = system_prompt

        # Tool definitions
        if tools:
            params["tools"] = self._format_tools(tools)

        # Pass through additional kwargs (temperature, top_p, etc.)
        for key in ("temperature", "top_p", "top_k", "stop_sequences"):
            if key in kwargs:
                params[key] = kwargs[key]

        return params

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools to Anthropic's expected schema.

        When caching is enabled, marks the LAST tool with cache_control
        so the entire tool definition prefix is cached (breakpoint 1).
        """
        formatted = []
        for i, tool in enumerate(tools):
            formatted_tool = {
                "name": tool.get("name", tool.get("function", {}).get("name", "")),
                "description": tool.get(
                    "description",
                    tool.get("function", {}).get("description", ""),
                ),
                "input_schema": tool.get(
                    "input_schema",
                    tool.get("parameters", tool.get("function", {}).get("parameters", {})),
                ),
            }
            # Cache breakpoint 1: mark the last tool for prefix caching
            if self._enable_caching and i == len(tools) - 1:
                formatted_tool["cache_control"] = {"type": "ephemeral"}
            formatted.append(formatted_tool)
        return formatted

    def _parse_response(self, response: Any, latency_ms: float) -> DriverResponse:
        """Parse an Anthropic API response into a DriverResponse."""
        # Extract text content
        content_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                content_parts.append(block.text)

        content = "\n".join(content_parts) if content_parts else ""

        # Extract tool calls
        tool_calls = self._extract_tool_calls(response)

        # Extract cache metrics from usage (prompt caching)
        usage = response.usage
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        if cache_read > 0:
            logger.debug(
                "Prompt cache HIT: %d tokens read from cache (saved ~90%% input cost)",
                cache_read,
            )
        if cache_creation > 0:
            logger.debug(
                "Prompt cache WRITE: %d tokens written to cache",
                cache_creation,
            )

        return DriverResponse(
            content=content,
            status=DriverResponseStatus.SUCCESS,
            model=response.model,
            provider=self._provider,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw={
                "id": response.id,
                "stop_reason": response.stop_reason,
                "model": response.model,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
            timestamp=datetime.now(UTC),
        )

    def _extract_tool_calls(self, response: Any) -> list[ToolCall]:
        """Extract tool calls from an Anthropic response."""
        tool_calls = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                        id=block.id,
                    )
                )
        return tool_calls

    def _classify_error(self, error: Exception) -> tuple:
        """Classify an exception into DriverResponseStatus and error code."""
        error_type = type(error).__name__

        # Check for specific anthropic error types
        if "RateLimitError" in error_type:
            return DriverResponseStatus.RATE_LIMITED, "RATE_LIMITED"
        if "AuthenticationError" in error_type:
            return DriverResponseStatus.ERROR, "AUTH_ERROR"
        if "BadRequestError" in error_type:
            return DriverResponseStatus.ERROR, "BAD_REQUEST"
        if "APIConnectionError" in error_type:
            return DriverResponseStatus.ERROR, "CONNECTION_ERROR"
        if "InternalServerError" in error_type:
            return DriverResponseStatus.ERROR, "SERVER_ERROR"

        return DriverResponseStatus.ERROR, "UNKNOWN_ERROR"
