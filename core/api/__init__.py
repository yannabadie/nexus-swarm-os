"""
API Module - Rate Limiting and API Management

NEXUS V12.4 - FORGE Update

Provides:
- APIRateLimiter: Token bucket rate limiter for API calls
- Prevents 429 Too Many Requests errors in PARALLEL mode

Imports are lazy to avoid circular dependency:
core.api -> core.infrastructure -> core.intelligence.swarm -> core.api
"""

import importlib as _importlib


def __getattr__(name: str):
    """Lazy import to break circular dependency with infrastructure/intelligence."""
    _exports = {
        "APIRateLimiter": ".rate_limiter",
        "RateLimitExceeded": ".rate_limiter",
    }
    if name in _exports:
        mod = _importlib.import_module(_exports[name], __package__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["APIRateLimiter", "RateLimitExceeded"]
