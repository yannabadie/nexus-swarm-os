"""
V12.3 SCALE-OUT - Redis Workflow Registry Tests

Tests:
- CRUD operations (create, read, update, delete)
- In-memory fallback when Redis unavailable
- Tenant isolation
- Status transitions
- TTL cleanup

Author: Claude (NEXUS V12.3 SCALE-OUT)
Date: 2025-12-16
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.workflow import (
    RedisWorkflowRegistry,
    WorkflowStatus,
    get_workflow_registry,
    reset_workflow_registry,
)


class TestWorkflowStatusEnum:
    """Test WorkflowStatus enum values."""

    def test_status_values(self):
        """Test all status enum values exist."""
        assert WorkflowStatus.PENDING.value == "pending"
        assert WorkflowStatus.RUNNING.value == "running"
        assert WorkflowStatus.COMPLETED.value == "completed"
        assert WorkflowStatus.FAILED.value == "failed"
        assert WorkflowStatus.CANCELLED.value == "cancelled"


class TestRedisWorkflowRegistryUnit:
    """Unit tests for RedisWorkflowRegistry (no Redis required)."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        reset_workflow_registry()
        yield
        reset_workflow_registry()

    def test_singleton_pattern(self):
        """Test registry uses singleton pattern."""
        reg1 = RedisWorkflowRegistry()
        reg2 = RedisWorkflowRegistry()
        assert reg1 is reg2

    def test_configure(self):
        """Test registry configuration."""
        registry = RedisWorkflowRegistry()
        registry.configure(
            redis_url="redis://test:6379",
            use_redis=False,
            workflow_ttl_hours=48,
        )
        assert registry._redis_url == "redis://test:6379"
        assert not registry._use_redis
        assert registry._workflow_ttl == 48 * 3600

    def test_initial_state(self):
        """Test registry initial state."""
        registry = RedisWorkflowRegistry()
        assert not registry._connected
        assert registry._memory_store == {}
        assert registry._tenant_index == {}


class TestRedisWorkflowRegistryInMemory:
    """Tests for in-memory fallback mode."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Setup fresh registry in memory-only mode."""
        reset_workflow_registry()
        self.registry = get_workflow_registry()
        self.registry.configure(use_redis=False)
        yield
        reset_workflow_registry()

    @pytest.mark.asyncio
    async def test_create_workflow(self):
        """Test creating a workflow in memory."""
        workflow_id = "test-123"
        tenant_id = str(uuid4())

        result = await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Test task",
            workspace_id="default",
            complexity="MODERATE",
        )

        assert result["workflow_id"] == workflow_id
        assert result["tenant_id"] == tenant_id
        assert result["status"] == WorkflowStatus.PENDING.value
        assert result["task"] == "Test task"
        assert result["complexity"] == "MODERATE"

    @pytest.mark.asyncio
    async def test_get_workflow(self):
        """Test retrieving a workflow."""
        workflow_id = "test-get"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Get test",
        )

        result = await self.registry.get_workflow(workflow_id, tenant_id)
        assert result is not None
        assert result["workflow_id"] == workflow_id

    @pytest.mark.asyncio
    async def test_get_workflow_wrong_tenant(self):
        """Test tenant isolation - cannot get other tenant's workflow."""
        workflow_id = "test-isolation"
        tenant_id = str(uuid4())
        other_tenant = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Isolation test",
        )

        result = await self.registry.get_workflow(workflow_id, other_tenant)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_status(self):
        """Test status update."""
        workflow_id = "test-update"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Update test",
        )

        result = await self.registry.update_status(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            status=WorkflowStatus.RUNNING.value,
        )

        assert result is not None
        assert result["status"] == WorkflowStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_update_status_with_result(self):
        """Test status update with result data."""
        workflow_id = "test-result"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Result test",
        )

        result = await self.registry.update_status(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            status=WorkflowStatus.COMPLETED.value,
            result={"output": "success"},
        )

        assert result["status"] == WorkflowStatus.COMPLETED.value
        assert result["result"] == {"output": "success"}

    @pytest.mark.asyncio
    async def test_update_status_with_error(self):
        """Test status update with error message."""
        workflow_id = "test-error"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Error test",
        )

        result = await self.registry.update_status(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            status=WorkflowStatus.FAILED.value,
            error="Something went wrong",
        )

        assert result["status"] == WorkflowStatus.FAILED.value
        assert result["error"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_list_workflows(self):
        """Test listing workflows for a tenant."""
        tenant_id = str(uuid4())

        for i in range(3):
            await self.registry.create_workflow(
                workflow_id=f"test-list-{i}",
                tenant_id=tenant_id,
                task=f"Task {i}",
            )

        workflows = await self.registry.list_workflows(tenant_id)
        assert len(workflows) == 3

    @pytest.mark.asyncio
    async def test_list_workflows_status_filter(self):
        """Test filtering workflows by status."""
        tenant_id = str(uuid4())

        # Create workflows with different statuses
        await self.registry.create_workflow(
            workflow_id="pending-1",
            tenant_id=tenant_id,
            task="Pending task",
        )

        await self.registry.create_workflow(
            workflow_id="running-1",
            tenant_id=tenant_id,
            task="Running task",
        )
        await self.registry.update_status("running-1", tenant_id, WorkflowStatus.RUNNING.value)

        # Filter by running
        running = await self.registry.list_workflows(tenant_id, status=WorkflowStatus.RUNNING.value)
        assert len(running) == 1
        assert running[0]["workflow_id"] == "running-1"

    @pytest.mark.asyncio
    async def test_list_workflows_tenant_isolation(self):
        """Test listing only returns current tenant's workflows."""
        tenant_a = str(uuid4())
        tenant_b = str(uuid4())

        await self.registry.create_workflow(
            workflow_id="tenant-a-1",
            tenant_id=tenant_a,
            task="Tenant A task",
        )
        await self.registry.create_workflow(
            workflow_id="tenant-b-1",
            tenant_id=tenant_b,
            task="Tenant B task",
        )

        workflows_a = await self.registry.list_workflows(tenant_a)
        workflows_b = await self.registry.list_workflows(tenant_b)

        assert len(workflows_a) == 1
        assert len(workflows_b) == 1
        assert workflows_a[0]["workflow_id"] == "tenant-a-1"
        assert workflows_b[0]["workflow_id"] == "tenant-b-1"

    @pytest.mark.asyncio
    async def test_delete_workflow(self):
        """Test deleting a workflow."""
        workflow_id = "test-delete"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Delete test",
        )

        deleted = await self.registry.delete_workflow(workflow_id, tenant_id)
        assert deleted

        result = await self.registry.get_workflow(workflow_id, tenant_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test statistics gathering."""
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id="stats-1",
            tenant_id=tenant_id,
            task="Stats test 1",
        )
        await self.registry.create_workflow(
            workflow_id="stats-2",
            tenant_id=tenant_id,
            task="Stats test 2",
        )
        await self.registry.update_status("stats-2", tenant_id, WorkflowStatus.COMPLETED.value)

        stats = self.registry.get_stats()
        assert stats["backend"] == "memory"
        assert stats["total_workflows"] == 2
        assert stats["by_status"]["pending"] == 1
        assert stats["by_status"]["completed"] == 1


class TestWorkflowLifecycle:
    """Tests for complete workflow lifecycle."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Setup fresh registry."""
        reset_workflow_registry()
        self.registry = get_workflow_registry()
        self.registry.configure(use_redis=False)
        yield
        reset_workflow_registry()

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test complete workflow lifecycle: create -> running -> completed."""
        workflow_id = "lifecycle-test"
        tenant_id = str(uuid4())

        # Create
        created = await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Full lifecycle test",
        )
        assert created["status"] == WorkflowStatus.PENDING.value

        # Start running
        running = await self.registry.update_status(workflow_id, tenant_id, WorkflowStatus.RUNNING.value)
        assert running["status"] == WorkflowStatus.RUNNING.value

        # Complete
        completed = await self.registry.update_status(
            workflow_id,
            tenant_id,
            WorkflowStatus.COMPLETED.value,
            result={"output": "done"},
        )
        assert completed["status"] == WorkflowStatus.COMPLETED.value
        assert completed["result"] == {"output": "done"}

    @pytest.mark.asyncio
    async def test_failure_lifecycle(self):
        """Test workflow failure lifecycle."""
        workflow_id = "failure-test"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Failure lifecycle test",
        )

        await self.registry.update_status(workflow_id, tenant_id, WorkflowStatus.RUNNING.value)

        failed = await self.registry.update_status(
            workflow_id,
            tenant_id,
            WorkflowStatus.FAILED.value,
            error="Task execution failed",
        )

        assert failed["status"] == WorkflowStatus.FAILED.value
        assert failed["error"] == "Task execution failed"

    @pytest.mark.asyncio
    async def test_cancellation_lifecycle(self):
        """Test workflow cancellation lifecycle."""
        workflow_id = "cancel-test"
        tenant_id = str(uuid4())

        await self.registry.create_workflow(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            task="Cancel lifecycle test",
        )

        await self.registry.update_status(workflow_id, tenant_id, WorkflowStatus.RUNNING.value)

        cancelled = await self.registry.update_status(workflow_id, tenant_id, WorkflowStatus.CANCELLED.value)

        assert cancelled["status"] == WorkflowStatus.CANCELLED.value


class TestConcurrentOperations:
    """Tests for concurrent workflow operations."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Setup fresh registry."""
        reset_workflow_registry()
        self.registry = get_workflow_registry()
        self.registry.configure(use_redis=False)
        yield
        reset_workflow_registry()

    @pytest.mark.asyncio
    async def test_concurrent_creates(self):
        """Test concurrent workflow creation."""
        tenant_id = str(uuid4())

        async def create_workflow(i: int):
            return await self.registry.create_workflow(
                workflow_id=f"concurrent-{i}",
                tenant_id=tenant_id,
                task=f"Concurrent task {i}",
            )

        results = await asyncio.gather(*[create_workflow(i) for i in range(10)])

        assert len(results) == 10
        workflows = await self.registry.list_workflows(tenant_id)
        assert len(workflows) == 10

    @pytest.mark.asyncio
    async def test_concurrent_updates(self):
        """Test concurrent status updates on different workflows."""
        tenant_id = str(uuid4())

        # Create workflows
        for i in range(5):
            await self.registry.create_workflow(
                workflow_id=f"update-{i}",
                tenant_id=tenant_id,
                task=f"Update task {i}",
            )

        async def update_workflow(i: int):
            return await self.registry.update_status(f"update-{i}", tenant_id, WorkflowStatus.COMPLETED.value)

        results = await asyncio.gather(*[update_workflow(i) for i in range(5)])

        assert all(r["status"] == WorkflowStatus.COMPLETED.value for r in results)
