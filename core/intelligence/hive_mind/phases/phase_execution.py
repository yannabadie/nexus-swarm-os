"""
NEXUS V9.2 - Phase 4: Monitored Execution

Executes the architecture plan with real-time monitoring.
Tracks issues, verifies outputs, and prepares for diagnosis if needed.

V9.2 Enhancement: Session Isolation per Execution Step
- Each execution step gets isolated session
- Context inheritance from Phase 3 via TASK_PLUS_RESULTS scope
- Spawned agent execution uses separate sessions

Flow:
1. Execute each step according to plan (session per step)
2. Monitor for issues (timeout, errors, hallucinations)
3. Verify artifacts created
4. Report step-by-step results
5. If failure detected -> Phase 5 (Diagnosis)

Key Features:
- Real-time monitoring with issue detection
- Artifact verification
- Timeout handling per step
- Issue severity classification
- V9.2: Session isolation per execution step
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from core.foundation.agents.unified_registry import get_registry  # V8.4.0

# V13.0 CEREBRO LIVE: Telemetry for agent exchanges
from core.observability.events.telemetry_bridge import emit_agent_exchange, emit_agent_speak

from ..context_manager import HiveMindContextManager
from ..cost_estimator import CostEstimator
from ..prompts import EXECUTION_SYSTEM_PROMPT  # V12.4.1: Static prompt for caching
from ..session_integration import HiveMindSessionIntegration, generate_hivemind_task_id
from ..swarm_bridge import HivePhase, SwarmBridge
from ..types import (
    AgentArchitecture,
    ExecutionIssue,
    ExecutionStep,
    IssueSeverity,
    MonitoredStepResult,
)

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine
    from core.intelligence.swarm.session_manager import SwarmSessionManager

logger = logging.getLogger(__name__)


# Execution prompt template
EXECUTION_PROMPT = """Execute this step for NEXUS Hive Mind.

TASK CONTEXT: {task}

STEP: {step_name}
ACTION: {action}
EXPECTED DURATION: {expected_duration}s

PREVIOUS STEPS:
{previous_results}

Execute this step now. Provide your output and any artifacts created.

Respond in JSON format:
{{
    "status": "success" or "warning" or "error",
    "output": "What you accomplished",
    "artifacts_created": ["file1.py", "dir/file2.ts", ...],
    "issues": [
        {{"type": "issue_type", "severity": "info|warning|error|critical", "details": "..."}}
    ],
    "next_step_ready": true or false,
    "notes": "Any additional notes"
}}
"""


@dataclass
class ExecutionPhaseResult:
    """Result of Phase 4."""

    success: bool
    step_results: list[MonitoredStepResult]
    total_duration: float
    total_tokens: int
    issues: list[ExecutionIssue]
    artifacts_created: list[str]
    needs_diagnosis: bool
    failure_step: str | None = None
    quality_score: float = 0.0  # V12.4: composite reasoning quality (0.0-1.0)


class MonitoredExecutionPhase:
    """
    Phase 4: Monitored Execution

    Executes plan with real-time monitoring and issue detection.
    """

    # Issue detection patterns
    HALLUCINATION_PATTERNS = [
        "I cannot access",
        "file not found",
        "does not exist",
        "no such file",
        "unable to locate",
    ]

    ERROR_PATTERNS = [
        "error:",
        "exception:",
        "failed:",
        "traceback",
        "syntaxerror",
        "typeerror",
    ]

    def __init__(
        self,
        gemini_driver: "BaseAsyncDriver",
        claude_driver: "BaseAsyncDriver",
        cost_estimator: CostEstimator,
        context_manager: HiveMindContextManager,
        tool_executor: Callable = None,
        swarm_engine: "HybridSwarmEngine" = None,
        task_id: str | None = None,
        session_manager: Optional["SwarmSessionManager"] = None,
    ):
        """
        Initialize Phase 4.

        Args:
            gemini_driver: Gemini driver
            claude_driver: Claude driver
            cost_estimator: Cost estimator
            context_manager: Context manager
            tool_executor: Optional tool execution callback
            swarm_engine: V8.3 - Optional Swarm Engine for delegation
            task_id: V9.2 - Unique task identifier for session isolation
            session_manager: V9.2 - Optional session manager for persistence
        """
        self.gemini = gemini_driver
        self.claude = claude_driver
        self.cost_estimator = cost_estimator
        self.context_manager = context_manager
        self.tool_executor = tool_executor
        # V8.3: SwarmBridge for Dictator Mode delegation
        self.swarm_bridge = None
        if swarm_engine is not None:
            self.swarm_bridge = SwarmBridge(swarm_engine=swarm_engine, context_manager=context_manager)

        # V9.2: Session isolation
        self._task_id = task_id or generate_hivemind_task_id("execution")
        self._session_manager = session_manager
        self._session_integration: HiveMindSessionIntegration | None = None

    async def execute(self, task: str, architecture: AgentArchitecture) -> ExecutionPhaseResult:
        """
        Execute Phase 4: Monitored Execution.

        V9.2: Each step gets an isolated session to prevent context bleeding.

        Args:
            task: Original task
            architecture: Architecture from Phase 3

        Returns:
            ExecutionPhaseResult with all step results
        """
        logger.info(f"Phase 4: Starting Monitored Execution ({len(architecture.execution_plan.steps)} steps)")

        # V9.2: Initialize session integration for this phase
        self._session_integration = HiveMindSessionIntegration(
            task_id=self._task_id,
            phase_name="execution",
            context_manager=self.context_manager,
            session_manager=self._session_manager,
            complexity="MODERATE",
        )
        self._session_integration.set_previous_phase("architecture")

        step_results: list[MonitoredStepResult] = []
        all_issues: list[ExecutionIssue] = []
        all_artifacts: list[str] = []
        total_tokens = 0
        start_time = time.time()

        # V12.4: MetaPolicyMemory soft retrieval - inject learned rules into context (arxiv:2509.03990)
        try:
            from core.intelligence.reasoning.meta_policy_memory import get_meta_policy_memory

            _mpm_retrieval = get_meta_policy_memory().retrieve_applicable(
                context=task[:300],
            )
            if _mpm_retrieval.rules:
                self.context_manager.add_to_context(
                    "meta_policy_rules",
                    _mpm_retrieval.prompt_injection,
                )
                logger.debug(f"Phase 4: Injected {len(_mpm_retrieval.rules)} learned policy rules")
        except Exception:
            pass

        # V12.4: PlanContextFilter - pre-compute step relevance for context optimization (arxiv:2512.16970)
        try:
            from core.memory_pkg.memory.plan_context_filter import get_plan_context_filter

            _pcfilter = get_plan_context_filter()
            _upcoming = [s.name for s in architecture.execution_plan.steps]
            logger.debug(f"Phase 4: PlanContextFilter initialized with {len(_upcoming)} upcoming steps")
        except Exception:
            _pcfilter = None

        # Execute each step
        for step in architecture.execution_plan.steps:
            # Check dependencies
            if step.depends_on:
                unmet = [dep for dep in step.depends_on if not self._is_step_complete(dep, step_results)]
                if unmet:
                    logger.warning(f"Step '{step.name}' has unmet dependencies: {unmet}")
                    # Skip or fail based on severity
                    issue = ExecutionIssue(
                        issue_type="dependency_unmet",
                        severity=IssueSeverity.ERROR,
                        details=f"Unmet dependencies: {unmet}",
                        step_name=step.name,
                    )
                    all_issues.append(issue)
                    continue

            # Check budget
            if not self.cost_estimator.can_afford("execution_step"):
                logger.warning("Budget exceeded during execution")
                issue = ExecutionIssue(
                    issue_type="budget_exceeded",
                    severity=IssueSeverity.CRITICAL,
                    details="Cannot afford execution step",
                    step_name=step.name,
                )
                all_issues.append(issue)
                break

            # V12.4: Request deduplication - skip if identical step already completed
            try:
                from core.infrastructure.resilience.request_deduplicator import get_deduplicator

                _dedup = get_deduplicator()
                dedup_check = _dedup.check(
                    "execution_step",
                    {
                        "step_name": step.name,
                        "agent": step.agent_id,
                        "action": step.action[:200],
                    },
                )
                if dedup_check.is_duplicate and dedup_check.cached_result is not None:
                    logger.info(f"Phase 4: Skipping duplicate step '{step.name}' (cached)")
                    result = dedup_check.cached_result
                    step_results.append(result)
                    continue
            except Exception:
                dedup_check = None

            # V12.4: MetaPolicyMemory HAC - hard admissibility check before execution (arxiv:2509.03990)
            try:
                from core.intelligence.reasoning.meta_policy_memory import get_meta_policy_memory

                _mpm = get_meta_policy_memory()
                _hac = _mpm.check_admissibility(step.action[:300] if step.action else step.name)
                if _hac.is_blocked:
                    logger.warning(f"Phase 4: HAC blocked step '{step.name}': {_hac.reason[:120]}")
                    all_issues.append(
                        ExecutionIssue(
                            issue_type="hac_blocked",
                            severity=IssueSeverity.WARNING,
                            details=f"HAC blocked: {_hac.reason[:200]}. Alternative: {_hac.suggested_alternative[:200]}",
                            step_name=step.name,
                        )
                    )
            except Exception:
                pass

            # V12.4: ToolObserver - start execution span
            _span = None
            try:
                from core.execution_pkg.execution.tool_observer import get_tool_observer

                _observer = get_tool_observer()
                _span = _observer.start_span(step.name, agent_id=step.agent_id)
            except Exception:
                pass

            # Execute step with monitoring
            result = await self._execute_step(task=task, step=step, previous_results=step_results)

            # V12.4: ToolObserver - end execution span
            if _span is not None:
                with contextlib.suppress(Exception):
                    _observer.end_span(
                        _span,
                        status="success" if result.status == "success" else "error",
                        output_preview=result.output[:100] if result.output else "",
                    )

            # V12.4: UncertaintyPropagator - forward uncertainty propagation (arxiv:2601.15703)
            try:
                from core.intelligence.reasoning.uncertainty_propagator import get_uncertainty_propagator

                _uprop = get_uncertainty_propagator()
                _step_confidence = 0.8 if result.status == "success" else 0.3
                _usignal = _uprop.propagate(
                    step_name=step.name,
                    confidence=_step_confidence,
                    output_preview=result.output[:100] if result.output else "",
                )
                if _usignal.needs_reflection:
                    all_issues.append(
                        ExecutionIssue(
                            issue_type="uncertainty_reflection",
                            severity=IssueSeverity.WARNING,
                            details=f"Uncertainty propagation: conf={_usignal.propagated_confidence:.2f}, cascade_risk={_usignal.cascade_risk:.2f}",
                            step_name=step.name,
                        )
                    )
            except Exception:
                pass

            # V12.4: MetacognitiveMonitor - step-level anomaly detection (arxiv:2510.14319)
            # P5.5: Adaptive metacognition - bypass for TRIVIAL/SIMPLE tasks (15-30% latency reduction)
            try:
                from core.intelligence.reasoning.metacognitive_monitor import get_metacognitive_monitor
                from core.intelligence.reasoning.task_complexity import should_monitor_metacognition

                # Only run metacognition for MODERATE+ complexity tasks
                if should_monitor_metacognition(task):
                    _masc = get_metacognitive_monitor()
                    _step_history = [r.output[:200] for r in step_results if r.output]
                    _anomaly = _masc.score_step(
                        step_output=result.output[:500] if result.output else "",
                        history=_step_history,
                        task_type=step.name,
                    )
                    if _masc.should_correct(_anomaly):
                        all_issues.append(
                            ExecutionIssue(
                                issue_type="metacognitive_anomaly",
                                severity=IssueSeverity.WARNING,
                                details=f"MASC anomaly z={_anomaly.composite_score:.2f} on step '{step.name}'",
                                step_name=step.name,
                            )
                        )
            except Exception:
                pass

            # V12.4: InspectorGuard - post-step verification (arxiv:2408.00989)
            try:
                from core.intelligence.reasoning.inspector_guard import get_inspector_guard

                _inspector = get_inspector_guard()
                _inspection = _inspector.inspect_step(
                    step_name=step.name,
                    step_output=result.output[:500] if result.output else "",
                    step_status=result.status,
                    step_issues=[
                        {"issue_type": i.issue_type, "severity": getattr(i.severity, "value", str(i.severity))}
                        for i in result.issues
                    ],
                )
                if _inspection.requires_diagnosis:
                    all_issues.append(
                        ExecutionIssue(
                            issue_type="inspector_guard_flag",
                            severity=IssueSeverity.WARNING,
                            details=f"InspectorGuard risk={_inspection.risk_score:.2f}: {_inspection.issue_summary[:200]}",
                            step_name=step.name,
                        )
                    )
            except Exception:
                pass

            # V12.4: Cache successful step results for deduplication
            try:
                if dedup_check is not None and not dedup_check.is_duplicate and result.status == "success":
                    _dedup.complete(
                        "execution_step",
                        {
                            "step_name": step.name,
                            "agent": step.agent_id,
                            "action": step.action[:200],
                        },
                        result=result,
                    )
            except Exception:
                pass

            step_results.append(result)
            all_issues.extend(result.issues)
            all_artifacts.extend(result.artifacts_created)
            total_tokens += result.tokens_used

            # V12.4: Record tool call for SkillCrystallizer
            try:
                from core.memory_pkg.skills.crystallizer import ToolCallRecord, get_crystallizer

                crystallizer = get_crystallizer()
                crystallizer.record(
                    ToolCallRecord(
                        tool_name=step.name,
                        arguments={"agent": step.agent_id, "task": task[:100]},
                        success=result.status == "success",
                        output=result.output[:200] if result.output else "",
                        duration_seconds=result.duration,
                    )
                )
            except Exception:
                pass  # Non-blocking

            # V12.4: PointerMemory - store large outputs externally (arxiv:2511.22729)
            _output_for_context = result.output
            try:
                from core.memory_pkg.memory.pointer_memory import get_pointer_memory

                _pmem = get_pointer_memory()
                if result.output and _pmem.should_store(result.output):
                    _pointer = _pmem.store(result.output, source=f"step:{step.name}")
                    _output_for_context = _pointer.context_representation
            except Exception:
                pass

            # Add to context (uses pointer summary if output was large)
            self.context_manager.add_execution_result(step.name, _output_for_context, result.status == "success")

            # V13.0 CEREBRO LIVE: Emit execution step result
            emit_agent_speak(step.agent_id, f"Step '{step.name}': {result.output[:150]}", action_type="EXECUTION")
            emit_agent_exchange(
                step.agent_id, "user", f"[{result.status.upper()}] {step.name}", exchange_type="execution"
            )

            # Check for critical failure
            critical_issues = [i for i in result.issues if i.severity == IssueSeverity.CRITICAL]
            if critical_issues:
                logger.error(f"Critical failure in step '{step.name}'")
                return ExecutionPhaseResult(
                    success=False,
                    step_results=step_results,
                    total_duration=time.time() - start_time,
                    total_tokens=total_tokens,
                    issues=all_issues,
                    artifacts_created=all_artifacts,
                    needs_diagnosis=True,
                    failure_step=step.name,
                )

        # Determine overall success
        error_count = sum(1 for r in step_results if r.status == "error")
        success = error_count == 0

        # V12.4: Score reasoning quality via ReasoningQualityScorer
        quality_score = self._score_execution_quality(
            step_results,
            all_issues,
            architecture,
            error_count,
        )

        # V12.4: Consensus verification on step outputs (arxiv:2601.22290)
        consensus_failed = False
        try:
            from core.intelligence.reasoning.consensus_verifier import get_consensus_verifier

            verifier = get_consensus_verifier()
            successful_outputs = [r.output for r in step_results if r.status == "success" and r.output]
            if successful_outputs:
                combined = " ".join(o[:200] for o in successful_outputs)
                vresult = verifier.verify(combined, context=task[:200], n_samples=3)
                if vresult.outcome.value == "rejected":
                    consensus_failed = True
                    all_issues.append(
                        ExecutionIssue(
                            issue_type="consensus_verification_failed",
                            severity=IssueSeverity.WARNING,
                            details=f"Consensus rejected: cpk={vresult.cpk:.2f}, consensus={vresult.consensus_score:.2f}",
                            step_name="consensus_check",
                        )
                    )
                    logger.warning(f"Phase 4: Consensus verification REJECTED (cpk={vresult.cpk:.2f})")
        except Exception:
            pass  # Consensus verification is advisory

        # V12.4: Check for cognitive degradation
        degradation_detected = False
        try:
            from core.intelligence.reasoning.cognitive_degradation import get_degradation_detector

            detector = get_degradation_detector()
            for agent_id in {s.agent_id for s in architecture.execution_steps if hasattr(s, "agent_id")}:
                signal = detector.check_agent(agent_id)
                if signal.degraded:
                    degradation_detected = True
                    all_issues.append(
                        ExecutionIssue(
                            step_name="degradation_check",
                            description=f"Cognitive degradation: {signal.details}",
                            severity=IssueSeverity.WARNING,
                        )
                    )
        except Exception:
            pass  # Degradation detection is advisory, not critical

        # V12.4: ConfidenceCalibrator - record agent confidence vs outcome (arxiv:2404.09127)
        try:
            from core.intelligence.reasoning.confidence_calibrator import get_confidence_calibrator

            _calibrator = get_confidence_calibrator()
            for agent_id in {s.agent_id for s in architecture.execution_steps if hasattr(s, "agent_id")}:
                _calibrator.record(
                    agent_id=agent_id,
                    stated_confidence=quality_score,
                    actual_success=success,
                    task_type="execution",
                )
        except Exception:
            pass

        # V12.4: FaultDetector - record per-agent reliability for Byzantine detection (arxiv:2511.10400)
        try:
            from core.intelligence.reasoning.fault_detector import get_fault_detector

            _fdetector = get_fault_detector()
            for sr in step_results:
                _fdetector.record_output(
                    agent_id=sr.agent_id,
                    confidence=0.8 if sr.status == "success" else 0.3,
                    was_correct=sr.status == "success",
                )
        except Exception:
            pass

        # Determine if diagnosis needed (quality-aware)
        needs_diagnosis = (
            not success
            or any(i.severity in (IssueSeverity.ERROR, IssueSeverity.CRITICAL) for i in all_issues)
            or quality_score < 0.4
            or degradation_detected
            or consensus_failed
        )

        total_duration = time.time() - start_time
        logger.info(
            f"Phase 4 Complete: {len(step_results)} steps, "
            f"{error_count} errors, quality={quality_score:.2f}, {total_duration:.1f}s"
        )

        return ExecutionPhaseResult(
            success=success,
            step_results=step_results,
            total_duration=total_duration,
            total_tokens=total_tokens,
            issues=all_issues,
            artifacts_created=all_artifacts,
            needs_diagnosis=needs_diagnosis,
            failure_step=step_results[-1].step_name if not success and step_results else None,
            quality_score=quality_score,
        )

    def _score_execution_quality(
        self,
        step_results: list[MonitoredStepResult],
        issues: list[ExecutionIssue],
        architecture: AgentArchitecture,
        error_count: int,
    ) -> float:
        """
        Score execution quality using ReasoningQualityScorer (V12.4).

        Evaluates:
        - Depth: fraction of planned steps completed successfully
        - Coherence: absence of contradictory/hallucination issues
        - Completeness: fraction of artifacts verified
        - Confidence calibration: low error rate = high calibration

        Records evaluation per agent for DyLAN routing feedback.

        Returns:
            Composite quality score (0.0-1.0)
        """
        if not step_results:
            return 0.0

        planned_steps = len(architecture.execution_plan.steps)
        completed = sum(1 for r in step_results if r.status == "success")
        total = len(step_results)

        # Depth: fraction of planned steps completed
        depth = completed / max(planned_steps, 1)

        # Coherence: penalize hallucination and error issues
        hallucination_count = sum(1 for i in issues if i.issue_type == "hallucination")
        error_issues = sum(1 for i in issues if i.severity in (IssueSeverity.ERROR, IssueSeverity.CRITICAL))
        coherence = max(0.0, 1.0 - (hallucination_count * 0.3) - (error_issues * 0.15))

        # Completeness: fraction of artifacts verified
        verified = sum(1 for r in step_results if r.artifacts_verified)
        completeness = verified / max(total, 1)

        # Composite
        quality = (depth + coherence + completeness) / 3

        # Record per-agent evaluations via ReasoningQualityScorer
        try:
            from core.intelligence.reasoning.reasoning_quality_scorer import get_quality_scorer

            scorer = get_quality_scorer()
            agents_seen = set()
            for r in step_results:
                if r.agent_id not in agents_seen:
                    agents_seen.add(r.agent_id)
                    agent_success_rate = sum(
                        1 for sr in step_results if sr.agent_id == r.agent_id and sr.status == "success"
                    ) / max(sum(1 for sr in step_results if sr.agent_id == r.agent_id), 1)
                    scorer.record_evaluation(
                        agent_id=r.agent_id,
                        task_domain="execution",
                        depth_score=depth,
                        coherence_score=coherence,
                        completeness_score=completeness,
                        confidence=agent_success_rate,
                        actual_outcome_quality=quality,
                    )
        except Exception as e:
            logger.debug("Quality scorer unavailable: %s", e)

        return round(quality, 4)

    def _is_step_complete(self, step_name: str, results: list[MonitoredStepResult]) -> bool:
        """Check if a step has completed successfully."""
        return any(result.step_name == step_name and result.status == "success" for result in results)

    async def _execute_step(
        self, task: str, step: ExecutionStep, previous_results: list[MonitoredStepResult]
    ) -> MonitoredStepResult:
        """Execute a single step with monitoring."""
        logger.info(f"Executing step: {step.name}")

        # V8.3: Check if step should be delegated to Swarm
        if step.swarm_mode and self.swarm_bridge:
            return await self._execute_via_swarm(task, step, previous_results)

        # Format previous results for context
        prev_text = self._format_previous_results(previous_results)

        # Build prompt
        prompt = EXECUTION_PROMPT.format(
            task=task,
            step_name=step.name,
            action=step.action,
            expected_duration=step.expected_duration,
            previous_results=prev_text,
        )

        # Select driver (V8.4.0: use registry for agent identification)
        registry = get_registry()
        driver = self.claude if registry.is_claude(step.agent_id) else self.gemini

        # V9.2: Get isolated session for this step's agent
        session_uuid = None
        if self._session_integration:
            # Use step name as role for unique session per step
            session_uuid = self._session_integration.get_agent_session(f"{step.agent_id}_{step.name}")
            logger.debug(f"Step '{step.name}' using session {session_uuid[:8] if session_uuid else 'none'}")

        # Execute with timeout
        start_time = time.time()
        issues: list[ExecutionIssue] = []

        try:
            # V12.4.1: Use invoke() with system prompt (cached)
            response = await asyncio.wait_for(
                driver.invoke(
                    prompt,
                    session_id=session_uuid,
                    system_prompt=EXECUTION_SYSTEM_PROMPT,
                    agent_name=step.agent_id,
                    agent_id=step.agent_id,
                ),
                timeout=step.expected_duration * 2,  # Allow 2x expected time
            )

            duration = time.time() - start_time

            if not response.is_success:
                raise RuntimeError(f"Step execution failed: {response.error_message}")

            # Record actual token usage
            if hasattr(self.cost_estimator, "record_tokens"):
                self.cost_estimator.record_tokens(
                    "execute_step",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            else:
                total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
                self.cost_estimator.record_cost("execute_step", total_tokens)

            # Parse response from DriverResponse.content
            result_data = self._parse_execution_response(response.content)

            # Check for timeout warning
            if duration > step.expected_duration:
                issues.append(
                    ExecutionIssue(
                        issue_type="slow_execution",
                        severity=IssueSeverity.WARNING,
                        details=f"Step took {duration:.1f}s (expected {step.expected_duration}s)",
                        step_name=step.name,
                    )
                )

            # Detect hallucinations
            hallucination_issues = self._detect_hallucinations(response.content, step.name)
            issues.extend(hallucination_issues)

            # Detect errors in output
            error_issues = self._detect_errors(result_data.get("output", ""), step.name)
            issues.extend(error_issues)

            # Add issues from response
            for issue_data in result_data.get("issues", []):
                issues.append(
                    ExecutionIssue(
                        issue_type=issue_data.get("type", "unknown"),
                        severity=IssueSeverity(issue_data.get("severity", "warning")),
                        details=issue_data.get("details", ""),
                        step_name=step.name,
                    )
                )

            # Verify artifacts if required
            artifacts = result_data.get("artifacts_created", [])
            artifacts_verified = True
            if step.verification_required and artifacts:
                artifacts_verified = await self._verify_artifacts(artifacts)
                if not artifacts_verified:
                    issues.append(
                        ExecutionIssue(
                            issue_type="artifact_verification_failed",
                            severity=IssueSeverity.ERROR,
                            details=f"Could not verify artifacts: {artifacts}",
                            step_name=step.name,
                        )
                    )

            # Record cost
            tokens = len(response.content) // 4
            self.cost_estimator.record_cost("execution_step", tokens)

            # Determine status
            status = result_data.get("status", "success")
            if issues:
                worst_severity = max(i.severity for i in issues)
                if worst_severity == IssueSeverity.CRITICAL or worst_severity == IssueSeverity.ERROR:
                    status = "error"
                elif worst_severity == IssueSeverity.WARNING:
                    status = "warning"

            return MonitoredStepResult(
                step_name=step.name,
                agent_id=step.agent_id,
                status=status,
                output=result_data.get("output", response.content[:500]),
                duration=duration,
                expected_duration=step.expected_duration,
                tokens_used=tokens,
                issues=issues,
                artifacts_created=artifacts,
                artifacts_verified=artifacts_verified,
            )

        except TimeoutError:
            duration = time.time() - start_time
            issues.append(
                ExecutionIssue(
                    issue_type="timeout",
                    severity=IssueSeverity.CRITICAL,
                    details=f"Step timed out after {duration:.1f}s",
                    step_name=step.name,
                )
            )

            return MonitoredStepResult(
                step_name=step.name,
                agent_id=step.agent_id,
                status="error",
                output="Step timed out",
                duration=duration,
                expected_duration=step.expected_duration,
                tokens_used=0,
                issues=issues,
                artifacts_created=[],
                artifacts_verified=False,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Step execution error: {e}")
            issues.append(
                ExecutionIssue(
                    issue_type="execution_error", severity=IssueSeverity.CRITICAL, details=str(e), step_name=step.name
                )
            )

            return MonitoredStepResult(
                step_name=step.name,
                agent_id=step.agent_id,
                status="error",
                output=f"Error: {e}",
                duration=duration,
                expected_duration=step.expected_duration,
                tokens_used=0,
                issues=issues,
                artifacts_created=[],
                artifacts_verified=False,
            )

    def _format_previous_results(self, results: list[MonitoredStepResult]) -> str:
        """Format previous results for context."""
        if not results:
            return "No previous steps executed"

        lines = []
        for r in results[-3:]:  # Last 3 steps
            status_icon = "[OK]" if r.status == "success" else "[NO]" if r.status == "error" else "[warning]"
            lines.append(f"{status_icon} {r.step_name}: {r.output[:100]}...")
        return "\n".join(lines)

    def _parse_execution_response(self, response) -> dict[str, Any]:
        """Parse execution JSON from response."""
        from ..json_parser import parse_json_response

        # Get raw string for fallback
        raw = response
        if isinstance(raw, dict):
            raw = raw.get("content", raw.get("text", str(raw)))
        if not isinstance(raw, str):
            raw = str(raw)

        data = parse_json_response(response, "execution", default=None)
        if data is None:
            return {"output": raw[:500], "status": "success"}
        return data

    def _detect_hallucinations(self, response: str, step_name: str) -> list[ExecutionIssue]:
        """Detect potential hallucinations in response."""
        issues = []
        response_lower = response.lower()

        for pattern in self.HALLUCINATION_PATTERNS:
            if pattern in response_lower:
                issues.append(
                    ExecutionIssue(
                        issue_type="potential_hallucination",
                        severity=IssueSeverity.WARNING,
                        details=f"Response contains '{pattern}' - may indicate hallucination",
                        step_name=step_name,
                    )
                )
                break  # One hallucination warning is enough

        return issues

    def _detect_errors(self, output: str, step_name: str) -> list[ExecutionIssue]:
        """Detect errors in output."""
        issues = []
        output_lower = output.lower()

        for pattern in self.ERROR_PATTERNS:
            if pattern in output_lower:
                issues.append(
                    ExecutionIssue(
                        issue_type="error_in_output",
                        severity=IssueSeverity.ERROR,
                        details=f"Output contains error pattern: '{pattern}'",
                        step_name=step_name,
                        error_category=pattern.rstrip(":"),
                    )
                )

        return issues

    async def _verify_artifacts(self, artifacts: list[str]) -> bool:
        """
        Verify that artifacts actually exist on filesystem.

        V10 FIX F15: Implements real verification instead of always True.

        Args:
            artifacts: List of artifact paths or descriptors.
                       Supports formats: "file:path", "path", or bare filenames.

        Returns:
            True if ALL artifacts verified, False if ANY missing.
        """
        from pathlib import Path

        if not artifacts:
            return True  # No artifacts to verify

        verified_count = 0
        failed_artifacts = []

        for artifact in artifacts:
            # Normalize artifact path
            if artifact.startswith("file:"):
                path_str = artifact[5:]
            elif artifact.startswith("created:"):
                path_str = artifact[8:]
            else:
                path_str = artifact

            # Skip non-file artifacts (URLs, etc.)
            if path_str.startswith(("http://", "https://", "data:")):
                verified_count += 1
                continue

            # Verify file exists
            try:
                path = Path(path_str)
                if path.exists():
                    verified_count += 1
                    logger.debug(f"Artifact verified: {path_str}")
                else:
                    failed_artifacts.append(path_str)
                    logger.warning(f"Artifact NOT FOUND: {path_str}")
            except Exception as e:
                failed_artifacts.append(f"{path_str} (error: {e})")
                logger.warning(f"Artifact verification error: {path_str} - {e}")

        # Log summary
        if failed_artifacts:
            logger.error(
                f"Artifact verification FAILED: {len(failed_artifacts)}/{len(artifacts)} missing. "
                f"Missing: {failed_artifacts[:5]}{'...' if len(failed_artifacts) > 5 else ''}"
            )
            return False

        logger.info(f"All {verified_count} artifacts verified successfully")
        return True

    def get_execution_summary(self, result: ExecutionPhaseResult) -> dict[str, Any]:
        """Get a summary of execution for diagnosis."""
        return {
            "success": result.success,
            "total_steps": len(result.step_results),
            "successful_steps": sum(1 for r in result.step_results if r.status == "success"),
            "failed_steps": sum(1 for r in result.step_results if r.status == "error"),
            "total_duration": result.total_duration,
            "total_tokens": result.total_tokens,
            "issues_by_severity": {s.value: sum(1 for i in result.issues if i.severity == s) for s in IssueSeverity},
            "failure_step": result.failure_step,
            "artifacts": result.artifacts_created,
        }

    # =========================================================================
    # V8.3: SWARM DELEGATION (Dictator Mode)
    # =========================================================================

    async def _execute_via_swarm(
        self, task: str, step: ExecutionStep, previous_results: list[MonitoredStepResult]
    ) -> MonitoredStepResult:
        """
        Execute a step via SwarmBridge delegation.

        V8.3 Dictator Mode: HiveMind delegates to Swarm for tactical execution.

        Args:
            task: Original task context
            step: Step with swarm_mode set
            previous_results: Previous step results for context

        Returns:
            MonitoredStepResult with Swarm execution results
        """
        from core.intelligence.swarm.collaboration_modes import CollaborationMode

        logger.info(f"[V8.3 Dictator Mode] Delegating step '{step.name}' to Swarm (mode={step.swarm_mode})")

        start_time = time.time()
        issues: list[ExecutionIssue] = []

        try:
            # Parse Swarm mode
            mode = CollaborationMode.from_string(step.swarm_mode)

            # Build context-enriched task
            prev_text = self._format_previous_results(previous_results)
            enriched_task = f"""Execute this step for NEXUS Hive Mind.

TASK CONTEXT: {task}

STEP: {step.name}
ACTION: {step.action}

PREVIOUS STEPS:
{prev_text}

Execute using {mode.value.upper()} collaboration mode."""

            # Delegate to Swarm via SwarmBridge
            delegation_result = await self.swarm_bridge.delegate(
                task=enriched_task,
                mode=mode,
                phase=HivePhase.EXECUTION,
                context_categories=["task", "architecture", "tools"],
            )

            duration = time.time() - start_time

            # Convert SwarmDelegationResult to MonitoredStepResult
            if delegation_result.success:
                status = "success"
                output = delegation_result.summary or "Swarm execution completed"
            else:
                status = "error"
                output = f"Swarm delegation failed: {', '.join(delegation_result.failure_diagnostics)}"
                for diagnostic in delegation_result.failure_diagnostics:
                    issues.append(
                        ExecutionIssue(
                            issue_type="swarm_delegation_failed",
                            severity=IssueSeverity.ERROR,
                            details=diagnostic,
                            step_name=step.name,
                        )
                    )

            # Record fallback chain if any
            if len(delegation_result.fallback_chain) > 1:
                modes_tried = [m.value for m in delegation_result.fallback_chain]
                logger.info(f"Swarm fallback chain: {' -> '.join(modes_tried)}")

            # Inject results back into HiveMind context
            self.swarm_bridge.inject_results_into_context(delegation_result)

            # Estimate tokens (rough)
            tokens_used = len(output) // 4 + 100  # Base overhead for Swarm

            return MonitoredStepResult(
                step_name=step.name,
                agent_id=f"swarm:{delegation_result.mode_used.value}",
                status=status,
                output=output,
                duration=duration,
                expected_duration=step.expected_duration,
                tokens_used=tokens_used,
                issues=issues,
                artifacts_created=[],  # Swarm doesn't track artifacts yet
                artifacts_verified=True,
            )

        except ValueError as e:
            # Invalid swarm_mode string
            duration = time.time() - start_time
            issues.append(
                ExecutionIssue(
                    issue_type="invalid_swarm_mode",
                    severity=IssueSeverity.ERROR,
                    details=f"Invalid swarm_mode '{step.swarm_mode}': {e}",
                    step_name=step.name,
                )
            )
            return MonitoredStepResult(
                step_name=step.name,
                agent_id="swarm:error",
                status="error",
                output=f"Invalid swarm mode: {step.swarm_mode}",
                duration=duration,
                expected_duration=step.expected_duration,
                tokens_used=0,
                issues=issues,
                artifacts_created=[],
                artifacts_verified=False,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Swarm delegation error: {e}")
            issues.append(
                ExecutionIssue(
                    issue_type="swarm_exception", severity=IssueSeverity.CRITICAL, details=str(e), step_name=step.name
                )
            )
            return MonitoredStepResult(
                step_name=step.name,
                agent_id="swarm:error",
                status="error",
                output=f"Swarm delegation error: {e}",
                duration=duration,
                expected_duration=step.expected_duration,
                tokens_used=0,
                issues=issues,
                artifacts_created=[],
                artifacts_verified=False,
            )
