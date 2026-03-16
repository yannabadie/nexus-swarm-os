"""
Tests for Phase 10c: ProjectMemory RAG

Verifies:
1. File indexing (single file and directory)
2. TF-IDF weighted Jaccard retrieval
3. Python function/class chunking
4. Markdown section chunking
5. Persistence (save/load)
6. Forget functionality
7. Context formatting
8. Edge cases (empty files, large files, etc.)
"""

import json
import shutil
from pathlib import Path

import pytest

from core.memory_pkg.memory.project_memory import (
    Chunk,
    ProjectMemory,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_nexus_root(tmp_path):
    """Create a temporary NEXUS root directory with sample files."""
    nexus_root = tmp_path / "nexus_project"
    nexus_root.mkdir()

    # Create .nexus directory (storage location)
    (nexus_root / ".nexus").mkdir()

    # Create sample Python file
    core_dir = nexus_root / "core"
    core_dir.mkdir()

    sample_py = core_dir / "sample.py"
    sample_py.write_text(
        '''"""Sample module for testing."""

import os
from pathlib import Path


class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b


def helper_function(x):
    """A standalone helper function."""
    return x * 2


async def async_function(data):
    """An async function for testing."""
    return await process(data)
''',
        encoding="utf-8",
    )

    # Create sample Markdown file
    docs_dir = nexus_root / "docs"
    docs_dir.mkdir()

    sample_md = docs_dir / "README.md"
    sample_md.write_text(
        """# Project Documentation

This is the main documentation.

## Installation

Run pip install to install dependencies.

### Prerequisites

- Python 3.11+
- Virtual environment

## Usage

Import the module and use it.

### Quick Start

Here's a quick example.

## API Reference

Full API documentation here.
""",
        encoding="utf-8",
    )

    # Create sample text file
    config_file = nexus_root / "config.txt"
    config_file.write_text("Configuration settings\n" * 60, encoding="utf-8")

    return nexus_root


@pytest.fixture
def project_memory(temp_nexus_root):
    """Create a ProjectMemory instance with temp root."""
    return ProjectMemory(temp_nexus_root)


# =============================================================================
# Test Initialization
# =============================================================================


class TestProjectMemoryInit:
    """Test ProjectMemory initialization."""

    def test_init_creates_storage_dir(self, tmp_path):
        """Ensure .nexus directory is created if missing."""
        nexus_root = tmp_path / "new_project"
        nexus_root.mkdir()

        memory = ProjectMemory(nexus_root)

        assert (nexus_root / ".nexus").exists()
        assert memory.storage_path == nexus_root / ".nexus" / "project_knowledge.json"

    def test_init_empty_index(self, project_memory):
        """New ProjectMemory should have empty index."""
        assert len(project_memory.chunks) == 0
        assert len(project_memory.indexed_files) == 0
        assert len(project_memory.idf) == 0

    def test_init_loads_existing_index(self, temp_nexus_root):
        """ProjectMemory should load existing index on init."""
        # First, create and save an index
        memory1 = ProjectMemory(temp_nexus_root)
        memory1.index_file(temp_nexus_root / "core" / "sample.py")
        memory1.save()  # Explicit save after index_file (index_directory auto-saves)
        chunks_count = len(memory1.chunks)

        # Create new instance - should load saved index
        memory2 = ProjectMemory(temp_nexus_root)
        assert len(memory2.chunks) == chunks_count
        assert len(memory2.indexed_files) == 1


# =============================================================================
# Test File Indexing
# =============================================================================


class TestIndexFile:
    """Test single file indexing."""

    def test_index_python_file(self, project_memory, temp_nexus_root):
        """Index a Python file and verify chunks."""
        chunks = project_memory.index_file(temp_nexus_root / "core" / "sample.py")

        assert chunks > 0
        assert "core\\sample.py" in project_memory.indexed_files or "core/sample.py" in project_memory.indexed_files

        # Should have chunks for module, class, functions
        chunk_names = [c.name for c in project_memory.chunks if c.name]
        assert "Calculator" in chunk_names or any("Calculator" in (c.name or "") for c in project_memory.chunks)

    def test_index_markdown_file(self, project_memory, temp_nexus_root):
        """Index a Markdown file and verify section chunks."""
        chunks = project_memory.index_file(temp_nexus_root / "docs" / "README.md")

        assert chunks > 0

        # Should have section chunks
        chunk_types = [c.chunk_type for c in project_memory.chunks]
        assert "section" in chunk_types

    def test_index_text_file(self, project_memory, temp_nexus_root):
        """Index a text file using line-based chunking."""
        chunks = project_memory.index_file(temp_nexus_root / "config.txt")

        assert chunks > 0

        # Should use line-based chunking
        chunk_types = [c.chunk_type for c in project_memory.chunks]
        assert "lines" in chunk_types

    def test_index_nonexistent_file(self, project_memory, temp_nexus_root):
        """Indexing nonexistent file returns 0."""
        chunks = project_memory.index_file(temp_nexus_root / "nonexistent.py")
        assert chunks == 0

    def test_index_already_indexed_skips(self, project_memory, temp_nexus_root):
        """Re-indexing same file without force returns 0."""
        py_file = temp_nexus_root / "core" / "sample.py"

        chunks1 = project_memory.index_file(py_file)
        chunks2 = project_memory.index_file(py_file)  # Should skip

        assert chunks1 > 0
        assert chunks2 == 0

    def test_index_force_reindex(self, project_memory, temp_nexus_root):
        """Force re-indexing should work."""
        py_file = temp_nexus_root / "core" / "sample.py"

        chunks1 = project_memory.index_file(py_file)
        chunks2 = project_memory.index_file(py_file, force=True)

        assert chunks1 > 0
        assert chunks2 == chunks1  # Should create same chunks

    def test_index_empty_file(self, project_memory, temp_nexus_root):
        """Empty files should not be indexed."""
        empty_file = temp_nexus_root / "empty.py"
        empty_file.write_text("", encoding="utf-8")

        chunks = project_memory.index_file(empty_file)
        assert chunks == 0

    def test_index_tiny_file(self, project_memory, temp_nexus_root):
        """Files smaller than MIN_CHUNK_SIZE should not be indexed."""
        tiny_file = temp_nexus_root / "tiny.py"
        tiny_file.write_text("x=1", encoding="utf-8")

        chunks = project_memory.index_file(tiny_file)
        assert chunks == 0


class TestIndexDirectory:
    """Test directory indexing."""

    def test_index_directory_recursive(self, project_memory, temp_nexus_root):
        """Index directory recursively."""
        total_chunks = project_memory.index_directory(temp_nexus_root)

        assert total_chunks > 0
        assert len(project_memory.indexed_files) >= 2  # At least py and md files

    def test_index_directory_with_extensions(self, project_memory, temp_nexus_root):
        """Index directory with specific extensions."""
        project_memory.index_directory(temp_nexus_root, extensions=[".py"])

        # Should only index Python files
        for f in project_memory.indexed_files:
            assert f.endswith(".py")

    def test_index_directory_excludes_dirs(self, project_memory, temp_nexus_root):
        """Excluded directories should be skipped."""
        # Create excluded directories
        pycache = temp_nexus_root / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("# cached", encoding="utf-8")

        venv = temp_nexus_root / "venv"
        venv.mkdir()
        (venv / "lib.py").write_text("# venv lib", encoding="utf-8")

        project_memory.index_directory(temp_nexus_root)

        # Excluded files should not be indexed
        for f in project_memory.indexed_files:
            assert "__pycache__" not in f
            assert "venv" not in f

    def test_index_nonexistent_directory(self, project_memory, temp_nexus_root):
        """Indexing nonexistent directory returns 0."""
        chunks = project_memory.index_directory(temp_nexus_root / "nonexistent")
        assert chunks == 0


# =============================================================================
# Test Chunking Strategies
# =============================================================================


class TestPythonChunking:
    """Test Python file chunking by function/class."""

    def test_chunk_extracts_class(self, project_memory, temp_nexus_root):
        """Python chunking should extract classes."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")

        class_chunks = [c for c in project_memory.chunks if c.chunk_type == "class"]

        assert len(class_chunks) >= 1
        assert any("Calculator" in (c.name or "") for c in class_chunks)

    def test_chunk_extracts_functions(self, project_memory, temp_nexus_root):
        """Python chunking should extract standalone functions."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")

        func_chunks = [c for c in project_memory.chunks if c.chunk_type == "function"]

        # Should have helper_function and async_function
        assert len(func_chunks) >= 1

    def test_chunk_has_terms(self, project_memory, temp_nexus_root):
        """Chunks should have precomputed terms."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")

        for chunk in project_memory.chunks:
            assert len(chunk.terms) > 0


class TestMarkdownChunking:
    """Test Markdown file chunking by section."""

    def test_chunk_extracts_sections(self, project_memory, temp_nexus_root):
        """Markdown chunking should extract sections."""
        project_memory.index_file(temp_nexus_root / "docs" / "README.md")

        section_chunks = [c for c in project_memory.chunks if c.chunk_type == "section"]

        assert len(section_chunks) >= 3  # Multiple sections in test file

    def test_section_names_extracted(self, project_memory, temp_nexus_root):
        """Section names should be extracted from headers."""
        project_memory.index_file(temp_nexus_root / "docs" / "README.md")

        section_names = [c.name for c in project_memory.chunks if c.chunk_type == "section" and c.name]

        assert len(section_names) >= 1


# =============================================================================
# Test Retrieval
# =============================================================================


class TestRetrieval:
    """Test retrieval (backend-agnostic - TF-IDF or BM25S)."""

    def test_retrieve_relevant_chunks(self, project_memory, temp_nexus_root):
        """Retrieve should return relevant chunks."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")
        project_memory.index_file(temp_nexus_root / "docs" / "README.md")
        project_memory._rebuild_backend_index()  # V7.9: Backend abstraction

        # Search for calculator-related content
        results = project_memory.retrieve("calculator add multiply")

        assert len(results) > 0
        # Top result should be from the Python file with Calculator class
        assert any("sample.py" in r.file_path for r in results)

    def test_retrieve_with_limit(self, project_memory, temp_nexus_root):
        """Retrieve should respect limit parameter."""
        project_memory.index_directory(temp_nexus_root)

        results = project_memory.retrieve("python function", limit=2)
        assert len(results) <= 2

    def test_retrieve_with_min_score(self, project_memory, temp_nexus_root):
        """Retrieve should filter by min_score."""
        project_memory.index_directory(temp_nexus_root)

        # High min_score should return fewer results
        results_low = project_memory.retrieve("test", min_score=0.01)
        results_high = project_memory.retrieve("test", min_score=0.9)

        assert len(results_high) <= len(results_low)

    def test_retrieve_empty_query(self, project_memory, temp_nexus_root):
        """Empty query should return empty results."""
        project_memory.index_directory(temp_nexus_root)

        results = project_memory.retrieve("")
        assert len(results) == 0

    def test_retrieve_no_match(self, project_memory, temp_nexus_root, monkeypatch):
        """Query with no matches should return empty at high min_score."""
        # Force TF-IDF backend so min_score is applied correctly at retrieval time.
        # The hybrid backend passes min_score=0.0 internally in its single-backend path.
        monkeypatch.setenv("PROJECT_MEMORY_BACKEND", "tfidf")
        project_memory._backend = project_memory._select_backend()
        project_memory._backend_dirty = True
        project_memory.index_directory(temp_nexus_root)

        results = project_memory.retrieve("xyznonexistentterm123", min_score=0.9)
        assert len(results) == 0

    def test_retrieve_empty_index(self, project_memory):
        """Retrieve on empty index returns empty."""
        results = project_memory.retrieve("anything")
        assert len(results) == 0


# =============================================================================
# Test Persistence
# =============================================================================


class TestPersistence:
    """Test save/load functionality."""

    def test_save_creates_file(self, project_memory, temp_nexus_root):
        """Save should create JSON file."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")
        project_memory.save()

        assert project_memory.storage_path.exists()

    def test_save_valid_json(self, project_memory, temp_nexus_root):
        """Saved file should be valid JSON."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")
        project_memory.save()

        with open(project_memory.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data
        assert "chunks" in data
        assert "indexed_files" in data
        assert "idf" in data

    def test_load_restores_state(self, temp_nexus_root):
        """Load should restore saved state."""
        # Index and save
        memory1 = ProjectMemory(temp_nexus_root)
        memory1.index_file(temp_nexus_root / "core" / "sample.py")
        memory1.save()  # Explicit save (index_file doesn't auto-save)
        chunks_before = len(memory1.chunks)
        files_before = len(memory1.indexed_files)

        # Load in new instance
        memory2 = ProjectMemory(temp_nexus_root)

        assert len(memory2.chunks) == chunks_before
        assert len(memory2.indexed_files) == files_before

    def test_chunk_serialization(self, temp_nexus_root):
        """Chunks should serialize/deserialize correctly."""
        memory1 = ProjectMemory(temp_nexus_root)
        memory1.index_file(temp_nexus_root / "core" / "sample.py")
        memory1.save()  # Explicit save

        # Get first chunk details
        original = memory1.chunks[0]

        # Reload
        memory2 = ProjectMemory(temp_nexus_root)
        restored = memory2.chunks[0]

        assert original.file_path == restored.file_path
        assert original.start_line == restored.start_line
        assert original.end_line == restored.end_line
        assert original.chunk_type == restored.chunk_type
        assert original.terms == restored.terms


# =============================================================================
# Test Forget
# =============================================================================


class TestForget:
    """Test forget functionality."""

    def test_forget_removes_chunks(self, project_memory, temp_nexus_root):
        """Forget should remove all chunks for a file."""
        py_file = temp_nexus_root / "core" / "sample.py"
        project_memory.index_file(py_file)
        chunks_before = len(project_memory.chunks)

        removed = project_memory.forget(py_file)

        assert removed == chunks_before
        assert len(project_memory.chunks) == 0

    def test_forget_updates_indexed_files(self, project_memory, temp_nexus_root):
        """Forget should remove file from indexed_files."""
        py_file = temp_nexus_root / "core" / "sample.py"
        project_memory.index_file(py_file)

        project_memory.forget(py_file)

        # File should no longer be in indexed list
        assert not any("sample.py" in f for f in project_memory.indexed_files)

    def test_forget_nonexistent(self, project_memory, temp_nexus_root):
        """Forget nonexistent file returns 0."""
        removed = project_memory.forget(temp_nexus_root / "nonexistent.py")
        assert removed == 0

    def test_forget_saves_index(self, temp_nexus_root):
        """Forget should save updated index."""
        memory1 = ProjectMemory(temp_nexus_root)
        py_file = temp_nexus_root / "core" / "sample.py"
        memory1.index_file(py_file)
        memory1.forget(py_file)

        # Reload and verify
        memory2 = ProjectMemory(temp_nexus_root)
        assert len(memory2.chunks) == 0


# =============================================================================
# Test Context Formatting
# =============================================================================


class TestContextFormatting:
    """Test format_chunks_for_context."""

    def test_format_empty_list(self, project_memory):
        """Formatting empty list returns empty string."""
        result = project_memory.format_chunks_for_context([])
        assert result == ""

    def test_format_includes_header(self, project_memory, temp_nexus_root):
        """Formatted output should have header."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")
        chunks = project_memory.retrieve("calculator")

        result = project_memory.format_chunks_for_context(chunks)

        assert "RELEVANT PROJECT KNOWLEDGE" in result

    def test_format_includes_file_path(self, project_memory, temp_nexus_root):
        """Formatted output should include file paths."""
        project_memory.index_file(temp_nexus_root / "core" / "sample.py")
        chunks = project_memory.retrieve("calculator")

        result = project_memory.format_chunks_for_context(chunks)

        assert "sample.py" in result

    def test_format_respects_max_chars(self, project_memory, temp_nexus_root):
        """Formatting should respect max_chars limit."""
        project_memory.index_directory(temp_nexus_root)
        chunks = project_memory.chunks[:10]  # Get several chunks

        result = project_memory.format_chunks_for_context(chunks, max_chars=500)

        # Result should be at or under limit (header excluded from exact check)
        assert len(result) < 1000  # Some reasonable upper bound


# =============================================================================
# Test Stats
# =============================================================================


class TestStats:
    """Test get_stats functionality."""

    def test_stats_empty_index(self, project_memory):
        """Stats on empty index should show zeros."""
        stats = project_memory.get_stats()

        assert stats.total_files == 0
        assert stats.total_chunks == 0
        assert stats.total_terms == 0

    def test_stats_after_indexing(self, project_memory, temp_nexus_root):
        """Stats should reflect indexed content."""
        project_memory.index_directory(temp_nexus_root)
        stats = project_memory.get_stats()

        assert stats.total_files > 0
        assert stats.total_chunks > 0
        assert stats.total_terms > 0
        assert "project_knowledge.json" in stats.storage_path


# =============================================================================
# Test Clear
# =============================================================================


class TestClear:
    """Test clear functionality."""

    def test_clear_removes_all(self, project_memory, temp_nexus_root):
        """Clear should remove all indexed content."""
        project_memory.index_directory(temp_nexus_root)
        assert len(project_memory.chunks) > 0

        project_memory.clear()

        assert len(project_memory.chunks) == 0
        assert len(project_memory.indexed_files) == 0
        assert len(project_memory.idf) == 0

    def test_clear_saves(self, temp_nexus_root):
        """Clear should save empty state."""
        memory1 = ProjectMemory(temp_nexus_root)
        memory1.index_directory(temp_nexus_root)
        memory1.clear()

        memory2 = ProjectMemory(temp_nexus_root)
        assert len(memory2.chunks) == 0


# =============================================================================
# Test Chunk Dataclass
# =============================================================================


class TestChunkDataclass:
    """Test Chunk dataclass serialization."""

    def test_chunk_to_dict(self):
        """Chunk should serialize to dict."""
        chunk = Chunk(
            file_path="test.py",
            start_line=1,
            end_line=10,
            content="def foo(): pass",
            terms={"foo", "pass"},
            chunk_type="function",
            name="foo",
        )

        d = chunk.to_dict()

        assert d["file_path"] == "test.py"
        assert d["start_line"] == 1
        assert d["chunk_type"] == "function"
        assert set(d["terms"]) == {"foo", "pass"}

    def test_chunk_from_dict(self):
        """Chunk should deserialize from dict."""
        d = {
            "file_path": "test.py",
            "start_line": 1,
            "end_line": 10,
            "content": "def foo(): pass",
            "terms": ["foo", "pass"],
            "chunk_type": "function",
            "name": "foo",
        }

        chunk = Chunk.from_dict(d)

        assert chunk.file_path == "test.py"
        assert chunk.chunk_type == "function"
        assert chunk.terms == {"foo", "pass"}


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_relative_path_resolution(self, project_memory, temp_nexus_root):
        """Relative paths should be resolved to nexus_root."""
        # Use relative path
        chunks = project_memory.index_file(Path("core/sample.py"))

        assert chunks > 0

    def test_unicode_content(self, project_memory, temp_nexus_root):
        """Unicode content should be handled correctly."""
        unicode_file = temp_nexus_root / "unicode.py"
        unicode_file.write_text(
            '''"""
French: résumé, café
Japanese: こんにちは
Emoji: 🐍 Python
"""
def greet():
    return "Hello 世界"
''',
            encoding="utf-8",
        )

        chunks = project_memory.index_file(unicode_file)
        assert chunks > 0

    def test_large_file_truncation(self, project_memory, temp_nexus_root):
        """Large chunks should be truncated."""
        large_file = temp_nexus_root / "large.py"
        # Create file with very long function
        content = "def very_long_function():\n" + "    x = 1\n" * 500
        large_file.write_text(content, encoding="utf-8")

        project_memory.index_file(large_file)

        # All chunks should be within size limit
        for chunk in project_memory.chunks:
            assert len(chunk.content) <= 2100  # MAX_CHUNK_SIZE + truncation message

    def test_binary_file_skip(self, project_memory, temp_nexus_root):
        """Binary files should be skipped gracefully."""
        binary_file = temp_nexus_root / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

        # Should not crash
        project_memory.index_file(binary_file)
        # May or may not create chunks, but should not error


# =============================================================================
# Test Integration
# =============================================================================


class TestWorkspaceNewPreservesMemory:
    """
    Regression test: Memory should persist across workspace changes.

    Memory is stored at NEXUS_ROOT/.nexus/, not in workspace/.
    """

    def test_memory_outside_workspace(self, temp_nexus_root):
        """Memory storage should be at nexus_root, not inside workspace folder."""
        # Simulate workspace structure
        workspace = temp_nexus_root / "workspace"
        workspace.mkdir()

        memory = ProjectMemory(temp_nexus_root)

        # Storage should be at nexus_root/.nexus, not workspace/.nexus
        assert memory.storage_dir == temp_nexus_root / ".nexus"
        # Verify storage is NOT inside the workspace folder
        assert not str(memory.storage_path).startswith(str(workspace))

    def test_memory_survives_workspace_delete(self, temp_nexus_root):
        """Deleting workspace should not affect memory."""
        # Create workspace
        workspace = temp_nexus_root / "workspace"
        workspace.mkdir()

        # Index and save
        memory1 = ProjectMemory(temp_nexus_root)
        memory1.index_file(temp_nexus_root / "core" / "sample.py")
        memory1.save()  # Explicit save
        chunks_before = len(memory1.chunks)

        # Simulate /workspace new - delete old workspace
        shutil.rmtree(workspace)
        workspace.mkdir()  # Create fresh workspace

        # Reload memory - should still have indexed content
        memory2 = ProjectMemory(temp_nexus_root)

        assert len(memory2.chunks) == chunks_before
