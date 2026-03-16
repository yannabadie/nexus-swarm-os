"""
NEXUS RAG Backend Live Benchmark
=================================
Real indexing + real retrieval across all available backends.
NO MOCKS. Tests against the NEXUS codebase itself.

Backends tested:
  - tfidf   (always available, stdlib-only)
  - bm25    (requires bm25s, PyStemmer)
  - hybrid  (requires lancedb + sentence-transformers + bm25s)
  - dense   (requires lancedb + sentence-transformers)

Usage:
    python benchmarks/test_rag_backends_live.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("NEXUS_ROOT", str(PROJECT_ROOT))

from core.memory_pkg.memory.project_memory import ProjectMemory
from core.memory_pkg.memory.backends import (
    BM25S_AVAILABLE,
    STEMMER_AVAILABLE,
    LANCEDB_AVAILABLE,
    SENTENCE_TRANSFORMERS_AVAILABLE,
    Bm25Backend,
    DenseBackend,
    HybridBackend,
    TfidfBackend,
)

logging.basicConfig(level=logging.WARNING)

# ── Files to index (relative to NEXUS root) ──────────────────────────
FILES_TO_INDEX = [
    Path("core/drivers/async_factory.py"),
    Path("core/orchestration_v7.py"),
    Path("core/config.py"),
]

# ── Queries ───────────────────────────────────────────────────────────
QUERIES = [
    "How does the driver factory create SDK drivers?",
    "What are the FSM states in the orchestrator?",
    "How are feature flags configured?",
]

# ── Backends to test (name -> env value) ──────────────────────────────
BACKEND_SPECS = [
    ("tfidf", "tfidf"),
    ("bm25", "bm25"),
    ("dense", "dense"),
    ("hybrid", "hybrid"),
]


def _backend_available(name: str) -> bool:
    """Return True if the backend can actually be instantiated."""
    if name == "tfidf":
        return True
    if name == "bm25":
        return BM25S_AVAILABLE
    if name == "dense":
        return LANCEDB_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE
    if name == "hybrid":
        return HybridBackend.is_available()
    return False


def _init_memory(root: Path, backend_env: str, storage_dir: Path) -> ProjectMemory:
    """Create a ProjectMemory with the given backend forced via env."""
    prev = os.environ.get("PROJECT_MEMORY_BACKEND")
    os.environ["PROJECT_MEMORY_BACKEND"] = backend_env
    try:
        mem = ProjectMemory(root, storage_dir=storage_dir, persist=False)
    finally:
        if prev is None:
            os.environ.pop("PROJECT_MEMORY_BACKEND", None)
        else:
            os.environ["PROJECT_MEMORY_BACKEND"] = prev
    return mem


def run_benchmark() -> dict:
    root = PROJECT_ROOT
    results: dict = {
        "project_root": str(root),
        "files_indexed": [str(f) for f in FILES_TO_INDEX],
        "queries": QUERIES,
        "backend_availability": {},
        "backends": {},
        "comparison": {},
    }

    # Report availability
    for name, _ in BACKEND_SPECS:
        available = _backend_available(name)
        results["backend_availability"][name] = available
        tag = "OK" if available else "MISSING deps"
        print(f"  [{name:>7}] available = {available}  ({tag})")

    print()

    for backend_name, backend_env in BACKEND_SPECS:
        if not _backend_available(backend_name):
            results["backends"][backend_name] = {"skipped": True, "reason": "dependencies not installed"}
            print(f"--- SKIP {backend_name} (deps missing) ---\n")
            continue

        print(f"=== Backend: {backend_name} ===")

        with tempfile.TemporaryDirectory(prefix=f"nexus_rag_{backend_name}_") as tmp:
            mem = _init_memory(root, backend_env, Path(tmp))
            info = mem.get_backend_info()
            print(f"  Active backend: {info.get('backend', '?')}")

            # Index files
            t0 = time.perf_counter()
            total_chunks = 0
            for fpath in FILES_TO_INDEX:
                n = mem.index_file(fpath, force=True)
                total_chunks += n
                print(f"  Indexed {fpath}: {n} chunks")

            # Force backend index rebuild
            mem._rebuild_backend_index()
            index_ms = (time.perf_counter() - t0) * 1000
            print(f"  Total chunks: {total_chunks}  |  Index time: {index_ms:.0f}ms")

            backend_results = {
                "backend_info": info,
                "total_chunks_indexed": total_chunks,
                "index_time_ms": round(index_ms, 1),
                "queries": {},
            }

            for query in QUERIES:
                t1 = time.perf_counter()
                chunks = mem.retrieve(query, limit=5, min_score=0.01, apply_datamarking=False)
                latency_ms = (time.perf_counter() - t1) * 1000

                if chunks:
                    top = chunks[0]
                    # Try to get a score from backend (tfidf/bm25 don't expose per-chunk scores directly)
                    # So we re-run a lightweight scoring for the top result
                    top_file = top.file_path
                    top_name = top.name or "(unnamed)"
                    top_type = top.chunk_type
                    top_lines = f"L{top.start_line}-{top.end_line}"
                else:
                    top_file = None
                    top_name = None
                    top_type = None
                    top_lines = None

                query_result = {
                    "results_count": len(chunks),
                    "top_result_file": top_file,
                    "top_result_name": top_name,
                    "top_result_type": top_type,
                    "top_result_lines": top_lines,
                    "latency_ms": round(latency_ms, 1),
                    "all_results": [
                        {
                            "file": c.file_path,
                            "name": c.name,
                            "type": c.chunk_type,
                            "lines": f"L{c.start_line}-{c.end_line}",
                        }
                        for c in chunks
                    ],
                }
                backend_results["queries"][query] = query_result

                status = "OK" if len(chunks) > 0 else "EMPTY"
                print(f"  [{status}] Query: {query[:60]}...")
                print(f"       Results: {len(chunks)}  |  Latency: {latency_ms:.1f}ms")
                if top_file:
                    print(f"       Top:     {top_file} -> {top_name} ({top_type}, {top_lines})")

            results["backends"][backend_name] = backend_results
            print()

    # ── Comparison ──────────────────────────────────────────────────────
    print("=== Comparison ===")
    active_backends = [name for name, _ in BACKEND_SPECS if name in results["backends"] and not results["backends"][name].get("skipped")]

    for query in QUERIES:
        print(f"\n  Query: {query[:70]}")
        query_comparison = {}
        for bname in active_backends:
            qr = results["backends"][bname]["queries"].get(query, {})
            count = qr.get("results_count", 0)
            top = qr.get("top_result_file", "N/A")
            lat = qr.get("latency_ms", 0)
            query_comparison[bname] = {"count": count, "top_file": top, "latency_ms": lat}
            print(f"    {bname:>7}: {count} results, top={top}, {lat:.1f}ms")

        results["comparison"][query] = query_comparison

    # Do backends return different results?
    print("\n=== Do backends differ? ===")
    differ_report = {}
    for query in QUERIES:
        top_files = {}
        for bname in active_backends:
            qr = results["backends"][bname]["queries"].get(query, {})
            top_files[bname] = qr.get("top_result_file")
        unique_tops = set(v for v in top_files.values() if v)
        same = len(unique_tops) <= 1
        differ_report[query[:50]] = {
            "top_files_by_backend": top_files,
            "all_same_top": same,
            "unique_top_count": len(unique_tops),
        }
        tag = "SAME" if same else "DIFFER"
        print(f"  [{tag}] {query[:60]} -> {top_files}")

    results["comparison"]["backend_differences"] = differ_report

    # Best backend heuristic (most results, lowest latency)
    if active_backends:
        total_results = {}
        total_latency = {}
        for bname in active_backends:
            total_results[bname] = sum(
                results["backends"][bname]["queries"][q].get("results_count", 0)
                for q in QUERIES
            )
            total_latency[bname] = sum(
                results["backends"][bname]["queries"][q].get("latency_ms", 0)
                for q in QUERIES
            )

        best_by_results = max(active_backends, key=lambda b: total_results[b])
        best_by_latency = min(active_backends, key=lambda b: total_latency[b])
        results["comparison"]["best_by_total_results"] = best_by_results
        results["comparison"]["best_by_latency"] = best_by_latency
        results["comparison"]["totals"] = {
            b: {"total_results": total_results[b], "total_latency_ms": round(total_latency[b], 1)}
            for b in active_backends
        }
        print(f"\n  Best by total results: {best_by_results} ({total_results[best_by_results]} total)")
        print(f"  Best by latency:      {best_by_latency} ({total_latency[best_by_latency]:.1f}ms total)")

    return results


def main() -> int:
    print("=" * 70)
    print("NEXUS RAG Backend Live Benchmark")
    print("=" * 70)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Files to index: {len(FILES_TO_INDEX)}")
    print(f"Queries: {len(QUERIES)}")
    print()

    results = run_benchmark()

    # Count pass/fail
    tested = 0
    passed = 0
    failed_backends = []
    for bname in [n for n, _ in BACKEND_SPECS]:
        bd = results["backends"].get(bname, {})
        if bd.get("skipped"):
            continue
        tested += 1
        all_ok = all(
            bd["queries"][q]["results_count"] > 0 for q in QUERIES
        )
        if all_ok:
            passed += 1
        else:
            failed_backends.append(bname)

    results["summary"] = {
        "backends_tested": tested,
        "backends_passed": passed,
        "backends_failed": len(failed_backends),
        "failed_backends": failed_backends,
        "verdict": "PASS" if passed == tested and tested > 0 else "PARTIAL" if passed > 0 else "FAIL",
    }

    print(f"\n{'=' * 70}")
    print(f"VERDICT: {results['summary']['verdict']}  ({passed}/{tested} backends fully passed)")
    if failed_backends:
        print(f"  Failed: {', '.join(failed_backends)}")
    print(f"{'=' * 70}")

    # Save results
    output_path = PROJECT_ROOT / "benchmarks" / "rag_backend_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to: {output_path}")
    return 0 if results["summary"]["verdict"] in ("PASS", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
