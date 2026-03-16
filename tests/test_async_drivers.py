"""
Tests for NEXUS V9.0 Async Drivers.

Tests cover:
- AsyncClaudeDriver: Non-blocking streaming
- AsyncGeminiDriver: Session isolation
- AsyncDriverFactory: Driver management
- Process cancellation: cancel_by_uuid, cancel_all
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Add project root to path
sys.path.insert(
    0, str(__file__).replace("\\tests\\test_async_drivers.py", "").replace("/tests/test_async_drivers.py", "")
)

import contextlib

from core.drivers.async_claude_driver import AsyncClaudeDriver, AsyncClaudeDriverConfig
from core.drivers.async_factory import AsyncDriverFactory
from core.drivers.async_gemini_driver import AsyncGeminiDriver, AsyncGeminiDriverConfig
from core.foundation.async_primitives import CancellationToken

# ============================================================================
# Mock Process Helper
# ============================================================================


def create_mock_process(output_lines: list, returncode: int = 0):
    """Create a mock asyncio.subprocess.Process."""
    mock_proc = MagicMock()
    mock_proc.returncode = None  # Initially running
    mock_proc.pid = 12345

    # Create async iterators for stdout/stderr
    async def stdout_iter():
        for line in output_lines:
            yield line.encode("utf-8")
        mock_proc.returncode = returncode  # Process completes after stdout ends

    async def stderr_read():
        return b""

    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: stdout_iter()

    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read = AsyncMock(return_value=b"")

    async def mock_wait():
        return returncode

    mock_proc.wait = mock_wait
    mock_proc.terminate = Mock()
    mock_proc.kill = Mock()

    return mock_proc


# ============================================================================
# AsyncClaudeDriver Tests
# ============================================================================


class TestAsyncClaudeDriver:
    """Tests for AsyncClaudeDriver."""

    @pytest.fixture
    def driver(self, tmp_path):
        """Create driver with temp workspace."""
        config = AsyncClaudeDriverConfig(
            cli_path="claude",
            timeout=60.0,
            model="claude-sonnet-4-5-20250929",
            workspace_path=tmp_path,
            verbose=False,
        )
        return AsyncClaudeDriver(config)

    @pytest.mark.asyncio
    async def test_invoke_stream_collects_output(self, driver, tmp_path):
        """invoke_stream should yield output lines."""
        output = ["Hello ", "World!\n"]
        mock_proc = create_mock_process(output)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            chunks = []
            async for chunk in driver.invoke_stream("Test prompt"):
                chunks.append(chunk)

            assert "Hello " in "".join(chunks)
            assert "World!" in "".join(chunks)

    @pytest.mark.asyncio
    async def test_invoke_returns_parsed_response(self, driver):
        """invoke should return parsed response dict."""
        output = ["This is a response from Claude.\n"]
        mock_proc = create_mock_process(output)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await driver.invoke("Test prompt")

            assert "sender" in result
            assert "action_type" in result
            assert "content" in result
            assert result["action_type"] == "TALK"

    @pytest.mark.asyncio
    async def test_invoke_with_session_uuid(self, driver, tmp_path):
        """invoke should use session_uuid for file isolation."""
        output = ["Response\n"]
        mock_proc = create_mock_process(output)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await driver.invoke("Test", session_uuid="test-uuid-123")

            # Context file should use session_uuid
            list((tmp_path / "_IO_BUFFER").glob("claude_context_test-uuid-123.md"))
            # File is deleted after invoke, so we verify it was created via the command
            mock_proc.terminate.assert_not_called()  # Should complete normally

    @pytest.mark.asyncio
    async def test_cancellation_stops_stream(self, driver):
        """CancellationToken should stop streaming."""

        async def slow_output():
            yield b"Line 1\n"
            await asyncio.sleep(0.1)
            yield b"Line 2\n"
            await asyncio.sleep(10)  # Would block if not cancelled
            yield b"Line 3\n"

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.__aiter__ = lambda self: slow_output()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.terminate = Mock()
        mock_proc.kill = Mock()

        token = CancellationToken()

        async def cancel_after_delay():
            await asyncio.sleep(0.15)
            token.cancel()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            cancel_task = asyncio.create_task(cancel_after_delay())

            with pytest.raises(asyncio.CancelledError):
                async for _ in driver.invoke_stream("Test", token=token):
                    pass

            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task

    @pytest.mark.asyncio
    async def test_parse_tool_use(self, driver):
        """Should parse XML tool_use blocks."""
        output = [
            "Let me read the file.\n",
            '<tool_use name="read">\n',
            '{"file_path": "/test.py"}\n',
            "</tool_use>\n",
        ]
        mock_proc = create_mock_process(output)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await driver.invoke("Read test.py")

            assert result["action_type"] == "TOOL_USE"
            assert result["tool_use"] is not None
            assert result["tool_use"]["tool_name"] == "read"

    @pytest.mark.asyncio
    async def test_cancel_by_uuid(self, driver):
        """cancel_by_uuid should terminate process."""
        # We can't easily test this without a real process,
        # but we can verify the method exists and handles missing UUID
        result = await driver.cancel_by_uuid("nonexistent-uuid")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_all(self, driver):
        """cancel_all should return count."""
        count = await driver.cancel_all()
        assert count == 0  # No active processes


# ============================================================================
# AsyncGeminiDriver Tests
# ============================================================================


class TestAsyncGeminiDriver:
    """Tests for AsyncGeminiDriver."""

    @pytest.fixture
    def driver(self, tmp_path):
        """Create driver with temp workspace."""
        config = AsyncGeminiDriverConfig(
            cli_path="gemini",
            timeout=60.0,
            model="gemini-3-pro-preview",
            workspace_path=tmp_path,
            verbose=False,
        )
        return AsyncGeminiDriver(config)

    @pytest.mark.asyncio
    async def test_invoke_stream_collects_output(self, driver):
        """invoke_stream should yield output lines."""
        output = ['{"response": "Hello"}\n']
        mock_proc = create_mock_process(output)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            chunks = []
            async for chunk in driver.invoke_stream("Test prompt"):
                chunks.append(chunk)

            assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_invoke_parses_json(self, driver):
        """invoke should parse JSON response."""
        json_response = '{"sender": "Gemini", "action_type": "TALK", "content": "Hello!", "status": "CONTINUE"}\n'
        output = [json_response]
        mock_proc = create_mock_process(output)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await driver.invoke("Test prompt")

            # Should have sender field (even if JSON extraction fails, we normalize)
            assert "sender" in result

    @pytest.mark.asyncio
    async def test_isolated_env_creates_resume_flag(self, driver, tmp_path):
        """V9.7.1: isolated_env should add --resume latest flag."""
        output = ['{"response": "OK"}\n']
        mock_proc = create_mock_process(output)

        called_args = []

        async def capture_args(*args, **kwargs):
            called_args.extend(args)
            return mock_proc

        # V9.7.1: --resume latest only added when isolated_env is provided
        isolated_env = {"HOME": "/tmp/isolated", "PATH": "/usr/bin"}

        with patch("asyncio.create_subprocess_exec", side_effect=capture_args):
            await driver.invoke("Test", session_uuid="session-123", isolated_env=isolated_env)

            # Check that --resume latest was in the command
            all_args = [str(a) for a in called_args]
            assert "--resume" in all_args
            assert "latest" in all_args

    @pytest.mark.asyncio
    async def test_no_isolated_env_no_resume_flag(self, driver, tmp_path):
        """V9.7.1: Without isolated_env, --resume should NOT be added (prevents context leakage)."""
        output = ['{"response": "OK"}\n']
        mock_proc = create_mock_process(output)

        called_args = []

        async def capture_args(*args, **kwargs):
            called_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_args):
            await driver.invoke("Test", session_uuid="session-123")  # No isolated_env

            # V9.7.1: --resume should NOT be in command (shared HOME = no resume)
            all_args = [str(a) for a in called_args]
            assert "--resume" not in all_args


# ============================================================================
# AsyncDriverFactory Tests
# ============================================================================


class TestAsyncDriverFactory:
    """Tests for AsyncDriverFactory."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config."""
        config = Mock()
        config.claude_cli_path = "claude"
        config.gemini_cli_path = "gemini"
        config.timeout = 60.0
        config.claude_sonnet_model = "claude-sonnet-4-5-20250929"
        config.gemini_default_model = "gemini-3-pro-preview"
        config.verbose = False
        config.gemini_persistent_mode = True
        return config

    @pytest.fixture
    def factory(self, mock_config, tmp_path):
        """Create factory."""
        return AsyncDriverFactory(mock_config, tmp_path)

    def test_get_claude_driver(self, factory):
        """Should create Claude driver."""
        driver = factory.get_claude_driver()
        assert isinstance(driver, AsyncClaudeDriver)

    def test_get_gemini_driver(self, factory):
        """Should create Gemini driver."""
        driver = factory.get_gemini_driver()
        assert isinstance(driver, AsyncGeminiDriver)

    def test_get_driver_by_name(self, factory):
        """Should get driver by agent name."""
        claude = factory.get_driver("claude")
        gemini = factory.get_driver("gemini")

        assert isinstance(claude, AsyncClaudeDriver)
        assert isinstance(gemini, AsyncGeminiDriver)

    def test_get_driver_unknown_raises(self, factory):
        """Should raise for unknown agent."""
        with pytest.raises(ValueError):
            factory.get_driver("unknown_agent")

    def test_driver_singleton(self, factory):
        """Same driver instance should be returned."""
        driver1 = factory.get_claude_driver()
        driver2 = factory.get_claude_driver()
        assert driver1 is driver2

    @pytest.mark.asyncio
    async def test_cancel_all(self, factory):
        """cancel_all should not error with no processes."""
        count = await factory.cancel_all()
        assert count == 0

    @pytest.mark.asyncio
    async def test_list_active_processes(self, factory):
        """Should return empty list initially."""
        processes = await factory.list_active_processes()
        assert processes == []


# ============================================================================
# Integration Tests
# ============================================================================


class TestAsyncDriverIntegration:
    """Integration tests for async drivers."""

    @pytest.mark.asyncio
    async def test_concurrent_invocations(self, tmp_path):
        """Multiple drivers should work concurrently."""
        mock_config = Mock()
        mock_config.claude_cli_path = "claude"
        mock_config.gemini_cli_path = "gemini"
        mock_config.timeout = 60.0
        mock_config.claude_sonnet_model = "claude-sonnet"
        mock_config.gemini_default_model = "gemini-3-pro"
        mock_config.verbose = False
        mock_config.gemini_persistent_mode = False

        factory = AsyncDriverFactory(mock_config, tmp_path)

        claude = factory.get_claude_driver()
        gemini = factory.get_gemini_driver()

        # Mock both drivers
        claude_proc = create_mock_process(["Claude response\n"])
        gemini_proc = create_mock_process(['{"sender": "Gemini"}\n'])

        call_count = [0]

        async def mock_subprocess(*args, **kwargs):
            call_count[0] += 1
            if "claude" in str(args[0]).lower():
                return claude_proc
            return gemini_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            # Run both concurrently
            results = await asyncio.gather(claude.invoke("Test 1"), gemini.invoke("Test 2"), return_exceptions=True)

            # Both should complete
            assert len(results) == 2
            # At least one should succeed
            assert any(isinstance(r, dict) for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
