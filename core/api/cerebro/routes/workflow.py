"""
NEXUS V12.3 SCALE-OUT - Workflow Control Endpoints
V11.6.1 IRONCLAD - MANDATORY authentication (Zero Trust)
V12.3 SCALE-OUT - Redis-backed workflow registry for multi-instance

Enables task execution control for CEREBRO UI:
- POST /api/workflow/start : Start a workflow (non-blocking)
- GET /api/workflow/{id} : Get workflow status
- POST /api/workflow/{id}/stop : Stop a running workflow

Authentication:
- V11.6.1 IRONCLAD: MANDATORY auth - tenant_id from JWT ONLY
- Query param backdoors REMOVED to prevent IDOR attacks

Storage:
- V12.3: Redis-backed registry with graceful degradation to in-memory
- Multi-instance support: workflows visible across all NEXUS instances

Author: Claude (NEXUS V11.5 CORTEX, V12.3 SCALE-OUT)
Date: 2025-12-15
"""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

# V12.3 SCALE-OUT: Redis-backed workflow registry
from core.workflow import WorkflowStatus, get_workflow_registry

from ..deps import AuthenticatedUser, require_auth

logger = logging.getLogger(__name__)

router = APIRouter()

# V12.3: Get shared registry instance (Redis or in-memory fallback)
_registry = get_workflow_registry()


class WorkflowStartRequest(BaseModel):
    """Request body for starting a workflow."""

    task: str
    complexity: str | None = None


class WorkflowResponse(BaseModel):
    """Response model for workflow operations."""

    workflow_id: str
    status: str
    task: str | None = None
    result: Any | None = None
    error: str | None = None


def _get_orchestrator():
    """
    Lazy load Orchestrator for complex tasks.

    Creates a new OrchestratorV7 instance with proper configuration.
    """
    try:
        from core.config import Config
        from core.runtime import NexusSessionRuntime

        config = Config()
        runtime = NexusSessionRuntime.from_config(config, interaction_mode="headless")
        return runtime.orchestrator
    except Exception as e:
        logger.error(f"Failed to create orchestrator: {e}")
        raise


@router.post("/start")
async def start_workflow(
    body: WorkflowStartRequest,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, str]:
    """
    Start a workflow (non-blocking).

    Creates a background task to process the user's request.
    Returns immediately with a workflow_id for status tracking.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    tenant_id from JWT token ONLY - prevents IDOR attacks.

    Args:
        body: WorkflowStartRequest with task description
        background_tasks: FastAPI background task manager
        user: Authenticated user (from JWT token)

    Returns:
        {"workflow_id": "...", "status": "pending"}

    Raises:
        401: Not authenticated
    """
    # V11.6.1 IRONCLAD: tenant_id from JWT ONLY (Zero Trust)
    tenant_id = user.tenant_id
    workspace_id = user.workspace_id

    workflow_id = str(uuid4())[:12]

    # V12.3 SCALE-OUT: Connect to Redis (if configured)
    await _registry.connect()

    # V12.3: Create workflow in shared registry
    await _registry.create_workflow(
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        task=body.task,
        workspace_id=workspace_id,
        complexity=body.complexity,
    )

    async def run_workflow():
        """Background task to execute the workflow."""
        import concurrent.futures

        from core.observability.events.telemetry_bridge import get_telemetry_bridge
        from core.observability.events.types import CerebroEventType

        bridge = get_telemetry_bridge()

        try:
            # V12.3: Update status in shared registry
            await _registry.update_status(workflow_id, tenant_id, WorkflowStatus.RUNNING.value)
            logger.info(f"[CORTEX] Workflow {workflow_id} started: {body.task[:50]}...")

            # V12.0 RETINA: Emit workflow start event
            await bridge.emit(
                CerebroEventType.HIVE_PHASE_START,
                {"phase": "WORKFLOW", "workflow_id": workflow_id, "task": body.task[:100]},
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )

            # V12.0 RETINA: Emit graph nodes for agents
            await bridge.emit(
                CerebroEventType.GRAPH_NODE_SPAWN,
                {
                    "node_id": "gemini",
                    "type": "agent",
                    "data": {"name": "Gemini", "status": "idle"},
                    "position": {"x": 100, "y": 50},
                },
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            await bridge.emit(
                CerebroEventType.GRAPH_NODE_SPAWN,
                {
                    "node_id": "claude",
                    "type": "agent",
                    "data": {"name": "Claude", "status": "idle"},
                    "position": {"x": 300, "y": 50},
                },
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )

            # Get orchestrator
            orchestrator = _get_orchestrator()

            # V12.0: Run sync process_turn in executor to avoid blocking event loop
            # This allows WebSocket events to be processed during workflow execution
            # V12.4 FIX F19: Use get_running_loop() instead of deprecated get_event_loop()
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, orchestrator.process_turn, body.task)

            # V12.3: Update status in shared registry
            await _registry.update_status(workflow_id, tenant_id, WorkflowStatus.COMPLETED.value, result=result)
            logger.info(f"[CORTEX] Workflow {workflow_id} completed")

            # V12.0 RETINA: Emit workflow complete event
            await bridge.emit(
                CerebroEventType.HIVE_PHASE_END,
                {"phase": "WORKFLOW", "workflow_id": workflow_id, "status": "completed"},
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )

        except Exception as e:
            # V12.3: Update status in shared registry
            await _registry.update_status(workflow_id, tenant_id, WorkflowStatus.FAILED.value, error=str(e))
            logger.error(f"[CORTEX] Workflow {workflow_id} failed: {e}")

            # V12.0 RETINA: Emit workflow failed event
            await bridge.emit(
                CerebroEventType.HIVE_PHASE_END,
                {"phase": "WORKFLOW", "workflow_id": workflow_id, "status": "failed", "error": str(e)},
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )

    background_tasks.add_task(run_workflow)

    logger.info(f"[CORTEX] Workflow {workflow_id} queued for tenant={tenant_id}")
    return {"workflow_id": workflow_id, "status": "pending"}


@router.get("/{workflow_id}")
async def get_workflow_status(
    workflow_id: str,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """
    Get workflow status.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    Verifies the authenticated user owns the workflow.

    Args:
        workflow_id: The workflow ID from start_workflow
        user: Authenticated user (from JWT token)

    Returns:
        Workflow state including status, task, result, error

    Raises:
        401: Not authenticated
        403: Workflow belongs to different tenant
        404: Workflow not found
    """
    # V12.3 SCALE-OUT: Connect to registry
    await _registry.connect()

    # V12.3: Get from shared registry (tenant-scoped)
    workflow = await _registry.get_workflow(workflow_id, user.tenant_id)

    if not workflow:
        raise HTTPException(404, f"Workflow {workflow_id} not found")

    # V11.6.1 IRONCLAD: Tenant ownership verified by registry query

    return {
        "workflow_id": workflow_id,
        "status": workflow["status"],
        "task": workflow["task"],
        "result": workflow.get("result"),
        "error": workflow.get("error"),
    }


@router.post("/{workflow_id}/stop")
async def stop_workflow(
    workflow_id: str,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, str]:
    """
    Stop a running workflow.

    Currently marks workflow as cancelled. Full CancellationToken
    integration is planned for V11.7.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    Verifies the authenticated user owns the workflow.

    Args:
        workflow_id: The workflow ID to stop
        user: Authenticated user (from JWT token)

    Returns:
        {"workflow_id": "...", "status": "cancelled"}

    Raises:
        401: Not authenticated
        403: Workflow belongs to different tenant
        404: Workflow not found
        400: Workflow not in stoppable state
    """
    # V12.3 SCALE-OUT: Connect to registry
    await _registry.connect()

    # V12.3: Get from shared registry (tenant-scoped)
    workflow = await _registry.get_workflow(workflow_id, user.tenant_id)

    if not workflow:
        raise HTTPException(404, f"Workflow {workflow_id} not found")

    # V11.6.1 IRONCLAD: Tenant ownership verified by registry query

    if workflow["status"] not in ("pending", "running"):
        raise HTTPException(400, f"Workflow {workflow_id} is {workflow['status']}, cannot stop")

    # V12.3: Mark as cancelled in shared registry
    # TODO: Integrate CancellationToken for graceful cancellation
    await _registry.update_status(workflow_id, user.tenant_id, WorkflowStatus.CANCELLED.value)
    logger.info(f"[CORTEX] Workflow {workflow_id} cancelled")

    return {"workflow_id": workflow_id, "status": "cancelled"}


@router.get("/")
async def list_workflows(
    user: AuthenticatedUser = Depends(require_auth),
    status: str | None = Query(None, description="Filter by status"),
) -> dict[str, list]:
    """
    List workflows for the authenticated tenant.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    Only shows workflows belonging to the authenticated tenant (IDOR prevention).

    Args:
        user: Authenticated user (from JWT token)
        status: Optional status filter (pending, running, completed, failed, cancelled)

    Returns:
        {"workflows": [...list of workflow summaries...]}

    Raises:
        401: Not authenticated
    """
    # V11.6.1 IRONCLAD: tenant_id from JWT ONLY (Zero Trust)
    tenant_id = user.tenant_id

    # V12.3 SCALE-OUT: Connect to registry
    await _registry.connect()

    # V12.3: List from shared registry (tenant-scoped)
    workflow_list = await _registry.list_workflows(tenant_id, status=status)

    # Format response
    workflows = []
    for wf_data in workflow_list:
        task = wf_data.get("task", "")
        workflows.append(
            {
                "workflow_id": wf_data["workflow_id"],
                "status": wf_data["status"],
                "task": task[:50] + "..." if len(task) > 50 else task,
                "tenant_id": wf_data.get("tenant_id"),
            }
        )

    return {"workflows": workflows}
