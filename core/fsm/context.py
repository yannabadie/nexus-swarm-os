"""
Task Execution Context - V7.5 Phase 0d

Immutable context for task execution, replacing mutable self.active_agent.
Enables thread-safe PARALLEL mode execution without race conditions.
"""

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class TaskExecutionContext:
    """
    Immutable context per task execution.

    Replaces self.active_agent global state to enable:
    - Thread-safe parallel execution
    - Clear agent attribution per operation
    - Session isolation per task

    Usage:
        context = TaskExecutionContext.create("Analyze codebase")
        # Pass context through methods instead of relying on self.active_agent
        result = orchestrator._invoke_agent(context, task_type="reasoning")
        # Change agent with immutable copy
        new_context = context.with_agent("Claude")
    """

    task_id: str
    current_agent: str
    objective: str = ""
    iteration: int = 0
    tool_requesting_agent: str | None = None
    validation_agent: str | None = None

    @classmethod
    def create(cls, objective: str = "", initial_agent: str = "Gemini") -> "TaskExecutionContext":
        """Create new context with unique task_id"""
        return cls(task_id=str(uuid4()), current_agent=initial_agent, objective=objective, iteration=0)

    def with_agent(self, agent: str) -> "TaskExecutionContext":
        """Return new context with different agent (immutable pattern)"""
        return TaskExecutionContext(
            task_id=self.task_id,
            current_agent=agent,
            objective=self.objective,
            iteration=self.iteration,
            tool_requesting_agent=self.tool_requesting_agent,
            validation_agent=self.validation_agent,
        )

    def with_iteration(self, iteration: int) -> "TaskExecutionContext":
        """Return new context with incremented iteration"""
        return TaskExecutionContext(
            task_id=self.task_id,
            current_agent=self.current_agent,
            objective=self.objective,
            iteration=iteration,
            tool_requesting_agent=self.tool_requesting_agent,
            validation_agent=self.validation_agent,
        )

    def with_tool_request(self, requesting_agent: str) -> "TaskExecutionContext":
        """Mark which agent is requesting tool execution"""
        return TaskExecutionContext(
            task_id=self.task_id,
            current_agent=self.current_agent,
            objective=self.objective,
            iteration=self.iteration,
            tool_requesting_agent=requesting_agent,
            validation_agent=self.validation_agent,
        )

    def with_validation(self, validating_agent: str) -> "TaskExecutionContext":
        """Mark which agent will validate the result"""
        return TaskExecutionContext(
            task_id=self.task_id,
            current_agent=self.current_agent,
            objective=self.objective,
            iteration=self.iteration,
            tool_requesting_agent=self.tool_requesting_agent,
            validation_agent=validating_agent,
        )

    def swap_agent(self) -> "TaskExecutionContext":
        """Swap between Gemini and Claude (for ping-pong turns)"""
        new_agent = "Claude" if self.current_agent == "Gemini" else "Gemini"
        return self.with_agent(new_agent)

    def next_iteration(self) -> "TaskExecutionContext":
        """Return context for next iteration"""
        return self.with_iteration(self.iteration + 1)

    def __str__(self) -> str:
        return f"TaskContext({self.task_id[:8]}..., agent={self.current_agent}, iter={self.iteration})"
