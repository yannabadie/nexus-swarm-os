"""
SequentialExecutor - V9.6 Extracted

Execute agents sequentially, passing output to next.

Use case: Clear dependencies, pipeline tasks.
"""

from ..collaboration_modes import CollaborationMode
from .base import (
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    ModeExecutor,
)


class SequentialExecutor(ModeExecutor):
    """
    Execute agents sequentially, passing output to next.

    Use case: Clear dependencies, pipeline tasks.
    """

    mode = CollaborationMode.SEQUENTIAL

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute agents in sequence."""
        first = context.get_agent_by_role("first")
        second = context.get_agent_by_role("second")

        if not first or not second:
            # Fallback to order
            agents = context.get_all_agents()
            first = agents[0] if agents else None
            second = agents[1] if len(agents) > 1 else None

        outputs: list[AgentResponse] = []
        total_tokens = 0
        total_time = 0.0

        # First agent
        # V7.5 Phase 7: Role-based session isolation
        if first:
            first_context = (
                f"SEQUENTIAL MODE - Phase 1:\n{context.task_input}\n\nYou are first. Provide your analysis/output."
            )
            first_response = self._invoke(context, first.agent_id, first_context, role="first")
            outputs.append(first_response)
            total_tokens += first_response.tokens_used
            total_time += first_response.time_seconds

            # Second agent receives first's output
            if second:
                second_context = (
                    f"SEQUENTIAL MODE - Phase 2:\n{context.task_input}\n\n"
                    f"Previous agent ({first.agent_id}) output:\n{first_response.content}\n\n"
                    "Continue/refine based on this."
                )
                second_response = self._invoke(context, second.agent_id, second_context, role="second")
                outputs.append(second_response)
                total_tokens += second_response.tokens_used
                total_time += second_response.time_seconds

        final_output = outputs[-1].content if outputs else ""

        return ExecutionResult(
            mode=self.mode,
            status=ExecutionStatus.COMPLETED,
            final_output=final_output,
            agent_outputs=outputs,
            total_rounds=len(outputs),
            total_tokens=total_tokens,
            total_time_seconds=total_time,
            metadata={"execution_type": "sequential"},
        )
