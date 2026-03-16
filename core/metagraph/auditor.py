"""
MetagraphRAG Self-Auditing System

Monitors MetagraphRAG performance, freshness, and accuracy.
Integrates with NEXUS observability for comprehensive tracking.

Features:
- Query performance metrics (latency, throughput)
- Graph freshness tracking (last updated, staleness)
- Cache hit rates
- Accuracy validation (optional manual verification)
- Integration with TelemetryCollector

Usage:
    from core.metagraph.auditor import get_auditor, track_query

    auditor = get_auditor()

    # Track a query
    with track_query("dependency_query", "DriverProtocol"):
        result = query_dependencies(graph, "DriverProtocol")

    # Get metrics
    stats = auditor.get_stats()
    print(f"Avg query latency: {stats.avg_query_latency_ms:.2f}ms")
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

# Optional telemetry integration (avoid hard dependency)
try:
    from core.observability import PerformanceProfiler, get_profiler

    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False
    PerformanceProfiler = None
    get_profiler = None


@dataclass
class QueryMetrics:
    """Metrics for a single query."""

    query_type: str  # "dependency_query", "impact_analysis", "semantic_search"
    query_target: str  # Symbol name or file path
    latency_ms: float
    timestamp: datetime
    result_count: int
    cache_hit: bool = False


@dataclass
class GraphFreshnessMetrics:
    """Metrics for graph freshness."""

    last_scan_time: datetime
    last_update_time: datetime
    total_symbols: int
    total_dependencies: int
    scan_duration_ms: float
    files_scanned: int
    files_failed: int


@dataclass
class AuditStats:
    """Aggregated audit statistics."""

    # Query metrics
    total_queries: int
    total_query_time_ms: float
    avg_query_latency_ms: float
    query_types: dict[str, int]

    # Cache metrics
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float

    # Freshness metrics
    graph_age_seconds: float
    last_scan_time: datetime
    total_symbols: int
    total_dependencies: int

    # Performance
    queries_per_second: float
    fastest_query_ms: float
    slowest_query_ms: float


class MetagraphAuditor:
    """
    Self-auditing system for MetagraphRAG.

    Tracks all queries, graph updates, and performance metrics.
    Integrates with NEXUS telemetry for unified observability.
    """

    def __init__(self):
        self.query_history: list[QueryMetrics] = []
        self.freshness_history: list[GraphFreshnessMetrics] = []

        # Current state
        self._last_scan_time: datetime | None = None
        self._last_update_time: datetime | None = None
        self._current_graph_stats: dict[str, int] = {}

        # Performance tracking
        self._query_count = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # Integration with NEXUS observability (optional)
        self.profiler = get_profiler() if TELEMETRY_AVAILABLE else None

    def track_query(
        self,
        query_type: str,
        query_target: str,
        latency_ms: float,
        result_count: int,
        cache_hit: bool = False,
    ) -> None:
        """
        Track a query execution.

        Args:
            query_type: Type of query (dependency_query, impact_analysis, etc.)
            query_target: Symbol name or file path queried
            latency_ms: Query execution time in milliseconds
            result_count: Number of results returned
            cache_hit: Whether this was a cache hit
        """
        metrics = QueryMetrics(
            query_type=query_type,
            query_target=query_target,
            latency_ms=latency_ms,
            timestamp=datetime.now(),
            result_count=result_count,
            cache_hit=cache_hit,
        )

        self.query_history.append(metrics)
        self._query_count += 1

        if cache_hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

        # Send to profiler (optional)
        if self.profiler:
            self.profiler.record(
                category="metagraph.query",
                name=query_type,
                duration_ms=latency_ms,
                tags={"cache_hit": str(cache_hit)},
            )

    def track_scan(
        self,
        scan_duration_ms: float,
        files_scanned: int,
        files_failed: int,
        graph_stats: dict[str, int],
    ) -> None:
        """
        Track a codebase scan.

        Args:
            scan_duration_ms: Time taken to scan in milliseconds
            files_scanned: Number of files successfully scanned
            files_failed: Number of files that failed to scan
            graph_stats: Graph statistics (symbols, dependencies, etc.)
        """
        now = datetime.now()

        metrics = GraphFreshnessMetrics(
            last_scan_time=now,
            last_update_time=now,
            total_symbols=graph_stats.get("symbols", 0),
            total_dependencies=graph_stats.get("dependencies", 0),
            scan_duration_ms=scan_duration_ms,
            files_scanned=files_scanned,
            files_failed=files_failed,
        )

        self.freshness_history.append(metrics)
        self._last_scan_time = now
        self._last_update_time = now
        self._current_graph_stats = graph_stats

        # Send to profiler (optional)
        if self.profiler:
            self.profiler.record(
                category="metagraph.scan",
                name="full_scan",
                duration_ms=scan_duration_ms,
            )

    def track_update(
        self,
        updated_files: set[str],
        graph_stats: dict[str, int],
    ) -> None:
        """
        Track an incremental graph update.

        Args:
            updated_files: Set of file paths that were updated
            graph_stats: Updated graph statistics
        """
        self._last_update_time = datetime.now()
        self._current_graph_stats = graph_stats

        # Send to profiler (optional)
        if self.profiler:
            self.profiler.record(
                category="metagraph.update",
                name="incremental_update",
                duration_ms=0.0,  # No duration for updates
            )

    def get_stats(self) -> AuditStats:
        """
        Get aggregated audit statistics.

        Returns:
            AuditStats with all metrics
        """
        # Query metrics
        total_queries = len(self.query_history)
        total_query_time = sum(q.latency_ms for q in self.query_history)
        avg_latency = total_query_time / max(total_queries, 1)

        query_types = defaultdict(int)
        for q in self.query_history:
            query_types[q.query_type] += 1

        # Cache metrics
        total_cache_ops = self._cache_hits + self._cache_misses
        cache_hit_rate = self._cache_hits / max(total_cache_ops, 1)

        # Freshness metrics
        graph_age_seconds = 0.0
        if self._last_scan_time:
            graph_age_seconds = (datetime.now() - self._last_scan_time).total_seconds()

        # Performance
        queries_per_second = 0.0
        if self.query_history:
            time_range = (self.query_history[-1].timestamp - self.query_history[0].timestamp).total_seconds()
            if time_range > 0:
                queries_per_second = total_queries / time_range

        fastest_query = min(
            (q.latency_ms for q in self.query_history),
            default=0.0,
        )
        slowest_query = max(
            (q.latency_ms for q in self.query_history),
            default=0.0,
        )

        return AuditStats(
            total_queries=total_queries,
            total_query_time_ms=total_query_time,
            avg_query_latency_ms=avg_latency,
            query_types=dict(query_types),
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
            cache_hit_rate=cache_hit_rate,
            graph_age_seconds=graph_age_seconds,
            last_scan_time=self._last_scan_time or datetime.now(),
            total_symbols=self._current_graph_stats.get("symbols", 0),
            total_dependencies=self._current_graph_stats.get("dependencies", 0),
            queries_per_second=queries_per_second,
            fastest_query_ms=fastest_query,
            slowest_query_ms=slowest_query,
        )

    def is_graph_stale(self, max_age_minutes: int = 60) -> bool:
        """
        Check if graph is stale and needs refresh.

        Args:
            max_age_minutes: Maximum age in minutes before considering stale

        Returns:
            True if graph is older than max_age_minutes
        """
        if not self._last_scan_time:
            return True

        age = datetime.now() - self._last_scan_time
        return age > timedelta(minutes=max_age_minutes)

    def get_query_performance_report(self) -> str:
        """Generate a human-readable performance report."""
        stats = self.get_stats()

        report = [
            "=" * 80,
            "MetagraphRAG Performance Report",
            "=" * 80,
            "",
            "Query Metrics:",
            f"  Total queries:      {stats.total_queries}",
            f"  Avg latency:        {stats.avg_query_latency_ms:.2f}ms",
            f"  Fastest query:      {stats.fastest_query_ms:.2f}ms",
            f"  Slowest query:      {stats.slowest_query_ms:.2f}ms",
            f"  Queries/second:     {stats.queries_per_second:.2f}",
            "",
            "Query Types:",
        ]

        for query_type, count in sorted(stats.query_types.items()):
            report.append(f"  {query_type:20s} {count:5d} queries")

        report.extend(
            [
                "",
                "Cache Performance:",
                f"  Cache hits:         {stats.cache_hits}",
                f"  Cache misses:       {stats.cache_misses}",
                f"  Hit rate:           {stats.cache_hit_rate:.1%}",
                "",
                "Graph Freshness:",
                f"  Last scan:          {stats.last_scan_time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"  Age:                {stats.graph_age_seconds / 60:.1f} minutes",
                f"  Total symbols:      {stats.total_symbols}",
                f"  Total dependencies: {stats.total_dependencies}",
                "",
                "=" * 80,
            ]
        )

        return "\n".join(report)

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        self.query_history.clear()
        self.freshness_history.clear()
        self._last_scan_time = None
        self._last_update_time = None
        self._current_graph_stats.clear()
        self._query_count = 0
        self._cache_hits = 0
        self._cache_misses = 0


# Global singleton instance
_auditor_instance: MetagraphAuditor | None = None


def get_auditor() -> MetagraphAuditor:
    """Get the global MetagraphAuditor instance."""
    global _auditor_instance
    if _auditor_instance is None:
        _auditor_instance = MetagraphAuditor()
    return _auditor_instance


def reset_auditor() -> None:
    """Reset the global auditor (for testing)."""
    global _auditor_instance
    if _auditor_instance:
        _auditor_instance.reset()
    _auditor_instance = None


@contextmanager
def track_query(query_type: str, query_target: str):
    """
    Context manager for tracking query execution time.

    Usage:
        with track_query("dependency_query", "DriverProtocol"):
            result = query_dependencies(graph, "DriverProtocol")
    """
    auditor = get_auditor()
    start_time = time.perf_counter()
    result_count = 0

    try:
        yield
    finally:
        latency_ms = (time.perf_counter() - start_time) * 1000
        auditor.track_query(
            query_type=query_type,
            query_target=query_target,
            latency_ms=latency_ms,
            result_count=result_count,
        )
