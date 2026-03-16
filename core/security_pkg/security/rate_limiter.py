"""
BACKWARD COMPATIBILITY RE-EXPORT

All security rate limiting functionality has been consolidated into:
  core/resilience/unified_rate_limiter.py

This file re-exports SecurityRateLimiter for backward compatibility.

DEPRECATED: This file will be removed in V13.0. Update imports to:
  from core.infrastructure.resilience.unified_rate_limiter import SecurityRateLimiter

Sprint 1 Consolidation: Eliminated 365 lines of duplicate token bucket code.
"""

from core.infrastructure.resilience.unified_rate_limiter import (
    DEFAULT_BUCKET_SIZE,
    DEFAULT_TOKENS_PER_SECOND,
    MAX_KEYS_PER_LIMIT,
    MAX_LIMITS,
    BucketState,
    LimiterStats,
    RateLimitConfig,
    RateLimitResult,
)
from core.infrastructure.resilience.unified_rate_limiter import (
    SecurityRateLimiter as RateLimiter,
)
from core.infrastructure.resilience.unified_rate_limiter import (
    get_security_rate_limiter as get_rate_limiter,
)
from core.infrastructure.resilience.unified_rate_limiter import (
    reset_security_rate_limiter as reset_rate_limiter,
)

__all__ = [
    "RateLimiter",
    "get_rate_limiter",
    "reset_rate_limiter",
    "RateLimitConfig",
    "BucketState",
    "RateLimitResult",
    "LimiterStats",
    "DEFAULT_TOKENS_PER_SECOND",
    "DEFAULT_BUCKET_SIZE",
    "MAX_LIMITS",
    "MAX_KEYS_PER_LIMIT",
]
