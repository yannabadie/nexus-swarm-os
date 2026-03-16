"""
Query Engine - Query the code dependency graph.

Provides 3 core queries:
1. query_dependencies() - Find what a symbol depends on
2. analyze_impact() - Find what would be affected by changing a file
3. semantic_search() - Search symbols by text/docstring
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .code_graph import CodeGraph, Dependency, Symbol, SymbolType


@dataclass
class DependencyResult:
    """Result of dependency query."""

    symbol: Symbol
    direct_dependencies: list[Dependency]
    transitive_dependencies: set[Symbol]
    dependency_depth: int

    def __repr__(self) -> str:
        return (
            f"DependencyResult({self.symbol.name}, "
            f"direct={len(self.direct_dependencies)}, "
            f"transitive={len(self.transitive_dependencies)})"
        )


@dataclass
class ImpactResult:
    """Result of impact analysis."""

    file_path: str
    affected_symbols: list[Symbol]
    direct_dependents: list[Dependency]
    transitive_dependents: set[Symbol]
    affected_files: set[str]
    impact_score: float  # 0-1, higher = more impact

    def __repr__(self) -> str:
        return (
            f"ImpactResult({self.file_path}, "
            f"symbols={len(self.affected_symbols)}, "
            f"files={len(self.affected_files)}, "
            f"score={self.impact_score:.2f})"
        )


@dataclass
class SearchResult:
    """Result of semantic search."""

    symbol: Symbol
    score: float  # 0-1, higher = better match
    match_reason: str  # Why this matched (name, docstring, etc.)

    def __repr__(self) -> str:
        return f"SearchResult({self.symbol.name}, score={self.score:.2f})"


def query_dependencies(
    graph: CodeGraph,
    symbol_name: str,
    max_depth: int = 10,
) -> DependencyResult | None:
    """
    Query what a symbol depends on.

    Args:
        graph: Code graph
        symbol_name: Symbol to query (qualified name or simple name)
        max_depth: Maximum transitive dependency depth

    Returns:
        DependencyResult with direct and transitive dependencies

    Example:
        >>> result = query_dependencies(graph, "DriverProtocol")
        >>> print(f"DriverProtocol depends on {len(result.transitive_dependencies)} symbols")
    """
    # Find symbol (try qualified name first, then simple name)
    symbol = graph.get_symbol(symbol_name)

    # If exact match is a phantom target (no file_path), try simple name search
    if symbol and not symbol.file_path:
        matches = graph.find_symbols_by_name(symbol_name)
        real_matches = [m for m in matches if m.file_path]
        if real_matches:
            symbol = real_matches[0]

    if not symbol:
        # Try finding by simple name
        matches = graph.find_symbols_by_name(symbol_name)
        if not matches:
            return None
        # Prefer symbols with actual file paths (skip phantom target symbols)
        real_matches = [m for m in matches if m.file_path]
        symbol = real_matches[0] if real_matches else matches[0]

    # Get direct dependencies
    direct_deps = graph.get_dependencies(symbol.qualified_name)

    # Get transitive dependencies
    transitive_deps = graph.get_transitive_dependencies(
        symbol.qualified_name,
        max_depth=max_depth,
    )

    # Calculate depth
    depth = _calculate_max_depth(graph, symbol.qualified_name, max_depth)

    return DependencyResult(
        symbol=symbol,
        direct_dependencies=direct_deps,
        transitive_dependencies=transitive_deps,
        dependency_depth=depth,
    )


def analyze_impact(
    graph: CodeGraph,
    file_path: str,
    max_depth: int = 10,
) -> ImpactResult:
    """
    Analyze impact of changing a file.

    Answers: "If I modify this file, what else is affected?"

    Args:
        graph: Code graph
        file_path: Path to file being changed
        max_depth: Maximum transitive dependent depth

    Returns:
        ImpactResult with affected symbols and files

    Example:
        >>> result = analyze_impact(graph, "core/drivers/protocol.py")
        >>> print(f"Changing protocol.py affects {len(result.affected_files)} files")
        >>> for file in sorted(result.affected_files):
        ...     print(f"  - {file}")
    """
    # Find all symbols in this file
    affected_symbols = graph.find_symbols_in_file(file_path)

    if not affected_symbols:
        return ImpactResult(
            file_path=file_path,
            affected_symbols=[],
            direct_dependents=[],
            transitive_dependents=set(),
            affected_files=set(),
            impact_score=0.0,
        )

    # Collect all dependents
    all_direct_deps = []
    all_transitive_deps = set()

    for symbol in affected_symbols:
        # Direct dependents
        direct_deps = graph.get_dependents(symbol.qualified_name)
        all_direct_deps.extend(direct_deps)

        # Transitive dependents
        transitive_deps = graph.get_transitive_dependents(
            symbol.qualified_name,
            max_depth=max_depth,
        )
        all_transitive_deps.update(transitive_deps)

    # Extract affected files (normalize paths for cross-platform comparison)
    normalized_input = file_path.replace("\\", "/")
    affected_files = {
        dep.source.file_path.replace("\\", "/")
        for dep in all_direct_deps if dep.source.file_path
    }
    affected_files.update(
        sym.file_path.replace("\\", "/")
        for sym in all_transitive_deps if sym.file_path
    )

    # Remove the file itself
    affected_files.discard(normalized_input)

    # Calculate impact score (0-1, higher = more impact)
    impact_score = _calculate_impact_score(
        len(affected_symbols),
        len(all_direct_deps),
        len(all_transitive_deps),
        len(affected_files),
    )

    return ImpactResult(
        file_path=file_path,
        affected_symbols=affected_symbols,
        direct_dependents=all_direct_deps,
        transitive_dependents=all_transitive_deps,
        affected_files=affected_files,
        impact_score=impact_score,
    )


def semantic_search(
    graph: CodeGraph,
    query: str,
    symbol_types: list[SymbolType] | None = None,
    limit: int = 10,
) -> list[SearchResult]:
    """
    Search for symbols by text query.

    Searches in:
    - Symbol name
    - Qualified name
    - Docstring
    - File path

    Args:
        graph: Code graph
        query: Search query (supports regex)
        symbol_types: Filter by symbol types (None = all types)
        limit: Maximum results to return

    Returns:
        List of SearchResult sorted by score (best first)

    Example:
        >>> results = semantic_search(graph, "driver.*protocol")
        >>> for result in results:
        ...     print(f"{result.symbol.name} - {result.match_reason}")
    """
    # Compile query as regex (case-insensitive)
    try:
        query_re = re.compile(query, re.IGNORECASE)
    except re.error:
        # If not valid regex, escape and use as literal
        query_re = re.compile(re.escape(query), re.IGNORECASE)

    results = []

    for symbol in graph.symbols.values():
        # Filter by type if requested
        if symbol_types and symbol.symbol_type not in symbol_types:
            continue

        # Check matches
        score = 0.0
        match_reasons = []

        # Name match (highest weight)
        if query_re.search(symbol.name):
            score += 0.5
            match_reasons.append("name")

        # Qualified name match
        if query_re.search(symbol.qualified_name):
            score += 0.3
            match_reasons.append("qualified_name")

        # Docstring match
        if symbol.docstring and query_re.search(symbol.docstring):
            score += 0.2
            match_reasons.append("docstring")

        # File path match
        if query_re.search(symbol.file_path):
            score += 0.1
            match_reasons.append("file_path")

        # If any match, add to results
        if score > 0:
            results.append(
                SearchResult(
                    symbol=symbol,
                    score=score,
                    match_reason=", ".join(match_reasons),
                )
            )

    # Sort by score (descending) and limit
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _calculate_max_depth(graph: CodeGraph, qualified_name: str, max_depth: int) -> int:
    """Calculate actual maximum dependency depth (BFS)."""
    visited = set()
    queue = [(qualified_name, 0)]
    max_found = 0

    while queue:
        current_name, depth = queue.pop(0)

        if depth >= max_depth or current_name in visited:
            continue

        visited.add(current_name)
        max_found = max(max_found, depth)

        for dep in graph.get_dependencies(current_name):
            queue.append((dep.target.qualified_name, depth + 1))

    return max_found


def _calculate_impact_score(
    num_symbols: int,
    num_direct_deps: int,
    num_transitive_deps: int,
    num_files: int,
) -> float:
    """
    Calculate impact score (0-1).

    Formula (heuristic):
    - 0.3 weight for number of symbols in file
    - 0.2 weight for direct dependents
    - 0.3 weight for transitive dependents
    - 0.2 weight for affected files

    Normalized to [0, 1] using log scale to handle large numbers.
    """
    import math

    # Log scale to handle large numbers
    log_symbols = math.log1p(num_symbols)
    log_direct = math.log1p(num_direct_deps)
    log_transitive = math.log1p(num_transitive_deps)
    log_files = math.log1p(num_files)

    # Weighted sum
    raw_score = 0.3 * log_symbols + 0.2 * log_direct + 0.3 * log_transitive + 0.2 * log_files

    # Normalize to [0, 1] (assume max ~10.0 for very high impact)
    normalized = min(raw_score / 10.0, 1.0)

    return normalized
