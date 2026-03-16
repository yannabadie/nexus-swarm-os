"""
NEXUS V7.8 - Execution Policy (Phase 14a Security Hardening + Phase 12.5 Code Validation)

Centralized command validation and execution security policy.
Prevents command injection, path traversal, and dangerous operations.

NOTE: This is different from core/governance/sandbox_policy.py which handles
      tool-level permissions during FSM states (brainstorming vs execution).
      This module handles command-level security for bash execution.

V7.8 Phase 12.5: Added CodeValidator for dynamic tool generation security.
    - AST-based Python code validation
    - Blocks dangerous imports, functions, and attribute access
    - Used by DynamicToolManager to validate generated code

Usage:
    policy = ExecutionPolicy(workspace_path)

    # Validate command
    is_valid, error = policy.validate_command("ls -la")
    if not is_valid:
        raise SecurityError(error)

    # Check path access
    if not policy.is_path_allowed(Path("/etc/passwd")):
        raise SecurityError("Path not allowed")

    # V7.8: Validate Python code for dynamic tools
    validator = CodeValidator()
    is_safe, violations = validator.validate_code(python_code)
    if not is_safe:
        raise SecurityError(f"Unsafe code: {violations}")
"""

import ast
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CommandType(Enum):
    """Classification of command types for security routing."""

    SIMPLE = "simple"  # Single command, no shell features (shell=False)
    COMPLEX = "complex"  # Requires shell features (pipe, redirect)
    BLOCKED = "blocked"  # Dangerous, always rejected


@dataclass
class CommandAnalysis:
    """Result of command analysis."""

    command_type: CommandType
    executable: str
    arguments: list[str]
    requires_shell: bool
    blocked_reason: str | None = None


class ExecutionPolicy:
    """
    Security policy for command execution and path access.

    Defense layers:
    1. Dangerous executable blocking (rm, sudo, nc, etc.)
    2. Shell metacharacter detection (|, &, ;, etc.)
    3. Path traversal prevention
    4. Workspace containment

    Thread-safe: All methods are stateless validations.
    """

    # Dangerous executables - ALWAYS blocked
    BLOCKED_EXECUTABLES: set[str] = {
        # Network tools (potential exfiltration)
        "nc",
        "netcat",
        "ncat",
        "socat",
        "telnet",
        "ftp",
        "sftp",
        "scp",
        "curl",
        "wget",  # Block raw downloads in sandbox
        # Privilege escalation
        "sudo",
        "su",
        "doas",
        "runas",
        "pkexec",
        "gksudo",
        "kdesudo",
        # Destructive commands
        "dd",
        "mkfs",
        "fdisk",
        "parted",
        "shred",
        "wipe",
        # Code execution (potential payload download)
        "perl",
        "ruby",
        "php",
        "node",
        "powershell",
        "pwsh",
        "cmd.exe",
        # System manipulation
        "systemctl",
        "service",
        "init",
        "reboot",
        "shutdown",
        "halt",
        "crontab",
        "at",
        # Compiler/build (prevent malicious builds)
        "make",
        "gcc",
        "g++",
        "clang",
        "cargo",
        "go build",
        "npm run",
    }

    # Dangerous patterns in commands - ALWAYS blocked
    BLOCKED_PATTERNS: list[tuple[str, str]] = [
        # Recursive delete
        (r"\brm\s+(-[rf]+\s+)*(/|~|\$HOME)", "rm on root or home"),
        (r"\brm\s+-rf?\s+\*", "rm with wildcard"),
        (r"del\s+/[sq]\s+", "Windows recursive delete"),
        # Fork bombs
        (r":\(\)\{\s*:\|:&\s*\};:", "Fork bomb pattern"),
        (r"while\s+true.*do", "Infinite loop"),
        # Password/secret access
        (r"/etc/passwd", "Password file access"),
        (r"/etc/shadow", "Shadow file access"),
        (r"\.ssh/", "SSH directory access"),
        (r"\.aws/", "AWS credentials access"),
        (r"\.gnupg/", "GPG keys access"),
        # Path traversal - deep parent access
        (r"\.\.(/|\\)\.\.(/|\\)\.\.", "Deep path traversal"),
        # Parent directory write operations
        (r">\s*\.\.(/|\\)", "Write redirect to parent"),
        (r">>\s*\.\.(/|\\)", "Append redirect to parent"),
        # Git operations via bash (use git tool instead)
        (r"\bgit\s+(push|commit|add|reset|rebase|merge)\b", "Git write operation via bash"),
        # Environment manipulation
        (r"export\s+\w+=", "Environment variable export"),
        (r"\$\(.*\)", "Command substitution"),
        (r"`.*`", "Backtick command substitution"),
        # Network operations
        (r"\b\d{4,5}\b.*\b(0\.0\.0\.0|127\.0\.0\.1|localhost)\b|\b(0\.0\.0\.0|127\.0\.0\.1|localhost)\b.*\d{4,5}", "Local network binding"),
        (r">/dev/tcp/", "Bash network redirect"),
        # History/log tampering
        (r"history\s+-[cd]", "History manipulation"),
        (r">\s*/var/log/", "Log file tampering"),
        (r"unset\s+HIST", "History variable unset"),
    ]

    # Shell metacharacters that require shell=True
    SHELL_METACHARACTERS: set[str] = {
        "|",  # Pipe
        "&",  # Background / AND
        ";",  # Command separator
        ">",  # Output redirect
        "<",  # Input redirect
        ">>",  # Append redirect
        "2>",  # Stderr redirect
        "&&",  # Conditional AND
        "||",  # Conditional OR
        "$(",
        ")",  # Command substitution
        "`",  # Backtick substitution
        "*",  # Glob wildcard
        "?",  # Glob single char
        "[",  # Glob charset
        "~",  # Home directory
        "$",  # Variable expansion
    }

    # Executables allowed with shell features (carefully controlled)
    ALLOWED_COMPLEX_EXECUTABLES: set[str] = {
        "grep",
        "rg",
        "ripgrep",  # Search with pipe
        "cat",
        "head",
        "tail",  # File viewing with pipe
        "sort",
        "uniq",
        "wc",  # Text processing
        "find",  # File finding (limited)
        "ls",
        "dir",  # Listing with pipe
        "echo",  # Output
    }

    def __init__(self, workspace_path: Path):
        """
        Initialize ExecutionPolicy.

        Args:
            workspace_path: Root workspace directory for containment
        """
        self.workspace_path = workspace_path.resolve()
        # Pre-compile blocked patterns for performance
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in self.BLOCKED_PATTERNS
        ]

    def validate_command(self, command: str) -> tuple[bool, str | None]:
        """
        Validate a shell command for security.

        Args:
            command: Shell command string

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is None
        """
        if not command or not command.strip():
            return False, "Empty command"

        command = command.strip()

        # Check blocked patterns first (fastest rejection)
        for pattern, description in self._compiled_patterns:
            if pattern.search(command):
                return False, f"[SECURITY] Blocked pattern: {description}"

        # Analyze command structure
        analysis = self.analyze_command(command)

        if analysis.command_type == CommandType.BLOCKED:
            return False, f"[SECURITY] Blocked: {analysis.blocked_reason}"

        return True, None

    def analyze_command(self, command: str) -> CommandAnalysis:
        """
        Analyze command to determine execution strategy.

        Args:
            command: Shell command string

        Returns:
            CommandAnalysis with type and parsed components
        """
        command = command.strip()

        # Check for shell metacharacters
        has_shell_features = any(meta in command for meta in self.SHELL_METACHARACTERS)

        # Try to parse command
        try:
            parts = shlex.split(command)
        except ValueError:
            # Unparseable command (unbalanced quotes, etc.)
            return CommandAnalysis(
                command_type=CommandType.BLOCKED,
                executable="",
                arguments=[],
                requires_shell=True,
                blocked_reason="Malformed command (unparseable)",
            )

        if not parts:
            return CommandAnalysis(
                command_type=CommandType.BLOCKED,
                executable="",
                arguments=[],
                requires_shell=False,
                blocked_reason="Empty command",
            )

        executable = parts[0].lower()

        # Strip path from executable for checking
        executable_name = Path(executable).name.lower()

        # Check if executable is blocked
        if executable_name in self.BLOCKED_EXECUTABLES:
            return CommandAnalysis(
                command_type=CommandType.BLOCKED,
                executable=executable,
                arguments=parts[1:],
                requires_shell=has_shell_features,
                blocked_reason=f"Blocked executable: {executable_name}",
            )

        # Check for rm with dangerous patterns
        if executable_name == "rm":
            args_str = " ".join(parts[1:])
            if re.search(r"-r.*-f|f.*-r|rf|fr", args_str) and any(
                dangerous in args_str for dangerous in ["/", "~", "..", "*"]
            ):
                # rm -rf is dangerous with dangerous target
                return CommandAnalysis(
                    command_type=CommandType.BLOCKED,
                    executable=executable,
                    arguments=parts[1:],
                    requires_shell=has_shell_features,
                    blocked_reason="Dangerous rm command",
                )

        # Determine command type
        if has_shell_features:
            # Check if this complex command is allowed
            if executable_name in self.ALLOWED_COMPLEX_EXECUTABLES:
                return CommandAnalysis(
                    command_type=CommandType.COMPLEX, executable=executable, arguments=parts[1:], requires_shell=True
                )
            else:
                # Complex command with non-allowed executable
                return CommandAnalysis(
                    command_type=CommandType.BLOCKED,
                    executable=executable,
                    arguments=parts[1:],
                    requires_shell=True,
                    blocked_reason=f"Shell features not allowed for: {executable_name}",
                )

        # Simple command - can use shell=False
        return CommandAnalysis(
            command_type=CommandType.SIMPLE, executable=executable, arguments=parts[1:], requires_shell=False
        )

    def is_path_allowed(self, path: Path, operation: str = "read") -> bool:
        """
        Check if a path is allowed for the given operation.

        Args:
            path: Path to check
            operation: "read" or "write"

        Returns:
            True if path is allowed
        """
        try:
            resolved = path.resolve()
        except (OSError, ValueError):
            return False

        # Check if path is within workspace FIRST (workspace is always allowed)
        try:
            resolved.relative_to(self.workspace_path)
            is_in_workspace = True
        except ValueError:
            is_in_workspace = False

        # Normalize path for cross-platform comparison
        path_str = str(resolved).replace("\\", "/").lower()
        original_str = str(path).replace("\\", "/").lower()

        # Block .env files (even in workspace for safety)
        if path_str.endswith(".env") or "/.env" in path_str:
            return False

        # If in workspace, allow (except .env checked above)
        if is_in_workspace:
            return True

        # Block sensitive directories (cross-platform) - outside workspace
        dir_sensitive = [
            "/.ssh/",
            "/.aws/",
            "/.gnupg/",
        ]

        for sens in dir_sensitive:
            if sens in path_str or sens in original_str:
                return False

        # Block sensitive system paths (Unix) - outside workspace
        unix_sensitive = [
            "/etc/passwd",
            "/etc/shadow",
            "/etc/sudoers",
        ]

        for sens in unix_sensitive:
            if sens in path_str or sens in original_str:
                return False

        # For writes, must be within workspace (already checked above)
        # For reads outside workspace, allow (for evolution mode)
        return operation != "write"

    def sanitize_arguments(self, args: list[str]) -> list[str]:
        """
        Sanitize command arguments to prevent injection.

        Args:
            args: List of command arguments

        Returns:
            Sanitized argument list
        """
        sanitized = []
        for arg in args:
            # Remove null bytes
            arg = arg.replace("\x00", "")
            # Remove command substitution
            arg = re.sub(r"\$\([^)]*\)", "", arg)
            arg = re.sub(r"`[^`]*`", "", arg)
            sanitized.append(arg)
        return sanitized

    def get_safe_execution_args(self, command: str) -> tuple[list[str], bool] | None:
        """
        Get safe execution arguments for a command.

        Args:
            command: Shell command string

        Returns:
            Tuple of (args_list, use_shell) or None if blocked
        """
        is_valid, error = self.validate_command(command)
        if not is_valid:
            return None

        analysis = self.analyze_command(command)

        if analysis.command_type == CommandType.BLOCKED:
            return None

        if analysis.command_type == CommandType.SIMPLE:
            # Safe to use shell=False
            args = [analysis.executable] + self.sanitize_arguments(analysis.arguments)
            return (args, False)

        # Complex command - needs shell=True but was validated
        return ([command], True)


# =============================================================================
# V7.8 Phase 12.5: CodeValidator for Dynamic Tool Generation
# =============================================================================


@dataclass
class CodeValidationResult:
    """Result of code validation."""

    is_safe: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_safe


class CodeValidator(ast.NodeVisitor):
    """
    AST-based Python code validator for dynamic tool generation.

    V7.8 Phase 12.5: Ensures generated tool code is safe to execute.

    Defense layers:
    1. Block dangerous module imports (os, subprocess, socket, etc.)
    2. Block dangerous function calls (eval, exec, compile, etc.)
    3. Block dangerous attribute access (__class__, __globals__, etc.)
    4. Block dangerous syntax patterns (lambda with banned ops, etc.)

    Thread-safe: All methods are stateless validations.

    Usage:
        validator = CodeValidator()
        result = validator.validate_code(python_code)
        if not result.is_safe:
            print(f"Blocked: {result.violations}")
    """

    # ==========================================================================
    # BLOCKED IMPORTS - Modules that provide dangerous capabilities
    # ==========================================================================
    BLOCKED_IMPORTS: set[str] = {
        # System access
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "platform",
        "sysconfig",
        # Network access
        "socket",
        "socketserver",
        "http",
        "http.client",
        "http.server",
        "urllib",
        "urllib.request",
        "urllib.parse",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "ssl",
        "asyncio",
        # Code execution / dynamic imports
        "importlib",
        "runpy",
        "code",
        "codeop",
        "compileall",
        "py_compile",
        # Serialization (RCE vectors)
        "pickle",
        "cPickle",
        "marshal",
        "shelve",
        "dill",
        # Native code / FFI
        "ctypes",
        "cffi",
        "_ctypes",
        "ffi",
        # Multiprocessing (sandbox escape)
        "multiprocessing",
        "threading",
        "concurrent",
        "_thread",
        "thread",
        # Dangerous builtins access
        "builtins",
        "__builtins__",
        # File operations (use provided wrappers)
        "io",
        "tempfile",
        "glob",
        "fnmatch",
        # Introspection
        "inspect",
        "dis",
        "gc",
        "traceback",
        # Signals (process manipulation)
        "signal",
        "atexit",
        # Resource manipulation
        "resource",
        "pwd",
        "grp",
        "crypt",
        # Windows-specific dangerous modules
        "winreg",
        "msvcrt",
        "_winapi",
    }

    # ==========================================================================
    # BLOCKED FUNCTIONS - Dangerous built-in functions
    # ==========================================================================
    BLOCKED_FUNCTIONS: set[str] = {
        # Code execution
        "eval",
        "exec",
        "compile",
        "__import__",
        # File operations (must use provided safe wrappers)
        "open",
        "file",
        # User input (interactive)
        "input",
        "raw_input",
        # Namespace manipulation
        "globals",
        "locals",
        "vars",
        "dir",  # Can reveal internal structure
        # Attribute manipulation
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        # Type manipulation
        "type",
        "isinstance",
        "issubclass",
        "super",  # Can be used for attribute access
        # Object introspection
        "id",
        "hash",
        "repr",  # Can leak memory addresses
        "callable",
        "staticmethod",
        "classmethod",
        # Memory manipulation
        "memoryview",
        "bytearray",
        # System exit
        "exit",
        "quit",
        "breakpoint",
        # Help (can reveal internals)
        "help",
        "credits",
        "license",
        "copyright",
    }

    # ==========================================================================
    # BLOCKED ATTRIBUTES - Dangerous dunder/special attributes
    # ==========================================================================
    BLOCKED_ATTRIBUTES: set[str] = {
        # Class/type introspection
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__subclasshook__",
        # Object lifecycle
        "__init__",
        "__new__",
        "__del__",
        "__init_subclass__",
        # Code objects
        "__code__",
        "__globals__",
        "__builtins__",
        "__closure__",
        "__annotations__",
        # Import machinery
        "__import__",
        "__loader__",
        "__spec__",
        "__package__",
        "__path__",
        # Callable manipulation
        "__call__",
        "__func__",
        "__self__",
        # Descriptor protocol (can bypass restrictions)
        "__get__",
        "__set__",
        "__delete__",
        "__set_name__",
        # Attribute access hooks
        "__getattr__",
        "__setattr__",
        "__delattr__",
        "__getattribute__",
        # Container dunders that could be abused
        "__dict__",
        "__slots__",
        # Metaclass manipulation
        "__metaclass__",
        "__prepare__",
        # Module attributes
        "__file__",
        "__cached__",
        "__doc__",
        # Reduce/pickle (serialization)
        "__reduce__",
        "__reduce_ex__",
        "__getstate__",
        "__setstate__",
    }

    # ==========================================================================
    # ALLOWED SAFE BUILTINS - Whitelisted functions for tools
    # ==========================================================================
    ALLOWED_BUILTINS: set[str] = {
        # Math
        "abs",
        "round",
        "min",
        "max",
        "sum",
        "pow",
        "divmod",
        # Type conversion
        "int",
        "float",
        "str",
        "bool",
        "bytes",
        "list",
        "tuple",
        "dict",
        "set",
        "frozenset",
        # String operations
        "ord",
        "chr",
        "ascii",
        "bin",
        "hex",
        "oct",
        "format",
        # Iteration
        "range",
        "enumerate",
        "zip",
        "map",
        "filter",
        "reversed",
        "sorted",
        "iter",
        "next",
        # Length/membership
        "len",
        "any",
        "all",
        "slice",
        # Printing (output only)
        "print",
    }

    def __init__(self):
        """Initialize CodeValidator."""
        self._violations: list[str] = []

    def validate_code(self, code: str) -> CodeValidationResult:
        """
        Validate Python code for safety.

        Args:
            code: Python source code string

        Returns:
            CodeValidationResult with is_safe and violations list
        """
        self._violations = []

        # Step 1: Try to parse the code
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return CodeValidationResult(is_safe=False, violations=[f"Syntax error: {e.msg} (line {e.lineno})"])

        # Step 2: Walk the AST and check for violations
        self.visit(tree)

        return CodeValidationResult(is_safe=len(self._violations) == 0, violations=self._violations.copy())

    def _add_violation(self, node: ast.AST, message: str) -> None:
        """Add a violation with line number."""
        line = getattr(node, "lineno", "?")
        self._violations.append(f"Line {line}: {message}")

    # ==========================================================================
    # AST Visitor Methods
    # ==========================================================================

    def visit_Import(self, node: ast.Import) -> None:
        """Check for blocked imports: import os, import subprocess"""
        for alias in node.names:
            module_name = alias.name.split(".")[0]  # Get root module
            if module_name in self.BLOCKED_IMPORTS:
                self._add_violation(node, f"Blocked import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check for blocked from-imports: from os import system"""
        if node.module:
            module_name = node.module.split(".")[0]
            if module_name in self.BLOCKED_IMPORTS:
                self._add_violation(node, f"Blocked import from: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Check for blocked function calls."""
        func_name = None

        # Direct call: eval(...)
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        # Method call: obj.method(...) - check method name
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name and func_name in self.BLOCKED_FUNCTIONS:
            self._add_violation(node, f"Blocked function call: {func_name}()")

        # Check for __import__ specifically
        if func_name == "__import__":
            self._add_violation(node, "Blocked: __import__() - use allowed modules only")

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Check for blocked attribute access."""
        if node.attr in self.BLOCKED_ATTRIBUTES:
            self._add_violation(node, f"Blocked attribute access: .{node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Check for direct access to blocked names."""
        # Block direct access to __builtins__ etc.
        if node.id.startswith("__") and node.id.endswith("__") and node.id in self.BLOCKED_ATTRIBUTES:
            self._add_violation(node, f"Blocked name access: {node.id}")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        """Block global statement - namespace manipulation."""
        self._add_violation(node, f"Blocked: global statement ({', '.join(node.names)})")
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        """Block nonlocal statement - namespace manipulation."""
        self._add_violation(node, f"Blocked: nonlocal statement ({', '.join(node.names)})")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check class definitions for dangerous patterns."""
        # Check for metaclass usage
        for keyword in node.keywords:
            if keyword.arg == "metaclass":
                self._add_violation(node, f"Blocked: metaclass in class {node.name}")

        # Check for dangerous method definitions
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in {
                "__del__",
                "__getattr__",
                "__setattr__",
                "__getattribute__",
                "__reduce__",
                "__reduce_ex__",
            }:
                self._add_violation(item, f"Blocked: dangerous method {item.name}() in class {node.name}")

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions."""
        # Block decorator usage (could bypass restrictions)
        if node.decorator_list:
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id in {"staticmethod", "classmethod", "property"}:
                    continue  # These are safe
                self._add_violation(decorator, f"Blocked: decorator on function {node.name}")
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Block async functions (require asyncio which is blocked)."""
        self._add_violation(node, f"Blocked: async function {node.name}")
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        """Block await expressions."""
        self._add_violation(node, "Blocked: await expression")
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        """Check with statements for dangerous patterns."""
        # Block file operations via with
        for item in node.items:
            if (
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "open"
            ):
                self._add_violation(node, "Blocked: with open() - use provided file wrappers")
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        """Allow try/except but check for bare except."""
        for handler in node.handlers:
            if handler.type is None:
                # Bare except: can catch SystemExit etc.
                self._add_violation(handler, "Blocked: bare except clause (specify exception type)")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        """Allow raise but check for SystemExit."""
        if (
            node.exc
            and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id in {"SystemExit", "KeyboardInterrupt"}
        ):
            self._add_violation(node, f"Blocked: raise {node.exc.func.id}")
        self.generic_visit(node)


# =============================================================================
# Singletons for easy access
# =============================================================================

_policy: ExecutionPolicy | None = None
_code_validator: CodeValidator | None = None


def get_execution_policy(workspace_path: Path | None = None) -> ExecutionPolicy:
    """Get or create the global ExecutionPolicy instance."""
    global _policy
    if _policy is None:
        if workspace_path is None:
            raise ValueError("workspace_path required for first initialization")
        _policy = ExecutionPolicy(workspace_path)
    return _policy


def get_code_validator() -> CodeValidator:
    """Get or create the global CodeValidator instance."""
    global _code_validator
    if _code_validator is None:
        _code_validator = CodeValidator()
    return _code_validator
