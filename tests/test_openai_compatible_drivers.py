"""
Tests for OpenAI and MiniMax SDK drivers.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.drivers.protocol import DriverResponseStatus

pytest.importorskip("openai", reason="openai package required for OpenAI-compatible driver tests")


class MockOpenAIMessage:
    def __init__(self, content: str = "Hello!", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class MockOpenAIChoice:
    def __init__(self, message: MockOpenAIMessage | None = None, finish_reason: str = "stop"):
        self.message = message or MockOpenAIMessage()
        self.finish_reason = finish_reason


class MockOpenAIUsage:
    def __init__(self, prompt_tokens: int = 100, completion_tokens: int = 50):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class MockOpenAIChatCompletion:
    def __init__(self, choices: list | None = None, usage: MockOpenAIUsage | None = None, model: str = "gpt-5.4"):
        self.id = "chatcmpl_test123"
        self.created = 1706832000
        self.model = model
        self.choices = choices or [MockOpenAIChoice()]
        self.usage = usage or MockOpenAIUsage()


class MockOpenAIStreamChunk:
    def __init__(self, content: str | None = None, finish_reason: str | None = None):
        self.choices = [MockOpenAIStreamChoice(content, finish_reason)]


class MockOpenAIStreamChoice:
    def __init__(self, content: str | None = None, finish_reason: str | None = None):
        self.delta = MockOpenAIDelta(content)
        self.finish_reason = finish_reason


class MockOpenAIDelta:
    def __init__(self, content: str | None = None):
        self.content = content


@pytest.fixture
def mock_openai_client():
    with patch("core.drivers.openai_sdk_driver.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_minimax_client():
    with patch("core.drivers.minimax_sdk_driver.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
class TestOpenAISDKDriver:
    async def test_invoke_success(self, mock_openai_client):
        from core.drivers.openai_sdk_driver import OpenAISDKDriver

        mock_response = MockOpenAIChatCompletion(
            choices=[MockOpenAIChoice(MockOpenAIMessage("OpenAI response"))],
            usage=MockOpenAIUsage(prompt_tokens=120, completion_tokens=80),
            model="gpt-5.4",
        )
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            driver = OpenAISDKDriver(model="gpt-5.4")

        result = await driver.invoke("Hello OpenAI!")

        assert result.status == DriverResponseStatus.SUCCESS
        assert result.content == "OpenAI response"
        assert result.provider == "openai"
        assert result.model == "gpt-5.4"

    async def test_invoke_stream(self, mock_openai_client):
        from core.drivers.openai_sdk_driver import OpenAISDKDriver

        async def mock_stream():
            for chunk in [
                MockOpenAIStreamChunk("Hello", None),
                MockOpenAIStreamChunk(" OpenAI", None),
                MockOpenAIStreamChunk("!", "stop"),
            ]:
                yield chunk

        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_stream())

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            driver = OpenAISDKDriver()

        chunks = []
        async for chunk in driver.invoke_stream("Hello"):
            chunks.append(chunk)

        assert [chunk.content for chunk in chunks] == ["Hello", " OpenAI", "!"]
        assert chunks[-1].finish_reason == "stop"

    async def test_factory_support(self):
        from core.config import OrchestratorConfig
        from core.drivers.async_factory import AsyncDriverFactory

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            factory = AsyncDriverFactory(OrchestratorConfig(driver_mode="sdk", openai_api_key="sk-test"))
            driver = factory.get_openai_sdk()
            assert driver.provider == "openai"
            assert factory.openai_sdk_available is True


@pytest.mark.asyncio
class TestMiniMaxSDKDriver:
    async def test_invoke_success(self, mock_minimax_client):
        from core.drivers.minimax_sdk_driver import MiniMaxSDKDriver

        mock_response = MockOpenAIChatCompletion(
            choices=[MockOpenAIChoice(MockOpenAIMessage("MiniMax response"))],
            usage=MockOpenAIUsage(prompt_tokens=140, completion_tokens=60),
            model="MiniMax-M2.5",
        )
        mock_minimax_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"MINIMAX_API_KEY": "sk-test"}):
            driver = MiniMaxSDKDriver(model="MiniMax-M2.5")

        result = await driver.invoke("Hello MiniMax!")

        assert result.status == DriverResponseStatus.SUCCESS
        assert result.content == "MiniMax response"
        assert result.provider == "minimax"
        assert result.model == "MiniMax-M2.5"

    async def test_invoke_timeout(self, mock_minimax_client):
        from core.drivers.minimax_sdk_driver import MiniMaxSDKDriver

        async def delayed_response(*args, **kwargs):
            await asyncio.sleep(10)
            return MockOpenAIChatCompletion()

        mock_minimax_client.chat.completions.create = delayed_response

        with patch.dict("os.environ", {"MINIMAX_API_KEY": "sk-test"}):
            driver = MiniMaxSDKDriver(timeout=0.1)

        result = await driver.invoke("Test")

        assert result.status == DriverResponseStatus.TIMEOUT
        assert result.error_code == "TIMEOUT"

    async def test_factory_support(self):
        from core.config import OrchestratorConfig
        from core.drivers.async_factory import AsyncDriverFactory

        with patch.dict("os.environ", {"MINIMAX_API_KEY": "sk-test"}):
            factory = AsyncDriverFactory(OrchestratorConfig(driver_mode="sdk", minimax_api_key="sk-test"))
            driver = factory.get_minimax_sdk()
            assert driver.provider == "minimax"
            assert factory.minimax_sdk_available is True
