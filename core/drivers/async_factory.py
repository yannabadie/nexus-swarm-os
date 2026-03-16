"""
Async Driver Factory - Create and Manage Async Drivers.

NEXUS V12.4 COGNITIVE BOOST - SDK-First Architecture

Provides a unified interface for creating and managing drivers:
- CLI drivers (AsyncClaudeDriver, AsyncGeminiDriver) - subprocess-based
- SDK drivers (AnthropicSDKDriver, GoogleGenAISDKDriver) - API-first

Driver selection:
- driver_mode="auto" (default): SDK when API key available, else CLI
- driver_mode="sdk": SDK only (fails if no API key)
- driver_mode="cli": CLI only (original behavior)

Usage:
    factory = AsyncDriverFactory(config, workspace_path)

    # CLI drivers (backward compatible)
    claude_cli = factory.get_claude_driver()
    gemini_cli = factory.get_gemini_driver()

    # SDK drivers (V12.4)
    claude_sdk = factory.get_claude_sdk()
    gemini_sdk = factory.get_gemini_sdk()

    # Smart routing (respects driver_mode config)
    driver = factory.get_driver("claude")

    # Cancel all processes
    await factory.cancel_all()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.foundation.async_primitives.process_handle import get_process_registry
from core.infrastructure.resilience.circuit_breaker import get_hierarchical_breaker
from core.observability.telemetry.budget_tracker import get_budget_tracker
from core.provider_registry import get_default_model

from .async_claude_driver import AsyncClaudeDriver, AsyncClaudeDriverConfig
from .async_gemini_driver import AsyncGeminiDriver, AsyncGeminiDriverConfig
from .driver_health_monitor import get_health_monitor
from .failover_manager import get_failover_manager
from .response_cache import ResponseCache

if TYPE_CHECKING:
    from .anthropic_sdk_driver import AnthropicSDKDriver
    from .deepseek_sdk_driver import DeepSeekSDKDriver
    from .google_genai_sdk_driver import GoogleGenAISDKDriver
    from .kimi_sdk_driver import KimiSDKDriver
    from .minimax_sdk_driver import MiniMaxSDKDriver
    from .openai_sdk_driver import OpenAISDKDriver

logger = logging.getLogger(__name__)


class AsyncDriverFactory:
    """
    Factory for creating and managing async drivers.

    V12.4: Supports both CLI (subprocess) and SDK (API) drivers.
    Singleton pattern ensures only one driver per type exists.
    """

    def __init__(self, config: Any, workspace_path: Path | None = None):
        """
        Initialize factory.

        Args:
            config: NEXUS config object (or mock with required attributes)
            workspace_path: Workspace path for file I/O (defaults to config.workspace_path or "./workspace")
        """
        self.config = config
        if workspace_path is None:
            workspace_path = getattr(config, "workspace_path", Path("./workspace"))
        self.workspace_path = Path(workspace_path)
        self._registry = get_process_registry()

        # Driver mode: "auto", "sdk", "cli"
        self._driver_mode: str = getattr(config, "driver_mode", "auto")

        # API keys for SDK drivers
        self._anthropic_api_key: str | None = getattr(config, "anthropic_api_key", None)
        self._google_api_key: str | None = getattr(config, "google_api_key", None)
        self._deepseek_api_key: str | None = getattr(config, "deepseek_api_key", None)
        self._kimi_api_key: str | None = getattr(config, "kimi_api_key", None)
        self._openai_api_key: str | None = getattr(config, "openai_api_key", None)
        self._minimax_api_key: str | None = getattr(config, "minimax_api_key", None)

        # Shared response cache for SDK drivers (deduplication)
        self._response_cache = ResponseCache(
            max_size=getattr(config, "response_cache_size", 500),
            ttl_seconds=getattr(config, "response_cache_ttl", 300.0),
            enabled=self._driver_mode != "cli",
        )

        # Shared budget tracker for automatic cost tracking
        self._budget_tracker = get_budget_tracker(config, Path(workspace_path))

        # Shared health monitor, failover manager, and circuit breaker
        self._health_monitor = get_health_monitor()
        self._failover = get_failover_manager()
        self._circuit_breaker = get_hierarchical_breaker()

        # Lazy-initialized CLI drivers
        self._claude_driver: AsyncClaudeDriver | None = None
        self._gemini_driver: AsyncGeminiDriver | None = None

        # Lazy-initialized SDK drivers (V12.4)
        self._claude_sdk: AnthropicSDKDriver | None = None
        self._gemini_sdk: GoogleGenAISDKDriver | None = None
        self._deepseek_sdk: DeepSeekSDKDriver | None = None
        self._kimi_sdk: KimiSDKDriver | None = None
        self._openai_sdk: OpenAISDKDriver | None = None
        self._minimax_sdk: MiniMaxSDKDriver | None = None

    # =========================================================================
    # CLI Drivers (backward compatible)
    # =========================================================================

    def get_claude_driver(self, model: str | None = None) -> AsyncClaudeDriver:
        """
        Get or create the Claude CLI driver.

        Args:
            model: Optional model override (uses config default if None)

        Returns:
            AsyncClaudeDriver instance
        """
        if self._claude_driver is None:
            config = AsyncClaudeDriverConfig(
                cli_path=getattr(self.config, "claude_cli_path", "claude"),
                timeout=getattr(self.config, "timeout", 300.0),
                model=model or getattr(self.config, "claude_sonnet_model", get_default_model("anthropic", "sonnet")),
                workspace_path=self.workspace_path,
                verbose=getattr(self.config, "verbose", False),
            )
            self._claude_driver = AsyncClaudeDriver(config)
        elif model:
            self._claude_driver.config.model = model

        return self._claude_driver

    def get_gemini_driver(self, model: str | None = None) -> AsyncGeminiDriver:
        """
        Get or create the Gemini CLI driver.

        Args:
            model: Optional model override (uses config default if None)

        Returns:
            AsyncGeminiDriver instance
        """
        if self._gemini_driver is None:
            config = AsyncGeminiDriverConfig(
                cli_path=getattr(self.config, "gemini_cli_path", "gemini"),
                timeout=getattr(self.config, "timeout", 300.0),
                model=model or getattr(self.config, "gemini_default_model", get_default_model("google", "pro")),
                workspace_path=self.workspace_path,
                verbose=getattr(self.config, "verbose", False),
                use_session_resume=getattr(self.config, "gemini_persistent_mode", True),
            )
            self._gemini_driver = AsyncGeminiDriver(config)
        elif model:
            self._gemini_driver.config.model = model

        return self._gemini_driver

    # =========================================================================
    # SDK Drivers (V12.4 API-First)
    # =========================================================================

    def get_claude_sdk(
        self,
        model: str | None = None,
    ) -> AnthropicSDKDriver:
        """
        Get or create the Claude SDK driver (API-first).

        Args:
            model: Optional model override

        Returns:
            AnthropicSDKDriver instance

        Raises:
            RuntimeError: If no ANTHROPIC_API_KEY is configured
        """
        if self._claude_sdk is None:
            if not self._anthropic_api_key:
                raise RuntimeError("AnthropicSDKDriver requires ANTHROPIC_API_KEY. Set it in .env or environment.")
            from .anthropic_sdk_driver import AnthropicSDKDriver

            self._claude_sdk = AnthropicSDKDriver(
                model=model or getattr(self.config, "claude_sonnet_model", get_default_model("anthropic", "sonnet")),
                api_key=self._anthropic_api_key,
                max_tokens=getattr(self.config, "max_tokens", 8192),
                timeout=float(getattr(self.config, "timeout", 300)),
                enable_caching=True,
                response_cache=self._response_cache,
            )
            self._claude_sdk._budget_tracker = self._budget_tracker
            self._claude_sdk._health_monitor = self._health_monitor
            sdk_model = getattr(self._claude_sdk, "_model", "unknown")
            self._failover.register_driver(f"claude/{sdk_model}", priority=0)
            logger.info(f"Created AnthropicSDKDriver (model={sdk_model})")
        elif model and hasattr(self._claude_sdk, "_model"):
            self._claude_sdk._model = model

        return self._claude_sdk

    def get_gemini_sdk(
        self,
        model: str | None = None,
    ) -> GoogleGenAISDKDriver:
        """
        Get or create the Gemini SDK driver (API-first).

        Args:
            model: Optional model override

        Returns:
            GoogleGenAISDKDriver instance

        Raises:
            RuntimeError: If no GOOGLE_API_KEY is configured
        """
        if self._gemini_sdk is None:
            if not self._google_api_key:
                raise RuntimeError(
                    "GoogleGenAISDKDriver requires GOOGLE_API_KEY or GEMINI_API_KEY. Set it in .env or environment."
                )
            from .google_genai_sdk_driver import GoogleGenAISDKDriver

            self._gemini_sdk = GoogleGenAISDKDriver(
                model=model or getattr(self.config, "gemini_default_model", get_default_model("google", "pro")),
                api_key=self._google_api_key,
                timeout=float(getattr(self.config, "timeout", 300)),
                response_cache=self._response_cache,
            )
            self._gemini_sdk._budget_tracker = self._budget_tracker
            self._gemini_sdk._health_monitor = self._health_monitor
            sdk_model = getattr(self._gemini_sdk, "_model", "unknown")
            self._failover.register_driver(f"gemini/{sdk_model}", priority=1)
            logger.info(f"Created GoogleGenAISDKDriver (model={sdk_model})")
        elif model and hasattr(self._gemini_sdk, "_model"):
            self._gemini_sdk._model = model

        return self._gemini_sdk

    def get_deepseek_sdk(
        self,
        model: str | None = None,
    ) -> DeepSeekSDKDriver:
        """
        Get or create the DeepSeek SDK driver (cost-effective alternative).

        DeepSeek provides 95% cost savings vs Anthropic/Gemini with
        OpenAI-compatible API and 5M free tokens for new users.

        Args:
            model: Optional model override (default: "deepseek-chat")
                   Aliases: "chat" (V3.2), "reasoner" (R1), "default"

        Returns:
            DeepSeekSDKDriver instance

        Raises:
            RuntimeError: If no DEEPSEEK_API_KEY is configured
        """
        if self._deepseek_sdk is None:
            if not self._deepseek_api_key:
                raise RuntimeError(
                    "DeepSeekSDKDriver requires DEEPSEEK_API_KEY. "
                    "Set it in .env or environment.\n"
                    "Get your free API key with 5M tokens at: https://platform.deepseek.com/"
                )
            from .deepseek_sdk_driver import DeepSeekSDKDriver

            self._deepseek_sdk = DeepSeekSDKDriver(
                model=model or getattr(self.config, "deepseek_model", "deepseek-chat"),
                api_key=self._deepseek_api_key,
                max_tokens=getattr(self.config, "max_tokens", 8192),
                timeout=float(getattr(self.config, "timeout", 300)),
                enable_caching=True,
                response_cache=self._response_cache,
            )
            self._deepseek_sdk.set_budget_tracker(self._budget_tracker)
            self._deepseek_sdk.set_health_monitor(self._health_monitor)
            sdk_model = getattr(self._deepseek_sdk, "_model", "unknown")
            self._failover.register_driver(f"deepseek/{sdk_model}", priority=2)
            logger.info(f"Created DeepSeekSDKDriver (model={sdk_model})")
        elif model and hasattr(self._deepseek_sdk, "_model"):
            self._deepseek_sdk._model = model

        return self._deepseek_sdk

    def get_kimi_sdk(
        self,
        model: str | None = None,
    ) -> KimiSDKDriver:
        """
        Get or create the Kimi SDK driver (Moonshot AI K2.5).

        Kimi K2.5 is a multimodal frontier model with agent swarm capabilities,
        vision, and tool calling. Released January 2026.

        Args:
            model: Optional model override (default: "kimi-k2.5")
                   Aliases: "k2.5" (latest), "k2", "latest", "default"

        Returns:
            KimiSDKDriver instance

        Raises:
            RuntimeError: If no KIMI_API_KEY is configured
        """
        if self._kimi_sdk is None:
            if not self._kimi_api_key:
                raise RuntimeError(
                    "KimiSDKDriver requires KIMI_API_KEY. "
                    "Set it in .env or environment.\n"
                    "Get your API key at: https://platform.moonshot.ai/"
                )
            from .kimi_sdk_driver import KimiSDKDriver

            self._kimi_sdk = KimiSDKDriver(
                model=model or getattr(self.config, "kimi_model", "kimi-k2.5"),
                api_key=self._kimi_api_key,
                max_tokens=getattr(self.config, "max_tokens", 8192),
                timeout=float(getattr(self.config, "timeout", 300)),
                enable_caching=True,
                response_cache=self._response_cache,
            )
            self._kimi_sdk.set_budget_tracker(self._budget_tracker)
            self._kimi_sdk.set_health_monitor(self._health_monitor)
            sdk_model = getattr(self._kimi_sdk, "_model", "unknown")
            self._failover.register_driver(f"kimi/{sdk_model}", priority=2)
            logger.info(f"Created KimiSDKDriver (model={sdk_model})")
        elif model and hasattr(self._kimi_sdk, "_model"):
            self._kimi_sdk._model = model

        return self._kimi_sdk

    def get_openai_sdk(
        self,
        model: str | None = None,
    ) -> OpenAISDKDriver:
        """Get or create the OpenAI SDK driver."""
        if self._openai_sdk is None:
            if not self._openai_api_key:
                raise RuntimeError("OpenAISDKDriver requires OPENAI_API_KEY. Set it in .env or environment.")
            from .openai_sdk_driver import OpenAISDKDriver

            self._openai_sdk = OpenAISDKDriver(
                model=model or getattr(self.config, "openai_model", "gpt-5.4"),
                api_key=self._openai_api_key,
                max_tokens=getattr(self.config, "max_tokens", 8192),
                timeout=float(getattr(self.config, "timeout", 300)),
                enable_caching=True,
                response_cache=self._response_cache,
            )
            self._openai_sdk.set_budget_tracker(self._budget_tracker)
            self._openai_sdk.set_health_monitor(self._health_monitor)
            sdk_model = getattr(self._openai_sdk, "_model", "unknown")
            self._failover.register_driver(f"openai/{sdk_model}", priority=2)
            logger.info(f"Created OpenAISDKDriver (model={sdk_model})")
        elif model and hasattr(self._openai_sdk, "_model"):
            self._openai_sdk._model = model

        return self._openai_sdk

    def get_minimax_sdk(
        self,
        model: str | None = None,
    ) -> MiniMaxSDKDriver:
        """Get or create the MiniMax SDK driver."""
        if self._minimax_sdk is None:
            if not self._minimax_api_key:
                raise RuntimeError("MiniMaxSDKDriver requires MINIMAX_API_KEY. Set it in .env or environment.")
            from .minimax_sdk_driver import MiniMaxSDKDriver

            self._minimax_sdk = MiniMaxSDKDriver(
                model=model or getattr(self.config, "minimax_model", "MiniMax-M2.5"),
                api_key=self._minimax_api_key,
                max_tokens=getattr(self.config, "max_tokens", 8192),
                timeout=float(getattr(self.config, "timeout", 300)),
                enable_caching=True,
                response_cache=self._response_cache,
            )
            self._minimax_sdk.set_budget_tracker(self._budget_tracker)
            self._minimax_sdk.set_health_monitor(self._health_monitor)
            sdk_model = getattr(self._minimax_sdk, "_model", "unknown")
            self._failover.register_driver(f"minimax/{sdk_model}", priority=2)
            logger.info(f"Created MiniMaxSDKDriver (model={sdk_model})")
        elif model and hasattr(self._minimax_sdk, "_model"):
            self._minimax_sdk._model = model

        return self._minimax_sdk

    # =========================================================================
    # Smart Driver Selection (V12.4)
    # =========================================================================

    @property
    def claude_sdk_available(self) -> bool:
        """Check if Claude SDK driver can be created (API key present)."""
        return bool(self._anthropic_api_key) and self._driver_mode != "cli"

    @property
    def gemini_sdk_available(self) -> bool:
        """Check if Gemini SDK driver can be created (API key present)."""
        return bool(self._google_api_key) and self._driver_mode != "cli"

    @property
    def deepseek_sdk_available(self) -> bool:
        """Check if DeepSeek SDK driver can be created (API key present)."""
        return bool(self._deepseek_api_key) and self._driver_mode != "cli"

    @property
    def kimi_sdk_available(self) -> bool:
        """Check if Kimi SDK driver can be created (API key present)."""
        return bool(self._kimi_api_key) and self._driver_mode != "cli"

    @property
    def openai_sdk_available(self) -> bool:
        """Check if OpenAI SDK driver can be created (API key present)."""
        return bool(self._openai_api_key) and self._driver_mode != "cli"

    @property
    def minimax_sdk_available(self) -> bool:
        """Check if MiniMax SDK driver can be created (API key present)."""
        return bool(self._minimax_api_key) and self._driver_mode != "cli"

    def get_best_claude(self, model: str | None = None) -> Any:
        """
        Get the best available Claude driver based on driver_mode.

        Returns SDK driver if API key available and mode allows,
        otherwise falls back to CLI driver.
        Circuit breaker: if provider circuit is open, skip SDK entirely.
        """
        if self._driver_mode == "sdk":
            return self.get_claude_sdk(model)

        if self._driver_mode == "auto" and self._anthropic_api_key:
            # Skip SDK if circuit breaker is open for claude
            from core.infrastructure.resilience.circuit_breaker import CircuitState

            if self._circuit_breaker.get_provider_state("claude") == CircuitState.OPEN:
                logger.warning("Claude SDK circuit open, using CLI fallback")
                return self.get_claude_driver(model)
            try:
                return self.get_claude_sdk(model)
            except Exception as e:
                logger.warning(f"SDK driver failed, falling back to CLI: {e}")

        return self.get_claude_driver(model)

    def get_best_gemini(self, model: str | None = None) -> Any:
        """
        Get the best available Gemini driver based on driver_mode.

        Returns SDK driver if API key available and mode allows,
        otherwise falls back to CLI driver.
        Circuit breaker: if provider circuit is open, skip SDK entirely.
        """
        if self._driver_mode == "sdk":
            return self.get_gemini_sdk(model)

        if self._driver_mode == "auto" and self._google_api_key:
            # Skip SDK if circuit breaker is open for gemini
            from core.infrastructure.resilience.circuit_breaker import CircuitState

            if self._circuit_breaker.get_provider_state("gemini") == CircuitState.OPEN:
                logger.warning("Gemini SDK circuit open, using CLI fallback")
                return self.get_gemini_driver(model)
            try:
                return self.get_gemini_sdk(model)
            except Exception as e:
                logger.warning(f"SDK driver failed, falling back to CLI: {e}")

        return self.get_gemini_driver(model)

    def get_driver(
        self,
        agent_id: str,
        model: str | None = None,
        prefer_sdk: bool = False,
    ) -> Any:
        """
        Get a driver by agent/provider ID.

        Args:
            agent_id: "claude", "gemini", "deepseek", "deepeek", "kimi", "openai", or "minimax"
            model: Optional model override
            prefer_sdk: If True, use SDK driver when available (respects driver_mode)

        Returns:
            Appropriate driver (CLI or SDK based on config/preference)

        Raises:
            ValueError: If agent_id is unknown
        """
        agent_lower = agent_id.lower()

        if prefer_sdk or self._driver_mode == "sdk":
            if agent_lower == "claude":
                return self.get_best_claude(model)
            elif agent_lower == "gemini":
                return self.get_best_gemini(model)
            elif agent_lower in {"deepseek", "deepeek"}:
                return self.get_deepseek_sdk(model)
            elif agent_lower == "kimi":
                return self.get_kimi_sdk(model)
            elif agent_lower == "openai":
                return self.get_openai_sdk(model)
            elif agent_lower == "minimax":
                return self.get_minimax_sdk(model)
        else:
            if agent_lower == "claude":
                return self.get_claude_driver(model)
            elif agent_lower == "gemini":
                return self.get_gemini_driver(model)

        raise ValueError(
            f"Unknown agent/provider: {agent_id}. Use claude, gemini, deepseek/deepeek, kimi, openai, or minimax."
        )

    # =========================================================================
    # Driver Info (V12.4)
    # =========================================================================

    def get_driver_info(self) -> dict[str, Any]:
        """
        Get information about available drivers and their status.

        Returns:
            Dict with driver availability and mode info
        """
        return {
            "driver_mode": self._driver_mode,
            "claude_cli_available": True,  # Always available
            "claude_sdk_available": self.claude_sdk_available,
            "claude_sdk_active": self._claude_sdk is not None,
            "gemini_cli_available": True,
            "gemini_sdk_available": self.gemini_sdk_available,
            "gemini_sdk_active": self._gemini_sdk is not None,
            "deepseek_sdk_available": self.deepseek_sdk_available,
            "deepseek_sdk_active": self._deepseek_sdk is not None,
            "kimi_sdk_available": self.kimi_sdk_available,
            "kimi_sdk_active": self._kimi_sdk is not None,
            "openai_sdk_available": self.openai_sdk_available,
            "openai_sdk_active": self._openai_sdk is not None,
            "minimax_sdk_available": self.minimax_sdk_available,
            "minimax_sdk_active": self._minimax_sdk is not None,
            "anthropic_api_key_set": bool(self._anthropic_api_key),
            "google_api_key_set": bool(self._google_api_key),
            "deepseek_api_key_set": bool(self._deepseek_api_key),
            "kimi_api_key_set": bool(self._kimi_api_key),
            "openai_api_key_set": bool(self._openai_api_key),
            "minimax_api_key_set": bool(self._minimax_api_key),
            "response_cache": self._response_cache.to_dict(),
            "health_monitor": self._health_monitor.to_dict(),
            "failover": self._failover.to_dict(),
            "circuit_breaker": self._circuit_breaker.get_status(),
        }

    # =========================================================================
    # Process Management
    # =========================================================================

    async def cancel_by_uuid(self, session_uuid: str) -> bool:
        """Cancel a specific process by UUID across all drivers."""
        return await self._registry.cancel_by_uuid(session_uuid)

    async def cancel_by_task_id(self, task_id: str) -> int:
        """Cancel all processes for a task."""
        return await self._registry.cancel_by_task_id(task_id)

    async def cancel_all(self) -> int:
        """Cancel ALL active processes (for Ctrl+C handler)."""
        count = await self._registry.cancel_all()
        return count

    async def list_active_processes(self) -> list[dict[str, Any]]:
        """List all active processes across all drivers."""
        return await self._registry.list_active()

    @property
    def active_process_count(self) -> int:
        """Get count of all active processes."""
        count = 0
        if self._claude_driver:
            count += self._claude_driver.active_process_count
        if self._gemini_driver:
            count += self._gemini_driver.active_process_count
        return count


# Global factory instance for convenience
_global_factory: AsyncDriverFactory | None = None


def get_driver_factory() -> AsyncDriverFactory | None:
    """Get the global driver factory instance."""
    return _global_factory


def set_driver_factory(factory: AsyncDriverFactory) -> None:
    """Set the global driver factory instance."""
    global _global_factory
    _global_factory = factory


def create_driver_factory(config: Any, workspace_path: Path) -> AsyncDriverFactory:
    """
    Create and register a global driver factory.

    Args:
        config: NEXUS config object
        workspace_path: Workspace path for file I/O

    Returns:
        New factory instance
    """
    factory = AsyncDriverFactory(config, workspace_path)
    set_driver_factory(factory)
    return factory
