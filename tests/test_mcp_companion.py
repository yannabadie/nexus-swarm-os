import json
import time
from pathlib import Path

from core.interface_pkg.mcp import server as mcp_server


def _write_sample_doc(root: Path) -> Path:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "# Sample Guide\n"
        "This guide explains how evidence packs are generated from local files.\n"
        "Use MCP to search project memory and export structured artifacts.\n"
    )
    file_path = docs_dir / "guide.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def test_build_memory_search_returns_verified_claims(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    sample_file = _write_sample_doc(root)

    payload = mcp_server.build_memory_search(
        query="evidence packs",
        root_path=root,
        mode="mock",
        backend="tfidf",
        limit=3,
        min_score=0.0,
        paths=[str(sample_file)],
    )

    assert payload["sources"]
    first_path = Path(payload["sources"][0]["file_path"]).as_posix()
    assert first_path == "docs/guide.md"
    assert payload["indexed_chunks"] >= 1
    assert payload["subqueries"]
    assert payload["retrieval_summary"]["selected_source_count"] >= 1
    assert payload["synthesis"]["claims"]
    assert payload["synthesis"]["verification_summary"]["claim_count"] >= 1


def test_build_evidence_pack_outputs_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    sample_file = _write_sample_doc(root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output_dir = workspace / "evidence_pack"

    outputs = mcp_server.build_evidence_pack(
        question="What does the guide describe?",
        root_path=root,
        workspace_path=workspace,
        output_dir=str(output_dir),
        mode="mock",
        backend="tfidf",
        limit=3,
        min_score=0.0,
        paths=[str(sample_file)],
    )

    report_path = Path(outputs["report"])
    sources_path = Path(outputs["sources"])
    trace_path = Path(outputs["trace"])
    graph_path = Path(outputs["graph"])
    metrics_path = Path(outputs["metrics"])
    manifest_path = Path(outputs["manifest"])

    assert report_path.exists()
    assert sources_path.exists()
    assert trace_path.exists()
    assert graph_path.exists()
    assert metrics_path.exists()
    assert manifest_path.exists()

    report_text = report_path.read_text(encoding="utf-8")
    assert "What does the guide describe?" in report_text
    assert "## Verified Claims" in report_text
    assert "## Research Plan" in report_text

    sources_payload = json.loads(sources_path.read_text(encoding="utf-8"))
    assert sources_payload["synthesis"]["claims"]

    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics_payload["claim_count"] >= 1
    assert metrics_payload["subquery_count"] >= 1

    latest = mcp_server.get_latest_research_evidence(workspace_path=workspace)
    assert latest["found"] is True
    assert Path(latest["output_dir"]) == output_dir
    assert latest["summary"]["claim_count"] >= 1


def test_latest_eval_and_canary_helpers(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    artifacts = root / "artifacts"
    swarm_dir = artifacts / "swarm-eval" / "swarm_eval_20260310_090000"
    swarm_dir.mkdir(parents=True, exist_ok=True)
    swarm_report = swarm_dir / "report.json"
    swarm_report.write_text(json.dumps({"generated_at": "2026-03-10T09:00:00Z", "task_count": 4}), encoding="utf-8")

    canary_report = artifacts / "provider-canaries.json"
    canary_report.write_text(
        json.dumps({"generated_at": "2026-03-10T09:05:00Z", "summary": {"passed_providers": 2}}),
        encoding="utf-8",
    )
    ledger_report = artifacts / "evidence-ledger.json"
    ledger_report.write_text(
        json.dumps({"generated_at": "2026-03-10T09:10:00Z", "evidence_status": "complete"}),
        encoding="utf-8",
    )

    latest_swarm = mcp_server.get_latest_swarm_eval(root_path=root, workspace_path=tmp_path / "workspace")
    latest_canaries = mcp_server.get_latest_provider_canaries(root_path=root, workspace_path=tmp_path / "workspace")
    latest_ledger = mcp_server.get_latest_evidence_ledger(root_path=root, workspace_path=tmp_path / "workspace")

    assert latest_swarm["found"] is True
    assert latest_swarm["payload"]["task_count"] == 4
    assert latest_canaries["found"] is True
    assert latest_canaries["payload"]["summary"]["passed_providers"] == 2
    assert latest_ledger["found"] is True
    assert latest_ledger["payload"]["evidence_status"] == "complete"


def test_prompt_builders_expose_expected_workflows() -> None:
    research_prompt = mcp_server.build_grounded_research_prompt(
        question="How does ProjectMemory work?",
        paths=["core/memory_pkg/memory/project_memory.py"],
        mode="mock",
        backend="hybrid",
    )
    review_prompt = mcp_server.build_evidence_review_prompt()

    assert "nexus_research" in research_prompt
    assert "nexus_memory_search" in research_prompt
    assert "nexus_export_evidence_pack" in research_prompt
    assert "nexus://evidence/latest" in review_prompt
    assert "contradictions" in review_prompt.lower()


def test_evidence_job_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    sample_file = _write_sample_doc(root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    job = mcp_server.start_evidence_job(
        question="What does the guide describe?",
        root_path=root,
        workspace_path=workspace,
        mode="mock",
        backend="tfidf",
        limit=3,
        min_score=0.0,
        paths=[str(sample_file)],
    )

    assert job["status"] in {"pending", "running"}
    assert job["job_id"]

    deadline = time.time() + 10
    latest = None
    while time.time() < deadline:
        latest = mcp_server.get_job_status(job["job_id"])
        if latest["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert latest is not None
    assert latest["found"] is True
    assert latest["status"] == "completed"
    assert latest["result"]["report"]
    assert latest["progress"]["percentage"] == 100

    jobs_resource = mcp_server.list_recent_jobs()
    assert any(entry["job_id"] == job["job_id"] for entry in jobs_resource["jobs"])
