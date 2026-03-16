"""
Tests for V12.4 Rate Limiter.

Validates:
- RateLimitConfig to_dict
- RateLimitResult to_dict
- LimiterStats to_dict
- Configure and unconfigure
- allow / check (basic, burst, denial, cost)
- retry_after calculation
- remaining tokens
- reset_key
- Multiple limits
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.security_pkg.security.rate_limiter import (
    DEFAULT_BUCKET_SIZE,
    DEFAULT_TOKENS_PER_SECOND,
    LimiterStats,
    RateLimitConfig,
    RateLimiter,
    RateLimitResult,
    get_rate_limiter,
    reset_rate_limiter,
)

# =============================================================================
# RateLimitConfig Tests
# =============================================================================


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_basic(self):
        c = RateLimitConfig(name="api")
        assert c.name == "api"
        assert c.tokens_per_second == DEFAULT_TOKENS_PER_SECOND
        assert c.bucket_size == DEFAULT_BUCKET_SIZE

    def test_custom(self):
        c = RateLimitConfig(name="strict", tokens_per_second=1.0, bucket_size=5)
        assert c.tokens_per_second == 1.0
        assert c.bucket_size == 5

    def test_to_dict(self):
        c = RateLimitConfig(name="api", tokens_per_second=5.0, bucket_size=10)
        d = c.to_dict()
        assert d["name"] == "api"
        assert d["tokens_per_second"] == 5.0
        assert d["bucket_size"] == 10


# =============================================================================
# RateLimitResult Tests
# =============================================================================


class TestRateLimitResult:
    """Test RateLimitResult dataclass."""

    def test_allowed(self):
        r = RateLimitResult(allowed=True, remaining_tokens=9.0)
        assert r.allowed is True

    def test_denied(self):
        r = RateLimitResult(allowed=False, retry_after_seconds=0.5)
        assert r.allowed is False
        assert r.retry_after_seconds == 0.5

    def test_to_dict(self):
        r = RateLimitResult(allowed=True, remaining_tokens=5.5, limit_name="api", key="u1")
        d = r.to_dict()
        assert d["allowed"] is True
        assert d["remaining_tokens"] == 5.5
        assert d["limit_name"] == "api"


# =============================================================================
# LimiterStats Tests
# =============================================================================


class TestLimiterStats:
    """Test LimiterStats dataclass."""

    def test_to_dict(self):
        s = LimiterStats(configured_limits=2, total_keys=10, total_allowed=100, total_denied=5)
        d = s.to_dict()
        assert d["configured_limits"] == 2
        assert d["total_allowed"] == 100
        assert d["total_denied"] == 5


# =============================================================================
# Configure Tests
# =============================================================================


class TestConfigure:
    """Test limit configuration."""

    def test_configure(self):
        rl = RateLimiter()
        config = rl.configure("api", tokens_per_second=5.0, bucket_size=10)
        assert config.name == "api"
        assert rl.limit_count == 1

    def test_configure_defaults(self):
        rl = RateLimiter()
        config = rl.configure("default")
        assert config.tokens_per_second == DEFAULT_TOKENS_PER_SECOND
        assert config.bucket_size == DEFAULT_BUCKET_SIZE

    def test_reconfigure(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=5.0)
        rl.configure("api", tokens_per_second=10.0)
        config = rl.get_config("api")
        assert config.tokens_per_second == 10.0

    def test_unconfigure(self):
        rl = RateLimiter()
        rl.configure("api")
        assert rl.unconfigure("api") is True
        assert rl.limit_count == 0

    def test_unconfigure_not_found(self):
        rl = RateLimiter()
        assert rl.unconfigure("missing") is False

    def test_get_config(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=5.0)
        config = rl.get_config("api")
        assert config is not None
        assert config.tokens_per_second == 5.0

    def test_get_config_not_found(self):
        rl = RateLimiter()
        assert rl.get_config("missing") is None

    def test_list_configs(self):
        rl = RateLimiter()
        rl.configure("api")
        rl.configure("tools")
        configs = rl.list_configs()
        assert len(configs) == 2


# =============================================================================
# Allow / Check Tests
# =============================================================================


class TestAllow:
    """Test rate limiting."""

    def test_allow_basic(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=10.0, bucket_size=10)
        assert rl.allow("api", "user1") is True

    def test_allow_unconfigured_limit(self):
        rl = RateLimiter()
        assert rl.allow("nonexistent", "user1") is True

    def test_allow_burst(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=1.0, bucket_size=5)
        for _ in range(5):
            assert rl.allow("api", "user1") is True

    def test_deny_after_burst(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=3)
        for _ in range(3):
            assert rl.allow("api", "user1") is True
        assert rl.allow("api", "user1") is False

    def test_allow_with_cost(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=1.0, bucket_size=10)
        assert rl.allow("api", "user1", cost=5.0) is True
        assert rl.allow("api", "user1", cost=5.0) is True
        assert rl.allow("api", "user1", cost=1.0) is False

    def test_check_result_allowed(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=10.0, bucket_size=10)
        result = rl.check("api", "user1")
        assert result.allowed is True
        assert result.remaining_tokens == 9.0
        assert result.limit_name == "api"
        assert result.key == "user1"

    def test_check_result_denied(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=1)
        rl.check("api", "user1")
        result = rl.check("api", "user1")
        assert result.allowed is False
        assert result.retry_after_seconds > 0

    def test_separate_keys(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=2)
        rl.allow("api", "user1")
        rl.allow("api", "user1")
        assert rl.allow("api", "user1") is False
        assert rl.allow("api", "user2") is True

    def test_separate_limits(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=1)
        rl.configure("tools", tokens_per_second=0.001, bucket_size=1)
        rl.allow("api", "user1")
        assert rl.allow("api", "user1") is False
        assert rl.allow("tools", "user1") is True


# =============================================================================
# Retry After Tests
# =============================================================================


class TestRetryAfter:
    """Test retry_after calculation."""

    def test_retry_after_when_allowed(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=10.0, bucket_size=10)
        assert rl.retry_after("api", "user1") == 0.0

    def test_retry_after_when_denied(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=1.0, bucket_size=1)
        rl.allow("api", "user1")
        wait = rl.retry_after("api", "user1")
        assert wait > 0


# =============================================================================
# Remaining Tests
# =============================================================================


class TestRemaining:
    """Test remaining tokens."""

    def test_remaining_full(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=10.0, bucket_size=10)
        assert rl.remaining("api", "new_user") == 10.0

    def test_remaining_after_use(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=10)
        rl.allow("api", "user1")
        remaining = rl.remaining("api", "user1")
        assert 8.9 < remaining < 9.1

    def test_remaining_unconfigured(self):
        rl = RateLimiter()
        assert rl.remaining("missing", "user1") == 0.0


# =============================================================================
# Reset Key Tests
# =============================================================================


class TestResetKey:
    """Test key reset."""

    def test_reset_key(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=5)
        for _ in range(5):
            rl.allow("api", "user1")
        assert rl.allow("api", "user1") is False
        assert rl.reset_key("api", "user1") is True
        assert rl.allow("api", "user1") is True

    def test_reset_key_not_found(self):
        rl = RateLimiter()
        assert rl.reset_key("missing", "user1") is False

    def test_reset_key_unknown_key(self):
        rl = RateLimiter()
        rl.configure("api")
        assert rl.reset_key("api", "never_seen") is False


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test limiter statistics."""

    def test_initial_stats(self):
        rl = RateLimiter()
        stats = rl.get_stats()
        assert stats.configured_limits == 0
        assert stats.total_keys == 0

    def test_stats_after_work(self):
        rl = RateLimiter()
        rl.configure("api", tokens_per_second=0.001, bucket_size=2)
        rl.allow("api", "user1")
        rl.allow("api", "user1")
        rl.allow("api", "user1")  # Denied
        stats = rl.get_stats()
        assert stats.configured_limits == 1
        assert stats.total_keys == 1
        assert stats.total_allowed == 2
        assert stats.total_denied == 1

    def test_stats_to_dict(self):
        rl = RateLimiter()
        d = rl.get_stats().to_dict()
        assert "configured_limits" in d
        assert "total_allowed" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_limit_count(self):
        rl = RateLimiter()
        rl.configure("a")
        rl.configure("b")
        assert rl.limit_count == 2

    def test_clear(self):
        rl = RateLimiter()
        rl.configure("api")
        rl.allow("api", "user1")
        rl.clear()
        assert rl.limit_count == 0

    def test_to_dict(self):
        rl = RateLimiter()
        rl.configure("api")
        d = rl.to_dict()
        assert d["limit_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global rate limiter."""

    def test_get(self):
        reset_rate_limiter()
        rl = get_rate_limiter()
        assert isinstance(rl, RateLimiter)

    def test_singleton(self):
        reset_rate_limiter()
        r1 = get_rate_limiter()
        r2 = get_rate_limiter()
        assert r1 is r2

    def test_reset(self):
        reset_rate_limiter()
        r1 = get_rate_limiter()
        reset_rate_limiter()
        r2 = get_rate_limiter()
        assert r1 is not r2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_security_package(self):
        from core.security_pkg.security import (
            LimiterStats,
            RateLimitConfig,
            RateLimiter,
            RateLimitResult,
            get_rate_limiter,
            reset_rate_limiter,
        )

        assert all(
            [
                RateLimiter,
                RateLimitConfig,
                RateLimitResult,
                LimiterStats,
                get_rate_limiter,
                reset_rate_limiter,
            ]
        )

    def test_from_module(self):
        from core.security_pkg.security.rate_limiter import (
            DEFAULT_BUCKET_SIZE,
            DEFAULT_TOKENS_PER_SECOND,
        )

        assert DEFAULT_TOKENS_PER_SECOND == 10.0
        assert DEFAULT_BUCKET_SIZE == 20
