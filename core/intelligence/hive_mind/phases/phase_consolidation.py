"""
NEXUS V9.2 - Phase 7: Knowledge Consolidation

Post-task debate between agents about what to retain.
Implements user's decision: agents debate what knowledge to keep.

V9.2 Enhancement: Session Isolation for Parallel Reflection
- Each agent reflects with isolated session
- Context inheritance from Phase 6 (TASK_PLUS_RESULTS scope)
- Model-aware context for reflection capabilities

Flow:
1. Gemini reflects on task outcome (session: uuid-cons-G)
2. Claude reflects on task outcome (session: uuid-cons-C) [parallel]
3. Agents debate: What learned? What to keep?
4. User Breakpoint: KNOWLEDGE_CONSOLIDATION
5. Archive decisions to Registry and RAG

Key Innovation:
- Post-task reflection improves future performance
- Agents decide together what's worth keeping
- Patterns/antipatterns extracted for learning
- Spawned agents evaluated for retention
- V9.2: Session isolation for parallel reflection
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..agent_registry import AgentRegistry
from ..base_phase import BasePhase
from ..context_manager import HiveMindContextManager
from ..cost_estimator import CostEstimator
from ..prompts import CONSOLIDATION_SYSTEM_PROMPT  # V12.4.1: Static prompt for caching
from ..session_integration import HiveMindSessionIntegration, generate_hivemind_task_id
from ..types import (
    AgentRetention,
    KnowledgeConsolidation,
    KnowledgeEntry,
    RetentionDecision,
)
from ..user_interaction import UserInteractionHandler

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm.session_manager import SwarmSessionManager
    from core.memory_pkg.memory.project_memory import ProjectMemory

logger = logging.getLogger(__name__)


# Reflection prompt
REFLECTION_PROMPT = """Reflect on this NEXUS Hive Mind task execution.

TASK: {task}

EXECUTION SUMMARY:
- Success: {success}
- Total Duration: {duration:.1f}s
- Steps Completed: {steps_completed}
- Issues Encountered: {issues_count}

APPROACH USED: {approach}

AGENTS USED: {agents_used}
AGENTS SPAWNED: {agents_spawned}

Reflect on:
1. What worked well?
2. What could be improved?
3. What patterns should be remembered?
4. What mistakes should be avoided?
5. Should spawned agents be kept?

Respond in JSON format:
{{
    "learned_patterns": ["pattern1", "pattern2", ...],
    "learned_antipatterns": ["avoid1", "avoid2", ...],
    "new_capabilities_identified": ["cap1", "cap2", ...],
    "agents_to_retain": [
        {{"agent_id": "agent1", "reason": "why keep", "vote": "KEEP_PERMANENT|ARCHIVE_KNOWLEDGE|MERGE_INTO_EXISTING|DELETE"}}
    ],
    "knowledge_to_archive": [
        {{"category": "pattern|antipattern|recipe|insight", "content": "...", "usefulness": 0.0-1.0, "tags": ["tag1", ...]}}
    ],
    "nexus_improvements": ["suggestion1", ...],
    "overall_reflection": "Your thoughts on the task",
    "satisfaction": 0.0 to 1.0
}}
"""

CONSOLIDATION_DEBATE_PROMPT = """You are debating knowledge consolidation with the other agent.

TASK: {task}

YOUR REFLECTION:
{your_reflection}

OTHER AGENT'S REFLECTION:
{other_reflection}

Discuss and propose final consolidation decisions.
Focus on: What should definitely be kept? What's debatable? What should be discarded?

Respond in JSON format:
{{
    "agreed_patterns": ["pattern1", ...],
    "debated_patterns": [{{"pattern": "...", "your_vote": "keep|discard", "reason": "..."}}],
    "agreed_agent_decisions": [{{"agent_id": "...", "decision": "KEEP_PERMANENT|DELETE", "both_agreed": true}}],
    "debated_agent_decisions": [{{"agent_id": "...", "your_vote": "KEEP|DELETE", "reason": "..."}}],
    "final_recommendation": "Overall recommendation for consolidation"
}}
"""


@dataclass
class ConsolidationPhaseResult:
    """Result of Phase 7."""

    consolidation: KnowledgeConsolidation
    gemini_reflection: str
    claude_reflection: str
    user_decision: str
    archived_to_rag: int
    agents_retained: list[str]
    agents_deleted: list[str]


class KnowledgeConsolidationPhase(BasePhase):
    """
    Phase 7: Knowledge Consolidation

    Post-task debate on what to retain.

    V9.2: Integrated session isolation for parallel reflection.
    """

    def __init__(
        self,
        gemini_driver: "BaseAsyncDriver | None" = None,
        claude_driver: "BaseAsyncDriver | None" = None,
        cost_estimator: CostEstimator | None = None,
        context_manager: HiveMindContextManager | None = None,
        agent_registry: AgentRegistry | None = None,
        user_handler: UserInteractionHandler | None = None,
        project_memory: "ProjectMemory" = None,
        task_id: str | None = None,
        session_manager: Optional["SwarmSessionManager"] = None,
        workspace_path: Path | None = None,  # V12.4.1 Epic 1.4: For V2 memory recording
        *,
        agents: dict[str, "BaseAsyncDriver"] | None = None,
    ):
        """
        Initialize Phase 7.

        Args:
            gemini_driver: Gemini driver (legacy, prefer agents dict)
            claude_driver: Claude driver (legacy, prefer agents dict)
            cost_estimator: Cost estimator
            context_manager: Context manager
            agent_registry: Agent registry
            user_handler: User interaction handler
            project_memory: Optional ProjectMemory for RAG archival
            task_id: V9.2 - Unique task identifier for session isolation
            session_manager: V9.2 - Optional session manager for persistence
            workspace_path: V12.4.1 - Workspace path for V2 memory recording
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
        self.registry = agent_registry
        self.user_handler = user_handler
        self.project_memory = project_memory

        # V9.2: Session isolation
        self._task_id = task_id or generate_hivemind_task_id("consolidation")
        self._session_manager = session_manager
        self._session_integration: HiveMindSessionIntegration | None = None

        # V12.4.1 Epic 1.4: Workspace path for V2 memory recording
        self._workspace_path = workspace_path

    async def execute(
        self,
        task: str,
        success: bool,
        duration: float,
        steps_completed: int,
        issues_count: int,
        approach: str,
        agents_used: list[str],
        agents_spawned: list[str],
    ) -> ConsolidationPhaseResult:
        """
        Execute Phase 7: Knowledge Consolidation.

        Args:
            task: Original task
            success: Whether task succeeded
            duration: Total execution duration
            steps_completed: Number of steps completed
            issues_count: Number of issues encountered
            approach: Approach used
            agents_used: Agents that were used
            agents_spawned: Agents that were spawned

        Returns:
            ConsolidationPhaseResult with decisions
        """
        logger.info("Phase 7: Starting Knowledge Consolidation")

        # V9.2: Initialize session integration with TASK_PLUS_RESULTS scope
        self._session_integration = HiveMindSessionIntegration(
            task_id=self._task_id,
            phase_name="consolidation",
            context_manager=self.context_manager,
            session_manager=self._session_manager,
            complexity="MODERATE",
        )
        self._session_integration.set_previous_phase("execution")

        # V9.2: Get isolated sessions for parallel reflection (V12.4: use actual agent IDs)
        parallel_sessions = self._session_integration.get_parallel_sessions(agents=self.agent_ids)
        logger.debug(f"Created isolated consolidation sessions: {parallel_sessions}")

        # Check budget
        if not self.cost_estimator.can_afford_multiple(
            {"reflection_gemini": 1, "reflection_claude": 1, "decide_retention": 1, "consolidate": 1}
        ):
            logger.warning("Limited budget for consolidation")
            return self._create_minimal_result(task, success)

        # Get reflections in parallel
        reflection_prompt = REFLECTION_PROMPT.format(
            task=task,
            success="Yes" if success else "No",
            duration=duration,
            steps_completed=steps_completed,
            issues_count=issues_count,
            approach=approach,
            agents_used=", ".join(agents_used),
            agents_spawned=", ".join(agents_spawned) or "None",
        )

        gemini_task = self._reflect_with_gemini(reflection_prompt, parallel_sessions.get("gemini"))
        claude_task = self._reflect_with_claude(reflection_prompt, parallel_sessions.get("claude"))

        gemini_result, claude_result = await asyncio.gather(gemini_task, claude_task, return_exceptions=True)

        # Handle errors
        if isinstance(gemini_result, Exception):
            gemini_result = f"Reflection failed: {gemini_result}"
        if isinstance(claude_result, Exception):
            claude_result = f"Reflection failed: {claude_result}"

        # Debate consolidation decisions
        consolidation = await self._debate_consolidation(
            task=task, gemini_reflection=gemini_result, claude_reflection=claude_result, success=success
        )

        # User breakpoint
        user_response = self.user_handler.knowledge_consolidation(
            learned_patterns=consolidation.learned_patterns,
            agents_to_retain=[
                {"agent_id": ar.agent_id, "reason": ar.reason}
                for ar in consolidation.agents_retention
                if ar.decision in (RetentionDecision.KEEP_PERMANENT, RetentionDecision.ARCHIVE_KNOWLEDGE)
            ],
            knowledge_to_archive=[ke.content[:100] for ke in consolidation.knowledge_to_archive],
        )

        # Apply decisions based on user choice
        agents_retained = []
        agents_deleted = []
        archived_count = 0

        if user_response.chosen_option in ("accept_all", "selective"):
            # Apply agent retention decisions
            agents_retained, agents_deleted = self._apply_agent_decisions(consolidation.agents_retention)

            # Archive knowledge to RAG
            archived_count = self._archive_knowledge(consolidation.knowledge_to_archive, task)

            # Add insights to context manager
            for pattern in consolidation.learned_patterns:
                self.context_manager.add_insight(category="pattern", content=pattern, tags=["hive_mind", "learned"])

            for antipattern in consolidation.learned_antipatterns:
                self.context_manager.add_insight(
                    category="antipattern", content=antipattern, tags=["hive_mind", "avoid"]
                )

        # Record costs
        self.cost_estimator.record_cost("decide_retention", 500)
        self.cost_estimator.record_cost("consolidate", 300)

        # V12.4: Detect patterns and crystallize skills from execution history
        try:
            from core.memory_pkg.skills.crystallizer import get_crystallizer

            crystallizer = get_crystallizer()
            patterns = crystallizer.detect_patterns()
            if patterns:
                skills = crystallizer.crystallize()
                logger.info(f"Phase 7: Crystallized {len(skills)} skills from {len(patterns)} patterns")
        except Exception as e:
            logger.debug(f"Skill crystallization failed: {e}")

        # V12.4: Extract principles for EvolveR library (arxiv:2510.16079)
        try:
            from ..principle_library import get_principle_library

            library = get_principle_library()
            # Extract principles from learned patterns
            for pattern in consolidation.learned_patterns:
                library.add_principle(
                    text=pattern,
                    tags=["pattern", "hive_mind"],
                    source_task=task[:100],
                )
            # Extract anti-principles from antipatterns
            for antipattern in consolidation.learned_antipatterns:
                p = library.add_principle(
                    text=f"AVOID: {antipattern}",
                    tags=["antipattern", "hive_mind"],
                    source_task=task[:100],
                )
                # Anti-patterns start with a failure recorded
                p.record_usage(success=False)
            logger.info(
                f"Phase 7: Extracted {len(consolidation.learned_patterns)} principles, "
                f"{len(consolidation.learned_antipatterns)} anti-principles to library"
            )
        except Exception as e:
            logger.debug(f"Principle extraction failed: {e}")

        # V12.4: AutoMemory - record task outcome for future mode/lead suggestions
        try:
            from core.memory_pkg.memory.auto_memory import get_auto_memory

            auto_mem = get_auto_memory()
            # Determine swarm mode from approach text
            swarm_mode = approach.split()[0] if approach else "UNKNOWN"
            # Determine lead agent (first in list)
            lead = agents_used[0] if agents_used else "unknown"
            if success:
                auto_mem.record_success(
                    task_type="hive_mind",
                    task_description=task[:200],
                    swarm_mode=swarm_mode,
                    lead_agent=lead,
                    duration_seconds=duration,
                    score=consolidation.confidence_in_decisions,
                )
            else:
                auto_mem.record_failure(
                    task_type="hive_mind",
                    task_description=task[:200],
                    swarm_mode=swarm_mode,
                    lead_agent=lead,
                    duration_seconds=duration,
                    reason="task_failed",
                )
            logger.info(f"Phase 7: AutoMemory recorded {'success' if success else 'failure'} for {swarm_mode}/{lead}")
        except Exception as e:
            logger.debug(f"AutoMemory recording failed: {e}")

        # V12.4.1 Epic 1.4: Record to V2 memories (semantic, LanceDB-backed)
        if self._workspace_path:
            try:
                from core.memory_pkg.memory import StrategyBlacklistV2, SuccessMemoryV2

                if success:
                    # Record success to SuccessMemoryV2
                    success_memory = SuccessMemoryV2(self._workspace_path)

                    # Create mock analysis and result objects for record_success()
                    # The V2 method expects TaskAnalysis and ExecutionResult, but we have
                    # consolidation data. We'll create duck-typed objects.
                    class MockAnalysis:
                        def __init__(self, task_desc, complexity, domains):
                            self.raw_input = task_desc
                            self.complexity = complexity
                            self.domains = domains
                            self.primary_domain = domains[0] if domains else None

                    class MockResult:
                        def __init__(self, mode, agents, duration):
                            self.selected_mode = mode
                            self.agent_outputs = [type("obj", (), {"agent_id": a}) for a in agents]
                            self.total_time_seconds = duration
                            self.status = "completed"
                            self.total_rounds = steps_completed

                    # Infer complexity from duration and steps
                    if duration > 120 or steps_completed > 10:
                        complexity_str = "COMPLEX"
                    elif duration > 60 or steps_completed > 5:
                        complexity_str = "MODERATE"
                    else:
                        complexity_str = "SIMPLE"

                    # Infer domains from task keywords
                    domains = []
                    task_lower = task.lower()
                    if any(word in task_lower for word in ["code", "implement", "fix", "debug", "refactor"]):
                        domains.append("coding")
                    if any(word in task_lower for word in ["security", "auth", "encrypt", "vulnerability"]):
                        domains.append("security")
                    if any(word in task_lower for word in ["test", "validate", "verify"]):
                        domains.append("testing")
                    if any(word in task_lower for word in ["research", "analyze", "investigate"]):
                        domains.append("research")
                    if not domains:
                        domains.append("general")

                    mock_analysis = MockAnalysis(task, complexity_str, domains)
                    mock_result = MockResult(swarm_mode, agents_used, duration)

                    # Quality score from consolidation confidence
                    quality_score = consolidation.confidence_in_decisions

                    success_memory.record_success(
                        task_id=self._task_id, analysis=mock_analysis, result=mock_result, quality_score=quality_score
                    )

                    logger.info(
                        f"Phase 7: SuccessMemoryV2 recorded success (mode={swarm_mode}, quality={quality_score:.2f})"
                    )

                else:
                    # Record failure to StrategyBlacklistV2
                    blacklist = StrategyBlacklistV2(self._workspace_path)

                    # Infer complexity from duration
                    if duration > 120:
                        complexity_str = "COMPLEX"
                    elif duration > 60:
                        complexity_str = "MODERATE"
                    else:
                        complexity_str = "SIMPLE"

                    # Extract error from antipatterns
                    error_message = "; ".join(consolidation.learned_antipatterns[:3]) or "Task failed"

                    # Infer retry count from issues
                    retry_count = max(1, issues_count)

                    # Infer domains (same logic as success)
                    domains = []
                    task_lower = task.lower()
                    if any(word in task_lower for word in ["code", "implement", "fix", "debug"]):
                        domains.append("coding")
                    if any(word in task_lower for word in ["security", "auth", "encrypt"]):
                        domains.append("security")
                    if any(word in task_lower for word in ["test", "validate"]):
                        domains.append("testing")
                    if not domains:
                        domains.append("general")

                    blacklist.add_failed_strategy(
                        description=task,
                        swarm_mode=swarm_mode,
                        error_message=error_message,
                        retry_count=retry_count,
                        complexity=complexity_str,
                        domains=domains,
                    )

                    logger.warning(
                        f"Phase 7: StrategyBlacklistV2 recorded failure (mode={swarm_mode}, retries={retry_count})"
                    )

            except Exception as e:
                logger.debug(f"V2 memory recording failed: {e}")

        # V12.4: UncertaintyPropagator - reset chain for next task (arxiv:2601.15703)
        try:
            from core.intelligence.reasoning.uncertainty_propagator import get_uncertainty_propagator

            get_uncertainty_propagator().reset_chain()
        except Exception:
            pass

        # V12.4: AdaptiveMemoryOrganizer - store task outcome as structured note (arxiv:2502.12110)
        try:
            from core.memory_pkg.memory.adaptive_memory_organizer import get_adaptive_memory_organizer

            _organizer = get_adaptive_memory_organizer()
            _note_content = (
                f"Task: {task[:150]}\n"
                f"Patterns: {'; '.join(consolidation.learned_patterns[:5])}\n"
                f"Antipatterns: {'; '.join(consolidation.learned_antipatterns[:3])}"
            )
            _organizer.add_note(
                content=_note_content,
                source="consolidation",
                importance=0.6 if not consolidation.learned_antipatterns else 0.7,
            )
        except Exception:
            pass

        # V12.4: ExperienceDistiller - distill task experience into strategic principles (arxiv:2510.16079)
        try:
            from core.memory_pkg.skills.experience_distiller import get_experience_distiller

            _distiller = get_experience_distiller()
            _lessons = list(consolidation.learned_patterns) + [
                f"AVOID: {ap}" for ap in consolidation.learned_antipatterns
            ]
            _outcome = "success" if not consolidation.learned_antipatterns else "mixed"
            _distiller.distill(
                task_description=task[:200],
                outcome=_outcome,
                lessons=_lessons[:10],
            )
        except Exception:
            pass

        return ConsolidationPhaseResult(
            consolidation=consolidation,
            gemini_reflection=gemini_result,
            claude_reflection=claude_result,
            user_decision=user_response.chosen_option,
            archived_to_rag=archived_count,
            agents_retained=agents_retained,
            agents_deleted=agents_deleted,
        )

    async def _reflect_with_gemini(self, prompt: str, session_uuid: str | None = None) -> str:
        """Get reflection from Gemini with session isolation."""
        try:
            logger.debug(f"Gemini reflection using session {session_uuid[:8] if session_uuid else 'none'}")
            # V12.4.1: Use invoke() with cached system prompt
            response = await self.gemini.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=CONSOLIDATION_SYSTEM_PROMPT,
                agent_name="gemini",
                agent_id="gemini",
            )

            if not response.is_success:
                logger.warning(f"Gemini reflection failed: {response.error_message}")
                return ""

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "reflection_gemini",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("reflection_gemini", total_tokens)

            return response.content
        except Exception as e:
            logger.error(f"Gemini reflection failed: {e}")
            raise

    async def _reflect_with_claude(self, prompt: str, session_uuid: str | None = None) -> str:
        """Get reflection from Claude with session isolation."""
        try:
            logger.debug(f"Claude reflection using session {session_uuid[:8] if session_uuid else 'none'}")
            # V12.4.1: Use invoke() with cached system prompt
            response = await self.claude.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=CONSOLIDATION_SYSTEM_PROMPT,
                agent_name="claude",
                agent_id="claude",
            )

            if not response.is_success:
                logger.warning(f"Claude reflection failed: {response.error_message}")
                return ""

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "reflection_claude",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("reflection_claude", total_tokens)

            return response.content
        except Exception as e:
            logger.error(f"Claude reflection failed: {e}")
            raise

    async def _debate_consolidation(
        self, task: str, gemini_reflection: str, claude_reflection: str, success: bool
    ) -> KnowledgeConsolidation:
        """Debate and finalize consolidation decisions."""
        # Parse reflections
        gemini_data = self._parse_reflection(gemini_reflection)
        claude_data = self._parse_reflection(claude_reflection)

        # Merge learned patterns (union)
        all_patterns = list(set(gemini_data.get("learned_patterns", []) + claude_data.get("learned_patterns", [])))

        all_antipatterns = list(
            set(gemini_data.get("learned_antipatterns", []) + claude_data.get("learned_antipatterns", []))
        )

        all_capabilities = list(
            set(gemini_data.get("new_capabilities_identified", []) + claude_data.get("new_capabilities_identified", []))
        )

        # Merge agent retention decisions
        agent_decisions = self._merge_agent_decisions(
            gemini_data.get("agents_to_retain", []), claude_data.get("agents_to_retain", [])
        )

        # Merge knowledge to archive
        knowledge_entries = self._merge_knowledge_entries(
            gemini_data.get("knowledge_to_archive", []), claude_data.get("knowledge_to_archive", [])
        )

        # Merge improvement suggestions
        all_improvements = list(
            set(gemini_data.get("nexus_improvements", []) + claude_data.get("nexus_improvements", []))
        )

        # Calculate satisfaction
        gemini_satisfaction = gemini_data.get("satisfaction", 0.5)
        claude_satisfaction = claude_data.get("satisfaction", 0.5)

        return KnowledgeConsolidation(
            learned_patterns=all_patterns,
            learned_antipatterns=all_antipatterns,
            new_capabilities_identified=all_capabilities,
            agents_retention=agent_decisions,
            knowledge_to_archive=knowledge_entries,
            tools_to_create=[],  # Future feature
            nexus_improvements=all_improvements,
            task_success=success,
            confidence_in_decisions=(gemini_satisfaction + claude_satisfaction) / 2,
            gemini_reflection=gemini_data.get("overall_reflection", ""),
            claude_reflection=claude_data.get("overall_reflection", ""),
        )

    def _parse_reflection(self, response) -> dict[str, Any]:
        """Parse reflection JSON from response."""
        from ..json_parser import parse_json_response

        data = parse_json_response(response, "consolidation", default=None)
        return data if data is not None else {}

    def _merge_agent_decisions(
        self, gemini_decisions: list[dict], claude_decisions: list[dict]
    ) -> list[AgentRetention]:
        """Merge agent retention decisions from both agents."""
        decisions_by_agent = {}

        # Process Gemini's decisions
        for d in gemini_decisions:
            agent_id = d.get("agent_id")
            if agent_id:
                vote = d.get("vote", "DELETE")
                try:
                    retention = RetentionDecision(vote)
                except ValueError:
                    retention = RetentionDecision.DELETE

                decisions_by_agent[agent_id] = {
                    "gemini_vote": retention,
                    "claude_vote": None,
                    "reason": d.get("reason", ""),
                }

        # Process Claude's decisions
        for d in claude_decisions:
            agent_id = d.get("agent_id")
            if agent_id:
                vote = d.get("vote", "DELETE")
                try:
                    retention = RetentionDecision(vote)
                except ValueError:
                    retention = RetentionDecision.DELETE

                if agent_id in decisions_by_agent:
                    decisions_by_agent[agent_id]["claude_vote"] = retention
                else:
                    decisions_by_agent[agent_id] = {
                        "gemini_vote": None,
                        "claude_vote": retention,
                        "reason": d.get("reason", ""),
                    }

        # Create final decisions
        results = []
        for agent_id, data in decisions_by_agent.items():
            gemini_vote = data.get("gemini_vote") or RetentionDecision.DELETE
            claude_vote = data.get("claude_vote") or RetentionDecision.DELETE

            # If both agree, use that decision
            if (
                gemini_vote == claude_vote
                or gemini_vote != RetentionDecision.DELETE
                and claude_vote == RetentionDecision.DELETE
            ):
                final_decision = gemini_vote
            elif claude_vote != RetentionDecision.DELETE and gemini_vote == RetentionDecision.DELETE:
                final_decision = claude_vote
            else:
                # Different keep types - use most conservative (ARCHIVE)
                final_decision = RetentionDecision.ARCHIVE_KNOWLEDGE

            results.append(
                AgentRetention(
                    agent_id=agent_id,
                    decision=final_decision,
                    reason=data.get("reason", ""),
                    gemini_vote=gemini_vote,
                    claude_vote=claude_vote,
                )
            )

        return results

    def _merge_knowledge_entries(self, gemini_entries: list[dict], claude_entries: list[dict]) -> list[KnowledgeEntry]:
        """Merge knowledge entries from both agents."""
        entries = []

        for e in gemini_entries + claude_entries:
            entries.append(
                KnowledgeEntry(
                    category=e.get("category", "insight"),
                    content=e.get("content", ""),
                    source_task="hive_mind",
                    usefulness_score=float(e.get("usefulness", 0.5)),
                    tags=e.get("tags", []),
                )
            )

        # Deduplicate by content similarity (simple)
        seen_content = set()
        unique_entries = []
        for e in entries:
            content_key = e.content[:50].lower()
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_entries.append(e)

        return unique_entries

    def _apply_agent_decisions(self, decisions: list[AgentRetention]) -> tuple[list[str], list[str]]:
        """Apply agent retention decisions to registry."""
        retained = []
        deleted = []

        for decision in decisions:
            if decision.decision == RetentionDecision.DELETE:
                # Deactivate in registry
                self.registry.deactivate_agent(decision.agent_id, reason=decision.reason)
                deleted.append(decision.agent_id)
            else:
                # Update usage (mark as retained)
                self.registry.record_usage(decision.agent_id, success=True)
                retained.append(decision.agent_id)

        return retained, deleted

    def _archive_knowledge(self, entries: list[KnowledgeEntry], task: str) -> int:
        """Archive knowledge entries to RAG."""
        if not self.project_memory:
            # Fall back to context manager
            for entry in entries:
                self.context_manager.add_insight(category=entry.category, content=entry.content, tags=entry.tags)
            return len(entries)

        archived = 0
        for entry in entries:
            try:
                doc_content = f"""
# Hive Mind Knowledge: {entry.category}

Task Context: {task[:100]}...

{entry.content}

Usefulness: {entry.usefulness_score:.0%}
Tags: {", ".join(entry.tags)}
"""
                if hasattr(self.project_memory, "add_document"):
                    self.project_memory.add_document(
                        content=doc_content,
                        metadata={"type": "hive_mind_knowledge", "category": entry.category, "tags": entry.tags},
                    )
                    archived += 1

            except Exception as e:
                logger.warning(f"Failed to archive knowledge: {e}")

        return archived

    def _create_minimal_result(self, task: str, success: bool) -> ConsolidationPhaseResult:
        """Create minimal result when budget is limited."""
        return ConsolidationPhaseResult(
            consolidation=KnowledgeConsolidation(
                learned_patterns=[],
                learned_antipatterns=[],
                new_capabilities_identified=[],
                agents_retention=[],
                knowledge_to_archive=[],
                tools_to_create=[],
                nexus_improvements=[],
                task_success=success,
                confidence_in_decisions=0.3,
                gemini_reflection="Budget limited",
                claude_reflection="Budget limited",
            ),
            gemini_reflection="Budget limited",
            claude_reflection="Budget limited",
            user_decision="skip",
            archived_to_rag=0,
            agents_retained=[],
            agents_deleted=[],
        )
