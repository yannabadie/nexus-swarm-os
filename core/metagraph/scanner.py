"""
Codebase Scanner - Build code graph by scanning Python files.

Recursively scans a directory, parses Python files, and builds a complete
dependency graph.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .ast_parser import parse_python_file
from .code_graph import CodeGraph, Dependency, Symbol

logger = logging.getLogger(__name__)


@dataclass
class ScanStats:
    """Statistics from codebase scan."""

    files_scanned: int = 0
    files_failed: int = 0
    symbols_found: int = 0
    dependencies_found: int = 0
    scan_time_ms: float = 0.0
    failed_files: list[str] = None

    def __post_init__(self):
        if self.failed_files is None:
            self.failed_files = []


def scan_codebase(
    root_path: str | Path,
    exclude_patterns: set[str] | None = None,
    include_tests: bool = False,
) -> tuple[CodeGraph, ScanStats]:
    """
    Scan a codebase and build dependency graph.

    Args:
        root_path: Root directory to scan
        exclude_patterns: File/dir patterns to exclude (e.g., {"__pycache__", ".git"})
        include_tests: Whether to include test files

    Returns:
        (graph, stats) tuple
    """
    start_time = time.monotonic()
    root_path = Path(root_path)

    # Default exclusions
    if exclude_patterns is None:
        exclude_patterns = {
            "__pycache__",
            ".git",
            ".pytest_cache",
            "venv",
            "env",
            ".venv",
            "node_modules",
            ".mypy_cache",
            ".ruff_cache",
        }

    # Find all Python files
    python_files = _find_python_files(root_path, exclude_patterns, include_tests)

    logger.info(f"Found {len(python_files)} Python files in {root_path}")

    # Build graph
    graph = CodeGraph()
    stats = ScanStats()

    for file_path in python_files:
        try:
            # Parse file
            symbols, dependencies = parse_python_file(file_path)

            # Add to graph
            for symbol in symbols:
                graph.add_symbol(symbol)

            for dep in dependencies:
                graph.add_dependency(dep)

            # Update stats
            stats.files_scanned += 1
            stats.symbols_found += len(symbols)
            stats.dependencies_found += len(dependencies)

        except Exception as e:
            logger.warning(f"Failed to parse {file_path}: {e}")
            stats.files_failed += 1
            stats.failed_files.append(str(file_path))

    # Finalize stats
    stats.scan_time_ms = (time.monotonic() - start_time) * 1000

    logger.info(
        f"Scan complete: {stats.files_scanned} files, "
        f"{stats.symbols_found} symbols, {stats.dependencies_found} dependencies "
        f"({stats.scan_time_ms:.0f}ms)"
    )

    return graph, stats


def _find_python_files(
    root_path: Path,
    exclude_patterns: set[str],
    include_tests: bool,
) -> list[Path]:
    """
    Find all Python files in directory tree.

    Args:
        root_path: Root directory
        exclude_patterns: Patterns to exclude
        include_tests: Whether to include test files

    Returns:
        List of Python file paths
    """
    python_files = []

    for path in root_path.rglob("*.py"):
        # Check exclusions
        if any(pattern in str(path) for pattern in exclude_patterns):
            continue

        # Skip test files if requested
        if not include_tests and "test" in path.name.lower():
            continue

        python_files.append(path)

    return python_files


def scan_file(file_path: str | Path) -> tuple[list[Symbol], list[Dependency]]:
    """
    Scan a single file and return symbols and dependencies.

    Convenience function for scanning individual files.
    """
    return parse_python_file(file_path)


def incremental_update(
    graph: CodeGraph,
    changed_files: list[str | Path],
) -> ScanStats:
    """
    Incrementally update graph with changed files.

    This is a simple implementation. Full version would:
    - Remove old symbols from changed files
    - Update only affected dependencies
    - Use git hooks for automatic updates

    Args:
        graph: Existing graph to update
        changed_files: List of files that changed

    Returns:
        Update statistics
    """
    start_time = time.monotonic()
    stats = ScanStats()

    for file_path in changed_files:
        try:
            file_path = Path(file_path)

            # Remove old symbols from this file
            old_symbols = graph.find_symbols_in_file(str(file_path))
            for symbol in old_symbols:
                # Remove from graph (simplified - full version needs proper cleanup)
                if symbol.qualified_name in graph.symbols:
                    del graph.symbols[symbol.qualified_name]

            # Parse file again
            symbols, dependencies = parse_python_file(file_path)

            # Add to graph
            for symbol in symbols:
                graph.add_symbol(symbol)

            for dep in dependencies:
                graph.add_dependency(dep)

            stats.files_scanned += 1
            stats.symbols_found += len(symbols)
            stats.dependencies_found += len(dependencies)

        except Exception as e:
            logger.warning(f"Failed to update {file_path}: {e}")
            stats.files_failed += 1
            stats.failed_files.append(str(file_path))

    stats.scan_time_ms = (time.monotonic() - start_time) * 1000
    return stats
