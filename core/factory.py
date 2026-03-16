"""
ServiceFactory - Context-Aware Service Instantiation.

NEXUS V10 PRISM - The Singleton Massacre

This module replaces global singletons with context-scoped instances.
Instead of:
    _registry = AgentRegistry()  # Global, shared by all tenants

We now have:
    registry = ServiceFactory.get_registry()  # Scoped to current tenant

Architecture:
    ServiceFactory maintains per-tenant instance caches:
    {
        "tenant_001": {
            "registry": AgentRegistry(...),
            "workspace_manager": SessionWorkspaceManager(...),
            ...
        },
        "tenant_002": {
            "registry": AgentRegistry(...),
            ...
        }
    }

Thread Safety:
    - Uses RLock for thread-safe instance creation
    - ContextVars ensure correct tenant lookup
    - Cache keys include tenant_id for isolation

Usage:
    from core.infrastructure.context import use_context
    from core.factory import ServiceFactory

    with use_context(tenant_id="acme"):
        # All services are scoped to "acme" tenant
        registry = ServiceFactory.get_registry()
        workspace = ServiceFactory.get_workspace_manager()
        tools = ServiceFactory.get_tool_registry()

Author: Claude (NEXUS PRISM V10)
Date: 2025-12-15
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, TypeVar

from .infrastructure.context import (
    DEFAULT_TENANT_ID,
    SessionContext,
    get_current_session_or_none,
)

T = TypeVar("T")


class ServiceFactory:
    """
    Factory for creating and caching context-scoped service instances.

    Replaces global singletons with tenant-isolated instances.
    Each tenant gets their own set of services, preventing data bleeding.

    Thread-safe with per-tenant instance caching.
    """

    # Instance cache: {tenant_id: {service_name: instance}}
    _instances: dict[str, dict[str, Any]] = {}
    _lock = threading.RLock()

    # NEXUS root path (set during initialization)
    _nexus_root: Path | None = None

    @classmethod
    def initialize(cls, nexus_root: Path) -> None:
        """
        Initialize the factory with NEXUS root path.

        Must be called once at startup before using the factory.

        Args:
            nexus_root: Path to NEXUS installation root
        """
        cls._nexus_root = nexus_root.resolve()

    @classmethod
    def get_nexus_root(cls) -> Path:
        """Get the NEXUS root path."""
        if cls._nexus_root is None:
            # Fallback: try to detect from current file
            cls._nexus_root = Path(__file__).parent.parent.resolve()
        return cls._nexus_root

    @classmethod
    def _get_tenant_cache(cls, tenant_id: str) -> dict[str, Any]:
        """Get or create the instance cache for a tenant."""
        with cls._lock:
            if tenant_id not in cls._instances:
                cls._instances[tenant_id] = {}
            return cls._instances[tenant_id]

    @classmethod
    def _get_or_create(cls, service_name: str, factory_func, ctx: SessionContext | None = None) -> Any:
        """
        Get or create a service instance for the current context.

        Args:
            service_name: Unique name for the service
            factory_func: Callable that creates the service instance
            ctx: Optional explicit context (uses current if not provided)

        Returns:
            Service instance scoped to the tenant
        """
        if ctx is None:
            ctx = get_current_session_or_none()

        # Fallback to default tenant if no context
        tenant_id = ctx.tenant_id if ctx else DEFAULT_TENANT_ID

        cache = cls._get_tenant_cache(tenant_id)

        with cls._lock:
            if service_name not in cache:
                cache[service_name] = factory_func(ctx)

        return cache[service_name]

    @classmethod
    def get_tenant_workspace_path(cls, ctx: SessionContext | None = None) -> Path:
        """
        Get the workspace path for the current tenant.

        Args:
            ctx: Optional explicit context

        Returns:
            Path to data/tenants/{tenant_id}/workspaces/{workspace_id}/
        """
        if ctx is None:
            ctx = get_current_session_or_none()

        if ctx and ctx.workspace_root:
            return ctx.workspace_root

        # Compute path from context
        nexus_root = cls.get_nexus_root()

        if ctx:
            return nexus_root / "data" / "tenants" / ctx.tenant_id / "workspaces" / ctx.workspace_id

        # Fallback to legacy workspace
        return nexus_root / "workspace"

    # =========================================================================
    # SERVICE GETTERS
    # =========================================================================

    @classmethod
    def get_registry(cls, ctx: SessionContext | None = None):
        """
        Get the agent registry for the current tenant.

        Returns:
            UnifiedAgentRegistry instance
        """

        def factory(ctx: SessionContext | None):
            from .foundation.agents.unified_registry import UnifiedAgentRegistry

            return UnifiedAgentRegistry()

        return cls._get_or_create("registry", factory, ctx)

    @classmethod
    def get_workspace_manager(cls, ctx: SessionContext | None = None):
        """
        Get the workspace manager for the current tenant.

        Returns:
            SessionWorkspaceManager instance
        """

        def factory(ctx: SessionContext | None):
            from .infrastructure.session.workspace_manager import SessionWorkspaceManager

            workspace_path = cls.get_tenant_workspace_path(ctx)
            return SessionWorkspaceManager(workspace_path)

        return cls._get_or_create("workspace_manager", factory, ctx)

    @classmethod
    def get_tool_registry(cls, ctx: SessionContext | None = None):
        """
        Get the tool registry for the current tenant.

        Returns:
            ToolRegistry instance
        """

        def factory(ctx: SessionContext | None):
            from .execution_pkg.execution.tool_registry import ToolRegistry

            return ToolRegistry()

        return cls._get_or_create("tool_registry", factory, ctx)

    @classmethod
    def get_rate_limiter_registry(cls, ctx: SessionContext | None = None):
        """
        Get the rate limiter registry for the current tenant.

        Each tenant has their own rate limits to prevent
        one tenant from blocking others.

        Returns:
            RateLimiterRegistry instance
        """

        def factory(ctx: SessionContext | None):
            from .api.rate_limiter import RateLimiterRegistry

            # Create a new registry (not the global singleton)
            registry = object.__new__(RateLimiterRegistry)
            registry._limiters = {}
            return registry

        return cls._get_or_create("rate_limiter_registry", factory, ctx)

    @classmethod
    def get_interaction_provider(cls, ctx: SessionContext | None = None):
        """
        Get the interaction provider for the current tenant.

        Returns:
            InteractionProvider instance
        """

        def factory(ctx: SessionContext | None):
            import os

            from .security_pkg.interaction import CLIProvider, HeadlessProvider

            mode = os.environ.get("NEXUS_INTERACTION_MODE", "cli").lower()

            if mode == "headless":
                return HeadlessProvider(strict=False)
            elif mode == "strict":
                return HeadlessProvider(strict=True)
            else:
                return CLIProvider()

        return cls._get_or_create("interaction_provider", factory, ctx)

    @classmethod
    def get_execution_engine(cls, ctx: SessionContext | None = None):
        """
        Get the execution engine for the current tenant.

        Returns:
            ExecutionEngine instance
        """

        def factory(ctx: SessionContext | None):
            from .execution_pkg.execution.execution_engine import ExecutionEngine

            workspace_path = cls.get_tenant_workspace_path(ctx)
            return ExecutionEngine(workspace_path)

        return cls._get_or_create("execution_engine", factory, ctx)

    @classmethod
    def get_system_health(cls, ctx: SessionContext | None = None):
        """
        Get the system health monitor for the current tenant.

        Returns:
            SystemHealth instance
        """

        def factory(ctx: SessionContext | None):
            from .infrastructure.resilience.system_health import SystemHealth

            workspace_path = cls.get_tenant_workspace_path(ctx)
            return SystemHealth(workspace_path)

        return cls._get_or_create("system_health", factory, ctx)

    @classmethod
    def get_budget_tracker(cls, ctx: SessionContext | None = None):
        """
        Get the budget tracker for the current tenant.

        Returns:
            BudgetTracker instance
        """

        def factory(ctx: SessionContext | None):
            from .observability.telemetry.budget_tracker import BudgetTracker

            workspace_path = cls.get_tenant_workspace_path(ctx)
            return BudgetTracker(workspace_path)

        return cls._get_or_create("budget_tracker", factory, ctx)

    @classmethod
    def get_path_guardian(cls, ctx: SessionContext | None = None):
        """
        Get the path guardian for the current tenant.

        PathGuardian validates file operations are within allowed zones.

        Returns:
            PathGuardian instance
        """

        def factory(ctx: SessionContext | None):
            from .security_pkg.security.path_guardian import PathGuardian

            workspace_path = cls.get_tenant_workspace_path(ctx)
            nexus_root = cls.get_nexus_root()
            return PathGuardian(
                workspace_path=workspace_path,
                parent_path=nexus_root,
            )

        return cls._get_or_create("path_guardian", factory, ctx)

    @classmethod
    def get_config(cls, ctx: SessionContext | None = None):
        """
        Get the config for the current tenant.

        The config is enhanced with tenant-specific paths.

        Returns:
            Config instance with tenant paths
        """

        def factory(ctx: SessionContext | None):
            from .config import Config

            config = Config()

            # Override workspace path for tenant
            workspace_path = cls.get_tenant_workspace_path(ctx)
            config.workspace_path = workspace_path

            # Override telemetry file path
            config.telemetry_file = str(workspace_path / "telemetry.jsonl")

            return config

        return cls._get_or_create("config", factory, ctx)

    # =========================================================================
    # V10 MEMORY FORGE: MEMORY SERVICES
    # =========================================================================

    # Global embedding engine (NOT tenant-scoped - shared compute)
    _embedding_engine = None
    _embedding_engine_lock = threading.RLock()

    @classmethod
    def get_embedding_engine(cls):
        """
        Get the global EmbeddingEngine singleton.

        NOTE: This is GLOBAL, not tenant-scoped. The embedding model
        is shared across all tenants to save RAM (~500MB per model).

        V10 MEMORY FORGE: Shared compute, isolated storage.

        Returns:
            EmbeddingEngine instance (global singleton)
        """
        with cls._embedding_engine_lock:
            if cls._embedding_engine is None:
                from .memory_pkg.memory.embedding_engine import EmbeddingEngine

                cls._embedding_engine = EmbeddingEngine()
            return cls._embedding_engine

    @classmethod
    def get_project_memory(cls, ctx: SessionContext | None = None):
        """
        Get the project memory for the current tenant.

        V10 MEMORY FORGE: Uses shared EmbeddingEngine for encoding,
        but storage is isolated per tenant.

        Returns:
            ProjectMemory instance with tenant-isolated storage
        """

        def factory(ctx: SessionContext | None):
            from .memory_pkg.memory.project_memory import ProjectMemory

            nexus_root = cls.get_nexus_root()

            # Get shared embedding engine
            engine = cls.get_embedding_engine()

            # Create tenant-scoped ProjectMemory with shared engine
            return ProjectMemory(nexus_root, embedding_engine=engine)

        return cls._get_or_create("project_memory", factory, ctx)

    @classmethod
    def get_auto_memory(cls, ctx: SessionContext | None = None):
        """
        Get the auto memory for the current tenant.

        AutoMemory provides automatic context management for agents.

        Returns:
            AutoMemory instance scoped to tenant
        """

        def factory(ctx: SessionContext | None):
            from .memory_pkg.memory.auto_memory import AutoMemory

            workspace_path = cls.get_tenant_workspace_path(ctx)
            return AutoMemory(workspace_path)

        return cls._get_or_create("auto_memory", factory, ctx)

    @classmethod
    def get_success_memory(cls, ctx: SessionContext | None = None):
        """
        Get the success memory for the current tenant.

        SuccessMemory tracks successful tool executions for
        learning and improvement.

        Returns:
            SuccessMemory instance scoped to tenant
        """

        def factory(ctx: SessionContext | None):
            from .memory_pkg.memory.success_memory_v2 import SuccessMemoryV2 as SuccessMemory

            workspace_path = cls.get_tenant_workspace_path(ctx)
            return SuccessMemory(workspace_path)

        return cls._get_or_create("success_memory", factory, ctx)

    @classmethod
    def get_spotlighter(cls, ctx: SessionContext | None = None):
        """
        Get the spotlighter for the current tenant.

        Spotlighter provides RAG content datamarking for
        security (OWASP LLM01:2025 - Prompt Injection detection).

        Returns:
            Spotlighter instance scoped to tenant
        """

        def factory(ctx: SessionContext | None):
            from .memory_pkg.memory.spotlighting import Spotlighter

            return Spotlighter()

        return cls._get_or_create("spotlighter", factory, ctx)

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    @classmethod
    def clear_tenant_cache(cls, tenant_id: str) -> None:
        """
        Clear all cached instances for a tenant.

        Use when tenant is deleted or for testing.

        Args:
            tenant_id: Tenant to clear
        """
        with cls._lock:
            if tenant_id in cls._instances:
                del cls._instances[tenant_id]

    @classmethod
    def clear_all_caches(cls) -> None:
        """
        Clear all cached instances.

        Use for testing or complete reset.
        """
        with cls._lock:
            cls._instances.clear()

    @classmethod
    def get_cache_stats(cls) -> dict[str, int]:
        """
        Get statistics about the instance cache.

        Returns:
            Dict with tenant count and total instance count
        """
        with cls._lock:
            tenant_count = len(cls._instances)
            instance_count = sum(len(services) for services in cls._instances.values())
            return {
                "tenant_count": tenant_count,
                "instance_count": instance_count,
            }


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================
# These functions maintain API compatibility during migration


def get_registry():
    """
    Backward-compatible registry getter.

    Deprecated: Use ServiceFactory.get_registry() instead.
    """
    return ServiceFactory.get_registry()


def get_workspace_manager(base_workspace: Path | None = None):
    """
    Backward-compatible workspace manager getter.

    Deprecated: Use ServiceFactory.get_workspace_manager() instead.
    """
    return ServiceFactory.get_workspace_manager()


def get_tool_registry():
    """
    Backward-compatible tool registry getter.

    Deprecated: Use ServiceFactory.get_tool_registry() instead.
    """
    return ServiceFactory.get_tool_registry()
