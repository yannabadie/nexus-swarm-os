"""
SpecialistExecutor - V9.6 Extracted

Single expert handles everything.

Use case: Exclusive expertise, highly specialized tasks.
V7 Enhancement: Failover to backup agent if specialist fails.
"""

from ..collaboration_modes import CollaborationMode
from .base import (
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    ModeExecutor,
)


class SpecialistExecutor(ModeExecutor):
    """
    Single expert handles everything.

    Use case: Exclusive expertise, highly specialized tasks.

    V7 Enhancement: Failover to backup agent if specialist fails.
    """

    mode = CollaborationMode.SPECIALIST

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with single specialist agent."""
        specialist = context.get_agent_by_role("specialist")

        if not specialist:
            # Find best agent
            agents = context.get_all_agents()
            specialist = agents[0] if agents else None

        if not specialist:
            return ExecutionResult(
                mode=self.mode,
                status=ExecutionStatus.FAILED,
                final_output="No specialist agent available",
                agent_outputs=[],
                total_rounds=0,
                total_tokens=0,
                total_time_seconds=0.0,
            )

        task_context = (
            f"SPECIALIST MODE - You are the sole expert:\n{context.task_input}\n\nHandle this task completely."
        )

        # V7 Enhancement: Use failover for resilience
        # V7.5 Phase 7: Role-based session isolation
        backup_agent = self._get_backup_agent(specialist.agent_id)
        response = self._invoke_with_failover(
            context,
            specialist.agent_id,
            backup_agent,
            task_context,
            primary_role="specialist",
            backup_role="specialist_backup",
        )

        # V7 Enhancement: Verify artifacts in output
        artifact_result = self._verify_artifacts(response.content, context)

        return ExecutionResult(
            mode=self.mode,
            status=ExecutionStatus.COMPLETED if response.status != "error" else ExecutionStatus.FAILED,
            final_output=response.content,
            agent_outputs=[response],
            total_rounds=1,
            total_tokens=response.tokens_used,
            total_time_seconds=response.time_seconds,
            metadata={
                "execution_type": "specialist",
                "specialist": specialist.agent_id,
                "used_failover": "Failover" in response.content,
                "artifacts_verified": artifact_result["verified"],
                "artifact_successes": artifact_result["successes"],
                "artifact_failures": artifact_result["failures"],
            },
        )
