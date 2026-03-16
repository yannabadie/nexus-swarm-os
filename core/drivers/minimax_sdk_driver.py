"""
MiniMax SDK driver for NEXUS.

MiniMax exposes an OpenAI-compatible API surface. This driver intentionally
reuses the same request/response contract as the rest of the SDK-native layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from core.observability.telemetry.otel_provider import trace_llm_call

from .protocol import BaseAsyncDriver, DriverResponse, DriverResponseStatus, StreamChunk, ToolCall

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI  # noqa: F401  # imported at module level for tests
except ImportError:
    AsyncOpenAI = None  # type: ignore[assignment]


class MiniMaxSDKDriver(BaseAsyncDriver):
    """MiniMax SDK driver using the OpenAI-compatible endpoint."""

    MODELS = {
        "reasoning": "MiniMax-M2.5",
        "chat": "MiniMax-M2.5-HighSpeed",
        "default": "MiniMax-M2.5",
        "fast": "MiniMax-M2.5-HighSpeed",
        "latest": "MiniMax-M2.5",
    }
    BASE_URL = "https://api.minimaxi.com/v1"

    def __init__(
        self,
        model: str = "MiniMax-M2.5",
        api_key: str | None = None,
        max_tokens: int = 8192,
        timeout: float = 300.0,
        enable_caching: bool = True,
        response_cache: Any | None = None,
    ):
        resolved_model = self.MODELS.get(model, model)
        super().__init__(provider="minimax", model=resolved_model, timeout=timeout)
        self._max_tokens = max_tokens
        self._enable_caching = enable_caching
        self._response_cache = response_cache
        self._budget_tracker = None
        self._health_monitor = None

        if AsyncOpenAI is None:
            raise ImportError("openai package required. Install with: pip install openai") from None

        resolved_key = api_key or os.getenv("MINIMAX_API_KEY")
        if not resolved_key:
            raise ValueError("MINIMAX_API_KEY not found. Set it in environment or pass api_key.")

        self._client = AsyncOpenAI(api_key=resolved_key, base_url=self.BASE_URL)

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
        start_time = time.monotonic()
        effective_timeout = timeout or self._timeout

        if self._response_cache and not tools:
            cached = self._response_cache.get(
                self._model,
                prompt,
                temperature=kwargs.get("temperature", 1.0),
                system_prompt=system_prompt or "",
            )
            if cached is not None:
                latency_ms = (time.monotonic() - start_time) * 1000
                return DriverResponse(
                    content=cached,
                    status=DriverResponseStatus.SUCCESS,
                    provider=self._provider,
                    model=self._model,
                    latency_ms=latency_ms,
                    raw={"cached": True, "cost_usd": 0.0},
                )

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            request_params = {
                "model": self._model,
                "messages": messages,
                "max_tokens": self._max_tokens,
                "temperature": kwargs.get("temperature", 1.0),
                "top_p": kwargs.get("top_p", 0.95),
                "stream": False,
            }
            if tools:
                request_params["tools"] = tools
                if "tool_choice" in kwargs:
                    request_params["tool_choice"] = kwargs["tool_choice"]

            with trace_llm_call(provider=self._provider, model=self._model, operation="chat.completions.create"):
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(**request_params),
                    timeout=effective_timeout,
                )

            choice = response.choices[0]
            content = choice.message.content or ""
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            cost_total = 0.0
            if self._budget_tracker:
                cost_total = self._budget_tracker.track_cost(
                    self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            latency_ms = (time.monotonic() - start_time) * 1000
            tool_calls = []
            if choice.message.tool_calls:
                for tool_call in choice.message.tool_calls:
                    tool_calls.append(
                        ToolCall(
                            id=tool_call.id,
                            name=tool_call.function.name,
                            arguments=tool_call.function.arguments,
                        )
                    )

            if self._response_cache and not tools and content:
                self._response_cache.put(
                    self._model,
                    prompt,
                    content,
                    temperature=kwargs.get("temperature", 1.0),
                    system_prompt=system_prompt or "",
                    tokens_used=total_tokens,
                )

            if self._health_monitor:
                self._health_monitor.record_success(
                    f"{self._provider}/{self._model}",
                    latency_ms=latency_ms,
                    tokens=total_tokens,
                )

            return DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost_total, 6),
                finish_reason=choice.finish_reason,
                tool_calls=tool_calls or None,
                raw={"response_id": response.id, "created": response.created, "cached": False},
            )
        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            return DriverResponse(
                content="",
                status=DriverResponseStatus.TIMEOUT,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
                error_message=f"Request timeout after {effective_timeout}s",
                error_code="TIMEOUT",
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            error_msg = str(exc)
            status = DriverResponseStatus.ERROR
            error_code = "UNKNOWN_ERROR"
            lowered = error_msg.lower()
            if "rate_limit" in lowered or "429" in lowered or "quota" in lowered:
                status = DriverResponseStatus.RATE_LIMITED
                error_code = "RATE_LIMIT"
            elif "authentication" in lowered or "401" in lowered or "403" in lowered:
                status = DriverResponseStatus.AUTHENTICATION_ERROR
                error_code = "AUTH_ERROR"

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
                error_code=error_code,
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
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            request_params = {
                "model": self._model,
                "messages": messages,
                "max_tokens": self._max_tokens,
                "temperature": kwargs.get("temperature", 1.0),
                "stream": True,
            }
            if tools:
                request_params["tools"] = tools

            with trace_llm_call(provider=self._provider, model=self._model, operation="chat.completions.create.stream"):
                stream = await self._client.chat.completions.create(**request_params)
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield StreamChunk(content=delta.content, finish_reason=chunk.choices[0].finish_reason)
        except Exception as exc:
            yield StreamChunk(content="", finish_reason="error", error=str(exc))

    async def cancel(self, session_id: str | None = None) -> None:
        logger.debug("MiniMax driver cancel called (no-op)")

    def set_budget_tracker(self, tracker: Any) -> None:
        self._budget_tracker = tracker

    def set_health_monitor(self, monitor: Any) -> None:
        self._health_monitor = monitor
