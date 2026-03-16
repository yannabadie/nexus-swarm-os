#!/usr/bin/env python3
"""
Generate a machine-readable CI evidence ledger.

Consumes pytest JUnit XML, coverage XML, workflow/job metadata, and the
provider compatibility registry to produce:
- a JSON ledger for automation
- a Markdown summary for humans and release notes
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _find_first_json(root: Path | None, filename: str) -> Path | None:
    if root is None or not root.exists():
        return None
    matches = sorted(root.glob(f"**/{filename}"))
    return matches[0] if matches else None


def _parse_junit(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "tests": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "passed": 0,
            "duration_seconds": None,
        }

    root = ElementTree.parse(path).getroot()
    suites = root
    if root.tag == "testsuite":
        suites = root

    tests = int(suites.attrib.get("tests", "0"))
    failures = int(suites.attrib.get("failures", "0"))
    errors = int(suites.attrib.get("errors", "0"))
    skipped = int(suites.attrib.get("skipped", "0"))
    duration = suites.attrib.get("time")
    duration_seconds = float(duration) if duration is not None else None

    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": max(tests - failures - errors - skipped, 0),
        "duration_seconds": duration_seconds,
    }


def _parse_coverage(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "line_rate": None,
            "line_percent": None,
            "lines_covered": None,
            "lines_valid": None,
        }

    root = ElementTree.parse(path).getroot()
    line_rate = root.attrib.get("line-rate")
    lines_covered = root.attrib.get("lines-covered")
    lines_valid = root.attrib.get("lines-valid")
    line_rate_value = float(line_rate) if line_rate is not None else None

    return {
        "line_rate": line_rate_value,
        "line_percent": round(line_rate_value * 100, 2) if line_rate_value is not None else None,
        "lines_covered": int(lines_covered) if lines_covered is not None else None,
        "lines_valid": int(lines_valid) if lines_valid is not None else None,
    }


def _git_commit_subject() -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def _job_pairs(raw_jobs: list[str]) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    for entry in raw_jobs:
        if "=" not in entry:
            raise ValueError(f"Invalid job result entry: {entry!r}")
        name, result = entry.split("=", 1)
        jobs.append({"name": name.strip(), "result": result.strip()})
    return jobs


def _artifact_entries(raw_artifacts: list[str]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for entry in raw_artifacts:
        if "=" in entry:
            name, value = entry.split("=", 1)
        else:
            name, value = entry, entry
        artifact_path = Path(value.strip())
        artifacts.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "status": "present" if artifact_path.exists() else "missing",
            }
        )
    return artifacts


def _categorize_jobs(jobs: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    categories = {
        "quality_gates": [],
        "structural_smoke": [],
        "live_provider_evidence": [],
        "stress_or_long_running": [],
        "other": [],
    }

    for job in jobs:
        name = job["name"]
        if name in {"unit-tests", "lint-type-check", "security-scan", "build-wheel"}:
            categories["quality_gates"].append(job)
        elif "integration" in name or "canary" in name:
            categories["live_provider_evidence"].append(job)
        elif "torture" in name:
            categories["stress_or_long_running"].append(job)
        elif "smoke" in name or name == "install-smoke":
            categories["structural_smoke"].append(job)
        else:
            categories["other"].append(job)

    return categories


def _provider_rows(provider_registry: dict[str, Any]) -> list[dict[str, str]]:
    """Flatten the provider registry into markdown-friendly rows."""
    providers = provider_registry.get("providers", {})
    replacements = provider_registry.get("replacements", {})
    rows: list[dict[str, str]] = []

    if not isinstance(providers, dict):
        return rows

    for provider_name, provider_data in providers.items():
        for family_name, model_data in provider_data.get("models", {}).items():
            default_model = model_data.get("default")
            if not default_model:
                continue
            rows.append(
                {
                    "provider": provider_name,
                    "family": family_name,
                    "model": default_model,
                    "status": "supported",
                    "replacement": replacements.get(default_model, "n/a"),
                    "sunset": model_data.get("sunset", "n/a"),
                }
            )

    return rows


def _build_ledger(args: argparse.Namespace) -> dict[str, Any]:
    junit = _parse_junit(args.junit_xml)
    coverage = _parse_coverage(args.coverage_xml)
    providers = _read_json(args.provider_registry) or {"providers": [], "generated_at": None}
    shadow_redteam = _read_json(args.shadow_redteam_json)
    provider_canaries = _read_json(args.provider_canaries_json)
    swarm_eval_report = _read_json(_find_first_json(args.swarm_eval_root, "report.json"))
    jobs = _job_pairs(args.job_result)
    artifacts = _artifact_entries(args.artifact)
    non_success_jobs = [job for job in jobs if job["result"] != "success"]
    missing_artifacts = [artifact for artifact in artifacts if artifact["status"] != "present"]

    return {
        "schema_version": 1,
        "generated_at": _iso_now(),
        "evidence_status": "partial" if non_success_jobs or missing_artifacts else "complete",
        "workflow": {
            "name": args.workflow_name,
            "run_id": args.run_id,
            "run_url": args.run_url,
            "branch": args.branch,
            "sha": args.sha,
            "commit_subject": _git_commit_subject(),
        },
        "quality": {
            "pytest": junit,
            "coverage": coverage,
            "jobs": jobs,
            "job_categories": _categorize_jobs(jobs),
        },
        "artifacts": artifacts,
        "security": {
            "shadow_redteam": shadow_redteam,
        },
        "swarm_evaluation": swarm_eval_report,
        "live_provider_canaries": provider_canaries,
        "provider_compatibility": providers,
        "environment": {
            "python_version": args.python_version,
            "platform": sys.platform,
            "workspace": str(Path.cwd()),
            "ci": os.getenv("CI", "false").lower() in {"1", "true", "yes"},
        },
    }


def _write_markdown(path: Path, ledger: dict[str, Any]) -> None:
    pytest_data = ledger["quality"]["pytest"]
    coverage = ledger["quality"]["coverage"]
    categorized_jobs = ledger["quality"]["job_categories"]
    lines = [
        "# CI Evidence Ledger",
        "",
        f"- Evidence status: {ledger['evidence_status']}",
        f"- Workflow: {ledger['workflow']['name']}",
        f"- Branch: {ledger['workflow']['branch']}",
        f"- SHA: {ledger['workflow']['sha']}",
        f"- Generated: {ledger['generated_at']}",
        "",
        "## Quality",
        "",
        f"- Tests collected: {pytest_data['tests']}",
        f"- Passed: {pytest_data['passed']}",
        f"- Failed: {pytest_data['failures']}",
        f"- Errors: {pytest_data['errors']}",
        f"- Skipped: {pytest_data['skipped']}",
        f"- Coverage: {coverage['line_percent']}%",
        "",
        "## Quality Gates",
        "",
    ]

    for job in categorized_jobs["quality_gates"]:
        lines.append(f"- {job['name']}: {job['result']}")

    lines.extend(
        [
            "",
            "## Structural Smoke",
            "",
        ]
    )

    if categorized_jobs["structural_smoke"]:
        for job in categorized_jobs["structural_smoke"]:
            lines.append(f"- {job['name']}: {job['result']}")
    else:
        lines.append("- No structural smoke jobs recorded.")

    lines.extend(
        [
            "",
            "## Live Provider Evidence",
            "",
        ]
    )

    if categorized_jobs["live_provider_evidence"]:
        for job in categorized_jobs["live_provider_evidence"]:
            lines.append(f"- {job['name']}: {job['result']}")
    else:
        lines.append("- No live provider evidence recorded in this ledger.")

    lines.extend(
        [
            "",
            "## Stress / Long-Running Jobs",
            "",
        ]
    )

    if categorized_jobs["stress_or_long_running"]:
        for job in categorized_jobs["stress_or_long_running"]:
            lines.append(f"- {job['name']}: {job['result']}")
    else:
        lines.append("- No stress or long-running jobs recorded.")

    if categorized_jobs["other"]:
        lines.extend(
            [
                "",
                "## Other Jobs",
                "",
            ]
        )
        for job in categorized_jobs["other"]:
            lines.append(f"- {job['name']}: {job['result']}")

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
        ]
    )

    for artifact in ledger["artifacts"]:
        lines.append(f"- {artifact['name']}: {artifact['status']} ({artifact['value']})")

    shadow_redteam = ledger.get("security", {}).get("shadow_redteam")
    lines.extend(
        [
            "",
            "## Security Evidence",
            "",
        ]
    )
    if shadow_redteam:
        lines.append(f"- Shadow Red Team total attacks: {shadow_redteam.get('total_attacks')}")
        lines.append(f"- Shadow Red Team bypassed attacks: {shadow_redteam.get('bypassed_attacks')}")
        lines.append(f"- Shadow Red Team attack success rate: {shadow_redteam.get('attack_success_rate'):.2%}")
        lines.append(f"- Shadow Red Team false positive rate: {shadow_redteam.get('false_positive_rate'):.2%}")
    else:
        lines.append("- No Shadow Red Team snapshot available.")

    swarm_eval = ledger.get("swarm_evaluation")
    lines.extend(
        [
            "",
            "## Swarm Evaluation",
            "",
        ]
    )
    if swarm_eval:
        for summary in swarm_eval.get("strategy_summaries", []):
            lines.append(
                f"- {summary['strategy']}: pass_rate={summary['pass_rate']:.0%}, "
                f"avg_score={summary['average_score']:.3f}, "
                f"recovery_rate={summary['recovery_rate']:.0%}"
            )
    else:
        lines.append("- No swarm evaluation report available.")

    provider_canaries = ledger.get("live_provider_canaries")
    lines.extend(
        [
            "",
            "## Live Provider Canaries",
            "",
        ]
    )
    if provider_canaries:
        summary = provider_canaries.get("summary", {})
        lines.append(f"- Configured providers: {summary.get('configured_providers', 0)}")
        lines.append(f"- Attempted providers: {summary.get('attempted_providers', 0)}")
        lines.append(f"- Passed providers: {summary.get('passed_providers', 0)}")
        lines.append(f"- Failed providers: {summary.get('failed_providers', 0)}")
        if summary.get("attempted_providers", 0):
            lines.append(f"- Pass rate: {summary.get('pass_rate', 0.0):.2%}")
    else:
        lines.append("- No live provider canary report available.")

    providers = _provider_rows(ledger["provider_compatibility"])
    lines.extend(
        [
            "",
            "## Providers",
            "",
        ]
    )
    if providers:
        for provider in providers:
            lines.append(
                f"- {provider['provider']} / {provider['family']} / {provider['model']}: {provider['status']} "
                f"(replacement: {provider['replacement']}, sunset: {provider['sunset']})"
            )
    else:
        lines.append("- No provider registry available.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the NEXUS CI evidence ledger.")
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--junit-xml", type=Path, default=None)
    parser.add_argument("--coverage-xml", type=Path, default=None)
    parser.add_argument("--provider-registry", type=Path, default=None)
    parser.add_argument("--shadow-redteam-json", type=Path, default=None)
    parser.add_argument("--swarm-eval-root", type=Path, default=None)
    parser.add_argument("--provider-canaries-json", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--job-result", action="append", default=[])
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args()

    ledger = _build_ledger(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)

    args.output_json.write_text(json.dumps(ledger, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    _write_markdown(args.output_markdown, ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
