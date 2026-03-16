"""
RedBlueExecutor - V9.6 Extracted

Adversarial: Blue proposes, Red attacks, iterate.

Use case: Security reviews, critical decisions, risk assessment.
"""

from pathlib import Path

# V13.0 CEREBRO LIVE: Telemetry for agent exchanges
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak
from core.utils.artifact_verifier import ArtifactVerifier

from ..collaboration_modes import CollaborationMode
from .base import (
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    ModeExecutor,
)


class RedBlueExecutor(ModeExecutor):
    """
    Adversarial: Blue proposes, Red attacks, iterate.

    Use case: Security reviews, critical decisions, risk assessment.
    """

    mode = CollaborationMode.RED_BLUE

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with adversarial red-blue pattern."""
        blue = context.get_agent_by_role("blue")
        red = context.get_agent_by_role("red")

        if not blue or not red:
            agents = context.get_all_agents()
            blue = agents[0] if agents else None
            red = agents[1] if len(agents) > 1 else None

        if not blue or not red:
            return ExecutionResult(
                mode=self.mode,
                status=ExecutionStatus.FAILED,
                final_output="Need both blue (proposer) and red (attacker) agents",
                agent_outputs=[],
                total_rounds=0,
                total_tokens=0,
                total_time_seconds=0.0,
            )

        outputs: list[AgentResponse] = []
        total_tokens = 0
        total_time = 0.0

        # V7.5 Phase 7: Role-based session isolation for adversarial mode
        # Phase 1: Blue proposes
        propose_context = (
            f"RED_BLUE MODE - You are BLUE (proposer):\n{context.task_input}\n\n"
            "Propose a complete solution. Be thorough as it will be attacked."
        )
        proposal = self._invoke(context, blue.agent_id, propose_context, role="blue")
        outputs.append(proposal)
        total_tokens += proposal.tokens_used
        total_time += proposal.time_seconds
        if context.on_round:
            context.on_round(0, proposal)

        # V13.0 CEREBRO LIVE: Emit Blue proposal
        emit_agent_speak(blue.agent_id, proposal.content[:200], action_type="PROPOSE")
        emit_agent_exchange(
            blue.agent_id, red.agent_id, "[PROPOSE] Solution ready for review", exchange_type="red_blue"
        )

        # Phase 2: Red attacks
        attack_context = (
            f"RED_BLUE MODE - You are RED (attacker):\n{context.task_input}\n\n"
            f"Blue's proposal:\n{proposal.content}\n\n"
            "Find weaknesses, security issues, edge cases, flaws. Be adversarial."
        )
        attack = self._invoke(context, red.agent_id, attack_context, role="red")
        outputs.append(attack)
        total_tokens += attack.tokens_used
        total_time += attack.time_seconds
        if context.on_round:
            context.on_round(1, attack)

        # V13.0 CEREBRO LIVE: Emit Red attack
        emit_agent_speak(red.agent_id, attack.content[:200], action_type="ATTACK")
        emit_agent_exchange(red.agent_id, blue.agent_id, "[ATTACK] Weaknesses found", exchange_type="red_blue")

        # Phase 3: Blue defends
        defend_context = (
            f"RED_BLUE MODE - Defense phase:\n"
            f"Your original proposal:\n{proposal.content}\n\n"
            f"Red's attack:\n{attack.content}\n\n"
            "Defend your proposal and/or revise to address valid concerns."
        )
        defense = self._invoke(context, blue.agent_id, defend_context, role="blue")
        outputs.append(defense)
        total_tokens += defense.tokens_used
        total_time += defense.time_seconds
        if context.on_round:
            context.on_round(2, defense)

        # V13.0 CEREBRO LIVE: Emit Blue defense
        emit_agent_speak(blue.agent_id, defense.content[:200], action_type="DEFEND")
        emit_agent_exchange(blue.agent_id, red.agent_id, "[DEFEND] Concerns addressed", exchange_type="red_blue")

        # Phase 4: Red verifies
        verify_context = (
            f"RED_BLUE MODE - Verification:\n"
            f"Original proposal:\n{proposal.content}\n\n"
            f"Your attack:\n{attack.content}\n\n"
            f"Blue's defense:\n{defense.content}\n\n"
            "Verify if concerns were addressed. Final verdict: PASS or FAIL with reasons."
        )
        verdict = self._invoke(context, red.agent_id, verify_context, role="red")
        outputs.append(verdict)
        total_tokens += verdict.tokens_used
        total_time += verdict.time_seconds
        if context.on_round:
            context.on_round(3, verdict)

        # V13.0 CEREBRO LIVE: Emit Red verdict
        emit_agent_speak(red.agent_id, verdict.content[:200], action_type="VERDICT")
        emit_agent_exchange(red.agent_id, "user", "[VERDICT] Review complete", exchange_type="red_blue")

        # Determine status with robust validation
        verdict_upper = verdict.content.upper()

        # 1. Improved text-based verdict detection
        # Require explicit "VERDICT: PASS" or "PASS" without "FAIL"
        text_passed = "VERDICT: PASS" in verdict_upper or ("PASS" in verdict_upper and "FAIL" not in verdict_upper)

        # 2. Artifact verification - check if mentioned files actually exist
        # V12.4: Handle None workspace_path explicitly
        workspace_path = context.blackboard.get("workspace_path")
        if workspace_path is None:
            workspace_path = Path.cwd()
        elif not isinstance(workspace_path, Path):
            workspace_path = Path(workspace_path)
        verifier = ArtifactVerifier(workspace_path)
        artifacts_ok, successes, failures = verifier.verify_from_content(defense.content)

        # 3. Combined verdict: PASS only if BOTH text verdict AND artifacts are OK
        passed = text_passed and artifacts_ok

        # 4. Override verdict if false positive detected (text says PASS but artifacts broken)
        final_verdict_content = verdict.content
        if text_passed and not artifacts_ok:
            override_msg = "\n\n[ARTIFACT VERIFICATION FAILED]\n" + "\n".join(failures)
            final_verdict_content = verdict.content + override_msg

        # FIX: Status was always COMPLETED before - now properly set to FAILED if not passed
        status = ExecutionStatus.COMPLETED if passed else ExecutionStatus.FAILED

        return ExecutionResult(
            mode=self.mode,
            status=status,
            final_output=defense.content,  # Defended solution
            agent_outputs=outputs,
            total_rounds=4,
            total_tokens=total_tokens,
            total_time_seconds=total_time,
            metadata={
                "execution_type": "red_blue",
                "verdict": "PASS" if passed else "FAIL",
                "text_verdict": text_passed,
                "artifacts_verified": artifacts_ok,
                "artifact_successes": successes,
                "artifact_failures": failures,
                "verdict_content": final_verdict_content,
                "validation_method": "robust_artifacts",
            },
        )
