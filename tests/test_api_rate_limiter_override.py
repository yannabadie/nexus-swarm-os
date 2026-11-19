"""
Tests for APIRateLimiterRegistry.limits_override().

Offline simulations (such as the swarm evaluation harness) play "providers" that are not real APIs, so
production quotas must not throttle them. limits_override() gives chosen provider keys their own capacity
for the duration of a block and restores the previous limiters afterwards.
"""

import pytest

from core.infrastructure.resilience.unified_rate_limiter import (
    DEFAULT_API_LIMITS,
    APIRateLimitConfig,
    APIRateLimiterRegistry,
)

SIMULATED = APIRateLimitConfig(requests_per_minute=600_000, burst_size=1_000)


@pytest.fixture
def registry():
    """The process-wide registry, with the provider keys used here removed before and after each test."""
    reg = APIRateLimiterRegistry()
    keys = ("sim-agent-a", "sim-agent-b", "sim-existing")
    for key in keys:
        reg._limiters.pop(key, None)
    yield reg
    for key in keys:
        reg._limiters.pop(key, None)


def test_unknown_provider_gets_the_default_quota(registry):
    """Baseline: without an override an unknown provider is limited like 'default'."""
    limiter = registry.get_limiter("sim-agent-a")
    assert limiter.rpm == DEFAULT_API_LIMITS["default"].requests_per_minute
    assert limiter.burst == DEFAULT_API_LIMITS["default"].burst_size


def test_override_applies_the_given_quota(registry):
    with registry.limits_override({"sim-agent-a": SIMULATED}):
        limiter = registry.get_limiter("sim-agent-a")
        assert limiter.rpm == SIMULATED.requests_per_minute
        assert limiter.burst == SIMULATED.burst_size


def test_override_is_not_a_throttle_for_a_burst_of_calls(registry):
    """Many sequential acquisitions go through the normal limiter code path without waiting."""
    with registry.limits_override({"sim-agent-a": SIMULATED}):
        limiter = registry.get_limiter("sim-agent-a")
        for _ in range(200):
            limiter.acquire_sync(timeout=1.0)
        stats = limiter.get_stats()
    assert stats["total_requests"] == 200
    assert stats["total_waits"] == 0


def test_override_removes_limiters_that_did_not_exist_before(registry):
    with registry.limits_override({"sim-agent-a": SIMULATED, "sim-agent-b": SIMULATED}):
        assert "sim-agent-a" in registry._limiters
    assert "sim-agent-a" not in registry._limiters
    assert "sim-agent-b" not in registry._limiters
    # and a fresh limiter is the default one again
    assert registry.get_limiter("sim-agent-a").rpm == DEFAULT_API_LIMITS["default"].requests_per_minute


def test_override_restores_the_previous_limiter_object_and_its_state(registry):
    original = registry.get_limiter("sim-existing")
    original.acquire_sync(timeout=1.0)
    used_before = original.get_stats()["total_requests"]

    with registry.limits_override({"sim-existing": SIMULATED}):
        assert registry.get_limiter("sim-existing") is not original

    assert registry.get_limiter("sim-existing") is original
    assert original.get_stats()["total_requests"] == used_before


def test_override_restores_even_when_the_block_raises(registry):
    original = registry.get_limiter("sim-existing")
    with (
        pytest.raises(RuntimeError, match="boom"),
        registry.limits_override({"sim-existing": SIMULATED, "sim-agent-a": SIMULATED}),
    ):
        raise RuntimeError("boom")
    assert registry.get_limiter("sim-existing") is original
    assert "sim-agent-a" not in registry._limiters
