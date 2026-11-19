import json
import time
from pathlib import Path

from core.foundation.agents.unified_registry import get_registry
from core.infrastructure.resilience.unified_rate_limiter import APIRateLimiterRegistry
from core.intelligence.swarm.eval_harness import SwarmEvalHarness


def test_swarm_eval_harness_runs_all_strategies(tmp_path: Path) -> None:
    harness = SwarmEvalHarness(output_root=tmp_path)
    report = harness.run()

    assert report.task_count > 0
    assert len(report.strategy_summaries) == 3
    strategies = {summary.strategy for summary in report.strategy_summaries}
    assert strategies == {"single_agent", "deterministic_pipeline", "swarm"}

    runs_by_strategy = {strategy: [run for run in report.runs if run.strategy == strategy] for strategy in strategies}
    for strategy, runs in runs_by_strategy.items():
        assert runs, strategy


def test_swarm_eval_harness_writes_report(tmp_path: Path) -> None:
    harness = SwarmEvalHarness(output_root=tmp_path)
    report = harness.run()
    output_dir = harness.write_report(report)

    report_json = output_dir / "report.json"
    report_md = output_dir / "report.md"
    assert report_json.exists()
    assert report_md.exists()

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["task_count"] == report.task_count
    assert payload["strategy_summaries"]

    markdown = report_md.read_text(encoding="utf-8")
    assert "# Swarm Evaluation Harness" in markdown
    assert "Strategy Summary" in markdown
    assert "`swarm`" in markdown


def test_swarm_eval_harness_records_recovery(tmp_path: Path) -> None:
    harness = SwarmEvalHarness(output_root=tmp_path)
    report = harness.run()

    swarm_runs = [run for run in report.runs if run.strategy == "swarm"]
    assert swarm_runs
    assert any(run.recovered for run in swarm_runs)


def test_swarm_eval_harness_runs_the_requested_collaboration_modes(tmp_path: Path) -> None:
    """The harness evidences the swarm, so no multi-agent mode may be silently degraded to a single agent."""
    harness = SwarmEvalHarness(output_root=tmp_path)
    report = harness.run()

    preferred = {case.task_id: case.preferred_mode.value for case in harness.task_cases}
    actual = {run.task_id: run.mode for run in report.runs if run.strategy == "swarm"}
    assert actual == preferred


def test_swarm_eval_harness_is_not_throttled_by_provider_quotas(tmp_path: Path) -> None:
    """The simulated agents are offline, so real provider rate limits must not turn the run into minutes."""
    harness = SwarmEvalHarness(output_root=tmp_path)

    started = time.monotonic()
    harness.run()
    elapsed = time.monotonic() - started

    assert elapsed < 30, f"deterministic harness took {elapsed:.0f}s"


def test_swarm_eval_harness_restores_global_registry_and_limiter_state(tmp_path: Path) -> None:
    """Simulated providers and their quotas exist only while the harness runs."""
    registry = get_registry()
    limiters = APIRateLimiterRegistry()
    active_before = list(registry.get_active_builtin_ids())
    limiter_keys_before = set(limiters._limiters)

    SwarmEvalHarness(output_root=tmp_path).run()

    assert registry.get_active_builtin_ids() == active_before
    assert set(limiters._limiters) == limiter_keys_before
