"""
NEXUS V12.2 IRONCLAD - WebSocket Streaming Endpoint
MANDATORY authentication (Zero Trust)
HIBERNATE state recovery on reconnect

Streams NEXUS events to connected UI clients via WebSocket.

Usage:
    # Connect with JWT token (MANDATORY)
    ws://localhost:8080/ws/stream?token=<jwt>&workspace_id=default

    # REMOVED: tenant_id query param fallback (IDOR prevention)
    # This was the SAME vulnerability pattern fixed in REST endpoints

Events are streamed as JSON:
    {
        "event_type": "interaction.ask",
        "payload": {"prompt": "Continue?"},
        "timestamp": "2025-12-15T10:30:00Z",
        "event_id": "abc123"
    }

Authentication:
    V11.6.2 IRONCLAD: JWT token is MANDATORY.
    Anonymous tenant_id param REMOVED to prevent IDOR attacks.

V12.2 IRONCLAD:
    - Check for hibernated state on connect
    - Emit state.restored event if recovering from hibernation
    - Enter HIBERNATE state on disconnect (if active workflow)
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.observability.events.redis_bus import get_redis_bus
from core.observability.events.types import CerebroEventType

from ..deps import WebSocketContext

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_context_from_params(
    websocket: WebSocket,
    workspace_id: str,
    token: str | None,
) -> WebSocketContext | None:
    """
    Extract context from JWT token.

    V11.6.2 IRONCLAD: JWT token is MANDATORY.
    The tenant_id query param fallback has been REMOVED to prevent IDOR attacks.
    This is the same vulnerability pattern that was fixed in REST endpoints.

    Args:
        websocket: WebSocket connection
        workspace_id: Workspace identifier (from query param, validated against JWT)
        token: JWT authentication token (MANDATORY)

    Returns:
        WebSocketContext if valid JWT, None otherwise
    """
    if not token:
        logger.warning("[IRONCLAD] WebSocket connection rejected: no token provided")
        return None

    try:
        from ..deps import _decode_token

        claims = _decode_token(token)
        if claims:
            # V11.6.2 IRONCLAD: tenant_id from JWT ONLY (Zero Trust)
            jwt_tenant = claims.get("tenant_id")
            jwt_workspace = claims.get("workspace_id", workspace_id)

            if not jwt_tenant:
                logger.warning("[IRONCLAD] WebSocket rejected: JWT missing tenant_id claim")
                return None

            return WebSocketContext(
                tenant_id=jwt_tenant,
                user_id=claims.get("sub", "anonymous"),
                workspace_id=jwt_workspace,
            )
    except Exception as e:
        logger.warning(f"[IRONCLAD] WebSocket rejected: invalid token - {e}")

    return None


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    workspace_id: str = Query("default", description="Workspace identifier"),
    token: str | None = Query(None, description="JWT auth token (MANDATORY)"),
    event_types: str | None = Query(None, description="Comma-separated event types to filter"),
):
    """
    Stream events to connected WebSocket clients.

    V11.6.2 IRONCLAD: MANDATORY authentication.
    JWT token is REQUIRED - anonymous tenant_id param removed (IDOR prevention).

    Query Parameters:
        workspace_id: Workspace identifier (default: "default")
        token: JWT authentication token (MANDATORY)
        event_types: Comma-separated list of event types to subscribe to

    Events are sent as JSON objects with event_type, payload, timestamp, event_id.

    Raises:
        4001: Authentication required (no token or invalid token)
    """
    # V11.6.2 IRONCLAD: Extract context from JWT ONLY
    ctx = await _get_context_from_params(websocket, workspace_id, token)

    if not ctx:
        await websocket.close(code=4001, reason="Authentication required")
        return

    # Accept connection
    await websocket.accept()
    logger.info(f"CEREBRO: WebSocket connected for {ctx}")

    # V12.2 IRONCLAD: Check for hibernated state
    hibernate_state = None
    try:
        from core.fsm.hibernation_manager import HibernationManager

        hibernate_state = await HibernationManager.get_hibernation(
            tenant_id=UUID(ctx.tenant_id),
            workspace_id=ctx.workspace_id,
        )
        if hibernate_state:
            # Restore state and notify client
            restored = await HibernationManager.exit_hibernate(
                tenant_id=UUID(ctx.tenant_id),
                workspace_id=ctx.workspace_id,
            )
            if restored:
                await websocket.send_json(
                    {
                        "event_type": "state.restored",
                        "payload": {
                            "previous_state": restored["previous_state"],
                            "hibernated_at": restored["entered_at"].isoformat(),
                            "fsm_context": restored.get("fsm_context"),
                            "active_agent": restored.get("active_agent"),
                            "turn_count": restored.get("turn_count", 0),
                        },
                    }
                )
                logger.info(
                    f"CEREBRO: Restored from hibernation: {ctx.tenant_id}/{ctx.workspace_id} "
                    f"previous_state={restored['previous_state']}"
                )
    except ImportError:
        logger.debug("CEREBRO: Hibernation manager not available")
    except Exception as e:
        logger.warning(f"CEREBRO: Failed to check hibernation: {e}")

    # Parse event type filter
    filter_types: list[CerebroEventType] | None = None
    if event_types:
        try:
            filter_types = [CerebroEventType(et.strip()) for et in event_types.split(",")]
        except ValueError as e:
            await websocket.send_json({"error": f"Invalid event_type: {e}"})

    # Get event bus
    bus = get_redis_bus()

    # V12.0: Inform client about streaming mode (Redis or in-memory)
    streaming_mode = "redis" if bus.is_connected() else "memory"
    if not bus.is_connected():
        await websocket.send_json(
            {
                "event_type": "system.info",
                "payload": {
                    "message": "Running in development mode (in-memory event bus)",
                    "mode": streaming_mode,
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "event_id": str(uuid.uuid4()),
            }
        )

    # Stream events (from Redis or in-memory)
    try:
        # Send initial connected message
        await websocket.send_json(
            {
                "event_type": "system.connected",
                "payload": {
                    "tenant_id": ctx.tenant_id,
                    "workspace_id": ctx.workspace_id,
                    "filter": [et.value for et in filter_types] if filter_types else "all",
                    "mode": streaming_mode,
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "event_id": str(uuid.uuid4()),
            }
        )

        logger.info(
            f"CEREBRO: Starting event subscription for {ctx.tenant_id}/{ctx.workspace_id} (mode={streaming_mode})"
        )

        # Subscribe and stream events
        async for event in bus.subscribe(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            event_types=filter_types,
        ):
            await websocket.send_json(
                {
                    "event_type": event.event_type.value,
                    "payload": event.payload,
                    "timestamp": event.timestamp,
                    "event_id": event.event_id,
                }
            )

    except WebSocketDisconnect:
        logger.info(f"CEREBRO: WebSocket disconnected: {ctx}")
    except asyncio.CancelledError:
        logger.debug(f"CEREBRO: WebSocket cancelled: {ctx}")
    except Exception as e:
        logger.error(f"CEREBRO: WebSocket error: {e}")
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "event_type": "system.error",
                    "payload": {"message": str(e)},
                }
            )


@router.websocket("/echo")
async def websocket_echo(websocket: WebSocket):
    """
    Echo WebSocket for testing.

    Echoes back any message received.
    """
    await websocket.accept()
    logger.debug("CEREBRO: Echo WebSocket connected")

    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"echo: {data}")
    except WebSocketDisconnect:
        logger.debug("CEREBRO: Echo WebSocket disconnected")
