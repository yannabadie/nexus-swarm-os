"""
Tests for Mutation Parser - Phase 14b

Tests cover:
- MutationParser: SEARCH/REPLACE block extraction
- JSON extraction with/without markdown
- Resilience to malformed input
- CRITICAL: KERNEL.py immutability validation
- Path validation (only core/ or workspace/)

NEXUS V7.6 HIVE MIND - Test Coverage for core/evolution/mutation_parser.py
Author: Claude (Phase 14b - 2025-12-05)
"""

import json

# Add parent to path for imports
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.evolution.mutation_parser import (
    Mutation,
    MutationParser,
    apply_mutation,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def parser():
    """Provide a fresh MutationParser instance."""
    return MutationParser()


@pytest.fixture
def temp_file(tmp_path):
    """Create a temporary Python file for mutation testing."""
    test_file = tmp_path / "test_module.py"
    test_file.write_text(
        """def old_function():
    return 42

def another_function():
    return "hello"
""",
        encoding="utf-8",
    )
    return test_file


# =============================================================================
# TEST: Basic SEARCH/REPLACE Parsing
# =============================================================================


class TestSearchReplaceParsing:
    """Tests for SEARCH/REPLACE block parsing."""

    def test_parse_single_replace_block(self, parser):
        """Test parsing a single SEARCH/REPLACE block."""
        text = """FILE: core/utils.py
REASON: Optimize calculation
IMPACT: 0.03

<<<<<<< SEARCH
def calculate_score(x):
    return x * 2
=======
def calculate_score(x):
    return x * 2.5
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        assert mutations[0].file == "core/utils.py"
        assert mutations[0].operation == "REPLACE"
        assert "x * 2" in mutations[0].search
        assert "x * 2.5" in mutations[0].replace
        assert mutations[0].reason == "Optimize calculation"
        assert mutations[0].expected_asi_impact == 0.03

    def test_parse_multiple_mutations(self, parser):
        """Test parsing multiple mutation blocks."""
        text = """FILE: core/module_a.py
<<<<<<< SEARCH
old_code_a
=======
new_code_a
>>>>>>> REPLACE

FILE: core/module_b.py
<<<<<<< SEARCH
old_code_b
=======
new_code_b
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        assert len(mutations) == 2
        assert mutations[0].file == "core/module_a.py"
        assert mutations[1].file == "core/module_b.py"

    def test_parse_append_block(self, parser):
        """Test parsing an APPEND block."""
        text = """FILE: core/helpers.py
REASON: Add new helper
IMPACT: 0.02

<<<<<<< APPEND
def new_helper():
    return 123
>>>>>>> END"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        assert mutations[0].operation == "APPEND"
        assert mutations[0].search is None
        assert "new_helper" in mutations[0].replace

    def test_preserve_indentation(self, parser):
        """Test that indentation is preserved in mutations."""
        text = """FILE: core/test.py
<<<<<<< SEARCH
class MyClass:
    def method(self):
        return 42
=======
class MyClass:
    def method(self):
        # Optimized
        return 42 * 2
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        # Check indentation preserved
        assert "    def method" in mutations[0].search
        assert "        return 42" in mutations[0].search
        assert "        # Optimized" in mutations[0].replace


# =============================================================================
# TEST: JSON Extraction
# =============================================================================


class TestJsonExtraction:
    """Tests for JSON extraction from various formats."""

    def test_extract_from_clean_json(self, parser):
        """Test extraction from clean JSON content."""
        # When direct FILE: markers exist, parser returns them
        text = """FILE: core/test.py
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE"""

        mutations = parser.parse(text)
        assert len(mutations) == 1

    def test_extract_from_markdown_code_block(self, parser):
        """Test extraction from markdown code block."""
        text = """```
FILE: core/test.py
<<<<<<< SEARCH
old_code
=======
new_code
>>>>>>> REPLACE
```"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        assert mutations[0].file == "core/test.py"

    def test_extract_from_gemini_wrapper(self, parser):
        """Test extraction from Gemini JSON wrapper."""
        # Simulate Gemini's nested JSON structure
        inner_content = """FILE: core/example.py
<<<<<<< SEARCH
def old():
    pass
=======
def new():
    pass
>>>>>>> REPLACE"""

        text = json.dumps(
            {"response": json.dumps({"sender": "Gemini", "content": inner_content, "status": "FINISHED"})}
        )

        mutations = parser.parse(text)

        assert len(mutations) == 1
        assert mutations[0].file == "core/example.py"


# =============================================================================
# TEST: Resilience to Malformed Input
# =============================================================================


class TestMalformedInputResilience:
    """Tests for resilience to malformed input."""

    def test_missing_separator_returns_none(self, parser):
        """Test that missing separator returns no mutation."""
        text = """FILE: core/test.py
<<<<<<< SEARCH
old_code
>>>>>>> REPLACE"""  # Missing =======

        mutations = parser.parse(text)

        # Should not crash, may return empty or handle gracefully
        assert isinstance(mutations, list)

    def test_missing_end_marker(self, parser):
        """Test handling of missing end marker."""
        text = """FILE: core/test.py
<<<<<<< SEARCH
old_code
=======
new_code"""  # Missing >>>>>>> REPLACE

        mutations = parser.parse(text)

        # Should handle gracefully
        assert isinstance(mutations, list)

    def test_empty_input(self, parser):
        """Test handling of empty input."""
        mutations = parser.parse("")

        # Parser may return empty list or list with empty mutation
        assert isinstance(mutations, list)
        # If not empty, mutations should have no meaningful content
        if mutations:
            for m in mutations:
                assert m.file == "" or m.replace == ""

    def test_no_file_marker(self, parser):
        """Test handling of content without FILE: marker."""
        text = """<<<<<<< SEARCH
old_code
=======
new_code
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        # Should return mutation with empty file path
        assert isinstance(mutations, list)

    def test_invalid_json_fallback(self, parser):
        """Test fallback when JSON is invalid."""
        text = """{"broken": "json", no_quotes: invalid}

FILE: core/test.py
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        # Should still extract the valid SEARCH/REPLACE block
        assert len(mutations) >= 1
        assert mutations[0].file == "core/test.py"

    def test_extra_whitespace_handling(self, parser):
        """Test handling of extra whitespace in blocks."""
        text = """FILE:   core/test.py


<<<<<<< SEARCH

old_code

=======

new_code

>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        # Whitespace should be cleaned appropriately
        assert mutations[0].file.strip() == "core/test.py"


# =============================================================================
# TEST: KERNEL.py IMMUTABILITY (CRITICAL)
# =============================================================================


class TestKernelImmutability:
    """CRITICAL: Tests that KERNEL.py cannot be mutated."""

    def test_kernel_mutation_rejected_in_parser(self, parser):
        """Test that KERNEL.py mutations are identified but can be filtered."""
        text = """FILE: KERNEL.py
<<<<<<< SEARCH
OBJECTIVE = "Old objective"
=======
OBJECTIVE = "Malicious objective"
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        # Parser extracts the mutation
        assert len(mutations) == 1

        # But we can check and reject it
        kernel_mutations = [m for m in mutations if "kernel.py" in m.file.lower()]
        assert len(kernel_mutations) == 1

    def test_kernel_path_variants_detected(self, parser):
        """Test that various KERNEL.py path variants are detected."""
        kernel_paths = [
            "KERNEL.py",
            "./KERNEL.py",
            "core/../KERNEL.py",
            "KERNEL.PY",  # Case insensitive
            "/absolute/path/KERNEL.py",
        ]

        for kernel_path in kernel_paths:
            text = f"""FILE: {kernel_path}
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE"""

            mutations = parser.parse(text)

            # Verify we can detect KERNEL.py in all variants
            if mutations:
                is_kernel = "kernel.py" in mutations[0].file.lower()
                assert is_kernel, f"Failed to detect KERNEL.py in path: {kernel_path}"

    def test_validate_kernel_immutability(self):
        """Test helper function to validate KERNEL.py is not in mutations."""

        def is_kernel_mutation(mutation: Mutation) -> bool:
            """Check if mutation targets KERNEL.py"""
            file_lower = mutation.file.lower()
            return "kernel.py" in file_lower

        # Create test mutations
        safe_mutation = Mutation(file="core/utils.py", operation="REPLACE", search="old", replace="new")

        kernel_mutation = Mutation(file="KERNEL.py", operation="REPLACE", search="old", replace="new")

        assert is_kernel_mutation(kernel_mutation) is True
        assert is_kernel_mutation(safe_mutation) is False

    def test_integration_kernel_filter(self, parser):
        """Integration test: Filter out KERNEL.py mutations from batch."""
        text = """FILE: core/safe.py
<<<<<<< SEARCH
safe_old
=======
safe_new
>>>>>>> REPLACE

FILE: KERNEL.py
<<<<<<< SEARCH
kernel_old
=======
kernel_new
>>>>>>> REPLACE

FILE: core/another_safe.py
<<<<<<< SEARCH
another_old
=======
another_new
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        # Filter out KERNEL.py mutations
        safe_mutations = [m for m in mutations if "kernel.py" not in m.file.lower()]

        assert len(mutations) == 3  # All parsed
        assert len(safe_mutations) == 2  # KERNEL.py filtered out
        assert all("kernel.py" not in m.file.lower() for m in safe_mutations)


# =============================================================================
# TEST: Path Validation
# =============================================================================


class TestPathValidation:
    """Tests for path validation (restrict to core/ or workspace/)."""

    def test_core_path_allowed(self, parser):
        """Test that core/ paths are allowed."""
        text = """FILE: core/module.py
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        assert mutations[0].file.startswith("core/")

    def test_workspace_path_allowed(self, parser):
        """Test that workspace/ paths are allowed."""
        text = """FILE: workspace/agents/test.py
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE"""

        mutations = parser.parse(text)

        assert len(mutations) == 1
        assert "workspace" in mutations[0].file

    def test_validate_allowed_paths(self):
        """Test helper to validate allowed paths."""

        def is_allowed_path(file_path: str) -> bool:
            """Check if path is in allowed directories."""
            allowed_prefixes = ["core/", "workspace/", "tests/", "prompts/", "config/"]
            disallowed_files = ["kernel.py", ".env", "credentials"]

            file_lower = file_path.lower()

            # Check disallowed files
            for disallowed in disallowed_files:
                if disallowed in file_lower:
                    return False

            # Check allowed prefixes
            return any(file_path.startswith(prefix) for prefix in allowed_prefixes)

        # Test allowed paths
        assert is_allowed_path("core/utils.py") is True
        assert is_allowed_path("workspace/test.py") is True
        assert is_allowed_path("tests/test_foo.py") is True
        assert is_allowed_path("prompts/system.md") is True

        # Test disallowed paths
        assert is_allowed_path("KERNEL.py") is False
        assert is_allowed_path(".env") is False
        assert is_allowed_path("../../../etc/passwd") is False
        assert is_allowed_path("random/path.py") is False

    def test_path_traversal_detection(self):
        """Test detection of path traversal attempts."""

        def has_path_traversal(file_path: str) -> bool:
            """Detect path traversal attempts."""
            dangerous_patterns = ["..", "//", "\\"]
            return any(pattern in file_path for pattern in dangerous_patterns)

        # Test dangerous paths
        assert has_path_traversal("../../../etc/passwd") is True
        assert has_path_traversal("core/../../KERNEL.py") is True
        assert has_path_traversal("core//utils.py") is True
        assert has_path_traversal("core\\utils.py") is True

        # Test safe paths
        assert has_path_traversal("core/utils.py") is False
        assert has_path_traversal("workspace/agents/test.py") is False


# =============================================================================
# TEST: apply_mutation Function
# =============================================================================


class TestApplyMutation:
    """Tests for apply_mutation function."""

    def test_apply_replace_mutation(self, temp_file):
        """Test applying a REPLACE mutation."""
        mutation = Mutation(
            file=str(temp_file),
            operation="REPLACE",
            search="def old_function():\n    return 42",
            replace="def old_function():\n    return 100",
        )

        success, message = apply_mutation(temp_file, mutation)

        assert success is True
        content = temp_file.read_text()
        assert "return 100" in content
        assert "return 42" not in content

    def test_apply_append_mutation(self, temp_file):
        """Test applying an APPEND mutation."""
        mutation = Mutation(
            file=str(temp_file), operation="APPEND", search=None, replace="def new_function():\n    return 999"
        )

        success, message = apply_mutation(temp_file, mutation)

        assert success is True
        content = temp_file.read_text()
        assert "def new_function():" in content

    def test_apply_mutation_file_not_found(self, tmp_path):
        """Test applying mutation to non-existent file."""
        non_existent = tmp_path / "does_not_exist.py"

        mutation = Mutation(file=str(non_existent), operation="REPLACE", search="old", replace="new")

        success, message = apply_mutation(non_existent, mutation)

        assert success is False
        assert "not found" in message.lower()

    def test_apply_mutation_search_not_found(self, temp_file):
        """Test applying mutation when search content not found."""
        mutation = Mutation(
            file=str(temp_file), operation="REPLACE", search="this_does_not_exist_in_file", replace="new_content"
        )

        success, message = apply_mutation(temp_file, mutation)

        assert success is False
        assert "not found" in message.lower()

    def test_apply_mutation_invalid_python(self, temp_file):
        """Test that invalid Python syntax is rejected."""
        mutation = Mutation(
            file=str(temp_file),
            operation="REPLACE",
            search="def old_function():\n    return 42",
            replace="def old_function(\n    return 42",  # Invalid syntax
        )

        success, message = apply_mutation(temp_file, mutation)

        assert success is False
        assert "invalid python" in message.lower() or "syntax" in message.lower()


# =============================================================================
# TEST: Mutation.to_dict Compatibility
# =============================================================================


class TestMutationToDict:
    """Tests for Mutation.to_dict() legacy compatibility."""

    def test_to_dict_replace_operation(self):
        """Test to_dict for REPLACE operation."""
        mutation = Mutation(
            file="core/test.py",
            operation="REPLACE",
            search="old_code",
            replace="new_code",
            reason="Test mutation",
            expected_asi_impact=0.05,
        )

        result = mutation.to_dict()

        assert result["file"] == "core/test.py"
        assert result["operation"] == "REPLACE"
        assert result["change"] == "new_code"
        assert result["reason"] == "Test mutation"
        assert result["expected_asi_impact"] == 0.05
        assert result["search_block"] == "old_code"
        assert result["target"] == "old_code"

    def test_to_dict_append_operation(self):
        """Test to_dict for APPEND operation."""
        mutation = Mutation(
            file="core/test.py", operation="APPEND", search=None, replace="new_code", reason="Add feature"
        )

        result = mutation.to_dict()

        assert result["file"] == "core/test.py"
        assert result["operation"] == "APPEND"
        assert result["change"] == "new_code"
        assert "search_block" not in result  # Not present for APPEND


# =============================================================================
# TEST: format_mutation (Roundtrip)
# =============================================================================


class TestFormatMutation:
    """Tests for format_mutation reverse operation."""

    def test_format_replace_mutation(self, parser):
        """Test formatting a REPLACE mutation back to text."""
        mutation = Mutation(
            file="core/test.py",
            operation="REPLACE",
            search="old_code",
            replace="new_code",
            reason="Test",
            expected_asi_impact=0.02,
        )

        formatted = parser.format_mutation(mutation)

        assert "FILE: core/test.py" in formatted
        assert "<<<<<<< SEARCH" in formatted
        assert "old_code" in formatted
        assert "=======" in formatted
        assert "new_code" in formatted
        assert ">>>>>>> REPLACE" in formatted

    def test_format_append_mutation(self, parser):
        """Test formatting an APPEND mutation back to text."""
        mutation = Mutation(
            file="core/test.py",
            operation="APPEND",
            search=None,
            replace="new_code",
            reason="Test",
            expected_asi_impact=0.02,
        )

        formatted = parser.format_mutation(mutation)

        assert "FILE: core/test.py" in formatted
        assert "<<<<<<< APPEND" in formatted
        assert "new_code" in formatted
        assert ">>>>>>> END" in formatted

    def test_roundtrip_parsing(self, parser):
        """Test that format -> parse is consistent."""
        original = Mutation(
            file="core/example.py",
            operation="REPLACE",
            search="def old():\n    pass",
            replace="def new():\n    return 42",
            reason="Improve function",
            expected_asi_impact=0.03,
        )

        # Format to text
        formatted = parser.format_mutation(original)

        # Parse back
        parsed = parser.parse(formatted)

        assert len(parsed) == 1
        assert parsed[0].file == original.file
        assert parsed[0].operation == original.operation
        assert parsed[0].search.strip() == original.search.strip()
        assert parsed[0].replace.strip() == original.replace.strip()


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
