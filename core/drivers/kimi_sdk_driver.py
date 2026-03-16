"""
NEXUS V12.4 COGNITIVE BOOST - Kimi SDK Driver (Moonshot AI)

Multimodal LLM with agent swarm capabilities, vision, and tool calling.
Released January 2026, Kimi K2.5 is a frontier-class model comparable to GPT-5/Gemini.

Features:
- OpenAI-compatible API (via openai package)
- Multimodal: Vision + Language understanding
- Agent Swarm: Native multi-agent collaboration
- Thinking modes: Instant + Deep reasoning
- Tool Calling: Native function calling support
- Context: 256K tokens
- Model: 1T params MoE (32B activated)

Benchmarks:
- Coding: Comparable to GPT-5 and Gemini 3 Pro
- SWE-bench: Strong performance on real GitHub issues
- Tool Use: Native support for complex workflows

Pricing (Feb 2025):
- Contact Moonshot AI for pricing (not publicly disclosed)
- API access requires registration at platform.moonshot.ai
- Estimated competitive with Gemini 2.5 Flash

Usage:
    from core.drivers.kimi_sdk_driver import KimiSDKDriver

    driver = KimiSDKDriver(api_key="your-key")
    response = await driver.invoke("Hello, Kimi!")

    # For reasoning tasks:
    driver_k25 = KimiSDKDriver(model="kimi-k2.5")
    response = await driver_k25.invoke("Analyze this codebase...")

    # Vision tasks:
    response = await driver.invoke(
        "What's in this image?",
        vision_input=image_data
    )

Requirements:
    pip install openai>=1.0.0

References:
    - API Platform: https://platform.moonshot.ai/
    - Model Card: https://huggingface.co/moonshotai/Kimi-K2.5
    - GitHub: https://github.com/MoonshotAI/Kimi-K2.5
    - InfoQ Article: https://www.infoq.com/news/2026/02/kimi-k25-swarm/

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2025-02-18
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

# Module-level import for mock.patch() support in tests
try:
    from openai import AsyncOpenAI  # noqa: F401  # used by tests via mock.patch()
except ImportError:
    AsyncOpenAI = None  # noqa: F841


class KimiSDKDriver(BaseAsyncDriver):
    """
    Kimi SDK driver using OpenAI-compatible endpoint (Moonshot AI).

    Kimi provides an OpenAI-compatible API, allowing use of the
    official `openai` Python SDK with a custom base_url.

    Supports multimodal (vision), agent swarm, and tool calling.
    """

    # Model aliases for convenience
    MODELS = {
        "k2.5": "kimi-k2.5",  # Latest (Jan 2026) - Multimodal + Agent Swarm
        "k2": "kimi-k2",  # Previous generation
        "latest": "kimi-latest",  # Auto-select best model
        "default": "kimi-k2.5",
    }

    # Kimi API endpoint (OpenAI-compatible)
    BASE_URL = "https://api.moonshot.ai/v1"

    def __init__(
        self,
        model: str = "kimi-k2.5",
        api_key: str | None = None,
        max_tokens: int = 8192,
        timeout: float = 300.0,
        enable_caching: bool = True,
        response_cache: Any | None = None,
    ):
        """
        Initialize Kimi SDK driver.

        Args:
            model: Model ID or alias (k2.5, k2, latest, default)
            api_key: Kimi API key (or set KIMI_API_KEY env var)
            max_tokens: Maximum tokens in response
            timeout: Request timeout in seconds
            enable_caching: Enable response caching
            response_cache: Optional ResponseCache instance
        """
        # Resolve model alias
        resolved_model = self.MODELS.get(model, model)

        super().__init__(provider="kimi", model=resolved_model, timeout=timeout)
        self._max_tokens = max_tokens
        self._enable_caching = enable_caching
        self._response_cache = response_cache
        self._budget_tracker = None
        self._health_monitor = None  # Injected by factory

        # Check that openai package is available (imported at module level)
        if AsyncOpenAI is None:
            raise ImportError("openai package required. Install with: pip install openai")

        # Get API key from param or environment
        resolved_key = api_key or os.getenv("KIMI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "KIMI_API_KEY not found. Set it in environment or pass api_key.\n"
                "Get your API key at: https://platform.moonshot.ai/"
            )

        # Create OpenAI client with Kimi endpoint
        self._client = AsyncOpenAI(
            api_key=resolved_key,
            base_url=self.BASE_URL,
        )

        logger.info(
            f"Kimi driver initialized: model={resolved_model}, caching={enable_caching}, max_tokens={max_tokens}"
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
        Invoke Kimi via OpenAI-compatible API.

        Args:
            prompt: User message content
            session_id: Unused for API driver (stateless)
            system_prompt: Optional system message
            tools: Optional tool definitions (OpenAI format)
            timeout: Override default timeout
            **kwargs: Extra params (temperature, top_p, vision_input, etc.)

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
                logger.debug("Kimi cache HIT (%.1fms)", latency_ms)
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

            # Check for vision input
            vision_input = kwargs.pop("vision_input", None)
            if vision_input:
                # Multimodal message with vision
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": vision_input}},
                        ],
                    }
                )
            else:
                messages.append({"role": "user", "content": prompt})

            # Build request parameters
            # NOTE: Kimi only accepts top_p=0.95 (not 1.0)
            request_params = {
                "model": self._model,
                "messages": messages,
                "max_tokens": self._max_tokens,
                "temperature": kwargs.get("temperature", 1.0),
                "top_p": 0.95,  # Kimi constraint: only 0.95 allowed
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
            logger.debug(f"Kimi API call: model={self._model}, len(prompt)={len(prompt)}")

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

            # Calculate cost (Kimi pricing not public - use estimate)
            # Estimated: Similar to Gemini 2.5 Flash ($0.30/$2.50)
            cost_input = (input_tokens / 1_000_000) * 0.30
            cost_output = (output_tokens / 1_000_000) * 2.50
            cost_total = cost_input + cost_output

            latency_ms = (time.monotonic() - start_time) * 1000

            # Track budget if available
            if self._budget_tracker:
                self._budget_tracker.record_cost(
                    provider=self._provider,
                    model=self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=round(cost_total, 6),
                )

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
                finish_reason=finish_reason,
                cost_usd=round(cost_total, 6),
                tool_calls=tool_calls if tool_calls else [],
                raw={
                    "response_id": response.id,
                    "created": response.created,
                    "cached": False,
                    "finish_reason": finish_reason,
                    "cost_usd": round(cost_total, 6),
                    "cost_breakdown": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_input_usd": round(cost_input, 6),
                        "cost_output_usd": round(cost_output, 6),
                        "note": "Pricing estimate (not official)",
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

            logger.info(f"Kimi success: {output_tokens} tokens, ${cost_total:.6f} (est), {latency_ms:.0f}ms")

            return driver_response

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"Kimi timeout after {latency_ms:.0f}ms")

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
            logger.error(f"Kimi error: {error_msg}", exc_info=True)

            # Classify error type
            status = DriverResponseStatus.ERROR
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                status = DriverResponseStatus.RATE_LIMITED
            elif "authentication" in error_msg.lower() or "401" in error_msg:
                status = DriverResponseStatus.AUTHENTICATION_ERROR

            if self._health_monitor:
                self._health_monitor.record_error(
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
        Invoke Kimi with streaming response.

        Args:
            prompt: User message
            session_id: Unused
            system_prompt: Optional system message
            tools: Optional tool definitions
            **kwargs: Extra parameters (vision_input, temperature, etc.)

        Yields:
            StreamChunk with incremental content
        """
        start_time = time.monotonic()

        try:
            # Build messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Check for vision input
            vision_input = kwargs.pop("vision_input", None)
            if vision_input:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": vision_input}},
                        ],
                    }
                )
            else:
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

            logger.debug(f"Kimi streaming: model={self._model}")

            # Stream response chunks
            with trace_llm_call(
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
            logger.debug(f"Kimi stream complete: {latency_ms:.0f}ms")

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"Kimi stream error: {e}", exc_info=True)

            yield StreamChunk(
                content="",
                finish_reason="error",
                error=str(e),
            )

    async def cancel(self, session_id: str | None = None) -> None:
        """
        Cancel any ongoing requests.

        Note: Kimi API doesn't support request cancellation.
        This is a no-op for compatibility with the BaseAsyncDriver protocol.
        """
        logger.debug("Kimi driver cancel called (no-op)")

    def set_budget_tracker(self, tracker: Any) -> None:
        """Inject budget tracker for automatic cost tracking."""
        self._budget_tracker = tracker

    def set_health_monitor(self, monitor: Any) -> None:
        """Inject health monitor for uptime/latency tracking."""
        self._health_monitor = monitor
