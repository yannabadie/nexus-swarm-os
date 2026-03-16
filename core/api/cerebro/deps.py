"""
NEXUS V10 CEREBRO - FastAPI Dependencies
V11.6 KEYMAKER - Added HTTP authentication dependencies

Dependency injection for WebSocket and HTTP authentication.

WebSocket Auth Methods:
1. Query params: ?tenant_id=xxx&token=yyy
2. First message: {"type": "auth", "tenant_id": "xxx", "token": "yyy"}

HTTP Auth Methods (V11.6):
1. Authorization header: Bearer <jwt>
2. Optional: Falls back to anonymous if auth not required

Note: Use require_auth() for protected routes, get_current_user_optional() for optional auth.
"""

import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException, WebSocket, status

logger = logging.getLogger(__name__)


@dataclass
class WebSocketContext:
    """
    Context extracted from WebSocket connection.

    Provides tenant isolation info for event filtering.
    """

    tenant_id: str
    user_id: str
    workspace_id: str

    def __str__(self) -> str:
        return f"WebSocketContext(tenant={self.tenant_id}, user={self.user_id}, ws={self.workspace_id})"


def _decode_token(token: str) -> dict | None:
    """Decode JWT token and return claims."""
    try:
        from jose import jwt

        from .middleware import JWT_ALGORITHM, JWT_SECRET

        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_exp": True})
    except Exception as e:
        logger.debug(f"Token decode failed: {e}")
        return None


async def get_ws_context(websocket: WebSocket) -> WebSocketContext:
    """
    Extract context from WebSocket connection.

    Auth Methods (in order):
    1. Query param 'token' (JWT)
    2. Query param 'tenant_id' (simple auth for dev)

    Args:
        websocket: FastAPI WebSocket connection

    Returns:
        WebSocketContext with tenant/user/workspace info

    Raises:
        HTTPException: If no valid auth provided
    """
    # Method 1: JWT token in query params
    token = websocket.query_params.get("token")
    if token:
        claims = _decode_token(token)
        if claims:
            return WebSocketContext(
                tenant_id=claims.get("tenant_id", "anonymous"),
                user_id=claims.get("sub", "anonymous"),
                workspace_id=claims.get("workspace_id", "default"),
            )

    # Method 2: Simple tenant_id in query params (dev mode)
    tenant_id = websocket.query_params.get("tenant_id")
    if tenant_id:
        return WebSocketContext(
            tenant_id=tenant_id,
            user_id=websocket.query_params.get("user_id", "anonymous"),
            workspace_id=websocket.query_params.get("workspace_id", "default"),
        )

    # No auth - reject
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="WebSocket requires authentication. Use ?token=<jwt> or ?tenant_id=<id>",
    )


async def get_ws_context_optional(websocket: WebSocket) -> WebSocketContext | None:
    """
    Extract context from WebSocket connection (optional).

    Same as get_ws_context but returns None instead of raising exception.

    Args:
        websocket: FastAPI WebSocket connection

    Returns:
        WebSocketContext or None if no valid auth
    """
    try:
        return await get_ws_context(websocket)
    except HTTPException:
        return None


def create_ws_url(
    base_url: str,
    tenant_id: str,
    workspace_id: str = "default",
    token: str | None = None,
) -> str:
    """
    Create WebSocket URL with auth params.

    Args:
        base_url: Base WebSocket URL (e.g., "ws://localhost:8080/ws/stream")
        tenant_id: Tenant identifier
        workspace_id: Workspace identifier
        token: Optional JWT token

    Returns:
        Complete WebSocket URL with query params

    Example:
        url = create_ws_url("ws://localhost:8080/ws/stream", "tenant_1")
        # -> "ws://localhost:8080/ws/stream?tenant_id=tenant_1&workspace_id=default"
    """
    params = [f"tenant_id={tenant_id}", f"workspace_id={workspace_id}"]
    if token:
        params.append(f"token={token}")
    return f"{base_url}?{'&'.join(params)}"


# =============================================================================
# V11.6 KEYMAKER - HTTP Authentication Dependencies
# =============================================================================


@dataclass
class AuthenticatedUser:
    """
    Authenticated user context for HTTP requests.

    Extracted from JWT token claims.
    V12.2 IRONCLAD: Added role field for RBAC.
    """

    user_id: str
    tenant_id: str
    workspace_id: str
    role: str = "viewer"  # V12.2: Default to most restrictive role

    def __str__(self) -> str:
        return f"AuthenticatedUser(user={self.user_id}, tenant={self.tenant_id}, role={self.role})"


async def require_auth(authorization: str | None = Header(None, description="Bearer <jwt>")) -> AuthenticatedUser:
    """
    Dependency that requires authentication.

    Use with Depends() on routes that must be protected:

        @router.get("/protected")
        async def protected_route(user: AuthenticatedUser = Depends(require_auth)):
            return {"tenant_id": user.tenant_id}

    Args:
        authorization: Authorization header (Bearer token)

    Returns:
        AuthenticatedUser with user_id, tenant_id, workspace_id

    Raises:
        HTTPException 401: If not authenticated or token invalid
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]
    claims = _decode_token(token)

    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(
        user_id=claims.get("sub", "anonymous"),
        tenant_id=claims.get("tenant_id", "default"),
        workspace_id=claims.get("workspace_id", "default"),
        role=claims.get("role", "viewer"),  # V12.2 IRONCLAD: Extract role from JWT
    )


async def get_current_user_optional(
    authorization: str | None = Header(None, description="Bearer <jwt>"),
) -> AuthenticatedUser | None:
    """
    Dependency that optionally extracts authentication.

    [warning]️ SECURITY WARNING (V11.6.1 IRONCLAD):
    This function should ONLY be used for routes that are genuinely public.
    For ANY route that accesses tenant-scoped data, use `require_auth` instead.

    NEVER use this to accept tenant_id from query params as fallback.
    That pattern creates IDOR vulnerabilities.

    Safe use cases:
    - Public health check with optional user info
    - Analytics/telemetry that works anonymously

    UNSAFE use cases (use require_auth instead):
    - Accessing tenant state, workflows, files
    - Any route that uses tenant_id/workspace_id for data isolation

    Args:
        authorization: Authorization header (Bearer token)

    Returns:
        AuthenticatedUser if valid token, None otherwise
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization[7:]
    claims = _decode_token(token)

    if not claims:
        return None

    return AuthenticatedUser(
        user_id=claims.get("sub", "anonymous"),
        tenant_id=claims.get("tenant_id", "default"),
        workspace_id=claims.get("workspace_id", "default"),
        role=claims.get("role", "viewer"),  # V12.2 IRONCLAD
    )
