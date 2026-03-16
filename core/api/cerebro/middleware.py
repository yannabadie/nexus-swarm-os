"""
NEXUS V10 CEREBRO - Tenant Context Middleware

Hydrates PRISM SessionContext from JWT for HTTP requests.
WebSocket connections use dependency injection instead (see deps.py).

JWT Payload Expected:
{
    "sub": "user_id",
    "tenant_id": "tenant_abc",
    "workspace_id": "default",
    "exp": 1234567890
}

V11.3 HARDENING: JWT_SECRET loaded from environment variable.
"""

import logging
import os
from datetime import UTC

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# V11.3 HARDENING: JWT secret from environment (NEVER hardcode in production)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET = os.environ.get("NEXUS_JWT_SECRET")
JWT_ALGORITHM = "HS256"

# Fail-fast pattern: warn in dev, would fail in production without secret
if not JWT_SECRET:
    # Development fallback - REMOVE IN PRODUCTION
    JWT_SECRET = "nexus-dev-insecure-secret-CHANGE-ME"
    logger.warning(
        "[warning]️  NEXUS_JWT_SECRET not set! Using insecure dev secret. "
        "Set NEXUS_JWT_SECRET environment variable for production."
    )


def decode_jwt(token: str) -> dict | None:
    """
    Decode and validate JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded claims dict or None if invalid
    """
    try:
        from jose import jwt

        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_exp": True})
        return claims
    except ImportError:
        logger.warning("python-jose not installed, JWT auth disabled")
        return None
    except Exception as e:
        logger.debug(f"JWT decode failed: {e}")
        return None


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to hydrate PRISM SessionContext from JWT.

    Only applies to HTTP requests, not WebSocket (websocket scope type).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request and hydrate tenant context.

        Args:
            request: Starlette Request
            call_next: Next middleware/handler

        Returns:
            Response
        """
        # Skip WebSocket connections - they use dependency injection
        if request.scope.get("type") == "websocket":
            return await call_next(request)

        # Try to extract JWT from Authorization header
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            claims = decode_jwt(token)

            if claims:
                # Hydrate PRISM context
                try:
                    from core.infrastructure.context import use_context_async

                    async with use_context_async(
                        tenant_id=claims.get("tenant_id", "anonymous"),
                        user_id=claims.get("sub", "anonymous"),
                        workspace_id=claims.get("workspace_id", "default"),
                    ):
                        return await call_next(request)

                except ImportError:
                    # context module not available
                    pass

        # No auth or auth failed - continue without context
        return await call_next(request)


def create_jwt_token(
    tenant_id: str,
    user_id: str = "anonymous",
    workspace_id: str = "default",
    expires_in_seconds: int = 3600,
    extra_claims: dict | None = None,
) -> str:
    """
    Create a JWT token.

    Args:
        tenant_id: Tenant identifier
        user_id: User identifier
        workspace_id: Workspace identifier
        expires_in_seconds: Token expiration time
        extra_claims: V12.2 IRONCLAD - Additional claims (e.g., role)

    Returns:
        JWT token string
    """
    from datetime import datetime, timedelta

    from jose import jwt

    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_seconds),
    }

    # V12.2 IRONCLAD: Merge extra claims (e.g., role)
    if extra_claims:
        claims.update(extra_claims)

    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)
