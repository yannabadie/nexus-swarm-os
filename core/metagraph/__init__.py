"""
NEXUS V12.4 COGNITIVE BOOST - MetagraphRAG with Auto-Integration

Precise codebase knowledge graph with automatic integration into NEXUS workflows.

Features:
- AST parsing of Python codebase
- In-memory dependency graph
- 3 core queries: dependencies, impact analysis, semantic search
- Self-auditing system (performance, freshness, accuracy)
- Automatic integration (auto-scan, auto-refresh, workflow helpers)

Quick Start (Automatic):
    from core.metagraph import get_graph, query_dependencies

    # Get graph (auto-scans if needed)
    graph = get_graph()

    # Query dependencies
    deps = query_dependencies(graph, "DriverProtocol")

Manual Usage:
    from core.metagraph import CodeGraph, scan_codebase

    # Build graph manually
    graph, stats = scan_codebase("core/")

Integration Helpers:
    from core.metagraph import (
        get_impact_before_edit,
        find_experts_for_file,
        check_dependency_safety,
    )

    # Impact analysis before editing
    impact = get_impact_before_edit("core/drivers/protocol.py")

    # Find symbols in file (potential experts)
    experts = find_experts_for_file("core/swarm/negotiation_protocol.py")

    # Check if modifying symbol is safe
    safety = check_dependency_safety("DriverProtocol")

Self-Auditing:
    from core.metagraph import get_auditor

    auditor = get_auditor()
    stats = auditor.get_stats()
    print(auditor.get_query_performance_report())

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2025-02-18 (POC), 2025-02-20 (Auto-Integration)
"""

# Core structures
# Parsing
from .ast_parser import extract_symbols, parse_python_file

# Self-auditing
from .auditor import (
    AuditStats,
    GraphFreshnessMetrics,
    MetagraphAuditor,
    QueryMetrics,
    get_auditor,
    reset_auditor,
    track_query,
)

# Auto-integration
from .auto_manager import (
    AutoManager,
    auto_refresh,
    check_dependency_safety,
    find_experts_for_file,
    get_graph,
    get_impact_before_edit,
    get_manager,
    get_metagraph_stats,
    is_graph_available,
    reset_manager,
)
from .code_graph import CodeGraph, Dependency, DependencyType, Symbol, SymbolType

# Queries
from .query_engine import (
    DependencyResult,
    ImpactResult,
    SearchResult,
    analyze_impact,
    query_dependencies,
    semantic_search,
)

# Scanning
from .scanner import ScanStats, scan_codebase

__all__ = [
    # Core structures
    "CodeGraph",
    "Symbol",
    "Dependency",
    "DependencyType",
    "SymbolType",
    # Parsing
    "parse_python_file",
    "extract_symbols",
    # Scanning
    "scan_codebase",
    "ScanStats",
    # Queries
    "query_dependencies",
    "analyze_impact",
    "semantic_search",
    "DependencyResult",
    "ImpactResult",
    "SearchResult",
    # Self-auditing
    "MetagraphAuditor",
    "get_auditor",
    "reset_auditor",
    "track_query",
    "AuditStats",
    "QueryMetrics",
    "GraphFreshnessMetrics",
    # Auto-integration
    "AutoManager",
    "get_manager",
    "reset_manager",
    "get_graph",
    "auto_refresh",
    "get_impact_before_edit",
    "find_experts_for_file",
    "check_dependency_safety",
    "is_graph_available",
    "get_metagraph_stats",
]

__version__ = "1.0.0"  # Auto-integration release
