"""
Code Graph - In-memory dependency graph for Python codebase.

Represents code structure as a directed graph:
- Nodes: Symbols (classes, functions, variables, modules)
- Edges: Dependencies (imports, calls, inheritance, usage)

This is a POC implementation using dicts. Full version will use Neo4j.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SymbolType(Enum):
    """Type of code symbol."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"


class DependencyType(Enum):
    """Type of dependency relationship."""

    IMPORTS = "imports"  # A imports B
    CALLS = "calls"  # A calls B
    INHERITS = "inherits"  # A inherits from B
    USES = "uses"  # A uses B (generic)
    DEFINES = "defines"  # Module defines Class/Function
    CONTAINS = "contains"  # Class contains Method


@dataclass
class Symbol:
    """
    Code symbol (class, function, module, etc.).

    Attributes:
        name: Symbol name (e.g., "DriverProtocol")
        qualified_name: Full qualified name (e.g., "core.drivers.protocol.DriverProtocol")
        symbol_type: Type of symbol (class, function, etc.)
        file_path: Path to file containing this symbol
        line_number: Line number where symbol is defined
        docstring: Symbol's docstring (if any)
        metadata: Additional metadata (decorators, params, etc.)
    """

    name: str
    qualified_name: str
    symbol_type: SymbolType
    file_path: str
    line_number: int
    docstring: str | None = None
    metadata: dict[str, any] = field(default_factory=dict)

    def __hash__(self):
        return hash(self.qualified_name)

    def __eq__(self, other):
        if not isinstance(other, Symbol):
            return False
        return self.qualified_name == other.qualified_name


@dataclass
class Dependency:
    """
    Dependency relationship between symbols.

    Attributes:
        source: Symbol that depends on target
        target: Symbol being depended on
        dep_type: Type of dependency
        file_path: File where dependency occurs
        line_number: Line where dependency occurs
    """

    source: Symbol
    target: Symbol
    dep_type: DependencyType
    file_path: str
    line_number: int

    def __hash__(self):
        return hash((self.source, self.target, self.dep_type))


class CodeGraph:
    """
    In-memory code dependency graph.

    POC implementation using dicts. Full version will use Neo4j for:
    - Persistent storage
    - Complex graph queries (Cypher)
    - Scalability (millions of nodes)

    Current structure:
    - symbols: {qualified_name -> Symbol}
    - dependencies: {source_name -> [Dependency]}
    - reverse_deps: {target_name -> [Dependency]} (for impact analysis)
    """

    def __init__(self):
        self.symbols: dict[str, Symbol] = {}
        self.dependencies: dict[str, list[Dependency]] = {}
        self.reverse_deps: dict[str, list[Dependency]] = {}

    def add_symbol(self, symbol: Symbol) -> None:
        """Add symbol to graph."""
        self.symbols[symbol.qualified_name] = symbol
        if symbol.qualified_name not in self.dependencies:
            self.dependencies[symbol.qualified_name] = []
        if symbol.qualified_name not in self.reverse_deps:
            self.reverse_deps[symbol.qualified_name] = []

    def add_dependency(self, dep: Dependency) -> None:
        """Add dependency edge to graph."""
        source_name = dep.source.qualified_name
        target_name = dep.target.qualified_name

        # Ensure symbols exist
        if source_name not in self.symbols:
            self.add_symbol(dep.source)
        if target_name not in self.symbols:
            self.add_symbol(dep.target)

        # Add forward dependency
        if source_name not in self.dependencies:
            self.dependencies[source_name] = []
        self.dependencies[source_name].append(dep)

        # Add reverse dependency (for impact analysis)
        if target_name not in self.reverse_deps:
            self.reverse_deps[target_name] = []
        self.reverse_deps[target_name].append(dep)

    def get_symbol(self, qualified_name: str) -> Symbol | None:
        """Get symbol by qualified name."""
        return self.symbols.get(qualified_name)

    def get_dependencies(self, qualified_name: str) -> list[Dependency]:
        """Get all dependencies of a symbol (what it depends on)."""
        return self.dependencies.get(qualified_name, [])

    def get_dependents(self, qualified_name: str) -> list[Dependency]:
        """Get all dependents of a symbol (what depends on it)."""
        return self.reverse_deps.get(qualified_name, [])

    def find_symbols_by_name(self, name: str) -> list[Symbol]:
        """Find all symbols with given name (unqualified)."""
        return [sym for sym in self.symbols.values() if sym.name == name]

    def find_symbols_by_type(self, symbol_type: SymbolType) -> list[Symbol]:
        """Find all symbols of given type."""
        return [sym for sym in self.symbols.values() if sym.symbol_type == symbol_type]

    def find_symbols_in_file(self, file_path: str) -> list[Symbol]:
        """Find all symbols defined in a file."""
        return [sym for sym in self.symbols.values() if sym.file_path == file_path]

    def get_transitive_dependencies(
        self,
        qualified_name: str,
        max_depth: int = 10,
    ) -> set[Symbol]:
        """
        Get transitive dependencies (all symbols reachable from this one).

        Uses BFS to traverse dependency graph up to max_depth.
        """
        visited = set()
        queue = [(qualified_name, 0)]

        while queue:
            current_name, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            if current_name in visited:
                continue

            visited.add(current_name)

            # Add dependencies to queue
            for dep in self.get_dependencies(current_name):
                target_name = dep.target.qualified_name
                if target_name not in visited:
                    queue.append((target_name, depth + 1))

        # Convert names to symbols
        return {self.symbols[name] for name in visited if name in self.symbols and name != qualified_name}

    def get_transitive_dependents(
        self,
        qualified_name: str,
        max_depth: int = 10,
    ) -> set[Symbol]:
        """
        Get transitive dependents (all symbols that depend on this one).

        Uses BFS to traverse reverse dependency graph up to max_depth.
        """
        visited = set()
        queue = [(qualified_name, 0)]

        while queue:
            current_name, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            if current_name in visited:
                continue

            visited.add(current_name)

            # Add dependents to queue
            for dep in self.get_dependents(current_name):
                source_name = dep.source.qualified_name
                if source_name not in visited:
                    queue.append((source_name, depth + 1))

        # Convert names to symbols
        return {self.symbols[name] for name in visited if name in self.symbols and name != qualified_name}

    def stats(self) -> dict[str, int]:
        """Get graph statistics."""
        total_deps = sum(len(deps) for deps in self.dependencies.values())

        return {
            "symbols": len(self.symbols),
            "dependencies": total_deps,
            "modules": len(self.find_symbols_by_type(SymbolType.MODULE)),
            "classes": len(self.find_symbols_by_type(SymbolType.CLASS)),
            "functions": len(self.find_symbols_by_type(SymbolType.FUNCTION)),
            "methods": len(self.find_symbols_by_type(SymbolType.METHOD)),
        }

    def __repr__(self) -> str:
        stats = self.stats()
        return (
            f"CodeGraph("
            f"symbols={stats['symbols']}, "
            f"dependencies={stats['dependencies']}, "
            f"classes={stats['classes']}, "
            f"functions={stats['functions']})"
        )
