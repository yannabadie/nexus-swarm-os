"""
NEXUS V12.4 COGNITIVE BOOST - Google GenAI SDK Driver

Direct API driver using the official Google GenAI Python SDK.
Replaces subprocess CLI execution with native SDK calls.

Features:
- Streaming responses (SSE-compatible for CEREBRO UI)
- Native function calling (tool_config)
- Token counting via usage_metadata
- Thinking/reasoning support (Gemini 3 Pro)
- Proper error classification

Usage:
    from core.drivers.google_genai_sdk_driver import GoogleGenAISDKDriver

    driver = GoogleGenAISDKDriver(model="gemini-3.1-pro-preview")
    response = await driver.invoke("Analyze this code...")

Requirements:
    pip install google-genai>=1.0.0

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-15
"""

from __future__ import annotations

import asyncio
import hashlib
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


class GoogleGenAISDKDriver(BaseAsyncDriver):
    """
    Google GenAI SDK driver implementing DriverProtocol.

    Uses the official `google-genai` Python SDK for direct API communication.
    Supports both synchronous and streaming modes, plus function calling.
    """

    def __init__(
        self,
        model: str = "gemini-3.1-pro-preview",
        api_key: str | None = None,
        timeout: float = 300.0,
        enable_thinking: bool = False,
        thinking_budget: int | None = None,
        enable_caching: bool = True,
        cache_ttl: int = 3600,
        response_cache: Any | None = None,
    ):
        super().__init__(provider="gemini", model=model, timeout=timeout)
        self._enable_thinking = enable_thinking
        self._thinking_budget = thinking_budget
        self._enable_caching = enable_caching
        self._cache_ttl = cache_ttl
        self._response_cache = response_cache
        self._budget_tracker = None
        self._health_monitor = None  # Injected by factory

        # Context caching state
        self._cached_content_name: str | None = None
        self._cached_content_hash: str | None = None

        try:
            from google import genai

            self._genai = genai
        except ImportError:
            raise ImportError("google-genai package required. Install with: pip install google-genai") from None

        resolved_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError("GEMINI_API_KEY not found. Set it in environment or pass api_key.")

        self._client = genai.Client(api_key=resolved_key)

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
        Invoke Gemini via the Google GenAI SDK.

        Args:
            prompt: User message content
            session_id: Unused for API driver
            system_prompt: Optional system instruction
            tools: Optional tool/function definitions
            timeout: Override default timeout
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
            config = self._build_config(system_prompt, tools, **kwargs)

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
                # Run in executor since google-genai may not have full async support
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._client.models.generate_content(
                            model=self._model,
                            contents=prompt,
                            config=config,
                        ),
                    ),
                    timeout=effective_timeout,
                )

                latency_ms = (time.monotonic() - start_time) * 1000
                result = self._parse_response(response, latency_ms)

                # OTel: record token usage on span
                span.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
                span.set_attribute("gen_ai.response.model", result.model or self._model)

            # Auto-track cost via BudgetTracker
            if self._budget_tracker and result.is_success:
                self._budget_tracker.track_cost(
                    self._model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
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
            raise
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
        Invoke Gemini with structured output using Pydantic model validation.

        Uses the Google GenAI SDK's responseSchema parameter for guaranteed
        schema-conformant responses. The parsed Pydantic model instance is
        accessible via response.raw["parsed"].

        Args:
            prompt: User message content
            output_type: Pydantic BaseModel class defining the output schema
            system_prompt: Optional system instruction
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
            # Build config with responseSchema
            config = self._build_config(system_prompt, tools=None, **kwargs)

            # Add Pydantic schema
            config.response_mime_type = "application/json"
            config.response_schema = output_type

            # OTel span wraps the API call
            agent_name = kwargs.pop("agent_name", "")
            agent_id = kwargs.pop("agent_id", "")
            with trace_llm_call(
                self._provider,
                self._model,
                "chat.structured",
                agent_name=agent_name,
                agent_id=agent_id,
            ) as span:
                # Run in executor
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._client.models.generate_content(
                            model=self._model,
                            contents=prompt,
                            config=config,
                        ),
                    ),
                    timeout=effective_timeout,
                )

                latency_ms = (time.monotonic() - start_time) * 1000

                # Extract JSON content
                content = response.text or ""

                # Parse Pydantic model from JSON
                parsed = None
                try:
                    parsed = output_type.model_validate_json(content)
                except Exception as e:
                    logger.warning(f"Failed to parse structured output: {e}")
                    # Gemini should guarantee valid JSON, but handle gracefully

                # Extract token usage
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    meta = response.usage_metadata
                    input_tokens = getattr(meta, "prompt_token_count", 0) or 0
                    output_tokens = getattr(meta, "candidates_token_count", 0) or 0

                # OTel: record token usage
                span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                span.set_attribute("gen_ai.response.model", self._model)

            # Auto-track cost
            if self._budget_tracker:
                self._budget_tracker.track_cost(
                    self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            # Record health
            driver_id = f"{self._provider}/{self._model}"
            if self._health_monitor:
                total_tokens = input_tokens + output_tokens
                self._health_monitor.record_success(
                    driver_id,
                    latency_ms=latency_ms,
                    tokens=total_tokens,
                )

            return DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                model=self._model,
                provider=self._provider,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw={
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
        Invoke Gemini with a raw JSON schema for structured output.

        Uses responseJsonSchema parameter for when you have a JSON schema dict
        rather than a Pydantic model. The response content is guaranteed-valid
        JSON matching your schema.

        Args:
            prompt: User message content
            json_schema: JSON Schema dict defining the output structure
            system_prompt: Optional system instruction
            timeout: Override default timeout
            **kwargs: Extra params (temperature, top_p, etc.)

        Returns:
            DriverResponse with content as valid JSON string
        """
        start_time = time.monotonic()
        effective_timeout = timeout or self._timeout

        try:
            # Build config with responseJsonSchema
            config = self._build_config(system_prompt, tools=None, **kwargs)

            # Add JSON schema
            config.response_mime_type = "application/json"
            config.response_json_schema = json_schema

            # OTel span wraps the API call
            agent_name = kwargs.pop("agent_name", "")
            agent_id = kwargs.pop("agent_id", "")
            with trace_llm_call(
                self._provider,
                self._model,
                "chat.json_schema",
                agent_name=agent_name,
                agent_id=agent_id,
            ) as span:
                # Run in executor
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._client.models.generate_content(
                            model=self._model,
                            contents=prompt,
                            config=config,
                        ),
                    ),
                    timeout=effective_timeout,
                )

                latency_ms = (time.monotonic() - start_time) * 1000

                # Extract JSON content
                content = response.text or ""

                # Extract token usage
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    meta = response.usage_metadata
                    input_tokens = getattr(meta, "prompt_token_count", 0) or 0
                    output_tokens = getattr(meta, "candidates_token_count", 0) or 0

                # OTel: record token usage
                span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                span.set_attribute("gen_ai.response.model", self._model)

            # Auto-track cost
            if self._budget_tracker:
                self._budget_tracker.track_cost(
                    self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            # Record health
            driver_id = f"{self._provider}/{self._model}"
            if self._health_monitor:
                total_tokens = input_tokens + output_tokens
                self._health_monitor.record_success(
                    driver_id,
                    latency_ms=latency_ms,
                    tokens=total_tokens,
                )

            return DriverResponse(
                content=content,
                status=DriverResponseStatus.SUCCESS,
                model=self._model,
                provider=self._provider,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw={"json_schema_provided": True},
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
        Stream Gemini's response chunk-by-chunk.

        Yields StreamChunk objects as content arrives.
        The final chunk has is_final=True with usage metadata.
        """
        start_time = time.monotonic()
        config = self._build_config(system_prompt, tools, **kwargs)

        try:
            # google-genai streaming
            stream = self._client.models.generate_content_stream(
                model=self._model,
                contents=prompt,
                config=config,
            )

            total_input_tokens = 0
            total_output_tokens = 0
            last_chunk_response = None

            for chunk in stream:
                last_chunk_response = chunk
                text = ""
                if chunk.text:
                    text = chunk.text

                # Track token usage from metadata
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    meta = chunk.usage_metadata
                    total_input_tokens = getattr(meta, "prompt_token_count", 0) or 0
                    total_output_tokens = getattr(meta, "candidates_token_count", 0) or 0

                if text:
                    yield StreamChunk(content=text)

                # Yield control to event loop
                await asyncio.sleep(0)

            latency_ms = (time.monotonic() - start_time) * 1000

            # Extract function calls from final response
            tool_call = None
            if last_chunk_response:
                tool_calls = self._extract_tool_calls(last_chunk_response)
                tool_call = tool_calls[0] if tool_calls else None

            yield StreamChunk(
                content="",
                is_final=True,
                tool_call=tool_call,
                latency_ms=latency_ms,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
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
        """Cancel is a no-op for API drivers."""
        return True

    async def health_check(self) -> bool:
        """Check if the Google GenAI API is reachable."""
        try:
            response = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.models.generate_content(
                        model=self._model,
                        contents="ping",
                        config=self._genai.types.GenerateContentConfig(
                            max_output_tokens=1,
                        ),
                    ),
                ),
                timeout=10.0,
            )
            return response is not None
        except Exception as e:
            logger.debug("Health check failed: %s", e)
            return False

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _ensure_cache(
        self,
        system_prompt: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> str | None:
        """Create or reuse a Gemini context cache for the given system+tools.

        Returns the cache name if caching is active, None otherwise.
        """
        if not self._enable_caching or not system_prompt:
            return self._cached_content_name

        # Compute hash of cacheable content to detect changes
        cache_key = hashlib.sha256(f"{system_prompt}|{str(tools or [])}".encode()).hexdigest()[:16]

        # Reuse existing cache if content unchanged
        if self._cached_content_name and self._cached_content_hash == cache_key:
            return self._cached_content_name

        # Invalidate old cache
        if self._cached_content_name:
            try:
                self._client.caches.delete(self._cached_content_name)
                logger.debug("Deleted stale Gemini cache: %s", self._cached_content_name)
            except Exception as e:
                logger.debug("Cache delete failed (may be expired): %s", e)

        # Create new cache
        try:
            types = self._genai.types
            cache_config_params: dict[str, Any] = {
                "display_name": f"nexus_ctx_{cache_key}",
                "system_instruction": system_prompt,
                "ttl": f"{self._cache_ttl}s",
            }

            cache = self._client.caches.create(
                model=self._model,
                config=types.CreateCachedContentConfig(**cache_config_params),
            )
            self._cached_content_name = cache.name
            self._cached_content_hash = cache_key
            logger.info(
                "Created Gemini context cache: %s (TTL=%ds)",
                cache.name,
                self._cache_ttl,
            )
            return cache.name
        except Exception as e:
            logger.warning("Gemini context caching unavailable: %s", e)
            self._cached_content_name = None
            self._cached_content_hash = None
            return None

    def _build_config(
        self,
        system_prompt: str | None,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> Any:
        """Build GenerateContentConfig for the request."""
        types = self._genai.types

        config_params: dict[str, Any] = {}

        # Try context caching first (system prompt cached server-side)
        cache_name = self._ensure_cache(system_prompt, tools)
        if cache_name:
            config_params["cached_content"] = cache_name
            # When using cached content, system_instruction is already in the cache
        elif system_prompt:
            config_params["system_instruction"] = system_prompt

        if "temperature" in kwargs:
            config_params["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            config_params["top_p"] = kwargs["top_p"]
        if "top_k" in kwargs:
            config_params["top_k"] = kwargs["top_k"]
        if "max_tokens" in kwargs:
            config_params["max_output_tokens"] = kwargs["max_tokens"]

        # Response format
        if kwargs.get("json_mode"):
            config_params["response_mime_type"] = "application/json"

        # Thinking/reasoning (Gemini 3 Pro feature)
        if self._enable_thinking:
            thinking_config = {"thinking_budget": self._thinking_budget or 8192}
            config_params["thinking_config"] = thinking_config

        # Function calling (tools included even with cache for dynamic tool lists)
        if tools:
            config_params["tools"] = self._format_tools(tools)

        return types.GenerateContentConfig(**config_params)

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[Any]:
        """Format tools for Google GenAI function calling."""
        types = self._genai.types

        function_declarations = []
        for tool in tools:
            name = tool.get("name", tool.get("function", {}).get("name", ""))
            description = tool.get(
                "description",
                tool.get("function", {}).get("description", ""),
            )
            parameters = tool.get(
                "parameters",
                tool.get("input_schema", tool.get("function", {}).get("parameters", {})),
            )

            decl = types.FunctionDeclaration(
                name=name,
                description=description,
                parameters=parameters if parameters else None,
            )
            function_declarations.append(decl)

        return [types.Tool(function_declarations=function_declarations)]

    def _parse_response(self, response: Any, latency_ms: float) -> DriverResponse:
        """Parse a Google GenAI response into a DriverResponse."""
        # Extract text content
        content = ""
        try:
            content = response.text or ""
        except (AttributeError, ValueError):
            # May not have text if only function calls
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        content += part.text

        # Extract tool calls
        tool_calls = self._extract_tool_calls(response)

        # Token usage
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            input_tokens = getattr(meta, "prompt_token_count", 0) or 0
            output_tokens = getattr(meta, "candidates_token_count", 0) or 0
            cached_tokens = getattr(meta, "cached_content_token_count", 0) or 0

        if cached_tokens > 0:
            logger.debug(
                "Gemini context cache HIT: %d tokens served from cache (90%% discount)",
                cached_tokens,
            )

        return DriverResponse(
            content=content,
            status=DriverResponseStatus.SUCCESS,
            model=self._model,
            provider=self._provider,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw={
                "candidates_count": len(response.candidates) if response.candidates else 0,
                "cached_content_token_count": cached_tokens,
            },
            timestamp=datetime.now(UTC),
        )

    def _extract_tool_calls(self, response: Any) -> list[ToolCall]:
        """Extract function calls from a Google GenAI response."""
        tool_calls = []
        try:
            if not response.candidates:
                return tool_calls
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    args = dict(fc.args) if fc.args else {}
                    tool_calls.append(
                        ToolCall(
                            name=fc.name,
                            arguments=args,
                        )
                    )
        except (AttributeError, IndexError):
            pass
        return tool_calls

    def _classify_error(self, error: Exception) -> tuple:
        """Classify an exception into DriverResponseStatus and error code."""
        error_str = str(error).lower()

        if "rate" in error_str and "limit" in error_str:
            return DriverResponseStatus.RATE_LIMITED, "RATE_LIMITED"
        if "quota" in error_str:
            return DriverResponseStatus.RATE_LIMITED, "QUOTA_EXCEEDED"
        if "auth" in error_str or "permission" in error_str or "403" in error_str:
            return DriverResponseStatus.ERROR, "AUTH_ERROR"
        if "not found" in error_str or "404" in error_str:
            return DriverResponseStatus.ERROR, "MODEL_NOT_FOUND"
        if "invalid" in error_str or "400" in error_str:
            return DriverResponseStatus.ERROR, "BAD_REQUEST"

        return DriverResponseStatus.ERROR, "UNKNOWN_ERROR"
