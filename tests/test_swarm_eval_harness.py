import json
from pathlib import Path

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
