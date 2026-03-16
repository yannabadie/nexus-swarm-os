"""
Mutation Parser V7 - Format SEARCH/REPLACE

Parses mutation blocks in SEARCH/REPLACE format (like Claude Code, aider).
This format preserves exact indentation unlike JSON with escaped \\n.

Format:
```
FILE: path/to/file.py
<<<<<<< SEARCH
def old_function():
    return 42
=======
def old_function():
    return optimized_result
>>>>>>> REPLACE
```

For APPEND operations (no SEARCH block):
```
FILE: path/to/file.py
<<<<<<< APPEND
def new_function():
    return 123
>>>>>>> END
```

Usage:
    from core.intelligence.evolution.mutation_parser import MutationParser, Mutation

    parser = MutationParser()
    mutations = parser.parse(raw_text)

    for mutation in mutations:
        print(f"File: {mutation.file}")
        print(f"Operation: {mutation.operation}")
        print(f"Search: {mutation.search}")
        print(f"Replace: {mutation.replace}")
"""

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Mutation:
    """Represents a single file mutation."""

    file: str
    operation: str  # "REPLACE" or "APPEND"
    search: str | None  # Content to find (None for APPEND)
    replace: str  # New content
    reason: str | None = None
    expected_asi_impact: float = 0.02

    def to_dict(self) -> dict:
        """Convert to legacy JSON format for compatibility."""
        result = {
            "file": self.file,
            "operation": self.operation,
            "change": self.replace,
            "reason": self.reason or "Mutation applied",
            "expected_asi_impact": self.expected_asi_impact,
        }
        if self.operation == "REPLACE" and self.search:
            # Include full search content for reliable matching
            result["search_block"] = self.search
            # Also include first line as target for legacy fallback
            first_line = self.search.split("\n")[0].strip()
            result["target"] = first_line
        return result


class MutationParser:
    """
    Parser for SEARCH/REPLACE mutation format.

    This format is more reliable than JSON for code mutations because:
    1. Preserves exact indentation (no \\n escaping)
    2. Familiar to LLMs (used by Claude Code, aider, etc.)
    3. Easy to review (diff-like format)
    """

    # Regex patterns
    FILE_PATTERN = re.compile(r"^FILE:\s*(.+?)\s*$", re.MULTILINE)
    REASON_PATTERN = re.compile(r"^REASON:\s*(.+?)$", re.MULTILINE)
    IMPACT_PATTERN = re.compile(r"^IMPACT:\s*([\d.]+)\s*$", re.MULTILINE)

    # Block markers
    SEARCH_START = "<<<<<<< SEARCH"
    APPEND_START = "<<<<<<< APPEND"
    SEPARATOR = "======="
    REPLACE_END = ">>>>>>> REPLACE"
    APPEND_END = ">>>>>>> END"

    def __init__(self):
        pass

    def parse(self, text: str) -> list[Mutation]:
        """
        Parse mutation text into list of Mutation objects.

        Args:
            text: Raw mutation text containing one or more mutation blocks

        Returns:
            List of Mutation objects
        """
        mutations = []

        # Pre-process: Extract content from Gemini JSON wrapper if present
        text = self._extract_from_json_wrapper(text)

        # Split by FILE: markers
        file_blocks = self._split_by_file(text)

        for file_path, block_content in file_blocks:
            # Parse each block
            parsed = self._parse_block(file_path, block_content)
            if parsed:
                mutations.append(parsed)

        return mutations

    def _extract_from_json_wrapper(self, text: str) -> str:
        """
        Extract mutation content from Gemini multi-layer wrapper.

        Gemini CLI wraps output in multiple layers:
        1. Outer JSON: {"response": "```json\\n{...}\\n```", "stats": {...}}
        2. Markdown code block: ```json\\n{...}\\n```
        3. Inner JSON: {"sender": "Gemini", "content": "FILE:..."}

        The inner JSON often has malformed escaping, so we use regex extraction.
        """
        import json

        # V7.5 HIVE MIND: Use robust extractor
        from core.utils.json_extractor import extract_json_safe as robust_extract_json

        working_text = text

        # LAYER 1: Extract from outer {"response": "..."} wrapper
        outer, _ = robust_extract_json(working_text)
        if outer and isinstance(outer, dict) and "response" in outer:
            working_text = outer["response"]

        # LAYER 2: Extract from markdown code blocks
        code_block_pattern = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)
        code_matches = code_block_pattern.findall(working_text)
        if code_matches:
            working_text = "\n\n".join(code_matches)

        # LAYER 3: Try JSON parsing first (clean case)
        inner, _ = robust_extract_json(working_text)
        if inner and isinstance(inner, dict) and "content" in inner:
            content = inner["content"]
            if "FILE:" in content or "<<<<<<< SEARCH" in content:
                return content

        # LAYER 3 FALLBACK: Regex extraction for malformed JSON
        # Extract content between "content": " and the closing patterns
        # This handles cases where content has unescaped newlines
        content_start_pattern = re.compile(r'"content"\s*:\s*"', re.DOTALL)
        match = content_start_pattern.search(working_text)

        if match:
            start_pos = match.end()
            # Find the end by looking for typical JSON field endings
            # The content ends at ",\n  " or "\n}" patterns
            remaining = working_text[start_pos:]

            # Look for end patterns: '",\n' followed by a new field, or '"\n}'
            end_patterns = [
                ('",\n  "next_agent"', -1),
                ('",\n  "status"', -1),
                ('",\n  "action_summary"', -1),
                ('"\n}', -1),
            ]

            end_pos = len(remaining)
            for pattern, _offset in end_patterns:
                idx = remaining.find(pattern)
                if idx != -1 and idx < end_pos:
                    end_pos = idx

            if end_pos < len(remaining):
                raw_content = remaining[:end_pos]
                # Decode JSON escape sequences
                try:
                    decoded = json.loads(f'"{raw_content}"')
                    if "FILE:" in decoded or "<<<<<<< SEARCH" in decoded:
                        return decoded
                except json.JSONDecodeError:
                    # If JSON decode fails, try manual unescape
                    decoded = raw_content.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
                    if "FILE:" in decoded or "<<<<<<< SEARCH" in decoded:
                        return decoded

        # If FILE: or SEARCH markers are directly in text, return as-is
        if "FILE:" in working_text or "<<<<<<< SEARCH" in working_text:
            return working_text

        # Last resort: return original
        return text

    def _split_by_file(self, text: str) -> list[tuple[str, str]]:
        """Split text into (file_path, block_content) tuples."""
        results = []

        # Find all FILE: markers
        file_matches = list(self.FILE_PATTERN.finditer(text))

        if not file_matches:
            # Try to parse as single block without FILE: marker
            # (for backwards compatibility or simple cases)
            return [("", text)]

        for i, match in enumerate(file_matches):
            file_path = match.group(1).strip()
            start = match.end()

            # Find end of this block (next FILE: or end of text)
            if i + 1 < len(file_matches):
                end = file_matches[i + 1].start()
            else:
                end = len(text)

            block_content = text[start:end].strip()
            results.append((file_path, block_content))

        return results

    def _parse_block(self, file_path: str, content: str) -> Mutation | None:
        """Parse a single mutation block."""

        # Extract optional metadata
        reason = None
        reason_match = self.REASON_PATTERN.search(content)
        if reason_match:
            reason = reason_match.group(1).strip()

        impact = 0.02
        impact_match = self.IMPACT_PATTERN.search(content)
        if impact_match:
            with contextlib.suppress(ValueError):
                impact = float(impact_match.group(1))

        # Determine operation type and parse accordingly
        if self.SEARCH_START in content:
            return self._parse_replace_block(file_path, content, reason, impact)
        elif self.APPEND_START in content:
            return self._parse_append_block(file_path, content, reason, impact)
        else:
            # Legacy: treat entire content as append
            return Mutation(
                file=file_path,
                operation="APPEND",
                search=None,
                replace=content.strip(),
                reason=reason,
                expected_asi_impact=impact,
            )

    def _parse_replace_block(self, file_path: str, content: str, reason: str | None, impact: float) -> Mutation | None:
        """Parse a SEARCH/REPLACE block."""

        # Find markers
        search_start = content.find(self.SEARCH_START)
        separator = content.find(self.SEPARATOR)
        replace_end = content.find(self.REPLACE_END)

        if search_start == -1 or separator == -1 or replace_end == -1:
            return None

        # Extract search content (between SEARCH_START and SEPARATOR)
        search_content = content[search_start + len(self.SEARCH_START) : separator]
        search_content = self._clean_block_content(search_content)

        # Extract replace content (between SEPARATOR and REPLACE_END)
        replace_content = content[separator + len(self.SEPARATOR) : replace_end]
        replace_content = self._clean_block_content(replace_content)

        if not search_content or not replace_content:
            return None

        return Mutation(
            file=file_path,
            operation="REPLACE",
            search=search_content,
            replace=replace_content,
            reason=reason,
            expected_asi_impact=impact,
        )

    def _parse_append_block(self, file_path: str, content: str, reason: str | None, impact: float) -> Mutation | None:
        """Parse an APPEND block."""

        # Find markers
        append_start = content.find(self.APPEND_START)
        append_end = content.find(self.APPEND_END)

        if append_start == -1 or append_end == -1:
            return None

        # Extract append content
        append_content = content[append_start + len(self.APPEND_START) : append_end]
        append_content = self._clean_block_content(append_content)

        if not append_content:
            return None

        return Mutation(
            file=file_path,
            operation="APPEND",
            search=None,
            replace=append_content,
            reason=reason,
            expected_asi_impact=impact,
        )

    def _clean_block_content(self, content: str) -> str:
        """Clean block content by removing leading/trailing empty lines."""
        lines = content.split("\n")

        # Remove leading empty lines
        while lines and not lines[0].strip():
            lines.pop(0)

        # Remove trailing empty lines
        while lines and not lines[-1].strip():
            lines.pop()

        return "\n".join(lines)

    def format_mutation(self, mutation: Mutation) -> str:
        """
        Format a Mutation object back to SEARCH/REPLACE text format.
        Useful for generating examples or debugging.
        """
        lines = [f"FILE: {mutation.file}"]

        if mutation.reason:
            lines.append(f"REASON: {mutation.reason}")

        lines.append(f"IMPACT: {mutation.expected_asi_impact}")
        lines.append("")

        if mutation.operation == "REPLACE" and mutation.search:
            lines.append(self.SEARCH_START)
            lines.append(mutation.search)
            lines.append(self.SEPARATOR)
            lines.append(mutation.replace)
            lines.append(self.REPLACE_END)
        else:
            lines.append(self.APPEND_START)
            lines.append(mutation.replace)
            lines.append(self.APPEND_END)

        return "\n".join(lines)


def apply_mutation(file_path: Path, mutation: Mutation) -> tuple[bool, str]:
    """
    Apply a mutation to a file.

    Args:
        file_path: Path to the file to mutate
        mutation: Mutation to apply

    Returns:
        Tuple of (success, message)
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    original_content = file_path.read_text(encoding="utf-8")

    if mutation.operation == "REPLACE":
        if not mutation.search:
            return False, "REPLACE operation requires search content"

        # Find the search content in the file
        if mutation.search not in original_content:
            # Try with normalized whitespace
            search_normalized = " ".join(mutation.search.split())
            content_normalized = " ".join(original_content.split())
            if search_normalized not in content_normalized:
                return False, f"Search content not found in {file_path}"

        # Replace
        new_content = original_content.replace(mutation.search, mutation.replace, 1)

    else:  # APPEND
        new_content = original_content.rstrip() + "\n\n" + mutation.replace + "\n"

    # Validate Python syntax if applicable
    if file_path.suffix == ".py":
        import ast

        try:
            ast.parse(new_content)
        except SyntaxError as e:
            return False, f"Mutation would create invalid Python: {e}"

    # Write
    file_path.write_text(new_content, encoding="utf-8")
    return True, f"Successfully applied {mutation.operation} to {file_path}"


# Example/test
if __name__ == "__main__":
    example = '''
FILE: core/utils.py
REASON: Add utility function for scoring
IMPACT: 0.03

<<<<<<< SEARCH
def calculate_score(x):
    return x * 2
=======
def calculate_score(x):
    """Calculate score with improved algorithm."""
    return x * 2.5 + 10
>>>>>>> REPLACE

FILE: core/helpers.py
REASON: Add new helper function
IMPACT: 0.02

<<<<<<< APPEND
def new_helper():
    """A new helper function."""
    return 42
>>>>>>> END
'''

    parser = MutationParser()
    mutations = parser.parse(example)

    print(f"Parsed {len(mutations)} mutations:\n")
    for m in mutations:
        print(f"  File: {m.file}")
        print(f"  Operation: {m.operation}")
        print(f"  Reason: {m.reason}")
        print(f"  Impact: {m.expected_asi_impact}")
        if m.search:
            print(f"  Search: {m.search[:50]}...")
        print(f"  Replace: {m.replace[:50]}...")
        print()
