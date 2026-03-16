"""
NEXUS V9.2 - Phase 2: Strategic Debate

Structured debate between agents to resolve disagreements.
Uses argument/counter-argument format with evidence requirements.

V9.2 Enhancement: Session Isolation for Sequential Debate
- Each agent maintains isolated session during debate
- Context inheritance from Phase 1 via TASK_PLUS_RESULTS scope
- Model-aware context for capability reminders

Flow:
1. Agent A presents argument on disagreement point (session: uuid-A)
2. Agent B responds (SUPPORT, OPPOSE, or CONCEDE) (session: uuid-B)
3. Repeat until consensus OR max turns reached
4. If no consensus, force vote based on confidence

Key Features:
- Each argument must address specific points
- Concessions are encouraged (sign of good reasoning)
- Evidence required for COMPLEX/EXPERT tasks
- Adaptive turns (3-10) based on context
- V9.2: Session isolation prevents context bleeding
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from core.foundation.agents.unified_registry import get_registry  # V8.4.0

# V13.0 CEREBRO LIVE: Telemetry for agent exchanges
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak

from ..adaptive_debate import AdaptiveDebateConfig, DebateParams, TaskComplexity
from ..context_manager import HiveMindContextManager
from ..cost_estimator import CostEstimator
from ..prompts import CONSENSUS_SYSTEM_PROMPT, DEBATE_SYSTEM_PROMPT  # V12.4.1: Static prompts for caching
from ..session_integration import HiveMindSessionIntegration, generate_hivemind_task_id
from ..types import (
    AnalysisComparison,
    DebateArgument,
    DebateResult,
    Disagreement,
)

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm.session_manager import SwarmSessionManager


logger = logging.getLogger(__name__)


# =============================================================================
# V10 FIX F11: Misalignment Detection
# =============================================================================


@dataclass
class MisalignmentFlag:
    """Flag indicating potential inter-agent misalignment."""

    flag_type: str  # e.g., "silent_dissent", "input_dismissal", "premature_closure"
    pattern_matched: str
    severity: str  # "LOW", "MEDIUM", "HIGH"
    agent_id: str
    turn_number: int
    context: str  # Snippet of the problematic text


class MisalignmentDetector:
    """
    V10 FIX F11: Detects inter-agent misalignment patterns.

    Based on MASFT taxonomy:
    - Information withholding
    - Input dismissal
    - Reasoning-action mismatch
    - Premature closure
    """

    # Patterns indicating misalignment (from MASFT research)
    MISALIGNMENT_PATTERNS = {
        "silent_dissent": [
            r"I disagree but will proceed",
            r"against my better judgment",
            r"I have concerns but",
            r"not ideal but acceptable",
        ],
        "input_dismissal": [
            r"ignoring.*input",
            r"disregard.*previous",
            r"regardless of.*said",
            r"irrelevant.*point",
        ],
        "premature_closure": [
            r"already decided",
            r"no need to discuss",
            r"conclusion is obvious",
            r"let's just proceed",
            r"debate is unnecessary",
        ],
        "reasoning_action_mismatch": [
            r"even though.*should.*I will",
            r"better approach.*but doing",
            r"recommended.*but implementing",
        ],
    }

    # Severity levels by pattern type
    SEVERITY_MAP = {
        "silent_dissent": "MEDIUM",
        "input_dismissal": "HIGH",
        "premature_closure": "HIGH",
        "reasoning_action_mismatch": "HIGH",
    }

    def __init__(self):
        self._flags: list[MisalignmentFlag] = []

    def check_argument(
        self, argument: "DebateArgument", agent_id: str, turn_number: int, previous_context: str = ""
    ) -> list[MisalignmentFlag]:
        """
        Check an argument for misalignment patterns.

        Args:
            argument: The debate argument to check
            agent_id: Agent that produced the argument
            turn_number: Current debate turn
            previous_context: Context from previous turns

        Returns:
            List of MisalignmentFlag if patterns detected
        """
        new_flags = []
        text_to_check = argument.argument + " " + (argument.concession or "")

        for pattern_type, patterns in self.MISALIGNMENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_to_check, re.IGNORECASE):
                    flag = MisalignmentFlag(
                        flag_type=pattern_type,
                        pattern_matched=pattern,
                        severity=self.SEVERITY_MAP.get(pattern_type, "LOW"),
                        agent_id=agent_id,
                        turn_number=turn_number,
                        context=text_to_check[:200],
                    )
                    new_flags.append(flag)
                    self._flags.append(flag)
                    logger.warning(
                        f"V10 MISALIGNMENT DETECTED: {pattern_type} by {agent_id} "
                        f"at turn {turn_number} (pattern: {pattern})"
                    )

        return new_flags

    def get_all_flags(self) -> list[MisalignmentFlag]:
        """Get all detected misalignment flags."""
        return self._flags.copy()

    def get_high_severity_count(self) -> int:
        """Count HIGH severity flags."""
        return sum(1 for f in self._flags if f.severity == "HIGH")

    def should_escalate(self, threshold: int = 2) -> bool:
        """Check if misalignment level requires escalation."""
        return self.get_high_severity_count() >= threshold

    def reset(self):
        """Clear all flags."""
        self._flags.clear()


# Debate prompt templates
DEBATE_OPENER_PROMPT = """You are participating in a NEXUS Hive Mind debate.

TASK: {task}

DISAGREEMENT POINT: {topic}
- Your position: {your_position}
- Other agent's position: {other_position}

COMPARISON CONTEXT:
- Agreement score: {agreement_score:.0%}
- Your confidence: {your_confidence:.0%}

Present your OPENING ARGUMENT. You must:
1. State your position clearly
2. Provide evidence/reasoning for your position
3. Identify weaknesses in the opposing position
4. Suggest a path to resolution

Respond in this JSON format:
{{
    "position": "SUPPORT" or "OPPOSE",
    "target_point": "Which aspect of the disagreement you're addressing",
    "argument": "Your detailed argument (2-4 sentences)",
    "evidence": ["evidence1", "evidence2", ...],
    "proposed_modification": "Optional: how to merge positions",
    "concession": "Optional: what you concede to the other side"
}}
"""

DEBATE_RESPONSE_PROMPT = """You are responding in a NEXUS Hive Mind debate.

TASK: {task}

DISAGREEMENT POINT: {topic}
- Your original position: {your_position}
- Other agent's position: {other_position}

PREVIOUS ARGUMENT (by {other_agent}):
{previous_argument}

DEBATE HISTORY:
{debate_history}

Respond to this argument. You may:
- SUPPORT: Agree and build on their point
- OPPOSE: Counter-argue with evidence
- CONCEDE: Accept their point (partial or full)

Respond in this JSON format:
{{
    "position": "SUPPORT" or "OPPOSE" or "CONCEDE",
    "target_point": "Which point you're addressing",
    "argument": "Your response (2-4 sentences)",
    "evidence": ["evidence1", "evidence2", ...],
    "proposed_modification": "Optional: refined solution",
    "concession": "Optional: what you now concede"
}}

IMPORTANT: Good debate involves concessions. If the other agent made a valid point, acknowledge it.
"""

# Note: CONSENSUS_CHECK_PROMPT removed in V12.4.1 - replaced by CONSENSUS_SYSTEM_PROMPT in prompts.py


@dataclass
class DebatePhaseResult:
    """Result of Phase 2."""

    debate_result: DebateResult
    final_approach: str
    final_capabilities: list[str]
    final_mode: str
    was_skipped: bool = False
    skip_reason: str | None = None
    # V10 FIX F11: Misalignment tracking
    misalignment_flags: list[MisalignmentFlag] | None = None


class StrategicDebatePhase:
    """
    Phase 2: Strategic Debate

    Agents debate disagreements until consensus or forced vote.

    V9.2: Integrated session isolation for debate turns.
    """

    def __init__(
        self,
        gemini_driver: "BaseAsyncDriver",
        claude_driver: "BaseAsyncDriver",
        cost_estimator: CostEstimator,
        context_manager: HiveMindContextManager,
        debate_config: AdaptiveDebateConfig = None,
        task_id: str | None = None,
        session_manager: Optional["SwarmSessionManager"] = None,
    ):
        """
        Initialize Phase 2.

        Args:
            gemini_driver: Gemini driver
            claude_driver: Claude driver
            cost_estimator: Cost estimator
            context_manager: Context manager
            debate_config: Adaptive debate configuration
            task_id: V9.2 - Unique task identifier for session isolation
            session_manager: V9.2 - Optional session manager for persistence
        """
        self.gemini = gemini_driver
        self.claude = claude_driver
        self.cost_estimator = cost_estimator
        self.context_manager = context_manager
        self.debate_config = debate_config or AdaptiveDebateConfig()

        # V9.2: Session isolation
        self._task_id = task_id or generate_hivemind_task_id("debate")
        self._session_manager = session_manager
        self._session_integration: HiveMindSessionIntegration | None = None

        # V10 FIX F11: Misalignment detector
        self._misalignment_detector = MisalignmentDetector()

    async def execute(
        self, task: str, comparison: AnalysisComparison, complexity: TaskComplexity = TaskComplexity.MODERATE
    ) -> DebatePhaseResult:
        """
        Execute Phase 2: Strategic Debate.

        V9.2: Creates isolated sessions for each agent during debate.

        Args:
            task: The original task
            comparison: Analysis comparison from Phase 1
            complexity: Task complexity for adaptive params

        Returns:
            DebatePhaseResult with final approach
        """
        # Check if debate should be skipped
        if not comparison.needs_debate:
            logger.info("Phase 2: Skipping debate (high agreement)")
            return self._create_skipped_result(comparison)

        # V9.2: Initialize session integration for this phase
        self._session_integration = HiveMindSessionIntegration(
            task_id=self._task_id,
            phase_name="debate",
            context_manager=self.context_manager,
            session_manager=self._session_manager,
            complexity=complexity.value if hasattr(complexity, "value") else str(complexity),
        )
        self._session_integration.set_previous_phase("analysis")

        logger.info(f"Phase 2: Starting Strategic Debate ({len(comparison.disagreements)} disagreements)")

        # Get adaptive debate parameters
        params = self.debate_config.get_debate_params(
            complexity=complexity,
            initial_disagreement=1 - comparison.agreement_score,
            error_history=[],  # TODO: Get from session history
        )

        # Track debate state
        debate_history: list[DebateArgument] = []
        consensus_progress: list[float] = [comparison.agreement_score]
        current_speaker = "gemini"  # Alternates
        turn_number = 0

        # V13.0 CEREBRO LIVE: Get registry for agent name resolution
        registry = get_registry()

        # Debate each significant disagreement
        primary_disagreement = self._get_primary_disagreement(comparison.disagreements)

        while turn_number < params.max_turns:
            turn_number += 1

            # Check budget
            if not self.cost_estimator.can_afford("debate_turn"):
                logger.warning("Budget exceeded during debate")
                break

            # Get argument from current speaker
            argument = await self._get_argument(
                task=task,
                speaker=current_speaker,
                turn_number=turn_number,
                disagreement=primary_disagreement,
                comparison=comparison,
                debate_history=debate_history,
                params=params,
            )

            debate_history.append(argument)
            self.context_manager.add_debate_turn(turn_number, current_speaker, argument.argument)

            # V12.4: Record position in ConsensusTracker
            try:
                from ..consensus_tracker import get_consensus_tracker

                tracker = get_consensus_tracker()
                tracker.record(
                    self._task_id,
                    "debate",
                    current_speaker,
                    argument.position,
                    topic=argument.target_point or "approach",
                    confidence=1.0 if argument.position == "OPPOSE" else 0.7,
                )
            except Exception:
                pass  # Non-blocking

            # V12.4: EchoChamberGuard - detect sycophantic patterns (arxiv:2509.05396)
            try:
                from ..echo_chamber_guard import GuardActionType, get_echo_chamber_guard

                guard = get_echo_chamber_guard()
                guard_action = guard.check_turn(
                    agent_id=current_speaker,
                    position=argument.position,
                    evidence=argument.evidence or [],
                    turn_number=turn_number,
                )
                if guard_action.action_type == GuardActionType.FLAG_SYCOPHANCY:
                    logger.warning(f"Phase 2: Sycophantic flip detected - {guard_action.reason}")
                elif guard_action.action_type == GuardActionType.FORCE_DEVIL_ADVOCATE:
                    logger.info(f"Phase 2: Devil's advocate forced - {guard_action.reason}")
                elif guard_action.action_type == GuardActionType.INJECT_INDEPENDENCE:
                    logger.debug(f"Phase 2: Independence checkpoint at turn {turn_number}")
            except Exception:
                pass  # Non-blocking

            # V13.0 CEREBRO LIVE: Emit debate exchange
            next_speaker = registry.get_alternate(current_speaker) or "user"
            emit_agent_speak(current_speaker, argument.argument[:300], action_type="DEBATE")
            emit_agent_exchange(
                current_speaker, next_speaker, f"[{argument.position}] {argument.argument[:80]}", exchange_type="debate"
            )

            # V10 FIX F11: Check for inter-agent misalignment
            misalignment_flags = self._misalignment_detector.check_argument(
                argument=argument,
                agent_id=current_speaker,
                turn_number=turn_number,
                previous_context=self._format_debate_history(debate_history[:-1]) if len(debate_history) > 1 else "",
            )
            if misalignment_flags:
                logger.warning(
                    f"Phase 2: {len(misalignment_flags)} misalignment flag(s) detected at turn {turn_number}"
                )

            # V10 FIX F11: Escalate if too many HIGH severity flags
            if self._misalignment_detector.should_escalate(threshold=2):
                logger.error("Phase 2: Misalignment escalation - too many HIGH severity flags")
                return self._create_result(
                    debate_history=debate_history,
                    consensus={
                        "consensus_reached": False,
                        "consensus_score": 0.3,
                        "resolved_points": [],
                        "unresolved_points": ["misalignment_escalation"],
                        "final_approach": "ESCALATE: Manual review required due to inter-agent misalignment",
                        "final_capabilities": [],
                        "gemini_satisfaction": 0.2,
                        "claude_satisfaction": 0.2,
                        "reasoning": f"Misalignment detected: {len(self._misalignment_detector.get_all_flags())} flags",
                    },
                    status="MISALIGNMENT_ESCALATION",
                )

            # Record agent behavior for learning
            self.debate_config.record_agent_argument(
                agent_id=current_speaker,
                made_concession=argument.concession is not None,
                defended_position=argument.position == "OPPOSE",
                changed_position=argument.position == "CONCEDE",
            )

            # V12.4: Quorum-based early termination (Aegean-inspired, arxiv:2512.20184)
            # If both agents agree (CONCEDE or SUPPORT) in consecutive turns,
            # that's a natural quorum - skip the expensive LLM consensus check
            if len(debate_history) >= 2 and turn_number >= params.min_turns:
                last_two = debate_history[-2:]
                agreeing_positions = {"SUPPORT", "CONCEDE"}
                if (
                    last_two[0].position in agreeing_positions
                    and last_two[1].position in agreeing_positions
                    and last_two[0].agent_id != last_two[1].agent_id
                ):
                    # Both agents agreed - quorum reached
                    quorum_approach = argument.proposed_modification or argument.argument
                    logger.info(
                        f"Phase 2: Quorum reached at turn {turn_number} "
                        f"({last_two[0].agent_id}={last_two[0].position}, "
                        f"{last_two[1].agent_id}={last_two[1].position})"
                    )
                    return self._create_result(
                        debate_history=debate_history,
                        consensus={
                            "consensus_reached": True,
                            "consensus_score": 0.95,
                            "resolved_points": [primary_disagreement.topic],
                            "unresolved_points": [],
                            "final_approach": quorum_approach,
                            "final_capabilities": [],
                            "gemini_satisfaction": 0.85,
                            "claude_satisfaction": 0.85,
                            "reasoning": "Quorum: both agents agreed in consecutive turns",
                        },
                        status="QUORUM_CONSENSUS",
                    )

            # Check for consensus after minimum turns
            if turn_number >= params.min_turns:
                consensus = await self._check_consensus(
                    task=task, debate_history=debate_history, disagreement=primary_disagreement, comparison=comparison
                )

                consensus_progress.append(consensus["consensus_score"])

                if consensus["consensus_reached"]:
                    logger.info(f"Consensus reached at turn {turn_number}")
                    return self._create_result(
                        debate_history=debate_history, consensus=consensus, status="CONSENSUS_REACHED"
                    )

                # Check for early exit on high consensus
                if consensus["consensus_score"] >= params.early_exit_threshold:
                    logger.info(f"Early exit: consensus score {consensus['consensus_score']:.0%}")
                    return self._create_result(
                        debate_history=debate_history, consensus=consensus, status="EARLY_CONSENSUS"
                    )

                # Check if should force vote
                if self.debate_config.should_force_vote(turn_number, consensus_progress, params):
                    logger.info("Forcing vote due to stalled consensus")
                    return await self._force_vote(
                        task=task, debate_history=debate_history, comparison=comparison, params=params
                    )

            # Switch speaker (V8.4.0: via registry)
            registry = get_registry()
            current_speaker = registry.get_alternate(current_speaker) or current_speaker

        # Max turns reached without consensus - force vote
        logger.info(f"Max turns ({params.max_turns}) reached - forcing vote")
        return await self._force_vote(task=task, debate_history=debate_history, comparison=comparison, params=params)

    def _create_skipped_result(self, comparison: AnalysisComparison) -> DebatePhaseResult:
        """Create result when debate is skipped."""
        # Use higher confidence analysis
        if comparison.gemini_analysis.confidence >= comparison.claude_analysis.confidence:
            primary = comparison.gemini_analysis
        else:
            primary = comparison.claude_analysis

        return DebatePhaseResult(
            debate_result=DebateResult(
                status="IMMEDIATE_CONSENSUS",
                final_approach=primary.proposed_approach,
                final_capabilities=comparison.merged_capabilities,
                final_mode="SPECIALIST",  # V8.4.0: Mode doesn't depend on agent
                debate_history=[],
                total_turns=0,
                resolved_disagreements=[],
                unresolved_disagreements=[],
                consensus_confidence=comparison.agreement_score,
                gemini_satisfaction=0.8,
                claude_satisfaction=0.8,
            ),
            final_approach=primary.proposed_approach,
            final_capabilities=comparison.merged_capabilities,
            final_mode="PARALLEL",  # Default mode for skipped debate
            was_skipped=True,
            skip_reason=f"High agreement ({comparison.agreement_score:.0%})",
        )

    def _get_primary_disagreement(self, disagreements: list[Disagreement]) -> Disagreement:
        """Get the most significant disagreement to debate."""
        if not disagreements:
            # Create a default disagreement for the approach
            return Disagreement(topic="approach", gemini_position="default", claude_position="default", severity=0.5)

        # Sort by severity and return highest
        sorted_disagreements = sorted(disagreements, key=lambda d: d.severity, reverse=True)
        return sorted_disagreements[0]

    async def _get_argument(
        self,
        task: str,
        speaker: str,
        turn_number: int,
        disagreement: Disagreement,
        comparison: AnalysisComparison,
        debate_history: list[DebateArgument],
        params: DebateParams,
    ) -> DebateArgument:
        """Get an argument from a speaker."""
        # Determine positions (V8.4.0: via registry)
        registry = get_registry()

        if registry.is_gemini(speaker):
            your_position = disagreement.gemini_position
            other_position = disagreement.claude_position
            your_confidence = comparison.gemini_analysis.confidence
            driver = self.gemini
        else:
            your_position = disagreement.claude_position
            other_position = disagreement.gemini_position
            your_confidence = comparison.claude_analysis.confidence
            driver = self.claude

        # V12.4.1: Build dynamic user prompt (static system prompt handled separately)
        if turn_number == 1 or (turn_number == 2 and registry.is_claude(speaker)):
            # Opening argument - dynamic context only
            user_prompt = f"""TASK: {task}

DISAGREEMENT POINT: {disagreement.topic}
- Your position: {your_position}
- Other agent's position: {other_position}

COMPARISON CONTEXT:
- Agreement score: {comparison.agreement_score:.0%}
- Your confidence: {your_confidence:.0%}

Present your OPENING ARGUMENT on this disagreement."""
        else:
            # Response to previous argument
            previous = debate_history[-1]
            history_text = self._format_debate_history(debate_history)

            # V8.4.0: Use registry for display name of other agent
            other_display = registry.get_display_name(registry.get_alternate(speaker) or speaker)
            user_prompt = f"""TASK: {task}

DISAGREEMENT POINT: {disagreement.topic}
- Your original position: {your_position}
- Other agent's position: {other_position}

PREVIOUS ARGUMENT (by {other_display}):
{previous.argument}

DEBATE HISTORY:
{history_text}

Respond to this argument (SUPPORT, OPPOSE, or CONCEDE)."""

        # V9.2: Get isolated session for this speaker
        session_uuid = None
        if self._session_integration:
            session_uuid = self._session_integration.get_agent_session(speaker)
            logger.debug(
                f"Debate turn {turn_number}: {speaker} using session {session_uuid[:8] if session_uuid else 'none'}"
            )

        # V12.4.1: Use invoke() with static system prompt (cached by SDK)
        try:
            response = await driver.invoke(
                user_prompt,
                session_id=session_uuid,
                system_prompt=DEBATE_SYSTEM_PROMPT,  # Static, cached
                agent_name=speaker,
                agent_id=speaker,
            )

            # Check for errors
            if not response.is_success:
                raise RuntimeError(f"Debate turn failed: {response.error_message}")

            # Parse argument from DriverResponse.content
            argument_data = self._parse_argument_response(response.content)

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "debate_turn",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                # Fallback for legacy cost estimator
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("debate_turn", total_tokens)

            return DebateArgument(
                agent_id=speaker,
                turn_number=turn_number,
                position=argument_data.get("position", "OPPOSE"),
                target_point=argument_data.get("target_point", disagreement.topic),
                argument=argument_data.get("argument", response.content[:200]),
                evidence=argument_data.get("evidence", []),
                proposed_modification=argument_data.get("proposed_modification"),
                concession=argument_data.get("concession"),
            )

        except Exception as e:
            logger.error(f"Error getting argument from {speaker}: {e}")
            return DebateArgument(
                agent_id=speaker,
                turn_number=turn_number,
                position="OPPOSE",
                target_point=disagreement.topic,
                argument=f"Error generating argument: {e}",
                evidence=[],
            )

    def _parse_argument_response(self, response) -> dict[str, Any]:
        """Parse argument JSON from response."""
        from ..json_parser import parse_json_response

        # Get raw string for fallback
        raw = response
        if isinstance(raw, dict):
            raw = raw.get("content", raw.get("text", str(raw)))
        if not isinstance(raw, str):
            raw = str(raw)

        data = parse_json_response(response, "debate", default=None)
        if data is None:
            return {"argument": raw[:300]}
        return data

    def _format_debate_history(self, history: list[DebateArgument]) -> str:
        """Format debate history for prompts."""
        registry = get_registry()  # V8.4.0
        lines = []
        for arg in history[-5:]:  # Last 5 turns
            speaker = registry.get_display_name(arg.agent_id).upper()
            lines.append(f"[Turn {arg.turn_number}] {speaker} ({arg.position}):")
            lines.append(f"  {arg.argument}")
            if arg.concession:
                lines.append(f"  CONCESSION: {arg.concession}")
        return "\n".join(lines)

    async def _check_consensus(
        self,
        task: str,
        debate_history: list[DebateArgument],
        disagreement: Disagreement,
        comparison: AnalysisComparison,
    ) -> dict[str, Any]:
        """Check if consensus has been reached."""
        history_text = self._format_debate_history(debate_history)

        # V12.4.1: Build dynamic user prompt for consensus check
        user_prompt = f"""TASK: {task}

DEBATE HISTORY:
{history_text}

ORIGINAL DISAGREEMENT: {disagreement.topic}
- Gemini's original position: {disagreement.gemini_position}
- Claude's original position: {disagreement.claude_position}

Evaluate if consensus has been reached."""

        # V9.2: Get session for consensus check (use gemini's session)
        session_uuid = None
        if self._session_integration:
            session_uuid = self._session_integration.get_agent_session("gemini")

        # Use Gemini for consensus check (neutral)
        try:
            from ..json_parser import parse_json_response

            # V12.4.1: Use invoke() with consensus-specific system prompt
            response = await self.gemini.invoke(
                user_prompt,
                session_id=session_uuid,
                system_prompt=CONSENSUS_SYSTEM_PROMPT,  # Static, cached
                agent_name="gemini",
                agent_id="gemini",
            )

            # Check for errors
            if not response.is_success:
                raise RuntimeError(f"Consensus check failed: {response.error_message}")

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "check_consensus",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("check_consensus", total_tokens)

            data = parse_json_response(response.content, "consensus", default=None)
            if data is not None:
                return data

        except Exception as e:
            logger.error(f"Consensus check failed: {e}")

        # Default: no consensus
        return {
            "consensus_reached": False,
            "consensus_score": comparison.agreement_score,
            "resolved_points": [],
            "unresolved_points": [disagreement.topic],
            "final_approach": "",
            "final_capabilities": [],
            "gemini_satisfaction": 0.5,
            "claude_satisfaction": 0.5,
            "reasoning": "Consensus check failed",
        }

    async def _force_vote(
        self, task: str, debate_history: list[DebateArgument], comparison: AnalysisComparison, params: DebateParams
    ) -> DebatePhaseResult:
        """Force a vote when consensus cannot be reached."""
        # Calculate decision using debate config
        decision = self.debate_config.calculate_final_decision(
            gemini_position=comparison.gemini_analysis.proposed_approach,
            claude_position=comparison.claude_analysis.proposed_approach,
            gemini_confidence=comparison.gemini_analysis.confidence,
            claude_confidence=comparison.claude_analysis.confidence,
            gemini_satisfaction=0.5,  # Neutral for forced vote
            claude_satisfaction=0.5,
        )

        # Record outcome
        self.debate_config.record_debate_outcome(
            task_id=task[:50],
            complexity=TaskComplexity.MODERATE,  # TODO: Get actual complexity
            turns_used=len(debate_history),
            final_consensus=decision["gemini_score"] + decision["claude_score"] / 2,
            was_forced_vote=True,
            gemini_satisfaction=decision["gemini_score"],
            claude_satisfaction=decision["claude_score"],
            task_success=True,  # Will be updated by later phases
        )

        # Update agent satisfaction
        winner = decision["winner"]
        self.debate_config.update_agent_satisfaction("gemini", decision["gemini_score"], winner == "gemini")
        self.debate_config.update_agent_satisfaction("claude", decision["claude_score"], winner == "claude")

        return self._create_result(
            debate_history=debate_history,
            consensus={
                "consensus_reached": False,
                "consensus_score": max(decision["gemini_score"], decision["claude_score"]),
                "resolved_points": [],
                "unresolved_points": [d.topic for d in comparison.disagreements],
                "final_approach": decision["position"],
                "final_capabilities": comparison.merged_capabilities,
                "gemini_satisfaction": decision["gemini_score"],
                "claude_satisfaction": decision["claude_score"],
                "reasoning": decision["reason"],
            },
            status="FORCED_VOTE",
        )

    def _create_result(
        self, debate_history: list[DebateArgument], consensus: dict[str, Any], status: str
    ) -> DebatePhaseResult:
        """Create debate phase result."""
        # Determine mode based on outcome
        if consensus.get("consensus_reached", False):
            mode = "PARALLEL"  # Both agents work together
        elif consensus.get("gemini_satisfaction", 0) > consensus.get("claude_satisfaction", 0):
            mode = "LEAD_SUPPORT"  # Gemini leads
        else:
            mode = "LEAD_SUPPORT"  # Claude leads

        final_caps = consensus.get("final_capabilities", [])
        if not final_caps:
            final_caps = ["general"]

        debate_result = DebateResult(
            status=status,
            final_approach=consensus.get("final_approach", "Default approach"),
            final_capabilities=final_caps,
            final_mode=mode,
            debate_history=debate_history,
            total_turns=len(debate_history),
            resolved_disagreements=consensus.get("resolved_points", []),
            unresolved_disagreements=consensus.get("unresolved_points", []),
            consensus_confidence=consensus.get("consensus_score", 0.5),
            gemini_satisfaction=consensus.get("gemini_satisfaction", 0.5),
            claude_satisfaction=consensus.get("claude_satisfaction", 0.5),
        )

        # V12.4: TrajectoryScorer - evaluate debate trajectory quality (arxiv:2509.11035)
        try:
            from core.intelligence.reasoning.trajectory_scorer import get_trajectory_scorer

            _tscorer = get_trajectory_scorer()
            _trajectory_dicts = [
                {
                    "agent_id": arg.agent_id,
                    "position": arg.position,
                    "argument": arg.argument,
                    "evidence": arg.evidence,
                    "concession": arg.concession,
                    "turn_number": arg.turn_number,
                }
                for arg in debate_history
            ]
            _tresult = _tscorer.score_debate(_trajectory_dicts)
            logger.debug(
                f"TrajectoryScorer: best={_tresult.best_agent}, "
                f"quality={_tresult.debate_quality:.2f}, "
                f"conformity={len([c for c in _tresult.conformity_analysis if c.conformity_detected])}"
            )
        except Exception:
            pass

        return DebatePhaseResult(
            debate_result=debate_result,
            final_approach=debate_result.final_approach,
            final_capabilities=debate_result.final_capabilities,
            final_mode=mode,
            was_skipped=False,
            # V10 FIX F11: Include misalignment flags
            misalignment_flags=self._misalignment_detector.get_all_flags()
            if hasattr(self, "_misalignment_detector")
            else None,
        )
