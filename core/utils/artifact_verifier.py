"""
Artifact Verifier - Robust validation of agent-produced artifacts.

This module provides real verification of files and code produced by agents,
going beyond simple text pattern matching for PASS/FAIL detection.
"""

import ast
import re
from pathlib import Path


class ArtifactVerifier:
    """
    Verifies that artifacts mentioned in agent output actually exist and are valid.

    Used primarily in RED_BLUE mode to detect false positives where an agent
    claims success but the actual files are missing or have errors.
    """

    def __init__(self, workspace: Path):
        """
        Initialize verifier with workspace path.

        Args:
            workspace: Path to the workspace directory where files are created
        """
        self.workspace = Path(workspace)

    def verify_from_content(self, content: str) -> tuple[bool, list[str], list[str]]:
        """
        Extract file references from content and verify they exist and are valid.

        Args:
            content: Agent output text claiming to have created/modified files

        Returns:
            Tuple of (all_passed, successes, failures) where:
            - all_passed: True if all checks passed
            - successes: List of successful check messages
            - failures: List of failure messages
        """
        files = self._extract_file_refs(content)
        successes: list[str] = []
        failures: list[str] = []

        if not files:
            # No files mentioned - consider this a pass (text-only response)
            return True, ["No file artifacts to verify"], []

        for f in files:
            # Resolve path relative to workspace
            path = self.workspace / f if not Path(f).is_absolute() else Path(f)

            # Check existence
            if not path.exists():
                failures.append(f"File not found: {f}")
                continue
            successes.append(f"File exists: {f}")

            # For Python files, verify syntax
            if path.suffix == ".py":
                syntax_ok, syntax_msg = self._verify_python_syntax(path)
                if syntax_ok:
                    successes.append(syntax_msg)
                else:
                    failures.append(syntax_msg)

            # For JSON files, verify valid JSON
            elif path.suffix == ".json":
                json_ok, json_msg = self._verify_json_syntax(path)
                if json_ok:
                    successes.append(json_msg)
                else:
                    failures.append(json_msg)

        return len(failures) == 0, successes, failures

    def _extract_file_refs(self, content: str) -> list[str]:
        """
        Extract file paths mentioned in content.

        Looks for common patterns like:
        - `filename.py` (backtick quoted)
        - "filename.py" (double quoted)
        - 'filename.py' (single quoted)
        - wrote/created/saved to filename.py

        Args:
            content: Text to search for file references

        Returns:
            List of unique file paths found
        """
        patterns = [
            # Backtick quoted files
            r"`([^`]+\.(?:py|md|json|txt|yaml|yml|js|ts|html|css))`",
            # Double quoted files
            r'"([^"]+\.(?:py|md|json|txt|yaml|yml|js|ts|html|css))"',
            # Single quoted files
            r"'([^']+\.(?:py|md|json|txt|yaml|yml|js|ts|html|css))'",
            # Action verbs followed by file paths
            r'(?:wrote|created|saved|modified|updated|generated)\s+(?:to\s+)?[`"\']?([^\s`"\']+\.(?:py|md|json|txt|yaml))',
            # Output/artifact patterns
            r'(?:output|artifact|file):\s*[`"\']?([^\s`"\']+\.(?:py|md|json|txt))',
        ]

        files = set()
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            files.update(matches)

        # Filter out obvious non-files (URLs, examples, etc.)
        filtered = []
        for f in files:
            # Skip URLs
            if f.startswith(("http://", "https://", "ftp://")):
                continue
            # Skip obvious placeholders
            if any(placeholder in f.lower() for placeholder in ["example", "placeholder", "xxx", "your_"]):
                continue
            filtered.append(f)

        return filtered

    def _verify_python_syntax(self, path: Path) -> tuple[bool, str]:
        """
        Verify Python file has valid syntax.

        Args:
            path: Path to Python file

        Returns:
            Tuple of (success, message)
        """
        try:
            content = path.read_text(encoding="utf-8")
            ast.parse(content)
            return True, f"Syntax OK: {path.name}"
        except SyntaxError as e:
            return False, f"Syntax error in {path.name} line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Cannot read {path.name}: {e}"

    def _verify_json_syntax(self, path: Path) -> tuple[bool, str]:
        """
        Verify JSON file is valid.

        Args:
            path: Path to JSON file

        Returns:
            Tuple of (success, message)
        """
        import json

        try:
            content = path.read_text(encoding="utf-8")
            json.loads(content)
            return True, f"JSON valid: {path.name}"
        except json.JSONDecodeError as e:
            return False, f"JSON error in {path.name} line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Cannot read {path.name}: {e}"
