"""
Tests for V12.4 SDK Driver Factory Wiring.

Validates:
- Factory creates SDK drivers when API keys are available
- Factory falls back to CLI drivers when no API keys
- driver_mode config controls behavior ("auto", "sdk", "cli")
- get_best_claude/get_best_gemini smart selection
- get_driver_info reports correct status
- ModelRouter.route_for_sdk selects correct model
"""

from unittest.mock import Mock, patch

import pytest

from core.drivers.async_claude_driver import AsyncClaudeDriver
from core.drivers.async_factory import AsyncDriverFactory
from core.drivers.async_gemini_driver import AsyncGeminiDriver
from core.execution_pkg.routing.model_router import ModelRouter, TaskType

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def base_config():
    """Config with no API keys (CLI-only)."""
    config = Mock()
    config.claude_cli_path = "claude"
    config.gemini_cli_path = "gemini"
    config.timeout = 60.0
    config.claude_sonnet_model = "claude-sonnet-4-5-20250929"
    config.claude_opus_model = "claude-opus-4-6-20250116"
    config.gemini_default_model = "gemini-3-pro-preview"
    config.verbose = False
    config.gemini_persistent_mode = True
    config.driver_mode = "auto"
    config.anthropic_api_key = None
    config.google_api_key = None
    config.max_tokens = 8192
    return config


@pytest.fixture
def sdk_config(base_config):
    """Config with API keys (SDK available)."""
    base_config.anthropic_api_key = "sk-ant-test-key-1234"
    base_config.google_api_key = "AIzaSy-test-key-5678"
    return base_config


@pytest.fixture
def cli_only_config(base_config):
    """Config forced to CLI mode even with keys."""
    base_config.anthropic_api_key = "sk-ant-test-key-1234"
    base_config.google_api_key = "AIzaSy-test-key-5678"
    base_config.driver_mode = "cli"
    return base_config


@pytest.fixture
def sdk_only_config(base_config):
    """Config forced to SDK mode."""
    base_config.anthropic_api_key = "sk-ant-test-key-1234"
    base_config.google_api_key = "AIzaSy-test-key-5678"
    base_config.driver_mode = "sdk"
    return base_config


# =============================================================================
# Factory CLI Backward Compatibility
# =============================================================================


class TestFactoryCLICompat:
    """Verify CLI drivers still work unchanged."""

    def test_get_claude_cli_driver(self, base_config, tmp_path):
        """get_claude_driver() returns CLI driver."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        driver = factory.get_claude_driver()
        assert isinstance(driver, AsyncClaudeDriver)

    def test_get_gemini_cli_driver(self, base_config, tmp_path):
        """get_gemini_driver() returns CLI driver."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        driver = factory.get_gemini_driver()
        assert isinstance(driver, AsyncGeminiDriver)

    def test_cli_driver_singleton(self, base_config, tmp_path):
        """CLI driver instances are reused."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        d1 = factory.get_claude_driver()
        d2 = factory.get_claude_driver()
        assert d1 is d2

    def test_get_driver_by_name_cli(self, base_config, tmp_path):
        """get_driver() returns CLI drivers by default."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        claude = factory.get_driver("claude")
        gemini = factory.get_driver("gemini")
        assert isinstance(claude, AsyncClaudeDriver)
        assert isinstance(gemini, AsyncGeminiDriver)

    def test_get_driver_unknown_raises(self, base_config, tmp_path):
        """get_driver() raises ValueError for unknown agent."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        with pytest.raises(ValueError, match="Unknown agent"):
            factory.get_driver("gpt4")


# =============================================================================
# SDK Driver Creation
# =============================================================================


class TestSDKDriverCreation:
    """Test SDK driver instantiation via factory."""

    @patch("core.drivers.anthropic_sdk_driver.AnthropicSDKDriver.__init__", return_value=None)
    def test_get_claude_sdk(self, mock_init, sdk_config, tmp_path):
        """get_claude_sdk() creates AnthropicSDKDriver."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        factory.get_claude_sdk()
        mock_init.assert_called_once()
        # Verify API key was passed
        call_kwargs = mock_init.call_args
        assert call_kwargs[1]["api_key"] == "sk-ant-test-key-1234"

    @patch("core.drivers.google_genai_sdk_driver.GoogleGenAISDKDriver.__init__", return_value=None)
    def test_get_gemini_sdk(self, mock_init, sdk_config, tmp_path):
        """get_gemini_sdk() creates GoogleGenAISDKDriver."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        factory.get_gemini_sdk()
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args
        assert call_kwargs[1]["api_key"] == "AIzaSy-test-key-5678"

    def test_get_claude_sdk_no_key_raises(self, base_config, tmp_path):
        """get_claude_sdk() raises RuntimeError without API key."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            factory.get_claude_sdk()

    def test_get_gemini_sdk_no_key_raises(self, base_config, tmp_path):
        """get_gemini_sdk() raises RuntimeError without API key."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
            factory.get_gemini_sdk()

    @patch("core.drivers.anthropic_sdk_driver.AnthropicSDKDriver.__init__", return_value=None)
    def test_sdk_driver_singleton(self, mock_init, sdk_config, tmp_path):
        """SDK driver instances are reused."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        d1 = factory.get_claude_sdk()
        d2 = factory.get_claude_sdk()
        assert d1 is d2
        assert mock_init.call_count == 1  # Created only once


# =============================================================================
# Driver Mode Selection
# =============================================================================


class TestDriverModeSelection:
    """Test driver_mode config behavior."""

    def test_auto_mode_no_keys_returns_cli(self, base_config, tmp_path):
        """auto mode without API keys returns CLI driver."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        driver = factory.get_best_claude()
        assert isinstance(driver, AsyncClaudeDriver)

    @patch("core.drivers.anthropic_sdk_driver.AnthropicSDKDriver.__init__", return_value=None)
    def test_auto_mode_with_key_returns_sdk(self, mock_init, sdk_config, tmp_path):
        """auto mode with API key returns SDK driver."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        factory.get_best_claude()
        # Should be SDK driver (mock prevents actual instantiation)
        mock_init.assert_called_once()

    def test_cli_mode_ignores_keys(self, cli_only_config, tmp_path):
        """cli mode returns CLI driver even with API keys."""
        factory = AsyncDriverFactory(cli_only_config, tmp_path)
        driver = factory.get_best_claude()
        assert isinstance(driver, AsyncClaudeDriver)

    @patch("core.drivers.anthropic_sdk_driver.AnthropicSDKDriver.__init__", return_value=None)
    def test_sdk_mode_uses_sdk(self, mock_init, sdk_only_config, tmp_path):
        """sdk mode uses SDK driver."""
        factory = AsyncDriverFactory(sdk_only_config, tmp_path)
        factory.get_best_claude()
        mock_init.assert_called_once()

    def test_sdk_availability_flags(self, sdk_config, tmp_path):
        """SDK availability properties reflect config."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        assert factory.claude_sdk_available is True
        assert factory.gemini_sdk_available is True

    def test_sdk_unavailable_without_keys(self, base_config, tmp_path):
        """SDK unavailable without API keys."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        assert factory.claude_sdk_available is False
        assert factory.gemini_sdk_available is False

    def test_sdk_unavailable_in_cli_mode(self, cli_only_config, tmp_path):
        """SDK unavailable in CLI mode even with keys."""
        factory = AsyncDriverFactory(cli_only_config, tmp_path)
        assert factory.claude_sdk_available is False
        assert factory.gemini_sdk_available is False


# =============================================================================
# Driver Info
# =============================================================================


class TestDriverInfo:
    """Test get_driver_info() reporting."""

    def test_driver_info_no_keys(self, base_config, tmp_path):
        """Driver info shows no SDK available without keys."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        info = factory.get_driver_info()
        assert info["driver_mode"] == "auto"
        assert info["claude_sdk_available"] is False
        assert info["gemini_sdk_available"] is False
        assert info["anthropic_api_key_set"] is False
        assert info["google_api_key_set"] is False
        assert info["claude_cli_available"] is True

    def test_driver_info_with_keys(self, sdk_config, tmp_path):
        """Driver info shows SDK available with keys."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        info = factory.get_driver_info()
        assert info["claude_sdk_available"] is True
        assert info["gemini_sdk_available"] is True
        assert info["anthropic_api_key_set"] is True
        assert info["google_api_key_set"] is True

    @patch("core.drivers.anthropic_sdk_driver.AnthropicSDKDriver.__init__", return_value=None)
    def test_driver_info_sdk_active(self, mock_init, sdk_config, tmp_path):
        """Driver info tracks active SDK instances."""
        factory = AsyncDriverFactory(sdk_config, tmp_path)
        assert factory.get_driver_info()["claude_sdk_active"] is False
        factory.get_claude_sdk()
        assert factory.get_driver_info()["claude_sdk_active"] is True


# =============================================================================
# Model Router SDK Integration
# =============================================================================


class TestModelRouterSDK:
    """Test ModelRouter.route_for_sdk()."""

    def test_route_claude_brainstorm_to_opus(self):
        """Brainstorm tasks route to Opus for SDK."""
        router = ModelRouter()
        model = router.route_for_sdk("claude", TaskType.BRAINSTORM)
        assert model == "claude-opus-4-6"

    def test_route_claude_tool_to_sonnet(self):
        """Tool tasks route to Sonnet for SDK."""
        router = ModelRouter()
        model = router.route_for_sdk("claude", TaskType.TOOL)
        assert model == "claude-sonnet-4-6"

    def test_route_gemini_reasoning_to_pro(self):
        """Reasoning tasks route to Gemini Pro for SDK."""
        router = ModelRouter()
        model = router.route_for_sdk("gemini", TaskType.REASONING)
        assert model == "gemini-3.1-pro-preview"

    def test_route_unknown_agent_raises(self):
        """Unknown agent raises ValueError."""
        router = ModelRouter()
        with pytest.raises(ValueError, match="Unknown agent"):
            router.route_for_sdk("gpt4", TaskType.BRAINSTORM)


# =============================================================================
# Process Management (unchanged)
# =============================================================================


class TestProcessManagement:
    """Verify process management still works."""

    @pytest.mark.asyncio
    async def test_cancel_all_no_processes(self, base_config, tmp_path):
        """cancel_all returns 0 with no active processes."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        count = await factory.cancel_all()
        assert count == 0

    @pytest.mark.asyncio
    async def test_list_active_empty(self, base_config, tmp_path):
        """list_active_processes returns empty list initially."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        processes = await factory.list_active_processes()
        assert processes == []

    def test_active_process_count_zero(self, base_config, tmp_path):
        """Active process count is 0 initially."""
        factory = AsyncDriverFactory(base_config, tmp_path)
        assert factory.active_process_count == 0
