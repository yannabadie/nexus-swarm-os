"""Tests for MetagraphRAG AST parser - visit_Call and dependency tracking."""

from __future__ import annotations

import ast
import textwrap

import pytest

from core.metagraph.ast_parser import ASTSymbolExtractor, parse_python_file
from core.metagraph.code_graph import (
    CodeGraph,
    Dependency,
    DependencyType,
    Symbol,
    SymbolType,
)
from core.metagraph.query_engine import analyze_impact, query_dependencies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract(source: str, module: str = "test_mod") -> ASTSymbolExtractor:
    """Parse source string and return the extractor with results."""
    tree = ast.parse(textwrap.dedent(source))
    ext = ASTSymbolExtractor(file_path="test.py", module_name=module)
    ext.visit(tree)
    return ext


def _dep_types(ext: ASTSymbolExtractor) -> list[DependencyType]:
    """Return list of dependency types found."""
    return [d.dep_type for d in ext.dependencies]


def _call_targets(ext: ASTSymbolExtractor) -> list[str]:
    """Return qualified names of CALLS targets."""
    return [
        d.target.qualified_name
        for d in ext.dependencies
        if d.dep_type == DependencyType.CALLS
    ]


# ---------------------------------------------------------------------------
# visit_Call tests
# ---------------------------------------------------------------------------

class TestVisitCall:
    """Tests for the new visit_Call method."""

    def test_simple_function_call(self):
        ext = _extract("""
            def foo():
                bar()
        """)
        targets = _call_targets(ext)
        assert "bar" in targets

    def test_method_call_on_object(self):
        ext = _extract("""
            def foo():
                obj.method()
        """)
        targets = _call_targets(ext)
        assert "obj.method" in targets

    def test_chained_attribute_call(self):
        ext = _extract("""
            def foo():
                a.b.c()
        """)
        targets = _call_targets(ext)
        assert "a.b.c" in targets

    def test_self_method_call_strips_self(self):
        """self.method() should record 'method', not 'self.method'."""
        ext = _extract("""
            class MyClass:
                def do_thing(self):
                    self.helper()
        """)
        targets = _call_targets(ext)
        assert "helper" in targets
        assert "self.helper" not in targets

    def test_private_calls_skipped(self):
        """Calls to private functions (starting with _) should be skipped."""
        ext = _extract("""
            def foo():
                _private()
                __dunder__()
                public()
        """)
        targets = _call_targets(ext)
        assert "public" in targets
        assert "_private" not in targets
        assert "__dunder__" not in targets

    def test_call_inside_class_method_has_correct_source(self):
        """Source of a call inside a method should be Class.method."""
        ext = _extract("""
            class Foo:
                def bar(self):
                    baz()
        """)
        calls = [d for d in ext.dependencies if d.dep_type == DependencyType.CALLS]
        assert len(calls) >= 1
        call = calls[0]
        assert call.source.qualified_name == "test_mod.Foo.bar"
        assert call.source.symbol_type == SymbolType.METHOD

    def test_call_inside_standalone_function_has_correct_source(self):
        """Source of a call inside a module function should be module.func."""
        ext = _extract("""
            def runner():
                helper()
        """)
        calls = [d for d in ext.dependencies if d.dep_type == DependencyType.CALLS]
        assert len(calls) >= 1
        assert calls[0].source.qualified_name == "test_mod.runner"
        assert calls[0].source.symbol_type == SymbolType.FUNCTION

    def test_call_at_module_level_has_module_source(self):
        """Calls at module level should have module as source."""
        ext = _extract("""
            setup()
        """)
        calls = [d for d in ext.dependencies if d.dep_type == DependencyType.CALLS]
        assert len(calls) >= 1
        assert calls[0].source.qualified_name == "test_mod"
        assert calls[0].source.symbol_type == SymbolType.MODULE

    def test_nested_calls_both_recorded(self):
        """Both outer and inner calls should be recorded."""
        ext = _extract("""
            def foo():
                outer(inner())
        """)
        targets = _call_targets(ext)
        assert "outer" in targets
        assert "inner" in targets

    def test_generic_visit_continues(self):
        """visit_Call should call generic_visit so nested structures are visited."""
        ext = _extract("""
            def foo():
                result = [bar(x) for x in baz()]
        """)
        targets = _call_targets(ext)
        assert "bar" in targets
        assert "baz" in targets


# ---------------------------------------------------------------------------
# Function scope tracking tests
# ---------------------------------------------------------------------------

class TestFunctionScope:
    """Tests for current_function tracking."""

    def test_current_function_set_in_function(self):
        """current_function should be set when visiting function body."""
        ext = _extract("""
            def my_func():
                do_work()
        """)
        calls = [d for d in ext.dependencies if d.dep_type == DependencyType.CALLS]
        assert any(
            d.source.qualified_name == "test_mod.my_func"
            for d in calls
        )

    def test_current_function_restored_after_function(self):
        """current_function should be restored after visiting a function."""
        ext = _extract("""
            def first():
                call_a()

            def second():
                call_b()
        """)
        calls = [d for d in ext.dependencies if d.dep_type == DependencyType.CALLS]
        sources = {d.target.qualified_name: d.source.qualified_name for d in calls}
        assert sources.get("call_a") == "test_mod.first"
        assert sources.get("call_b") == "test_mod.second"

    def test_method_scope_includes_class_and_function(self):
        """Inside a method, source should be module.Class.method."""
        ext = _extract("""
            class Engine:
                def start(self):
                    ignite()
        """)
        calls = [d for d in ext.dependencies if d.dep_type == DependencyType.CALLS]
        assert calls[0].source.qualified_name == "test_mod.Engine.start"


# ---------------------------------------------------------------------------
# _get_call_name tests
# ---------------------------------------------------------------------------

class TestGetCallName:
    """Tests for _get_call_name helper."""

    def test_simple_name(self):
        ext = ASTSymbolExtractor("test.py", "mod")
        node = ast.parse("foo()").body[0].value
        assert ext._get_call_name(node) == "foo"

    def test_attribute_name(self):
        ext = ASTSymbolExtractor("test.py", "mod")
        node = ast.parse("obj.method()").body[0].value
        assert ext._get_call_name(node) == "obj.method"

    def test_self_stripped(self):
        ext = ASTSymbolExtractor("test.py", "mod")
        node = ast.parse("self.run()").body[0].value
        assert ext._get_call_name(node) == "run"

    def test_deep_chain(self):
        ext = ASTSymbolExtractor("test.py", "mod")
        node = ast.parse("a.b.c.d()").body[0].value
        assert ext._get_call_name(node) == "a.b.c.d"

    def test_subscript_call_returns_none(self):
        """foo[0]() should return None (subscript, not Name/Attribute)."""
        ext = ASTSymbolExtractor("test.py", "mod")
        node = ast.parse("foo[0]()").body[0].value
        assert ext._get_call_name(node) is None


# ---------------------------------------------------------------------------
# Path normalization tests
# ---------------------------------------------------------------------------

class TestPathNormalization:
    """Tests for Windows path separator handling."""

    def test_find_symbols_forward_slash(self):
        graph = CodeGraph()
        sym = Symbol(
            name="Foo",
            qualified_name="mod.Foo",
            symbol_type=SymbolType.CLASS,
            file_path="core\\drivers\\protocol.py",
            line_number=1,
        )
        graph.add_symbol(sym)

        # Query with forward slashes should find it
        result = graph.find_symbols_in_file("core/drivers/protocol.py")
        assert len(result) == 1
        assert result[0].name == "Foo"

    def test_find_symbols_backslash(self):
        graph = CodeGraph()
        sym = Symbol(
            name="Bar",
            qualified_name="mod.Bar",
            symbol_type=SymbolType.CLASS,
            file_path="core/drivers/protocol.py",
            line_number=1,
        )
        graph.add_symbol(sym)

        # Query with backslashes should find it
        result = graph.find_symbols_in_file("core\\drivers\\protocol.py")
        assert len(result) == 1
        assert result[0].name == "Bar"

    def test_find_symbols_same_separator(self):
        graph = CodeGraph()
        sym = Symbol(
            name="Baz",
            qualified_name="mod.Baz",
            symbol_type=SymbolType.CLASS,
            file_path="core/config.py",
            line_number=1,
        )
        graph.add_symbol(sym)

        result = graph.find_symbols_in_file("core/config.py")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Query engine phantom symbol resolution tests
# ---------------------------------------------------------------------------

class TestPhantomSymbolResolution:
    """Tests that query_dependencies prefers real symbols over phantoms."""

    def test_prefers_real_over_phantom(self):
        graph = CodeGraph()

        # Add a real symbol
        real = Symbol(
            name="Foo",
            qualified_name="mod.Foo",
            symbol_type=SymbolType.CLASS,
            file_path="mod.py",
            line_number=10,
        )
        graph.add_symbol(real)

        # Add a phantom (from a CALLS target)
        phantom = Symbol(
            name="Foo",
            qualified_name="Foo",
            symbol_type=SymbolType.FUNCTION,
            file_path="",
            line_number=0,
        )
        graph.add_symbol(phantom)

        # Add a dependency from real symbol
        dep = Dependency(
            source=real,
            target=Symbol(
                name="helper",
                qualified_name="helper",
                symbol_type=SymbolType.FUNCTION,
                file_path="",
                line_number=0,
            ),
            dep_type=DependencyType.CALLS,
            file_path="mod.py",
            line_number=15,
        )
        graph.add_dependency(dep)

        # Query by simple name should pick the real symbol
        result = query_dependencies(graph, "Foo")
        assert result is not None
        assert result.symbol.qualified_name == "mod.Foo"
        assert result.symbol.file_path == "mod.py"
        assert len(result.direct_dependencies) == 1


# ---------------------------------------------------------------------------
# Integration: DependencyType.CALLS enum exists
# ---------------------------------------------------------------------------

class TestDependencyTypeEnum:
    """Verify CALLS enum member exists."""

    def test_calls_exists(self):
        assert hasattr(DependencyType, "CALLS")
        assert DependencyType.CALLS.value == "calls"

    def test_all_expected_types(self):
        expected = {"imports", "calls", "inherits", "uses", "defines", "contains"}
        actual = {dt.value for dt in DependencyType}
        assert expected == actual
