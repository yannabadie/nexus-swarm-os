"""
AST Parser - Extract symbols and dependencies from Python code.

Uses Python's ast module to analyze source code structure.
Extracts:
- Classes, functions, methods
- Imports (from X import Y)
- Function calls
- Inheritance relationships
"""

from __future__ import annotations

import ast
from pathlib import Path

from .code_graph import (
    Dependency,
    DependencyType,
    Symbol,
    SymbolType,
)


class ASTSymbolExtractor(ast.NodeVisitor):
    """
    Extract symbols from Python AST.

    Visits AST nodes and collects:
    - Module-level definitions
    - Classes and methods
    - Functions
    - Imports
    """

    def __init__(self, file_path: str, module_name: str):
        self.file_path = file_path
        self.module_name = module_name
        self.symbols: list[Symbol] = []
        self.dependencies: list[Dependency] = []
        self.current_class: str | None = None
        self.current_function: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition."""
        # Create class symbol
        qualified_name = f"{self.module_name}.{node.name}"
        class_symbol = Symbol(
            name=node.name,
            qualified_name=qualified_name,
            symbol_type=SymbolType.CLASS,
            file_path=self.file_path,
            line_number=node.lineno,
            docstring=ast.get_docstring(node),
            metadata={
                "decorators": [self._get_decorator_name(d) for d in node.decorator_list],
                "bases": [self._get_base_name(b) for b in node.bases],
            },
        )
        self.symbols.append(class_symbol)

        # Handle inheritance
        for base in node.bases:
            base_name = self._get_base_name(base)
            if base_name:
                # Create dependency for inheritance
                base_symbol = Symbol(
                    name=base_name.split(".")[-1],
                    qualified_name=base_name,
                    symbol_type=SymbolType.CLASS,
                    file_path="",  # Unknown for external classes
                    line_number=0,
                )
                dep = Dependency(
                    source=class_symbol,
                    target=base_symbol,
                    dep_type=DependencyType.INHERITS,
                    file_path=self.file_path,
                    line_number=node.lineno,
                )
                self.dependencies.append(dep)

        # Visit methods
        prev_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function/method definition."""
        # Determine if method or function
        if self.current_class:
            symbol_type = SymbolType.METHOD
            qualified_name = f"{self.module_name}.{self.current_class}.{node.name}"
        else:
            symbol_type = SymbolType.FUNCTION
            qualified_name = f"{self.module_name}.{node.name}"

        # Create symbol
        func_symbol = Symbol(
            name=node.name,
            qualified_name=qualified_name,
            symbol_type=symbol_type,
            file_path=self.file_path,
            line_number=node.lineno,
            docstring=ast.get_docstring(node),
            metadata={
                "decorators": [self._get_decorator_name(d) for d in node.decorator_list],
                "args": [arg.arg for arg in node.args.args],
            },
        )
        self.symbols.append(func_symbol)

        # Visit function body to find calls (track current function scope)
        prev_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_Call(self, node: ast.Call) -> None:
        """Visit function/method call to record usage dependencies."""
        called_name = self._get_call_name(node)
        if called_name and not called_name.startswith("_"):  # Skip private/dunder
            # Determine source (current scope: function > class > module)
            if self.current_class and self.current_function:
                source_qn = f"{self.module_name}.{self.current_class}.{self.current_function}"
                source_type = SymbolType.METHOD
            elif self.current_class:
                source_qn = f"{self.module_name}.{self.current_class}"
                source_type = SymbolType.CLASS
            elif self.current_function:
                source_qn = f"{self.module_name}.{self.current_function}"
                source_type = SymbolType.FUNCTION
            else:
                source_qn = self.module_name
                source_type = SymbolType.MODULE

            source_symbol = Symbol(
                name=source_qn.split(".")[-1],
                qualified_name=source_qn,
                symbol_type=source_type,
                file_path=self.file_path,
                line_number=node.lineno,
            )

            target_symbol = Symbol(
                name=called_name.split(".")[-1],
                qualified_name=called_name,
                symbol_type=SymbolType.FUNCTION,
                file_path="",
                line_number=0,
            )

            dep = Dependency(
                source=source_symbol,
                target=target_symbol,
                dep_type=DependencyType.CALLS,
                file_path=self.file_path,
                line_number=node.lineno,
            )
            self.dependencies.append(dep)

        self.generic_visit(node)

    def _get_call_name(self, node: ast.Call) -> str | None:
        """Extract function name from a Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            # e.g., self.method() or module.func()
            parts: list[str] = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.insert(0, current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                # Skip 'self' prefix
                if current.id != "self":
                    parts.insert(0, current.id)
            return ".".join(parts) if parts else None
        return None

    def visit_Import(self, node: ast.Import) -> None:
        """Visit import statement (import X)."""
        for alias in node.names:
            imported_name = alias.name
            self._add_import_dependency(imported_name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit from-import statement (from X import Y)."""
        if node.module:
            for alias in node.names:
                if alias.name != "*":
                    imported_name = f"{node.module}.{alias.name}"
                    self._add_import_dependency(imported_name, node.lineno)

    def _add_import_dependency(self, imported_name: str, lineno: int) -> None:
        """Add import dependency."""
        # Create placeholder symbol for import source
        source_symbol = Symbol(
            name=self.module_name.split(".")[-1] if self.module_name else "unknown",
            qualified_name=self.module_name or "unknown",
            symbol_type=SymbolType.MODULE,
            file_path=self.file_path,
            line_number=1,
        )

        # Create symbol for imported item
        target_symbol = Symbol(
            name=imported_name.split(".")[-1],
            qualified_name=imported_name,
            symbol_type=SymbolType.IMPORT,
            file_path="",  # External
            line_number=0,
        )

        # Create dependency
        dep = Dependency(
            source=source_symbol,
            target=target_symbol,
            dep_type=DependencyType.IMPORTS,
            file_path=self.file_path,
            line_number=lineno,
        )
        self.dependencies.append(dep)

    def _get_decorator_name(self, node: ast.expr) -> str:
        """Extract decorator name from AST node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return node.func.id
            elif isinstance(node.func, ast.Attribute):
                return node.func.attr
        return "unknown"

    def _get_base_name(self, node: ast.expr) -> str | None:
        """Extract base class name from AST node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # Handle qualified names like abc.ABC
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.insert(0, current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.insert(0, current.id)
            return ".".join(parts)
        return None


def parse_python_file(file_path: str | Path) -> tuple[list[Symbol], list[Dependency]]:
    """
    Parse a Python file and extract symbols and dependencies.

    Args:
        file_path: Path to Python file

    Returns:
        (symbols, dependencies) tuple

    Raises:
        SyntaxError: If file has invalid Python syntax
    """
    file_path = Path(file_path)

    # Read source code
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Try latin-1 as fallback
        source = file_path.read_text(encoding="latin-1")

    # Parse AST
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in {file_path}: {e}") from None

    # Determine module name from file path
    # e.g., core/drivers/protocol.py -> core.drivers.protocol
    module_name = _path_to_module_name(file_path)

    # Extract symbols and dependencies
    extractor = ASTSymbolExtractor(str(file_path), module_name)
    extractor.visit(tree)

    return extractor.symbols, extractor.dependencies


def extract_symbols(file_path: str | Path) -> list[Symbol]:
    """
    Extract only symbols from a Python file (no dependencies).

    Convenience function for simple symbol extraction.
    """
    symbols, _ = parse_python_file(file_path)
    return symbols


def _path_to_module_name(file_path: Path) -> str:
    """
    Convert file path to Python module name.

    Examples:
        core/drivers/protocol.py -> core.drivers.protocol
        tests/test_example.py -> tests.test_example
    """
    # Remove .py extension
    parts = file_path.with_suffix("").parts

    # Find where to start (skip workspace/, if present)
    start_idx = 0
    for i, part in enumerate(parts):
        if part in ("core", "tests", "workspace"):
            start_idx = i
            break

    # Join with dots
    module_parts = parts[start_idx:]
    return ".".join(module_parts)
