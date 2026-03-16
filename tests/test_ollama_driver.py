"""
Tests for V12.4 Ollama Driver - Local LLM support.

Validates:
- OllamaDriver initialization and configuration
- Request payload construction
- Response parsing (content, tool calls, tokens)
- Error handling (timeout, HTTP errors, connection errors)
- Tool formatting (OpenAI format, simple format)
- Health check
- Model listing
- Streaming response parsing
- Module exports
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from core.drivers.ollama_driver import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    OllamaDriver,
)
from core.drivers.protocol import (
    DriverResponseStatus,
)

# =============================================================================
# Fixtures
# =============================================================================


class MockResponse:
    """Mock httpx response."""

    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text or json.dumps(self._data)

    def json(self):
        return self._data


def _make_chat_response(content="Hello!", tool_calls=None, model="llama3.1"):
    """Create a mock Ollama chat response."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "model": model,
        "message": message,
        "done": True,
        "prompt_eval_count": 50,
        "eval_count": 25,
        "total_duration": 1000000000,
    }


def _make_tags_response(models=None):
    """Create a mock /api/tags response."""
    if models is None:
        models = [
            {"name": "llama3.1:latest", "size": 4000000000},
            {"name": "codellama:latest", "size": 3000000000},
        ]
    return {"models": models}


@pytest.fixture
def mock_httpx():
    """Patch httpx to avoid real HTTP calls."""
    with patch("core.drivers.ollama_driver.OllamaDriver._get_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInitialization:
    """Test driver initialization."""

    def test_default_values(self):
        driver = OllamaDriver()
        assert driver.provider == "ollama"
        assert driver.model == DEFAULT_MODEL
        assert driver._base_url == DEFAULT_BASE_URL
        assert driver._timeout == DEFAULT_TIMEOUT

    def test_custom_values(self):
        driver = OllamaDriver(
            model="codellama",
            base_url="http://gpu-server:11434",
            timeout=60.0,
            temperature=0.3,
            num_ctx=8192,
        )
        assert driver.model == "codellama"
        assert driver._base_url == "http://gpu-server:11434"
        assert driver._temperature == 0.3
        assert driver._num_ctx == 8192

    def test_trailing_slash_stripped(self):
        driver = OllamaDriver(base_url="http://localhost:11434/")
        assert driver._base_url == "http://localhost:11434"

    def test_repr(self):
        driver = OllamaDriver(model="mistral")
        r = repr(driver)
        assert "mistral" in r
        assert "OllamaDriver" in r


# =============================================================================
# Invoke Tests
# =============================================================================


class TestInvoke:
    """Test invoke method."""

    @pytest.mark.asyncio
    async def test_basic_invoke(self, mock_httpx):
        data = _make_chat_response(content="Hi there!")
        mock_httpx.post = AsyncMock(return_value=MockResponse(200, data))

        driver = OllamaDriver()
        response = await driver.invoke("Hello")

        assert response.is_success
        assert response.content == "Hi there!"
        assert response.provider == "ollama"
        assert response.input_tokens == 50
        assert response.output_tokens == 25

    @pytest.mark.asyncio
    async def test_invoke_with_system_prompt(self, mock_httpx):
        data = _make_chat_response(content="OK")
        mock_httpx.post = AsyncMock(return_value=MockResponse(200, data))

        driver = OllamaDriver()
        await driver.invoke("Hello", system_prompt="You are helpful")

        call_args = mock_httpx.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        messages = payload.get("messages", [])
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_invoke_with_tools(self, mock_httpx):
        tool_calls = [
            {
                "function": {
                    "name": "get_weather",
                    "arguments": {"city": "Paris"},
                }
            }
        ]
        data = _make_chat_response(content="", tool_calls=tool_calls)
        mock_httpx.post = AsyncMock(return_value=MockResponse(200, data))

        driver = OllamaDriver()
        tools = [{"name": "get_weather", "description": "Get weather", "parameters": {}}]
        response = await driver.invoke("Weather in Paris?", tools=tools)

        assert response.is_success
        assert response.has_tool_calls
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "Paris"}

    @pytest.mark.asyncio
    async def test_invoke_http_error(self, mock_httpx):
        mock_httpx.post = AsyncMock(return_value=MockResponse(500, text="Internal Server Error"))

        driver = OllamaDriver()
        response = await driver.invoke("Hello")

        assert not response.is_success
        assert response.status == DriverResponseStatus.ERROR
        assert "500" in response.error_message

    @pytest.mark.asyncio
    async def test_invoke_timeout(self, mock_httpx):
        mock_httpx.post = AsyncMock(side_effect=TimeoutError())

        driver = OllamaDriver()
        response = await driver.invoke("Hello")

        assert not response.is_success
        assert response.status == DriverResponseStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_invoke_connection_error(self, mock_httpx):
        mock_httpx.post = AsyncMock(side_effect=ConnectionError("Connection refused"))

        driver = OllamaDriver()
        response = await driver.invoke("Hello")

        assert not response.is_success
        assert "Connection refused" in response.error_message

    @pytest.mark.asyncio
    async def test_invoke_cancelled(self, mock_httpx):
        mock_httpx.post = AsyncMock(side_effect=asyncio.CancelledError())

        driver = OllamaDriver()
        with pytest.raises(asyncio.CancelledError):
            await driver.invoke("Hello")


# =============================================================================
# Tool Formatting Tests
# =============================================================================


class TestToolFormatting:
    """Test tool definition formatting."""

    def test_openai_format_passthrough(self):
        driver = OllamaDriver()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {"type": "object"},
                },
            }
        ]
        formatted = driver._format_tools(tools)
        assert formatted == tools

    def test_simple_format_conversion(self):
        driver = OllamaDriver()
        tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ]
        formatted = driver._format_tools(tools)
        assert formatted[0]["type"] == "function"
        assert formatted[0]["function"]["name"] == "read_file"
        assert formatted[0]["function"]["description"] == "Read a file"

    def test_input_schema_key(self):
        driver = OllamaDriver()
        tools = [
            {
                "name": "bash",
                "input_schema": {"type": "object"},
            }
        ]
        formatted = driver._format_tools(tools)
        assert formatted[0]["function"]["parameters"] == {"type": "object"}


# =============================================================================
# Response Parsing Tests
# =============================================================================


class TestResponseParsing:
    """Test response parsing."""

    def test_basic_parsing(self):
        driver = OllamaDriver()
        data = _make_chat_response(content="Test output", model="mistral")
        response = driver._parse_response(data, elapsed_ms=150.0)

        assert response.content == "Test output"
        assert response.model == "mistral"
        assert response.provider == "ollama"
        assert response.latency_ms == 150.0
        assert response.input_tokens == 50
        assert response.output_tokens == 25

    def test_tool_call_parsing(self):
        driver = OllamaDriver()
        data = _make_chat_response(
            content="",
            tool_calls=[
                {
                    "function": {
                        "name": "calculator",
                        "arguments": {"expr": "2+2"},
                    },
                }
            ],
        )
        response = driver._parse_response(data, elapsed_ms=100.0)

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "calculator"
        assert response.tool_calls[0].arguments == {"expr": "2+2"}

    def test_empty_response(self):
        driver = OllamaDriver()
        data = {"message": {}, "done": True}
        response = driver._parse_response(data, elapsed_ms=50.0)

        assert response.content == ""
        assert response.is_success
        assert response.tool_calls == []

    def test_raw_data_preserved(self):
        driver = OllamaDriver()
        data = _make_chat_response(content="test")
        response = driver._parse_response(data, elapsed_ms=50.0)

        assert response.raw is not None
        assert response.raw["model"] == "llama3.1"


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_healthy(self, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=MockResponse(200, _make_tags_response()))

        driver = OllamaDriver()
        assert await driver.health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy_server_down(self, mock_httpx):
        mock_httpx.get = AsyncMock(side_effect=ConnectionError())

        driver = OllamaDriver()
        assert await driver.health_check() is False

    @pytest.mark.asyncio
    async def test_unhealthy_bad_status(self, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=MockResponse(503))

        driver = OllamaDriver()
        assert await driver.health_check() is False


# =============================================================================
# Model Listing Tests
# =============================================================================


class TestListModels:
    """Test model listing."""

    @pytest.mark.asyncio
    async def test_list_models(self, mock_httpx):
        models = [
            {"name": "llama3.1:latest", "size": 4000000000},
            {"name": "codellama:7b", "size": 3000000000},
        ]
        mock_httpx.get = AsyncMock(return_value=MockResponse(200, _make_tags_response(models)))

        driver = OllamaDriver()
        result = await driver.list_models()

        assert len(result) == 2
        assert result[0]["name"] == "llama3.1:latest"

    @pytest.mark.asyncio
    async def test_list_models_empty(self, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=MockResponse(200, {"models": []}))

        driver = OllamaDriver()
        result = await driver.list_models()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_models_error(self, mock_httpx):
        mock_httpx.get = AsyncMock(side_effect=ConnectionError())

        driver = OllamaDriver()
        result = await driver.list_models()
        assert result == []


# =============================================================================
# Cancel Tests
# =============================================================================


class TestCancel:
    """Test cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_with_client(self):
        driver = OllamaDriver()
        mock_client = AsyncMock()
        driver._client = mock_client
        assert await driver.cancel() is True
        mock_client.aclose.assert_called_once()
        assert driver._client is None

    @pytest.mark.asyncio
    async def test_cancel_no_client(self):
        driver = OllamaDriver()
        assert await driver.cancel() is False


# =============================================================================
# Close Tests
# =============================================================================


class TestClose:
    """Test resource cleanup."""

    @pytest.mark.asyncio
    async def test_close(self):
        driver = OllamaDriver()
        driver._client = AsyncMock()
        await driver.close()
        assert driver._client is None

    @pytest.mark.asyncio
    async def test_close_no_client(self):
        driver = OllamaDriver()
        await driver.close()  # Should not raise


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that Ollama driver is importable."""

    def test_from_drivers_package(self):
        from core.drivers import OllamaDriver

        assert OllamaDriver is not None

    def test_from_module(self):
        from core.drivers.ollama_driver import OllamaDriver

        assert OllamaDriver is not None

    def test_constants_exported(self):
        from core.drivers.ollama_driver import (
            DEFAULT_BASE_URL,
            DEFAULT_MODEL,
            DEFAULT_TIMEOUT,
        )

        assert DEFAULT_BASE_URL == "http://localhost:11434"
        assert DEFAULT_MODEL == "llama3.1"
        assert DEFAULT_TIMEOUT == 120.0
