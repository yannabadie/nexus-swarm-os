"""
Query Performance Tracker - Database Query Execution Metrics.

NEXUS V12.4 COGNITIVE BOOST - Tracks performance across database query operations.

This module provides centralized tracking of database query performance including
execution times, row counts, query types (SELECT/INSERT/UPDATE/DELETE), and
table-level metrics for performance analysis and bottleneck identification.

Metrics Tracked:
    - Query execution duration per table
    - Row counts per query
    - Success/failure rates per table
    - Query type distribution (SELECT, INSERT, UPDATE, DELETE)
    - Table-level aggregate profiles
    - Recent query history

Thread-Safety:
    Uses threading.Lock for all mutations. Global singleton with double-checked locking.

Usage:
    from core.infrastructure.db.query_performance_tracker import get_query_tracker

    tracker = get_query_tracker()

    # Record a query
    tracker.record_query(
        query_type="select",
        table_name="tenant",
        duration_ms=12.5,
        rows_affected=42,
        success=True,
    )

    # Query table profile
    profile = tracker.get_table_profile("tenant")
    print(f"Tenant avg duration: {profile.avg_duration_ms:.2f}ms")

    # Find slowest tables
    slowest = tracker.get_slowest_tables(limit=3)

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)

# Constants
MAX_QUERIES: int = 50000  # FIFO eviction beyond this


@dataclass
class QueryRecord:
    """
    Single database query execution record.

    Captures all metadata for one query execution including type,
    target table, duration, and row count.
    """

    query_id: str = ""
    query_type: str = ""  # select, insert, update, delete
    table_name: str = ""
    duration_ms: float = 0.0
    rows_affected: int = 0
    success: bool = True
    timestamp: str = ""  # ISO format

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


@dataclass
class TableProfile:
    """
    Aggregate metrics for a single database table.

    Computed from all queries targeting this table.
    """

    table_name: str = ""
    total_queries: int = 0
    success_count: int = 0
    total_duration_ms: float = 0.0
    total_rows: int = 0

    @property
    def success_rate(self) -> float:
        """Ratio of successful queries to total queries (0.0-1.0)."""
        if self.total_queries == 0:
            return 0.0
        return self.success_count / self.total_queries

    @property
    def avg_duration_ms(self) -> float:
        """Average query duration in milliseconds."""
        if self.total_queries == 0:
            return 0.0
        return self.total_duration_ms / self.total_queries

    @property
    def avg_rows(self) -> float:
        """Average rows affected per query."""
        if self.total_queries == 0:
            return 0.0
        return self.total_rows / self.total_queries

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with computed properties."""
        base = dataclasses.asdict(self)
        base["success_rate"] = round(self.success_rate, 4)
        base["avg_duration_ms"] = round(self.avg_duration_ms, 2)
        base["avg_rows"] = round(self.avg_rows, 2)
        return base


@dataclass
class QueryPerformanceStats:
    """
    Overall query performance statistics.

    Provides high-level summary of all tracked queries.
    """

    total_queries: int = 0
    unique_tables: int = 0
    overall_success_rate: float = 0.0
    avg_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


class QueryPerformanceTracker:
    """
    Centralized tracker for database query performance.

    Thread-safe singleton that tracks all database query executions with bounded
    history. Provides table-level profiling and performance analysis capabilities.

    Features:
        - Per-table aggregate profiling
        - Success rate and duration tracking
        - Row count statistics
        - Query type tracking (SELECT, INSERT, UPDATE, DELETE)
        - Recent query history with optional table filtering
        - Bounded FIFO history (configurable max)
        - Slowest table identification

    Thread-Safety:
        All mutations are protected by threading.Lock.
        Singleton access via get_query_tracker() with double-checked locking.
    """

    def __init__(self, max_queries: int = MAX_QUERIES):
        """
        Initialize query performance tracker.

        Args:
            max_queries: Maximum number of queries to keep in history.
                         Oldest queries are evicted when limit is reached.
        """
        self._max_queries = max_queries
        self._queries: list[QueryRecord] = []
        self._profiles: dict[str, TableProfile] = {}
        self._counter: int = 1
        self._lock = threading.Lock()

    def record_query(
        self,
        query_type: str,
        table_name: str,
        duration_ms: float = 0.0,
        rows_affected: int = 0,
        success: bool = True,
    ) -> QueryRecord:
        """
        Record a database query execution.

        Thread-safe. Updates table profile and adds to history with FIFO eviction
        if at max capacity.

        Args:
            query_type: Type of query (select, insert, update, delete)
            table_name: Target table name
            duration_ms: Query execution duration in milliseconds
            rows_affected: Number of rows affected by the query
            success: Whether the query succeeded

        Returns:
            QueryRecord: The created query record
        """
        with self._lock:
            # Generate query ID
            query_id = f"qr_{self._counter:06d}"
            self._counter += 1

            # Create query record
            record = QueryRecord(
                query_id=query_id,
                query_type=query_type,
                table_name=table_name,
                duration_ms=duration_ms,
                rows_affected=rows_affected,
                success=success,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # FIFO eviction if at capacity
            while len(self._queries) >= self._max_queries:
                self._queries.pop(0)

            # Append to history
            self._queries.append(record)

            # Update table profile
            if table_name not in self._profiles:
                self._profiles[table_name] = TableProfile(table_name=table_name)

            profile = self._profiles[table_name]
            profile.total_queries += 1
            profile.total_duration_ms += duration_ms
            profile.total_rows += rows_affected

            if success:
                profile.success_count += 1

            return record

    def get_table_profile(self, table_name: str) -> TableProfile | None:
        """
        Get the aggregate profile for a specific table.

        Args:
            table_name: Table name to query

        Returns:
            TableProfile if found, None otherwise
        """
        with self._lock:
            return self._profiles.get(table_name)

    def get_all_profiles(self) -> list[TableProfile]:
        """
        Get profiles for all tracked tables.

        Returns:
            List of TableProfile sorted by total_queries (descending)
        """
        with self._lock:
            profiles = list(self._profiles.values())
            return sorted(profiles, key=lambda p: p.total_queries, reverse=True)

    def get_slowest_tables(self, limit: int = 5) -> list[TableProfile]:
        """
        Get slowest tables by average query duration.

        Args:
            limit: Maximum number of results

        Returns:
            List of TableProfile sorted by avg_duration_ms (descending)
        """
        with self._lock:
            profiles = list(self._profiles.values())
            return sorted(profiles, key=lambda p: p.avg_duration_ms, reverse=True)[:limit]

    def get_recent_queries(
        self,
        limit: int = 10,
        table_name: str | None = None,
    ) -> list[QueryRecord]:
        """
        Get recent queries, optionally filtered by table name.

        Args:
            limit: Maximum number of queries to return
            table_name: If provided, filter to this table only

        Returns:
            List of QueryRecord (most recent first)
        """
        with self._lock:
            queries = list(self._queries)

            if table_name:
                queries = [q for q in queries if q.table_name == table_name]

            # Reverse to get most recent first
            queries.reverse()
            return queries[:limit]

    def list_tables(self) -> list[str]:
        """
        Get list of all tracked table names.

        Returns:
            List of table name strings (sorted alphabetically)
        """
        with self._lock:
            return sorted(self._profiles.keys())

    def get_stats(self) -> QueryPerformanceStats:
        """
        Get overall tracker statistics.

        Returns:
            QueryPerformanceStats with aggregate metrics
        """
        with self._lock:
            total_queries = sum(p.total_queries for p in self._profiles.values())
            total_successes = sum(p.success_count for p in self._profiles.values())
            total_duration = sum(p.total_duration_ms for p in self._profiles.values())

            overall_success_rate = 0.0
            if total_queries > 0:
                overall_success_rate = total_successes / total_queries

            avg_duration_ms = 0.0
            if total_queries > 0:
                avg_duration_ms = total_duration / total_queries

            return QueryPerformanceStats(
                total_queries=total_queries,
                unique_tables=len(self._profiles),
                overall_success_rate=overall_success_rate,
                avg_duration_ms=avg_duration_ms,
            )

    @property
    def query_count(self) -> int:
        """Total number of queries tracked."""
        with self._lock:
            return len(self._queries)

    def clear(self) -> None:
        """
        Clear all tracked data.

        Thread-safe. Resets tracker to initial state.
        """
        with self._lock:
            self._queries.clear()
            self._profiles.clear()
            self._counter = 1

    def to_dict(self) -> dict[str, Any]:
        """
        Convert tracker to dictionary representation.

        CRITICAL: Calls get_stats(), get_all_profiles(), and get_recent_queries()
        BEFORE acquiring self._lock to prevent deadlock.

        Returns:
            Dictionary with stats, profiles, and recent queries
        """
        # Get data BEFORE acquiring lock (deadlock prevention)
        stats = self.get_stats()
        all_profiles = self.get_all_profiles()
        recent = self.get_recent_queries(limit=20)

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "tables": sorted(self._profiles.keys()),
                "profiles": [p.to_dict() for p in all_profiles],
                "recent_queries": [q.to_dict() for q in recent],
                "query_count": len(self._queries),
                "max_queries": self._max_queries,
            }


# =============================================================================
# Global Singleton
# =============================================================================

_instance: QueryPerformanceTracker | None = None
_lock = threading.Lock()


def get_query_tracker() -> QueryPerformanceTracker:
    """
    Get the global QueryPerformanceTracker singleton.

    Thread-safe with double-checked locking pattern.

    Returns:
        QueryPerformanceTracker: Global singleton instance
    """
    global _instance

    # First check (without lock for performance)
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = QueryPerformanceTracker()

    return _instance


def reset_query_tracker() -> None:
    """
    Reset the global QueryPerformanceTracker singleton.

    Thread-safe. Useful for testing or reinitializing state.
    """
    global _instance

    with _lock:
        _instance = None


# Convenience exports
__all__ = [
    "QueryRecord",
    "TableProfile",
    "QueryPerformanceStats",
    "QueryPerformanceTracker",
    "get_query_tracker",
    "reset_query_tracker",
    "MAX_QUERIES",
]
