"""
MutationValidator - Behavioral analysis of mutation code.

Mode: WARN + CONTINUE (never blocks, only logs warnings)

This validator uses AST analysis to detect potentially dangerous patterns
in mutation code, but follows the user's decision to WARN rather than BLOCK.

Special handling:
- open(): Allowed if workspace-relative path
- os/subprocess: Warning only (agents may have legitimate uses)
"""

import ast
import re
from pathlib import Path


class MutationValidator:
    """Validates mutation code - warning mode (never blocks)."""

    # Imports potentiellement dangereux (WARNING seulement)
    SUSPICIOUS_IMPORTS = {
        "os",
        "subprocess",
        "shutil",
        "sys",
        "socket",
        "requests",
        "urllib",
        "pickle",
        "marshal",
        "ctypes",
        "multiprocessing",
    }

    # Fonctions suspectes (WARNING seulement)
    SUSPICIOUS_CALLS = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "system",
        "popen",
        "spawn",
        "remove",
        "rmdir",
        "unlink",
        "rmtree",
        "chmod",
        "chown",
    }

    # Patterns regex suspects dans le code
    SUSPICIOUS_PATTERNS = [
        (r"os\.system\s*\(", "os.system() - command execution"),
        (r"subprocess\.(run|call|Popen|check_output)", "subprocess execution"),
        (r"shutil\.(rmtree|move|copy)", "shutil file operation"),
        (r"__import__\s*\(", "dynamic import"),
        (r"\bexec\s*\(", "exec() - arbitrary code execution"),
        (r"\beval\s*\(", "eval() - arbitrary code execution"),
        (r"os\.(remove|unlink|rmdir)", "os file deletion"),
        (r"Path\([^)]*\)\.unlink", "pathlib file deletion"),
        (r"\.write\s*\([^)]*\.\.[^)]*\)", "write with parent path"),
    ]

    def __init__(self, workspace_path: Path | None = None):
        """
        Initialize MutationValidator.

        Args:
            workspace_path: Optional workspace path for relative path analysis
        """
        self.workspace_path = workspace_path

    def validate(self, code: str, target_file: str) -> tuple[list[str], list[str]]:
        """
        Validate mutation code for suspicious patterns.

        Args:
            code: The Python code to validate
            target_file: The target file path (for context)

        Returns:
            (warnings, info_messages)
            - warnings: List of warning messages for suspicious patterns
            - info: List of informational messages (e.g., open() allowed)

        NOTE: This method NEVER blocks. It returns warnings for human review,
        but the mutation is always applied (user's choice: "Avertir + continuer").
        """
        warnings: list[str] = []
        info: list[str] = []

        # 1. Analyse statique par regex (rapide, catch-all)
        for pattern, description in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                warnings.append(f"Pattern suspect: {description}")

        # 2. Analyse AST (plus précise)
        try:
            tree = ast.parse(code)
            ast_warnings, ast_info = self._analyze_ast(tree)
            warnings.extend(ast_warnings)
            info.extend(ast_info)

        except SyntaxError as e:
            # Expected for indented code snippets (class methods, etc.)
            # The actual syntax validation happens in repl.py after block insertion
            # This is NOT an error - just info that AST analysis couldn't be performed
            info.append(f"AST analysis skipped (expected for indented code snippets): {e.msg}")

        # 3. Dédupliquer les warnings
        warnings = list(dict.fromkeys(warnings))
        info = list(dict.fromkeys(info))

        return warnings, info

    def _analyze_ast(self, tree: ast.AST) -> tuple[list[str], list[str]]:
        """
        Analyze AST for suspicious patterns.

        Returns:
            (warnings, info)
        """
        warnings: list[str] = []
        info: list[str] = []

        for node in ast.walk(tree):
            # Vérifier imports suspects
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_root = alias.name.split(".")[0]
                    if module_root in self.SUSPICIOUS_IMPORTS:
                        warnings.append(f"Import suspect: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_root = node.module.split(".")[0]
                    if module_root in self.SUSPICIOUS_IMPORTS:
                        warnings.append(f"Import from suspect: {node.module}")

            # Vérifier appels de fonctions
            elif isinstance(node, ast.Call):
                func_name = self._get_func_name(node)

                if not func_name:
                    continue

                # Cas spécial: open() - autoriser si workspace-relative
                if func_name == "open":
                    path_arg = self._extract_first_string_arg(node)
                    if path_arg:
                        if self._is_parent_or_absolute_path(path_arg):
                            warnings.append(f"open() avec chemin parent/absolu: {path_arg}")
                        else:
                            info.append(f"open() autorisé (workspace-relative): {path_arg}")
                    else:
                        info.append("open() avec chemin dynamique (non analysable)")

                # Autres fonctions suspectes
                elif func_name in self.SUSPICIOUS_CALLS:
                    warnings.append(f"Appel suspect: {func_name}()")

                # Méthodes suspectes sur objets
                elif isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                    if method_name in self.SUSPICIOUS_CALLS:
                        warnings.append(f"Méthode suspecte: .{method_name}()")

        return warnings, info

    def _get_func_name(self, node: ast.Call) -> str:
        """Extract function name from a Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""

    def _extract_first_string_arg(self, node: ast.Call) -> str:
        """Extract the first string argument from a call (for open() analysis)."""
        if node.args:
            first_arg = node.args[0]
            # ast.Constant is the canonical way since Python 3.8+
            # ast.Str was removed in Python 3.14
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                return first_arg.value
        return ""

    def _is_parent_or_absolute_path(self, path: str) -> bool:
        """Check if a path references parent directory or is absolute."""
        if not path:
            return False

        # Absolute paths
        if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            return True

        # Parent directory references
        if path.startswith(".."):
            return True

        # Hidden parent references
        return bool("/../" in path or path.endswith("/.."))

    def format_report(self, warnings: list[str], info: list[str], target_file: str) -> str:
        """
        Format a human-readable report.

        Args:
            warnings: List of warnings
            info: List of info messages
            target_file: The target file for context

        Returns:
            Formatted string report
        """
        lines = []

        if warnings:
            lines.append(f"MUTATION WARNINGS for {target_file}:")
            for w in warnings:
                lines.append(f"  {w}")
            lines.append("  (Applying anyway - review the code)")

        if info:
            lines.append(f"Info for {target_file}:")
            for i in info:
                lines.append(f"  {i}")

        return "\n".join(lines) if lines else ""
