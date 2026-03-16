"""
NEXUS CEREBRO API - Causality Timeline Routes
V12.4 P2.1 OBSERVABILITY

Provides timeline visualization of task execution events with cost, latency, and state diffs.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.api.cerebro.deps import AuthenticatedUser, require_auth
from core.observability.events.event_store import EventStore
from core.observability.telemetry.budget_tracker import BudgetTracker

router = APIRouter(prefix="/timeline", tags=["timeline"])


def get_tenant_id(user: AuthenticatedUser = Depends(require_auth)) -> str:
    """Extract tenant_id from authenticated user."""
    return user.tenant_id


# ============================================================================
# Request/Response Models
# ============================================================================


class TokenMetrics(BaseModel):
    """Token usage metrics for an event."""

    input: int = 0
    output: int = 0
    cache_creation: int | None = None
    cache_read: int | None = None


class TimelineEvent(BaseModel):
    """Single event in the causality timeline."""

    timestamp: str
    task_id: str
    phase: str  # analysis, debate, architecture, execution, diagnosis, retry, consolidation
    agent_id: str
    action: str  # llm_call, tool_exec, snapshot, transition, validation
    model: str | None = None
    tokens: TokenMetrics | None = None
    cost: float | None = None
    latency_ms: float | None = None
    result: str  # success, failure, rollback, pending
    diff: dict[str, Any] | None = None  # State changes
    error: str | None = None
    metadata: dict[str, Any] | None = None


class TimelineResponse(BaseModel):
    """Timeline response with events and aggregated metrics."""

    events: list[TimelineEvent]
    total_cost: float = Field(default=0.0, description="Total cost across all events")
    total_tokens: dict[str, int] = Field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})
    duration_ms: float = Field(default=0.0, description="Total task duration")


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_event_cost(event: dict[str, Any]) -> float:
    """
    Calculate cost for a single event based on tokens and model.

    Uses BudgetTracker pricing for accurate cost calculation.
    """
    if not event.get("tokens"):
        return 0.0

    model = event.get("model", "unknown")
    tokens = event["tokens"]

    # Use BudgetTracker for pricing (supports prompt caching)
    tracker = BudgetTracker()

    try:
        cost = tracker.calculate_cost(
            model=model,
            input_tokens=tokens.get("input", 0),
            output_tokens=tokens.get("output", 0),
            cache_creation_tokens=tokens.get("cache_creation", 0),
            cache_read_tokens=tokens.get("cache_read", 0),
        )
        return cost
    except Exception:
        # Fallback: rough estimate if pricing not available
        # Assume $3/MTok input, $15/MTok output (Claude Sonnet ballpark)
        input_cost = tokens.get("input", 0) * 3.0 / 1_000_000
        output_cost = tokens.get("output", 0) * 15.0 / 1_000_000
        return input_cost + output_cost


def enrich_event(raw_event: dict[str, Any]) -> TimelineEvent:
    """
    Enrich raw event with calculated metrics (cost, latency).

    Args:
        raw_event: Raw event dict from EventStore

    Returns:
        Enriched TimelineEvent
    """
    # Extract basic fields
    timestamp = raw_event.get("timestamp", datetime.utcnow().isoformat())
    task_id = raw_event.get("task_id", "unknown")
    phase = raw_event.get("phase", "unknown")
    agent_id = raw_event.get("agent_id", "system")
    action = raw_event.get("action", "unknown")
    result = raw_event.get("result", "pending")

    # Extract metadata
    metadata = raw_event.get("metadata", {})
    model = metadata.get("model")
    error = raw_event.get("error")
    state_diff = raw_event.get("state_diff")

    # Extract tokens
    tokens_data = metadata.get("tokens")
    tokens = None
    if tokens_data:
        tokens = TokenMetrics(
            input=tokens_data.get("input", 0),
            output=tokens_data.get("output", 0),
            cache_creation=tokens_data.get("cache_creation"),
            cache_read=tokens_data.get("cache_read"),
        )

    # Calculate cost
    cost = calculate_event_cost(raw_event)

    # Extract latency
    latency_ms = metadata.get("latency_ms") or raw_event.get("latency_ms")

    return TimelineEvent(
        timestamp=timestamp,
        task_id=task_id,
        phase=phase,
        agent_id=agent_id,
        action=action,
        model=model,
        tokens=tokens,
        cost=cost,
        latency_ms=latency_ms,
        result=result,
        diff=state_diff,
        error=error,
        metadata=metadata,
    )


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/{task_id}", response_model=TimelineResponse)
async def get_timeline_events(task_id: str, tenant_id: str = Depends(get_tenant_id)):
    """
    Fetch causality timeline for a specific task.

    Returns chronological list of events with cost, latency, tokens, and state diffs.

    Args:
        task_id: Unique task identifier
        tenant_id: Tenant ID (from auth middleware)

    Returns:
        TimelineResponse with enriched events and aggregated metrics

    Raises:
        HTTPException: 404 if task not found, 500 on error
    """
    try:
        # Fetch events from EventStore
        event_store = EventStore()
        raw_events = await event_store.get_events(task_id=task_id, tenant_id=tenant_id)

        if not raw_events:
            raise HTTPException(status_code=404, detail=f"No events found for task {task_id}")

        # Enrich events with cost/latency
        enriched_events = [enrich_event(event) for event in raw_events]

        # Calculate aggregated metrics
        total_cost = sum(e.cost or 0.0 for e in enriched_events)

        total_tokens = {
            "input": sum(e.tokens.input if e.tokens else 0 for e in enriched_events),
            "output": sum(e.tokens.output if e.tokens else 0 for e in enriched_events),
            "cache_read": sum(e.tokens.cache_read if e.tokens and e.tokens.cache_read else 0 for e in enriched_events),
        }

        # Calculate total duration (first to last event)
        if len(enriched_events) >= 2:
            first_time = datetime.fromisoformat(enriched_events[0].timestamp)
            last_time = datetime.fromisoformat(enriched_events[-1].timestamp)
            duration_ms = (last_time - first_time).total_seconds() * 1000
        else:
            duration_ms = enriched_events[0].latency_ms or 0.0

        return TimelineResponse(
            events=enriched_events, total_cost=total_cost, total_tokens=total_tokens, duration_ms=duration_ms
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch timeline: {str(e)}") from e


@router.get("/{task_id}/summary")
async def get_timeline_summary(task_id: str, tenant_id: str = Depends(get_tenant_id)):
    """
    Get high-level summary of task timeline without full event details.

    Useful for dashboard widgets showing task cost/duration at a glance.
    """
    try:
        # Fetch timeline
        timeline = await get_timeline_events(task_id, tenant_id)

        # Return summary only
        return {
            "task_id": task_id,
            "total_events": len(timeline.events),
            "total_cost": timeline.total_cost,
            "total_tokens": timeline.total_tokens,
            "duration_ms": timeline.duration_ms,
            "phases_completed": list(set(e.phase for e in timeline.events)),
            "agents_involved": list(set(e.agent_id for e in timeline.events)),
            "success_rate": sum(1 for e in timeline.events if e.result == "success") / len(timeline.events)
            if timeline.events
            else 0,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch timeline summary: {str(e)}") from e
