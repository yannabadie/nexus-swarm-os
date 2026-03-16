"""
NEXUS V11.5 CORTEX - State Snapshot Endpoint
V11.6.1 IRONCLAD - MANDATORY authentication (Zero Trust)
V13.0 FIX - In-memory fallback when Redis unavailable

Enables F5 Recovery for CEREBRO UI:
- GET /api/state/snapshot : Get state snapshot for UI hydration
- DELETE /api/state/snapshot : Clear state (for testing)

The snapshot includes:
- Phase state (current HiveMind phase)
- Graph nodes (agents in the swarm)
- Recent logs (last 100 entries)
- Pending interactions (CRITICAL: for Fantôme fix)

Authentication:
- V11.6.1 IRONCLAD: MANDATORY auth - tenant_id from JWT ONLY
- Query param backdoors REMOVED to prevent IDOR attacks

V13.0: Falls back to in-memory state when Redis is unavailable.

Author: Claude (NEXUS V11.5 CORTEX)
Date: 2025-12-15
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends

from ..deps import AuthenticatedUser, require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/snapshot")
async def get_state_snapshot(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """
    Get state snapshot for UI hydration (F5 recovery).

    Called by CEREBRO UI on page load/refresh to restore state.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    tenant_id and workspace_id are extracted from JWT token ONLY.
    No query param backdoors - prevents IDOR attacks.

    V13.0: Falls back to in-memory state when Redis is unavailable.

    Args:
        user: Authenticated user (from JWT token)

    Returns:
        Dict with:
        - phase: Current HiveMind phase state (or None)
        - nodes: Dict of graph nodes by node_id
        - logs: List of recent log entries (max 100)
        - pending_interactions: List of pending human-in-the-loop requests (CRITICAL)
        - tenant_id: Tenant identifier (from JWT)
        - workspace_id: Workspace identifier (from JWT)

    Raises:
        401: Not authenticated
        500: Snapshot failed
    """
    # V11.6.1 IRONCLAD: tenant_id from JWT ONLY (Zero Trust)
    tenant_id = user.tenant_id
    workspace_id = user.workspace_id

    try:
        from core.observability.events.redis_bus import get_redis_bus

        bus = get_redis_bus()
    except Exception as e:
        logger.error(f"Failed to get Redis bus: {e}")
        # V13.0: Return empty state instead of 503
        return _empty_snapshot(tenant_id, workspace_id)

    # V13.0: Check if Redis is connected, otherwise use in-memory
    if bus.is_connected() and bus._redis:
        return await _get_snapshot_from_redis(bus, tenant_id, workspace_id)
    else:
        # V13.0: Use in-memory state storage
        return _get_snapshot_from_memory(bus, tenant_id, workspace_id)


def _empty_snapshot(tenant_id: str, workspace_id: str) -> dict[str, Any]:
    """Return empty snapshot structure."""
    return {
        "phase": None,
        "nodes": {},
        "logs": [],
        "pending_interactions": [],
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
    }


def _get_snapshot_from_memory(bus, tenant_id: str, workspace_id: str) -> dict[str, Any]:
    """Get snapshot from in-memory state (V13.0 fallback)."""
    try:
        state = bus.get_full_state(tenant_id, workspace_id)

        # Get pending interactions
        pending_interactions = _get_pending_interactions()

        logger.info(
            f"[CORTEX] In-memory snapshot: tenant={tenant_id}, "
            f"workspace={workspace_id}, nodes={len(state.get('nodes', {}))}, "
            f"logs={len(state.get('logs', []))}, pending={len(pending_interactions)}"
        )

        return {
            "phase": state.get("phase"),
            "nodes": state.get("nodes", {}),
            "logs": state.get("logs", []),
            "pending_interactions": pending_interactions,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }
    except Exception as e:
        logger.error(f"In-memory snapshot failed: {e}")
        return _empty_snapshot(tenant_id, workspace_id)


async def _get_snapshot_from_redis(bus, tenant_id: str, workspace_id: str) -> dict[str, Any]:
    """Get snapshot from Redis (original implementation)."""
    redis = bus._redis
    base_key = f"nexus:{tenant_id}:{workspace_id}:state"

    try:
        # Get phase state
        phase_raw = await redis.get(f"{base_key}:phase")
        phase = json.loads(phase_raw) if phase_raw else None

        # Get graph nodes (hash)
        nodes_raw = await redis.hgetall(f"{base_key}:nodes")
        nodes = {}
        if nodes_raw:
            for k, v in nodes_raw.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                nodes[key] = json.loads(val)

        # Get logs (list, most recent first)
        logs_raw = await redis.lrange(f"{base_key}:logs", 0, 99)
        logs = []
        if logs_raw:
            for log_entry in logs_raw:
                entry = log_entry.decode() if isinstance(log_entry, bytes) else log_entry
                logs.append(json.loads(entry))

        # Get pending interactions
        pending_interactions = _get_pending_interactions()

        logger.info(
            f"[CORTEX] Redis snapshot: tenant={tenant_id}, "
            f"workspace={workspace_id}, nodes={len(nodes)}, "
            f"logs={len(logs)}, pending={len(pending_interactions)}"
        )

        return {
            "phase": phase,
            "nodes": nodes,
            "logs": logs,
            "pending_interactions": pending_interactions,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }

    except Exception as e:
        logger.error(f"Redis snapshot failed: {e}")
        # V13.0: Fall back to in-memory
        return _get_snapshot_from_memory(bus, tenant_id, workspace_id)


def _get_pending_interactions() -> list[dict[str, Any]]:
    """Get pending interactions from HeadlessProvider."""
    try:
        from core.security_pkg.interaction import get_interaction_provider

        provider = get_interaction_provider()
        if hasattr(provider, "get_pending_requests"):
            return provider.get_pending_requests()
    except Exception as e:
        logger.debug(f"Could not get pending interactions: {e}")
    return []


@router.delete("/snapshot")
async def clear_state_snapshot(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, str]:
    """
    Clear state snapshot (for testing/debugging).

    Removes all persisted state for a tenant/workspace.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    tenant_id from JWT token ONLY - prevents IDOR attacks.

    V13.0: Clears both Redis and in-memory state.

    Args:
        user: Authenticated user (from JWT token)

    Returns:
        {"status": "cleared"}

    Raises:
        401: Not authenticated
    """
    # V11.6.1 IRONCLAD: tenant_id from JWT ONLY (Zero Trust)
    tenant_id = user.tenant_id
    workspace_id = user.workspace_id

    try:
        from core.observability.events.redis_bus import get_redis_bus

        bus = get_redis_bus()
    except Exception as e:
        logger.error(f"Failed to get Redis bus: {e}")
        return {"status": "cleared"}  # V13.0: No state to clear

    # V13.0: Clear in-memory state always
    bus.clear_state(tenant_id, workspace_id)

    # Clear Redis if connected
    if bus.is_connected() and bus._redis:
        redis = bus._redis
        base_key = f"nexus:{tenant_id}:{workspace_id}:state"

        try:
            await redis.delete(f"{base_key}:phase", f"{base_key}:nodes", f"{base_key}:logs")
        except Exception as e:
            logger.warning(f"Redis clear failed (continuing): {e}")

    logger.info(f"[CORTEX] State cleared: tenant={tenant_id}, workspace={workspace_id}")
    return {"status": "cleared"}
