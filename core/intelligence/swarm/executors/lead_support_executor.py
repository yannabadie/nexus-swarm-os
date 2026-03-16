"""
LeadSupportExecutor - V9.6 Extracted

Lead agent drives (80%), support reviews (20%).

Use case: Clear expertise dominance, complex coding tasks.
"""

from ..collaboration_modes import CollaborationMode
from .base import (
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    ModeExecutor,
)


class LeadSupportExecutor(ModeExecutor):
    """
    Lead agent drives (80%), support reviews (20%).

    Use case: Clear expertise dominance, complex coding tasks.
    """

    mode = CollaborationMode.LEAD_SUPPORT

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with lead-support pattern."""
        lead = context.get_agent_by_role("lead")
        support = context.get_agent_by_role("support")

        if not lead or not support:
            agents = context.get_all_agents()
            lead = agents[0] if agents else None
            support = agents[1] if len(agents) > 1 else None

        outputs: list[AgentResponse] = []
        total_tokens = 0
        total_time = 0.0

        # Lead produces solution
        # V7.5 Phase 7: Role-based session isolation
        round_num = 0
        if lead:
            lead_context = f"LEAD_SUPPORT MODE - You are LEAD:\n{context.task_input}\n\nProvide complete solution."
            lead_response = self._invoke(context, lead.agent_id, lead_context, role="lead")
            outputs.append(lead_response)
            total_tokens += lead_response.tokens_used
            total_time += lead_response.time_seconds
            if context.on_round:
                context.on_round(round_num, lead_response)
            round_num += 1

            # Support reviews
            if support:
                review_context = (
                    f"LEAD_SUPPORT MODE - You are SUPPORT:\n{context.task_input}\n\n"
                    f"Lead ({lead.agent_id}) solution:\n{lead_response.content}\n\n"
                    "Review and provide feedback. Suggest improvements if needed."
                )
                review_response = self._invoke(context, support.agent_id, review_context, role="support")
                outputs.append(review_response)
                total_tokens += review_response.tokens_used
                total_time += review_response.time_seconds
                if context.on_round:
                    context.on_round(round_num, review_response)
                round_num += 1

                # If support has suggestions, lead revises
                if "suggest" in review_response.content.lower() or "improve" in review_response.content.lower():
                    revision_context = (
                        f"LEAD_SUPPORT MODE - Revision:\n"
                        f"Your original solution:\n{lead_response.content}\n\n"
                        f"Support feedback:\n{review_response.content}\n\n"
                        "Revise if appropriate."
                    )
                    revision_response = self._invoke(context, lead.agent_id, revision_context, role="lead")
                    outputs.append(revision_response)
                    total_tokens += revision_response.tokens_used
                    total_time += revision_response.time_seconds
                    if context.on_round:
                        context.on_round(round_num, revision_response)

        final_output = outputs[-1].content if outputs else ""

        # V7 Enhancement: Verify artifacts in final output
        artifact_result = self._verify_artifacts(final_output, context)

        return ExecutionResult(
            mode=self.mode,
            status=ExecutionStatus.COMPLETED,
            final_output=final_output,
            agent_outputs=outputs,
            total_rounds=len(outputs),
            total_tokens=total_tokens,
            total_time_seconds=total_time,
            metadata={
                "execution_type": "lead_support",
                "artifacts_verified": artifact_result["verified"],
                "artifact_successes": artifact_result["successes"],
                "artifact_failures": artifact_result["failures"],
            },
        )
