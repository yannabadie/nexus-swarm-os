"""
NEXUS V12.1 RETINA - HTTP Rate Limiting for CEREBRO API

Provides protection against:
- Brute-force attacks on login endpoint (5/minute)
- DoS on workflow endpoints (10/minute)
- Abuse on file operations (30/minute)

Uses slowapi library with Redis backend (fallback to in-memory).

Author: Claude (NEXUS V12.1 RETINA - Conseiller 1 feedback)
Date: 2025-12-16
"""

import logging
import os
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Rate limit configuration per endpoint pattern
RATE_LIMITS = {
    "/api/auth/login": "5/minute",  # Brute-force protection
    "/api/workflow/start": "10/minute",  # DoS protection
    "/api/files/save": "30/minute",  # Abuse protection
    "/api/files/tree": "20/minute",  # Tree traversal protection
    "default": "100/minute",  # General API limit
}


def get_remote_address(request: Request) -> str:
    """
    Extract client IP address from request.

    Handles X-Forwarded-For header for reverse proxy setups.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    client = request.client
    if client:
        return client.host

    return "unknown"


def get_rate_limit_for_path(path: str) -> str:
    """Get rate limit string for a given path."""
    for pattern, limit in RATE_LIMITS.items():
        if pattern != "default" and path.startswith(pattern):
            return limit
    return RATE_LIMITS["default"]


# Try to use slowapi, fallback to simple in-memory limiter
_limiter = None
_use_slowapi = False

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address as slowapi_get_remote

    # Check if Redis is available for distributed rate limiting
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    try:
        # Try Redis storage for distributed rate limiting
        _limiter = Limiter(
            key_func=slowapi_get_remote,
            storage_uri=redis_url,
            strategy="moving-window",
        )
        _use_slowapi = True
        logger.info(f"[RETINA] Rate limiting enabled with Redis backend: {redis_url}")
    except Exception as e:
        # Fallback to in-memory
        _limiter = Limiter(key_func=slowapi_get_remote)
        _use_slowapi = True
        logger.warning(f"[RETINA] Rate limiting using in-memory (Redis unavailable: {e})")

except ImportError:
    logger.warning("[RETINA] slowapi not installed - run 'pip install slowapi' for rate limiting")


def get_limiter():
    """Get the rate limiter instance (or None if unavailable)."""
    return _limiter


def is_rate_limiting_enabled() -> bool:
    """Check if rate limiting is enabled."""
    return _use_slowapi and _limiter is not None


async def rate_limit_exceeded_handler(request: Request, exc) -> Response:
    """
    Handler for rate limit exceeded errors.

    Returns JSON response with retry-after header.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down.",
            "detail": str(exc.detail) if hasattr(exc, "detail") else "Rate limit exceeded",
        },
        headers={"Retry-After": "60"},
    )


def setup_rate_limiting(app):
    """
    Configure rate limiting for FastAPI app.

    Args:
        app: FastAPI application instance
    """
    if not is_rate_limiting_enabled():
        logger.debug("[RETINA] Rate limiting not configured")
        return

    try:
        from slowapi.errors import RateLimitExceeded

        app.state.limiter = _limiter
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
        # Note: SlowAPIMiddleware is optional, we use decorator-based limiting

        logger.info("[RETINA] Rate limiting middleware configured")

    except ImportError as e:
        logger.warning(f"[RETINA] Failed to setup rate limiting: {e}")


# Decorator factory for route-level rate limiting
def limit(limit_string: str):
    """
    Decorator factory for rate limiting routes.

    Usage:
        @router.get("/endpoint")
        @limit("10/minute")
        async def endpoint(request: Request):
            ...

    Args:
        limit_string: Rate limit in format "count/period" (e.g., "10/minute")

    Returns:
        Decorator function
    """
    if _limiter is not None:
        return _limiter.limit(limit_string)
    else:
        # No-op decorator if limiter not available
        def noop_decorator(func: Callable) -> Callable:
            return func

        return noop_decorator


# =============================================================================
# Simple fallback rate limiter (if slowapi not installed)
# =============================================================================

import time  # noqa: E402  # after slowapi fallback section
from collections import defaultdict  # noqa: E402
from threading import Lock  # noqa: E402


class SimpleRateLimiter:
    """
    Simple in-memory rate limiter fallback.

    Uses token bucket algorithm per IP address.
    Not suitable for distributed deployments.
    """

    def __init__(self):
        self._buckets: dict = defaultdict(lambda: {"tokens": 100, "last_update": time.time()})
        self._lock = Lock()

    def _parse_limit(self, limit_string: str) -> tuple:
        """Parse '10/minute' format to (count, seconds)."""
        parts = limit_string.split("/")
        count = int(parts[0])
        period = parts[1].lower()

        period_seconds = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }.get(period, 60)

        return count, period_seconds

    def check_rate_limit(self, key: str, limit_string: str) -> bool:
        """
        Check if request is within rate limit.

        Args:
            key: Identifier (usually IP address)
            limit_string: Rate limit (e.g., "10/minute")

        Returns:
            True if allowed, False if rate limited
        """
        max_tokens, period = self._parse_limit(limit_string)

        with self._lock:
            now = time.time()
            bucket = self._buckets[key]

            # Refill tokens based on elapsed time
            elapsed = now - bucket["last_update"]
            refill_rate = max_tokens / period
            new_tokens = bucket["tokens"] + (elapsed * refill_rate)
            bucket["tokens"] = min(max_tokens, new_tokens)
            bucket["last_update"] = now

            # Check if token available
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True

            return False


_simple_limiter = SimpleRateLimiter()


def check_simple_rate_limit(request: Request, limit_string: str = "100/minute") -> bool:
    """
    Check rate limit using simple in-memory limiter.

    Use this as fallback when slowapi is not available.

    Args:
        request: FastAPI request
        limit_string: Rate limit string

    Returns:
        True if allowed, False if rate limited
    """
    if is_rate_limiting_enabled():
        # Use slowapi instead
        return True

    key = get_remote_address(request)
    return _simple_limiter.check_rate_limit(key, limit_string)
