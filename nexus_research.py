"""
NEXUS Research CLI - local evidence-pack generation with grounded synthesis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.config import Config
from core.memory_pkg.memory.project_memory import ProjectMemory

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "what",
    "how",
    "why",
    "when",
    "where",
    "which",
    "does",
    "doesn",
    "mode",
    "local",
    "mock",
    "using",
    "used",
}

CONTRADICTION_RULES = (
    (
        "workspace/.nexus",
        "nexus_root/.nexus",
        "Retrieved evidence disagrees on whether storage lives under workspace or NEXUS_ROOT.",
    ),
    (
        "default runtime authority",
        "historical review",
        "Retrieved evidence disagrees on whether a governance surface is active runtime authority or historical-only.",
    ),
)


class ResearchCancelledError(RuntimeError):
    """Raised when an evidence-pack run is cancelled cooperatively."""


def _check_cancel(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    phase: str,
    completed: int,
    total: int,
    message: str,
    detail: dict[str, Any] | None = None,
) -> None:
    if progress_callback is None:
        return

    safe_total = max(total, 1)
    payload = {
        "phase": phase,
        "completed": completed,
        "total": safe_total,
        "percentage": int((completed / safe_total) * 100),
        "message": message,
        "detail": detail or {},
        "ts": _iso_now(),
    }
    progress_callback(payload)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _resolve_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Index path must be under NEXUS root: {candidate}")
    return candidate


def _default_index_paths(root: Path) -> List[Path]:
    candidates = []
    for name in ("core", "docs"):
        candidate = root / name
        if candidate.exists():
            candidates.append(candidate)
    return candidates or [root]


def _init_memory(root: Path, backend: str, storage_dir: Path | None = None, persist: bool = True) -> ProjectMemory:
    previous_backend = os.environ.get("PROJECT_MEMORY_BACKEND")
    os.environ["PROJECT_MEMORY_BACKEND"] = backend
    try:
        return ProjectMemory(root, storage_dir=storage_dir, persist=persist)
    finally:
        if previous_backend is None:
            os.environ.pop("PROJECT_MEMORY_BACKEND", None)
        else:
            os.environ["PROJECT_MEMORY_BACKEND"] = previous_backend


def _clip(text: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _extract_query_terms(question: str) -> set[str]:
    terms = set()
    for term in re.findall(r"[a-zA-Z_][a-zA-Z0-9_./-]*", question.lower()):
        if len(term) > 2 and term not in STOP_WORDS:
            terms.add(term)
    return terms


def _confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _extract_best_snippet(source: Dict[str, Any]) -> str:
    excerpt = str(source.get("excerpt", ""))
    chunk_type = str(source.get("chunk_type", ""))
    name = str(source.get("name") or "").strip()

    lines = [
        line.strip()
        for line in excerpt.splitlines()
        if line.strip() and line.strip() not in {'"""', "'''"}
    ]
    if not lines:
        if name:
            return f"Relevant {chunk_type} `{name}` was retrieved."
        return "Relevant evidence was retrieved."

    if chunk_type == "section":
        for line in lines:
            candidate = line.lstrip("#").strip("` ").strip()
            if candidate:
                return _clip(candidate)

    for line in lines:
        if line.startswith(('"""', "'''")):
            candidate = line.strip('"\' ')
            if candidate:
                return _clip(candidate)

    for line in lines:
        if line.startswith("#"):
            candidate = line.lstrip("#").strip()
            if candidate:
                return _clip(candidate)

    for line in lines:
        if line.startswith("class "):
            return _clip(f"Defines {line}.")
        if line.startswith("def ") or line.startswith("async def "):
            return _clip(f"Defines {line}.")

    for line in lines:
        candidate = line.strip("` ").strip()
        if candidate:
            return _clip(candidate)

    if name:
        return f"Relevant {chunk_type} `{name}` was retrieved."
    return "Relevant evidence was retrieved."


def _dedupe_strings(values: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _normalize_query_fragment(text: str) -> str:
    fragment = re.sub(r"\s+", " ", text).strip(" ?.,:;")
    return _clip(fragment, max_chars=120) if fragment else ""


def _build_subqueries(question: str) -> List[str]:
    normalized = _normalize_query_fragment(question)
    subqueries = [normalized] if normalized else []
    fragments = re.split(r"\b(?:and|whether|versus|vs\.?|plus|while)\b", question, flags=re.IGNORECASE)
    subqueries.extend(_normalize_query_fragment(fragment) for fragment in fragments)

    query_terms = sorted(_extract_query_terms(question))
    if query_terms:
        focus_terms = " ".join(query_terms[: min(len(query_terms), 6)])
        subqueries.append(focus_terms)
        subqueries.append(f"implementation {focus_terms}")
        subqueries.append(f"documentation {focus_terms}")

    return _dedupe_strings([query for query in subqueries if query])


def _structure_bonus(chunk_type: Any) -> float:
    return 0.15 if str(chunk_type) in {"function", "class", "section"} else 0.0


def _format_claim_statement(source: Dict[str, Any]) -> str:
    snippet = _extract_best_snippet(source)
    target = f"`{source['name']}`" if source.get("name") else f"`{source['file_path']}`"

    if str(source.get("chunk_type")) == "section":
        return f"Documentation in {target} indicates: {snippet}"
    if source.get("name"):
        return f"Implementation evidence around {target} indicates: {snippet}"
    return f"Evidence from `{source['file_path']}` indicates: {snippet}"


def _build_source_payload(
    chunk: Any,
    question_terms: set[str],
    matched_queries: List[str],
    best_rank: int,
    retrieval_score: float,
    query_hit_count: int,
    total_queries: int,
) -> Dict[str, Any]:
    terms = sorted(chunk.terms)
    source_terms = set(str(term).lower() for term in terms)
    overlap = len(question_terms & source_terms)
    overlap_score = overlap / max(len(question_terms), 1) if question_terms else 0.5
    query_coverage = query_hit_count / max(total_queries, 1)
    rank_signal = min(retrieval_score / max(query_hit_count, 1), 1.0)
    verification_score = min(
        round(
            (0.45 * overlap_score)
            + (0.30 * query_coverage)
            + (0.25 * rank_signal)
            + _structure_bonus(chunk.chunk_type),
            2,
        ),
        1.0,
    )

    return {
        "file_path": chunk.file_path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "chunk_type": chunk.chunk_type,
        "name": chunk.name,
        "terms": terms,
        "excerpt": chunk.content.strip()[:400],
        "query_matches": matched_queries,
        "query_hit_count": query_hit_count,
        "query_coverage": round(query_coverage, 2),
        "best_rank": best_rank,
        "retrieval_score": round(retrieval_score, 2),
        "verification_score": verification_score,
        "verification_label": _confidence_label(verification_score),
    }


def _select_diverse_sources(candidates: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []

    selected: List[Dict[str, Any]] = []
    selected_keys: set[tuple[str, int, int]] = set()
    seen_files: set[str] = set()
    diversity_target = max(1, min(limit, 3))

    for source in candidates:
        key = (str(source["file_path"]), int(source["start_line"]), int(source["end_line"]))
        if key in selected_keys:
            continue
        if len(seen_files) < diversity_target and str(source["file_path"]) in seen_files:
            continue
        selected.append(source)
        selected_keys.add(key)
        seen_files.add(str(source["file_path"]))
        if len(selected) >= limit:
            return selected

    for source in candidates:
        key = (str(source["file_path"]), int(source["start_line"]), int(source["end_line"]))
        if key in selected_keys:
            continue
        selected.append(source)
        selected_keys.add(key)
        if len(selected) >= limit:
            break

    return selected


def _collect_sources(
    memory: ProjectMemory,
    question: str,
    limit: int,
    min_score: float,
    cancel_check: Callable[[], None] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    subqueries = _build_subqueries(question)
    question_terms = _extract_query_terms(question)
    per_query_limit = max(limit, 3)
    raw_hit_count = 0
    aggregated: Dict[tuple[str, int, int], Dict[str, Any]] = {}

    for idx, query in enumerate(subqueries, start=1):
        _check_cancel(cancel_check)
        query_results = memory.retrieve(query, limit=per_query_limit, min_score=min_score, apply_datamarking=False)
        raw_hit_count += len(query_results)
        _emit_progress(
            progress_callback,
            phase="retrieve",
            completed=idx,
            total=len(subqueries),
            message=f"Retrieved evidence for subquery {idx}/{len(subqueries)}",
            detail={"query": query, "results": len(query_results)},
        )
        for rank, chunk in enumerate(query_results, start=1):
            key = (chunk.file_path, chunk.start_line, chunk.end_line)
            entry = aggregated.setdefault(
                key,
                {
                    "chunk": chunk,
                    "queries": [],
                    "best_rank": rank,
                    "retrieval_score": 0.0,
                    "query_hit_count": 0,
                },
            )
            if query not in entry["queries"]:
                entry["queries"].append(query)
                entry["query_hit_count"] += 1
            entry["best_rank"] = min(entry["best_rank"], rank)
            entry["retrieval_score"] += 1.0 / rank

    candidates: List[Dict[str, Any]] = []
    for entry in aggregated.values():
        candidates.append(
            _build_source_payload(
                chunk=entry["chunk"],
                question_terms=question_terms,
                matched_queries=entry["queries"],
                best_rank=entry["best_rank"],
                retrieval_score=entry["retrieval_score"],
                query_hit_count=entry["query_hit_count"],
                total_queries=len(subqueries),
            )
        )

    candidates.sort(
        key=lambda source: (
            source["verification_score"],
            source["query_hit_count"],
            source["retrieval_score"],
            -source["best_rank"],
        ),
        reverse=True,
    )

    sources = _select_diverse_sources(candidates, limit)
    for idx, source in enumerate(sources, start=1):
        source["source_id"] = f"S{idx}"

    return {
        "sources": sources,
        "subqueries": subqueries,
        "raw_hit_count": raw_hit_count,
    }


def _build_contradictions(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    contradictions: List[Dict[str, Any]] = []
    lowered = [
        {
            "source_id": source["source_id"],
            "file_path": source["file_path"],
            "excerpt": str(source.get("excerpt", "")).lower(),
        }
        for source in sources
    ]

    for left, right, description in CONTRADICTION_RULES:
        left_hits = [source for source in lowered if left in source["excerpt"]]
        right_hits = [source for source in lowered if right in source["excerpt"]]
        if left_hits and right_hits:
            contradiction_id = f"C{len(contradictions) + 1}"
            contradiction_sources = sorted({hit["source_id"] for hit in left_hits + right_hits})
            contradictions.append(
                {
                    "contradiction_id": contradiction_id,
                    "description": description,
                    "left_source_ids": sorted(hit["source_id"] for hit in left_hits),
                    "right_source_ids": sorted(hit["source_id"] for hit in right_hits),
                    "source_ids": contradiction_sources,
                }
            )

    return contradictions


def _claim_anchor(question_terms: set[str], source: Dict[str, Any]) -> str:
    overlap_terms = [term for term in source.get("terms", []) if str(term).lower() in question_terms]
    if overlap_terms:
        return "|".join(sorted(str(term).lower() for term in overlap_terms[:3]))
    if source.get("name"):
        return f"name:{str(source['name']).lower()}"
    return f"path:{Path(str(source['file_path'])).stem.lower()}"


def _build_claims(
    question: str,
    sources: List[Dict[str, Any]],
    subqueries: List[str],
    contradictions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    question_terms = _extract_query_terms(question)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in sources:
        grouped[_claim_anchor(question_terms, source)].append(source)

    claims: List[Dict[str, Any]] = []
    for anchor, group in grouped.items():
        ordered_group = sorted(
            group,
            key=lambda source: (
                source["verification_score"],
                source["query_hit_count"],
                source["retrieval_score"],
            ),
            reverse=True,
        )
        lead = ordered_group[0]
        group_ids = {str(source["source_id"]) for source in ordered_group}
        supporting_ids = set(group_ids)
        opposing_ids: set[str] = set()

        for contradiction in contradictions:
            left_ids = set(contradiction.get("left_source_ids", []))
            right_ids = set(contradiction.get("right_source_ids", []))
            if lead["source_id"] in left_ids:
                opposing_ids.update(right_ids)
                supporting_ids.difference_update(right_ids & group_ids)
            elif lead["source_id"] in right_ids:
                opposing_ids.update(left_ids)
                supporting_ids.difference_update(left_ids & group_ids)
            elif group_ids & left_ids and group_ids & right_ids:
                left_matches = [source for source in ordered_group if source["source_id"] in left_ids]
                right_matches = [source for source in ordered_group if source["source_id"] in right_ids]
                left_score = sum(float(source["verification_score"]) for source in left_matches)
                right_score = sum(float(source["verification_score"]) for source in right_matches)
                if left_score >= right_score:
                    opposing_ids.update(right_ids)
                    supporting_ids.difference_update(right_ids & group_ids)
                else:
                    opposing_ids.update(left_ids)
                    supporting_ids.difference_update(left_ids & group_ids)

        if not supporting_ids:
            supporting_ids = {str(lead["source_id"])}
        opposing_ids.difference_update(supporting_ids)
        supporting_sources = [source for source in ordered_group if source["source_id"] in supporting_ids]
        claim_queries = _dedupe_strings(
            [query for source in supporting_sources for query in source.get("query_matches", [])]
        )
        support_score = sum(float(source["verification_score"]) for source in supporting_sources) / len(supporting_sources)
        query_coverage = len(claim_queries) / max(len(subqueries), 1)
        diversity_score = min(len({str(source["file_path"]) for source in supporting_sources}) / 2.0, 1.0)
        support_bonus = min((len(supporting_sources) - 1) * 0.1, 0.2)
        conflict_penalty = min(len(opposing_ids) * 0.15, 0.35)
        claim_score = max(
            min(
                round(
                    (0.50 * support_score)
                    + (0.25 * query_coverage)
                    + (0.15 * diversity_score)
                    + support_bonus
                    - conflict_penalty,
                    2,
                ),
                1.0,
            ),
            0.0,
        )
        status = "mixed" if opposing_ids else "supported" if claim_score >= 0.55 else "weak"
        claims.append(
            {
                "claim_id": f"CL{len(claims) + 1}",
                "anchor": anchor,
                "statement": _format_claim_statement(lead),
                "supporting_source_ids": [source["source_id"] for source in supporting_sources],
                "opposing_source_ids": sorted(opposing_ids),
                "query_matches": claim_queries,
                "status": status,
                "confidence": {"label": _confidence_label(claim_score), "score": claim_score},
            }
        )

    status_rank = {"supported": 0, "mixed": 1, "weak": 2}
    claims.sort(key=lambda claim: (status_rank[claim["status"]], -claim["confidence"]["score"], claim["claim_id"]))
    for idx, claim in enumerate(claims, start=1):
        claim["claim_id"] = f"CL{idx}"
    return claims


def _build_findings(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for idx, claim in enumerate(claims, start=1):
        statement = claim["statement"]
        if claim["status"] == "mixed":
            statement = f"{statement} Conflicting evidence remains unresolved."
        elif claim["status"] == "weak":
            statement = f"{statement} Evidence is still narrow or weak."
        findings.append(
            {
                "finding_id": f"F{idx}",
                "statement": statement,
                "source_ids": claim["supporting_source_ids"] + claim["opposing_source_ids"],
                "confidence": claim["confidence"],
                "status": claim["status"],
            }
        )
    return findings


def _build_answer_bullets(claims: List[Dict[str, Any]]) -> List[str]:
    strong_claims = [claim for claim in claims if claim["status"] in {"supported", "mixed"}]
    if not strong_claims:
        if not claims:
            return ["No grounded answer could be synthesized from the retrieved sources."]
        lead = claims[0]
        return [
            "Evidence is too weak or fragmented to produce a confident answer.",
            f"Weak signal: {lead['statement']} [{', '.join(lead['supporting_source_ids'])}]",
        ]

    bullets: List[str] = []
    for claim in strong_claims[:3]:
        if claim["opposing_source_ids"]:
            bullets.append(
                f"Mixed: {claim['statement']} Support [{', '.join(claim['supporting_source_ids'])}] "
                f"Opposition [{', '.join(claim['opposing_source_ids'])}]"
            )
        else:
            bullets.append(f"Supported: {claim['statement']} [{', '.join(claim['supporting_source_ids'])}]")
    return bullets


def _build_synthesis(question: str, sources: List[Dict[str, Any]], subqueries: List[str]) -> Dict[str, Any]:
    contradictions = _build_contradictions(sources)
    claims = _build_claims(question, sources, subqueries, contradictions)
    findings = _build_findings(claims)
    unique_files = len({source["file_path"] for source in sources})
    average_confidence = (
        round(sum(claim["confidence"]["score"] for claim in claims) / len(claims), 2) if claims else 0.0
    )
    supported_claims = [claim for claim in claims if claim["status"] == "supported"]
    mixed_claims = [claim for claim in claims if claim["status"] == "mixed"]
    weak_claims = [claim for claim in claims if claim["status"] == "weak"]
    coverage_score = min(len(sources) / max(len(subqueries), 1), 1.0)
    diversity_score = min(unique_files / 3.0, 1.0)
    support_ratio = len(supported_claims) / max(len(claims), 1)
    contradiction_penalty = (0.10 * len(contradictions)) + (0.08 * len(mixed_claims))
    score = max(
        round(
            (0.45 * average_confidence)
            + (0.25 * coverage_score)
            + (0.15 * diversity_score)
            + (0.15 * support_ratio)
            - contradiction_penalty,
            2,
        ),
        0.0,
    )
    confidence = {"label": _confidence_label(score), "score": score}

    return {
        "question": question,
        "answer_bullets": _build_answer_bullets(claims),
        "claims": claims,
        "findings": findings,
        "contradictions": contradictions,
        "overall_confidence": confidence,
        "verification_summary": {
            "claim_count": len(claims),
            "supported_claim_count": len(supported_claims),
            "mixed_claim_count": len(mixed_claims),
            "weak_claim_count": len(weak_claims),
            "subquery_count": len(subqueries),
        },
    }


def _write_report(
    path: Path,
    question: str,
    mode: str,
    backend: str,
    generated_at: str,
    subqueries: List[str],
    synthesis: Dict[str, Any],
    sources: List[Dict[str, Any]],
) -> None:
    confidence = synthesis["overall_confidence"]
    lines = [
        "# Research Report",
        "",
        f"Question: {question}",
        f"Mode: {mode}",
        f"Backend: {backend}",
        f"Generated: {generated_at}",
        f"Confidence: {confidence['label']} ({confidence['score']:.2f})",
        f"Subqueries: {len(subqueries)}",
        "",
        "## Research Plan",
    ]

    for query in subqueries:
        lines.append(f"- {query}")

    lines.extend(["", "## Answer"])
    for bullet in synthesis["answer_bullets"]:
        lines.append(f"- {bullet}")

    lines.extend(["", "## Verified Claims"])
    if synthesis["claims"]:
        for claim in synthesis["claims"]:
            conf = claim["confidence"]
            support = ", ".join(claim["supporting_source_ids"])
            if claim["opposing_source_ids"]:
                lines.append(
                    f"- [{claim['claim_id']}] ({claim['status']} / {conf['label']} {conf['score']:.2f}) "
                    f"{claim['statement']} Support [{support}] Opposition [{', '.join(claim['opposing_source_ids'])}]"
                )
            else:
                lines.append(
                    f"- [{claim['claim_id']}] ({claim['status']} / {conf['label']} {conf['score']:.2f}) "
                    f"{claim['statement']} [{support}]"
                )
    else:
        lines.append("- No verified claims could be produced from the retrieved evidence.")

    lines.extend(["", "## Findings"])
    if synthesis["findings"]:
        for finding in synthesis["findings"]:
            conf = finding["confidence"]
            lines.append(
                f"- [{finding['finding_id']}] ({finding.get('status', 'unknown')} / {conf['label']} {conf['score']:.2f}) "
                f"{finding['statement']} [{', '.join(finding['source_ids'])}]"
            )
    else:
        lines.append("- No findings were synthesized from the retrieved evidence.")

    lines.extend(["", "## Contradictions"])
    if synthesis["contradictions"]:
        for contradiction in synthesis["contradictions"]:
            lines.append(
                f"- [{contradiction['contradiction_id']}] {contradiction['description']} "
                f"[{', '.join(contradiction['source_ids'])}]"
            )
    else:
        lines.append("- No heuristic contradictions detected among the retrieved sources.")

    lines.extend(["", "## Sources"])
    if sources:
        for source in sources:
            lines.append(
                f"- [{source['source_id']}] {source['file_path']} "
                f"(L{source['start_line']}-{source['end_line']}) "
                f"score={source['verification_score']:.2f} queries={source['query_hit_count']}"
            )
    else:
        lines.append("- No sources matched the query at the current threshold.")

    lines.extend(
        [
            "",
            "## Notes",
            "- This report was generated in mock/local mode using on-disk project data.",
            "- No external network calls or API keys were required.",
            "- Retrieval uses decomposed subqueries, evidence aggregation, and deterministic claim verification heuristics.",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sources(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _write_metrics(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _write_trace(path: Path, events: List[Dict[str, object]]) -> None:
    lines = [json.dumps(event, ensure_ascii=True) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape_mermaid(text: str) -> str:
    return _clip(str(text).replace('"', "'"), max_chars=110)


def _write_reasoning_graph(
    path: Path,
    question: str,
    synthesis: Dict[str, Any],
    sources: List[Dict[str, Any]],
) -> None:
    lines = ["graph TD", f'  Q["{_escape_mermaid(question)}"]']
    source_lookup = {source["source_id"]: source for source in sources}

    for claim in synthesis["claims"]:
        claim_id = claim["claim_id"]
        lines.append(f'  Q --> {claim_id}["{_escape_mermaid(claim["statement"])}"]')
        for source_id in claim["supporting_source_ids"]:
            source = source_lookup.get(source_id)
            if not source:
                continue
            lines.append(f'  {claim_id} --> {source_id}["{_escape_mermaid(source["file_path"])}"]')
        for source_id in claim["opposing_source_ids"]:
            source = source_lookup.get(source_id)
            if not source:
                continue
            lines.append(f'  {claim_id} -.-> {source_id}["{_escape_mermaid(source["file_path"])}"]')

    for contradiction in synthesis["contradictions"]:
        contradiction_id = contradiction["contradiction_id"]
        lines.append(f'  Q --> {contradiction_id}["{_escape_mermaid(contradiction["description"])}"]')
        for source_id in contradiction["source_ids"]:
            source = source_lookup.get(source_id)
            if not source:
                continue
            lines.append(f'  {contradiction_id} --> {source_id}["{_escape_mermaid(source["file_path"])}"]')

    if not synthesis["claims"] and not synthesis["contradictions"]:
        lines.append('  Q --> R["No grounded findings"]')

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(path: Path, files: List[Path]) -> None:
    lines = []
    for file_path in files:
        digest = _hash_file(file_path)
        lines.append(f"{digest}  {file_path.name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_research_payload(
    question: str,
    root_path: Optional[Path] = None,
    mode: str = "mock",
    backend: Optional[str] = None,
    limit: int = 5,
    min_score: float = 0.2,
    paths: Optional[List[str]] = None,
    cancel_check: Callable[[], None] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    config = Config()
    root = Path(root_path) if root_path else config.nexus_root
    root = root.resolve()

    mode = mode.lower()
    if mode not in {"mock", "local"}:
        raise ValueError(f"Unsupported mode: {mode}. Use 'mock' or 'local'.")

    backend = backend or ("tfidf" if mode == "mock" else "auto")
    index_paths = [_resolve_path(root, p) for p in paths] if paths else _default_index_paths(root)

    with tempfile.TemporaryDirectory(prefix="nexus_research_memory_") as temp_dir:
        _check_cancel(cancel_check)
        memory = _init_memory(
            root,
            backend,
            storage_dir=Path(temp_dir),
            persist=False,
        )

        indexed_chunks = 0
        _emit_progress(
            progress_callback,
            phase="index",
            completed=0,
            total=len(index_paths),
            message="Preparing invocation-scoped index",
            detail={"paths": [str(path) for path in index_paths]},
        )
        for idx, path in enumerate(index_paths, start=1):
            _check_cancel(cancel_check)
            if path.is_dir():
                indexed_chunks += memory.index_directory(path)
            elif path.is_file():
                indexed_chunks += memory.index_file(path)
            _emit_progress(
                progress_callback,
                phase="index",
                completed=idx,
                total=len(index_paths),
                message=f"Indexed path {idx}/{len(index_paths)}",
                detail={"path": str(path), "indexed_chunks": indexed_chunks},
            )

        retrieval_summary = _collect_sources(
            memory,
            question,
            limit=limit,
            min_score=min_score,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        sources = retrieval_summary["sources"]
        subqueries = retrieval_summary["subqueries"]
        backend_info = memory.get_backend_info()

    backend_name = backend_info.get("backend", backend)
    generated_at = _iso_now()
    _check_cancel(cancel_check)
    synthesis = _build_synthesis(question, sources, subqueries)
    _emit_progress(
        progress_callback,
        phase="synthesize",
        completed=1,
        total=1,
        message="Synthesized verified claims from retrieved evidence",
        detail={
            "claims": len(synthesis["claims"]),
            "contradictions": len(synthesis["contradictions"]),
        },
    )

    return {
        "question": question,
        "mode": mode,
        "backend": backend_name,
        "generated_at": generated_at,
        "root_path": str(root),
        "index_paths": [str(p) for p in index_paths],
        "indexed_chunks": indexed_chunks,
        "subqueries": subqueries,
        "retrieval_summary": {
            "raw_hit_count": retrieval_summary["raw_hit_count"],
            "selected_source_count": len(sources),
        },
        "sources": sources,
        "synthesis": synthesis,
    }


def run_research(
    question: str,
    root_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    mode: str = "mock",
    backend: Optional[str] = None,
    limit: int = 5,
    min_score: float = 0.2,
    paths: Optional[List[str]] = None,
    cancel_check: Callable[[], None] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Dict[str, Path]:
    start_time = time.perf_counter()
    config = Config()

    output_dir = Path(output_dir) if output_dir else (
        config.workspace_path / "research" / _utc_now().strftime("%Y%m%d_%H%M%S")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_research_payload(
        question=question,
        root_path=root_path,
        mode=mode,
        backend=backend,
        limit=limit,
        min_score=min_score,
        paths=paths,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    sources = payload["sources"]
    synthesis = payload["synthesis"]
    backend_name = payload["backend"]
    generated_at = payload["generated_at"]

    report_path = output_dir / "report.md"
    sources_path = output_dir / "sources.json"
    trace_path = output_dir / "trace.jsonl"
    graph_path = output_dir / "reasoning_graph.mmd"
    metrics_path = output_dir / "metrics.json"
    manifest_path = output_dir / "manifest.sha256"

    _write_report(
        report_path,
        question=question,
        mode=payload["mode"],
        backend=backend_name,
        generated_at=generated_at,
        subqueries=payload["subqueries"],
        synthesis=synthesis,
        sources=sources,
    )

    _write_sources(
        sources_path,
        payload,
    )
    _check_cancel(cancel_check)
    _emit_progress(
        progress_callback,
        phase="write_outputs",
        completed=1,
        total=2,
        message="Wrote report and source payload",
        detail={"output_dir": str(output_dir)},
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    _write_metrics(
        metrics_path,
        {
            "question": question,
            "mode": payload["mode"],
            "backend": backend_name,
            "generated_at": generated_at,
            "indexed_chunks": payload["indexed_chunks"],
            "subquery_count": len(payload["subqueries"]),
            "source_count": len(sources),
            "claim_count": len(synthesis["claims"]),
            "supported_claim_count": synthesis["verification_summary"]["supported_claim_count"],
            "mixed_claim_count": synthesis["verification_summary"]["mixed_claim_count"],
            "weak_claim_count": synthesis["verification_summary"]["weak_claim_count"],
            "finding_count": len(synthesis["findings"]),
            "contradiction_count": len(synthesis["contradictions"]),
            "unique_files": len({source["file_path"] for source in sources}),
            "confidence_score": synthesis["overall_confidence"]["score"],
            "confidence_label": synthesis["overall_confidence"]["label"],
            "duration_ms": duration_ms,
        },
    )

    trace_events = [
        {
            "ts": generated_at,
            "event": "start",
            "detail": {"mode": payload["mode"], "backend": backend_name},
        },
        {
            "ts": _iso_now(),
            "event": "index",
            "detail": {"paths": payload["index_paths"], "chunks": payload["indexed_chunks"]},
        },
        {
            "ts": _iso_now(),
            "event": "plan",
            "detail": {"subqueries": payload["subqueries"]},
        },
        {
            "ts": _iso_now(),
            "event": "retrieve",
            "detail": {
                "limit": limit,
                "min_score": min_score,
                "raw_hits": payload["retrieval_summary"]["raw_hit_count"],
                "selected_sources": len(sources),
            },
        },
        {
            "ts": _iso_now(),
            "event": "synthesize",
            "detail": {
                "claims": len(synthesis["claims"]),
                "findings": len(synthesis["findings"]),
                "contradictions": len(synthesis["contradictions"]),
                "confidence": synthesis["overall_confidence"],
            },
        },
        {
            "ts": _iso_now(),
            "event": "write_outputs",
            "detail": {"output_dir": str(output_dir)},
        },
    ]

    _write_trace(trace_path, trace_events)
    _write_reasoning_graph(graph_path, question, synthesis, sources)
    _write_manifest(manifest_path, [report_path, sources_path, trace_path, graph_path, metrics_path])
    _check_cancel(cancel_check)
    _emit_progress(
        progress_callback,
        phase="write_outputs",
        completed=2,
        total=2,
        message="Wrote evidence pack artifacts",
        detail={"output_dir": str(output_dir)},
    )

    return {
        "output_dir": output_dir,
        "report": report_path,
        "sources": sources_path,
        "trace": trace_path,
        "graph": graph_path,
        "metrics": metrics_path,
        "manifest": manifest_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a NEXUS research evidence pack (mock/local mode).")
    parser.add_argument("question", help="Research question to answer.")
    parser.add_argument("--mode", default="mock", help="Mode: mock or local.")
    parser.add_argument("--root", help="Root path to index (default: NEXUS_ROOT).")
    parser.add_argument("--output", help="Output directory for evidence pack.")
    parser.add_argument("--backend", help="Memory backend (tfidf, bm25, dense, hybrid, auto).")
    parser.add_argument("--limit", type=int, default=5, help="Max chunks to return.")
    parser.add_argument("--min-score", type=float, default=0.2, help="Minimum score threshold.")
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Optional paths to index (repeatable).",
    )

    args = parser.parse_args()

    outputs = run_research(
        question=args.question,
        root_path=Path(args.root).resolve() if args.root else None,
        output_dir=Path(args.output).resolve() if args.output else None,
        mode=args.mode,
        backend=args.backend,
        limit=args.limit,
        min_score=args.min_score,
        paths=args.paths,
    )

    print(f"Evidence pack written to: {outputs['output_dir']}")
    print(f"Report: {outputs['report']}")
    print(f"Sources: {outputs['sources']}")
    print(f"Trace: {outputs['trace']}")
    print(f"Graph: {outputs['graph']}")
    print(f"Metrics: {outputs['metrics']}")
    print(f"Manifest: {outputs['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
