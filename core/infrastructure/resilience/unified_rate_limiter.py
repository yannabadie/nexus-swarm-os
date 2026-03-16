"""
Unified Rate Limiter - Token bucket rate limiting for all NEXUS components.

V12.4 COGNITIVE BOOST - Sprint 1 Consolidation
Consolidates 3 separate token bucket implementations:
- core/resilience/rate_limiter.py (per-provider API limits)
- core/security/rate_limiter.py (per-key security limits)
- core/api/rate_limiter.py (async/sync API call limits)

Eliminates ~560 lines of duplicate code while preserving all functionality.

Usage:
    # Provider-scoped limiting (Gemini, Claude, etc.)
    from core.infrastructure.resilience.unified_rate_limiter import ProviderRateLimiter
    limiter = ProviderRateLimiter()
    if limiter.acquire("gemini", estimated_tokens=500):
        # make API call

    # Security limiting (per-user, per-IP, etc.)
    from core.infrastructure.resilience.unified_rate_limiter import SecurityRateLimiter
    limiter = SecurityRateLimiter()
    limiter.configure("api", tokens_per_second=10, bucket_size=20)
    if limiter.allow("api", "user-123"):
        # allow request

    # API call limiting (async/sync support)
    from core.infrastructure.resilience.unified_rate_limiter import APIRateLimiter
    limiter = APIRateLimiter(requests_per_minute=60, provider="gemini")
    await limiter.acquire_async()  # async
    limiter.acquire_sync()  # sync
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Core Token Bucket Implementation
# =============================================================================


class TokenBucket:
    """
    Thread-safe token bucket implementation.

    Tokens are added at a constant rate up to max_tokens.
    Each request consumes tokens. If insufficient tokens available,
    the request must wait.
    """

    def __init__(self, rate: float, max_tokens: int):
        """
        Initialize token bucket.

        Args:
            rate: Tokens added per second
            max_tokens: Maximum tokens in bucket
        """
        self.rate = rate
        self.max_tokens = max_tokens
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens acquired, False if insufficient
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_time(self, tokens: int = 1) -> float:
        """
        Calculate time to wait until tokens are available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Seconds to wait (0 if tokens available)
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                return 0.0
            deficit = tokens - self._tokens
            return deficit / self.rate if self.rate > 0 else float("inf")

    @property
    def available(self) -> float:
        """Current available tokens."""
        with self._lock:
            self._refill()
            return self._tokens

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(
            self.max_tokens,
            self._tokens + elapsed * self.rate,
        )

    def reset(self) -> None:
        """Reset bucket to full capacity."""
        with self._lock:
            self._tokens = float(self.max_tokens)
            self._last_refill = time.monotonic()


# =============================================================================
# Provider Rate Limiting (resilience)
# =============================================================================


@dataclass
class ProviderLimits:
    """Rate limits for an API provider."""

    rpm: int = 60  # Requests per minute
    tpm: int = 1_000_000  # Tokens per minute
    max_burst: int = 0  # Max burst above RPM (0 = auto)

    def __post_init__(self):
        if self.max_burst == 0:
            self.max_burst = max(1, self.rpm // 5)


@dataclass
class ProviderState:
    """Tracks rate limiting state for a single provider."""

    provider: str
    limits: ProviderLimits
    request_bucket: TokenBucket = field(init=False)
    token_bucket: TokenBucket = field(init=False)
    total_requests: int = 0
    total_tokens: int = 0
    blocked_requests: int = 0
    last_request_time: float = 0.0

    def __post_init__(self):
        # RPM -> requests per second
        rps = self.limits.rpm / 60.0
        max_burst = self.limits.rpm + self.limits.max_burst
        self.request_bucket = TokenBucket(rate=rps, max_tokens=max_burst)

        # TPM -> tokens per second
        tps = self.limits.tpm / 60.0
        self.token_bucket = TokenBucket(rate=tps, max_tokens=self.limits.tpm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "rpm_limit": self.limits.rpm,
            "tpm_limit": self.limits.tpm,
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "blocked_requests": self.blocked_requests,
            "request_tokens_available": round(self.request_bucket.available, 1),
            "token_tokens_available": round(self.token_bucket.available, 0),
        }


# Default provider limits
DEFAULT_PROVIDER_LIMITS: dict[str, ProviderLimits] = {
    "gemini": ProviderLimits(rpm=60, tpm=1_000_000),
    "claude": ProviderLimits(rpm=50, tpm=400_000),
    "ollama": ProviderLimits(rpm=120, tpm=10_000_000),
}


class ProviderRateLimiter:
    """
    Per-provider rate limiter for API calls.

    Enforces both RPM (requests per minute) and TPM (tokens per minute)
    limits to prevent API rate limit errors.
    """

    def __init__(self, defaults: dict[str, ProviderLimits] | None = None):
        """
        Initialize provider rate limiter.

        Args:
            defaults: Provider limit overrides (merged with DEFAULT_PROVIDER_LIMITS)
        """
        self._lock = threading.Lock()
        self._providers: dict[str, ProviderState] = {}

        # Initialize with defaults
        limits = dict(DEFAULT_PROVIDER_LIMITS)
        if defaults:
            limits.update(defaults)

        for provider, provider_limits in limits.items():
            self._providers[provider] = ProviderState(
                provider=provider,
                limits=provider_limits,
            )

    def configure(self, provider: str, limits: ProviderLimits) -> None:
        """Configure or update limits for a provider."""
        with self._lock:
            self._providers[provider] = ProviderState(
                provider=provider,
                limits=limits,
            )

    def acquire(self, provider: str, estimated_tokens: int = 0) -> bool:
        """
        Try to acquire permission to make an API call.

        Args:
            provider: Provider name
            estimated_tokens: Estimated token usage (for TPM check)

        Returns:
            True if allowed to proceed
        """
        with self._lock:
            state = self._providers.get(provider)
            if not state:
                return True  # Unknown provider = no limits

            # Check RPM
            if not state.request_bucket.acquire():
                state.blocked_requests += 1
                _logger.debug(f"Rate limit: {provider} RPM exceeded")
                return False

            # Check TPM (if estimated tokens provided)
            if estimated_tokens > 0 and not state.token_bucket.acquire(estimated_tokens):
                # Refund the request token
                state.request_bucket._tokens = min(
                    state.request_bucket.max_tokens,
                    state.request_bucket._tokens + 1,
                )
                state.blocked_requests += 1
                _logger.debug(f"Rate limit: {provider} TPM exceeded")
                return False

            state.total_requests += 1
            state.last_request_time = time.monotonic()
            return True

    def record_tokens(
        self,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record actual token usage after a call completes."""
        total = input_tokens + output_tokens
        with self._lock:
            state = self._providers.get(provider)
            if state:
                state.total_tokens += total

    def retry_after(self, provider: str) -> float:
        """Get recommended wait time before retrying."""
        with self._lock:
            state = self._providers.get(provider)
            if not state:
                return 0.0
            return state.request_bucket.wait_time()

    def get_state(self, provider: str) -> dict[str, Any] | None:
        """Get current rate limiting state for a provider."""
        with self._lock:
            state = self._providers.get(provider)
            return state.to_dict() if state else None

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get state for all providers."""
        with self._lock:
            return {name: state.to_dict() for name, state in self._providers.items()}

    def reset(self, provider: str | None = None) -> None:
        """Reset rate limiter state."""
        with self._lock:
            if provider:
                state = self._providers.get(provider)
                if state:
                    self._providers[provider] = ProviderState(
                        provider=provider,
                        limits=state.limits,
                    )
            else:
                for name, state in list(self._providers.items()):
                    self._providers[name] = ProviderState(
                        provider=name,
                        limits=state.limits,
                    )

    @property
    def providers(self) -> list[str]:
        """List configured providers."""
        return list(self._providers.keys())

    def to_dict(self) -> dict[str, Any]:
        """Export limiter state."""
        states = self.get_all_states()
        total_blocked = sum(s.get("blocked_requests", 0) for s in states.values())
        return {
            "provider_count": len(self._providers),
            "total_blocked_requests": total_blocked,
            "providers": states,
        }


# =============================================================================
# Security Rate Limiting (per-key)
# =============================================================================

DEFAULT_TOKENS_PER_SECOND = 10.0
DEFAULT_BUCKET_SIZE = 20
MAX_LIMITS = 500
MAX_KEYS_PER_LIMIT = 50000


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit."""

    name: str
    tokens_per_second: float = DEFAULT_TOKENS_PER_SECOND
    bucket_size: int = DEFAULT_BUCKET_SIZE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tokens_per_second": self.tokens_per_second,
            "bucket_size": self.bucket_size,
        }


@dataclass
class BucketState:
    """Internal state for a token bucket."""

    tokens: float
    last_refill: float
    total_allowed: int = 0
    total_denied: int = 0


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining_tokens: float = 0.0
    retry_after_seconds: float = 0.0
    limit_name: str = ""
    key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "remaining_tokens": round(self.remaining_tokens, 2),
            "retry_after_seconds": round(self.retry_after_seconds, 3),
            "limit_name": self.limit_name,
            "key": self.key,
        }


@dataclass
class LimiterStats:
    """Rate limiter statistics."""

    configured_limits: int
    total_keys: int
    total_allowed: int
    total_denied: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured_limits": self.configured_limits,
            "total_keys": self.total_keys,
            "total_allowed": self.total_allowed,
            "total_denied": self.total_denied,
        }


class SecurityRateLimiter:
    """
    Per-key rate limiter for security contexts.

    Features:
    - Per-key token bucket algorithm
    - Configurable rates and burst sizes
    - Multiple named limit tiers
    - Retry-after calculation
    - Statistics tracking
    - Thread-safe
    """

    def __init__(self):
        self._configs: dict[str, RateLimitConfig] = {}
        self._buckets: dict[str, dict[str, BucketState]] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        name: str,
        *,
        tokens_per_second: float = DEFAULT_TOKENS_PER_SECOND,
        bucket_size: int = DEFAULT_BUCKET_SIZE,
    ) -> RateLimitConfig:
        """Configure a named rate limit."""
        config = RateLimitConfig(
            name=name,
            tokens_per_second=tokens_per_second,
            bucket_size=bucket_size,
        )
        with self._lock:
            if len(self._configs) >= MAX_LIMITS and name not in self._configs:
                raise ValueError(f"Maximum limits ({MAX_LIMITS}) reached")
            self._configs[name] = config
            if name not in self._buckets:
                self._buckets[name] = {}
        return config

    def unconfigure(self, name: str) -> bool:
        """Remove a rate limit configuration."""
        with self._lock:
            if name not in self._configs:
                return False
            del self._configs[name]
            self._buckets.pop(name, None)
            return True

    def get_config(self, name: str) -> RateLimitConfig | None:
        """Get a rate limit configuration."""
        return self._configs.get(name)

    def list_configs(self) -> list[RateLimitConfig]:
        """List all configured rate limits."""
        return list(self._configs.values())

    def _refill(self, bucket: BucketState, config: RateLimitConfig, now: float) -> None:
        """Refill tokens based on elapsed time."""
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            new_tokens = elapsed * config.tokens_per_second
            bucket.tokens = min(config.bucket_size, bucket.tokens + new_tokens)
            bucket.last_refill = now

    def _get_or_create_bucket(self, limit_name: str, key: str, config: RateLimitConfig, now: float) -> BucketState:
        """Get or create a bucket for a key."""
        buckets = self._buckets.get(limit_name)
        if buckets is None:
            buckets = {}
            self._buckets[limit_name] = buckets

        bucket = buckets.get(key)
        if bucket is None:
            bucket = BucketState(
                tokens=float(config.bucket_size),
                last_refill=now,
            )
            buckets[key] = bucket
        return bucket

    def allow(self, limit_name: str, key: str, *, cost: float = 1.0) -> bool:
        """Check if a request is allowed under the rate limit."""
        result = self.check(limit_name, key, cost=cost)
        return result.allowed

    def check(self, limit_name: str, key: str, *, cost: float = 1.0) -> RateLimitResult:
        """Check rate limit and return detailed result."""
        with self._lock:
            config = self._configs.get(limit_name)
            if config is None:
                return RateLimitResult(
                    allowed=True,
                    limit_name=limit_name,
                    key=key,
                )

            now = time.monotonic()
            bucket = self._get_or_create_bucket(limit_name, key, config, now)
            self._refill(bucket, config, now)

            if bucket.tokens >= cost:
                bucket.tokens -= cost
                bucket.total_allowed += 1
                return RateLimitResult(
                    allowed=True,
                    remaining_tokens=bucket.tokens,
                    limit_name=limit_name,
                    key=key,
                )
            else:
                needed = cost - bucket.tokens
                retry_after = needed / config.tokens_per_second if config.tokens_per_second > 0 else 0.0
                bucket.total_denied += 1
                return RateLimitResult(
                    allowed=False,
                    remaining_tokens=bucket.tokens,
                    retry_after_seconds=retry_after,
                    limit_name=limit_name,
                    key=key,
                )

    def retry_after(self, limit_name: str, key: str, *, cost: float = 1.0) -> float:
        """Get seconds until the next request would be allowed."""
        result = self.check(limit_name, key, cost=cost)
        if result.allowed:
            return 0.0
        return result.retry_after_seconds

    def reset_key(self, limit_name: str, key: str) -> bool:
        """Reset a specific key's bucket to full."""
        with self._lock:
            config = self._configs.get(limit_name)
            if config is None:
                return False
            buckets = self._buckets.get(limit_name, {})
            if key not in buckets:
                return False
            buckets[key] = BucketState(
                tokens=float(config.bucket_size),
                last_refill=time.monotonic(),
            )
            return True

    def remaining(self, limit_name: str, key: str) -> float:
        """Get remaining tokens for a key."""
        with self._lock:
            config = self._configs.get(limit_name)
            if config is None:
                return 0.0
            buckets = self._buckets.get(limit_name, {})
            bucket = buckets.get(key)
            if bucket is None:
                return float(config.bucket_size)
            now = time.monotonic()
            self._refill(bucket, config, now)
            return bucket.tokens

    def get_stats(self) -> LimiterStats:
        """Get rate limiter statistics."""
        total_keys = 0
        total_allowed = 0
        total_denied = 0
        with self._lock:
            for buckets in self._buckets.values():
                total_keys += len(buckets)
                for bucket in buckets.values():
                    total_allowed += bucket.total_allowed
                    total_denied += bucket.total_denied
        return LimiterStats(
            configured_limits=len(self._configs),
            total_keys=total_keys,
            total_allowed=total_allowed,
            total_denied=total_denied,
        )

    @property
    def limit_count(self) -> int:
        return len(self._configs)

    def clear(self) -> None:
        """Clear all configurations and buckets."""
        with self._lock:
            self._configs.clear()
            self._buckets.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit_count": self.limit_count,
            "stats": self.get_stats().to_dict(),
        }


# Global security rate limiter singleton
_security_limiter: SecurityRateLimiter | None = None
_security_limiter_lock = threading.Lock()


def get_security_rate_limiter() -> SecurityRateLimiter:
    """Get or create the global security rate limiter."""
    global _security_limiter
    if _security_limiter is None:
        with _security_limiter_lock:
            if _security_limiter is None:
                _security_limiter = SecurityRateLimiter()
    return _security_limiter


def reset_security_rate_limiter() -> None:
    """Reset the global security rate limiter (for testing)."""
    global _security_limiter
    _security_limiter = None


# =============================================================================
# API Rate Limiting (async/sync support)
# =============================================================================


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded and timeout is reached."""

    pass


@dataclass
class APIRateLimitConfig:
    """Configuration for API rate limiting per provider."""

    requests_per_minute: int = 60
    burst_size: int = 10
    retry_after_seconds: float = 1.0


DEFAULT_API_LIMITS: dict[str, APIRateLimitConfig] = {
    "gemini": APIRateLimitConfig(requests_per_minute=60, burst_size=10),
    "claude": APIRateLimitConfig(requests_per_minute=50, burst_size=8),
    "default": APIRateLimitConfig(requests_per_minute=30, burst_size=5),
}


class APIRateLimiter:
    """
    Token bucket rate limiter for API calls with async/sync support.

    Thread-safe and async-safe implementation using both asyncio.Lock
    and threading.Lock for hybrid sync/async usage.
    """

    def __init__(self, requests_per_minute: int = 60, burst_size: int = 10, provider: str = "default"):
        """
        Initialize API rate limiter.

        Args:
            requests_per_minute: Maximum requests per minute
            burst_size: Maximum burst size (concurrent requests)
            provider: Provider name for logging
        """
        self.rpm = requests_per_minute
        self.burst = burst_size
        self.provider = provider

        # Token bucket state (deque for sliding window)
        self._tokens: deque[float] = deque(maxlen=burst_size)
        self._token_interval = 60.0 / requests_per_minute

        # Thread safety
        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

        # Statistics
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0

    def _refill_tokens(self) -> int:
        """Refill tokens based on elapsed time."""
        now = time.time()

        # Remove expired tokens (older than 60 seconds)
        while self._tokens and (now - self._tokens[0]) > 60.0:
            self._tokens.popleft()

        # Calculate available capacity
        current_tokens = len(self._tokens)
        available_capacity = self.burst - current_tokens

        return available_capacity

    def _try_acquire(self) -> bool:
        """Try to acquire a token without waiting."""
        now = time.time()

        # Refill and check capacity
        available = self._refill_tokens()

        if available > 0 or len(self._tokens) < self.burst:
            # Add new token timestamp
            self._tokens.append(now)
            self._total_requests += 1
            return True

        return False

    def _time_until_available(self) -> float:
        """Calculate time until a token will be available."""
        if not self._tokens:
            return 0.0

        # Oldest token will expire after 60 seconds
        oldest = self._tokens[0]
        now = time.time()
        time_until_expire = 60.0 - (now - oldest)

        return max(0.0, time_until_expire)

    async def acquire(self, timeout: float = 30.0) -> None:
        """Async acquire alias for acquire_async()."""
        await self.acquire_async(timeout)

    async def acquire_async(self, timeout: float = 30.0) -> None:
        """Acquire a rate limit token (async version)."""
        start_time = time.time()

        async with self._async_lock:
            while True:
                if self._try_acquire():
                    return

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    raise RateLimitExceeded(
                        f"Rate limit exceeded for {self.provider}. Waited {elapsed:.1f}s (timeout: {timeout}s)"
                    )

                # Calculate wait time
                wait_time = min(self._time_until_available(), timeout - elapsed, self._token_interval)

                self._total_waits += 1
                self._total_wait_time += wait_time

                await asyncio.sleep(wait_time)

    def acquire_sync(self, timeout: float = 30.0) -> None:
        """Acquire a rate limit token (sync version for ThreadPoolExecutor)."""
        start_time = time.time()

        with self._sync_lock:
            while True:
                if self._try_acquire():
                    return

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    raise RateLimitExceeded(
                        f"Rate limit exceeded for {self.provider}. Waited {elapsed:.1f}s (timeout: {timeout}s)"
                    )

                # Calculate wait time
                wait_time = min(self._time_until_available(), timeout - elapsed, self._token_interval)

                self._total_waits += 1
                self._total_wait_time += wait_time

                # Release lock while waiting
                self._sync_lock.release()
                try:
                    time.sleep(wait_time)
                finally:
                    self._sync_lock.acquire()

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        avg_wait = self._total_wait_time / self._total_waits if self._total_waits > 0 else 0.0

        return {
            "provider": self.provider,
            "rpm_limit": self.rpm,
            "burst_limit": self.burst,
            "total_requests": self._total_requests,
            "total_waits": self._total_waits,
            "total_wait_time": round(self._total_wait_time, 2),
            "avg_wait_time": round(avg_wait, 3),
            "current_bucket_size": len(self._tokens),
        }

    def reset(self) -> None:
        """Reset the rate limiter state and statistics."""
        with self._sync_lock:
            self._tokens.clear()
            self._total_requests = 0
            self._total_waits = 0
            self._total_wait_time = 0.0


class APIRateLimiterRegistry:
    """Registry of API rate limiters per provider (singleton pattern)."""

    _instance: APIRateLimiterRegistry | None = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._limiters: dict[str, APIRateLimiter] = {}
        return cls._instance

    def get_limiter(self, provider: str) -> APIRateLimiter:
        """Get or create API rate limiter for a provider."""
        if provider not in self._limiters:
            config = DEFAULT_API_LIMITS.get(provider, DEFAULT_API_LIMITS["default"])
            self._limiters[provider] = APIRateLimiter(
                requests_per_minute=config.requests_per_minute, burst_size=config.burst_size, provider=provider
            )
        return self._limiters[provider]

    def get_all_stats(self) -> dict[str, dict]:
        """Get statistics from all API rate limiters."""
        return {provider: limiter.get_stats() for provider, limiter in self._limiters.items()}

    def reset_all(self) -> None:
        """Reset all API rate limiters."""
        for limiter in self._limiters.values():
            limiter.reset()


def get_api_rate_limiter_registry() -> APIRateLimiterRegistry:
    """
    Get the API rate limiter registry.

    V10 PRISM: Returns tenant-scoped registry via ServiceFactory if available.
    Falls back to global singleton.
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_rate_limiter_registry()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    return APIRateLimiterRegistry()


def get_api_rate_limiter(provider: str) -> APIRateLimiter:
    """Convenience function to get API rate limiter for a provider."""
    return get_api_rate_limiter_registry().get_limiter(provider)
