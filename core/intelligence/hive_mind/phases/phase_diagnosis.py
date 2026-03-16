"""
NEXUS V9.2 - Phase 5: Failure Diagnosis

Dual-agent failure analysis when execution encounters issues.
Both agents independently diagnose, then synthesize.

V9.2 Enhancement: Session Isolation for Parallel Diagnosis
- Each agent diagnoses with isolated session
- Full context inheritance from Phase 4 (FULL scope for debugging)
- Model-aware context for diagnostic capabilities

Flow:
1. Gemini diagnoses failure (session: uuid-diag-G)
2. Claude diagnoses failure (session: uuid-diag-C) [parallel]
3. Synthesize diagnoses
4. User Breakpoint: AFTER_DIAGNOSIS
5. Return diagnosis for Phase 6 (Retry)

Key Innovation:
- Dual diagnosis catches more root causes
- Cross-validation reduces misdiagnosis
- User can override or guide retry
- V9.2: Session isolation for parallel diagnosis
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from ..base_phase import BasePhase
from ..context_manager import HiveMindContextManager
from ..cost_estimator import CostEstimator
from ..prompts import DIAGNOSIS_SYSTEM_PROMPT  # V12.4.1: Static prompt for caching
from ..session_integration import HiveMindSessionIntegration, generate_hivemind_task_id
from ..types import (
    FAILURE_RECOVERY_MAP,
    ExecutionIssue,
    FailureDiagnosis,
    FailureType,
    MonitoredStepResult,
    RecoveryStrategy,
)
from ..user_interaction import UserInteractionHandler

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm.session_manager import SwarmSessionManager


logger = logging.getLogger(__name__)


# Diagnosis prompt
DIAGNOSIS_PROMPT = """You are diagnosing a failure in NEXUS Hive Mind execution.

TASK: {task}

EXECUTION CONTEXT:
{execution_context}

FAILURE STEP: {failure_step}

ISSUES DETECTED:
{issues}

Analyze the failure and provide diagnosis.

Respond in JSON format:
{{
    "failure_type": "timeout|capability_missing|hallucination|strategy_wrong|tool_error|context_lost|budget_exceeded|unknown",
    "root_cause": "The fundamental cause of failure",
    "contributing_factors": ["factor1", "factor2", ...],
    "evidence": ["evidence1", "evidence2", ...],
    "recommended_changes": [
        "change1",
        "change2",
        ...
    ],
    "missing_capability": "If capability was missing, what was it?",
    "confidence": 0.0 to 1.0,
    "reasoning": "Why you believe this is the root cause"
}}

Be specific. Focus on actionable fixes.
"""

SYNTHESIS_PROMPT = """Synthesize these two diagnoses of a NEXUS execution failure.

TASK: {task}

GEMINI'S DIAGNOSIS:
{gemini_diagnosis}

CLAUDE'S DIAGNOSIS:
{claude_diagnosis}

Create a unified diagnosis that:
1. Identifies the most likely root cause
2. Merges recommended changes (prioritize by likelihood)
3. Notes where agents disagree

Respond in JSON format:
{{
    "failure_type": "timeout|capability_missing|hallucination|strategy_wrong|tool_error|context_lost|budget_exceeded|unknown",
    "root_cause": "The agreed/most likely root cause",
    "contributing_factors": ["factor1", "factor2", ...],
    "evidence": ["evidence1", "evidence2", ...],
    "recommended_changes": ["change1", "change2", ...],
    "confidence": 0.0 to 1.0,
    "agents_agreed": true or false,
    "disagreement_notes": "Where the agents disagreed (if any)"
}}
"""


@dataclass
class DiagnosisPhaseResult:
    """Result of Phase 5."""

    diagnosis: FailureDiagnosis
    gemini_diagnosis: str
    claude_diagnosis: str
    user_decision: str  # "retry", "modify_changes", "escalate", "abort"
    user_modifications: str | None = None


class FailureDiagnosisPhase(BasePhase):
    """
    Phase 5: Failure Diagnosis

    Dual-agent analysis of execution failures.

    V9.2: Integrated session isolation for parallel diagnosis.
    """

    def __init__(
        self,
        gemini_driver: "BaseAsyncDriver | None" = None,
        claude_driver: "BaseAsyncDriver | None" = None,
        cost_estimator: CostEstimator | None = None,
        context_manager: HiveMindContextManager | None = None,
        user_handler: UserInteractionHandler | None = None,
        task_id: str | None = None,
        session_manager: Optional["SwarmSessionManager"] = None,
        *,
        agents: dict[str, "BaseAsyncDriver"] | None = None,
    ):
        """
        Initialize Phase 5.

        Args:
            gemini_driver: Gemini driver (legacy, prefer agents dict)
            claude_driver: Claude driver (legacy, prefer agents dict)
            cost_estimator: Cost estimator
            context_manager: Context manager
            user_handler: User interaction handler
            task_id: V9.2 - Unique task identifier for session isolation
            session_manager: V9.2 - Optional session manager for persistence
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
        self.user_handler = user_handler

        # V9.2: Session isolation
        self._task_id = task_id or generate_hivemind_task_id("diagnosis")
        self._session_manager = session_manager
        self._session_integration: HiveMindSessionIntegration | None = None

    async def execute(
        self, task: str, step_results: list[MonitoredStepResult], issues: list[ExecutionIssue], failure_step: str | None
    ) -> DiagnosisPhaseResult:
        """
        Execute Phase 5: Failure Diagnosis.

        Args:
            task: Original task
            step_results: Results from execution
            issues: Issues detected
            failure_step: Step that failed

        Returns:
            DiagnosisPhaseResult with diagnosis and user decision
        """
        logger.info("Phase 5: Starting Failure Diagnosis")

        # V9.2: Initialize session integration with FULL scope (needs complete context for debugging)
        self._session_integration = HiveMindSessionIntegration(
            task_id=self._task_id,
            phase_name="diagnosis",
            context_manager=self.context_manager,
            session_manager=self._session_manager,
            complexity="COMPLEX",  # Diagnosis needs full context
        )
        self._session_integration.set_previous_phase("execution")

        # V9.2: Get isolated sessions for parallel diagnosis
        parallel_sessions = self._session_integration.get_parallel_sessions(agents=["gemini", "claude"])
        logger.debug(f"Created isolated diagnosis sessions: {parallel_sessions}")

        # Check budget
        if not self.cost_estimator.can_afford_multiple(
            {"failure_diagnosis_gemini": 1, "failure_diagnosis_claude": 1, "synthesize_diagnosis": 1}
        ):
            logger.warning("Limited budget for diagnosis")

        # Format context
        execution_context = self._format_execution_context(step_results)
        issues_text = self._format_issues(issues)

        # Get diagnoses in parallel
        prompt = DIAGNOSIS_PROMPT.format(
            task=task, execution_context=execution_context, failure_step=failure_step or "Unknown", issues=issues_text
        )

        gemini_task = self._diagnose_with_gemini(prompt, parallel_sessions.get("gemini"))
        claude_task = self._diagnose_with_claude(prompt, parallel_sessions.get("claude"))

        gemini_result, claude_result = await asyncio.gather(gemini_task, claude_task, return_exceptions=True)

        # Handle errors
        if isinstance(gemini_result, Exception):
            gemini_result = f"Diagnosis failed: {gemini_result}"
        if isinstance(claude_result, Exception):
            claude_result = f"Diagnosis failed: {claude_result}"

        # Synthesize diagnoses
        diagnosis = await self._synthesize_diagnoses(
            task=task, gemini_diagnosis=gemini_result, claude_diagnosis=claude_result
        )

        # V12.4: Multi-persona analysis (MAR, arxiv:2512.20845)
        try:
            from ..persona_diagnosis import get_persona_diagnoser

            persona_diagnoser = get_persona_diagnoser()
            persona_result = persona_diagnoser.analyze(
                failure_context=f"Task: {task[:100]}. Failure step: {failure_step}. Issues: {issues_text[:200]}",
                gemini_diagnosis=str(gemini_result)[:500],
                claude_diagnosis=str(claude_result)[:500],
                failure_type=diagnosis.failure_type.value
                if hasattr(diagnosis.failure_type, "value")
                else str(diagnosis.failure_type),
            )
            # Enrich diagnosis with persona insights
            unique_insights = persona_result.get_unique_insights()
            if unique_insights:
                diagnosis.contributing_factors.extend(unique_insights[:3])
                logger.info(
                    f"Phase 5: Multi-persona added {len(unique_insights)} unique insights "
                    f"(consensus: {persona_result.consensus_level:.0%})"
                )
        except Exception as e:
            logger.debug(f"Multi-persona analysis failed: {e}")

        # V12.4: MAST classification + MARS triple-pathway reflection (arxiv:2503.13657, arxiv:2601.11974)
        try:
            from ..failure_taxonomy import get_mast_classifier, get_triple_reflector

            failure_type_str = (
                diagnosis.failure_type.value
                if hasattr(diagnosis.failure_type, "value")
                else str(diagnosis.failure_type)
            )

            # MAST: Classify failure into 14-mode taxonomy
            mast_classifier = get_mast_classifier()
            mast_result = mast_classifier.classify(
                failure_context=f"Task: {task[:100]}. Failure step: {failure_step}. Root cause: {diagnosis.root_cause}",
                failure_type=failure_type_str,
                agent_diagnoses=[str(gemini_result)[:300], str(claude_result)[:300]],
            )
            # Enrich evidence with MAST classification
            diagnosis.evidence.append(
                f"MAST codes: {', '.join(c.value for c in mast_result.codes)} "
                f"(primary: {mast_result.primary_category.value}, confidence: {mast_result.confidence:.0%})"
            )

            # MARS: Generate triple-pathway reflection for retry guidance
            reflector = get_triple_reflector()
            reflection = reflector.reflect(
                failure_context=f"Task: {task[:100]}. Step: {failure_step}",
                diagnosis=diagnosis.root_cause,
                failure_type=failure_type_str,
                mast_codes=[c.value for c in mast_result.codes],
            )
            # Add synthesis as a recommended change for Phase 6
            diagnosis.recommended_changes.insert(0, f"[MARS] {reflection.synthesis}")
            logger.info(
                f"Phase 5: MAST classified {len(mast_result.codes)} codes, "
                f"MARS generated reflection (type: {failure_type_str})"
            )
            # V12.4: MetaPolicyMemory - consolidate MARS reflection into reusable rule (arxiv:2509.03990)
            try:
                from core.intelligence.reasoning.meta_policy_memory import get_meta_policy_memory

                mpm = get_meta_policy_memory()
                mpm.consolidate(
                    mars_result=reflection,
                    mast_codes=[c.value for c in mast_result.codes],
                    source_task=task[:200],
                )
            except Exception as mpm_err:
                logger.debug(f"MetaPolicyMemory consolidation failed: {mpm_err}")

        except Exception as e:
            logger.debug(f"MAST/MARS analysis failed: {e}")

        # V12.4: FailureClassifier - 5-category root cause classification (arxiv:2509.25370)
        try:
            from core.intelligence.reasoning.failure_classifier import get_failure_classifier

            _fclassifier = get_failure_classifier()
            _step_outputs = [r.output[:200] for r in step_results if r.output] if step_results else []
            _issues = [
                {"issue_type": i.issue_type, "severity": getattr(i.severity, "value", str(i.severity))}
                for i in (issues or [])
            ]
            _fc_result = _fclassifier.classify(
                failure_description=diagnosis.root_cause,
                step_outputs=_step_outputs,
                issues=_issues,
            )
            diagnosis.contributing_factors.append(
                f"AgentDebug category: {_fc_result.category.value} "
                f"(confidence: {_fc_result.confidence:.0%}). "
                f"Recovery: {_fc_result.recovery_strategy[:150]}"
            )
        except Exception:
            pass

        # V12.4: FaultDetector - check if failure is due to Byzantine agent behavior (arxiv:2511.10400)
        try:
            from core.intelligence.reasoning.fault_detector import get_fault_detector

            _fdetector = get_fault_detector()
            for agent_id in {r.agent_id for r in step_results if hasattr(r, "agent_id")}:
                _fstatus = _fdetector.check_agent(agent_id)
                if _fstatus.is_faulty:
                    diagnosis.contributing_factors.append(
                        f"Byzantine fault: agent '{agent_id}' flagged as faulty "
                        f"(fault_rate={_fstatus.fault_rate:.0%}, trust={_fstatus.trust_score:.2f})"
                    )
        except Exception:
            pass

        # V12.4: MultiAgentReflexion - cross-agent reflection to break degeneration loops (arxiv:2512.20845)
        try:
            from core.intelligence.hive_mind.multi_agent_reflexion import get_multi_agent_reflexion

            _mar = get_multi_agent_reflexion()
            _reflections = []
            if gemini_result:
                _reflections.append(_mar.create_reflection("gemini", gemini_result, failure_context=task[:200]))
            if claude_result:
                _reflections.append(_mar.create_reflection("claude", claude_result, failure_context=task[:200]))
            if len(_reflections) >= 2:
                _synthesis = _mar.synthesize(
                    reflections=_reflections,
                    failure_context=task[:200],
                    attempt_number=getattr(self, "_retry_count", 1),
                )
                if _synthesis.degeneration_detected:
                    diagnosis.contributing_factors.append(
                        f"MAR: Degeneration-of-thought detected (agreement={_synthesis.agreement_level:.0%}). "
                        f"Anti-degeneration strategy: {_synthesis.proposed_strategy[:150]}"
                    )
                if _synthesis.diverse_insights:
                    diagnosis.contributing_factors.append(
                        f"MAR diverse insights: {'; '.join(_synthesis.diverse_insights[:3])}"
                    )
        except Exception:
            pass

        # V12.4: SystemHealth check - enrich diagnosis with system-level context
        try:
            from core.infrastructure.resilience.system_health import get_system_health

            health = get_system_health()
            report = await health.check_all()
            if report.overall_status.value != "healthy":
                diagnosis.contributing_factors.append(
                    f"System health: {report.overall_status.value} "
                    f"({sum(1 for c in report.components if c.status.value != 'healthy')} degraded components)"
                )
                logger.info(f"Phase 5: System health {report.overall_status.value} — may contribute to failure")
        except Exception:
            pass

        # Add to context
        self.context_manager.add_diagnosis("gemini", gemini_result)
        self.context_manager.add_diagnosis("claude", claude_result)

        # User breakpoint
        user_response = self.user_handler.after_diagnosis(
            failure_type=diagnosis.failure_type.value,
            root_cause=diagnosis.root_cause,
            recommended_changes=diagnosis.recommended_changes,
        )

        return DiagnosisPhaseResult(
            diagnosis=diagnosis,
            gemini_diagnosis=gemini_result,
            claude_diagnosis=claude_result,
            user_decision=user_response.chosen_option,
            user_modifications=user_response.custom_input,
        )

    def _format_execution_context(self, results: list[MonitoredStepResult]) -> str:
        """Format execution results for context."""
        lines = []
        for r in results:
            status_icon = "[OK]" if r.status == "success" else "[NO]" if r.status == "error" else "[warning]"
            lines.append(f"{status_icon} [{r.step_name}] ({r.agent_id})")
            lines.append(f"   Output: {r.output[:200]}...")
            lines.append(f"   Duration: {r.duration:.1f}s (expected {r.expected_duration}s)")
            if r.issues:
                lines.append(f"   Issues: {len(r.issues)}")
        return "\n".join(lines)

    def _format_issues(self, issues: list[ExecutionIssue]) -> str:
        """Format issues for diagnosis."""
        if not issues:
            return "No specific issues detected"

        lines = []
        for i in issues:
            lines.append(f"- [{i.severity.value.upper()}] {i.issue_type}: {i.details}")
        return "\n".join(lines)

    async def _diagnose_with_gemini(self, prompt: str, session_uuid: str | None = None) -> str:
        """Get diagnosis from Gemini with session isolation."""
        try:
            logger.debug(f"Gemini diagnosis using session {session_uuid[:8] if session_uuid else 'none'}")
            # V12.4.1: Use invoke() with cached system prompt
            response = await self.gemini.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
                agent_name="gemini",
                agent_id="gemini",
            )

            if not response.is_success:
                raise RuntimeError(f"Gemini diagnosis failed: {response.error_message}")

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "failure_diagnosis_gemini",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("failure_diagnosis_gemini", total_tokens)

            return response.content
        except Exception as e:
            logger.error(f"Gemini diagnosis failed: {e}")
            raise

    async def _diagnose_with_claude(self, prompt: str, session_uuid: str | None = None) -> str:
        """Get diagnosis from Claude with session isolation."""
        try:
            logger.debug(f"Claude diagnosis using session {session_uuid[:8] if session_uuid else 'none'}")
            # V12.4.1: Use invoke() with cached system prompt
            response = await self.claude.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
                agent_name="claude",
                agent_id="claude",
            )

            if not response.is_success:
                raise RuntimeError(f"Claude diagnosis failed: {response.error_message}")

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "failure_diagnosis_claude",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("failure_diagnosis_claude", total_tokens)

            return response.content
        except Exception as e:
            logger.error(f"Claude diagnosis failed: {e}")
            raise

    async def _synthesize_diagnoses(self, task: str, gemini_diagnosis: str, claude_diagnosis: str) -> FailureDiagnosis:
        """Synthesize two diagnoses into one."""
        prompt = SYNTHESIS_PROMPT.format(
            task=task, gemini_diagnosis=gemini_diagnosis, claude_diagnosis=claude_diagnosis
        )

        # V9.2: Use session for synthesis
        session_uuid = None
        if self._session_integration:
            session_uuid = self._session_integration.get_agent_session("gemini_synthesis")
            logger.debug(f"Synthesis using session {session_uuid[:8] if session_uuid else 'none'}")

        try:
            # V12.4.1: Use invoke() with cached system prompt
            response = await self.gemini.invoke(
                prompt,
                session_id=session_uuid,
                system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
                agent_name="gemini",
                agent_id="gemini",
            )

            if not response.is_success:
                logger.warning(f"Diagnosis synthesis failed: {response.error_message}")
                return self._create_fallback_diagnosis()

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "synthesize_diagnosis",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("synthesize_diagnosis", total_tokens)

            # Parse response from DriverResponse.content
            return self._parse_diagnosis_response(response.content, gemini_diagnosis, claude_diagnosis)

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return self._create_fallback_diagnosis(gemini_diagnosis, claude_diagnosis)

    def _parse_diagnosis_response(self, response, gemini_diagnosis: str, claude_diagnosis: str) -> FailureDiagnosis:
        """Parse synthesis response into FailureDiagnosis."""
        from ..json_parser import parse_json_response

        data = parse_json_response(response, "diagnosis", default=None)
        if data is None:
            return self._create_fallback_diagnosis(gemini_diagnosis, claude_diagnosis)

        try:
            # Parse failure type
            failure_type_str = data.get("failure_type", "unknown")
            try:
                failure_type = FailureType(failure_type_str)
            except ValueError:
                failure_type = FailureType.UNKNOWN

            return FailureDiagnosis(
                failure_type=failure_type,
                root_cause=data.get("root_cause", "Unknown"),
                contributing_factors=data.get("contributing_factors", []),
                evidence=data.get("evidence", []),
                recommended_changes=data.get("recommended_changes", []),
                confidence=float(data.get("confidence", 0.5)),
                gemini_diagnosis=gemini_diagnosis,
                claude_diagnosis=claude_diagnosis,
                missing_capability=data.get("missing_capability"),
            )

        except Exception as e:
            logger.warning(f"Diagnosis parse error: {e}")
            return self._create_fallback_diagnosis(gemini_diagnosis, claude_diagnosis)

    def _create_fallback_diagnosis(self, gemini_diagnosis: str, claude_diagnosis: str) -> FailureDiagnosis:
        """Create fallback diagnosis when parsing fails."""
        return FailureDiagnosis(
            failure_type=FailureType.UNKNOWN,
            root_cause="Could not synthesize diagnoses",
            contributing_factors=["Diagnosis synthesis failed"],
            evidence=[],
            recommended_changes=["Review task and retry manually"],
            confidence=0.3,
            gemini_diagnosis=gemini_diagnosis,
            claude_diagnosis=claude_diagnosis,
        )

    def get_retry_recommendations(self, result: DiagnosisPhaseResult) -> dict[str, Any]:
        """
        Get recommendations for retry phase.

        Uses PALADIN-inspired recovery strategy mapping (V12.4):
        each FailureType maps to a specific RecoveryStrategy.

        Args:
            result: Diagnosis result

        Returns:
            Recommendations for Phase 6
        """
        diagnosis = result.diagnosis

        # V12.4: Look up recovery strategy from structured mapping
        recovery = FAILURE_RECOVERY_MAP.get(diagnosis.failure_type, RecoveryStrategy.ESCALATE_USER)

        # Build recommendations based on failure type
        recommendations = {
            "should_retry": result.user_decision == "retry",
            "failure_type": diagnosis.failure_type.value,
            "recovery_strategy": recovery.value,
            "changes": diagnosis.recommended_changes,
            "confidence": diagnosis.confidence,
        }

        # Add specific recommendations by failure type
        if diagnosis.failure_type == FailureType.TIMEOUT:
            recommendations["architecture_changes"] = {
                "increase_timeout": True,
                "simplify_steps": True,
                "parallelize": False,
            }

        elif diagnosis.failure_type == FailureType.CAPABILITY_MISSING:
            recommendations["architecture_changes"] = {
                "spawn_specialist": True,
                "capability_needed": diagnosis.missing_capability,
                "fallback_agent": "claude",
            }

        elif diagnosis.failure_type == FailureType.HALLUCINATION:
            recommendations["architecture_changes"] = {
                "add_verification": True,
                "use_tools": True,
                "reduce_ambiguity": True,
            }

        elif diagnosis.failure_type == FailureType.STRATEGY_WRONG:
            recommendations["architecture_changes"] = {
                "rethink_approach": True,
                "use_alternative": True,
                "debate_again": diagnosis.confidence < 0.5,
            }

        elif diagnosis.failure_type == FailureType.TOOL_ERROR:
            recommendations["architecture_changes"] = {
                "check_prerequisites": True,
                "use_alternative_tool": True,
                "validate_paths": True,
            }

        elif diagnosis.failure_type == FailureType.CONTEXT_LOST:
            recommendations["architecture_changes"] = {
                "reduce_context": True,
                "summarize_history": True,
                "fresh_start": diagnosis.confidence > 0.7,
            }

        elif diagnosis.failure_type == FailureType.BUDGET_EXCEEDED:
            recommendations["architecture_changes"] = {
                "increase_budget": True,
                "simplify_task": True,
                "skip_optional": True,
            }

        elif diagnosis.failure_type == FailureType.MEMORY_ERROR:
            recommendations["architecture_changes"] = {
                "compress_context": True,
                "reload_key_facts": True,
                "fresh_session": True,
            }

        elif diagnosis.failure_type == FailureType.PLANNING_ERROR:
            recommendations["architecture_changes"] = {
                "decompose_task": True,
                "re_analyze": True,
                "switch_lead_agent": diagnosis.confidence < 0.5,
            }

        # Apply user modifications if any
        if result.user_modifications:
            recommendations["user_override"] = result.user_modifications

        return recommendations
