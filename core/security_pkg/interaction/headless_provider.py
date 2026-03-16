"""
HeadlessProvider - Non-blocking Interaction Provider for Servers.

NEXUS V9.8 DETOX - Headless Refactoring
NEXUS V10 CEREBRO - Redis Event Publishing
NEXUS V11.5 CORTEX - Interactive Mode (Human-in-the-Loop)

This provider never blocks (by default):
- Always returns defaults immediately
- Logs all prompts for audit trail
- Publishes events to Redis for external UI observation (V10)
- Raises InteractionRequiredError for critical questions without defaults

V11.5 CORTEX Interactive Mode:
- When interactive=True, waits for external response via resolve_interaction()
- Pending interactions are tracked for F5 recovery (snapshot)
- Default timeout: 5 minutes

Use cases:
- Web API server
- Background daemon
- CI/CD pipelines
- Automated testing
- External UI observation via CEREBRO API (V10)
- Human-in-the-loop via CORTEX API (V11.5)

Author: Claude (NEXUS DETOX)
Date: 2025-12-13
V10: 2025-12-15 (CEREBRO integration)
V11.5: 2025-12-15 (CORTEX interactive mode)
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .base import Choice, InteractionLevel, InteractionProvider, InteractionRequiredError

logger = logging.getLogger("nexus.interaction.headless")


class HeadlessProvider(InteractionProvider):
    """
    Non-blocking provider for server/daemon mode.

    This provider:
    - Never calls input() or any blocking I/O
    - Always returns default values immediately
    - Logs all prompts and responses for audit
    - Publishes events to Redis for external observation (V10 CEREBRO)
    - Can operate in strict mode (raise on missing defaults)

    V11.5 CORTEX Interactive Mode:
    - When interactive=True, waits for external API response
    - Pending interactions tracked in _pending_interactions for snapshot
    - Use resolve_interaction() to respond from external API
    - Timeout after interaction_timeout seconds (default 5 min)

    Usage:
        # Lenient mode (default) - returns empty/False for missing defaults
        provider = HeadlessProvider(strict=False)

        # Strict mode - raises InteractionRequiredError for missing defaults
        provider = HeadlessProvider(strict=True)

        # With custom logger
        provider = HeadlessProvider(logger_name="myapp.interaction")

        # Disable Redis publishing (V10)
        provider = HeadlessProvider(publish_events=False)

        # Interactive mode for CORTEX UI (V11.5)
        provider = HeadlessProvider(interactive=True)
    """

    def __init__(
        self,
        strict: bool = False,
        logger_name: str | None = None,
        publish_events: bool = True,
        interactive: bool = False,
        interaction_timeout: float = 300.0,
    ):
        """
        Initialize headless provider.

        Args:
            strict: If True, raise error when required input has no default
            logger_name: Custom logger name (default: nexus.interaction.headless)
            publish_events: If True, publish events to Redis (V10 CEREBRO)
            interactive: If True, wait for external response via resolve_interaction() (V11.5)
            interaction_timeout: Timeout in seconds for interactive mode (default 5 min)
        """
        self.strict = strict
        self._logger = logging.getLogger(logger_name) if logger_name else logger
        self._publish_events = publish_events
        self._interactive = interactive
        self._interaction_timeout = interaction_timeout
        self._pending_futures: dict[str, asyncio.Future] = {}
        self._pending_interactions: dict[str, dict] = {}

    async def _publish_event(self, event_type_name: str, payload: dict[str, Any]) -> None:
        """
        Publish interaction event to Redis (fire-and-forget).

        V10 CEREBRO: Enables external UI observation of NEXUS interactions.
        Never blocks, silently ignores errors.

        Args:
            event_type_name: Event type value (e.g., "interaction.ask")
            payload: Event payload data
        """
        if not self._publish_events:
            return

        try:
            # Lazy import to avoid circular dependencies
            from core.observability.events.redis_bus import get_redis_bus
            from core.observability.events.types import CerebroEvent, CerebroEventType

            # Get current tenant context
            try:
                from core.infrastructure.context import get_current_session_or_none

                ctx = get_current_session_or_none()
                if ctx:
                    tenant_id = ctx.tenant_id
                    workspace_id = ctx.workspace_id
                else:
                    tenant_id = "anonymous"
                    workspace_id = "default"
            except ImportError:
                tenant_id = "anonymous"
                workspace_id = "default"

            # Create and publish event
            event = CerebroEvent(
                event_type=CerebroEventType(event_type_name),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                payload=payload,
            )

            bus = get_redis_bus()
            await bus.publish(event)

        except Exception:
            # Fire-and-forget: never block, never raise
            pass

    # =========================================================================
    # V11.5 CORTEX - Interactive Mode Methods
    # =========================================================================

    def get_pending_requests(self) -> list[dict]:
        """
        Return list of pending interaction metadata for snapshot.

        V11.5 CORTEX: Used by /api/state/snapshot to include pending
        interactions in F5 recovery data.

        Returns:
            List of pending interaction dicts with request_id, type, prompt, timestamp
        """
        return list(self._pending_interactions.values())

    def resolve_interaction(self, request_id: str, response: Any) -> bool:
        """
        Resolve a pending interaction from external API.

        V11.5 CORTEX: Called by /api/interactions/{request_id}/reply
        to provide user response to waiting Future.

        Args:
            request_id: The request ID from the interaction event
            response: The user's response (str for ask, bool for confirm, str for choose)

        Returns:
            True if resolved, False if request_id not found or already resolved
        """
        future = self._pending_futures.get(request_id)
        if future and not future.done():
            future.set_result(response)
            self._pending_futures.pop(request_id, None)
            self._pending_interactions.pop(request_id, None)
            self._logger.info(f"[CORTEX] Resolved interaction {request_id}")
            return True
        self._logger.warning(f"[CORTEX] Interaction {request_id} not found or expired")
        return False

    async def _wait_for_response(
        self, request_id: str, interaction_type: str, prompt: str, default: Any, extra_data: dict | None = None
    ) -> Any:
        """
        Wait for external response in interactive mode.

        Args:
            request_id: Unique request ID
            interaction_type: Type of interaction (ask, confirm, choose)
            prompt: The prompt text
            default: Default value if timeout
            extra_data: Additional data (e.g., choices)

        Returns:
            User response or default on timeout
        """
        future: asyncio.Future = asyncio.Future()
        self._pending_futures[request_id] = future
        self._pending_interactions[request_id] = {
            "request_id": request_id,
            "type": interaction_type,
            "prompt": prompt,
            "default": default,
            "timestamp": datetime.now(UTC).isoformat(),
            **(extra_data or {}),
        }

        try:
            result = await asyncio.wait_for(future, timeout=self._interaction_timeout)
            return result
        except TimeoutError:
            self._logger.warning(f"[CORTEX] Timeout for {request_id} after {self._interaction_timeout}s")
            return default
        finally:
            self._pending_futures.pop(request_id, None)
            self._pending_interactions.pop(request_id, None)

    # =========================================================================
    # Interaction Methods
    # =========================================================================

    async def ask(
        self, prompt: str, default: str | None = None, timeout: float | None = None, required: bool = False
    ) -> str:
        """Return default immediately, or wait for response in interactive mode."""
        request_id = str(uuid4())[:8]
        self._logger.info(f"[HEADLESS] Prompt: {prompt} (req={request_id})")

        # V10 CEREBRO: Publish event with request_id for interactive mode
        await self._publish_event(
            "interaction.ask",
            {
                "prompt": prompt,
                "default": default,
                "required": required,
                "request_id": request_id,
            },
        )

        # V11.5 CORTEX: Interactive mode - wait for external response
        if self._interactive:
            result = await self._wait_for_response(
                request_id=request_id, interaction_type="ask", prompt=prompt, default=default or ""
            )
            return str(result) if result is not None else ""

        # Non-interactive: return default (legacy behavior)
        if default is not None:
            self._logger.info(f"[HEADLESS] Using default: {default}")
            return default

        if required or self.strict:
            self._logger.warning(f"[HEADLESS] Required input has no default: {prompt}")
            raise InteractionRequiredError(prompt=prompt, context="Headless mode cannot provide user input")

        self._logger.debug("[HEADLESS] No default, returning empty string")
        return ""

    async def confirm(self, prompt: str, default: bool = False, timeout: float | None = None) -> bool:
        """Return default confirmation immediately, or wait in interactive mode."""
        request_id = str(uuid4())[:8]
        self._logger.info(f"[HEADLESS] Confirm: {prompt} -> {default} (req={request_id})")

        # V10 CEREBRO: Publish event with request_id
        await self._publish_event(
            "interaction.confirm",
            {
                "prompt": prompt,
                "default": default,
                "request_id": request_id,
            },
        )

        # V11.5 CORTEX: Interactive mode - wait for external response
        if self._interactive:
            result = await self._wait_for_response(
                request_id=request_id, interaction_type="confirm", prompt=prompt, default=default
            )
            return bool(result) if result is not None else default

        return default

    async def choose(
        self, prompt: str, choices: list[Choice], default: str | None = None, timeout: float | None = None
    ) -> str:
        """Return default choice immediately, or wait in interactive mode."""
        request_id = str(uuid4())[:8]
        self._logger.info(f"[HEADLESS] Choice: {prompt} (req={request_id})")
        self._logger.debug(f"[HEADLESS] Options: {[c.key for c in choices]}")

        choice_keys = [c.key for c in choices]

        # V10 CEREBRO: Publish event with request_id
        await self._publish_event(
            "interaction.choose",
            {
                "prompt": prompt,
                "choices": choice_keys,
                "default": default,
                "request_id": request_id,
            },
        )

        # V11.5 CORTEX: Interactive mode - wait for external response
        if self._interactive:
            fallback = default if default else (choice_keys[0] if choice_keys else None)
            result = await self._wait_for_response(
                request_id=request_id,
                interaction_type="choose",
                prompt=prompt,
                default=fallback,
                extra_data={"choices": choice_keys},
            )
            # Validate response is a valid choice
            if result in choice_keys:
                return str(result)
            self._logger.warning(f"[CORTEX] Invalid choice '{result}', using fallback")
            return fallback or ""

        # Non-interactive: return default (legacy behavior)
        if default is not None and any(c.key == default for c in choices):
            self._logger.info(f"[HEADLESS] Using default choice: {default}")
            return default

        # No valid default - use first choice or raise
        if choices:
            first_key = choices[0].key
            if self.strict and default is None:
                raise InteractionRequiredError(prompt=prompt, context=f"Choice required, options: {choice_keys}")
            self._logger.info(f"[HEADLESS] Using first choice: {first_key}")
            return first_key

        raise InteractionRequiredError(prompt=prompt, context="No choices available")

    async def announce(self, message: str, level: InteractionLevel = InteractionLevel.INFO) -> None:
        """Log announcement instead of printing."""
        log_method = {
            InteractionLevel.DEBUG: self._logger.debug,
            InteractionLevel.INFO: self._logger.info,
            InteractionLevel.WARNING: self._logger.warning,
            InteractionLevel.ERROR: self._logger.error,
            InteractionLevel.CRITICAL: self._logger.critical,
        }.get(level, self._logger.info)

        log_method(f"[ANNOUNCE] {message}")

        # V10 CEREBRO: Publish event
        await self._publish_event(
            "interaction.announce",
            {
                "message": message,
                "level": level.value if hasattr(level, "value") else str(level),
            },
        )

    async def progress(self, message: str, current: int, total: int) -> None:
        """Log progress at intervals (every 10% or completion)."""
        if total <= 0:
            return

        pct = current / total * 100

        # Log at 0%, every 25%, and 100%
        should_log = current == 0 or current >= total or (current % max(1, total // 4)) == 0

        if should_log:
            self._logger.debug(f"[PROGRESS] {pct:.0f}% ({current}/{total}) - {message}")

            # V10 CEREBRO: Publish event (only at log intervals to reduce noise)
            await self._publish_event(
                "interaction.progress",
                {
                    "message": message,
                    "current": current,
                    "total": total,
                    "percent": round(pct, 1),
                },
            )

    @property
    def is_interactive(self) -> bool:
        """Headless provider is not interactive."""
        return False
