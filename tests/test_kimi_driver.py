"""
Tests for KimiSDKDriver (Moonshot AI K2.5).

These tests use mocks to validate driver behavior without real API calls.
They verify:
- Request building (parameters, tools, system prompts, vision)
- Response parsing (content, tool calls, token counts)
- Error classification (rate limit, auth, timeout)
- Streaming behavior
- Protocol compliance (DriverProtocol)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.drivers.protocol import (
    DriverResponseStatus,
)

# Skip all tests if openai is not installed (Kimi driver requires it)
pytest.importorskip("openai", reason="openai package required for Kimi driver tests")

# =============================================================================
# Mock OpenAI Response Objects (Kimi uses OpenAI-compatible API)
# =============================================================================


class MockOpenAIMessage:
    def __init__(self, content: str = "Hello from Kimi!", tool_calls: list = None):
        self.content = content
        self.tool_calls = tool_calls or []


class MockOpenAIChoice:
    def __init__(self, message: MockOpenAIMessage = None, finish_reason: str = "stop"):
        self.message = message or MockOpenAIMessage()
        self.finish_reason = finish_reason


class MockOpenAIUsage:
    def __init__(self, prompt_tokens: int = 100, completion_tokens: int = 50):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class MockOpenAIChatCompletion:
    def __init__(
        self,
        choices: list = None,
        usage: MockOpenAIUsage = None,
        model: str = "kimi-k2.5",
    ):
        self.id = "chatcmpl_test123"
        self.created = 1706832000
        self.model = model
        self.choices = choices or [MockOpenAIChoice()]
        self.usage = usage or MockOpenAIUsage()


class MockOpenAIToolCall:
    def __init__(self, name: str, arguments: str, tc_id: str = "call_123"):
        self.id = tc_id
        self.type = "function"
        self.function = MockOpenAIFunction(name, arguments)


class MockOpenAIFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class MockOpenAIStreamChunk:
    def __init__(self, content: str = None, finish_reason: str = None):
        self.choices = [MockOpenAIStreamChoice(content, finish_reason)]


class MockOpenAIStreamChoice:
    def __init__(self, content: str = None, finish_reason: str = None):
        self.delta = MockOpenAIDelta(content)
        self.finish_reason = finish_reason


class MockOpenAIDelta:
    def __init__(self, content: str = None):
        self.content = content


# =============================================================================
# KimiSDKDriver Tests
# =============================================================================


@pytest.fixture
def mock_openai_client():
    """Mock AsyncOpenAI client for Kimi."""
    with patch("core.drivers.kimi_sdk_driver.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
class TestKimiSDKDriver:
    """Tests for KimiSDKDriver."""

    async def test_invoke_basic_success(self, mock_openai_client):
        """Test basic invoke() with text response."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        # Mock API response
        mock_response = MockOpenAIChatCompletion(
            choices=[MockOpenAIChoice(MockOpenAIMessage("Kimi response"))],
            usage=MockOpenAIUsage(prompt_tokens=100, completion_tokens=50),
        )
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Create driver with mocked API key
        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver(model="kimi-k2.5")

        # Invoke
        result = await driver.invoke("Hello Kimi!")

        # Verify
        assert result.status == DriverResponseStatus.SUCCESS
        assert result.content == "Kimi response"
        assert result.provider == "kimi"
        assert result.model == "kimi-k2.5"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cost_usd > 0  # Should have non-zero cost estimate

        # Verify API call
        call_args = mock_openai_client.chat.completions.create.call_args
        assert call_args[1]["model"] == "kimi-k2.5"
        assert call_args[1]["messages"][-1]["role"] == "user"
        assert call_args[1]["messages"][-1]["content"] == "Hello Kimi!"

    async def test_invoke_with_system_prompt(self, mock_openai_client):
        """Test invoke() with system prompt."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        mock_response = MockOpenAIChatCompletion()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()

        await driver.invoke("User prompt", system_prompt="You are helpful")

        # Verify system prompt included
        call_args = mock_openai_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful"
        assert messages[1]["role"] == "user"

    async def test_invoke_with_vision(self, mock_openai_client):
        """Test invoke() with vision input (multimodal)."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        mock_response = MockOpenAIChatCompletion()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()

        await driver.invoke("What's in this image?", vision_input="data:image/png;base64,iVBORw0KG...")

        # Verify multimodal message format
        call_args = mock_openai_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) == 2
        assert user_msg["content"][0]["type"] == "text"
        assert user_msg["content"][1]["type"] == "image_url"

    async def test_invoke_with_tool_calls(self, mock_openai_client):
        """Test invoke() with tool calling."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        # Mock response with tool call
        tool_call = MockOpenAIToolCall(name="get_weather", arguments='{"location": "Paris"}', tc_id="call_abc123")
        mock_message = MockOpenAIMessage(content="", tool_calls=[tool_call])
        mock_response = MockOpenAIChatCompletion(choices=[MockOpenAIChoice(mock_message, finish_reason="tool_calls")])
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()

        # Invoke with tools
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = await driver.invoke("What's the weather?", tools=tools)

        # Verify tool call in response
        assert result.status == DriverResponseStatus.SUCCESS
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == '{"location": "Paris"}'
        assert result.tool_calls[0].id == "call_abc123"
        assert result.finish_reason == "tool_calls"

    async def test_invoke_timeout(self, mock_openai_client):
        """Test invoke() with timeout."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        # Mock timeout
        async def delayed_response(*args, **kwargs):
            await asyncio.sleep(10)
            return MockOpenAIChatCompletion()

        mock_openai_client.chat.completions.create = delayed_response

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver(timeout=0.1)

        result = await driver.invoke("Test")

        # Verify timeout status
        assert result.status == DriverResponseStatus.TIMEOUT
        assert result.content == ""
        assert "timeout" in result.error_message.lower()

    async def test_invoke_rate_limit_error(self, mock_openai_client):
        """Test invoke() with rate limit error."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        # Mock rate limit error
        async def raise_rate_limit(*args, **kwargs):
            raise Exception("rate_limit_exceeded: 429")

        mock_openai_client.chat.completions.create = raise_rate_limit

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()

        result = await driver.invoke("Test")

        # Verify error classification
        assert result.status == DriverResponseStatus.RATE_LIMITED
        assert result.content == ""
        assert "rate_limit" in result.error_message.lower()

    async def test_invoke_auth_error(self, mock_openai_client):
        """Test invoke() with authentication error."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        # Mock auth error
        async def raise_auth_error(*args, **kwargs):
            raise Exception("authentication failed: 401")

        mock_openai_client.chat.completions.create = raise_auth_error

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()

        result = await driver.invoke("Test")

        # Verify error classification
        assert result.status == DriverResponseStatus.AUTHENTICATION_ERROR
        assert "authentication" in result.error_message.lower()

    async def test_invoke_stream(self, mock_openai_client):
        """Test invoke_stream() with streaming response."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        # Mock streaming response
        async def mock_stream():
            chunks = [
                MockOpenAIStreamChunk(content="Hello", finish_reason=None),
                MockOpenAIStreamChunk(content=" Kimi", finish_reason=None),
                MockOpenAIStreamChunk(content="!", finish_reason="stop"),
            ]
            for chunk in chunks:
                yield chunk

        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_stream())

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()

        # Collect streamed chunks
        chunks = []
        async for chunk in driver.invoke_stream("Hello"):
            chunks.append(chunk)

        # Verify streaming
        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " Kimi"
        assert chunks[2].content == "!"
        assert chunks[2].finish_reason == "stop"

    async def test_missing_api_key(self):
        """Test driver initialization without API key."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError, match="KIMI_API_KEY not found"):
            KimiSDKDriver()

    async def test_model_alias_resolution(self, mock_openai_client):
        """Test model alias resolution."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        mock_response = MockOpenAIChatCompletion()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            # Test aliases
            driver_k25 = KimiSDKDriver(model="k2.5")
            assert driver_k25._model == "kimi-k2.5"

            driver_latest = KimiSDKDriver(model="latest")
            assert driver_latest._model == "kimi-latest"

            driver_default = KimiSDKDriver(model="default")
            assert driver_default._model == "kimi-k2.5"

            # Test direct model ID
            driver_direct = KimiSDKDriver(model="kimi-k2")
            assert driver_direct._model == "kimi-k2"

    async def test_response_caching(self, mock_openai_client):
        """Test response caching functionality."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver
        from core.drivers.response_cache import ResponseCache

        mock_response = MockOpenAIChatCompletion(choices=[MockOpenAIChoice(MockOpenAIMessage("Cached response"))])
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        cache = ResponseCache(max_size=100)

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver(enable_caching=True, response_cache=cache)

        # First call - cache miss
        result1 = await driver.invoke("Test prompt")
        assert result1.content == "Cached response"
        assert mock_openai_client.chat.completions.create.call_count == 1

        # Second call - cache hit (same prompt)
        result2 = await driver.invoke("Test prompt")
        assert result2.content == "Cached response"
        assert mock_openai_client.chat.completions.create.call_count == 1  # Still 1
        assert result2.raw["cached"] is True

    async def test_budget_tracker_integration(self, mock_openai_client):
        """Test budget tracker integration."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        mock_response = MockOpenAIChatCompletion(usage=MockOpenAIUsage(prompt_tokens=1000, completion_tokens=500))
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_tracker = MagicMock()

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()
            driver.set_budget_tracker(mock_tracker)

        await driver.invoke("Test")

        # Verify budget tracking (record_cost renamed to track_cost with new signature)
        assert mock_tracker.track_cost.called
        call_args = mock_tracker.track_cost.call_args
        assert call_args[0][0] == "kimi-k2.5"  # positional: model
        assert call_args[1]["input_tokens"] == 1000
        assert call_args[1]["output_tokens"] == 500

    async def test_health_monitor_integration(self, mock_openai_client):
        """Test health monitor integration."""
        from core.drivers.kimi_sdk_driver import KimiSDKDriver

        mock_response = MockOpenAIChatCompletion()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_monitor = MagicMock()

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            driver = KimiSDKDriver()
            driver.set_health_monitor(mock_monitor)

        # Successful call
        await driver.invoke("Test")
        assert mock_monitor.record_success.called

        # Error call
        mock_openai_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))
        await driver.invoke("Test")
        assert mock_monitor.record_error.called


# =============================================================================
# Factory Integration Tests
# =============================================================================


@pytest.mark.asyncio
class TestKimiFactoryIntegration:
    """Tests for Kimi driver factory integration."""

    async def test_factory_get_kimi_sdk(self):
        """Test AsyncDriverFactory.get_kimi_sdk()."""
        from core.config import OrchestratorConfig
        from core.drivers.async_factory import AsyncDriverFactory

        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            config = OrchestratorConfig(
                driver_mode="sdk",
                kimi_api_key="sk-test",
            )
            factory = AsyncDriverFactory(config)

            driver = factory.get_kimi_sdk()

            assert driver is not None
            assert driver._provider == "kimi"
            assert driver._model == "kimi-k2-thinking"

            # Verify singleton pattern
            driver2 = factory.get_kimi_sdk()
            assert driver is driver2

    async def test_factory_kimi_availability(self):
        """Test AsyncDriverFactory.kimi_sdk_available property."""
        from core.config import OrchestratorConfig
        from core.drivers.async_factory import AsyncDriverFactory

        # With API key
        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            config = OrchestratorConfig(driver_mode="sdk", kimi_api_key="sk-test")
            factory = AsyncDriverFactory(config)
            assert factory.kimi_sdk_available is True

        # Without API key
        with patch.dict("os.environ", {}, clear=True):
            config = OrchestratorConfig(driver_mode="sdk")
            factory = AsyncDriverFactory(config)
            assert factory.kimi_sdk_available is False

        # CLI mode (SDK unavailable)
        with patch.dict("os.environ", {"KIMI_API_KEY": "sk-test"}):
            config = OrchestratorConfig(driver_mode="cli", kimi_api_key="sk-test")
            factory = AsyncDriverFactory(config)
            assert factory.kimi_sdk_available is False
