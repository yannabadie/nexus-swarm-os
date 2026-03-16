"""
Tests for V12.4 Structured Outputs (Anthropic SDK).

Validates:
- invoke_structured() with Pydantic models
- invoke_json_schema() with raw JSON schemas
- Parsed output accessible via response.raw["parsed"]
- Error handling (timeout, rate limit, cancellation)
- System prompt and kwargs passthrough
- Protocol compliance (new methods don't break existing interface)
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from core.drivers.protocol import (
    DriverResponseStatus,
)

# =============================================================================
# Pydantic Models for Testing
# =============================================================================


class ContactInfo(BaseModel):
    name: str
    email: str
    plan_interest: str
    demo_requested: bool


class TaskAnalysis(BaseModel):
    complexity: str
    domains: list[str]
    estimated_turns: int
    reasoning: str | None = None


class SimpleResult(BaseModel):
    answer: str
    confidence: float


# =============================================================================
# Mock Response Objects
# =============================================================================


class MockTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class MockUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class MockParseResponse:
    """Mock for messages.parse() response with parsed_output."""

    def __init__(
        self,
        content_text: str = '{"answer": "4", "confidence": 1.0}',
        parsed_output: object = None,
        model: str = "claude-sonnet-4-5-20250929",
        stop_reason: str = "end_turn",
    ):
        self.id = "msg_structured_123"
        self.content = [MockTextBlock(content_text)]
        self.model = model
        self.stop_reason = stop_reason
        self.usage = MockUsage()
        self.parsed_output = parsed_output


class MockCreateResponse:
    """Mock for messages.create() response (JSON schema mode)."""

    def __init__(
        self,
        content_text: str = '{"name": "John", "email": "john@example.com"}',
        model: str = "claude-sonnet-4-5-20250929",
        stop_reason: str = "end_turn",
    ):
        self.id = "msg_json_456"
        self.content = [MockTextBlock(content_text)]
        self.model = model
        self.stop_reason = stop_reason
        self.usage = MockUsage(input_tokens=120, output_tokens=30)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_anthropic_module():
    """Create a mock anthropic module."""
    mock_module = MagicMock()
    mock_async_client = AsyncMock()
    mock_sync_client = MagicMock()
    mock_module.AsyncAnthropic.return_value = mock_async_client
    mock_module.Anthropic.return_value = mock_sync_client
    return mock_module, mock_async_client


@pytest.fixture
def driver(mock_anthropic_module):
    """Create an AnthropicSDKDriver with mocked SDK."""
    mock_module, mock_async_client = mock_anthropic_module

    with (
        patch.dict("sys.modules", {"anthropic": mock_module}),
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}),
    ):
        from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

        d = AnthropicSDKDriver(model="claude-sonnet-4-5-20250929")
        d._client = mock_async_client
        return d


# =============================================================================
# invoke_structured() Tests
# =============================================================================


class TestInvokeStructured:
    """Test structured output with Pydantic models."""

    @pytest.mark.asyncio
    async def test_basic_structured_output(self, driver, mock_anthropic_module):
        """Should return parsed Pydantic model in response.raw."""
        _, mock_client = mock_anthropic_module

        parsed_model = SimpleResult(answer="4", confidence=1.0)
        mock_response = MockParseResponse(
            content_text='{"answer": "4", "confidence": 1.0}',
            parsed_output=parsed_model,
        )
        mock_client.messages.parse = AsyncMock(return_value=mock_response)
        driver._client = mock_client

        response = await driver.invoke_structured("What is 2+2?", SimpleResult)

        assert response.is_success
        assert response.provider == "claude"
        assert response.raw["parsed"] is parsed_model
        assert response.raw["output_type"] == "SimpleResult"
        assert '"answer"' in response.content
        assert response.latency_ms > 0

    @pytest.mark.asyncio
    async def test_structured_with_complex_model(self, driver, mock_anthropic_module):
        """Should handle complex Pydantic models with nested types."""
        _, mock_client = mock_anthropic_module

        parsed = TaskAnalysis(
            complexity="MODERATE",
            domains=["CODING", "TESTING"],
            estimated_turns=5,
            reasoning="Multi-file refactor",
        )
        mock_response = MockParseResponse(
            content_text=json.dumps(parsed.model_dump()),
            parsed_output=parsed,
        )
        mock_client.messages.parse = AsyncMock(return_value=mock_response)
        driver._client = mock_client

        response = await driver.invoke_structured(
            "Analyze this task: refactor auth module",
            TaskAnalysis,
        )

        assert response.is_success
        assert response.raw["parsed"].complexity == "MODERATE"
        assert "CODING" in response.raw["parsed"].domains
        assert response.raw["output_type"] == "TaskAnalysis"

    @pytest.mark.asyncio
    async def test_structured_passes_output_format(self, driver, mock_anthropic_module):
        """Should pass output_format to messages.parse()."""
        _, mock_client = mock_anthropic_module

        mock_client.messages.parse = AsyncMock(
            return_value=MockParseResponse(parsed_output=SimpleResult(answer="yes", confidence=0.9))
        )
        driver._client = mock_client

        await driver.invoke_structured("test", SimpleResult)

        call_kwargs = mock_client.messages.parse.call_args[1]
        assert call_kwargs["output_format"] is SimpleResult
        assert call_kwargs["model"] == "claude-sonnet-4-5-20250929"

    @pytest.mark.asyncio
    async def test_structured_with_system_prompt_cached(self, driver, mock_anthropic_module):
        """Should include cached system prompt when caching enabled."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.parse = AsyncMock(
            return_value=MockParseResponse(parsed_output=SimpleResult(answer="x", confidence=0.5))
        )
        driver._client = mock_client

        await driver.invoke_structured(
            "test",
            SimpleResult,
            system_prompt="You are an expert analyst.",
        )

        call_kwargs = mock_client.messages.parse.call_args[1]
        assert "system" in call_kwargs
        assert isinstance(call_kwargs["system"], list)
        assert call_kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert call_kwargs["system"][0]["text"] == "You are an expert analyst."

    @pytest.mark.asyncio
    async def test_structured_with_system_prompt_uncached(self, mock_anthropic_module):
        """Should pass plain string system prompt when caching disabled."""
        mock_module, mock_async_client = mock_anthropic_module

        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

            d = AnthropicSDKDriver(enable_caching=False)
            d._client = mock_async_client

        mock_async_client.messages.parse = AsyncMock(
            return_value=MockParseResponse(parsed_output=SimpleResult(answer="x", confidence=0.5))
        )

        await d.invoke_structured(
            "test",
            SimpleResult,
            system_prompt="Be helpful.",
        )

        call_kwargs = mock_async_client.messages.parse.call_args[1]
        assert call_kwargs["system"] == "Be helpful."

    @pytest.mark.asyncio
    async def test_structured_passes_kwargs(self, driver, mock_anthropic_module):
        """Should pass temperature and other kwargs."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.parse = AsyncMock(
            return_value=MockParseResponse(parsed_output=SimpleResult(answer="x", confidence=0.5))
        )
        driver._client = mock_client

        await driver.invoke_structured(
            "test",
            SimpleResult,
            temperature=0.0,
            top_p=0.9,
        )

        call_kwargs = mock_client.messages.parse.call_args[1]
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_structured_timeout(self, driver, mock_anthropic_module):
        """Should handle timeout gracefully."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.parse = AsyncMock(side_effect=TimeoutError())
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult, timeout=0.001)

        assert response.status == DriverResponseStatus.TIMEOUT
        assert response.error_code == "TIMEOUT"
        assert "Structured output timed out" in response.error_message

    @pytest.mark.asyncio
    async def test_structured_cancelled_propagates(self, driver, mock_anthropic_module):
        """Should re-raise CancelledError per protocol."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.parse = AsyncMock(side_effect=asyncio.CancelledError())
        driver._client = mock_client

        with pytest.raises(asyncio.CancelledError):
            await driver.invoke_structured("test", SimpleResult)

    @pytest.mark.asyncio
    async def test_structured_rate_limit(self, driver, mock_anthropic_module):
        """Should classify rate limit errors correctly."""
        _, mock_client = mock_anthropic_module

        class RateLimitError(Exception):
            pass

        mock_client.messages.parse = AsyncMock(side_effect=RateLimitError("Rate limited"))
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult)

        assert response.status == DriverResponseStatus.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_structured_generic_error(self, driver, mock_anthropic_module):
        """Should handle generic errors with proper classification."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.parse = AsyncMock(side_effect=ValueError("Invalid schema"))
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult)

        assert response.status == DriverResponseStatus.ERROR
        assert "Invalid schema" in response.error_message

    @pytest.mark.asyncio
    async def test_structured_token_counts(self, driver, mock_anthropic_module):
        """Should extract token usage from response."""
        _, mock_client = mock_anthropic_module

        mock_resp = MockParseResponse(parsed_output=SimpleResult(answer="42", confidence=0.99))
        mock_resp.usage = MockUsage(input_tokens=200, output_tokens=75)
        mock_client.messages.parse = AsyncMock(return_value=mock_resp)
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult)

        assert response.input_tokens == 200
        assert response.output_tokens == 75

    @pytest.mark.asyncio
    async def test_structured_no_parsed_output(self, driver, mock_anthropic_module):
        """Should handle response without parsed_output attribute."""
        _, mock_client = mock_anthropic_module

        mock_resp = MockParseResponse(content_text='{"answer": "test", "confidence": 0.5}')
        # Simulate old SDK that doesn't have parsed_output
        del mock_resp.parsed_output
        mock_client.messages.parse = AsyncMock(return_value=mock_resp)
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult)

        assert response.is_success
        assert response.raw["parsed"] is None


# =============================================================================
# invoke_json_schema() Tests
# =============================================================================


class TestInvokeJsonSchema:
    """Test structured output with raw JSON schemas."""

    @pytest.mark.asyncio
    async def test_basic_json_schema(self, driver, mock_anthropic_module):
        """Should return valid JSON matching the schema."""
        _, mock_client = mock_anthropic_module

        json_content = '{"name": "John", "email": "john@test.com", "active": true}'
        mock_client.messages.create = AsyncMock(return_value=MockCreateResponse(content_text=json_content))
        driver._client = mock_client

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "active": {"type": "boolean"},
            },
            "required": ["name", "email", "active"],
            "additionalProperties": False,
        }

        response = await driver.invoke_json_schema(
            "Extract: John Smith, john@test.com, active user",
            schema,
        )

        assert response.is_success
        parsed = json.loads(response.content)
        assert parsed["name"] == "John"
        assert parsed["email"] == "john@test.com"
        assert parsed["active"] is True

    @pytest.mark.asyncio
    async def test_json_schema_passes_output_config(self, driver, mock_anthropic_module):
        """Should include output_config.format in request."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(return_value=MockCreateResponse())
        driver._client = mock_client

        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
            "additionalProperties": False,
        }

        await driver.invoke_json_schema("test", schema)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "output_config" in call_kwargs
        assert call_kwargs["output_config"]["format"]["type"] == "json_schema"
        assert call_kwargs["output_config"]["format"]["schema"] is schema

    @pytest.mark.asyncio
    async def test_json_schema_with_system_prompt(self, driver, mock_anthropic_module):
        """Should pass system prompt through to request."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(return_value=MockCreateResponse())
        driver._client = mock_client

        schema = {"type": "object", "properties": {}, "additionalProperties": False}

        await driver.invoke_json_schema("test", schema, system_prompt="Extract data.")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" in call_kwargs

    @pytest.mark.asyncio
    async def test_json_schema_timeout(self, driver, mock_anthropic_module):
        """Should handle timeout gracefully."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(side_effect=TimeoutError())
        driver._client = mock_client

        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        response = await driver.invoke_json_schema("test", schema, timeout=0.001)

        assert response.status == DriverResponseStatus.TIMEOUT
        assert "JSON schema output timed out" in response.error_message

    @pytest.mark.asyncio
    async def test_json_schema_cancelled_propagates(self, driver, mock_anthropic_module):
        """Should re-raise CancelledError."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(side_effect=asyncio.CancelledError())
        driver._client = mock_client

        schema = {"type": "object", "properties": {}, "additionalProperties": False}

        with pytest.raises(asyncio.CancelledError):
            await driver.invoke_json_schema("test", schema)

    @pytest.mark.asyncio
    async def test_json_schema_error(self, driver, mock_anthropic_module):
        """Should handle API errors gracefully."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(side_effect=Exception("Schema too complex"))
        driver._client = mock_client

        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        response = await driver.invoke_json_schema("test", schema)

        assert response.status == DriverResponseStatus.ERROR
        assert "Schema too complex" in response.error_message

    @pytest.mark.asyncio
    async def test_json_schema_token_counts(self, driver, mock_anthropic_module):
        """Should extract token usage."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(return_value=MockCreateResponse())
        driver._client = mock_client

        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        response = await driver.invoke_json_schema("test", schema)

        assert response.input_tokens == 120
        assert response.output_tokens == 30


# =============================================================================
# Protocol Compliance Tests
# =============================================================================


class TestStructuredOutputProtocol:
    """Test that structured output methods don't break existing interface."""

    def test_driver_has_structured_methods(self):
        """Driver should expose both structured output methods."""
        from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

        assert hasattr(AnthropicSDKDriver, "invoke_structured")
        assert hasattr(AnthropicSDKDriver, "invoke_json_schema")

    def test_original_invoke_still_exists(self):
        """Original invoke() should not be affected."""
        from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

        assert hasattr(AnthropicSDKDriver, "invoke")
        assert hasattr(AnthropicSDKDriver, "invoke_stream")
        assert hasattr(AnthropicSDKDriver, "cancel")
        assert hasattr(AnthropicSDKDriver, "health_check")

    @pytest.mark.asyncio
    async def test_original_invoke_unaffected(self, driver, mock_anthropic_module):
        """Original invoke() should work identically after adding structured methods."""
        _, mock_client = mock_anthropic_module

        mock_resp = MagicMock()
        mock_resp.id = "msg_orig"
        mock_resp.content = [MockTextBlock("plain text response")]
        mock_resp.model = "claude-sonnet-4-5-20250929"
        mock_resp.stop_reason = "end_turn"
        mock_resp.usage = MockUsage()

        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        driver._client = mock_client

        response = await driver.invoke("Hello!")

        assert response.is_success
        assert "plain text response" in response.content
        # No parsed field in raw for regular invoke
        assert response.raw.get("parsed") is None


# =============================================================================
# Edge Cases
# =============================================================================


class TestStructuredOutputEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_content_response(self, driver, mock_anthropic_module):
        """Should handle empty content gracefully."""
        _, mock_client = mock_anthropic_module

        mock_resp = MockParseResponse(
            content_text="",
            parsed_output=SimpleResult(answer="", confidence=0.0),
        )
        mock_resp.content = []  # Empty content blocks
        mock_client.messages.parse = AsyncMock(return_value=mock_resp)
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult)

        assert response.is_success
        assert response.content == ""
        assert response.raw["parsed"] is not None

    @pytest.mark.asyncio
    async def test_max_tokens_override(self, driver, mock_anthropic_module):
        """Should allow max_tokens override via kwargs."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.parse = AsyncMock(
            return_value=MockParseResponse(parsed_output=SimpleResult(answer="x", confidence=0.5))
        )
        driver._client = mock_client

        await driver.invoke_structured("test", SimpleResult, max_tokens=16384)

        call_kwargs = mock_client.messages.parse.call_args[1]
        assert call_kwargs["max_tokens"] == 16384

    @pytest.mark.asyncio
    async def test_model_in_response(self, driver, mock_anthropic_module):
        """Should preserve model from response (may differ from request)."""
        _, mock_client = mock_anthropic_module

        mock_resp = MockParseResponse(
            parsed_output=SimpleResult(answer="x", confidence=0.5),
            model="claude-opus-4-6",
        )
        mock_client.messages.parse = AsyncMock(return_value=mock_resp)
        driver._client = mock_client

        response = await driver.invoke_structured("test", SimpleResult)

        assert response.model == "claude-opus-4-6"
        assert response.raw["model"] == "claude-opus-4-6"
