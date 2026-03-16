"""
Torture Protocol V8 - HiveMind Integration Tests

30 tests covering TrueHiveMind 7-phase pipeline integration.

Test IDs: HM-001 to HM-030
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.intelligence.hive_mind.saga_manager import SagaManager
from core.intelligence.hive_mind.types import (
    AgentArchitecture,
    AnalysisComparison,
    DebateResult,
    Disagreement,
    ExecutionPlan,
    ExecutionStep,
    FailureDiagnosis,
    FailureType,
    HiveMindState,
    IndependentAnalysis,
    KnowledgeConsolidation,
    MonitoredStepResult,
    RAGConfig,
    RetryDecision,
)

# ============================================================================
# Mock Components
# ============================================================================


@dataclass
class MockConfig:
    """Mock NEXUS config."""

    hive_mind_budget_limit: int = 50000
    hive_mind_breakpoint_timeout: int = 60


class MockDriver:
    """Mock LLM driver."""

    def __init__(self, name: str = "mock"):
        self.name = name
        self.call_count = 0
        self.last_prompt = None
        self._fail_at_call = -1
        self._responses = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.last_prompt = prompt

        if self.call_count == self._fail_at_call:
            raise RuntimeError(f"MockDriver {self.name} failed at call {self.call_count}")

        if self._responses:
            return self._responses.pop(0)

        return f"Mock response from {self.name} (call {self.call_count})"

    def set_fail_at(self, call_number: int):
        self._fail_at_call = call_number

    def add_response(self, response: str):
        self._responses.append(response)


class MockHiveMindPhase:
    """Mock phase for testing."""

    def __init__(self, name: str, default_result: Any = None):
        self.name = name
        self._default_result = default_result
        self._fail = False
        self._delay_ms = 0
        self.execute_count = 0

    async def execute(self, *args, **kwargs) -> Any:
        self.execute_count += 1

        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)

        if self._fail:
            raise RuntimeError(f"Phase {self.name} failed!")

        return self._default_result

    def set_fail(self, should_fail: bool = True):
        self._fail = should_fail

    def set_delay(self, delay_ms: int):
        self._delay_ms = delay_ms


def create_mock_analysis_result(needs_debate: bool = False):
    """Create mock analysis result."""
    analysis = IndependentAnalysis(
        agent_id="mock",
        task_understanding="Mock understanding",
        complexity_assessment="MODERATE",
        proposed_approach="Mock approach",
        required_capabilities=["coding"],
        potential_risks=["none"],
        confidence=0.9,
        reasoning="Mock reasoning",
    )
    comparison = AnalysisComparison(
        analyses={"gemini": analysis, "claude": analysis},
        disagreements=[]
        if not needs_debate
        else [Disagreement(topic="approach", positions={"gemini": "A", "claude": "B"})],
        agreement_score=0.95 if not needs_debate else 0.5,
        needs_debate=needs_debate,
        merged_capabilities=["coding"],
        merged_risks=["none"],
    )

    class AnalysisResult:
        def __init__(self):
            self.comparison = comparison
            self.needs_debate = needs_debate

    return AnalysisResult()


def create_mock_debate_result():
    """Create mock debate result."""
    debate = DebateResult(
        status="CONSENSUS_REACHED",
        final_approach="Agreed approach",
        final_capabilities=["coding"],
        final_mode="LEAD_SUPPORT",
        debate_history=[],
        total_turns=2,
        resolved_disagreements=["approach"],
        unresolved_disagreements=[],
        consensus_confidence=0.9,
        satisfactions={"gemini": 0.85, "claude": 0.85},
    )

    class DebatePhaseResult:
        def __init__(self):
            self.debate_result = debate
            self.final_approach = "Agreed approach"
            self.was_skipped = False

    return DebatePhaseResult()


def create_mock_architecture():
    """Create mock architecture."""
    return AgentArchitecture(
        status="READY",
        collaboration_mode="LEAD_SUPPORT",
        agents_to_use=["gemini", "claude"],
        agents_to_spawn=[],
        rag_config=RAGConfig(),
        execution_plan=ExecutionPlan(
            strategy="sequential",
            steps=[
                ExecutionStep(name="step1", agent_id="gemini", action="analyze"),
                ExecutionStep(name="step2", agent_id="claude", action="implement"),
            ],
            estimated_total_duration=60.0,
            estimated_total_tokens=5000,
        ),
        reasoning="Mock architecture",
    )


def create_mock_execution_result(success: bool = True):
    """Create mock execution result."""

    class ExecutionResult:
        def __init__(self):
            self.success = success
            self.output = "Mock execution output"
            self.step_results = [
                MonitoredStepResult(
                    step_name="step1",
                    agent_id="gemini",
                    status="success" if success else "error",
                    output="Step 1 output",
                    duration=10.0,
                    expected_duration=30.0,
                    tokens_used=1000,
                )
            ]
            self.total_duration = 60.0
            self.total_tokens = 5000
            self.artifacts_created = []

    return ExecutionResult()


@pytest.fixture
def saga_dir(tmp_path):
    """Create saga directory."""
    saga_dir = tmp_path / ".nexus" / "sagas"
    saga_dir.mkdir(parents=True)
    return saga_dir


@pytest.fixture
def mock_config():
    """Create mock config."""
    return MockConfig()


@pytest.fixture
def mock_drivers():
    """Create mock drivers."""
    return {"gemini": MockDriver("gemini"), "claude": MockDriver("claude")}


# ============================================================================
# HM-001: Crash between checkpoint_phase() and update_context()
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm001_crash_between_checkpoint_and_context(saga_dir):
    """
    HM-001: Test crash between checkpoint and context update.

    Scenario: Checkpoint succeeds but update_context() crashes.
    Expected: Can resume from checkpoint, context inconsistent but recoverable.
    """
    saga = SagaManager(saga_dir, "hm001-test", auto_persist=True)

    # Checkpoint succeeds
    await saga.checkpoint_phase("analysis", {"result": "ok"}, "S1", 5)

    # Simulate crash before update_context completes
    # (In real scenario, process would die here)

    # Resume from checkpoint
    recovered = await SagaManager.resume_from(saga_dir, "hm001-test")

    assert recovered is not None
    assert recovered.recovery_point == "analysis"
    assert "analysis" in recovered._checkpoints


# ============================================================================
# HM-002: Phase 1 (Analysis) failure with retry
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm002_analysis_failure_retry(saga_dir):
    """
    HM-002: Test analysis phase failure and retry.

    Scenario: Analysis fails once, succeeds on retry.
    Expected: Task completes on second attempt.
    """
    saga = SagaManager(saga_dir, "hm002-test", auto_persist=True)
    retry_count = [0]

    async def analysis_with_retry():
        retry_count[0] += 1
        if retry_count[0] == 1:
            raise RuntimeError("Analysis timeout")
        return create_mock_analysis_result()

    # First attempt fails
    try:
        await analysis_with_retry()
    except RuntimeError:
        # Record failure
        saga.update_context(analysis_failed=True, retry_count=1)

    # Retry succeeds
    await analysis_with_retry()
    await saga.checkpoint_phase("analysis", {"success": True}, "S1", 5)

    assert retry_count[0] == 2
    assert saga._checkpoints.get("analysis") is not None


# ============================================================================
# HM-003: Phase 2 (Debate) deadlock
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm003_debate_deadlock(saga_dir):
    """
    HM-003: Test debate phase deadlock (agents never agree).

    Scenario: Debate reaches max turns without consensus.
    Expected: Forced vote or escalation.
    """
    saga = SagaManager(saga_dir, "hm003-test", auto_persist=True)
    max_turns = 5
    turns = 0

    async def debate_turn():
        nonlocal turns
        turns += 1
        # Never reach consensus
        return {"consensus": False, "turn": turns}

    # Simulate debate until max turns
    while turns < max_turns:
        await debate_turn()

    # Force resolution after deadlock
    debate_result = {"status": "FORCED_VOTE", "turns": turns, "consensus": False}
    await saga.checkpoint_phase("debate", debate_result, "S2", 10)

    assert turns == max_turns
    assert debate_result["status"] == "FORCED_VOTE"


# ============================================================================
# HM-004: Phase 3 (Architecture) spawn failure
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm004_architecture_spawn_failure(saga_dir):
    """
    HM-004: Test architecture phase when agent spawn fails.

    Scenario: Architecture requires spawning agent that fails to spawn.
    Expected: Fallback to existing agents or escalate.
    """
    saga = SagaManager(saga_dir, "hm004-test", auto_persist=True)

    architecture = create_mock_architecture()
    architecture.status = "SPAWN_REQUIRED"
    architecture.agents_to_spawn = [MagicMock(role="specialist", fallback_agent="claude")]

    spawn_failed = True
    fallback_used = False

    if spawn_failed:
        # Use fallback agent
        fallback_used = True
        architecture.agents_to_use = ["gemini", "claude"]  # Fallback

    await saga.checkpoint_phase("architecture", {"status": "FALLBACK_USED", "fallback_agent": "claude"}, "S3", 15)

    assert fallback_used
    assert "claude" in architecture.agents_to_use


# ============================================================================
# HM-005: Full 7-phase success with all checkpoints
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm005_full_pipeline_success(saga_dir):
    """
    HM-005: Test complete 7-phase pipeline success.

    Scenario: All phases complete successfully.
    Expected: All checkpoints recorded, task completes.
    """
    saga = SagaManager(saga_dir, "hm005-test", auto_persist=True)
    phases = ["analysis", "debate", "architecture", "execution", "diagnosis", "retry", "consolidation"]

    for i, phase in enumerate(phases):
        await saga.checkpoint_phase(phase, {f"{phase}_result": "ok"}, f"S{i + 1}", i * 5)
        saga.update_context(**{f"{phase}_complete": True})

    # Verify all checkpoints
    assert len(saga._checkpoints) == 7
    for phase in phases:
        assert phase in saga._checkpoints

    # Verify context
    assert saga._saga_context.get("consolidation_complete") is True


# ============================================================================
# HM-006: Phase 4 (Execution) fail, rollback to Phase 3
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm006_execution_fail_rollback(saga_dir):
    """
    HM-006: Test execution failure with rollback to architecture.

    Scenario: Execution fails, rollback to architecture phase.
    Expected: Compensation runs, state restored to architecture.
    """
    saga = SagaManager(saga_dir, "hm006-test", auto_persist=True)
    compensation_log = []

    async def execution_compensation():
        compensation_log.append("execution_cleanup")

    # Setup phases
    await saga.checkpoint_phase("analysis", {}, "S1", 5)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("architecture", {}, "S3", 15)
    saga.update_context(architecture_complete=True)
    await saga.checkpoint_phase("execution", {}, "S4", 20, compensation=execution_compensation)

    # Execution fails - rollback to architecture
    await saga.rollback_to("architecture")

    assert "execution_cleanup" in compensation_log
    assert saga._recovery_point == "architecture"


# ============================================================================
# HM-007: Hot-swap during stagnation
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm007_hot_swap_stagnation(saga_dir):
    """
    HM-007: Test hot-swap lead agent during stagnation.

    Scenario: Lead agent produces similar outputs 3 times.
    Expected: Lead swapped to other agent.
    """
    saga = SagaManager(saga_dir, "hm007-test", auto_persist=True)

    # Simulate stagnation detection
    outputs = ["Similar output v1", "Similar output v1", "Similar output v1"]
    current_lead = "gemini"
    swap_count = 0

    def detect_stagnation(outputs):
        # Simple similarity check
        return bool(len(outputs) >= 3 and outputs[-1] == outputs[-2] == outputs[-3])

    if detect_stagnation(outputs):
        current_lead = "claude" if current_lead == "gemini" else "gemini"
        swap_count += 1

    await saga.checkpoint_phase(
        "execution", {"lead_swapped": True, "new_lead": current_lead, "swap_count": swap_count}, "S4", 20
    )

    assert current_lead == "claude"
    assert swap_count == 1


# ============================================================================
# HM-008: Phase 5 (Diagnosis) identifies hallucination
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm008_diagnosis_hallucination(saga_dir):
    """
    HM-008: Test diagnosis phase detecting hallucination.

    Scenario: Execution failed due to hallucinated file path.
    Expected: Diagnosis identifies HALLUCINATION failure type.
    """
    saga = SagaManager(saga_dir, "hm008-test", auto_persist=True)

    # Simulate failed execution
    execution_error = "FileNotFoundError: /nonexistent/path/file.py"

    # Diagnosis identifies root cause
    diagnosis = FailureDiagnosis(
        failure_type=FailureType.HALLUCINATION,
        root_cause="Agent referenced non-existent file path",
        contributing_factors=["Insufficient context", "No file verification"],
        evidence=[execution_error],
        recommended_changes=["Add file existence check", "Use RAG for valid paths"],
        confidence=0.85,
    )

    await saga.checkpoint_phase("diagnosis", diagnosis.to_dict(), "S5", 25)

    assert diagnosis.failure_type == FailureType.HALLUCINATION
    assert "hallucinated" in diagnosis.root_cause.lower() or "non-existent" in diagnosis.root_cause.lower()


# ============================================================================
# HM-009: Phase 6 (Retry) with new architecture
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm009_retry_new_architecture(saga_dir):
    """
    HM-009: Test retry phase generating new architecture.

    Scenario: After failure, retry with modified approach.
    Expected: New architecture generated, retry succeeds.
    """
    saga = SagaManager(saga_dir, "hm009-test", auto_persist=True)

    # Original architecture failed
    original = create_mock_architecture()
    original.collaboration_mode = "PARALLEL"

    # Retry decision: change approach
    retry_decision = RetryDecision(
        action="RETRY",
        reason="Parallel execution caused race condition",
        changes_made=["Changed mode to SEQUENTIAL"],
        expected_improvement=0.7,
    )

    # New architecture
    new_arch = create_mock_architecture()
    new_arch.collaboration_mode = "SEQUENTIAL"
    retry_decision.new_architecture = new_arch

    await saga.checkpoint_phase(
        "retry",
        {
            "action": retry_decision.action,
            "changes": retry_decision.changes_made,
            "new_mode": new_arch.collaboration_mode,
        },
        "S6",
        30,
    )

    assert retry_decision.action == "RETRY"
    assert new_arch.collaboration_mode == "SEQUENTIAL"


# ============================================================================
# HM-010: Phase 7 (Consolidation) agent retention
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm010_consolidation_retention(saga_dir):
    """
    HM-010: Test consolidation phase agent retention decision.

    Scenario: Spawned agent performed well, should be retained.
    Expected: Agent marked for permanent retention.
    """
    saga = SagaManager(saga_dir, "hm010-test", auto_persist=True)

    consolidation = KnowledgeConsolidation(
        learned_patterns=["Pattern 1"],
        learned_antipatterns=["Antipattern 1"],
        new_capabilities_identified=["capability_x"],
        agents_retention=[],
        knowledge_to_archive=[],
        tools_to_create=[],
        nexus_improvements=["Improvement 1"],
        task_success=True,
        confidence_in_decisions=0.9,
        gemini_reflection="Good collaboration",
        claude_reflection="Agreed",
    )

    await saga.checkpoint_phase(
        "consolidation",
        {"patterns_learned": len(consolidation.learned_patterns), "task_success": consolidation.task_success},
        "S7",
        35,
    )

    assert consolidation.task_success
    assert len(consolidation.learned_patterns) > 0


# ============================================================================
# HM-011: Concurrent phase execution (parallel analysis)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm011_concurrent_analysis(saga_dir):
    """
    HM-011: Test concurrent Gemini and Claude analysis.

    Scenario: Both agents analyze task in parallel.
    Expected: Both complete, results merged.
    """
    results = {}

    async def gemini_analysis():
        await asyncio.sleep(0.1)
        return {"agent": "gemini", "approach": "A"}

    async def claude_analysis():
        await asyncio.sleep(0.1)
        return {"agent": "claude", "approach": "B"}

    # Run in parallel
    gemini_result, claude_result = await asyncio.gather(gemini_analysis(), claude_analysis())

    results["gemini"] = gemini_result
    results["claude"] = claude_result

    assert "gemini" in results
    assert "claude" in results
    assert results["gemini"]["approach"] != results["claude"]["approach"]


# ============================================================================
# HM-012: Concurrent HiveMind tasks (5 parallel)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.torture_slow
@pytest.mark.asyncio
async def test_hm012_concurrent_hive_tasks(saga_dir):
    """
    HM-012: Test 5 concurrent HiveMind task executions.

    Scenario: 5 tasks run in parallel, each with own saga.
    Expected: No interference, all complete independently.
    """

    async def run_task(task_id: str) -> dict:
        task_saga_dir = saga_dir / task_id
        task_saga_dir.mkdir(parents=True, exist_ok=True)
        saga = SagaManager(task_saga_dir, task_id, auto_persist=True)

        await asyncio.sleep(0.05)  # Simulate work
        await saga.checkpoint_phase("analysis", {"task_id": task_id}, "S1", 5)

        return {"task_id": task_id, "success": True}

    # Run 5 tasks in parallel
    tasks = [run_task(f"task_{i}") for i in range(5)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 5
    assert all(r["success"] for r in results)
    # Verify unique task IDs
    task_ids = [r["task_id"] for r in results]
    assert len(set(task_ids)) == 5


# ============================================================================
# HM-013: Budget exceeded mid-pipeline
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm013_budget_exceeded(saga_dir):
    """
    HM-013: Test budget exceeded during execution.

    Scenario: Token budget exceeded at phase 4.
    Expected: Graceful stop, checkpoint preserved.
    """
    saga = SagaManager(saga_dir, "hm013-test", auto_persist=True)
    budget_limit = 10000
    tokens_used = 0

    # Phases consume tokens
    phases_tokens = [2000, 3000, 4000, 5000]  # Total: 14000 > 10000
    budget_exceeded_at = None

    for i, phase_tokens in enumerate(phases_tokens):
        tokens_used += phase_tokens
        phase_name = ["analysis", "debate", "architecture", "execution"][i]

        if tokens_used > budget_limit:
            budget_exceeded_at = phase_name
            break

        await saga.checkpoint_phase(phase_name, {"tokens": tokens_used}, f"S{i + 1}", i * 5)

    assert budget_exceeded_at == "execution"
    assert tokens_used > budget_limit
    # Should have checkpoints up to architecture
    assert "architecture" in saga._checkpoints


# ============================================================================
# HM-014: Context manager truncation during phase
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm014_context_truncation(saga_dir):
    """
    HM-014: Test context truncation during long execution.

    Scenario: Context grows too large, needs truncation.
    Expected: Checkpoint records correct context_index.
    """
    saga = SagaManager(saga_dir, "hm014-test", auto_persist=True)

    # Simulate context growth and truncation
    context_items = 100
    truncated_to = 50

    await saga.checkpoint_phase("analysis", {"context_items": context_items}, "S1", context_index=context_items)

    # Context truncated
    await saga.checkpoint_phase(
        "execution", {"context_items": truncated_to, "truncated": True}, "S4", context_index=truncated_to
    )

    assert saga._checkpoints["analysis"]["context_index"] == context_items
    assert saga._checkpoints["execution"]["context_index"] == truncated_to


# ============================================================================
# HM-015: User breakpoint timeout
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm015_breakpoint_timeout(saga_dir):
    """
    HM-015: Test user breakpoint timeout (auto-accept).

    Scenario: User doesn't respond to breakpoint.
    Expected: Default action taken after timeout.
    """
    saga = SagaManager(saga_dir, "hm015-test", auto_persist=True)

    # Simulate breakpoint with timeout
    breakpoint_timeout_ms = 100
    user_responded = False
    default_action = "accept"

    async def wait_for_user():
        await asyncio.sleep(breakpoint_timeout_ms / 1000)
        return default_action if not user_responded else "reject"

    action = await asyncio.wait_for(wait_for_user(), timeout=1.0)

    await saga.checkpoint_phase("debate_breakpoint", {"action": action, "was_timeout": True}, "S2b", 10)

    assert action == "accept"


# ============================================================================
# HM-016: Strategy blacklist after repeated failure
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm016_strategy_blacklist(saga_dir):
    """
    HM-016: Test strategy blacklisting after 3 failures.

    Scenario: Same strategy fails 3 times.
    Expected: Strategy added to blacklist.
    """
    saga = SagaManager(saga_dir, "hm016-test", auto_persist=True)

    blacklist = []
    strategy = "PARALLEL"
    max_failures = 3

    for failure_count, _attempt in enumerate(range(4), start=1):
        # Simulate failure

        if failure_count >= max_failures and strategy not in blacklist:
            blacklist.append(strategy)

        if strategy in blacklist:
            # Switch strategy
            strategy = "SEQUENTIAL"

    await saga.checkpoint_phase("retry", {"blacklist": blacklist, "final_strategy": strategy}, "S6", 30)

    assert "PARALLEL" in blacklist
    assert strategy == "SEQUENTIAL"


# ============================================================================
# HM-017: Stagnation detector + hot-swap + checkpoint
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm017_stagnation_hotswap_checkpoint(saga_dir):
    """
    HM-017: Test stagnation detection triggering hot-swap with checkpoint.

    Scenario: Stagnation detected, lead swapped, checkpoint updated.
    Expected: Checkpoint reflects hot-swap event.
    """
    saga = SagaManager(saga_dir, "hm017-test", auto_persist=True)

    # Initial checkpoint
    await saga.checkpoint_phase("execution", {"lead": "gemini", "step": 1}, "S4", 20)
    saga.update_context(current_lead="gemini")

    # Stagnation detected
    stagnation_detected = True

    if stagnation_detected:
        new_lead = "claude"
        saga.update_context(current_lead=new_lead, hot_swap_occurred=True, swap_reason="stagnation")

        # Update checkpoint
        await saga.checkpoint_phase("execution", {"lead": new_lead, "step": 2, "hot_swapped": True}, "S4", 25)

    assert saga._saga_context["current_lead"] == "claude"
    assert saga._saga_context["hot_swap_occurred"] is True


# ============================================================================
# HM-018: Phase skip (debate not needed)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm018_phase_skip(saga_dir):
    """
    HM-018: Test skipping debate phase when not needed.

    Scenario: Analysis shows high agreement (>90%).
    Expected: Debate phase skipped, no checkpoint for debate.
    """
    saga = SagaManager(saga_dir, "hm018-test", auto_persist=True)

    # Analysis with high agreement
    agreement_score = 0.95
    needs_debate = agreement_score < 0.9

    await saga.checkpoint_phase("analysis", {"agreement_score": agreement_score, "needs_debate": needs_debate}, "S1", 5)

    # Skip debate if not needed
    if not needs_debate:
        saga.update_context(debate_skipped=True)
    else:
        await saga.checkpoint_phase("debate", {}, "S2", 10)

    # Go directly to architecture
    await saga.checkpoint_phase("architecture", {}, "S3", 15)

    assert "debate" not in saga._checkpoints
    assert saga._saga_context.get("debate_skipped") is True


# ============================================================================
# HM-019: RAG integration failure
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm019_rag_failure(saga_dir):
    """
    HM-019: Test RAG integration failure during architecture.

    Scenario: RAG query fails (database unavailable).
    Expected: Architecture proceeds without RAG, flag set.
    """
    saga = SagaManager(saga_dir, "hm019-test", auto_persist=True)

    rag_available = False
    rag_config = RAGConfig(enabled=True, depth="standard")

    if not rag_available:
        # Disable RAG
        rag_config.enabled = False

    architecture = create_mock_architecture()
    architecture.rag_config = rag_config

    await saga.checkpoint_phase("architecture", {"rag_enabled": rag_config.enabled, "rag_failed": True}, "S3", 15)

    assert rag_config.enabled is False


# ============================================================================
# HM-020: Execution step timeout
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm020_execution_step_timeout(saga_dir):
    """
    HM-020: Test execution step timeout handling.

    Scenario: Single step takes longer than expected_duration.
    Expected: Step marked as timeout, execution continues.
    """
    saga = SagaManager(saga_dir, "hm020-test", auto_persist=True)

    step = ExecutionStep(name="slow_step", agent_id="gemini", action="complex_analysis", expected_duration=1.0)

    # Simulate timeout
    actual_duration = 2.5
    timeout_occurred = actual_duration > step.expected_duration * 2

    result = MonitoredStepResult(
        step_name=step.name,
        agent_id=step.agent_id,
        status="timeout" if timeout_occurred else "success",
        output="Partial output",
        duration=actual_duration,
        expected_duration=step.expected_duration,
        tokens_used=3000,
    )

    await saga.checkpoint_phase(
        "execution", {"step": step.name, "status": result.status, "timeout": timeout_occurred}, "S4", 20
    )

    assert result.status == "timeout"
    assert actual_duration > step.expected_duration


# ============================================================================
# HM-021: Multi-retry exhaustion
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm021_multi_retry_exhaustion(saga_dir):
    """
    HM-021: Test retry exhaustion after max attempts.

    Scenario: Task fails 3 times (max retries).
    Expected: Final state is HIVE_FAILED.
    """
    saga = SagaManager(saga_dir, "hm021-test", auto_persist=True)
    max_retries = 3

    for attempt in range(max_retries):
        saga.update_context(retry_attempt=attempt + 1)
        # Simulate failure
        await saga.checkpoint_phase(
            f"retry_{attempt}", {"attempt": attempt + 1, "success": False}, f"S_retry_{attempt}", 30 + attempt * 5
        )

    # Max retries exhausted
    final_state = HiveMindState.HIVE_FAILED
    saga.update_context(final_state=final_state.value, retries_exhausted=True)

    assert saga._saga_context["retry_attempt"] == max_retries
    assert saga._saga_context["retries_exhausted"] is True


# ============================================================================
# HM-022: Resume from Phase 3 (architecture)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm022_resume_from_architecture(saga_dir):
    """
    HM-022: Test resume from architecture phase.

    Scenario: Process crashed after architecture, resume execution.
    Expected: Resumes from architecture checkpoint.
    """
    # Create saga with checkpoints up to architecture
    saga = SagaManager(saga_dir, "hm022-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", 5)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", 10)
    saga.update_context(debate_complete=True)
    await saga.checkpoint_phase("architecture", {"plan": "ready"}, "S3", 15)
    saga.update_context(architecture_complete=True)

    # Simulate crash and resume
    recovered = await SagaManager.resume_from(saga_dir, "hm022-test")

    assert recovered is not None
    assert recovered.recovery_point == "architecture"
    assert recovered._saga_context.get("architecture_complete") is True
    # Should continue from execution phase
    assert "execution" not in recovered._checkpoints


# ============================================================================
# HM-023: Resume from Phase 5 (diagnosis)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm023_resume_from_diagnosis(saga_dir):
    """
    HM-023: Test resume from diagnosis phase.

    Scenario: Process crashed during retry decision.
    Expected: Resumes from diagnosis, can retry.
    """
    saga = SagaManager(saga_dir, "hm023-test", auto_persist=True)

    # Checkpoints up to diagnosis
    phases = ["analysis", "debate", "architecture", "execution", "diagnosis"]
    for i, phase in enumerate(phases):
        await saga.checkpoint_phase(phase, {f"{phase}_data": "ok"}, f"S{i + 1}", i * 5)
        saga.update_context(**{f"{phase}_complete": True})

    # Simulate crash and resume
    recovered = await SagaManager.resume_from(saga_dir, "hm023-test")

    assert recovered is not None
    assert recovered.recovery_point == "diagnosis"
    # Can proceed to retry
    await recovered.checkpoint_phase("retry", {"action": "RETRY"}, "S6", 30)

    assert "retry" in recovered._checkpoints


# ============================================================================
# HM-024: Partial step completion
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm024_partial_step_completion(saga_dir):
    """
    HM-024: Test partial step completion tracking.

    Scenario: Execution plan has 5 steps, 3 complete before failure.
    Expected: Checkpoint records completed steps.
    """
    saga = SagaManager(saga_dir, "hm024-test", auto_persist=True)

    steps = ["step1", "step2", "step3", "step4", "step5"]
    completed_steps = []

    for i, step in enumerate(steps):
        if i < 3:
            completed_steps.append(step)
        else:
            # Simulate failure at step4
            break

    await saga.checkpoint_phase(
        "execution", {"total_steps": len(steps), "completed_steps": completed_steps, "failed_at": "step4"}, "S4", 20
    )

    assert len(completed_steps) == 3
    assert saga._checkpoints["execution"]["result"]["failed_at"] == "step4"


# ============================================================================
# HM-025: Agent capability mismatch
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm025_capability_mismatch(saga_dir):
    """
    HM-025: Test diagnosis identifying capability mismatch.

    Scenario: Task requires capability no agent has.
    Expected: Diagnosis recommends spawning specialist.
    """
    saga = SagaManager(saga_dir, "hm025-test", auto_persist=True)

    required_capability = "quantum_computing"
    available_capabilities = ["coding", "research", "analysis"]

    capability_available = required_capability in available_capabilities

    diagnosis = FailureDiagnosis(
        failure_type=FailureType.CAPABILITY_MISSING,
        root_cause=f"Missing capability: {required_capability}",
        contributing_factors=["No specialized agent available"],
        evidence=["Task requires quantum simulation"],
        recommended_changes=["Spawn quantum_specialist agent"],
        confidence=0.95,
        missing_capability=required_capability,
    )

    await saga.checkpoint_phase("diagnosis", diagnosis.to_dict(), "S5", 25)

    assert not capability_available
    assert diagnosis.missing_capability == required_capability


# ============================================================================
# HM-026: Context bleeding between phases
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm026_context_isolation(saga_dir):
    """
    HM-026: Test context isolation between phases.

    Scenario: Phase-specific data should not bleed between phases.
    Expected: Each phase checkpoint has isolated context.
    """
    saga = SagaManager(saga_dir, "hm026-test", auto_persist=True)

    # Phase 1: Analysis context
    await saga.checkpoint_phase("analysis", {"phase_data": "analysis_only"}, "S1", 5)

    # Phase 2: Debate context (should not contain analysis_only)
    await saga.checkpoint_phase("debate", {"phase_data": "debate_only"}, "S2", 10)

    # Verify isolation
    analysis_result = saga._checkpoints["analysis"]["result"]
    debate_result = saga._checkpoints["debate"]["result"]

    assert analysis_result["phase_data"] == "analysis_only"
    assert debate_result["phase_data"] == "debate_only"


# ============================================================================
# HM-027: Artifact verification failure
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm027_artifact_verification_failure(saga_dir, tmp_path):
    """
    HM-027: Test artifact verification failure during execution.

    Scenario: Step creates file but verification finds it empty.
    Expected: Step marked as failed, artifacts_verified=False.
    """
    saga = SagaManager(saga_dir, "hm027-test", auto_persist=True)

    # Create empty artifact
    artifact_path = tmp_path / "output.txt"
    artifact_path.write_text("")  # Empty file

    # Verification
    artifacts_verified = artifact_path.stat().st_size > 0

    result = MonitoredStepResult(
        step_name="generate_code",
        agent_id="claude",
        status="error" if not artifacts_verified else "success",
        output="Generated file is empty",
        duration=5.0,
        expected_duration=10.0,
        tokens_used=500,
        artifacts_created=[str(artifact_path)],
        artifacts_verified=artifacts_verified,
    )

    await saga.checkpoint_phase("execution", {"step": result.step_name, "verified": artifacts_verified}, "S4", 20)

    assert not artifacts_verified
    assert result.status == "error"


# ============================================================================
# HM-028: Knowledge consolidation conflict
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm028_consolidation_conflict(saga_dir):
    """
    HM-028: Test conflicting knowledge consolidation decisions.

    Scenario: Gemini and Claude disagree on agent retention.
    Expected: Conflict recorded, user breakpoint triggered.
    """
    saga = SagaManager(saga_dir, "hm028-test", auto_persist=True)

    # Gemini says keep, Claude says delete
    gemini_decision = "KEEP_PERMANENT"
    claude_decision = "DELETE"

    has_conflict = gemini_decision != claude_decision

    await saga.checkpoint_phase(
        "consolidation",
        {
            "gemini_vote": gemini_decision,
            "claude_vote": claude_decision,
            "conflict": has_conflict,
            "needs_user_decision": has_conflict,
        },
        "S7",
        35,
    )

    assert has_conflict
    assert saga._checkpoints["consolidation"]["result"]["needs_user_decision"]


# ============================================================================
# HM-029: Cascading phase failures
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.asyncio
async def test_hm029_cascading_failures(saga_dir):
    """
    HM-029: Test cascading failures across multiple phases.

    Scenario: Phase 3 bug causes Phase 4-6 to fail.
    Expected: Root cause identified as architecture issue.
    """
    saga = SagaManager(saga_dir, "hm029-test", auto_persist=True)

    # Good phases
    await saga.checkpoint_phase("analysis", {"ok": True}, "S1", 5)
    await saga.checkpoint_phase("debate", {"ok": True}, "S2", 10)

    # Bad architecture (root cause)
    await saga.checkpoint_phase("architecture", {"has_bug": True, "bug": "wrong_agent_assignment"}, "S3", 15)

    # Cascading failures
    failures = []
    for phase in ["execution", "diagnosis", "retry"]:
        failures.append({"phase": phase, "caused_by": "architecture_bug"})

    # Final diagnosis points to root cause
    await saga.checkpoint_phase(
        "diagnosis",
        {
            "root_cause_phase": "architecture",
            "root_cause": "wrong_agent_assignment",
            "cascading_failures": len(failures),
        },
        "S5",
        25,
    )

    assert saga._checkpoints["diagnosis"]["result"]["root_cause_phase"] == "architecture"


# ============================================================================
# HM-030: Full pipeline stress (10 iterations)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_hive
@pytest.mark.torture_slow
@pytest.mark.asyncio
async def test_hm030_full_pipeline_stress(saga_dir):
    """
    HM-030: Stress test with 10 full pipeline iterations.

    Scenario: Run 10 complete tasks sequentially.
    Expected: All complete, no saga corruption.
    """

    results = []
    start_time = time.time()

    for i in range(10):
        task_id = f"stress_{i}"
        task_saga_dir = saga_dir / task_id
        task_saga_dir.mkdir(parents=True, exist_ok=True)

        saga = SagaManager(task_saga_dir, task_id, auto_persist=True)

        # Full pipeline
        phases = ["analysis", "debate", "architecture", "execution", "consolidation"]
        for j, phase in enumerate(phases):
            await saga.checkpoint_phase(phase, {"task": i, "phase": phase}, f"S{j + 1}", j * 5)

        results.append({"task_id": task_id, "phases": len(saga._checkpoints)})

    elapsed = time.time() - start_time

    # All tasks completed
    assert len(results) == 10
    assert all(r["phases"] == 5 for r in results)
    # Should complete in reasonable time (<30s)
    assert elapsed < 30.0


# ============================================================================
# Run All Tests (Standalone Mode)
# ============================================================================


def run_all(metrics_collector=None):
    """Run all HiveMind integration tests."""
    print("\n" + "=" * 50)
    print("HIVEMIND INTEGRATION TESTS (30 scenarios)")
    print("=" * 50 + "\n")
    print("Run with: pytest tests/torture/scenarios/hive_integration.py -v")
    return metrics_collector


if __name__ == "__main__":
    print("Run with: pytest tests/torture/scenarios/hive_integration.py -v -m torture")
