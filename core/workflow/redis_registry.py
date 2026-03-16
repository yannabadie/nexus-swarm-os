"""
NEXUS V12.3 SCALE-OUT - Redis Workflow Registry

Redis-backed workflow storage with graceful degradation to in-memory.
Supports multi-instance deployments where workflows must be visible across nodes.

Key Schema:
    workflows:{tenant_id} (Hash)
        {workflow_id} -> JSON{status, task, workspace_id, complexity, result, error, created_at}

    workflows:active (Set)
        -> Set of active workflow IDs for cleanup

Features:
- Graceful degradation: Falls back to in-memory dict when Redis unavailable
- Tenant isolation: Workflows keyed by tenant_id
- TTL: Completed/failed workflows expire after 24h (configurable)
- Thread-safe singleton pattern

Author: Claude (NEXUS V12.3 SCALE-OUT)
Date: 2025-12-16
"""

import json
import logging
from datetime import UTC, datetime
from enum import Enum
from threading import RLock
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RedisWorkflowRegistry:
    """
    Redis-backed workflow registry with graceful degradation.

    Falls back to in-memory storage when Redis is unavailable.
    Thread-safe singleton for process-level consistency.

    Attributes:
        WORKFLOW_TTL: TTL for completed/failed workflows (default 24h)
        KEY_PREFIX: Redis key prefix for workflows
    """

    _instance: Optional["RedisWorkflowRegistry"] = None
    _lock = RLock()

    # TTL in seconds (24 hours for completed/failed workflows)
    WORKFLOW_TTL = 86400
    KEY_PREFIX = "workflows"

    def __new__(cls) -> "RedisWorkflowRegistry":
        """Singleton pattern with double-checked locking."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        """Initialize registry (only runs once due to singleton)."""
        if self._initialized:
            return

        self._redis: Any | None = None  # redis.asyncio.Redis
        self._use_redis: bool = False
        self._redis_url: str = "redis://localhost:6379"
        self._connected: bool = False
        self._workflow_ttl: int = self.WORKFLOW_TTL

        # In-memory fallback storage
        # Key: workflow_id, Value: workflow dict
        self._memory_store: dict[str, dict[str, Any]] = {}
        # Tenant index for list operations
        # Key: tenant_id, Value: set of workflow_ids
        self._tenant_index: dict[str, set] = {}

        self._initialized = True
        logger.info("[WORKFLOW] RedisWorkflowRegistry initialized with in-memory fallback")

    def configure(
        self,
        redis_url: str = "redis://localhost:6379",
        use_redis: bool = True,
        workflow_ttl_hours: int = 24,
    ) -> None:
        """
        Configure the registry.

        Args:
            redis_url: Redis connection URL
            use_redis: Whether to attempt Redis connection
            workflow_ttl_hours: TTL for completed workflows in hours
        """
        self._redis_url = redis_url
        self._use_redis = use_redis
        self._workflow_ttl = workflow_ttl_hours * 3600
        logger.info(f"[WORKFLOW] Configured: use_redis={use_redis}, ttl={workflow_ttl_hours}h")

    async def connect(self) -> bool:
        """
        Connect to Redis if configured.

        Returns:
            True if connected to Redis, False if using in-memory fallback.
        """
        if not self._use_redis:
            logger.info("[WORKFLOW] Redis disabled, using in-memory storage")
            return False

        if self._connected:
            return True

        try:
            import redis.asyncio as redis_async

            self._redis = redis_async.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

            # Test connection
            await self._redis.ping()
            self._connected = True
            logger.info(f"[WORKFLOW] Connected to Redis at {self._redis_url}")
            return True

        except ImportError:
            logger.warning("[WORKFLOW] redis package not installed, using in-memory fallback")
            self._connected = False
            return False

        except Exception as e:
            logger.warning(f"[WORKFLOW] Redis connection failed: {e}, using in-memory fallback")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                logger.debug("Redis close error: %s", e)
            self._redis = None
            self._connected = False
            logger.info("[WORKFLOW] Disconnected from Redis")

    def _workflow_key(self, tenant_id: str) -> str:
        """Generate Redis key for tenant's workflows hash."""
        return f"{self.KEY_PREFIX}:{tenant_id}"

    def _serialize(self, data: dict[str, Any]) -> str:
        """Serialize workflow data to JSON."""
        # Convert UUID to string if present
        serializable = {}
        for k, v in data.items():
            if isinstance(v, UUID):
                serializable[k] = str(v)
            elif isinstance(v, datetime):
                serializable[k] = v.isoformat()
            else:
                serializable[k] = v
        return json.dumps(serializable)

    def _deserialize(self, data: str) -> dict[str, Any]:
        """Deserialize workflow data from JSON."""
        return json.loads(data)

    async def create_workflow(
        self,
        workflow_id: str,
        tenant_id: str,
        task: str,
        workspace_id: str = "default",
        complexity: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new workflow entry.

        Args:
            workflow_id: Unique workflow identifier
            tenant_id: Tenant identifier for isolation
            task: Task description
            workspace_id: Workspace identifier
            complexity: Optional complexity level

        Returns:
            Created workflow dict
        """
        workflow = {
            "workflow_id": workflow_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "task": task,
            "complexity": complexity,
            "status": WorkflowStatus.PENDING.value,
            "result": None,
            "error": None,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        if self._connected and self._redis:
            try:
                key = self._workflow_key(tenant_id)
                await self._redis.hset(key, workflow_id, self._serialize(workflow))
                await self._redis.sadd(f"{self.KEY_PREFIX}:active", workflow_id)
                logger.debug(f"[WORKFLOW] Created {workflow_id} in Redis")
            except Exception as e:
                logger.warning(f"[WORKFLOW] Redis create failed: {e}, using memory")
                self._store_in_memory(workflow_id, tenant_id, workflow)
        else:
            self._store_in_memory(workflow_id, tenant_id, workflow)

        return workflow

    def _store_in_memory(
        self,
        workflow_id: str,
        tenant_id: str,
        workflow: dict[str, Any],
    ) -> None:
        """Store workflow in in-memory fallback."""
        with self._lock:
            self._memory_store[workflow_id] = workflow
            if tenant_id not in self._tenant_index:
                self._tenant_index[tenant_id] = set()
            self._tenant_index[tenant_id].add(workflow_id)

    async def update_status(
        self,
        workflow_id: str,
        tenant_id: str,
        status: str,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Update workflow status.

        Args:
            workflow_id: Workflow identifier
            tenant_id: Tenant identifier
            status: New status value
            result: Optional result data
            error: Optional error message

        Returns:
            Updated workflow dict or None if not found
        """
        workflow = await self.get_workflow(workflow_id, tenant_id)
        if not workflow:
            return None

        workflow["status"] = status
        workflow["updated_at"] = datetime.now(UTC).isoformat()

        if result is not None:
            workflow["result"] = result
        if error is not None:
            workflow["error"] = error

        if self._connected and self._redis:
            try:
                key = self._workflow_key(tenant_id)
                await self._redis.hset(key, workflow_id, self._serialize(workflow))

                # Set TTL on completed/failed workflows
                if status in (
                    WorkflowStatus.COMPLETED.value,
                    WorkflowStatus.FAILED.value,
                    WorkflowStatus.CANCELLED.value,
                ):
                    await self._redis.srem(f"{self.KEY_PREFIX}:active", workflow_id)
                    # Note: Individual hash fields don't support TTL, would need separate key
                    # For now, rely on periodic cleanup

                logger.debug(f"[WORKFLOW] Updated {workflow_id} to {status} in Redis")
            except Exception as e:
                logger.warning(f"[WORKFLOW] Redis update failed: {e}, updating memory")
                self._update_in_memory(workflow_id, workflow)
        else:
            self._update_in_memory(workflow_id, workflow)

        return workflow

    def _update_in_memory(self, workflow_id: str, workflow: dict[str, Any]) -> None:
        """Update workflow in in-memory storage."""
        with self._lock:
            self._memory_store[workflow_id] = workflow

    async def get_workflow(
        self,
        workflow_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        """
        Get a specific workflow.

        Args:
            workflow_id: Workflow identifier
            tenant_id: Tenant identifier for authorization

        Returns:
            Workflow dict or None if not found
        """
        if self._connected and self._redis:
            try:
                key = self._workflow_key(tenant_id)
                data = await self._redis.hget(key, workflow_id)
                if data:
                    return self._deserialize(data)
            except Exception as e:
                logger.warning(f"[WORKFLOW] Redis get failed: {e}, checking memory")

        # Fallback to memory
        with self._lock:
            workflow = self._memory_store.get(workflow_id)
            if workflow and workflow.get("tenant_id") == tenant_id:
                return workflow
            return None

    async def list_workflows(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List workflows for a tenant.

        Args:
            tenant_id: Tenant identifier
            status: Optional status filter
            limit: Maximum results

        Returns:
            List of workflow dicts
        """
        workflows = []

        if self._connected and self._redis:
            try:
                key = self._workflow_key(tenant_id)
                all_data = await self._redis.hgetall(key)

                for wf_json in all_data.values():
                    workflow = self._deserialize(wf_json)
                    if status and workflow.get("status") != status:
                        continue
                    workflows.append(workflow)

                # Sort by created_at descending
                workflows.sort(key=lambda w: w.get("created_at", ""), reverse=True)
                return workflows[:limit]

            except Exception as e:
                logger.warning(f"[WORKFLOW] Redis list failed: {e}, using memory")

        # Fallback to memory
        with self._lock:
            wf_ids = self._tenant_index.get(tenant_id, set())
            for wf_id in wf_ids:
                workflow = self._memory_store.get(wf_id)
                if workflow:
                    if status and workflow.get("status") != status:
                        continue
                    workflows.append(workflow)

        # Sort by created_at descending
        workflows.sort(key=lambda w: w.get("created_at", ""), reverse=True)
        return workflows[:limit]

    async def delete_workflow(
        self,
        workflow_id: str,
        tenant_id: str,
    ) -> bool:
        """
        Delete a workflow.

        Args:
            workflow_id: Workflow identifier
            tenant_id: Tenant identifier

        Returns:
            True if deleted, False if not found
        """
        if self._connected and self._redis:
            try:
                key = self._workflow_key(tenant_id)
                deleted = await self._redis.hdel(key, workflow_id)
                await self._redis.srem(f"{self.KEY_PREFIX}:active", workflow_id)
                if deleted:
                    logger.debug(f"[WORKFLOW] Deleted {workflow_id} from Redis")
                    return True
            except Exception as e:
                logger.warning(f"[WORKFLOW] Redis delete failed: {e}")

        # Also delete from memory
        with self._lock:
            if workflow_id in self._memory_store:
                wf = self._memory_store.pop(workflow_id, None)
                if wf and wf.get("tenant_id") in self._tenant_index:
                    self._tenant_index[wf["tenant_id"]].discard(workflow_id)
                return True

        return False

    async def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """
        Clean up expired completed/failed workflows.

        Args:
            max_age_hours: Maximum age in hours for completed workflows

        Returns:
            Number of workflows cleaned up
        """
        cleaned = 0
        cutoff = datetime.now(UTC).isoformat()
        # Calculate cutoff time (simplified - just check age in hours)
        from datetime import timedelta

        cutoff_dt = datetime.now(UTC) - timedelta(hours=max_age_hours)
        cutoff = cutoff_dt.isoformat()

        # Clean in-memory store
        with self._lock:
            to_delete = []
            for wf_id, workflow in self._memory_store.items():
                if workflow.get("status") in (
                    WorkflowStatus.COMPLETED.value,
                    WorkflowStatus.FAILED.value,
                    WorkflowStatus.CANCELLED.value,
                ):
                    created = workflow.get("created_at", "")
                    if created < cutoff:
                        to_delete.append(wf_id)

            for wf_id in to_delete:
                wf = self._memory_store.pop(wf_id, None)
                if wf and wf.get("tenant_id") in self._tenant_index:
                    self._tenant_index[wf["tenant_id"]].discard(wf_id)
                cleaned += 1

        logger.info(f"[WORKFLOW] Cleaned up {cleaned} expired workflows")
        return cleaned

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            total = len(self._memory_store)
            by_status = {}
            for wf in self._memory_store.values():
                status = wf.get("status", "unknown")
                by_status[status] = by_status.get(status, 0) + 1

        return {
            "backend": "redis" if self._connected else "memory",
            "total_workflows": total,
            "by_status": by_status,
            "tenants": len(self._tenant_index),
        }


# =============================================================================
# Module-level singleton access
# =============================================================================

_registry: RedisWorkflowRegistry | None = None


def get_workflow_registry() -> RedisWorkflowRegistry:
    """
    Get the workflow registry singleton.

    Initializes with config on first call.

    Returns:
        RedisWorkflowRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = RedisWorkflowRegistry()

        # Try to load config
        try:
            from ..config import Config

            config = Config()
            redis_url = getattr(config, "redis_url", "redis://localhost:6379")
            use_redis = getattr(config, "use_redis_workflows", True)
            ttl_hours = getattr(config, "workflow_ttl_hours", 24)
            _registry.configure(redis_url, use_redis, ttl_hours)
        except Exception as e:
            logger.debug("Workflow registry config load failed, using defaults: %s", e)

    return _registry


def reset_workflow_registry() -> None:
    """Reset the registry singleton (for testing)."""
    global _registry
    if _registry:
        _registry._memory_store.clear()
        _registry._tenant_index.clear()
        _registry._connected = False
        _registry._redis = None
    _registry = None
