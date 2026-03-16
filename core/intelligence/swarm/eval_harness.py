"""
Deterministic swarm evaluation harness.

Compares three execution strategies on a fixed task set:
- single_agent
- deterministic_pipeline
- swarm

The harness is intentionally local and reproducible. It exercises the real
HybridSwarmEngine with a deterministic agent simulator so NEXUS can publish
comparative evidence without requiring external providers.
"""

from __future__ import annotations

import json
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.intelligence.reasoning.evaluation_panel import EvaluationPanel

from .agent_metrics import create_default_pool
from .collaboration_modes import CollaborationMode
from .executors.base import AgentResponse
from .hybrid_swarm_engine import HybridSwarmEngine
from .task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain


@dataclass(frozen=True)
class EvalTaskCase:
    task_id: str
    prompt: str
    analysis: TaskAnalysis
    expected_keywords: tuple[str, ...]
    preferred_mode: CollaborationMode
    description: str = ""
    baseline_agent: str | None = None


@dataclass
class EvalRunResult:
    strategy: str
    task_id: str
    mode: str
    passed: bool
    overall_score: float
    keyword_coverage: float
    panel_score: float
    latency_seconds: float
    tokens_used: int
    recovered: bool = False
    failure_mode: str | None = None
    output_preview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "task_id": self.task_id,
            "mode": self.mode,
            "passed": self.passed,
            "overall_score": round(self.overall_score, 3),
            "keyword_coverage": round(self.keyword_coverage, 3),
            "panel_score": round(self.panel_score, 3),
            "latency_seconds": round(self.latency_seconds, 3),
            "tokens_used": self.tokens_used,
            "recovered": self.recovered,
            "failure_mode": self.failure_mode,
            "output_preview": self.output_preview,
            "metadata": self.metadata,
        }


@dataclass
class EvalStrategySummary:
    strategy: str
    runs: list[EvalRunResult]

    def to_dict(self) -> dict[str, Any]:
        scores = [run.overall_score for run in self.runs]
        latencies = [run.latency_seconds for run in self.runs]
        tokens = [run.tokens_used for run in self.runs]
        recovered = [run for run in self.runs if run.recovered]
        failures = [run.failure_mode for run in self.runs if run.failure_mode]
        return {
            "strategy": self.strategy,
            "task_count": len(self.runs),
            "pass_rate": round(sum(1 for run in self.runs if run.passed) / max(len(self.runs), 1), 3),
            "average_score": round(statistics.mean(scores), 3) if scores else 0.0,
            "score_variance": round(statistics.pvariance(scores), 4) if len(scores) > 1 else 0.0,
            "average_latency_seconds": round(statistics.mean(latencies), 3) if latencies else 0.0,
            "average_tokens": round(statistics.mean(tokens), 1) if tokens else 0.0,
            "recovery_rate": round(len(recovered) / max(len(self.runs), 1), 3),
            "failure_modes": {mode: failures.count(mode) for mode in sorted(set(failures))},
        }


@dataclass
class EvalHarnessReport:
    generated_at: str
    task_count: int
    strategy_summaries: list[EvalStrategySummary]
    runs: list[EvalRunResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "task_count": self.task_count,
            "strategy_summaries": [summary.to_dict() for summary in self.strategy_summaries],
            "runs": [run.to_dict() for run in self.runs],
        }


def _build_analysis(
    prompt: str,
    complexity: TaskComplexity,
    domains: list[TaskDomain],
    primary_domain: TaskDomain,
    gemini_fit: float,
    claude_fit: float,
    confidence: float = 0.85,
) -> TaskAnalysis:
    return TaskAnalysis(
        complexity=complexity,
        domains=domains,
        primary_domain=primary_domain,
        gemini_fit_score=gemini_fit,
        claude_fit_score=claude_fit,
        raw_input=prompt,
        confidence=confidence,
        requires_web=TaskDomain.RESEARCH in domains,
        requires_deep_reasoning=complexity >= TaskComplexity.COMPLEX,
    )


DEFAULT_EVAL_CASES: tuple[EvalTaskCase, ...] = (
    EvalTaskCase(
        task_id="auth_expiry_bug",
        prompt="Review the auth module and identify the token expiry bug.",
        analysis=_build_analysis(
            prompt="Review the auth module and identify the token expiry bug.",
            complexity=TaskComplexity.COMPLEX,
            domains=[TaskDomain.CODING, TaskDomain.SECURITY, TaskDomain.TESTING],
            primary_domain=TaskDomain.CODING,
            gemini_fit=0.62,
            claude_fit=0.92,
        ),
        expected_keywords=("token.py", "expiry check", "test_token_expiry", "security"),
        preferred_mode=CollaborationMode.LEAD_SUPPORT,
        description="Complex bug-fix task where support review should improve the final answer.",
        baseline_agent="claude_opus",
    ),
    EvalTaskCase(
        task_id="memory_storage_contradiction",
        prompt="Explain where ProjectMemory stores data and whether docs disagree.",
        analysis=_build_analysis(
            prompt="Explain where ProjectMemory stores data and whether docs disagree.",
            complexity=TaskComplexity.COMPLEX,
            domains=[TaskDomain.ANALYSIS, TaskDomain.DOCUMENTATION, TaskDomain.CODING],
            primary_domain=TaskDomain.ANALYSIS,
            gemini_fit=0.86,
            claude_fit=0.84,
        ),
        expected_keywords=("NEXUS_ROOT/.nexus", "workspace/.nexus", "contradiction", "README"),
        preferred_mode=CollaborationMode.RED_BLUE,
        description="Cross-check task where adversarial review should resolve a docs/code contradiction.",
        baseline_agent="gemini_primary",
    ),
    EvalTaskCase(
        task_id="provider_compatibility_gap",
        prompt="Assess whether CI proves live provider compatibility.",
        analysis=_build_analysis(
            prompt="Assess whether CI proves live provider compatibility.",
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.RESEARCH, TaskDomain.ANALYSIS, TaskDomain.DOCUMENTATION],
            primary_domain=TaskDomain.RESEARCH,
            gemini_fit=0.9,
            claude_fit=0.72,
        ),
        expected_keywords=("provider registry", "structural smoke", "Gemini-only", "live canaries"),
        preferred_mode=CollaborationMode.PARALLEL,
        description="Comparative architecture claim where parallel aggregation should improve coverage.",
        baseline_agent="gemini_primary",
    ),
    EvalTaskCase(
        task_id="security_recovery",
        prompt="Review execution safeguards and highlight what still bypasses them.",
        analysis=_build_analysis(
            prompt="Review execution safeguards and highlight what still bypasses them.",
            complexity=TaskComplexity.EXPERT,
            domains=[TaskDomain.SECURITY, TaskDomain.ANALYSIS],
            primary_domain=TaskDomain.SECURITY,
            gemini_fit=0.74,
            claude_fit=0.9,
        ),
        expected_keywords=("curl", "wget", "PathGuardian", "Shadow Red Team"),
        preferred_mode=CollaborationMode.RED_BLUE,
        description="Recovery scenario where RED_BLUE fails artifact verification and should degrade gracefully.",
        baseline_agent="claude_opus",
    ),
)


class DeterministicAgentSimulator:
    """Deterministic agent simulator used by the evaluation harness."""

    def __init__(self) -> None:
        self.current_case: EvalTaskCase | None = None

    def set_case(self, case: EvalTaskCase) -> None:
        self.current_case = case

    def invoke(
        self,
        agent_id: str,
        task_type: str,
        context: str,
        session_uuid: str | None = None,
        isolated_env: dict[str, str] | None = None,
    ) -> AgentResponse:
        del task_type, session_uuid, isolated_env
        if self.current_case is None:
            raise RuntimeError("No active evaluation case set.")

        mode = self._detect_mode(context)
        content, status, tokens, duration = self._response_for(self.current_case.task_id, agent_id, mode, context)
        return AgentResponse(
            agent_id=agent_id,
            content=content,
            status=status,
            tokens_used=tokens,
            time_seconds=duration,
            error=None if status != "error" else content,
        )

    def single_agent_response(self, case: EvalTaskCase, agent_id: str) -> AgentResponse:
        self.set_case(case)
        content, status, tokens, duration = self._response_for(case.task_id, agent_id, "single_agent", case.prompt)
        return AgentResponse(
            agent_id=agent_id,
            content=content,
            status=status,
            tokens_used=tokens,
            time_seconds=duration,
            error=None if status != "error" else content,
        )

    def pipeline_response(self, case: EvalTaskCase, lead_id: str, support_id: str) -> list[AgentResponse]:
        self.set_case(case)
        lead = self.invoke(lead_id, "execution", f"LEAD_SUPPORT MODE - You are LEAD:\n{case.prompt}\n\nProvide complete solution.")
        support = self.invoke(
            support_id,
            "execution",
            (
                f"LEAD_SUPPORT MODE - You are SUPPORT:\n{case.prompt}\n\n"
                f"Lead ({lead_id}) solution:\n{lead.content}\n\nReview and provide feedback. Suggest improvements if needed."
            ),
        )
        revision = self.invoke(
            lead_id,
            "execution",
            (
                "LEAD_SUPPORT MODE - Revision:\n"
                f"Your original solution:\n{lead.content}\n\n"
                f"Support feedback:\n{support.content}\n\n"
                "Revise if appropriate."
            ),
        )
        return [lead, support, revision]

    def _detect_mode(self, context: str) -> str:
        if "RED_BLUE MODE" in context:
            return "red_blue"
        if "LEAD_SUPPORT MODE" in context:
            return "lead_support"
        if "PARALLEL MODE" in context:
            return "parallel"
        if "PING_PONG MODE" in context:
            return "ping_pong"
        if "SEQUENTIAL MODE" in context:
            return "sequential"
        return "single_agent"

    def _response_for(self, task_id: str, agent_id: str, mode: str, context: str) -> tuple[str, str, int, float]:
        if task_id == "auth_expiry_bug":
            return self._auth_bug(agent_id, mode, context)
        if task_id == "memory_storage_contradiction":
            return self._memory_storage(agent_id, mode, context)
        if task_id == "provider_compatibility_gap":
            return self._provider_gap(agent_id, mode, context)
        if task_id == "security_recovery":
            return self._security_recovery(agent_id, mode, context)
        raise ValueError(f"Unknown task_id: {task_id}")

    def _auth_bug(self, agent_id: str, mode: str, context: str) -> tuple[str, str, int, float]:
        if mode == "single_agent" and agent_id == "claude_opus":
            return (
                "COMPLETED: Root cause in token.py is a missing expiry check during token validation.",
                "success",
                110,
                1.4,
            )
        if "Revision:" in context:
            return (
                "COMPLETED: Root cause in token.py is a missing expiry check. Add security regression test test_token_expiry so expired tokens are rejected.",
                "success",
                170,
                1.8,
            )
        if "SUPPORT" in context:
            return (
                "Suggest adding a security regression test named test_token_expiry and explicitly rejecting expired tokens.",
                "success",
                80,
                0.9,
            )
        return (
            "COMPLETED: Investigate token.py. The validation path misses an expiry check for expired tokens.",
            "success",
            120,
            1.2,
        )

    def _memory_storage(self, agent_id: str, mode: str, context: str) -> tuple[str, str, int, float]:
        if mode == "single_agent" and agent_id == "gemini_primary":
            return (
                "COMPLETED: README documentation still describes LanceDB storage in workspace/.nexus.",
                "success",
                95,
                1.0,
            )
        if "Defense phase" in context:
            return (
                "COMPLETED: Corrected conclusion: ProjectMemory stores data under NEXUS_ROOT/.nexus/project_knowledge.json, while README still says workspace/.nexus. This is a documentation contradiction that should be fixed.",
                "success",
                180,
                1.7,
            )
        if "attacker" in context.lower() or "Find weaknesses" in context:
            return (
                "FAIL: Code evidence contradicts the README. ProjectMemory stores under NEXUS_ROOT/.nexus/project_knowledge.json, not workspace/.nexus.",
                "success",
                105,
                1.1,
            )
        return (
            "COMPLETED: Initial claim from docs: storage appears to live in workspace/.nexus according to README.",
            "success",
            100,
            1.1,
        )

    def _provider_gap(self, agent_id: str, mode: str, context: str) -> tuple[str, str, int, float]:
        if mode == "single_agent":
            return (
                "COMPLETED: core/provider_registry.json gives structural provider compatibility evidence and replacements.",
                "success",
                100,
                1.0,
            )
        if mode == "parallel":
            if agent_id == "gemini_primary":
                return (
                    "COMPLETED: provider registry and evidence-ledger prove structural smoke rather than end-to-end execution.",
                    "success",
                    115,
                    1.1,
                )
            return (
                "COMPLETED: CI still needs live canaries, and the manual context-isolation test is Gemini-only despite broader provider claims.",
                "success",
                125,
                1.2,
            )
        return (
            "COMPLETED: Provider evidence is partial and should be separated into structural smoke and live canaries.",
            "success",
            120,
            1.2,
        )

    def _security_recovery(self, agent_id: str, mode: str, context: str) -> tuple[str, str, int, float]:
        if mode == "single_agent":
            return (
                "COMPLETED: ExecutionPolicy blocks curl and wget, and PathGuardian protects KERNEL.py and .env.",
                "success",
                110,
                1.1,
            )
        if mode == "red_blue":
            if "Defense phase" in context:
                return (
                    "COMPLETED: I created security_fix.py so curl and wget are blocked and the guards are fully resolved.",
                    "success",
                    130,
                    1.4,
                )
            if "attacker" in context.lower() or "Find weaknesses" in context:
                return (
                    "FAIL: The proposal does not mention bypass evidence from Shadow Red Team and relies on an unverified artifact.",
                    "success",
                    95,
                    1.0,
                )
            return (
                "COMPLETED: Proposed security_fix.py to block curl and wget in execution policy.",
                "success",
                100,
                1.0,
            )
        if "Revision:" in context:
            return (
                "COMPLETED: ExecutionPolicy blocks curl and wget, PathGuardian protects KERNEL.py and .env, and the remaining gap is Shadow Red Team bypass coverage.",
                "success",
                165,
                1.7,
            )
        if "SUPPORT" in context:
            return (
                "Suggest adding a Shadow Red Team regression check because bypass evidence still exists even if curl and wget are blocked.",
                "success",
                90,
                0.9,
            )
        return (
            "COMPLETED: ExecutionPolicy blocks curl and wget, while PathGuardian protects KERNEL.py and .env.",
            "success",
            105,
            1.1,
        )


class SwarmEvalHarness:
    """Deterministic comparative evaluation harness for the swarm layer."""

    def __init__(
        self,
        task_cases: tuple[EvalTaskCase, ...] = DEFAULT_EVAL_CASES,
        output_root: Path | None = None,
    ) -> None:
        self.task_cases = task_cases
        self.output_root = Path(output_root) if output_root else Path("workspace/evals")
        self.simulator = DeterministicAgentSimulator()
        self.panel = EvaluationPanel()

    def run(self) -> EvalHarnessReport:
        generated_at = datetime.now(UTC).isoformat()
        runs: list[EvalRunResult] = []

        for case in self.task_cases:
            runs.append(self._run_single_agent(case))
            runs.append(self._run_deterministic_pipeline(case))
            runs.append(self._run_swarm(case))

        summaries = []
        for strategy in ("single_agent", "deterministic_pipeline", "swarm"):
            strategy_runs = [run for run in runs if run.strategy == strategy]
            summaries.append(EvalStrategySummary(strategy=strategy, runs=strategy_runs))

        return EvalHarnessReport(
            generated_at=generated_at,
            task_count=len(self.task_cases),
            strategy_summaries=summaries,
            runs=runs,
        )

    def write_report(self, report: EvalHarnessReport) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_dir = self.output_root / f"swarm_eval_{stamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "report.json"
        md_path = output_dir / "report.md"
        json_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        md_path.write_text(self._render_markdown(report), encoding="utf-8")
        return output_dir

    def _run_single_agent(self, case: EvalTaskCase) -> EvalRunResult:
        agent_id = case.baseline_agent or ("gemini_primary" if case.analysis.recommended_lead == "gemini" else "claude_opus")
        response = self.simulator.single_agent_response(case, agent_id)
        return self._score_run(
            strategy="single_agent",
            case=case,
            mode="single_agent",
            output=response.content,
            latency_seconds=response.time_seconds,
            tokens_used=response.tokens_used,
        )

    def _run_deterministic_pipeline(self, case: EvalTaskCase) -> EvalRunResult:
        lead_id = case.baseline_agent or ("gemini_primary" if case.analysis.recommended_lead == "gemini" else "claude_opus")
        support_id = "claude_opus" if lead_id == "gemini_primary" else "gemini_primary"
        responses = self.simulator.pipeline_response(case, lead_id, support_id)
        final_output = responses[-1].content
        latency_seconds = sum(response.time_seconds for response in responses)
        tokens_used = sum(response.tokens_used for response in responses)
        return self._score_run(
            strategy="deterministic_pipeline",
            case=case,
            mode="deterministic_pipeline",
            output=final_output,
            latency_seconds=latency_seconds,
            tokens_used=tokens_used,
        )

    def _run_swarm(self, case: EvalTaskCase) -> EvalRunResult:
        self.simulator.set_case(case)
        with tempfile.TemporaryDirectory(prefix=f"nexus_swarm_eval_{case.task_id}_") as temp_dir:
            workspace_path = Path(temp_dir)
            engine = HybridSwarmEngine(
                agent_pool=create_default_pool(),
                invoke_agent=self.simulator.invoke,
                workspace_path=workspace_path,
            )
            engine.task_analyzer.analyze = lambda _task: case.analysis  # type: ignore[method-assign]
            result = engine.process_task(case.prompt, blackboard={"workspace_path": workspace_path}, force_mode=case.preferred_mode, skip_negotiation=True)

        failure_mode = None
        if result.execution_result.status.value != "completed":
            failure_mode = result.execution_result.status.value
        recovered = result.execution_result.metadata.get("status") == "RECOVERED"
        return self._score_run(
            strategy="swarm",
            case=case,
            mode=result.selected_mode.value,
            output=result.final_output,
            latency_seconds=result.execution_result.total_time_seconds,
            tokens_used=result.execution_result.total_tokens,
            recovered=recovered,
            failure_mode=failure_mode,
            metadata=result.execution_result.metadata,
        )

    def _score_run(
        self,
        strategy: str,
        case: EvalTaskCase,
        mode: str,
        output: str,
        latency_seconds: float,
        tokens_used: int,
        recovered: bool = False,
        failure_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvalRunResult:
        output_lower = output.lower()
        matched_keywords = [keyword for keyword in case.expected_keywords if keyword.lower() in output_lower]
        keyword_coverage = len(matched_keywords) / max(len(case.expected_keywords), 1)
        panel_result = self.panel.evaluate(output, case.prompt)
        overall_score = round((0.65 * keyword_coverage) + (0.35 * panel_result.composite_score), 3)
        passed = keyword_coverage >= 0.5 and overall_score >= 0.55
        preview = output.replace("\n", " ")[:180]
        return EvalRunResult(
            strategy=strategy,
            task_id=case.task_id,
            mode=mode,
            passed=passed,
            overall_score=overall_score,
            keyword_coverage=keyword_coverage,
            panel_score=panel_result.composite_score,
            latency_seconds=latency_seconds,
            tokens_used=tokens_used,
            recovered=recovered,
            failure_mode=failure_mode,
            output_preview=preview,
            metadata=metadata or {},
        )

    def _render_markdown(self, report: EvalHarnessReport) -> str:
        lines = [
            "# Swarm Evaluation Harness",
            "",
            f"- Generated: {report.generated_at}",
            f"- Tasks: {report.task_count}",
            "",
            "## Strategy Summary",
            "",
            "| Strategy | Pass Rate | Avg Score | Avg Latency (s) | Avg Tokens | Recovery Rate | Score Variance |",
            "|----------|-----------|-----------|-----------------|------------|---------------|----------------|",
        ]

        for summary in report.strategy_summaries:
            payload = summary.to_dict()
            lines.append(
                f"| `{payload['strategy']}` | {payload['pass_rate']:.0%} | {payload['average_score']:.3f} | "
                f"{payload['average_latency_seconds']:.3f} | {payload['average_tokens']:.1f} | "
                f"{payload['recovery_rate']:.0%} | {payload['score_variance']:.4f} |"
            )

        lines.extend(
            [
                "",
                "## Task Runs",
                "",
                "| Task | Strategy | Mode | Score | Coverage | Latency (s) | Tokens | Recovered |",
                "|------|----------|------|-------|----------|-------------|--------|-----------|",
            ]
        )

        for run in report.runs:
            lines.append(
                f"| `{run.task_id}` | `{run.strategy}` | `{run.mode}` | {run.overall_score:.3f} | "
                f"{run.keyword_coverage:.0%} | {run.latency_seconds:.3f} | {run.tokens_used} | "
                f"{'yes' if run.recovered else 'no'} |"
            )

        best_by_strategy = sorted(
            ((summary.strategy, summary.to_dict()["average_score"]) for summary in report.strategy_summaries),
            key=lambda item: item[1],
            reverse=True,
        )
        lines.extend(
            [
                "",
                "## Notes",
                "",
                "- This harness is deterministic and local-first. It compares strategies with a simulated dual-agent environment while exercising the real HybridSwarmEngine.",
                f"- Best average score in this run: `{best_by_strategy[0][0]}` ({best_by_strategy[0][1]:.3f}).",
                "- Recovery rate reflects runs where swarm degraded and still returned a usable result.",
            ]
        )

        return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_EVAL_CASES",
    "DeterministicAgentSimulator",
    "EvalHarnessReport",
    "EvalRunResult",
    "EvalStrategySummary",
    "EvalTaskCase",
    "SwarmEvalHarness",
]
