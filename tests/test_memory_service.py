"""
Tests for MemoryService (V9.1 Service Layer)

These tests verify the MemoryService extracted from repl.py works correctly.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestMemoryService:
    """Test MemoryService functionality."""

    @pytest.fixture
    def mock_project_memory(self):
        """Create a mock ProjectMemory."""
        pm = MagicMock()
        pm.nexus_root = Path("/fake/nexus/root")
        pm.indexed_files = []
        pm.get_stats.return_value = MagicMock(
            total_files=0, total_chunks=0, total_terms=0, storage_path="/fake/storage"
        )
        pm.get_backend_info.return_value = {"backend": "tfidf"}
        return pm

    @pytest.fixture
    def mock_console(self):
        """Create a mock console."""
        console = MagicMock()
        console.print = MagicMock()
        console.print_error = MagicMock()
        console.console = MagicMock()
        console.console.print = MagicMock()
        return console

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            yield workspace

    @pytest.fixture
    def memory_service(self, mock_project_memory, temp_workspace, mock_console):
        """Create a MemoryService instance."""
        from core.memory_pkg.memory.service import MemoryService

        return MemoryService(project_memory=mock_project_memory, workspace_path=temp_workspace, console=mock_console)

    def test_learn_default_path(self, memory_service, mock_project_memory, mock_console):
        """Test learn with no path uses default."""
        mock_project_memory.index_directory.return_value = 10
        mock_project_memory.nexus_root = Path("/fake/root")

        # Mock path exists
        with (
            patch("core.memory_pkg.memory.service.Path.exists", return_value=True),
            patch("core.memory_pkg.memory.service.Path.is_file", return_value=False),
        ):
            memory_service.learn("")

        # Should use default path "core"
        mock_console.print.assert_any_call("[dim]No path specified, indexing default: core[/dim]")

    def test_learn_file_not_found(self, memory_service, mock_project_memory):
        """Test learn with non-existent path."""
        mock_project_memory.nexus_root = Path("/fake/root")

        result = memory_service.learn("nonexistent/path")
        assert not result.success
        assert "not found" in result.error

    def test_learn_file_success(self, memory_service, mock_project_memory, temp_workspace):
        """Test learn with valid file."""
        # Create a real file
        test_file = temp_workspace / "test.py"
        test_file.write_text("# test content")

        mock_project_memory.nexus_root = temp_workspace
        mock_project_memory.index_file.return_value = 5

        result = memory_service.learn("test.py")
        assert result.success
        assert result.chunks_added == 5

    def test_learn_directory_success(self, memory_service, mock_project_memory, temp_workspace):
        """Test learn with valid directory."""
        # Create a real directory
        test_dir = temp_workspace / "test_dir"
        test_dir.mkdir()

        mock_project_memory.nexus_root = temp_workspace
        mock_project_memory.index_directory.return_value = 15

        result = memory_service.learn("test_dir")
        assert result.success
        assert result.chunks_added == 15

    def test_forget_empty_path(self, memory_service, mock_console):
        """Test forget with empty path."""
        result = memory_service.forget("")
        assert not result.success
        mock_console.print_error.assert_called()

    def test_forget_success(self, memory_service, mock_project_memory, temp_workspace):
        """Test forget with valid path."""
        mock_project_memory.nexus_root = temp_workspace
        mock_project_memory.forget.return_value = 3

        result = memory_service.forget("some/path")
        assert result.success
        assert result.chunks_removed == 3

    def test_forget_not_in_memory(self, memory_service, mock_project_memory, temp_workspace):
        """Test forget when path not in memory."""
        mock_project_memory.nexus_root = temp_workspace
        mock_project_memory.forget.return_value = 0

        result = memory_service.forget("not/in/memory")
        assert result.success
        assert result.chunks_removed == 0

    def test_get_status_returns_stats(self, memory_service, mock_project_memory):
        """Test get_status returns proper stats."""
        mock_project_memory.indexed_files = ["file1.py", "file2.py"]
        mock_project_memory.get_stats.return_value = MagicMock(
            total_files=2, total_chunks=10, total_terms=100, storage_path="/path/to/storage"
        )

        status = memory_service.get_status()
        assert status is not None
        assert status.total_files == 2
        assert status.total_chunks == 10
        assert len(status.indexed_files) == 2

    def test_get_status_no_project_memory(self, temp_workspace, mock_console):
        """Test get_status when project memory is None."""
        from core.memory_pkg.memory.service import MemoryService

        service = MemoryService(project_memory=None, workspace_path=temp_workspace, console=mock_console)
        status = service.get_status()
        assert status is None
        mock_console.print_error.assert_called()

    def test_query_no_results(self, memory_service, mock_project_memory):
        """Test query with no results."""
        mock_project_memory.retrieve.return_value = []

        result = memory_service.query("unknown topic")
        assert result.success
        assert result.chunks == []

    def test_query_with_results(self, memory_service, mock_project_memory):
        """Test query with results."""
        mock_chunk = MagicMock()
        mock_chunk.file_path = "test.py"
        mock_chunk.start_line = 1
        mock_chunk.end_line = 10
        mock_chunk.content = "Some test content here"

        mock_project_memory.retrieve.return_value = [mock_chunk]

        result = memory_service.query("test query")
        assert result.success
        assert len(result.chunks) == 1

    def test_init_rag_creates_directory(self, memory_service, temp_workspace, mock_project_memory):
        """Test init_rag creates memory directory."""
        mock_project_memory.index_directory.return_value = 5

        memory_dir = temp_workspace / "memory"
        assert not memory_dir.exists()

        result = memory_service.init_rag()
        assert result.success
        assert memory_dir.exists()

    def test_clear_success(self, memory_service, mock_project_memory, mock_console):
        """Test clear operation."""
        result = memory_service.clear()
        assert result is True
        mock_project_memory.clear.assert_called_once()

    def test_clear_no_project_memory(self, temp_workspace, mock_console):
        """Test clear when project memory is None."""
        from core.memory_pkg.memory.service import MemoryService

        service = MemoryService(project_memory=None, workspace_path=temp_workspace, console=mock_console)
        result = service.clear()
        assert result is False

    def test_handle_rag_command_init(self, memory_service, mock_project_memory, temp_workspace):
        """Test /rag init subcommand."""
        mock_project_memory.index_directory.return_value = 0
        memory_service.handle_rag_command("init")
        mock_project_memory.index_directory.assert_called()

    def test_handle_rag_command_clear(self, memory_service, mock_project_memory):
        """Test /rag clear subcommand."""
        memory_service.handle_rag_command("clear")
        mock_project_memory.clear.assert_called_once()

    def test_handle_rag_command_query(self, memory_service, mock_project_memory):
        """Test /rag query subcommand."""
        mock_project_memory.retrieve.return_value = []
        memory_service.handle_rag_command("query test question")
        mock_project_memory.retrieve.assert_called_with("test question", limit=5)

    def test_handle_rag_command_invalid(self, memory_service, mock_console):
        """Test /rag with invalid subcommand."""
        memory_service.handle_rag_command("invalid")
        mock_console.print_error.assert_called()


class TestMemoryServiceIntegration:
    """Integration tests for MemoryService with commands."""

    def test_command_uses_service(self):
        """Test that MemoryCommand uses MemoryService."""
        from core.interface_pkg.interface.commands.memory import _get_memory_service
        from core.interface_pkg.interface.commands.registry import CommandContext

        mock_orchestrator = MagicMock()
        mock_orchestrator.project_memory = MagicMock()
        mock_orchestrator.project_memory.nexus_root = Path("/fake/root")

        mock_console = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            context = CommandContext(
                orchestrator=mock_orchestrator, console=mock_console, config={}, extras={"workspace_path": Path(tmpdir)}
            )

            service = _get_memory_service(context)
            from core.memory_pkg.memory.service import MemoryService

            assert isinstance(service, MemoryService)
