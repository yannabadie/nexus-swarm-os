"""
BACKWARD COMPATIBILITY RE-EXPORT

Provider rate limiting functionality has been consolidated into:
  core/resilience/unified_rate_limiter.py

This file re-exports ProviderRateLimiter for backward compatibility.

DEPRECATED: This file will be removed in V13.0. Update imports to:
  from core.infrastructure.resilience.unified_rate_limiter import ProviderRateLimiter

Sprint 1 Consolidation: Eliminated 359 lines of duplicate token bucket code.
"""

from core.infrastructure.resilience.unified_rate_limiter import (
    DEFAULT_PROVIDER_LIMITS as DEFAULT_LIMITS,
)
from core.infrastructure.resilience.unified_rate_limiter import (
    ProviderLimits,
    ProviderState,
    TokenBucket,
)
from core.infrastructure.resilience.unified_rate_limiter import (
    ProviderRateLimiter as RateLimiter,
)

__all__ = [
    "RateLimiter",
    "ProviderLimits",
    "ProviderState",
    "TokenBucket",
    "DEFAULT_LIMITS",
]
