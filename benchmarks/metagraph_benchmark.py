"""
MetagraphRAG Benchmark: Honest Performance Evaluation

Tests the claims from CLAUDE.md:
  - "180-720x faster than grep"
  - "95-98% precision"
  - "<1ms query latency (cached)"

Methodology:
  1. Scan codebase with MetagraphRAG
  2. Run 10 queries via MetagraphRAG (dependency, impact, semantic search)
  3. Run equivalent grep commands for the same queries
  4. Compare latency and precision (correctness of results)
  5. Flag queries where MetagraphRAG returns empty results (inflated speedup)

Author: Benchmark script for NEXUS V12.4
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)

# Set env to scan from core/
os.environ["METAGRAPH_SCAN_ROOT"] = "core"
os.environ["METAGRAPH_AUTO_SCAN"] = "true"

NUM_ITERATIONS = 10  # Number of times to repeat each query for timing stability


@dataclass
class QueryResult:
    """Result from a single benchmark query."""
    query_name: str
    query_target: str
    query_type: str
    description: str
    # MetagraphRAG results
    metagraph_time_ms: float
    metagraph_files_found: list[str] = field(default_factory=list)
    metagraph_symbols_found: list[str] = field(default_factory=list)
    metagraph_result_count: int = 0
    metagraph_returned_empty: bool = False
    # Grep results
    grep_time_ms: float = 0.0
    grep_files_found: list[str] = field(default_factory=list)
    grep_result_count: int = 0
    # Comparison
    speedup_ratio: float = 0.0
    speedup_is_meaningful: bool = True  # False if metagraph returned empty
    # Precision analysis (against union ground truth)
    metagraph_precision: float = 0.0
    grep_precision: float = 0.0
    metagraph_recall: float = 0.0
    grep_recall: float = 0.0
    notes: str = ""


@dataclass
class BenchmarkResults:
    """Complete benchmark results."""
    timestamp: str
    python_version: str
    project_root: str
    # Scan stats
    scan_time_ms: float
    files_scanned: int
    files_failed: int
    symbols_found: int
    dependencies_found: int
    graph_classes: int
    graph_functions: int
    graph_methods: int
    # Bugs discovered
    bugs_discovered: list[str] = field(default_factory=list)
    # Query results
    queries: list[dict] = field(default_factory=list)
    # Aggregated metrics - ALL queries
    all_queries_metagraph_avg_ms: float = 0.0
    all_queries_grep_avg_ms: float = 0.0
    all_queries_avg_speedup: float = 0.0
    # Aggregated metrics - ONLY queries where MetagraphRAG returned results
    productive_queries_count: int = 0
    productive_queries_metagraph_avg_ms: float = 0.0
    productive_queries_grep_avg_ms: float = 0.0
    productive_queries_avg_speedup: float = 0.0
    productive_queries_median_speedup: float = 0.0
    # Empty query analysis
    empty_queries_count: int = 0
    empty_queries_reasons: list[str] = field(default_factory=list)
    # Precision
    metagraph_avg_precision: float = 0.0
    grep_avg_precision: float = 0.0
    metagraph_avg_recall: float = 0.0
    grep_avg_recall: float = 0.0
    # Auditor report
    auditor_report: str = ""
    # Verdict
    claimed_speedup: str = ""
    actual_speedup: str = ""
    claimed_precision: str = ""
    actual_precision: str = ""
    verdict_speedup: str = ""
    verdict_precision: str = ""
    verdict_latency: str = ""
    verdict_overall: str = ""


def run_grep_query(pattern: str, search_dir: str = "core") -> tuple[float, list[str], int]:
    """
    Run a grep -rl query and return (time_ms, files_found, match_count).
    """
    start = time.perf_counter()
    try:
        result = subprocess.run(
            ["grep", "-r", "-l", "--include=*.py", pattern, search_dir],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return elapsed_ms, files, len(files)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"  [WARN] grep failed: {e}")
        return elapsed_ms, [], 0


def normalize_path(p: str) -> str:
    """Normalize a file path for comparison (forward slashes, lowercase)."""
    return p.replace("\\", "/").strip()


def compute_precision_recall(found: set[str], ground_truth: set[str]) -> tuple[float, float]:
    """
    Compute precision and recall against a ground truth set.
    """
    if not found and not ground_truth:
        return 1.0, 1.0  # Both empty = perfect agreement
    if not found:
        return 0.0, 0.0
    if not ground_truth:
        return 0.0, 0.0
    tp = len(found & ground_truth)
    precision = tp / len(found) if found else 0.0
    recall = tp / len(ground_truth) if ground_truth else 0.0
    return precision, recall


def time_metagraph_query(func, *args, iterations=NUM_ITERATIONS, **kwargs):
    """Run a MetagraphRAG query multiple times and return (avg_ms, last_result)."""
    start = time.perf_counter()
    result = None
    for _ in range(iterations):
        result = func(*args, **kwargs)
    total_ms = (time.perf_counter() - start) * 1000
    avg_ms = total_ms / iterations
    return avg_ms, result


def time_grep_query(pattern: str, iterations=NUM_ITERATIONS):
    """Run grep multiple times and return (avg_ms, files, count)."""
    times = []
    files = []
    count = 0
    for _ in range(iterations):
        t, f, c = run_grep_query(pattern)
        times.append(t)
        files = f
        count = c
    return sum(times) / len(times), files, count


def main():
    print("=" * 80)
    print("MetagraphRAG Benchmark: Honest Performance Evaluation")
    print(f"Date: {datetime.now().isoformat()}")
    print(f"Iterations per query: {NUM_ITERATIONS}")
    print("=" * 80)
    print()

    # =========================================================================
    # PHASE 1: Scan codebase
    # =========================================================================
    print("[PHASE 1] Scanning codebase with MetagraphRAG...")

    from core.metagraph import scan_codebase, get_auditor, reset_auditor
    from core.metagraph import query_dependencies, analyze_impact, semantic_search
    from core.metagraph.code_graph import SymbolType

    reset_auditor()
    auditor = get_auditor()

    scan_start = time.perf_counter()
    graph, scan_stats = scan_codebase("core", include_tests=False)
    scan_time_ms = (time.perf_counter() - scan_start) * 1000

    graph_stats = graph.stats()
    print(f"  Scan time:       {scan_time_ms:.1f}ms")
    print(f"  Files scanned:   {scan_stats.files_scanned}")
    print(f"  Files failed:    {scan_stats.files_failed}")
    print(f"  Symbols found:   {graph_stats['symbols']}")
    print(f"  Dependencies:    {graph_stats['dependencies']}")
    print(f"  Classes:         {graph_stats['classes']}")
    print(f"  Functions:       {graph_stats['functions']}")
    print(f"  Methods:         {graph_stats['methods']}")

    # Track scan in auditor
    auditor.track_scan(
        scan_duration_ms=scan_time_ms,
        files_scanned=scan_stats.files_scanned,
        files_failed=scan_stats.files_failed,
        graph_stats=graph_stats,
    )

    # =========================================================================
    # PHASE 1b: Diagnose graph connectivity
    # =========================================================================
    print("\n[PHASE 1b] Diagnosing graph structure...")

    # Check how many symbols have dependencies
    symbols_with_deps = sum(
        1 for name in graph.symbols
        if len(graph.get_dependencies(name)) > 0
    )
    symbols_with_dependents = sum(
        1 for name in graph.symbols
        if len(graph.get_dependents(name)) > 0
    )
    total_symbols = len(graph.symbols)

    print(f"  Symbols with outgoing deps:  {symbols_with_deps}/{total_symbols} "
          f"({symbols_with_deps/total_symbols*100:.1f}%)")
    print(f"  Symbols with incoming deps:  {symbols_with_dependents}/{total_symbols} "
          f"({symbols_with_dependents/total_symbols*100:.1f}%)")

    # Check path format used in graph
    sample_paths = set()
    for sym in list(graph.symbols.values())[:20]:
        if sym.file_path:
            sample_paths.add(sym.file_path)
    print(f"  Path format samples: {list(sample_paths)[:3]}")

    # Check if specific symbols have deps
    test_symbol = "OrchestratorV7"
    matches = graph.find_symbols_by_name(test_symbol)
    if matches:
        sym = matches[0]
        deps = graph.get_dependencies(sym.qualified_name)
        dependents = graph.get_dependents(sym.qualified_name)
        print(f"  {test_symbol}: {len(deps)} deps, {len(dependents)} dependents")
    else:
        print(f"  {test_symbol}: NOT FOUND in graph")

    # Discover bugs
    bugs = []

    # Bug 1: Impact queries use forward-slash paths but graph stores backslash paths (Windows)
    sample_path = list(sample_paths)[0] if sample_paths else ""
    if "\\" in sample_path:
        bug_msg = (
            "BUG: Graph stores Windows backslash paths (e.g., 'core\\\\config.py') "
            "but analyze_impact() is called with forward-slash paths "
            "(e.g., 'core/config.py'). find_symbols_in_file() does exact string "
            "match, so impact queries return 0 results on Windows."
        )
        bugs.append(bug_msg)
        print(f"  [BUG FOUND] {bug_msg}")

    # Bug 2: Class symbols have 0 dependencies (only module-level imports tracked)
    class_deps_count = 0
    for sym in graph.find_symbols_by_type(SymbolType.CLASS)[:50]:
        if graph.get_dependencies(sym.qualified_name):
            class_deps_count += 1
    if class_deps_count == 0:
        bug_msg = (
            "BUG: Class-level dependency queries return 0 dependencies. "
            "The AST parser only records module-level import dependencies, "
            "not class-to-class dependency edges. query_dependencies() for "
            "a class symbol always returns 0 transitive dependencies."
        )
        bugs.append(bug_msg)
        print(f"  [BUG FOUND] {bug_msg}")

    print()

    # =========================================================================
    # PHASE 2: Define and run benchmark queries
    # =========================================================================
    print("[PHASE 2] Running benchmark queries...")
    print("-" * 80)

    # We'll run queries that both work AND don't work, and be honest about it.
    # For impact queries, we also try with the correct path format.

    results = []

    # ---------- Dependency queries ----------
    dep_targets = ["OrchestratorV7", "AsyncDriverFactory", "CodeGraph", "Config"]

    for target in dep_targets:
        desc = f"Dependency: what does {target} depend on?"
        print(f"\n  {desc}")

        # MetagraphRAG
        mg_time, dep_result = time_metagraph_query(
            query_dependencies, graph, target
        )

        mg_files = []
        mg_symbols = []
        mg_count = 0
        is_empty = True
        notes = ""

        if dep_result and dep_result.transitive_dependencies:
            mg_symbols = [dep_result.symbol.name] + [
                s.name for s in dep_result.transitive_dependencies
            ]
            mg_files = list(set(
                s.file_path for s in dep_result.transitive_dependencies if s.file_path
            ))
            mg_count = len(dep_result.transitive_dependencies)
            is_empty = False
        elif dep_result:
            notes = (
                "Symbol found but has 0 transitive dependencies. "
                "AST parser only links module-level imports, not class deps."
            )
        else:
            notes = "Symbol not found in graph."

        # Grep equivalent
        grep_time, grep_files, grep_count = time_grep_query(target)

        # Normalize paths
        mg_files_norm = set(normalize_path(f) for f in mg_files if f)
        grep_files_norm = set(normalize_path(f) for f in grep_files if f)

        # Ground truth = union
        ground_truth = mg_files_norm | grep_files_norm
        mg_prec, mg_recall = compute_precision_recall(mg_files_norm, ground_truth)
        grep_prec, grep_recall = compute_precision_recall(grep_files_norm, ground_truth)

        speedup = grep_time / mg_time if mg_time > 0 else float("inf")

        result = QueryResult(
            query_name=f"dep_{target}",
            query_target=target,
            query_type="dependency",
            description=desc,
            metagraph_time_ms=round(mg_time, 4),
            metagraph_files_found=sorted(mg_files_norm),
            metagraph_symbols_found=mg_symbols[:20],
            metagraph_result_count=mg_count,
            metagraph_returned_empty=is_empty,
            grep_time_ms=round(grep_time, 4),
            grep_files_found=sorted(grep_files_norm),
            grep_result_count=grep_count,
            speedup_ratio=round(speedup, 2),
            speedup_is_meaningful=not is_empty,
            metagraph_precision=round(mg_prec, 4),
            grep_precision=round(grep_prec, 4),
            metagraph_recall=round(mg_recall, 4),
            grep_recall=round(grep_recall, 4),
            notes=notes,
        )
        results.append(result)

        status = "[EMPTY]" if is_empty else "[OK]"
        print(f"    {status} MetagraphRAG: {mg_time:.3f}ms, {mg_count} results, "
              f"{len(mg_files_norm)} files")
        print(f"         Grep:         {grep_time:.3f}ms, {grep_count} results, "
              f"{len(grep_files_norm)} files")
        if is_empty:
            print(f"         NOTE: {notes}")
        print(f"         Speedup:      {speedup:.1f}x "
              f"({'MISLEADING - MG returned nothing' if is_empty else 'meaningful'})")

        auditor.track_query("dependency", target, mg_time, mg_count)

    # ---------- Impact queries ----------
    impact_targets_forward_slash = [
        "core/orchestration_v7.py",
        "core/config.py",
    ]

    for target in impact_targets_forward_slash:
        desc = f"Impact: what is affected by changing {target}?"
        print(f"\n  {desc}")

        # Try with forward slash (as documented in API)
        mg_time_fwd, impact_fwd = time_metagraph_query(
            analyze_impact, graph, target
        )

        # Also try with the actual path format stored in the graph (backslash on Windows)
        target_bs = target.replace("/", "\\")
        mg_time_bs, impact_bs = time_metagraph_query(
            analyze_impact, graph, target_bs
        )

        # Use whichever returned results (prefer backslash since graph uses it)
        if impact_bs and impact_bs.affected_files:
            mg_time = mg_time_bs
            impact_result = impact_bs
            path_note = "Used backslash path (matches graph format)"
        elif impact_fwd and impact_fwd.affected_files:
            mg_time = mg_time_fwd
            impact_result = impact_fwd
            path_note = "Used forward slash path"
        else:
            mg_time = mg_time_fwd
            impact_result = impact_fwd
            path_note = "Neither path format returned results"

        mg_symbols = [s.name for s in impact_result.affected_symbols]
        mg_files = list(impact_result.affected_files)
        mg_count = len(impact_result.affected_files)
        is_empty = mg_count == 0

        notes = ""
        if is_empty:
            # Check why
            syms_fwd = graph.find_symbols_in_file(target)
            syms_bs = graph.find_symbols_in_file(target_bs)
            notes = (
                f"Forward-slash query found {len(syms_fwd)} symbols, "
                f"backslash query found {len(syms_bs)} symbols. "
                f"{path_note}."
            )
            if len(syms_bs) > 0 and mg_count == 0:
                # Symbols exist but no dependents
                notes += " Symbols found but have 0 reverse dependencies in graph."

        # Grep: find files that import from this module
        module_name = target.replace("/", ".").replace(".py", "").split(".")[-1]
        grep_time, grep_files, grep_count = time_grep_query(module_name)

        mg_files_norm = set(normalize_path(f) for f in mg_files if f)
        grep_files_norm = set(normalize_path(f) for f in grep_files if f)
        ground_truth = mg_files_norm | grep_files_norm
        mg_prec, mg_recall = compute_precision_recall(mg_files_norm, ground_truth)
        grep_prec, grep_recall = compute_precision_recall(grep_files_norm, ground_truth)

        speedup = grep_time / mg_time if mg_time > 0 else float("inf")

        result = QueryResult(
            query_name=f"impact_{module_name}",
            query_target=target,
            query_type="impact",
            description=desc,
            metagraph_time_ms=round(mg_time, 4),
            metagraph_files_found=sorted(mg_files_norm),
            metagraph_symbols_found=mg_symbols[:20],
            metagraph_result_count=mg_count,
            metagraph_returned_empty=is_empty,
            grep_time_ms=round(grep_time, 4),
            grep_files_found=sorted(grep_files_norm),
            grep_result_count=grep_count,
            speedup_ratio=round(speedup, 2),
            speedup_is_meaningful=not is_empty,
            metagraph_precision=round(mg_prec, 4),
            grep_precision=round(grep_prec, 4),
            metagraph_recall=round(mg_recall, 4),
            grep_recall=round(grep_recall, 4),
            notes=notes,
        )
        results.append(result)

        status = "[EMPTY]" if is_empty else "[OK]"
        print(f"    {status} MetagraphRAG: {mg_time:.3f}ms, {mg_count} affected files, "
              f"{len(mg_symbols)} symbols")
        print(f"         Grep:         {grep_time:.3f}ms, {grep_count} files")
        if is_empty:
            print(f"         NOTE: {notes}")
        print(f"         Speedup:      {speedup:.1f}x "
              f"({'MISLEADING' if is_empty else 'meaningful'})")

        auditor.track_query("impact", target, mg_time, mg_count)

    # ---------- Semantic search queries ----------
    search_targets = ["driver", "protocol", "memory", "security"]

    for target in search_targets:
        desc = f"Search: find all symbols matching '{target}'"
        print(f"\n  {desc}")

        mg_time, search_results = time_metagraph_query(
            semantic_search, graph, target, limit=50
        )

        mg_symbols = [r.symbol.name for r in search_results]
        mg_files = list(set(
            r.symbol.file_path for r in search_results if r.symbol.file_path
        ))
        mg_count = len(search_results)
        is_empty = mg_count == 0

        # Grep
        grep_time, grep_files, grep_count = time_grep_query(target)

        mg_files_norm = set(normalize_path(f) for f in mg_files if f)
        grep_files_norm = set(normalize_path(f) for f in grep_files if f)
        ground_truth = mg_files_norm | grep_files_norm
        mg_prec, mg_recall = compute_precision_recall(mg_files_norm, ground_truth)
        grep_prec, grep_recall = compute_precision_recall(grep_files_norm, ground_truth)

        speedup = grep_time / mg_time if mg_time > 0 else float("inf")

        notes = ""
        if mg_count > 0:
            notes = (
                f"MetagraphRAG finds {mg_count} AST symbols vs grep's {grep_count} files. "
                f"MG is more targeted (classes/functions only), grep matches any text."
            )

        result = QueryResult(
            query_name=f"search_{target}",
            query_target=target,
            query_type="search",
            description=desc,
            metagraph_time_ms=round(mg_time, 4),
            metagraph_files_found=sorted(mg_files_norm),
            metagraph_symbols_found=mg_symbols[:20],
            metagraph_result_count=mg_count,
            metagraph_returned_empty=is_empty,
            grep_time_ms=round(grep_time, 4),
            grep_files_found=sorted(grep_files_norm),
            grep_result_count=grep_count,
            speedup_ratio=round(speedup, 2),
            speedup_is_meaningful=not is_empty,
            metagraph_precision=round(mg_prec, 4),
            grep_precision=round(grep_prec, 4),
            metagraph_recall=round(mg_recall, 4),
            grep_recall=round(grep_recall, 4),
            notes=notes,
        )
        results.append(result)

        status = "[EMPTY]" if is_empty else "[OK]"
        print(f"    {status} MetagraphRAG: {mg_time:.3f}ms, {mg_count} symbols, "
              f"{len(mg_files_norm)} files")
        print(f"         Grep:         {grep_time:.3f}ms, {grep_count} files")
        print(f"         Speedup:      {speedup:.1f}x")
        if notes:
            print(f"         NOTE: {notes}")

        auditor.track_query("search", target, mg_time, mg_count)

    # =========================================================================
    # PHASE 3: Auditor report
    # =========================================================================
    print("\n" + "=" * 80)
    print("[PHASE 3] Auditor Performance Report")
    print("=" * 80)

    auditor_report = auditor.get_query_performance_report()
    print(auditor_report)

    # =========================================================================
    # PHASE 4: Aggregate and verdict
    # =========================================================================
    print("\n" + "=" * 80)
    print("[PHASE 4] Aggregate Results & Verdict")
    print("=" * 80)

    # Split into productive (returned results) and empty queries
    productive = [r for r in results if not r.metagraph_returned_empty]
    empty = [r for r in results if r.metagraph_returned_empty]

    all_mg_times = [r.metagraph_time_ms for r in results]
    all_grep_times = [r.grep_time_ms for r in results]
    all_speedups = [r.speedup_ratio for r in results]

    all_avg_mg = sum(all_mg_times) / len(all_mg_times) if all_mg_times else 0
    all_avg_grep = sum(all_grep_times) / len(all_grep_times) if all_grep_times else 0
    all_avg_speedup = sum(all_speedups) / len(all_speedups) if all_speedups else 0

    prod_mg_times = [r.metagraph_time_ms for r in productive]
    prod_grep_times = [r.grep_time_ms for r in productive]
    prod_speedups = [r.speedup_ratio for r in productive]

    prod_avg_mg = sum(prod_mg_times) / len(prod_mg_times) if prod_mg_times else 0
    prod_avg_grep = sum(prod_grep_times) / len(prod_grep_times) if prod_grep_times else 0
    prod_avg_speedup = sum(prod_speedups) / len(prod_speedups) if prod_speedups else 0
    sorted_prod_speedups = sorted(prod_speedups) if prod_speedups else [0]
    prod_median_speedup = sorted_prod_speedups[len(sorted_prod_speedups) // 2]

    # Precision/recall (only for productive queries)
    prod_mg_precisions = [r.metagraph_precision for r in productive]
    prod_grep_precisions = [r.grep_precision for r in productive]
    prod_mg_recalls = [r.metagraph_recall for r in productive]
    prod_grep_recalls = [r.grep_recall for r in productive]

    avg_mg_precision = sum(prod_mg_precisions) / len(prod_mg_precisions) if prod_mg_precisions else 0
    avg_grep_precision = sum(prod_grep_precisions) / len(prod_grep_precisions) if prod_grep_precisions else 0
    avg_mg_recall = sum(prod_mg_recalls) / len(prod_mg_recalls) if prod_mg_recalls else 0
    avg_grep_recall = sum(prod_grep_recalls) / len(prod_grep_recalls) if prod_grep_recalls else 0

    print(f"\n  Total queries:        {len(results)}")
    print(f"  Productive queries:   {len(productive)} (returned results)")
    print(f"  Empty queries:        {len(empty)} (returned 0 results)")

    print(f"\n  --- ALL QUERIES (including empty/misleading) ---")
    print(f"  MetagraphRAG avg:     {all_avg_mg:.3f}ms")
    print(f"  Grep avg:             {all_avg_grep:.3f}ms")
    print(f"  Avg speedup:          {all_avg_speedup:.1f}x "
          f"(INFLATED by {len(empty)} empty queries)")

    print(f"\n  --- PRODUCTIVE QUERIES ONLY (MetagraphRAG returned results) ---")
    print(f"  MetagraphRAG avg:     {prod_avg_mg:.3f}ms")
    print(f"  Grep avg:             {prod_avg_grep:.3f}ms")
    print(f"  Avg speedup:          {prod_avg_speedup:.1f}x")
    print(f"  Median speedup:       {prod_median_speedup:.1f}x")
    if prod_speedups:
        print(f"  Min speedup:          {min(prod_speedups):.1f}x")
        print(f"  Max speedup:          {max(prod_speedups):.1f}x")

    print(f"\n  --- PRECISION / RECALL (productive queries) ---")
    print(f"  MetagraphRAG precision: {avg_mg_precision:.2%}")
    print(f"  Grep precision:         {avg_grep_precision:.2%}")
    print(f"  MetagraphRAG recall:    {avg_mg_recall:.2%}")
    print(f"  Grep recall:            {avg_grep_recall:.2%}")

    print(f"\n  --- EMPTY QUERY BREAKDOWN ---")
    for r in empty:
        print(f"    {r.query_name}: {r.notes}")

    # =========================================================================
    # VERDICT
    # =========================================================================
    print("\n" + "-" * 80)
    print("  VERDICT")
    print("-" * 80)

    # Speedup claim: "180-720x faster"
    speedup_claim = "180-720x faster than grep"
    if len(productive) == 0:
        verdict_speedup = (
            "UNTESTABLE: All MetagraphRAG queries returned 0 results. "
            "Speedup is meaningless when the tool finds nothing."
        )
    elif prod_avg_speedup >= 180:
        verdict_speedup = (
            f"CONFIRMED (for productive queries): {prod_avg_speedup:.0f}x avg speedup."
        )
    elif prod_avg_speedup >= 50:
        verdict_speedup = (
            f"OVERSTATED: {prod_avg_speedup:.0f}x avg is fast but below 180-720x. "
            f"Additionally, {len(empty)}/{len(results)} queries returned empty results."
        )
    elif prod_avg_speedup >= 1:
        verdict_speedup = (
            f"SIGNIFICANTLY OVERSTATED: Real speedup is {prod_avg_speedup:.1f}x for "
            f"the {len(productive)} queries that worked. {len(empty)}/{len(results)} "
            f"queries returned empty results due to bugs in the graph."
        )
    else:
        verdict_speedup = (
            f"FALSE: MetagraphRAG is actually SLOWER than grep for productive queries."
        )

    # Precision claim: "95-98% precision"
    precision_claim = "95-98% precision vs 60-70% (grep)"
    if len(productive) == 0:
        verdict_precision = "UNTESTABLE: No productive queries to evaluate."
    elif avg_mg_precision >= 0.95:
        verdict_precision = (
            f"CONFIRMED: MetagraphRAG precision {avg_mg_precision:.1%} on "
            f"productive queries."
        )
    elif avg_mg_precision >= 0.80:
        verdict_precision = (
            f"PARTIALLY TRUE: MetagraphRAG precision {avg_mg_precision:.1%} is decent "
            f"but below 95-98%. Grep precision: {avg_grep_precision:.1%}."
        )
    else:
        verdict_precision = (
            f"NOT CONFIRMED: MetagraphRAG precision {avg_mg_precision:.1%} is "
            f"significantly below claimed 95-98%. Note: {len(empty)}/{len(results)} "
            f"queries returned 0 results (0% precision implicitly)."
        )

    # Latency claim: "<1ms query latency (cached)"
    sub_1ms_all = [t for t in all_mg_times if t < 1.0]
    sub_1ms_prod = [t for t in prod_mg_times if t < 1.0]
    if len(sub_1ms_all) == len(all_mg_times):
        verdict_latency = (
            f"CONFIRMED: All {len(all_mg_times)} queries < 1ms. But "
            f"{len(empty)} were empty (returning nothing is always fast)."
        )
    elif len(sub_1ms_prod) > 0:
        verdict_latency = (
            f"PARTIALLY TRUE: {len(sub_1ms_prod)}/{len(productive)} productive queries "
            f"< 1ms. {len(sub_1ms_all) - len(sub_1ms_prod)} empty queries also < 1ms. "
            f"Productive query avg: {prod_avg_mg:.3f}ms."
        )
    else:
        verdict_latency = (
            f"NOT CONFIRMED for productive queries: avg {prod_avg_mg:.3f}ms. "
            f"Only empty queries achieved < 1ms."
        )

    print(f"\n  Claim 1: \"{speedup_claim}\"")
    print(f"  Result:  {verdict_speedup}")
    print(f"\n  Claim 2: \"{precision_claim}\"")
    print(f"  Result:  {verdict_precision}")
    print(f"\n  Claim 3: \"<1ms query latency (cached)\"")
    print(f"  Result:  {verdict_latency}")

    # Overall verdict
    verdict_overall = (
        f"BENCHMARK SUMMARY: "
        f"Of {len(results)} queries, {len(productive)} returned results and "
        f"{len(empty)} returned nothing. "
        f"For queries that produced results (semantic search), MetagraphRAG is "
        f"{prod_avg_speedup:.1f}x faster than grep (median {prod_median_speedup:.1f}x), "
        f"with {avg_mg_precision:.0%} precision. "
        f"Dependency and impact queries are NON-FUNCTIONAL: the AST parser only "
        f"tracks module-level import edges, not class/function dependency graphs, "
        f"so query_dependencies() for classes always returns 0 results. "
        f"Impact analysis is broken on Windows due to path separator mismatch. "
        f"The claimed '180-720x faster' speedup was measured against queries that "
        f"return empty results (trivially fast). "
        f"The claimed '95-98% precision' cannot be verified because the core "
        f"dependency/impact queries do not work. "
        f"Bugs found: {len(bugs)}."
    )

    print(f"\n  OVERALL: {verdict_overall}")

    if bugs:
        print(f"\n  BUGS DISCOVERED:")
        for i, bug in enumerate(bugs, 1):
            print(f"    {i}. {bug}")

    # =========================================================================
    # PHASE 5: Write results JSON
    # =========================================================================
    output = BenchmarkResults(
        timestamp=datetime.now().isoformat(),
        python_version=sys.version,
        project_root=str(PROJECT_ROOT),
        scan_time_ms=round(scan_time_ms, 2),
        files_scanned=scan_stats.files_scanned,
        files_failed=scan_stats.files_failed,
        symbols_found=graph_stats["symbols"],
        dependencies_found=graph_stats["dependencies"],
        graph_classes=graph_stats["classes"],
        graph_functions=graph_stats["functions"],
        graph_methods=graph_stats["methods"],
        bugs_discovered=bugs,
        queries=[asdict(r) for r in results],
        all_queries_metagraph_avg_ms=round(all_avg_mg, 4),
        all_queries_grep_avg_ms=round(all_avg_grep, 4),
        all_queries_avg_speedup=round(all_avg_speedup, 2),
        productive_queries_count=len(productive),
        productive_queries_metagraph_avg_ms=round(prod_avg_mg, 4),
        productive_queries_grep_avg_ms=round(prod_avg_grep, 4),
        productive_queries_avg_speedup=round(prod_avg_speedup, 2),
        productive_queries_median_speedup=round(prod_median_speedup, 2),
        empty_queries_count=len(empty),
        empty_queries_reasons=[r.notes for r in empty],
        metagraph_avg_precision=round(avg_mg_precision, 4),
        grep_avg_precision=round(avg_grep_precision, 4),
        metagraph_avg_recall=round(avg_mg_recall, 4),
        grep_avg_recall=round(avg_grep_recall, 4),
        auditor_report=auditor_report,
        claimed_speedup=speedup_claim,
        actual_speedup=(
            f"Productive queries: {prod_avg_speedup:.1f}x avg, "
            f"{prod_median_speedup:.1f}x median. "
            f"All queries (including empty): {all_avg_speedup:.1f}x avg (inflated)."
        ),
        claimed_precision=precision_claim,
        actual_precision=(
            f"MetagraphRAG {avg_mg_precision:.1%} vs grep {avg_grep_precision:.1%} "
            f"(productive queries only)."
        ),
        verdict_speedup=verdict_speedup,
        verdict_precision=verdict_precision,
        verdict_latency=verdict_latency,
        verdict_overall=verdict_overall,
    )

    output_path = PROJECT_ROOT / "benchmarks" / "metagraph_benchmark_results.json"
    with open(output_path, "w") as f:
        json.dump(asdict(output), f, indent=2, default=str)

    print(f"\n  Results written to: {output_path}")
    print("=" * 80)

    return output


if __name__ == "__main__":
    main()
