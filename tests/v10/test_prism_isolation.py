"""
PRISM Isolation Tests - Multi-Tenant Data Isolation Verification.

NEXUS V10 - OPERATION PRISM

These tests verify that the multi-tenant architecture properly
isolates data between tenants. A failure here means potential
data bleeding between customers - CRITICAL for SaaS.

Test Scenarios:
1. Context isolation - Different tenants get different contexts
2. ServiceFactory isolation - Services are scoped per-tenant
3. Async isolation - Concurrent async tasks maintain isolation
4. Budget isolation - Spending is tracked per-tenant
5. Path isolation - File paths are tenant-scoped

Run with:
    pytest tests/v10/test_prism_isolation.py -v

Author: Claude (NEXUS PRISM V10)
Date: 2025-12-15
"""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

# Add NEXUS root to path
NEXUS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(NEXUS_ROOT))


class TestSessionContext:
    """Tests for core/context/session.py"""

    def test_context_creation(self):
        """SessionContext can be created with required fields."""
        from core.infrastructure.context import SessionContext

        ctx = SessionContext(tenant_id="acme")
        assert ctx.tenant_id == "acme"
        assert ctx.user_id == "anonymous"
        assert ctx.workspace_id == "default"

    def test_context_immutable(self):
        """SessionContext is immutable (frozen dataclass)."""
        from core.infrastructure.context import SessionContext

        ctx = SessionContext(tenant_id="acme")

        with pytest.raises(AttributeError):
            ctx.tenant_id = "other"

    def test_context_requires_tenant_id(self):
        """SessionContext raises ValueError without tenant_id."""
        from core.infrastructure.context import SessionContext

        with pytest.raises(ValueError, match="tenant_id is required"):
            SessionContext(tenant_id="")

    def test_use_context_sets_and_resets(self):
        """use_context properly sets and resets context."""
        from core.infrastructure.context import (
            get_current_session,
            get_current_session_or_none,
            use_context,
        )

        # Before context
        assert get_current_session_or_none() is None

        # Inside context
        with use_context(tenant_id="acme", user_id="alice"):
            ctx = get_current_session()
            assert ctx.tenant_id == "acme"
            assert ctx.user_id == "alice"

        # After context
        assert get_current_session_or_none() is None

    def test_nested_contexts(self):
        """Nested contexts work correctly."""
        from core.infrastructure.context import get_current_session, use_context

        with use_context(tenant_id="outer"):
            outer_ctx = get_current_session()
            assert outer_ctx.tenant_id == "outer"

            with use_context(tenant_id="inner"):
                inner_ctx = get_current_session()
                assert inner_ctx.tenant_id == "inner"

            # Restored to outer
            restored_ctx = get_current_session()
            assert restored_ctx.tenant_id == "outer"

    def test_get_current_session_raises_without_context(self):
        """get_current_session raises RuntimeError without active context."""
        from core.infrastructure.context import current_session, get_current_session

        # Ensure no context
        current_session.set(None)

        with pytest.raises(RuntimeError, match="No session context active"):
            get_current_session()


class TestServiceFactoryIsolation:
    """Tests for ServiceFactory tenant isolation."""

    def setup_method(self):
        """Clear factory cache before each test."""
        from core.factory import ServiceFactory

        ServiceFactory.clear_all_caches()

    def test_registry_isolation(self):
        """Different tenants get different registry instances."""
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context

        with use_context(tenant_id="tenant_a"):
            registry_a = ServiceFactory.get_registry()

        with use_context(tenant_id="tenant_b"):
            registry_b = ServiceFactory.get_registry()

        # Different instances
        assert registry_a is not registry_b

    def test_same_tenant_gets_same_instance(self):
        """Same tenant gets cached instance."""
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context

        with use_context(tenant_id="acme"):
            registry_1 = ServiceFactory.get_registry()
            registry_2 = ServiceFactory.get_registry()

        # Same instance (cached)
        assert registry_1 is registry_2

    def test_workspace_path_isolation(self):
        """Different tenants get different workspace paths."""
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context

        ServiceFactory.initialize(NEXUS_ROOT)

        with use_context(tenant_id="alpha"):
            path_alpha = ServiceFactory.get_tenant_workspace_path()

        with use_context(tenant_id="beta"):
            path_beta = ServiceFactory.get_tenant_workspace_path()

        assert "alpha" in str(path_alpha)
        assert "beta" in str(path_beta)
        assert path_alpha != path_beta

    def test_cache_clear_per_tenant(self):
        """Clearing one tenant doesn't affect others."""
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context

        # Create instances for both tenants
        with use_context(tenant_id="tenant_a"):
            registry_a1 = ServiceFactory.get_registry()

        with use_context(tenant_id="tenant_b"):
            registry_b1 = ServiceFactory.get_registry()

        # Clear only tenant_a
        ServiceFactory.clear_tenant_cache("tenant_a")

        # tenant_b still has cached instance
        with use_context(tenant_id="tenant_b"):
            registry_b2 = ServiceFactory.get_registry()
            assert registry_b1 is registry_b2

        # tenant_a gets new instance
        with use_context(tenant_id="tenant_a"):
            registry_a2 = ServiceFactory.get_registry()
            assert registry_a1 is not registry_a2


class TestAsyncIsolation:
    """Tests for async context isolation."""

    @pytest.mark.asyncio
    async def test_async_context_isolation(self):
        """Async tasks maintain isolated contexts."""
        from core.infrastructure.context import get_current_session, use_context_async

        results = {}

        async def task_a():
            async with use_context_async(tenant_id="alpha"):
                await asyncio.sleep(0.01)  # Simulate async work
                results["a"] = get_current_session().tenant_id

        async def task_b():
            async with use_context_async(tenant_id="beta"):
                await asyncio.sleep(0.01)
                results["b"] = get_current_session().tenant_id

        # Run concurrently
        await asyncio.gather(task_a(), task_b())

        # Each task saw its own context
        assert results["a"] == "alpha"
        assert results["b"] == "beta"

    @pytest.mark.asyncio
    async def test_concurrent_factory_calls(self):
        """Concurrent ServiceFactory calls get correct instances."""
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context_async

        ServiceFactory.clear_all_caches()
        instances = {}

        async def get_registry_for_tenant(tenant_id: str):
            async with use_context_async(tenant_id=tenant_id):
                await asyncio.sleep(0.01)
                instances[tenant_id] = ServiceFactory.get_registry()

        # Run 3 concurrent tasks
        await asyncio.gather(
            get_registry_for_tenant("t1"),
            get_registry_for_tenant("t2"),
            get_registry_for_tenant("t3"),
        )

        # All different instances
        assert instances["t1"] is not instances["t2"]
        assert instances["t2"] is not instances["t3"]
        assert instances["t1"] is not instances["t3"]


class TestThreadIsolation:
    """Tests for thread isolation."""

    def test_thread_isolation(self):
        """Different threads with contexts are isolated."""
        from core.infrastructure.context import get_current_session_or_none, use_context

        results = {}
        errors = []

        def thread_task(tenant_id: str):
            try:
                with use_context(tenant_id=tenant_id):
                    # Simulate some work
                    import time

                    time.sleep(0.01)

                    ctx = get_current_session_or_none()
                    if ctx:
                        results[tenant_id] = ctx.tenant_id
                    else:
                        errors.append(f"No context for {tenant_id}")
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=thread_task, args=("thread_a",)),
            threading.Thread(target=thread_task, args=("thread_b",)),
            threading.Thread(target=thread_task, args=("thread_c",)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert results.get("thread_a") == "thread_a"
        assert results.get("thread_b") == "thread_b"
        assert results.get("thread_c") == "thread_c"


class TestDatabaseModels:
    """Tests for core/db models."""

    @pytest.fixture(autouse=True)
    def skip_if_no_sqlmodel(self):
        """Skip tests if sqlmodel is not installed."""
        pytest.importorskip("sqlmodel")

    def test_tenant_creation(self):
        """Tenant model can be created."""
        from core.infrastructure.db import PlanTier, Tenant

        tenant = Tenant(name="Acme Corp", slug="acme")
        assert tenant.name == "Acme Corp"
        assert tenant.slug == "acme"
        assert tenant.plan_tier == PlanTier.FREE

    def test_quota_defaults_by_plan(self):
        """Quota defaults vary by plan tier."""
        from uuid import uuid4

        from core.infrastructure.db import PlanTier, create_quota_for_plan

        tenant_id = uuid4()

        free_quota = create_quota_for_plan(tenant_id, PlanTier.FREE)
        pro_quota = create_quota_for_plan(tenant_id, PlanTier.PRO)
        enterprise_quota = create_quota_for_plan(tenant_id, PlanTier.ENTERPRISE)

        # Free has lowest limits
        assert free_quota.daily_budget_usd < pro_quota.daily_budget_usd
        assert pro_quota.daily_budget_usd < enterprise_quota.daily_budget_usd

        # Feature flags
        assert not free_quota.hive_mind_enabled
        assert pro_quota.hive_mind_enabled
        assert enterprise_quota.evolution_enabled

    def test_quota_budget_checks(self):
        """Quota budget checking methods work."""
        from uuid import uuid4

        from core.infrastructure.db import Quota

        quota = Quota(
            tenant_id=uuid4(),
            daily_budget_usd=50.0,
            current_spend_usd=45.0,
        )

        assert not quota.is_over_daily_budget()
        assert quota.remaining_daily_budget() == 5.0

        quota.current_spend_usd = 55.0
        assert quota.is_over_daily_budget()
        assert quota.remaining_daily_budget() == 0.0


class TestBackwardCompatibility:
    """Tests for backward compatibility during migration."""

    def test_default_tenant_context(self):
        """Default context works for single-tenant mode."""
        from core.infrastructure.context import DEFAULT_TENANT_ID, get_default_context

        ctx = get_default_context()
        assert ctx.tenant_id == DEFAULT_TENANT_ID
        assert ctx.workspace_id == "default"

    def test_ensure_context_creates_default(self):
        """ensure_context creates default if none exists."""
        from core.infrastructure.context import (
            DEFAULT_TENANT_ID,
            current_session,
            ensure_context,
        )

        # Reset
        current_session.set(None)

        ctx = ensure_context()
        assert ctx.tenant_id == DEFAULT_TENANT_ID

        # Cleanup
        current_session.set(None)


class TestPathGuardianIntegration:
    """Tests for PathGuardian with tenant context."""

    def test_path_guardian_from_factory(self):
        """ServiceFactory creates PathGuardian with correct paths."""
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context

        ServiceFactory.initialize(NEXUS_ROOT)

        with use_context(tenant_id="secure_tenant"):
            guardian = ServiceFactory.get_path_guardian()

            # Workspace should be tenant-scoped
            assert "secure_tenant" in str(guardian.workspace)


# =============================================================================
# CRITICAL ISOLATION TEST
# =============================================================================


class TestCriticalIsolation:
    """
    CRITICAL: These tests verify no data bleeding between tenants.

    A failure here is a SECURITY ISSUE.
    """

    def test_no_cross_tenant_registry_access(self):
        """
        CRITICAL: Tenant A cannot access Tenant B's registered agents.
        """
        from core.factory import ServiceFactory
        from core.foundation.agents.unified_registry import AgentDescriptor, AgentProvider
        from core.infrastructure.context import use_context

        ServiceFactory.clear_all_caches()

        # Tenant A registers an agent
        with use_context(tenant_id="tenant_a"):
            registry_a = ServiceFactory.get_registry()
            registry_a.register(
                AgentDescriptor(
                    id="secret_agent_a",
                    provider=AgentProvider.SPAWNED,
                    display_name="Secret Agent A",
                )
            )

        # Tenant B should NOT see it
        with use_context(tenant_id="tenant_b"):
            registry_b = ServiceFactory.get_registry()
            agent = registry_b.get("secret_agent_a")
            assert agent is None, "SECURITY: Tenant B saw Tenant A's agent!"

    def test_no_cross_tenant_service_sharing(self):
        """
        CRITICAL: Services are never shared between tenants.
        """
        from core.factory import ServiceFactory
        from core.infrastructure.context import use_context

        ServiceFactory.clear_all_caches()

        services_a = []
        services_b = []

        with use_context(tenant_id="tenant_a"):
            services_a.append(ServiceFactory.get_registry())
            services_a.append(ServiceFactory.get_tool_registry())

        with use_context(tenant_id="tenant_b"):
            services_b.append(ServiceFactory.get_registry())
            services_b.append(ServiceFactory.get_tool_registry())

        # No service should be shared
        for svc_a in services_a:
            for svc_b in services_b:
                assert svc_a is not svc_b, "SECURITY: Shared service detected!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
