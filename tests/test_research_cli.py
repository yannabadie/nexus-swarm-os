import json
import json
from pathlib import Path

import pytest

from nexus_research import run_research
from core.memory_pkg.memory.project_memory import ProjectMemory


def _write_sample_doc(root: Path) -> Path:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "# Sample Guide\n"
        "This guide explains how the memory index builds evidence packs for NEXUS.\n"
        "Use the research CLI to search local files and produce a report.\n"
        "Evidence pack outputs include report, sources, trace, and graph artifacts.\n"
    )
    file_path = docs_dir / "guide.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _write_conflicting_docs(root: Path) -> list[Path]:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_paths = [
        docs_dir / "legacy_storage.md",
        docs_dir / "runtime_storage.md",
    ]
    doc_paths[0].write_text(
        (
            "# Legacy Note\n"
            "ProjectMemory stores data under workspace/.nexus for older review flows.\n"
            "Historical review documents still mention workspace/.nexus.\n"
        ),
        encoding="utf-8",
    )
    doc_paths[1].write_text(
        (
            "# Runtime Note\n"
            "ProjectMemory stores data under NEXUS_ROOT/.nexus/project_knowledge.json.\n"
            "Default runtime authority is the code and current runtime docs.\n"
        ),
        encoding="utf-8",
    )
    return doc_paths


def test_run_research_writes_verified_evidence_pack(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    sample_file = _write_sample_doc(root)
    output_dir = tmp_path / "out"

    outputs = run_research(
        question="How does the evidence pack get generated and what artifacts does it produce?",
        root_path=root,
        output_dir=output_dir,
        mode="mock",
        backend="tfidf",
        paths=[str(sample_file)],
        limit=3,
        min_score=0.0,
    )

    assert outputs["output_dir"] == output_dir
    for key in ("report", "sources", "trace", "graph", "metrics", "manifest"):
        assert outputs[key].exists()

    report_text = outputs["report"].read_text(encoding="utf-8")
    assert "How does the evidence pack get generated" in report_text
    assert "Mode: mock" in report_text
    assert "## Research Plan" in report_text
    assert "## Answer" in report_text
    assert "## Verified Claims" in report_text
    assert "Confidence:" in report_text

    sources_payload = json.loads(outputs["sources"].read_text(encoding="utf-8"))
    assert sources_payload["question"].startswith("How does the evidence pack get generated")
    assert sources_payload["mode"] == "mock"
    assert str(sample_file) in sources_payload["index_paths"]
    assert sources_payload["indexed_chunks"] >= 1
    assert sources_payload["sources"]
    assert sources_payload["subqueries"]
    assert sources_payload["retrieval_summary"]["selected_source_count"] >= 1
    assert "synthesis" in sources_payload
    assert sources_payload["synthesis"]["claims"]
    assert sources_payload["synthesis"]["verification_summary"]["claim_count"] >= 1
    assert sources_payload["synthesis"]["overall_confidence"]["label"] in {"low", "medium", "high"}
    first_source_path = Path(sources_payload["sources"][0]["file_path"]).as_posix()
    assert first_source_path == "docs/guide.md"

    trace_lines = outputs["trace"].read_text(encoding="utf-8").splitlines()
    assert len(trace_lines) >= 5
    trace_events = [json.loads(line)["event"] for line in trace_lines]
    assert "plan" in trace_events
    assert "synthesize" in trace_events

    graph_text = outputs["graph"].read_text(encoding="utf-8").replace("\\", "/")
    assert "graph TD" in graph_text
    assert "docs/guide.md" in graph_text
    assert "CL1" in graph_text

    metrics_payload = json.loads(outputs["metrics"].read_text(encoding="utf-8"))
    assert metrics_payload["question"].startswith("How does the evidence pack get generated")
    assert metrics_payload["source_count"] >= 1
    assert metrics_payload["claim_count"] >= 1
    assert metrics_payload["subquery_count"] >= 1
    assert "confidence_score" in metrics_payload
    assert "confidence_label" in metrics_payload

    manifest_lines = outputs["manifest"].read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 5


def test_run_research_surfaces_conflicting_claims(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    doc_paths = _write_conflicting_docs(root)
    output_dir = tmp_path / "out"

    outputs = run_research(
        question="Where does ProjectMemory store data and do docs disagree?",
        root_path=root,
        output_dir=output_dir,
        mode="mock",
        backend="tfidf",
        paths=[str(path) for path in doc_paths],
        limit=4,
        min_score=0.0,
    )

    sources_payload = json.loads(outputs["sources"].read_text(encoding="utf-8"))
    contradictions = sources_payload["synthesis"]["contradictions"]
    claims = sources_payload["synthesis"]["claims"]

    assert contradictions
    assert any(claim["status"] == "mixed" for claim in claims)
    assert any(claim["opposing_source_ids"] for claim in claims)
    mixed_claim = next(claim for claim in claims if claim["status"] == "mixed")
    assert set(mixed_claim["supporting_source_ids"]).isdisjoint(mixed_claim["opposing_source_ids"])

    report_text = outputs["report"].read_text(encoding="utf-8")
    assert "## Contradictions" in report_text
    # Contradictions section should reference the conflicting docs (by filename or concept)
    assert "legacy_storage" in report_text.lower() or "runtime_storage" in report_text.lower() or "workspace" in report_text.lower() or "nexus_root" in report_text.lower()


def test_run_research_rejects_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("Outside root evidence.", encoding="utf-8")

    with pytest.raises(ValueError, match="Index path must be under NEXUS root"):
        run_research(
            question="Should reject escaped paths",
            root_path=root,
            output_dir=tmp_path / "out",
            mode="mock",
            backend="tfidf",
            paths=[str(outside_file)],
        )


def test_run_research_is_invocation_scoped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    stale_file = docs_dir / "stale.md"
    stale_file.write_text("# Stale\nlegacy token alpha stale evidence\n", encoding="utf-8")
    fresh_file = docs_dir / "fresh.md"
    fresh_file.write_text("# Fresh\ncurrent runtime note only\n", encoding="utf-8")

    memory = ProjectMemory(root)
    memory.index_file(stale_file)
    memory.save()

    outputs = run_research(
        question="legacy token alpha stale evidence",
        root_path=root,
        output_dir=tmp_path / "out",
        mode="mock",
        backend="tfidf",
        paths=[str(fresh_file)],
        limit=3,
        min_score=0.0,
    )

    sources_payload = json.loads(outputs["sources"].read_text(encoding="utf-8"))
    returned_paths = {Path(source["file_path"]).as_posix() for source in sources_payload["sources"]}
    assert "docs/stale.md" not in returned_paths


def test_run_research_rejects_empty_question(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Question cannot be empty"):
        run_research("   ", root_path=tmp_path, output_dir=tmp_path / "out")


def test_run_research_rejects_invalid_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported mode"):
        run_research(
            "What is indexed?",
            root_path=tmp_path,
            output_dir=tmp_path / "out",
            mode="cloud",
        )
