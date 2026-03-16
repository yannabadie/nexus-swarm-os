"""
PingPongExecutor - V9.6 Extracted

Rapid alternation until convergence.

Use case: Creative tasks, brainstorming, iterative refinement.

V7.9: Enhanced with TaskCompletionValidator to prevent premature FINISHED.
"""

from pathlib import Path

# V13.0 CEREBRO LIVE: Telemetry for agent exchanges
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak

from ..collaboration_modes import CollaborationMode
from ..task_completion_validator import TaskCompletionValidator
from .base import (
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    ModeExecutor,
)


class PingPongExecutor(ModeExecutor):
    """
    Rapid alternation until convergence.

    Use case: Creative tasks, brainstorming, iterative refinement.

    V7.9: Enhanced with TaskCompletionValidator to prevent premature FINISHED.
    """

    mode = CollaborationMode.PING_PONG

    def __init__(self, workspace_path: Path | None = None):
        """
        Initialize PingPongExecutor.

        Args:
            workspace_path: Path to workspace for artifact verification
        """
        self._workspace_path = workspace_path

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with ping-pong pattern."""
        agents = context.get_all_agents()
        if len(agents) < 2:
            return ExecutionResult(
                mode=self.mode,
                status=ExecutionStatus.FAILED,
                final_output="Need 2 agents for ping-pong",
                agent_outputs=[],
                total_rounds=0,
                total_tokens=0,
                total_time_seconds=0.0,
            )

        # V7.9: Initialize completion validator
        workspace_path = context.blackboard.get("workspace_path") or self._workspace_path
        completion_validator = TaskCompletionValidator(workspace_path) if workspace_path else None

        # V7.9: Get task analysis for validation (from blackboard if available)
        # V12.4: Convert from dict if needed (blackboard stores dict for JSON serialization)
        task_analysis_raw = context.blackboard.get("task_analysis")
        if task_analysis_raw and isinstance(task_analysis_raw, dict):
            from ..task_analyzer import TaskAnalysis

            task_analysis = TaskAnalysis.from_dict(task_analysis_raw)
        else:
            task_analysis = task_analysis_raw

        outputs: list[AgentResponse] = []
        tool_results: list[dict] = []  # Collect tool results for validation
        total_tokens = 0
        total_time = 0.0
        current_idx = 0
        accumulated_context = context.task_input
        false_finish_count = 0  # Track rejected FINISHED signals

        # V7.5 Phase 7: Alternating roles for session isolation
        for round_num in range(context.max_rounds):
            agent = agents[current_idx % len(agents)]
            role = f"ping_{current_idx % len(agents)}"  # ping_0, ping_1, etc.

            # V7.9: Add context about rejected finishes if any
            rejection_notice = ""
            if false_finish_count > 0:
                rejection_notice = (
                    f"\n\n[IMPORTANT: {false_finish_count} premature FINISHED signal(s) were rejected. "
                    "Only say FINISHED when ALL work is truly complete with no remaining tasks.]"
                )

            round_context = (
                f"PING_PONG MODE - Round {round_num + 1}:\n"
                f"Original task: {context.task_input}\n\n"
                f"Conversation so far:\n{accumulated_context}{rejection_notice}\n\n"
                "Continue the work. Say 'FINISHED' ONLY when the task is FULLY complete."
            )

            response = self._invoke(context, agent.agent_id, round_context, role=role)
            outputs.append(response)
            total_tokens += response.tokens_used
            total_time += response.time_seconds

            # Collect tool results from response
            if response.tool_results:
                tool_results.extend(response.tool_results)

            # V13.0 CEREBRO LIVE: Emit ping-pong exchange
            next_agent = agents[(current_idx + 1) % len(agents)]
            emit_agent_speak(agent.agent_id, response.content[:200], action_type="PING_PONG")
            emit_agent_exchange(
                agent.agent_id,
                next_agent.agent_id,
                f"Round {round_num + 1}: {response.content[:60]}",
                exchange_type="ping_pong",
            )

            # V7.5: Stream round to callback for real-time display
            if context.on_round:
                context.on_round(round_num, response)

            # Update accumulated context
            accumulated_context += f"\n\n[{agent.agent_id} - Round {round_num + 1}]:\n{response.content}"

            # V7.9: Enhanced convergence check with validation
            if response.is_finished:
                # Validate the completion claim
                is_valid_finish = True
                validation_reason = "Basic completion check passed"

                if completion_validator and task_analysis:
                    validation_result = completion_validator.validate_completion(
                        task_input=context.task_input,
                        agent_response=response.content,
                        task_analysis=task_analysis,
                        tool_results=tool_results,
                    )
                    is_valid_finish = validation_result.is_valid
                    validation_reason = validation_result.reason

                    if not is_valid_finish:
                        # Reject the FINISHED signal
                        false_finish_count += 1
                        import sys

                        print(
                            f"[COMPLETION VALIDATOR] Rejected FINISHED signal (round {round_num + 1}): "
                            f"{validation_reason}",
                            file=sys.stderr,
                        )
                        # Continue to next round
                        current_idx += 1
                        continue

                # Valid completion - return result
                return ExecutionResult(
                    mode=self.mode,
                    status=ExecutionStatus.CONVERGED,
                    final_output=response.content,
                    agent_outputs=outputs,
                    total_rounds=round_num + 1,
                    total_tokens=total_tokens,
                    total_time_seconds=total_time,
                    metadata={
                        "execution_type": "ping_pong",
                        "converged_at": round_num + 1,
                        "validation_reason": validation_reason,
                        "false_finish_count": false_finish_count,
                    },
                )

            current_idx += 1

        # Max rounds reached without convergence
        # V10 FIX F14: Use INCOMPLETE instead of COMPLETED
        final_output = outputs[-1].content if outputs else ""

        return ExecutionResult(
            mode=self.mode,
            status=ExecutionStatus.INCOMPLETE,  # V10: Max rounds != completion
            final_output=final_output,
            agent_outputs=outputs,
            total_rounds=context.max_rounds,
            total_tokens=total_tokens,
            total_time_seconds=total_time,
            metadata={
                "execution_type": "ping_pong",
                "max_rounds_reached": True,
                "false_finish_count": false_finish_count,
                "reason": "max_rounds_exceeded_without_convergence",  # V10: Explicit reason
            },
        )
