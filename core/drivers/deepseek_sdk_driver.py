"""
NEXUS V12.4 COGNITIVE BOOST - DeepSeek SDK Driver

Cost-effective LLM API using DeepSeek's OpenAI-compatible endpoint.
95% cheaper than Anthropic/Gemini with 5M free tokens for new users.

Features:
- OpenAI-compatible API (via openai package)
- Cache hits: $0.014/M (90% savings vs $0.14/M cache miss)
- DeepSeek V3: $0.14/$0.28 per million tokens (Feb 2025)
- DeepSeek R1: Reasoning model at $0.55/$2.19 per M tokens
- Streaming responses
- Function/tool calling support

Pricing (Feb 2025):
- Input: $0.14/M tokens (cache miss), $0.014/M (cache hit)
- Output: $0.28/M tokens
- FREE: 5M tokens for new signups (no credit card)

Comparison (Feb 2025):
- vs Claude 3.7 Sonnet: $3/$15 per million (98% cheaper)
- vs Gemini 2.5 Flash: $0.30/$2.50 per million (85% cheaper)
- vs GPT-4o: $2.50/$10 per million (95% cheaper)

Usage:
    from core.drivers.deepseek_sdk_driver import DeepSeekSDKDriver

    driver = DeepSeekSDKDriver(api_key="your-key")
    response = await driver.invoke("Hello, DeepSeek!")

    # For reasoning tasks:
    driver_r1 = DeepSeekSDKDriver(model="deepseek-reasoner")
    response = await driver_r1.invoke("Solve this complex problem...")

Requirements:
    pip install openai>=1.0.0

References:
    - API Docs: https://api-docs.deepseek.com/
    - Pricing: https://api-docs.deepseek.com/quick_start/pricing
    - Models: deepseek-chat, deepseek-reasoner

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-18
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
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


class DeepSeekSDKDriver(BaseAsyncDriver):
    """
    DeepSeek SDK driver using OpenAI-compatible endpoint.

    DeepSeek provides an OpenAI-compatible API, allowing use of the
    official `openai` Python SDK with a custom base_url.

    Supports both V3.2 (general) and R1 (reasoning) models.
    """

    # Model aliases for convenience
    MODELS = {
        "chat": "deepseek-chat",  # V3.2 - General purpose
        "reasoner": "deepseek-reasoner",  # R1 - Complex reasoning
        "default": "deepseek-chat",
    }

    # DeepSeek API endpoint (OpenAI-compatible)
    BASE_URL = "https://api.deepseek.com"

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        max_tokens: int = 8192,
        timeout: float = 300.0,
        enable_caching: bool = True,
        response_cache: Any | None = None,
    ):
        """
        Initialize DeepSeek SDK driver.

        Args:
            model: Model ID or alias (chat, reasoner, default)
            api_key: DeepSeek API key (or set DEEPSEEK_API_KEY env var)
            max_tokens: Maximum tokens in response
            timeout: Request timeout in seconds
            enable_caching: Enable response caching
            response_cache: Optional ResponseCache instance
        """
        # Resolve model alias
        resolved_model = self.MODELS.get(model, model)

        super().__init__(provider="deepseek", model=resolved_model, timeout=timeout)
        self._max_tokens = max_tokens
        self._enable_caching = enable_caching
        self._response_cache = response_cache
        self._budget_tracker = None
        self._health_monitor = None  # Injected by factory

        # Lazy import to avoid hard dependency
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai") from None

        # Get API key from param or environment
        resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_key:
            raise ValueError(
                "DEEPSEEK_API_KEY not found. Set it in environment or pass api_key.\n"
                "Get your free API key with 5M tokens at: https://platform.deepseek.com/"
            )

        # Create OpenAI client with DeepSeek endpoint
        self._client = AsyncOpenAI(
            api_key=resolved_key,
            base_url=self.BASE_URL,
        )

        logger.info(
            f"DeepSeek driver initialized: model={resolved_model}, caching={enable_caching}, max_tokens={max_tokens}"
        )

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
        Invoke DeepSeek via OpenAI-compatible API.

        Args:
            prompt: User message content
            session_id: Unused for API driver (stateless)
            system_prompt: Optional system message
            tools: Optional tool definitions (OpenAI format)
            timeout: Override default timeout
            **kwargs: Extra params (temperature, top_p, presence_penalty, etc.)

        Returns:
            DriverResponse with content and metadata
        """
        start_time = time.monotonic()
        effective_timeout = timeout or self._timeout

        # Response cache check (skip if tools present)
        if self._response_cache and not tools:
            temperature = kwargs.get("temperature", 1.0)
            cached = self._response_cache.get(
                self._model,
                prompt,
                temperature=temperature,
                system_prompt=system_prompt or "",
            )
            if cached is not None:
                latency_ms = (time.monotonic() - start_time) * 1000
                logger.debug("DeepSeek cache HIT (%.1fms)", latency_ms)
                return DriverResponse(
                    content=cached,
                    status=DriverResponseStatus.SUCCESS,
                    provider=self._provider,
                    model=self._model,
                    latency_ms=latency_ms,
                    raw={"cached": True, "cost_usd": 0.0},
                )

        try:
            # Build messages list
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Build request parameters
            request_params = {
                "model": self._model,
                "messages": messages,
                "max_tokens": self._max_tokens,
                "temperature": kwargs.get("temperature", 1.0),
                "top_p": kwargs.get("top_p", 1.0),
                "frequency_penalty": kwargs.get("frequency_penalty", 0.0),
                "presence_penalty": kwargs.get("presence_penalty", 0.0),
                "stream": False,
            }

            # Add tools if provided
            if tools:
                request_params["tools"] = tools
                if "tool_choice" in kwargs:
                    request_params["tool_choice"] = kwargs["tool_choice"]

            # Make API call with timeout
            logger.debug(f"DeepSeek API call: model={self._model}, len(prompt)={len(prompt)}")

            with trace_llm_call(
                provider=self._provider,
                model=self._model,
                operation="chat.completions.create",
            ):
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(**request_params),
                    timeout=effective_timeout,
                )

            # Extract response content
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason

            # Extract token usage
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            # Calculate cost (DeepSeek V3 pricing - Feb 2025)
            # Input: $0.14/M, Output: $0.28/M
            cost_input = (input_tokens / 1_000_000) * 0.14
            cost_output = (output_tokens / 1_000_000) * 0.28
            cost_total = cost_input + cost_output

            # Track budget if available
            if self._budget_tracker:
                self._budget_tracker.track_cost(
                    self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            latency_ms = (time.monotonic() - start_time) * 1000

            # Handle tool calls if present
            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        )
                    )

            # Build response
            driver_response = DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_total,
                finish_reason=finish_reason,
                tool_calls=tool_calls if tool_calls else None,
                raw={
                    "response_id": response.id,
                    "created": response.created,
                    "cached": False,
                    "cost_breakdown": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_input_usd": round(cost_input, 6),
                        "cost_output_usd": round(cost_output, 6),
                    },
                },
            )

            # Cache successful response (if caching enabled and no tools)
            if self._response_cache and not tools and content:
                self._response_cache.put(
                    self._model,
                    prompt,
                    content,
                    temperature=kwargs.get("temperature", 1.0),
                    system_prompt=system_prompt or "",
                )

            # Update health monitor
            if self._health_monitor:
                self._health_monitor.record_success(
                    f"{self._provider}/{self._model}",
                    latency_ms=latency_ms,
                    tokens=total_tokens,
                )

            logger.info(f"DeepSeek success: {output_tokens} tokens, ${cost_total:.6f}, {latency_ms:.0f}ms")

            return driver_response

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"DeepSeek timeout after {latency_ms:.0f}ms")

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
                error_message=f"Request timeout after {effective_timeout}s",
            )

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            error_msg = str(e)
            logger.error(f"DeepSeek error: {error_msg}", exc_info=True)

            # Classify error type
            status = DriverResponseStatus.ERROR
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                status = DriverResponseStatus.RATE_LIMITED
            elif "authentication" in error_msg.lower() or "401" in error_msg:
                status = DriverResponseStatus.AUTHENTICATION_ERROR

            if self._health_monitor:
                self._health_monitor.record_failure(
                    f"{self._provider}/{self._model}",
                    error=error_msg,
                    latency_ms=latency_ms,
                )

            return DriverResponse(
                content="",
                status=status,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=error_msg,
                raw={"exception": error_msg},
            )

    async def invoke_stream(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """
        Invoke DeepSeek with streaming response.

        Args:
            prompt: User message
            session_id: Unused
            system_prompt: Optional system message
            tools: Optional tool definitions
            **kwargs: Extra parameters

        Yields:
            StreamChunk with incremental content
        """
        start_time = time.monotonic()

        try:
            # Build messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Build request with streaming enabled
            request_params = {
                "model": self._model,
                "messages": messages,
                "max_tokens": self._max_tokens,
                "temperature": kwargs.get("temperature", 1.0),
                "stream": True,
            }

            if tools:
                request_params["tools"] = tools

            logger.debug(f"DeepSeek streaming: model={self._model}")

            # Stream response chunks
            async with trace_llm_call(
                provider=self._provider,
                model=self._model,
                operation="chat.completions.create.stream",
            ):
                stream = await self._client.chat.completions.create(**request_params)

                async for chunk in stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yield StreamChunk(
                                content=delta.content,
                                finish_reason=chunk.choices[0].finish_reason,
                            )

            latency_ms = (time.monotonic() - start_time) * 1000
            logger.debug(f"DeepSeek stream complete: {latency_ms:.0f}ms")

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"DeepSeek stream error: {e}", exc_info=True)

            yield StreamChunk(
                content="",
                finish_reason="error",
                error=str(e),
            )

    async def cancel(self, session_id: str | None = None) -> None:
        """
        Cancel any ongoing requests.

        Note: DeepSeek API doesn't support request cancellation.
        This is a no-op for compatibility with the BaseAsyncDriver protocol.
        """
        logger.debug("DeepSeek driver cancel called (no-op)")

    def set_budget_tracker(self, tracker: Any) -> None:
        """Inject budget tracker for automatic cost tracking."""
        self._budget_tracker = tracker

    def set_health_monitor(self, monitor: Any) -> None:
        """Inject health monitor for uptime/latency tracking."""
        self._health_monitor = monitor
