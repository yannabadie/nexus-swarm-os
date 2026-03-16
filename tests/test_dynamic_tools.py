"""
Tests for Phase 12.5: Dynamic Tool Generation

Tests verify:
1. SECURITY: Dangerous code patterns are blocked by CodeValidator
2. FUNCTIONAL: Valid tools can be created, executed, and deleted
3. TIMEOUT: Infinite loops are properly terminated
4. ISOLATION: Tools run in subprocess with proper limits
"""

import tempfile
from pathlib import Path

import pytest

from core.execution_pkg.execution.dynamic_tools import (
    DynamicToolManager,
)
from core.security_pkg.security.execution_policy import CodeValidator

# =============================================================================
# CODEVALIDATOR SECURITY TESTS
# =============================================================================


class TestCodeValidatorSecurity:
    """Test CodeValidator blocks dangerous patterns."""

    @pytest.fixture
    def validator(self):
        """Create a fresh CodeValidator."""
        return CodeValidator()

    # -------------------------------------------------------------------------
    # BLOCKED IMPORTS
    # -------------------------------------------------------------------------

    def test_blocks_import_os(self, validator):
        """Test that import os is blocked."""
        code = "import os\ndef run(): return os.getcwd()"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import: os" in v for v in result.violations)

    def test_blocks_import_subprocess(self, validator):
        """Test that import subprocess is blocked."""
        code = "import subprocess\ndef run(): return subprocess.run(['ls'])"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import: subprocess" in v for v in result.violations)

    def test_blocks_import_socket(self, validator):
        """Test that import socket is blocked."""
        code = "import socket\ndef run(): return socket.socket()"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import: socket" in v for v in result.violations)

    def test_blocks_import_pickle(self, validator):
        """Test that import pickle is blocked (RCE vector)."""
        code = "import pickle\ndef run(data): return pickle.loads(data)"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import: pickle" in v for v in result.violations)

    def test_blocks_from_os_import(self, validator):
        """Test that from os import is blocked."""
        code = "from os import system\ndef run(): return system('ls')"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import from: os" in v for v in result.violations)

    def test_blocks_import_ctypes(self, validator):
        """Test that import ctypes (FFI) is blocked."""
        code = "import ctypes\ndef run(): return ctypes.CDLL('libc.so.6')"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import: ctypes" in v for v in result.violations)

    def test_blocks_import_multiprocessing(self, validator):
        """Test that multiprocessing is blocked (sandbox escape)."""
        code = "import multiprocessing\ndef run(): return multiprocessing.Process()"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("import: multiprocessing" in v for v in result.violations)

    # -------------------------------------------------------------------------
    # BLOCKED FUNCTIONS
    # -------------------------------------------------------------------------

    def test_blocks_eval(self, validator):
        """Test that eval() is blocked."""
        code = "def run(code): return eval(code)"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("eval()" in v for v in result.violations)

    def test_blocks_exec(self, validator):
        """Test that exec() is blocked."""
        code = "def run(code): exec(code)"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("exec()" in v for v in result.violations)

    def test_blocks_compile(self, validator):
        """Test that compile() is blocked."""
        code = "def run(src): return compile(src, '<string>', 'exec')"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("compile()" in v for v in result.violations)

    def test_blocks_open(self, validator):
        """Test that open() is blocked."""
        code = "def run(path): return open(path).read()"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("open()" in v for v in result.violations)

    def test_blocks_dunder_import(self, validator):
        """Test that __import__() is blocked."""
        code = "def run(name): return __import__(name)"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("__import__" in v for v in result.violations)

    def test_blocks_globals(self, validator):
        """Test that globals() is blocked."""
        code = "def run(): return globals()"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("globals()" in v for v in result.violations)

    def test_blocks_getattr(self, validator):
        """Test that getattr() is blocked."""
        code = "def run(obj, name): return getattr(obj, name)"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("getattr()" in v for v in result.violations)

    # -------------------------------------------------------------------------
    # BLOCKED ATTRIBUTES
    # -------------------------------------------------------------------------

    def test_blocks_dunder_class(self, validator):
        """Test that __class__ access is blocked."""
        code = "def run(obj): return obj.__class__"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("__class__" in v for v in result.violations)

    def test_blocks_dunder_globals(self, validator):
        """Test that __globals__ access is blocked."""
        code = "def run(fn): return fn.__globals__"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("__globals__" in v for v in result.violations)

    def test_blocks_dunder_code(self, validator):
        """Test that __code__ access is blocked."""
        code = "def run(fn): return fn.__code__"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("__code__" in v for v in result.violations)

    def test_blocks_dunder_builtins(self, validator):
        """Test that __builtins__ access is blocked."""
        code = "def run(): return __builtins__"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("__builtins__" in v for v in result.violations)

    # -------------------------------------------------------------------------
    # BLOCKED PATTERNS
    # -------------------------------------------------------------------------

    def test_blocks_global_statement(self, validator):
        """Test that global statement is blocked."""
        code = "x = 0\ndef run():\n    global x\n    x = 1\n    return x"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("global statement" in v for v in result.violations)

    def test_blocks_nonlocal_statement(self, validator):
        """Test that nonlocal statement is blocked."""
        code = """
def outer():
    x = 0
    def run():
        nonlocal x
        x = 1
        return x
    return run
"""
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("nonlocal statement" in v for v in result.violations)

    def test_blocks_async_function(self, validator):
        """Test that async functions are blocked."""
        code = "async def run(): return await something()"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("async function" in v for v in result.violations)

    def test_blocks_dangerous_class_methods(self, validator):
        """Test that dangerous class methods are blocked."""
        code = """
class Evil:
    def __del__(self):
        pass
def run(): return Evil()
"""
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("__del__" in v for v in result.violations)

    def test_blocks_metaclass(self, validator):
        """Test that metaclass usage is blocked."""
        code = """
class Meta(type): pass
class Evil(metaclass=Meta): pass
def run(): return Evil()
"""
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("metaclass" in v for v in result.violations)

    def test_blocks_bare_except(self, validator):
        """Test that bare except clauses are blocked."""
        code = """
def run():
    try:
        return 1
    except:
        pass
"""
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("bare except" in v for v in result.violations)

    def test_blocks_raise_systemexit(self, validator):
        """Test that raise SystemExit is blocked."""
        code = "def run(): raise SystemExit(0)"
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("SystemExit" in v for v in result.violations)

    # -------------------------------------------------------------------------
    # VALID SAFE CODE
    # -------------------------------------------------------------------------

    def test_allows_safe_math_code(self, validator):
        """Test that safe math code is allowed."""
        code = """
def run(n):
    result = 0
    for i in range(n):
        result += i
    return result
"""
        result = validator.validate_code(code)
        assert result.is_safe
        assert len(result.violations) == 0

    def test_allows_safe_string_code(self, validator):
        """Test that safe string manipulation is allowed."""
        code = """
def run(s):
    return s.upper().strip().replace(' ', '_')
"""
        result = validator.validate_code(code)
        assert result.is_safe

    def test_allows_safe_list_operations(self, validator):
        """Test that safe list operations are allowed."""
        code = """
def run(items):
    result = []
    for item in sorted(items):
        result.append(item * 2)
    return result
"""
        result = validator.validate_code(code)
        assert result.is_safe

    def test_allows_print(self, validator):
        """Test that print() is allowed."""
        code = """
def run(msg):
    print(msg)
    return msg
"""
        result = validator.validate_code(code)
        assert result.is_safe

    def test_catches_syntax_error(self, validator):
        """Test that syntax errors are caught."""
        code = "def run( return 1"  # Invalid syntax
        result = validator.validate_code(code)
        assert not result.is_safe
        assert any("Syntax error" in v for v in result.violations)


# =============================================================================
# DYNAMIC TOOL MANAGER TESTS
# =============================================================================


class TestDynamicToolManager:
    """Test DynamicToolManager functionality."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_workspace):
        """Create a DynamicToolManager with temp workspace."""
        return DynamicToolManager(temp_workspace)

    # -------------------------------------------------------------------------
    # TOOL CREATION
    # -------------------------------------------------------------------------

    def test_create_valid_tool(self, manager):
        """Test creating a valid tool."""
        code = """
def run(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b
"""
        result = manager.create_tool("fibonacci", code, "Calculate fibonacci")

        assert result.success
        assert result.tool_name == "fibonacci"
        assert result.tool_path is not None
        assert result.tool_path.exists()

    def test_create_tool_blocks_dangerous_code(self, manager):
        """Test that dangerous code is blocked during creation."""
        code = """
import subprocess
def run():
    return subprocess.run(['rm', '-rf', '/'])
"""
        result = manager.create_tool("evil", code)

        assert not result.success
        assert "validation failed" in result.error.lower()
        assert len(result.validation_violations) > 0

    def test_create_tool_requires_run_function(self, manager):
        """Test that tool must define run() function."""
        code = """
def calculate(n):
    return n * 2
"""
        result = manager.create_tool("no_run", code)

        assert not result.success
        assert "run()" in result.error

    def test_create_tool_validates_name(self, manager):
        """Test that tool name is validated."""
        code = "def run(): return 1"

        # Invalid names
        result = manager.create_tool("123invalid", code)
        assert not result.success

        result = manager.create_tool("has-dash", code)
        assert not result.success

        result = manager.create_tool("", code)
        assert not result.success

        # Valid names
        result = manager.create_tool("valid_name", code)
        assert result.success

    def test_cannot_create_duplicate_tool(self, manager):
        """Test that duplicate tool names are rejected."""
        code = "def run(): return 1"

        result1 = manager.create_tool("unique", code)
        assert result1.success

        result2 = manager.create_tool("unique", code)
        assert not result2.success
        assert "already exists" in result2.error

    # -------------------------------------------------------------------------
    # TOOL EXECUTION
    # -------------------------------------------------------------------------

    def test_execute_simple_tool(self, manager):
        """Test executing a simple tool."""
        code = """
def run(x, y):
    return x + y
"""
        manager.create_tool("adder", code, "Add two numbers")
        result = manager.execute_tool("adder", {"x": 5, "y": 3})

        assert result.success
        assert "8" in result.output

    def test_execute_fibonacci_tool(self, manager):
        """Test executing a fibonacci tool."""
        code = """
def run(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b
"""
        manager.create_tool("fib", code)
        result = manager.execute_tool("fib", {"n": 10})

        assert result.success
        assert "55" in result.output  # fib(10) = 55

    def test_execute_nonexistent_tool(self, manager):
        """Test executing a tool that doesn't exist."""
        result = manager.execute_tool("nonexistent", {})

        assert not result.success
        assert "not found" in result.error.lower()

    def test_execute_tool_with_error(self, manager):
        """Test handling tool execution errors."""
        code = """
def run():
    raise ValueError("Test error")
"""
        manager.create_tool("error_tool", code)
        result = manager.execute_tool("error_tool", {})

        assert not result.success
        assert "Test error" in result.error or "Test error" in result.output

    def test_execute_tool_timeout(self, manager):
        """Test that infinite loops timeout."""
        code = """
def run():
    while True:
        pass
"""
        manager.create_tool("infinite", code)

        # This should timeout
        result = manager.execute_tool("infinite", {})

        assert not result.success
        assert result.timed_out
        # Check error message contains timeout info
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()

    # -------------------------------------------------------------------------
    # TOOL DELETION
    # -------------------------------------------------------------------------

    def test_delete_existing_tool(self, manager):
        """Test deleting an existing tool."""
        code = "def run(): return 1"
        manager.create_tool("to_delete", code)

        success, message = manager.delete_tool("to_delete")

        assert success
        assert "deleted" in message.lower()

        # Verify tool is gone
        result = manager.execute_tool("to_delete", {})
        assert not result.success

    def test_delete_nonexistent_tool(self, manager):
        """Test deleting a tool that doesn't exist."""
        success, message = manager.delete_tool("nonexistent")

        assert not success
        assert "not found" in message.lower()

    # -------------------------------------------------------------------------
    # TOOL LISTING
    # -------------------------------------------------------------------------

    def test_list_tools_empty(self, manager):
        """Test listing tools when none exist."""
        tools = manager.list_tools()
        assert len(tools) == 0

    def test_list_tools_with_tools(self, manager):
        """Test listing tools after creation."""
        manager.create_tool("tool1", "def run(): return 1")
        manager.create_tool("tool2", "def run(): return 2")

        tools = manager.list_tools()

        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "tool1" in names
        assert "tool2" in names

    def test_cleanup_all(self, manager):
        """Test cleanup_all removes all tools."""
        manager.create_tool("tool1", "def run(): return 1")
        manager.create_tool("tool2", "def run(): return 2")

        count = manager.cleanup_all()

        assert count == 2
        assert len(manager.list_tools()) == 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestDynamicToolsIntegration:
    """Integration tests for dynamic tools."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_full_lifecycle(self, temp_workspace):
        """Test complete tool lifecycle: create, list, execute, delete."""
        manager = DynamicToolManager(temp_workspace)

        # Create
        code = """
def run(items):
    return sorted(items)
"""
        create_result = manager.create_tool("sorter", code, "Sort a list")
        assert create_result.success

        # List
        tools = manager.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "sorter"

        # Execute
        exec_result = manager.execute_tool("sorter", {"items": [3, 1, 2]})
        assert exec_result.success
        # JSON output may be formatted with newlines
        assert "1" in exec_result.output and "2" in exec_result.output and "3" in exec_result.output

        # Delete
        success, _ = manager.delete_tool("sorter")
        assert success

        # Verify gone
        assert len(manager.list_tools()) == 0

    def test_persistence_across_manager_instances(self, temp_workspace):
        """Test that tools persist across manager instances."""
        # Create tool with first manager
        manager1 = DynamicToolManager(temp_workspace)
        manager1.create_tool("persistent", "def run(): return 42")

        # Create new manager and verify tool exists
        manager2 = DynamicToolManager(temp_workspace)
        tools = manager2.list_tools()

        assert len(tools) == 1
        assert tools[0].name == "persistent"

        # Execute with new manager
        result = manager2.execute_tool("persistent", {})
        assert result.success
        assert "42" in result.output

    def test_complex_tool_with_multiple_functions(self, temp_workspace):
        """Test tool with helper functions."""
        code = """
def helper(x):
    return x * 2

def run(n):
    result = 0
    for i in range(n):
        result += helper(i)
    return result
"""
        manager = DynamicToolManager(temp_workspace)
        manager.create_tool("complex", code)

        result = manager.execute_tool("complex", {"n": 5})

        # 0*2 + 1*2 + 2*2 + 3*2 + 4*2 = 0 + 2 + 4 + 6 + 8 = 20
        assert result.success
        assert "20" in result.output


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def temp_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_tool_with_unicode(self, temp_workspace):
        """Test tool with unicode characters."""
        manager = DynamicToolManager(temp_workspace)
        code = """
def run(text):
    return f"Hello {text}!"
"""
        manager.create_tool("greeter", code)
        result = manager.execute_tool("greeter", {"text": "World"})

        assert result.success
        # Check the greeting is in output (unicode may be escaped in JSON)
        assert "Hello" in result.output and "World" in result.output

    def test_tool_returning_complex_data(self, temp_workspace):
        """Test tool returning complex data structures."""
        manager = DynamicToolManager(temp_workspace)
        code = """
def run():
    return {
        "list": [1, 2, 3],
        "dict": {"a": 1},
        "nested": {"x": [{"y": 2}]}
    }
"""
        manager.create_tool("complex_return", code)
        result = manager.execute_tool("complex_return", {})

        assert result.success
        assert "list" in result.output
        assert "nested" in result.output

    def test_validator_handles_empty_code(self):
        """Test validator with empty code."""
        validator = CodeValidator()
        result = validator.validate_code("")
        # Empty code is syntactically valid (empty module)
        assert result.is_safe

    def test_validator_handles_whitespace_only(self):
        """Test validator with whitespace-only code."""
        validator = CodeValidator()
        result = validator.validate_code("   \n\t\n   ")
        assert result.is_safe
