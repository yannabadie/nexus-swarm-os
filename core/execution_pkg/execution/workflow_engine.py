"""
Workflow Template Engine - Reusable multi-step task pipelines.

V12.4 COGNITIVE BOOST - Task #45

Defines and executes multi-step workflows with:
- Step dependency tracking (DAG-based)
- Conditional branching (skip_if / run_if)
- Step-level result passing via shared context
- Workflow templates for reuse
- Execution history and status tracking

Complements the TaskScheduler (which manages individual task priority)
by orchestrating sequences of dependent steps as a unified pipeline.

Usage:
    from core.execution_pkg.execution.workflow_engine import WorkflowEngine, WorkflowStep

    engine = WorkflowEngine()

    # Define a workflow
    wf = engine.create_workflow("code_review", description="Review and test code")
    wf.add_step(WorkflowStep(name="lint", handler="lint_code"))
    wf.add_step(WorkflowStep(name="test", handler="run_tests", depends_on=["lint"]))
    wf.add_step(WorkflowStep(name="report", handler="generate_report", depends_on=["test"]))

    # Execute (handler functions provided at runtime)
    result = engine.execute(wf, handlers={
        "lint_code": lambda ctx: {"issues": 0},
        "run_tests": lambda ctx: {"passed": 42},
        "generate_report": lambda ctx: {"summary": "All good"},
    })
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_STEPS = 100
MAX_RETRIES = 3


# =============================================================================
# Types
# =============================================================================


class StepStatus(Enum):
    """Status of a workflow step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(Enum):
    """Status of an entire workflow."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""

    name: str
    handler: str  # handler function key
    depends_on: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    skip_if: str | None = None  # context key: skip if truthy
    run_if: str | None = None  # context key: run only if truthy
    retries: int = 0
    timeout_seconds: float = 0  # 0 = no timeout
    description: str = ""

    # Runtime state (set during execution)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    duration_seconds: float = 0.0
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "handler": self.handler,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": str(self.result)[:200] if self.result else None,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 3),
            "attempts": self.attempts,
        }


@dataclass
class Workflow:
    """A complete workflow definition with steps."""

    workflow_id: str = ""
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.CREATED
    created_at: float = 0.0
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.workflow_id:
            self.workflow_id = uuid.uuid4().hex[:12]
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    def add_step(self, step: WorkflowStep) -> None:
        """Add a step to the workflow."""
        self.steps.append(step)

    def get_step(self, name: str) -> WorkflowStep | None:
        """Get a step by name."""
        for s in self.steps:
            if s.name == name:
                return s
        return None

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    @property
    def skipped_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.SKIPPED)

    @property
    def progress(self) -> float:
        """Workflow progress (0.0 to 1.0)."""
        if not self.steps:
            return 1.0
        done = sum(1 for s in self.steps if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED))
        return done / len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "step_count": self.step_count,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "progress": round(self.progress, 4),
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass
class ExecutionResult:
    """Result of executing a workflow."""

    workflow_id: str
    workflow_name: str
    status: WorkflowStatus
    total_steps: int
    completed_steps: int
    failed_steps: int
    skipped_steps: int
    total_duration: float
    context: dict[str, Any]  # shared execution context
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "success": self.success,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "total_duration": round(self.total_duration, 3),
            "errors": self.errors,
        }


# =============================================================================
# Workflow Engine
# =============================================================================


class WorkflowEngine:
    """
    Executes multi-step workflows with dependency tracking.

    Steps are executed in topological order based on depends_on.
    Results from each step are stored in a shared context dict.
    Conditional execution via skip_if / run_if context keys.
    """

    def __init__(self):
        self._templates: dict[str, Workflow] = {}
        self._history: list[ExecutionResult] = []

    # =========================================================================
    # Template Management
    # =========================================================================

    def create_workflow(
        self,
        name: str,
        *,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        """Create a new workflow."""
        wf = Workflow(
            name=name,
            description=description,
            metadata=metadata or {},
        )
        return wf

    def register_template(self, workflow: Workflow) -> None:
        """Register a workflow as a reusable template."""
        self._templates[workflow.name] = workflow

    def get_template(self, name: str) -> Workflow | None:
        """Get a registered template."""
        return self._templates.get(name)

    def list_templates(self) -> list[str]:
        """List registered template names."""
        return sorted(self._templates.keys())

    # =========================================================================
    # Execution
    # =========================================================================

    def execute(
        self,
        workflow: Workflow,
        handlers: dict[str, Callable],
        *,
        initial_context: dict[str, Any] | None = None,
        stop_on_failure: bool = True,
    ) -> ExecutionResult:
        """
        Execute a workflow.

        Args:
            workflow: Workflow to execute
            handlers: Map of handler key -> callable(context) -> result
            initial_context: Initial shared context
            stop_on_failure: Stop workflow on first step failure

        Returns:
            ExecutionResult
        """
        context = dict(initial_context or {})
        start_time = time.monotonic()
        workflow.status = WorkflowStatus.RUNNING
        errors: list[str] = []

        # Topological order
        order = self._topological_sort(workflow)

        for step_name in order:
            step = workflow.get_step(step_name)
            if step is None:
                continue

            # Check conditional skip
            if self._should_skip(step, context):
                step.status = StepStatus.SKIPPED
                continue

            # Check dependencies completed
            if not self._deps_satisfied(step, workflow):
                step.status = StepStatus.SKIPPED
                continue

            # Get handler
            handler = handlers.get(step.handler)
            if handler is None:
                step.status = StepStatus.FAILED
                step.error = f"Handler '{step.handler}' not found"
                errors.append(f"Step '{step.name}': {step.error}")
                if stop_on_failure:
                    break
                continue

            # Execute with retries
            success = self._execute_step(step, handler, context)
            if success:
                context[step.name] = step.result
            else:
                errors.append(f"Step '{step.name}': {step.error}")
                if stop_on_failure:
                    break

        # Determine final status
        end_time = time.monotonic()
        if workflow.failed_steps > 0:
            workflow.status = WorkflowStatus.FAILED
        else:
            workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = end_time

        result = ExecutionResult(
            workflow_id=workflow.workflow_id,
            workflow_name=workflow.name,
            status=workflow.status,
            total_steps=workflow.step_count,
            completed_steps=workflow.completed_steps,
            failed_steps=workflow.failed_steps,
            skipped_steps=workflow.skipped_steps,
            total_duration=end_time - start_time,
            context=context,
            errors=errors,
        )

        self._history.append(result)
        return result

    def _execute_step(
        self,
        step: WorkflowStep,
        handler: Callable,
        context: dict[str, Any],
    ) -> bool:
        """Execute a single step with retries."""
        max_attempts = max(1, step.retries + 1)

        for attempt in range(max_attempts):
            step.attempts = attempt + 1
            step.status = StepStatus.RUNNING
            start = time.monotonic()

            try:
                step.result = handler(context)
                step.duration_seconds = time.monotonic() - start
                step.status = StepStatus.COMPLETED
                return True
            except Exception as e:
                step.duration_seconds = time.monotonic() - start
                step.error = str(e)
                if attempt + 1 < max_attempts:
                    continue
                step.status = StepStatus.FAILED
                return False

        step.status = StepStatus.FAILED
        return False

    def _should_skip(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> bool:
        """Check if step should be skipped based on conditions."""
        if step.skip_if and context.get(step.skip_if):
            return True
        return bool(step.run_if and not context.get(step.run_if))

    def _deps_satisfied(
        self,
        step: WorkflowStep,
        workflow: Workflow,
    ) -> bool:
        """Check if all dependencies are completed."""
        for dep_name in step.depends_on:
            dep = workflow.get_step(dep_name)
            if dep is None:
                return False
            if dep.status not in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                return False
        return True

    def _topological_sort(self, workflow: Workflow) -> list[str]:
        """Sort steps in dependency order (Kahn's algorithm)."""
        if not workflow.steps:
            return []

        # Build adjacency info
        in_degree: dict[str, int] = {}
        dependents: dict[str, list[str]] = {}
        all_names: set[str] = set()

        for step in workflow.steps:
            all_names.add(step.name)
            in_degree.setdefault(step.name, 0)
            dependents.setdefault(step.name, [])
            for dep in step.depends_on:
                in_degree[step.name] = in_degree.get(step.name, 0) + 1
                dependents.setdefault(dep, []).append(step.name)

        # Start with steps that have no dependencies
        queue = [name for name in all_names if in_degree.get(name, 0) == 0]
        # Sort queue for deterministic order
        queue.sort()
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)
            for dep in sorted(dependents.get(current, [])):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        return result

    # =========================================================================
    # Queries
    # =========================================================================

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def execution_count(self) -> int:
        return len(self._history)

    def get_history(self, limit: int = 10) -> list[ExecutionResult]:
        """Get execution history (most recent first)."""
        return list(reversed(self._history[-limit:]))

    def clear_history(self) -> int:
        """Clear execution history."""
        count = len(self._history)
        self._history.clear()
        return count

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_count": self.template_count,
            "execution_count": self.execution_count,
            "templates": self.list_templates(),
        }
