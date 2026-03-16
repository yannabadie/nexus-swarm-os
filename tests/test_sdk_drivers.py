"""
Tests for SDK-native LLM drivers (Anthropic + Google GenAI).

These tests use mocks to validate driver behavior without real API calls.
They verify:
- Request building (parameters, tools, system prompts)
- Response parsing (content, tool calls, token counts)
- Error classification (rate limit, auth, timeout)
- Streaming behavior
- Protocol compliance (DriverProtocol)
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.drivers.protocol import (
    DriverResponse,
    DriverResponseStatus,
    StreamChunk,
    ToolCall,
)

# =============================================================================
# Mock Anthropic Response Objects
# =============================================================================


class MockAnthropicTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class MockAnthropicToolUseBlock:
    def __init__(self, name: str, input_data: dict, block_id: str = "tool_1"):
        self.type = "tool_use"
        self.name = name
        self.input = input_data
        self.id = block_id


class MockAnthropicUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class MockAnthropicResponse:
    def __init__(
        self,
        content: list = None,
        model: str = "claude-sonnet-4-5-20250929",
        stop_reason: str = "end_turn",
        usage: MockAnthropicUsage = None,
    ):
        self.id = "msg_test123"
        self.content = content or [MockAnthropicTextBlock("Hello from Claude!")]
        self.model = model
        self.stop_reason = stop_reason
        self.usage = usage or MockAnthropicUsage()


# =============================================================================
# Mock Google GenAI Response Objects
# =============================================================================


class MockGenAIPart:
    def __init__(self, text: str = None, function_call: Any = None):
        self.text = text
        self.function_call = function_call


class MockGenAIFunctionCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class MockGenAIContent:
    def __init__(self, parts: list = None):
        self.parts = parts or [MockGenAIPart(text="Hello from Gemini!")]


class MockGenAICandidate:
    def __init__(self, content: MockGenAIContent = None):
        self.content = content or MockGenAIContent()


class MockGenAIUsageMetadata:
    def __init__(self, prompt_token_count: int = 80, candidates_token_count: int = 40):
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class MockGenAIResponse:
    def __init__(
        self,
        text: str = "Hello from Gemini!",
        candidates: list = None,
        usage_metadata: MockGenAIUsageMetadata = None,
    ):
        self.text = text
        self.candidates = candidates or [MockGenAICandidate()]
        self.usage_metadata = usage_metadata or MockGenAIUsageMetadata()


# =============================================================================
# Anthropic SDK Driver Tests
# =============================================================================


class TestAnthropicSDKDriver:
    """Test the Anthropic SDK driver with mocked API."""

    @pytest.fixture
    def mock_anthropic_module(self):
        """Create a mock anthropic module."""
        mock_module = MagicMock()
        mock_async_client = AsyncMock()
        mock_sync_client = MagicMock()
        mock_module.AsyncAnthropic.return_value = mock_async_client
        mock_module.Anthropic.return_value = mock_sync_client
        return mock_module, mock_async_client

    @pytest.fixture
    def driver(self, mock_anthropic_module):
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

    @pytest.mark.asyncio
    async def test_basic_invoke(self, driver, mock_anthropic_module):
        """Test basic invocation returns proper DriverResponse."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(return_value=MockAnthropicResponse())
        driver._client = mock_client

        response = await driver.invoke("Hello!")

        assert isinstance(response, DriverResponse)
        assert response.is_success
        assert "Hello from Claude!" in response.content
        assert response.provider == "claude"
        assert response.input_tokens == 100
        assert response.output_tokens == 50
        assert response.latency_ms > 0

    @pytest.mark.asyncio
    async def test_invoke_with_system_prompt(self, driver, mock_anthropic_module):
        """Test system prompt is included in request."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(return_value=MockAnthropicResponse())
        driver._client = mock_client

        await driver.invoke("Hello!", system_prompt="You are a helpful assistant.")

        call_kwargs = mock_client.messages.create.call_args[1]
        # System prompt should be present (either as string or cache-controlled list)
        assert "system" in call_kwargs

    @pytest.mark.asyncio
    async def test_invoke_with_tools(self, driver, mock_anthropic_module):
        """Test tool definitions are formatted correctly."""
        _, mock_client = mock_anthropic_module

        tool_use_response = MockAnthropicResponse(
            content=[
                MockAnthropicToolUseBlock(
                    name="read_file",
                    input_data={"path": "/tmp/test.py"},
                    block_id="tool_abc",
                )
            ]
        )
        mock_client.messages.create = AsyncMock(return_value=tool_use_response)
        driver._client = mock_client

        tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            }
        ]

        response = await driver.invoke("Read the file", tools=tools)

        assert response.has_tool_calls
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"path": "/tmp/test.py"}
        assert response.tool_calls[0].id == "tool_abc"

    @pytest.mark.asyncio
    async def test_invoke_timeout(self, driver, mock_anthropic_module):
        """Test timeout handling."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(side_effect=TimeoutError())
        driver._client = mock_client

        response = await driver.invoke("Hello!", timeout=0.001)

        assert response.status == DriverResponseStatus.TIMEOUT
        assert response.error_code == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_invoke_rate_limit(self, driver, mock_anthropic_module):
        """Test rate limit error classification."""
        _, mock_client = mock_anthropic_module

        class RateLimitError(Exception):
            pass

        mock_client.messages.create = AsyncMock(side_effect=RateLimitError("Rate limited"))
        driver._client = mock_client

        response = await driver.invoke("Hello!")

        assert response.status == DriverResponseStatus.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self, driver, mock_anthropic_module):
        """Test that CancelledError is re-raised per protocol."""
        _, mock_client = mock_anthropic_module
        mock_client.messages.create = AsyncMock(side_effect=asyncio.CancelledError())
        driver._client = mock_client

        with pytest.raises(asyncio.CancelledError):
            await driver.invoke("Hello!")

    def test_provider_property(self, driver):
        """Test provider returns 'claude'."""
        assert driver.provider == "claude"

    def test_model_property(self, driver):
        """Test model returns configured model."""
        assert driver.model == "claude-sonnet-4-5-20250929"

    @pytest.mark.asyncio
    async def test_cancel_returns_true(self, driver):
        """Test cancel() is a no-op that returns True."""
        assert await driver.cancel() is True

    def test_request_building_with_caching(self, driver):
        """Test that prompt caching is enabled by default."""
        params = driver._build_request(
            prompt="Test",
            system_prompt="Be helpful",
            tools=None,
        )
        # System should be a list with cache_control
        assert isinstance(params["system"], list)
        assert params["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_request_building_without_caching(self, mock_anthropic_module):
        """Test request without caching."""
        mock_module, mock_async_client = mock_anthropic_module

        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

            d = AnthropicSDKDriver(enable_caching=False)
            d._client = mock_async_client

        params = d._build_request(
            prompt="Test",
            system_prompt="Be helpful",
            tools=None,
        )
        assert params["system"] == "Be helpful"

    def test_tool_formatting(self, driver):
        """Test various tool definition formats are handled."""
        # Standard format
        tools_standard = [{"name": "foo", "description": "bar", "input_schema": {"type": "object"}}]
        formatted = driver._format_tools(tools_standard)
        assert formatted[0]["name"] == "foo"

        # OpenAI-style format
        tools_openai = [{"function": {"name": "baz", "description": "qux", "parameters": {"type": "object"}}}]
        formatted = driver._format_tools(tools_openai)
        assert formatted[0]["name"] == "baz"


# =============================================================================
# Google GenAI SDK Driver Tests
# =============================================================================


class TestGoogleGenAISDKDriver:
    """Test the Google GenAI SDK driver with mocked API."""

    @pytest.fixture
    def mock_genai_module(self):
        """Create a mock google.genai module."""
        mock_genai = MagicMock()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Mock types
        mock_types = MagicMock()
        mock_genai.types = mock_types
        mock_types.GenerateContentConfig = MagicMock()
        mock_types.FunctionDeclaration = MagicMock()
        mock_types.Tool = MagicMock()

        return mock_genai, mock_client

    @pytest.fixture
    def driver(self, mock_genai_module):
        """Create a GoogleGenAISDKDriver with mocked SDK."""
        mock_genai, mock_client = mock_genai_module

        mock_google = MagicMock()
        mock_google.genai = mock_genai

        with (
            patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}),
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-456"}),
        ):
            from core.drivers.google_genai_sdk_driver import GoogleGenAISDKDriver

            d = GoogleGenAISDKDriver(model="gemini-3-pro-preview")
            d._client = mock_client
            d._genai = mock_genai
            return d

    @pytest.mark.asyncio
    async def test_basic_invoke(self, driver, mock_genai_module):
        """Test basic invocation returns proper DriverResponse."""
        _, mock_client = mock_genai_module
        mock_client.models.generate_content.return_value = MockGenAIResponse()
        driver._client = mock_client

        response = await driver.invoke("Hello!")

        assert isinstance(response, DriverResponse)
        assert response.is_success
        assert "Hello from Gemini!" in response.content
        assert response.provider == "gemini"
        assert response.input_tokens == 80
        assert response.output_tokens == 40

    @pytest.mark.asyncio
    async def test_invoke_with_function_call(self, driver, mock_genai_module):
        """Test function calling response parsing."""
        _, mock_client = mock_genai_module

        fc = MockGenAIFunctionCall("search_web", {"query": "NEXUS docs"})
        part = MockGenAIPart(function_call=fc)
        content = MockGenAIContent(parts=[part])
        candidate = MockGenAICandidate(content=content)

        response_obj = MockGenAIResponse(
            text=None,
            candidates=[candidate],
        )
        # Override text to avoid AttributeError
        response_obj.text = None

        mock_client.models.generate_content.return_value = response_obj
        driver._client = mock_client

        response = await driver.invoke("Search for docs")

        assert response.has_tool_calls
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "search_web"
        assert response.tool_calls[0].arguments == {"query": "NEXUS docs"}

    @pytest.mark.asyncio
    async def test_invoke_timeout(self, driver, mock_genai_module):
        """Test timeout handling."""
        _, mock_client = mock_genai_module
        import time

        def slow_call(*args, **kwargs):
            time.sleep(5)  # Block longer than timeout

        mock_client.models.generate_content.side_effect = slow_call
        driver._client = mock_client

        response = await driver.invoke("Hello!", timeout=0.01)
        assert response.status == DriverResponseStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_invoke_auth_error(self, driver, mock_genai_module):
        """Test authentication error classification."""
        _, mock_client = mock_genai_module
        mock_client.models.generate_content.side_effect = Exception("403 Permission denied")
        driver._client = mock_client

        response = await driver.invoke("Hello!")

        assert response.status == DriverResponseStatus.ERROR
        assert response.error_code == "AUTH_ERROR"

    @pytest.mark.asyncio
    async def test_invoke_rate_limit_error(self, driver, mock_genai_module):
        """Test rate limit error classification."""
        _, mock_client = mock_genai_module
        mock_client.models.generate_content.side_effect = Exception("Rate limit exceeded")
        driver._client = mock_client

        response = await driver.invoke("Hello!")

        assert response.status == DriverResponseStatus.RATE_LIMITED

    def test_provider_property(self, driver):
        """Test provider returns 'gemini'."""
        assert driver.provider == "gemini"

    def test_model_property(self, driver):
        """Test model returns configured model."""
        assert driver.model == "gemini-3-pro-preview"

    @pytest.mark.asyncio
    async def test_cancel_returns_true(self, driver):
        """Test cancel() is a no-op returning True."""
        assert await driver.cancel() is True

    def test_error_classification(self, driver):
        """Test various error classification."""
        # Rate limit
        status, code = driver._classify_error(Exception("rate limit exceeded"))
        assert status == DriverResponseStatus.RATE_LIMITED

        # Quota
        status, code = driver._classify_error(Exception("quota exhausted"))
        assert status == DriverResponseStatus.RATE_LIMITED

        # Auth
        status, code = driver._classify_error(Exception("403 permission denied"))
        assert status == DriverResponseStatus.ERROR
        assert code == "AUTH_ERROR"

        # Not found
        status, code = driver._classify_error(Exception("404 not found"))
        assert status == DriverResponseStatus.ERROR
        assert code == "MODEL_NOT_FOUND"

        # Unknown
        status, code = driver._classify_error(Exception("something random"))
        assert status == DriverResponseStatus.ERROR
        assert code == "UNKNOWN_ERROR"

    def test_tool_call_extraction_empty_candidates(self, driver):
        """Test extraction with no candidates."""
        response = MockGenAIResponse()
        response.candidates = None
        result = driver._extract_tool_calls(response)
        assert result == []


# =============================================================================
# Protocol Compliance Tests
# =============================================================================


class TestProtocolCompliance:
    """Test that both SDK drivers comply with DriverProtocol."""

    def test_anthropic_driver_has_required_methods(self):
        """Verify AnthropicSDKDriver exposes all DriverProtocol methods."""
        from core.drivers.anthropic_sdk_driver import AnthropicSDKDriver

        assert hasattr(AnthropicSDKDriver, "invoke")
        assert hasattr(AnthropicSDKDriver, "invoke_stream")
        assert hasattr(AnthropicSDKDriver, "cancel")
        assert hasattr(AnthropicSDKDriver, "health_check")
        assert hasattr(AnthropicSDKDriver, "provider")
        assert hasattr(AnthropicSDKDriver, "model")

    def test_google_driver_has_required_methods(self):
        """Verify GoogleGenAISDKDriver exposes all DriverProtocol methods."""
        from core.drivers.google_genai_sdk_driver import GoogleGenAISDKDriver

        assert hasattr(GoogleGenAISDKDriver, "invoke")
        assert hasattr(GoogleGenAISDKDriver, "invoke_stream")
        assert hasattr(GoogleGenAISDKDriver, "cancel")
        assert hasattr(GoogleGenAISDKDriver, "health_check")
        assert hasattr(GoogleGenAISDKDriver, "provider")
        assert hasattr(GoogleGenAISDKDriver, "model")

    def test_driver_response_to_dict_roundtrip(self):
        """Test DriverResponse serialization."""
        response = DriverResponse(
            content="Hello",
            status=DriverResponseStatus.SUCCESS,
            model="test-model",
            provider="test",
            tool_calls=[ToolCall(name="foo", arguments={"bar": 1}, id="tc_1")],
            latency_ms=42.5,
            input_tokens=100,
            output_tokens=50,
        )
        d = response.to_dict()
        assert d["content"] == "Hello"
        assert d["status"] == "SUCCESS"
        assert d["model"] == "test-model"
        assert d["latency_ms"] == 42.5
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["name"] == "foo"

    def test_stream_chunk_fields(self):
        """Test StreamChunk dataclass fields."""
        chunk = StreamChunk(content="Hello", is_final=False)
        assert chunk.content == "Hello"
        assert chunk.is_final is False
        assert chunk.tool_call is None

        final = StreamChunk(
            content="",
            is_final=True,
            latency_ms=100.0,
            input_tokens=50,
            output_tokens=25,
        )
        assert final.is_final is True
        assert final.latency_ms == 100.0


# =============================================================================
# Cross-Driver Consistency Tests
# =============================================================================


class TestCrossDriverConsistency:
    """Test that both drivers produce consistent response formats."""

    @pytest.mark.asyncio
    async def test_error_responses_have_same_structure(self):
        """Both drivers should produce identically-structured error responses."""

        # Create error responses via the protocol helper
        from core.drivers.protocol import BaseAsyncDriver

        class DummyDriver(BaseAsyncDriver):
            async def invoke(self, *a, **kw):
                return self._create_error_response("test error", "TEST")

            async def invoke_stream(self, *a, **kw):
                yield StreamChunk(content="")

            async def cancel(self, *a, **kw):
                return True

        d1 = DummyDriver(provider="claude", model="test")
        d2 = DummyDriver(provider="gemini", model="test")

        r1 = await d1.invoke("")
        r2 = await d2.invoke("")

        # Same structure
        assert r1.status == r2.status == DriverResponseStatus.ERROR
        assert r1.error_message == r2.error_message == "test error"
        assert r1.error_code == r2.error_code == "TEST"
        assert r1.content == r2.content == ""
