"""
NEXUS V9.2 - Phase 1: Independent Analysis

Both agents analyze the task INDEPENDENTLY before comparing.
This ensures genuine diversity of thought, not rubber-stamping.

V9.2 Enhancement: Session Isolation for Parallel Agents
- Each agent gets unique session_uuid for isolation
- Context scope: TASK_ONLY (no cross-contamination)
- Model-aware context for capability reminders

Flow:
1. Gemini analyzes task -> IndependentAnalysis (session: uuid-001)
2. Claude analyzes task -> IndependentAnalysis (session: uuid-002) [parallel]
3. Compare analyses -> AnalysisComparison
4. Decide: needs_debate? -> Phase 2 or skip to Phase 3

Key Innovation:
- Agents DON'T see each other's analysis until both are complete
- Comparison identifies genuine disagreements
- High agreement (>85%) can skip debate entirely
- V9.2: Session isolation prevents context bleeding
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

# V13.0 CEREBRO LIVE: Telemetry for agent exchanges
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak

from ..base_phase import BasePhase
from ..context_manager import HiveMindContextManager
from ..context_scope import ContextScope, ScopedContext
from ..cost_estimator import CostEstimator
from ..prompts import ANALYSIS_SYSTEM_PROMPT  # V12.4.1: Static prompt for caching
from ..session_integration import HiveMindSessionIntegration, generate_hivemind_task_id
from ..types import (
    AnalysisComparison,
    Disagreement,
    IndependentAnalysis,
)

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm.session_manager import SwarmSessionManager

logger = logging.getLogger(__name__)


# V12.4.1 OPTIMIZATION: Static prompt moved to prompts.py for SDK-level caching
# The ANALYSIS_SYSTEM_PROMPT is now imported from ..prompts
# This enables 70-85% cost reduction on repeated HiveMind tasks (ArXiv 2601.06007)


@dataclass
class AnalysisPhaseResult:
    """Result of Phase 1."""

    gemini_analysis: IndependentAnalysis
    claude_analysis: IndependentAnalysis
    comparison: AnalysisComparison
    needs_debate: bool
    skip_reason: str | None = None


class IndependentAnalysisPhase(BasePhase):
    """
    Phase 1: Independent Analysis

    Both agents analyze the task separately, then compare results.

    V9.2: Integrated session isolation for parallel agent execution.
    """

    # Thresholds
    AGREEMENT_THRESHOLD = 0.85  # Above this, skip debate
    DISAGREEMENT_SEVERITY_THRESHOLD = 0.5  # Below this, disagreement is minor

    def __init__(
        self,
        gemini_driver: "BaseAsyncDriver | None" = None,
        claude_driver: "BaseAsyncDriver | None" = None,
        cost_estimator: CostEstimator | None = None,
        context_manager: HiveMindContextManager | None = None,
        task_id: str | None = None,
        session_manager: Optional["SwarmSessionManager"] = None,
        workspace_path: Optional["Path"] = None,  # V12.4.1 Epic 1.4: For V2 memory access
        *,
        agents: dict[str, "BaseAsyncDriver"] | None = None,
    ):
        """
        Initialize Phase 1.

        Args:
            gemini_driver: Gemini driver instance (legacy, prefer agents dict)
            claude_driver: Claude driver instance (legacy, prefer agents dict)
            cost_estimator: Cost estimator for budget control
            context_manager: Context manager for state
            task_id: V9.2 - Unique task identifier for session isolation
            session_manager: V9.2 - Optional session manager for persistence
            workspace_path: V12.4.1 - Workspace path for V2 memory access
            agents: V12.4 - Dict mapping provider IDs to driver instances
        """
        # V12.4: N-agent support via BasePhase
        if agents is None:
            agents = {}
            if gemini_driver is not None:
                agents["gemini"] = gemini_driver
            if claude_driver is not None:
                agents["claude"] = claude_driver
        super().__init__(agents=agents)
        self.agent_ids = list(self.agents.keys())
        self.cost_estimator = cost_estimator
        self.context_manager = context_manager

        # V9.2: Session isolation
        self._task_id = task_id or generate_hivemind_task_id("analysis")
        self._session_manager = session_manager
        self._session_integration: HiveMindSessionIntegration | None = None

        # V12.4.1 Epic 1.4: Workspace path for V2 memory
        self._workspace_path = workspace_path

    async def execute(self, task: str) -> AnalysisPhaseResult:
        """
        Execute Phase 1: Independent Analysis.

        V9.2: Creates isolated sessions for each agent to prevent context bleeding.

        Args:
            task: The task to analyze

        Returns:
            AnalysisPhaseResult with both analyses and comparison
        """
        logger.info("Phase 1: Starting Independent Analysis")

        # V9.2: Initialize session integration for this phase
        self._session_integration = HiveMindSessionIntegration(
            task_id=self._task_id,
            phase_name="analysis",
            context_manager=self.context_manager,
            session_manager=self._session_manager,
            complexity="MODERATE",  # Will be refined after analysis
        )

        # Add task to context
        self.context_manager.add_task(task)

        # Check budget
        if not self.cost_estimator.can_afford_multiple(
            {"independent_analysis_gemini": 1, "independent_analysis_claude": 1, "compare_analyses": 1}
        ):
            logger.error("Cannot afford Phase 1 operations")
            raise RuntimeError("Budget exceeded for Phase 1")

        # V9.2: Get isolated sessions for parallel execution
        parallel_sessions = self._session_integration.get_parallel_sessions(agents=["gemini", "claude"])
        logger.debug(f"Created isolated sessions: {parallel_sessions}")

        # V12.4: Retrieve relevant principles from EvolveR library (arxiv:2510.16079)
        principles_context = ""
        try:
            from ..principle_library import get_principle_library

            library = get_principle_library()
            # Derive tags from task keywords
            task_words = task.lower().split()
            task_tags = [w for w in task_words if len(w) > 4][:5]
            principles_context = library.format_for_prompt(tags=task_tags, top_k=3)
            if principles_context:
                logger.info(
                    f"Phase 1: Injecting {len(library.retrieve(tags=task_tags, top_k=3))} principles into analysis"
                )
        except Exception as e:
            logger.debug(f"Principle retrieval failed: {e}")

        # V12.4.1 Epic 1.4: Retrieve semantic memories (successes & blacklist)
        memory_context = ""
        try:
            memory_context = await self._retrieve_memory_context(task)
        except Exception as e:
            logger.debug(f"Memory retrieval failed: {e}")

        # V12.4.1 OPTIMIZATION: Build dynamic user prompt (static system prompt handled in methods)
        # Only task + principles + memories go in user prompt -> enables SDK caching of system prompt
        user_prompt = f"TASK: {task}"
        if principles_context:
            user_prompt += f"\n\nRELEVANT PRINCIPLES:\n{principles_context}"
        if memory_context:
            user_prompt += f"\n\n{memory_context}"

        # V12.4: Run analyses in parallel with isolated sessions for ALL agents
        analysis_tasks = []
        for agent_id, driver in self.agents.items():
            session_uuid = parallel_sessions.get(agent_id)
            analysis_tasks.append(self._analyze_with_agent(agent_id, driver, user_prompt, session_uuid))

        raw_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

        # Collect results by agent_id, handling errors
        analyses: dict[str, IndependentAnalysis] = {}
        for agent_id, result in zip(self.agent_ids, raw_results):
            if isinstance(result, Exception):
                logger.error(f"{agent_id} analysis failed: {result}")
                analyses[agent_id] = self._create_fallback_analysis(agent_id, str(result))
            else:
                analyses[agent_id] = result

        # Backward compat: set gemini_analysis/claude_analysis for downstream code
        gemini_analysis = analyses.get("gemini", list(analyses.values())[0] if analyses else None)
        claude_analysis = analyses.get("claude", list(analyses.values())[-1] if analyses else None)

        # Add all analyses to context
        for agent_id, analysis in analyses.items():
            self.context_manager.add_analysis(agent_id, analysis.to_dict())

        # V13.0 CEREBRO LIVE: Emit agent exchanges for analysis phase
        agent_id_list = list(analyses.keys())
        for i, (agent_id, analysis) in enumerate(analyses.items()):
            emit_agent_speak(agent_id, f"Analysis: {analysis.task_understanding[:200]}", action_type="ANALYSIS")
            # Emit exchange to next agent (round-robin)
            next_agent = agent_id_list[(i + 1) % len(agent_id_list)]
            emit_agent_exchange(
                agent_id,
                next_agent,
                f"Complexity: {analysis.complexity_assessment}, Confidence: {analysis.confidence:.0%}",
                exchange_type="analysis",
            )

        # V12.4: Evaluate analysis quality via ThoughtEvaluator
        try:
            from core.intelligence.reasoning.thought_evaluator import get_thought_evaluator

            evaluator = get_thought_evaluator()
            for agent_id, analysis in analyses.items():
                # Novelty: higher if approach is specific (more words = more detail)
                approach_len = len(analysis.proposed_approach.split())
                novelty = min(1.0, approach_len / 30.0)  # ~30 words = full novelty
                evaluator.score_thought(
                    f"{self._task_id}_{agent_id}_analysis",
                    content=analysis.proposed_approach[:200],
                    novelty=novelty,
                    relevance=0.8,  # Analyses are inherently relevant
                    confidence=analysis.confidence,
                    tags=[agent_id, "analysis"],
                )
        except Exception as e:
            logger.debug(f"ThoughtEvaluator scoring failed: {e}")

        # V12.4: Record agent positions in ConsensusTracker
        try:
            from ..consensus_tracker import get_consensus_tracker

            tracker = get_consensus_tracker()
            session_id = self._task_id
            for agent_id, analysis in analyses.items():
                tracker.record(
                    session_id,
                    "analysis",
                    agent_id,
                    analysis.proposed_approach[:100],
                    topic="approach",
                    confidence=analysis.confidence,
                )
                tracker.record(
                    session_id,
                    "analysis",
                    agent_id,
                    analysis.complexity_assessment,
                    topic="complexity",
                    confidence=analysis.confidence,
                )
        except Exception as e:
            logger.debug(f"ConsensusTracker recording failed: {e}")

        # V12.4: Multi-dimensional evaluation of analysis quality (CRM, arxiv:2511.16202)
        try:
            from core.intelligence.reasoning.evaluation_panel import get_evaluation_panel

            eval_panel = get_evaluation_panel()
            for agent_id, analysis in analyses.items():
                panel_result = eval_panel.evaluate(
                    output=analysis.proposed_approach[:500],
                    context=task[:200],
                )
                logger.debug(
                    f"Phase 1: {agent_id} analysis quality: "
                    f"composite={panel_result.composite_score:.2f}, "
                    f"weakest={panel_result.weakest_dimension.value}"
                )
        except Exception as e:
            logger.debug(f"EvaluationPanel scoring failed: {e}")

        # Compare analyses (V12.4: N-agent comparison)
        comparison = self._compare_analyses_multi(analyses)

        # Record costs
        self.cost_estimator.record_cost("compare_analyses", 500)

        # Decide if debate is needed
        needs_debate = self._needs_debate(comparison)
        skip_reason = None

        if not needs_debate:
            skip_reason = self._get_skip_reason(comparison)
            logger.info(f"Skipping debate: {skip_reason}")

        result = AnalysisPhaseResult(
            gemini_analysis=gemini_analysis,
            claude_analysis=claude_analysis,
            comparison=comparison,
            needs_debate=needs_debate,
            skip_reason=skip_reason,
        )

        logger.info(f"Phase 1 Complete: agreement={comparison.agreement_score:.0%}, needs_debate={needs_debate}")

        return result

    async def _analyze_with_gemini(self, prompt: str, session_uuid: str | None = None) -> IndependentAnalysis:
        """
        Get analysis from Gemini.

        V12.4.1: Uses invoke() with system_prompt for SDK-level caching.

        Args:
            prompt: Dynamic user prompt (task + principles)
            session_uuid: Unique session for isolation

        Returns:
            IndependentAnalysis from Gemini
        """
        logger.debug(f"Requesting Gemini analysis (session: {session_uuid[:8] if session_uuid else 'none'})")

        try:
            # V12.4.1 Epic 1.2: Use invoke_structured() with Pydantic schema
            from ..schemas import AnalysisOutput

            response = await self.gemini.invoke_structured(
                prompt,
                output_type=AnalysisOutput,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,  # Static, cached
                agent_name="gemini",
                agent_id="gemini",
            )

            # Check for errors
            if not response.is_success:
                raise RuntimeError(f"Gemini analysis failed: {response.error_message}")

            # Extract parsed Pydantic model (guaranteed type-safe)
            parsed = response.raw.get("parsed")
            if parsed is None:
                # Fallback: parse from JSON content
                import json

                from ..schemas import AnalysisOutput as Schema

                try:
                    data = json.loads(response.content)
                    parsed = Schema(**data)
                except Exception as err:
                    raise RuntimeError("Failed to parse structured output") from err

            analysis_data = {
                "task_understanding": parsed.task_understanding,
                "complexity_assessment": parsed.complexity_assessment.value,
                "proposed_approach": parsed.proposed_approach,
                "required_capabilities": parsed.required_capabilities,
                "potential_risks": parsed.potential_risks,
                "confidence": parsed.confidence,
                "reasoning": parsed.reasoning,
            }

            # Record actual token usage (not estimates)
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "independent_analysis_gemini",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                # Fallback for legacy cost estimator
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("independent_analysis_gemini", total_tokens)

            return IndependentAnalysis(agent_id="gemini", **analysis_data)

        except Exception as e:
            logger.error(f"Gemini analysis error: {e}")
            raise

    async def _analyze_with_claude(self, prompt: str, session_uuid: str | None = None) -> IndependentAnalysis:
        """
        Get analysis from Claude.

        V12.4.1: Uses invoke() with system_prompt for SDK-level caching.

        Args:
            prompt: Dynamic user prompt (task + principles)
            session_uuid: Unique session for isolation

        Returns:
            IndependentAnalysis from Claude
        """
        logger.debug(f"Requesting Claude analysis (session: {session_uuid[:8] if session_uuid else 'none'})")

        try:
            # V12.4.1 Epic 1.2: Use invoke_structured() with Pydantic schema
            from ..schemas import AnalysisOutput

            response = await self.claude.invoke_structured(
                prompt,
                output_type=AnalysisOutput,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,  # Static, cached
                agent_name="claude",
                agent_id="claude",
            )

            # Check for errors
            if not response.is_success:
                raise RuntimeError(f"Claude analysis failed: {response.error_message}")

            # Extract parsed Pydantic model (guaranteed type-safe)
            parsed = response.raw.get("parsed")
            if parsed is None:
                # Fallback: parse from JSON content
                import json

                from ..schemas import AnalysisOutput as Schema

                try:
                    data = json.loads(response.content)
                    parsed = Schema(**data)
                except Exception as err:
                    raise RuntimeError("Failed to parse structured output") from err

            analysis_data = {
                "task_understanding": parsed.task_understanding,
                "complexity_assessment": parsed.complexity_assessment.value,
                "proposed_approach": parsed.proposed_approach,
                "required_capabilities": parsed.required_capabilities,
                "potential_risks": parsed.potential_risks,
                "confidence": parsed.confidence,
                "reasoning": parsed.reasoning,
            }

            # Record actual token usage (not estimates)
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "independent_analysis_claude",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                # Fallback for legacy cost estimator
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("independent_analysis_claude", total_tokens)

            return IndependentAnalysis(agent_id="claude", **analysis_data)

        except Exception as e:
            logger.error(f"Claude analysis error: {e}")
            raise

    async def _analyze_with_agent(
        self, agent_id: str, driver: "BaseAsyncDriver", prompt: str, session_uuid: str | None = None
    ) -> IndependentAnalysis:
        """
        Get analysis from any agent.

        V12.4: Generic N-agent analysis method. The legacy _analyze_with_gemini
        and _analyze_with_claude methods are retained for backward compat but
        this is the canonical path.

        Args:
            agent_id: Agent identifier (e.g. "gemini", "claude", "openai")
            driver: The async driver instance for this agent
            prompt: Dynamic user prompt (task + principles)
            session_uuid: Unique session for isolation

        Returns:
            IndependentAnalysis from the agent
        """
        logger.debug(f"Requesting {agent_id} analysis (session: {session_uuid[:8] if session_uuid else 'none'})")

        try:
            from ..schemas import AnalysisOutput

            response = await driver.invoke_structured(
                prompt,
                output_type=AnalysisOutput,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                agent_name=agent_id,
                agent_id=agent_id,
            )

            if not response.is_success:
                raise RuntimeError(f"{agent_id} analysis failed: {response.error_message}")

            parsed = response.raw.get("parsed")
            if parsed is None:
                import json

                from ..schemas import AnalysisOutput as Schema

                try:
                    data = json.loads(response.content)
                    parsed = Schema(**data)
                except Exception as err:
                    raise RuntimeError("Failed to parse structured output") from err

            analysis_data = {
                "task_understanding": parsed.task_understanding,
                "complexity_assessment": parsed.complexity_assessment.value,
                "proposed_approach": parsed.proposed_approach,
                "required_capabilities": parsed.required_capabilities,
                "potential_risks": parsed.potential_risks,
                "confidence": parsed.confidence,
                "reasoning": parsed.reasoning,
            }

            cost_key = f"independent_analysis_{agent_id}"
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    cost_key,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost(cost_key, total_tokens)

            return IndependentAnalysis(agent_id=agent_id, **analysis_data)

        except Exception as e:
            logger.error(f"{agent_id} analysis error: {e}")
            raise

    def _create_fallback_analysis(self, agent_id: str, error: str) -> IndependentAnalysis:
        """Create fallback analysis when an agent fails."""
        return IndependentAnalysis(
            agent_id=agent_id,
            task_understanding=f"Error: {error}",
            complexity_assessment="MODERATE",
            proposed_approach="Fallback to other agent's analysis",
            required_capabilities=["general"],
            potential_risks=["agent_failure"],
            confidence=0.1,
            reasoning=f"Fallback due to error: {error}",
        )

    def _compare_analyses(self, gemini: IndependentAnalysis, claude: IndependentAnalysis) -> AnalysisComparison:
        """
        Compare two independent analyses to find disagreements.

        Returns:
            AnalysisComparison with disagreements and agreement score
        """
        disagreements = []
        agreement_points = 0
        total_points = 0

        # Compare complexity assessment
        total_points += 1
        if gemini.complexity_assessment == claude.complexity_assessment:
            agreement_points += 1
        else:
            disagreements.append(
                Disagreement(
                    topic="complexity",
                    positions={"gemini": gemini.complexity_assessment, "claude": claude.complexity_assessment},
                    severity=0.6,  # Complexity disagreement is significant
                )
            )

        # Compare required capabilities
        total_points += 1
        gemini_caps = set(c.lower() for c in gemini.required_capabilities)
        claude_caps = set(c.lower() for c in claude.required_capabilities)

        caps_overlap = len(gemini_caps & claude_caps)
        caps_total = len(gemini_caps | claude_caps)
        caps_agreement = caps_overlap / caps_total if caps_total > 0 else 1.0

        agreement_points += caps_agreement

        if caps_agreement < 0.7:
            disagreements.append(
                Disagreement(
                    topic="capabilities",
                    positions={"gemini": list(gemini_caps), "claude": list(claude_caps)},
                    severity=0.7,
                    gemini_only=list(gemini_caps - claude_caps),
                    claude_only=list(claude_caps - gemini_caps),
                )
            )

        # Compare approach (semantic similarity would be better, but using keyword overlap)
        total_points += 1
        approach_similarity = self._text_similarity(gemini.proposed_approach, claude.proposed_approach)
        agreement_points += approach_similarity

        if approach_similarity < 0.6:
            disagreements.append(
                Disagreement(
                    topic="approach",
                    positions={"gemini": gemini.proposed_approach, "claude": claude.proposed_approach},
                    severity=0.8,  # Approach disagreement is very significant
                )
            )

        # Compare risks
        total_points += 1
        gemini_risks = set(r.lower() for r in gemini.potential_risks)
        claude_risks = set(r.lower() for r in claude.potential_risks)

        risks_overlap = len(gemini_risks & claude_risks)
        risks_total = len(gemini_risks | claude_risks)
        risks_agreement = risks_overlap / risks_total if risks_total > 0 else 1.0

        agreement_points += risks_agreement

        if risks_agreement < 0.5:
            disagreements.append(
                Disagreement(
                    topic="risks",
                    positions={"gemini": list(gemini_risks), "claude": list(claude_risks)},
                    severity=0.5,
                    gemini_only=list(gemini_risks - claude_risks),
                    claude_only=list(claude_risks - gemini_risks),
                )
            )

        # Compare confidence (large gap is a disagreement)
        total_points += 1
        confidence_gap = abs(gemini.confidence - claude.confidence)
        confidence_agreement = 1 - confidence_gap
        agreement_points += confidence_agreement

        if confidence_gap > 0.3:
            disagreements.append(
                Disagreement(
                    topic="confidence",
                    positions={"gemini": gemini.confidence, "claude": claude.confidence},
                    severity=0.4,
                )
            )

        # Calculate overall agreement
        agreement_score = agreement_points / total_points if total_points > 0 else 0.5

        # Merge capabilities and risks for final output
        merged_capabilities = list(gemini_caps | claude_caps)
        merged_risks = list(gemini_risks | claude_risks)

        # Decide if debate needed
        needs_debate = agreement_score < self.AGREEMENT_THRESHOLD or any(
            d.severity > self.DISAGREEMENT_SEVERITY_THRESHOLD for d in disagreements
        )

        return AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude},
            disagreements=disagreements,
            agreement_score=agreement_score,
            needs_debate=needs_debate,
            merged_capabilities=merged_capabilities,
            merged_risks=merged_risks,
        )

    def _compare_analyses_multi(self, analyses: dict[str, IndependentAnalysis]) -> AnalysisComparison:
        """
        Compare N independent analyses to find disagreements.

        V12.4: Generalized from 2-agent to N-agent comparison.
        For 2 agents, delegates to the original pairwise method.
        For N>2 agents, computes pairwise agreement and merges.

        Args:
            analyses: Dict mapping agent_id to IndependentAnalysis

        Returns:
            AnalysisComparison with disagreements and agreement score
        """
        agent_ids = list(analyses.keys())

        # Fast path: 2 agents (or fewer) -- use original pairwise method
        if len(agent_ids) <= 2:
            vals = list(analyses.values())
            a = vals[0] if vals else self._create_fallback_analysis("unknown", "no agents")
            b = vals[1] if len(vals) > 1 else a
            return self._compare_analyses(a, b)

        # N-agent comparison: compute average pairwise agreement
        from itertools import combinations

        disagreements = []
        total_agreement = 0.0
        pair_count = 0

        all_caps: set[str] = set()
        all_risks: set[str] = set()

        for a in analyses.values():
            all_caps.update(c.lower() for c in a.required_capabilities)
            all_risks.update(r.lower() for r in a.potential_risks)

        # Check complexity consensus
        complexity_values = {a.complexity_assessment for a in analyses.values()}
        if len(complexity_values) > 1:
            disagreements.append(
                Disagreement(
                    topic="complexity",
                    positions={aid: a.complexity_assessment for aid, a in analyses.items()},
                    severity=0.6,
                )
            )

        # Check approach similarity (average pairwise)
        approach_agreements = []
        for (id_a, a), (id_b, b) in combinations(analyses.items(), 2):
            sim = self._text_similarity(a.proposed_approach, b.proposed_approach)
            approach_agreements.append(sim)
            pair_count += 1

        avg_approach = sum(approach_agreements) / len(approach_agreements) if approach_agreements else 1.0
        if avg_approach < 0.6:
            disagreements.append(
                Disagreement(
                    topic="approach",
                    positions={aid: a.proposed_approach for aid, a in analyses.items()},
                    severity=0.8,
                )
            )

        # Check confidence spread
        confidences = [a.confidence for a in analyses.values()]
        confidence_spread = max(confidences) - min(confidences)
        if confidence_spread > 0.3:
            disagreements.append(
                Disagreement(
                    topic="confidence",
                    positions={aid: a.confidence for aid, a in analyses.items()},
                    severity=0.4,
                )
            )

        # Calculate overall agreement score from multiple dimensions
        complexity_agree = 1.0 if len(complexity_values) == 1 else 1.0 / len(complexity_values)
        confidence_agree = 1.0 - confidence_spread
        agreement_score = (complexity_agree + avg_approach + confidence_agree) / 3.0

        needs_debate = agreement_score < self.AGREEMENT_THRESHOLD or any(
            d.severity > self.DISAGREEMENT_SEVERITY_THRESHOLD for d in disagreements
        )

        return AnalysisComparison(
            analyses=analyses,
            disagreements=disagreements,
            agreement_score=agreement_score,
            needs_debate=needs_debate,
            merged_capabilities=list(all_caps),
            merged_risks=list(all_risks),
        )

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity using word overlap."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        # Remove common stop words
        stop_words = {"the", "a", "an", "to", "for", "of", "in", "on", "with", "and", "or", "is", "are"}
        words1 = words1 - stop_words
        words2 = words2 - stop_words

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union

    def _needs_debate(self, comparison: AnalysisComparison) -> bool:
        """Determine if debate is needed based on comparison.

        Uses DyLAN-style confidence-weighted scoring: agents with poor
        calibration or detected cognitive degradation trigger debate
        even at moderate agreement levels (V12.4).
        """
        # Already calculated in comparison, but add extra checks

        # Always debate if agreement is low
        if comparison.agreement_score < 0.7:
            return True

        # Debate if any severe disagreement
        severe_disagreements = [d for d in comparison.disagreements if d.severity > 0.6]
        if severe_disagreements:
            return True

        # Debate if confidence gap is large (V12.4: check all agent pairs)
        all_analyses = list(comparison.analyses.values())
        if len(all_analyses) >= 2:
            confidences = [a.confidence for a in all_analyses]
            confidence_gap = max(confidences) - min(confidences)
            if confidence_gap > 0.4:
                return True

        # V12.4: Check quality profiles - poorly calibrated agents
        # should trigger debate even at moderate agreement
        try:
            from core.intelligence.reasoning.cognitive_degradation import get_degradation_detector
            from core.intelligence.reasoning.reasoning_quality_scorer import get_quality_scorer

            scorer = get_quality_scorer()
            detector = get_degradation_detector()
            for agent_id in comparison.analyses.keys():
                profile = scorer.get_agent_profile(agent_id)
                if profile and profile.avg_calibration < 0.5 and comparison.agreement_score < 0.9:
                    return True  # Low calibration + moderate agreement = debate
                signal = detector.check_agent(agent_id)
                if signal.degraded and comparison.agreement_score < 0.9:
                    return True  # Degraded agent + moderate agreement = debate
        except Exception:
            pass  # Quality checks are advisory

        # High agreement, no severe issues = skip debate
        return comparison.needs_debate

    def _get_skip_reason(self, comparison: AnalysisComparison) -> str:
        """Get reason for skipping debate."""
        if comparison.agreement_score >= 0.95:
            return "Near-perfect agreement (>95%)"
        elif comparison.agreement_score >= 0.9:
            return "Very high agreement (>90%)"
        elif comparison.agreement_score >= self.AGREEMENT_THRESHOLD:
            return f"High agreement ({comparison.agreement_score:.0%})"
        elif not comparison.disagreements:
            return "No significant disagreements found"
        else:
            return "Minor disagreements only"

    def get_consensus_summary(self, result: AnalysisPhaseResult) -> dict[str, Any]:
        """
        Get a summary of the consensus (or disagreements) for Phase 2 or 3.

        Args:
            result: Phase 1 result

        Returns:
            Summary dict for next phase
        """
        comparison = result.comparison

        # Use highest confidence analysis as primary (V12.4: N-agent aware)
        all_analyses = list(comparison.analyses.values()) if comparison.analyses else []
        if all_analyses:
            primary = max(all_analyses, key=lambda a: a.confidence)
        elif result.gemini_analysis is not None:
            primary = result.gemini_analysis
        else:
            primary = result.claude_analysis

        return {
            "task_understanding": primary.task_understanding,
            "complexity": primary.complexity_assessment,
            "approach": primary.proposed_approach if not result.needs_debate else "TO_BE_DEBATED",
            "capabilities": comparison.merged_capabilities,
            "risks": comparison.merged_risks,
            "agreement_score": comparison.agreement_score,
            "disagreement_topics": [d.topic for d in comparison.disagreements],
            "primary_agent": primary.agent_id,
            "needs_debate": result.needs_debate,
        }

    async def _retrieve_memory_context(self, task: str) -> str:
        """
        Retrieve semantic memory context from V2 memories.

        V12.4.1 Epic 1.4: Query SuccessMemoryV2 and StrategyBlacklistV2
        for historical context to improve analysis quality.

        Args:
            task: Task description to query against

        Returns:
            Formatted memory context string for injection into prompt
        """
        context_parts = []

        try:
            # Import V2 memories
            from core.memory_pkg.memory import (
                StrategyBlacklistV2,
                SuccessMemoryV2,
            )

            # Get workspace path (injected in __init__ or fallback to default)
            workspace_path = self._workspace_path
            if workspace_path is None:
                # Fallback: try to infer from current working directory
                workspace_path = Path.cwd() / "workspace"
                logger.debug(f"Using fallback workspace_path: {workspace_path}")

            # Initialize V2 memories (lazy-loaded, auto-migration)
            success_memory = SuccessMemoryV2(workspace_path)
            blacklist = StrategyBlacklistV2(workspace_path)

            # 1. Check blacklist FIRST (anti-circular retry prevention)
            is_blacklisted, block_reason = blacklist.is_blacklisted(task)

            if is_blacklisted:
                context_parts.append("[warning]️  BLACKLIST WARNING")
                context_parts.append("=" * 60)
                context_parts.append(block_reason)
                context_parts.append("")

                # Suggest alternatives
                alternatives = blacklist.suggest_alternatives(task, limit=3)
                if alternatives:
                    context_parts.append("💡 Suggested Alternatives:")
                    for alt in alternatives:
                        context_parts.append(f"  - {alt}")
                    context_parts.append("")

                logger.warning("Phase 1: Task matches blacklisted strategy (semantic similarity)")

            # 2. Retrieve similar past successes (even if blacklisted, for comparison)
            similar_successes = success_memory.find_similar_tasks(
                task,
                limit=3,
                min_score=0.2,  # Lower threshold for informational purposes
            )

            if similar_successes:
                context_parts.append("📚 SIMILAR PAST SUCCESSES")
                context_parts.append("=" * 60)

                for i, (entry, similarity) in enumerate(similar_successes, 1):
                    context_parts.append(f"{i}. {entry.description} (similarity: {similarity:.2f})")
                    context_parts.append(f"   Mode: {entry.swarm_mode}")
                    context_parts.append(f"   Complexity: {entry.complexity}")
                    context_parts.append(f"   Quality: {entry.quality_score:.2f}/1.00")
                    context_parts.append(f"   Duration: {entry.duration_seconds:.1f}s")
                    if entry.domains:
                        context_parts.append(f"   Domains: {', '.join(entry.domains)}")
                    context_parts.append("")

                logger.info(f"Phase 1: Injected {len(similar_successes)} similar past successes")

            # 3. Get best mode recommendation based on memory
            best_mode_result = success_memory.get_best_mode_for_similar(task, min_similarity=0.2)

            if best_mode_result:
                mode, task_id, score = best_mode_result
                context_parts.append("💭 MEMORY-BASED RECOMMENDATION")
                context_parts.append("=" * 60)
                context_parts.append(
                    f"Based on similar past successes, consider using '{mode}' mode (confidence: {score:.0%})"
                )
                context_parts.append("")

                logger.info(f"Phase 1: Memory recommends mode={mode} (confidence={score:.0%})")

            # Return formatted context
            if context_parts:
                return "HISTORICAL MEMORY CONTEXT:\n" + "\n".join(context_parts)
            else:
                return ""

        except ImportError as e:
            logger.debug(f"V2 memory modules not available: {e}")
            return ""
        except Exception as e:
            logger.warning(f"Memory retrieval failed: {e}", exc_info=True)
            return ""

    # V9.2: Session accessors for subsequent phases
    @property
    def task_id(self) -> str:
        """Get task ID for session continuity."""
        return self._task_id

    @property
    def session_integration(self) -> HiveMindSessionIntegration | None:
        """Get session integration for subsequent phases."""
        return self._session_integration

    def get_phase_transition_context(self, result: AnalysisPhaseResult, to_phase: str) -> "ScopedContext":
        """
        Create scoped context for transition to next phase.

        V9.2: Controlled inheritance - passes results summary, not full history.

        Args:
            result: Phase 1 result
            to_phase: Target phase name (e.g., "debate", "architecture")

        Returns:
            ScopedContext for the next phase
        """
        if self._session_integration is None:
            raise RuntimeError("Session integration not initialized. Call execute() first.")

        # Determine complexity from analysis
        if result.claude_analysis.complexity_assessment in ["COMPLEX", "EXPERT"]:
            pass

        # Create scoped context with appropriate inheritance
        return self._session_integration.create_phase_context(
            scope=ContextScope.TASK_PLUS_RESULTS,
            agent_id=None,  # Will be set by next phase
            relevant_files=[],  # Could extract from analysis if available
        )
