"""
Tests for V12.4 Per-Provider Rate Limiter.

Validates:
- ProviderLimits configuration and defaults
- TokenBucket algorithm (acquire, refill, wait_time)
- RateLimiter per-provider rate limiting
- RPM enforcement (requests per minute)
- TPM enforcement (tokens per minute)
- Blocked request tracking
- Token recording
- Retry-after calculation
- Provider state reporting
- Reset functionality
- Module exports
"""

import time

from core.infrastructure.resilience.rate_limiter import (
    DEFAULT_LIMITS,
    ProviderLimits,
    ProviderState,
    RateLimiter,
    TokenBucket,
)

# =============================================================================
# ProviderLimits Tests
# =============================================================================


class TestProviderLimits:
    """Test provider limits configuration."""

    def test_defaults(self):
        limits = ProviderLimits()
        assert limits.rpm == 60
        assert limits.tpm == 1_000_000
        assert limits.max_burst > 0

    def test_custom(self):
        limits = ProviderLimits(rpm=30, tpm=500_000, max_burst=10)
        assert limits.rpm == 30
        assert limits.tpm == 500_000
        assert limits.max_burst == 10

    def test_auto_burst(self):
        limits = ProviderLimits(rpm=100)
        assert limits.max_burst == 20  # 100 // 5

    def test_min_burst(self):
        limits = ProviderLimits(rpm=1)
        assert limits.max_burst >= 1


# =============================================================================
# TokenBucket Tests
# =============================================================================


class TestTokenBucket:
    """Test token bucket algorithm."""

    def test_initial_full(self):
        bucket = TokenBucket(rate=10.0, max_tokens=100)
        assert bucket.available == 100.0

    def test_acquire_single(self):
        bucket = TokenBucket(rate=10.0, max_tokens=100)
        assert bucket.acquire() is True
        assert bucket.available < 100.0

    def test_acquire_multiple(self):
        bucket = TokenBucket(rate=10.0, max_tokens=100)
        assert bucket.acquire(50) is True
        assert bucket.available < 51.0

    def test_acquire_empty(self):
        bucket = TokenBucket(rate=1.0, max_tokens=2)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False  # Empty

    def test_refill_over_time(self):
        bucket = TokenBucket(rate=1000.0, max_tokens=1000)
        bucket.acquire(1000)
        assert bucket.available < 1.0
        time.sleep(0.01)  # 10ms * 1000/s = ~10 tokens
        assert bucket.available > 5.0

    def test_no_exceed_max(self):
        bucket = TokenBucket(rate=1000.0, max_tokens=10)
        time.sleep(0.1)
        assert bucket.available <= 10.0

    def test_wait_time_zero_when_available(self):
        bucket = TokenBucket(rate=10.0, max_tokens=100)
        assert bucket.wait_time() == 0.0

    def test_wait_time_positive_when_empty(self):
        bucket = TokenBucket(rate=10.0, max_tokens=2)
        bucket.acquire(2)
        wait = bucket.wait_time()
        assert wait > 0.0
        assert wait <= 0.2

    def test_zero_rate(self):
        bucket = TokenBucket(rate=0.0, max_tokens=1)
        bucket.acquire()
        assert bucket.wait_time() == float("inf")


# =============================================================================
# ProviderState Tests
# =============================================================================


class TestProviderState:
    """Test provider state tracking."""

    def test_creation(self):
        state = ProviderState(
            provider="gemini",
            limits=ProviderLimits(rpm=60, tpm=1_000_000),
        )
        assert state.provider == "gemini"
        assert state.total_requests == 0
        assert state.total_tokens == 0
        assert state.blocked_requests == 0

    def test_to_dict(self):
        state = ProviderState(
            provider="claude",
            limits=ProviderLimits(rpm=50, tpm=400_000),
        )
        d = state.to_dict()
        assert d["provider"] == "claude"
        assert d["rpm_limit"] == 50
        assert d["tpm_limit"] == 400_000
        assert "request_tokens_available" in d
        assert "token_tokens_available" in d


# =============================================================================
# RateLimiter - Initialization Tests
# =============================================================================


class TestRateLimiterInit:
    """Test rate limiter initialization."""

    def test_default_providers(self):
        limiter = RateLimiter()
        assert "gemini" in limiter.providers
        assert "claude" in limiter.providers
        assert "ollama" in limiter.providers

    def test_custom_defaults(self):
        limiter = RateLimiter(
            defaults={
                "custom_api": ProviderLimits(rpm=10, tpm=100_000),
            }
        )
        assert "custom_api" in limiter.providers
        assert "gemini" in limiter.providers

    def test_override_default(self):
        limiter = RateLimiter(
            defaults={
                "gemini": ProviderLimits(rpm=30, tpm=500_000),
            }
        )
        state = limiter.get_state("gemini")
        assert state["rpm_limit"] == 30


# =============================================================================
# RateLimiter - Acquire Tests
# =============================================================================


class TestAcquire:
    """Test request acquisition."""

    def test_basic_acquire(self):
        limiter = RateLimiter()
        assert limiter.acquire("gemini") is True

    def test_multiple_acquires(self):
        limiter = RateLimiter()
        for _ in range(10):
            assert limiter.acquire("gemini") is True

    def test_acquire_unknown_provider(self):
        limiter = RateLimiter()
        assert limiter.acquire("unknown") is True

    def test_rpm_exhaustion(self):
        limiter = RateLimiter(
            defaults={
                "test": ProviderLimits(rpm=5, tpm=1_000_000, max_burst=0),
            }
        )
        successes = 0
        for _ in range(20):
            if limiter.acquire("test"):
                successes += 1
        assert successes < 20
        assert successes >= 5

    def test_tpm_check(self):
        limiter = RateLimiter(
            defaults={
                "test": ProviderLimits(rpm=1000, tpm=100),
            }
        )
        assert limiter.acquire("test", estimated_tokens=100) is True
        assert limiter.acquire("test", estimated_tokens=100) is False

    def test_blocked_counter(self):
        limiter = RateLimiter(
            defaults={
                "test": ProviderLimits(rpm=2, tpm=1_000_000, max_burst=0),
            }
        )
        for _ in range(10):
            limiter.acquire("test")
        state = limiter.get_state("test")
        assert state["blocked_requests"] > 0

    def test_request_count_incremented(self):
        limiter = RateLimiter()
        limiter.acquire("gemini")
        limiter.acquire("gemini")
        state = limiter.get_state("gemini")
        assert state["total_requests"] == 2


# =============================================================================
# RateLimiter - Token Recording Tests
# =============================================================================


class TestTokenRecording:
    """Test token usage recording."""

    def test_record_tokens(self):
        limiter = RateLimiter()
        limiter.acquire("gemini")
        limiter.record_tokens("gemini", input_tokens=500, output_tokens=200)
        state = limiter.get_state("gemini")
        assert state["total_tokens"] == 700

    def test_record_accumulates(self):
        limiter = RateLimiter()
        limiter.record_tokens("claude", input_tokens=100, output_tokens=50)
        limiter.record_tokens("claude", input_tokens=200, output_tokens=100)
        state = limiter.get_state("claude")
        assert state["total_tokens"] == 450

    def test_record_unknown_provider(self):
        limiter = RateLimiter()
        limiter.record_tokens("unknown", input_tokens=100)  # No error


# =============================================================================
# RateLimiter - Retry After Tests
# =============================================================================


class TestRetryAfter:
    """Test retry-after calculation."""

    def test_no_wait_when_available(self):
        limiter = RateLimiter()
        assert limiter.retry_after("gemini") == 0.0

    def test_wait_when_exhausted(self):
        limiter = RateLimiter(
            defaults={
                "test": ProviderLimits(rpm=2, tpm=1_000_000, max_burst=0),
            }
        )
        for _ in range(10):
            limiter.acquire("test")
        wait = limiter.retry_after("test")
        assert wait > 0.0

    def test_unknown_provider_no_wait(self):
        limiter = RateLimiter()
        assert limiter.retry_after("unknown") == 0.0


# =============================================================================
# RateLimiter - State Reporting Tests
# =============================================================================


class TestStateReporting:
    """Test state and reporting."""

    def test_get_state(self):
        limiter = RateLimiter()
        state = limiter.get_state("gemini")
        assert state is not None
        assert state["provider"] == "gemini"
        assert "rpm_limit" in state
        assert "tpm_limit" in state

    def test_get_state_nonexistent(self):
        limiter = RateLimiter()
        assert limiter.get_state("missing") is None

    def test_get_all_states(self):
        limiter = RateLimiter()
        states = limiter.get_all_states()
        assert "gemini" in states
        assert "claude" in states

    def test_to_dict(self):
        limiter = RateLimiter()
        d = limiter.to_dict()
        assert d["provider_count"] >= 3
        assert "total_blocked_requests" in d
        assert "providers" in d


# =============================================================================
# RateLimiter - Configure Tests
# =============================================================================


class TestConfigure:
    """Test provider configuration."""

    def test_configure_new(self):
        limiter = RateLimiter()
        limiter.configure("openai", ProviderLimits(rpm=100, tpm=2_000_000))
        assert "openai" in limiter.providers
        state = limiter.get_state("openai")
        assert state["rpm_limit"] == 100

    def test_configure_override(self):
        limiter = RateLimiter()
        limiter.configure("gemini", ProviderLimits(rpm=30))
        state = limiter.get_state("gemini")
        assert state["rpm_limit"] == 30

    def test_configure_resets_counters(self):
        limiter = RateLimiter()
        limiter.acquire("gemini")
        limiter.record_tokens("gemini", input_tokens=100)
        limiter.configure("gemini", ProviderLimits(rpm=60))
        state = limiter.get_state("gemini")
        assert state["total_requests"] == 0
        assert state["total_tokens"] == 0


# =============================================================================
# RateLimiter - Reset Tests
# =============================================================================


class TestReset:
    """Test rate limiter reset."""

    def test_reset_specific(self):
        limiter = RateLimiter()
        limiter.acquire("gemini")
        limiter.record_tokens("gemini", input_tokens=100)
        limiter.acquire("claude")
        limiter.record_tokens("claude", input_tokens=200)

        limiter.reset("gemini")
        gemini = limiter.get_state("gemini")
        claude = limiter.get_state("claude")
        assert gemini["total_requests"] == 0
        assert claude["total_requests"] == 1

    def test_reset_all(self):
        limiter = RateLimiter()
        limiter.acquire("gemini")
        limiter.acquire("claude")
        limiter.reset()
        for provider in limiter.providers:
            state = limiter.get_state(provider)
            assert state["total_requests"] == 0

    def test_reset_preserves_limits(self):
        limiter = RateLimiter()
        limiter.configure("test", ProviderLimits(rpm=42))
        limiter.reset("test")
        state = limiter.get_state("test")
        assert state["rpm_limit"] == 42


# =============================================================================
# Default Limits Tests
# =============================================================================


class TestDefaultLimits:
    """Test default limit values."""

    def test_gemini_defaults(self):
        assert DEFAULT_LIMITS["gemini"].rpm == 60
        assert DEFAULT_LIMITS["gemini"].tpm == 1_000_000

    def test_claude_defaults(self):
        assert DEFAULT_LIMITS["claude"].rpm == 50
        assert DEFAULT_LIMITS["claude"].tpm == 400_000

    def test_ollama_defaults(self):
        assert DEFAULT_LIMITS["ollama"].rpm == 120
        assert DEFAULT_LIMITS["ollama"].tpm == 10_000_000


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_resilience_package(self):
        from core.infrastructure.resilience import ProviderLimits, RateLimiter, TokenBucket

        assert all([RateLimiter, ProviderLimits, TokenBucket])

    def test_from_module(self):
        from core.infrastructure.resilience.rate_limiter import (
            DEFAULT_LIMITS,
            ProviderLimits,
            ProviderState,
            RateLimiter,
            TokenBucket,
        )

        assert all([RateLimiter, ProviderLimits, ProviderState, TokenBucket])
        assert len(DEFAULT_LIMITS) >= 3
