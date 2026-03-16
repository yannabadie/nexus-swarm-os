"""
MetagraphRAG Automatic Integration Manager

Handles automatic codebase scanning, graph refreshing, and integration
with NEXUS workflows.

Features:
- Auto-scan on startup (configurable)
- Incremental updates on file changes
- Helper functions for common patterns
- Integration with orchestrator, swarm, evolution

Usage:
    from core.metagraph.auto_manager import get_graph, auto_refresh

    # Get current graph (auto-scans if needed)
    graph = get_graph()

    # Query dependencies
    from core.metagraph import query_dependencies
    result = query_dependencies(graph, "DriverProtocol")

    # Auto-refresh after file changes
    auto_refresh(changed_files=["core/drivers/protocol.py"])
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from .auditor import get_auditor
from .code_graph import CodeGraph
from .scanner import ScanStats, scan_codebase


class AutoManager:
    """
    Automatic integration manager for MetagraphRAG.

    Handles:
    - Auto-scanning on first use
    - Incremental updates
    - Graph caching
    - Integration helpers
    """

    def __init__(self):
        self._graph: CodeGraph | None = None
        self._last_scan_time: datetime | None = None
        self._scan_stats: ScanStats | None = None

        # Configuration (from env or defaults)
        self._auto_scan_enabled = os.getenv("METAGRAPH_AUTO_SCAN", "true").lower() == "true"
        self._scan_root = Path(os.getenv("METAGRAPH_SCAN_ROOT", "core"))
        self._max_age_minutes = int(os.getenv("METAGRAPH_MAX_AGE_MINUTES", "60"))
        self._include_tests = os.getenv("METAGRAPH_INCLUDE_TESTS", "false").lower() == "true"

        # Auditor integration
        self.auditor = get_auditor()

    def get_graph(self, force_refresh: bool = False) -> CodeGraph:
        """
        Get current code graph, scanning if needed.

        Args:
            force_refresh: Force a full rescan even if graph exists

        Returns:
            CodeGraph instance (cached or freshly scanned)
        """
        # Check if we need to scan
        needs_scan = force_refresh or self._graph is None or self._is_stale()

        if needs_scan and self._auto_scan_enabled:
            self._perform_full_scan()
        elif self._graph is None:
            # Auto-scan disabled but graph doesn't exist
            # Create empty graph
            self._graph = CodeGraph()

        return self._graph

    def auto_refresh(self, changed_files: list[str]) -> None:
        """
        Incrementally update graph for changed files.

        For now, this triggers a full rescan. Future optimization:
        parse only changed files and update graph incrementally.

        Args:
            changed_files: List of file paths that changed
        """
        if not self._auto_scan_enabled:
            return

        # Filter for Python files
        py_files = [f for f in changed_files if f.endswith(".py")]

        if not py_files:
            return

        # For POC: full rescan (future: incremental update)
        self._perform_full_scan()

        # Track update
        self.auditor.track_update(
            updated_files=set(py_files),
            graph_stats=self._graph.stats() if self._graph else {},
        )

    def is_available(self) -> bool:
        """Check if graph is available and fresh."""
        return self._graph is not None and not self._is_stale()

    def get_impact_before_edit(self, file_path: str) -> dict:
        """
        Get impact analysis before editing a file.

        Useful for orchestrator to warn about high-impact changes.

        Args:
            file_path: Path to file being edited

        Returns:
            Dict with impact metrics:
            - affected_files: List[str]
            - impact_score: float (0-1)
            - symbols_affected: int
        """
        from .query_engine import analyze_impact

        graph = self.get_graph()
        result = analyze_impact(graph, file_path)

        return {
            "affected_files": sorted(result.affected_files),
            "impact_score": result.impact_score,
            "symbols_affected": len(result.affected_symbols),
            "direct_dependents": len(result.direct_dependents),
            "transitive_dependents": len(result.transitive_dependents),
        }

    def find_experts_for_file(self, file_path: str) -> list[str]:
        """
        Find symbols/classes in a file (potential experts).

        Useful for swarm mode to identify which agent should handle
        modifications to this file based on historical success.

        Args:
            file_path: Path to file

        Returns:
            List of symbol names in the file
        """
        graph = self.get_graph()
        symbols = graph.find_symbols_in_file(file_path)

        return [sym.name for sym in symbols]

    def check_dependency_safety(self, symbol_name: str) -> dict:
        """
        Check if modifying a symbol is safe.

        Args:
            symbol_name: Symbol to check

        Returns:
            Dict with safety metrics:
            - is_safe: bool (has few dependents)
            - dependent_count: int
            - risk_level: str (low/medium/high)
        """
        from .query_engine import query_dependencies

        graph = self.get_graph()
        result = query_dependencies(graph, symbol_name)

        if not result:
            return {
                "is_safe": True,
                "dependent_count": 0,
                "risk_level": "unknown",
                "reason": "Symbol not found",
            }

        dep_count = len(result.transitive_dependencies)

        # Risk thresholds
        if dep_count == 0 or dep_count < 10:
            risk_level = "low"
            is_safe = True
        elif dep_count < 50:
            risk_level = "medium"
            is_safe = False
        else:
            risk_level = "high"
            is_safe = False

        return {
            "is_safe": is_safe,
            "dependent_count": dep_count,
            "risk_level": risk_level,
            "reason": f"{dep_count} transitive dependencies",
        }

    def get_stats(self) -> dict:
        """Get manager statistics."""
        graph_stats = self._graph.stats() if self._graph else {}

        return {
            "graph_available": self._graph is not None,
            "last_scan_time": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "graph_age_minutes": self._get_age_minutes(),
            "is_stale": self._is_stale(),
            "auto_scan_enabled": self._auto_scan_enabled,
            "scan_root": str(self._scan_root),
            **graph_stats,
        }

    def _perform_full_scan(self) -> None:
        """Perform a full codebase scan."""
        start_time = time.perf_counter()

        # Scan codebase
        self._graph, self._scan_stats = scan_codebase(
            root_path=self._scan_root,
            include_tests=self._include_tests,
        )

        self._last_scan_time = datetime.now()

        scan_duration_ms = (time.perf_counter() - start_time) * 1000

        # Track in auditor
        self.auditor.track_scan(
            scan_duration_ms=scan_duration_ms,
            files_scanned=self._scan_stats.files_scanned,
            files_failed=self._scan_stats.files_failed,
            graph_stats=self._graph.stats(),
        )

    def _is_stale(self) -> bool:
        """Check if graph is stale."""
        if not self._last_scan_time:
            return True

        age = datetime.now() - self._last_scan_time
        return age > timedelta(minutes=self._max_age_minutes)

    def _get_age_minutes(self) -> float:
        """Get graph age in minutes."""
        if not self._last_scan_time:
            return float("inf")

        age = datetime.now() - self._last_scan_time
        return age.total_seconds() / 60


# Global singleton
_manager_instance: AutoManager | None = None


def get_manager() -> AutoManager:
    """Get the global AutoManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AutoManager()
    return _manager_instance


def reset_manager() -> None:
    """Reset the global manager (for testing)."""
    global _manager_instance
    _manager_instance = None


# Convenience functions


def get_graph(force_refresh: bool = False) -> CodeGraph:
    """
    Get current code graph (auto-scans if needed).

    Args:
        force_refresh: Force a full rescan

    Returns:
        CodeGraph instance
    """
    return get_manager().get_graph(force_refresh=force_refresh)


def auto_refresh(changed_files: list[str]) -> None:
    """
    Auto-refresh graph after file changes.

    Args:
        changed_files: List of file paths that changed
    """
    get_manager().auto_refresh(changed_files)


def get_impact_before_edit(file_path: str) -> dict:
    """
    Get impact analysis before editing a file.

    Args:
        file_path: Path to file

    Returns:
        Impact metrics dict
    """
    return get_manager().get_impact_before_edit(file_path)


def find_experts_for_file(file_path: str) -> list[str]:
    """
    Find symbols in a file (potential experts).

    Args:
        file_path: Path to file

    Returns:
        List of symbol names
    """
    return get_manager().find_experts_for_file(file_path)


def check_dependency_safety(symbol_name: str) -> dict:
    """
    Check if modifying a symbol is safe.

    Args:
        symbol_name: Symbol to check

    Returns:
        Safety metrics dict
    """
    return get_manager().check_dependency_safety(symbol_name)


def is_graph_available() -> bool:
    """Check if graph is available and fresh."""
    return get_manager().is_available()


def get_metagraph_stats() -> dict:
    """Get MetagraphRAG statistics."""
    manager_stats = get_manager().get_stats()
    audit_stats = get_auditor().get_stats()

    return {
        **manager_stats,
        "query_metrics": {
            "total_queries": audit_stats.total_queries,
            "avg_latency_ms": audit_stats.avg_query_latency_ms,
            "cache_hit_rate": audit_stats.cache_hit_rate,
        },
    }
