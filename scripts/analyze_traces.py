"""
NEXUS V12.4 P4.1 - Jaeger Trace Analysis

Fetches traces from Jaeger API and identifies hot paths for Rust migration.

Usage:
    # After running benchmark_workload.py
    python scripts/analyze_traces.py

Output:
    - Hot paths (>100ms avg latency)
    - High frequency operations (>1000 calls)
    - CPU bottlenecks (top 20 by total time)
"""

import requests
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any

# Jaeger API endpoint (default docker-compose)
JAEGER_API = "http://localhost:16686/api"
SERVICE_NAME = "nexus-backend"


def fetch_jaeger_traces(
    service: str = SERVICE_NAME,
    limit: int = 1000,
    lookback_hours: int = 1
) -> List[Dict[str, Any]]:
    """
    Fetch traces from Jaeger API.

    Args:
        service: Service name to filter
        limit: Max traces to fetch
        lookback_hours: How far back to search

    Returns:
        List of trace dicts
    """
    # Calculate time range
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=lookback_hours)

    # Jaeger expects microseconds since epoch
    start_us = int(start_time.timestamp() * 1_000_000)
    end_us = int(end_time.timestamp() * 1_000_000)

    url = f"{JAEGER_API}/traces"
    params = {
        "service": service,
        "limit": limit,
        "start": start_us,
        "end": end_us,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        traces = data.get("data", [])
        print(f"[OK] Fetched {len(traces)} traces from Jaeger")
        return traces

    except requests.RequestException as e:
        print(f"[NO] Failed to fetch traces: {e}")
        print(f"Make sure Jaeger is running: docker compose --profile observability up -d")
        return []


def analyze_hotpaths(traces: List[Dict[str, Any]]) -> None:
    """
    Analyze traces and identify hot paths.

    Metrics:
    - Average latency per operation
    - Max latency per operation
    - Call count per operation
    - Total time per operation (avg * count)
    """
    if not traces:
        print("[warning]️ No traces to analyze")
        return

    # Collect span data
    operations = defaultdict(lambda: {
        "durations": [],
        "count": 0,
        "total_ms": 0,
        "max_ms": 0,
        "tags": defaultdict(int)
    })

    for trace in traces:
        for span in trace.get("spans", []):
            op_name = span.get("operationName", "unknown")
            duration_us = span.get("duration", 0)
            duration_ms = duration_us / 1000.0

            operations[op_name]["durations"].append(duration_ms)
            operations[op_name]["count"] += 1
            operations[op_name]["total_ms"] += duration_ms
            operations[op_name]["max_ms"] = max(
                operations[op_name]["max_ms"], duration_ms
            )

            # Track tags for context
            for tag in span.get("tags", []):
                key = tag.get("key", "")
                if key in ("error", "component", "span.kind"):
                    operations[op_name]["tags"][key] += 1

    # Calculate statistics
    results = []
    for op_name, data in operations.items():
        avg_ms = data["total_ms"] / data["count"] if data["count"] > 0 else 0
        results.append({
            "operation": op_name,
            "avg_ms": avg_ms,
            "max_ms": data["max_ms"],
            "count": data["count"],
            "total_ms": data["total_ms"],
            "errors": data["tags"].get("error", 0)
        })

    # Sort by total time (impact = avg * frequency)
    results.sort(key=lambda x: x["total_ms"], reverse=True)

    # Print analysis
    print("\n" + "=" * 100)
    print("🔥 HOT PATHS (Top 20 by Total Time)")
    print("=" * 100)
    print(f"{'Operation':<50} {'Avg (ms)':>10} {'Max (ms)':>10} {'Count':>8} {'Total (s)':>10} {'Errors':>8}")
    print("-" * 100)

    for i, r in enumerate(results[:20], 1):
        print(
            f"{r['operation'][:50]:<50} "
            f"{r['avg_ms']:>10.2f} "
            f"{r['max_ms']:>10.2f} "
            f"{r['count']:>8} "
            f"{r['total_ms'] / 1000:>10.2f} "
            f"{r['errors']:>8}"
        )

    # Identify candidates for Rust migration
    print("\n" + "=" * 100)
    print("🎯 RUST MIGRATION CANDIDATES")
    print("=" * 100)

    # Criteria: avg >100ms OR count >1000 OR total >10s
    candidates = [
        r for r in results
        if r["avg_ms"] > 100 or r["count"] > 1000 or r["total_ms"] > 10000
    ]

    if candidates:
        print(f"Found {len(candidates)} candidates for optimization:")
        for c in candidates[:10]:
            reason = []
            if c["avg_ms"] > 100:
                reason.append(f"slow avg ({c['avg_ms']:.0f}ms)")
            if c["count"] > 1000:
                reason.append(f"high frequency ({c['count']} calls)")
            if c["total_ms"] > 10000:
                reason.append(f"high impact ({c['total_ms'] / 1000:.1f}s total)")

            print(f"  - {c['operation']}: {', '.join(reason)}")
    else:
        print("[OK] No obvious hot paths found (system performing well)")

    # Summary stats
    total_spans = sum(r["count"] for r in results)
    total_time_s = sum(r["total_ms"] for r in results) / 1000

    print("\n" + "=" * 100)
    print("📊 SUMMARY")
    print("=" * 100)
    print(f"Total operations: {len(results)}")
    print(f"Total spans: {total_spans}")
    print(f"Total time: {total_time_s:.2f}s")
    print(f"Avg span duration: {(total_time_s / total_spans) * 1000:.2f}ms")

    # Export for further analysis
    output_file = "workspace/profiling_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n💾 Detailed results saved to: {output_file}")


def main():
    """Entry point for trace analysis."""
    print("🔍 Fetching traces from Jaeger...")
    traces = fetch_jaeger_traces()

    if traces:
        analyze_hotpaths(traces)
    else:
        print("\n[warning]️ No traces found. Did you run benchmark_workload.py first?")


if __name__ == "__main__":
    main()
