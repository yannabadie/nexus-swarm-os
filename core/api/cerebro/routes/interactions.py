"""
NEXUS V11.5 CORTEX - Interaction Response Endpoints
V11.6.1 IRONCLAD - MANDATORY authentication (Zero Trust)

Enables Human-in-the-Loop for CEREBRO UI:
- POST /api/interactions/{request_id}/reply : Reply to a pending interaction
- GET /api/interactions/pending : List pending interactions

Authentication:
- V11.6.1 IRONCLAD: MANDATORY auth for all interaction endpoints

Author: Claude (NEXUS V11.5 CORTEX)
Date: 2025-12-15
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import AuthenticatedUser, require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


class InteractionResponse(BaseModel):
    """Request body for replying to an interaction."""

    response: Any


@router.post("/{request_id}/reply")
async def reply_to_interaction(
    request_id: str,
    body: InteractionResponse,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, str]:
    """
    Reply to a pending interaction.

    Called by CEREBRO UI when user responds to an ask/confirm/choose prompt.

    V11.6.1 IRONCLAD: MANDATORY authentication.

    Args:
        request_id: The request_id from the interaction.* event
        body: Response payload containing the user's answer
        user: Authenticated user (from JWT token)

    Returns:
        {"status": "resolved", "request_id": request_id}

    Raises:
        401: Not authenticated
        400: Provider does not support interaction resolution
        404: Request not found or already expired
    """
    try:
        from core.security_pkg.interaction import get_interaction_provider

        provider = get_interaction_provider()
    except Exception as e:
        logger.error(f"Failed to get interaction provider: {e}")
        raise HTTPException(500, "Interaction provider unavailable") from e

    # Check if provider supports interactive mode
    if not hasattr(provider, "resolve_interaction"):
        raise HTTPException(
            400,
            "Provider does not support interaction resolution. "
            "Ensure HeadlessProvider was created with interactive=True",
        )

    # Resolve the pending interaction
    resolved = provider.resolve_interaction(request_id, body.response)

    if not resolved:
        raise HTTPException(404, f"Request {request_id} not found or already expired/resolved")

    logger.info(f"[CORTEX] Interaction {request_id} resolved via API")
    return {"status": "resolved", "request_id": request_id}


@router.get("/pending")
async def list_pending_interactions(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, list[dict]]:
    """
    List all pending interactions.

    Used for debugging and for state snapshot (F5 recovery).

    V11.6.1 IRONCLAD: MANDATORY authentication.

    Args:
        user: Authenticated user (from JWT token)

    Returns:
        {"pending": [...list of pending interaction dicts...]}

    Raises:
        401: Not authenticated
    """
    try:
        from core.security_pkg.interaction import get_interaction_provider

        provider = get_interaction_provider()
    except Exception as e:
        logger.warning(f"Failed to get interaction provider: {e}")
        return {"pending": []}

    if hasattr(provider, "get_pending_requests"):
        pending = provider.get_pending_requests()
        return {"pending": pending}

    return {"pending": []}
