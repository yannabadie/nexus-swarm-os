"""
NEXUS V12.2 IRONCLAD - Authentication Endpoints

Provides JWT authentication for CEREBRO UI:
- POST /api/auth/login : Authenticate and get JWT token
- GET /api/auth/me : Verify token and get user info
- POST /api/auth/refresh : Refresh token before expiration (V12.1 RETINA)
- POST /api/auth/logout : Logout (client-side token removal)

Security Notes:
- V12.2: Database-backed user authentication with bcrypt
- Fallback to NEXUS_ADMIN_PASSWORD env var for backward compatibility
- 24h token expiration
- V12.1 RETINA: Refresh token mechanism (Conseiller 2 feedback)

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import logging
import os

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# Configuration
# =============================================================================

# Fallback: Single admin password from environment (backward compatibility)
FALLBACK_ADMIN_PASSWORD = os.environ.get("NEXUS_ADMIN_PASSWORD", "nexus")
TOKEN_EXPIRE_HOURS = 24

# Warn if using default password
if FALLBACK_ADMIN_PASSWORD == "nexus":
    logger.warning(
        "NEXUS_ADMIN_PASSWORD not set! Using default 'nexus'. "
        "Set NEXUS_ADMIN_PASSWORD environment variable for security."
    )


# =============================================================================
# Database Authentication (V12.2 IRONCLAD)
# =============================================================================


def authenticate_user_db(username: str, password: str) -> tuple[bool, dict | None]:
    """
    Authenticate user against database.

    Args:
        username: Username to authenticate
        password: Plaintext password to verify

    Returns:
        Tuple of (success, user_info_dict or None)
        user_info contains: user_id, tenant_id, role
    """
    try:
        from sqlmodel import select

        from core.infrastructure.db import User, get_session
        from core.security_pkg.security.password import verify_password

        with get_session() as session:
            statement = select(User).where(User.username == username, User.is_active)
            user = session.exec(statement).first()

            if user and verify_password(password, user.hashed_password):
                return True, {
                    "user_id": str(user.id),
                    "tenant_id": str(user.tenant_id),
                    "role": user.role.value if hasattr(user.role, "value") else str(user.role),
                }

        return False, None

    except Exception as e:
        logger.debug(f"[KEYMAKER] DB auth failed, will try fallback: {e}")
        return False, None


def authenticate_user_fallback(username: str, password: str) -> tuple[bool, dict | None]:
    """
    Fallback authentication using environment variable.

    For backward compatibility when:
    - Database not initialized
    - User not in database

    Args:
        username: Username (any accepted for MVP)
        password: Password to check against NEXUS_ADMIN_PASSWORD

    Returns:
        Tuple of (success, user_info_dict or None)
    """
    if password == FALLBACK_ADMIN_PASSWORD:
        return True, {
            "user_id": username,
            "tenant_id": "default",
            "role": "admin",  # Fallback users get admin role
        }
    return False, None


def authenticate_user(username: str, password: str) -> tuple[bool, dict]:
    """
    Authenticate user: try DB first, fallback to env var.

    Args:
        username: Username to authenticate
        password: Password to verify

    Returns:
        Tuple of (success, user_info_dict)

    Raises:
        HTTPException 401 if authentication fails
    """
    # Try database authentication first
    success, user_info = authenticate_user_db(username, password)
    if success:
        logger.info(f"[KEYMAKER] DB auth successful for user: {username}")
        return True, user_info

    # Fallback to environment variable
    success, user_info = authenticate_user_fallback(username, password)
    if success:
        logger.info(f"[KEYMAKER] Fallback auth successful for user: {username}")
        return True, user_info

    # Authentication failed
    logger.warning(f"[KEYMAKER] Failed login attempt for user: {username}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


# =============================================================================
# Request/Response Models
# =============================================================================


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Login response with JWT token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    tenant_id: str
    user_id: str


class UserInfo(BaseModel):
    """Current user info response."""

    user_id: str
    tenant_id: str
    workspace_id: str
    authenticated: bool = True


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """
    Authenticate user and return JWT token.

    V12.2 IRONCLAD Implementation:
    - Try database authentication first (bcrypt hashed passwords)
    - Fallback to NEXUS_ADMIN_PASSWORD env var for backward compatibility
    - Returns user's actual tenant_id and role from database

    Args:
        body: LoginRequest with username and password

    Returns:
        TokenResponse with access_token, expires_in, etc.

    Raises:
        401: Invalid credentials
    """
    # Authenticate user (DB first, then fallback)
    # This will raise HTTPException 401 if both fail
    _, user_info = authenticate_user(body.username, body.password)

    # Generate JWT token
    try:
        from ..middleware import create_jwt_token

        expires_seconds = TOKEN_EXPIRE_HOURS * 3600
        token = create_jwt_token(
            tenant_id=user_info["tenant_id"],
            user_id=user_info["user_id"],
            workspace_id="default",
            expires_in_seconds=expires_seconds,
            # V12.2: Include role in token claims
            extra_claims={"role": user_info["role"]},
        )

        return TokenResponse(
            access_token=token,
            expires_in=expires_seconds,
            tenant_id=user_info["tenant_id"],
            user_id=user_info["user_id"],
        )

    except ImportError as e:
        logger.error(f"[KEYMAKER] JWT library not available: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service unavailable (python-jose not installed)",
        ) from e
    except Exception as e:
        logger.error(f"[KEYMAKER] Token generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token generation failed",
        ) from e


@router.get("/me", response_model=UserInfo)
async def get_current_user(authorization: str | None = Header(None, description="Bearer token")) -> UserInfo:
    """
    Verify token and return current user info.

    Used by UI to:
    - Check if stored token is still valid on page load
    - Get user info for display

    Args:
        authorization: Bearer token in Authorization header

    Returns:
        UserInfo with user_id, tenant_id, workspace_id

    Raises:
        401: Not authenticated or invalid token
    """
    # Check Authorization header
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract and decode token
    token = authorization[7:]

    try:
        from ..middleware import decode_jwt

        claims = decode_jwt(token)

        if not claims:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return UserInfo(
            user_id=claims.get("sub", "anonymous"),
            tenant_id=claims.get("tenant_id", "default"),
            workspace_id=claims.get("workspace_id", "default"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[KEYMAKER] Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


@router.post("/logout")
async def logout() -> dict:
    """
    Logout endpoint (client-side token invalidation).

    Note: JWT tokens are stateless, so logout is handled client-side
    by removing the token from storage. This endpoint exists for
    API completeness and potential future server-side invalidation.

    Returns:
        {"status": "logged_out"}
    """
    # MVP: No server-side token invalidation
    # Future: Add token to blacklist in Redis
    return {"status": "logged_out", "message": "Remove token from client storage"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(authorization: str | None = Header(None, description="Bearer token")) -> TokenResponse:
    """
    V12.1 RETINA: Refresh JWT token before expiration.

    Returns a new access_token with extended expiry (24h from now).
    The original token must still be valid (not expired).

    Frontend should call this ~5 minutes before token expiration:
    ```typescript
    const decoded = jwtDecode(token);
    const refreshAt = (decoded.exp - 300) * 1000; // 5min before
    setTimeout(() => refreshToken(), refreshAt - Date.now());
    ```

    Args:
        authorization: Bearer token in Authorization header

    Returns:
        TokenResponse with new access_token

    Raises:
        401: Not authenticated or token expired
    """
    # Check Authorization header
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract and decode token
    token = authorization[7:]

    try:
        from ..middleware import create_jwt_token, decode_jwt

        claims = decode_jwt(token)

        if not claims:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token. Please login again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Generate new token with same claims but fresh expiration
        expires_seconds = TOKEN_EXPIRE_HOURS * 3600
        new_token = create_jwt_token(
            tenant_id=claims.get("tenant_id", "default"),
            user_id=claims.get("sub", "anonymous"),
            workspace_id=claims.get("workspace_id", "default"),
            expires_in_seconds=expires_seconds,
        )

        logger.info(f"[KEYMAKER] Token refreshed for user: {claims.get('sub')}")

        return TokenResponse(
            access_token=new_token,
            expires_in=expires_seconds,
            tenant_id=claims.get("tenant_id", "default"),
            user_id=claims.get("sub", "anonymous"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[KEYMAKER] Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token refresh failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
