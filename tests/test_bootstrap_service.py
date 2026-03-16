"""
Tests for BootstrapService (V9.1 Service Layer)

These tests verify the BootstrapService extracted from repl.py works correctly.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestBootstrapService:
    """Test BootstrapService functionality."""

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
    def temp_project(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            # Create some project files
            (project / "main.py").write_text("print('hello')")
            (project / "README.md").write_text("# Test Project")
            yield project

    @pytest.fixture
    def bootstrap_service(self, mock_console):
        """Create a BootstrapService instance."""
        from core.infrastructure.bootstrap.service import BootstrapService

        return BootstrapService(console=mock_console)

    # ==================== bootstrap() tests ====================

    def test_bootstrap_path_not_exists(self, bootstrap_service, mock_console):
        """Test bootstrap with non-existent path."""
        result = bootstrap_service.bootstrap(Path("/nonexistent/path"))

        assert result.success is False
        assert "does not exist" in result.error
        mock_console.print_error.assert_called()

    def test_bootstrap_path_is_file(self, bootstrap_service, mock_console, temp_project):
        """Test bootstrap with file path instead of directory."""
        file_path = temp_project / "main.py"

        result = bootstrap_service.bootstrap(file_path)

        assert result.success is False
        assert "not a directory" in result.error
        mock_console.print_error.assert_called()

    def test_bootstrap_default_path(self, bootstrap_service, mock_console):
        """Test bootstrap with default path (cwd)."""
        with (
            patch.object(Path, "cwd", return_value=Path(tempfile.gettempdir())),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch("core.infrastructure.bootstrap.AutoBootstrap") as mock_auto,
        ):
            mock_analysis = MagicMock()
            mock_analysis.project_name = "test"
            mock_analysis.languages = ["python"]
            mock_analysis.frameworks = []
            mock_analysis.databases = []
            mock_analysis.tools = []
            mock_analysis.has_tests = False
            mock_analysis.has_docs = False
            mock_analysis.has_ci = False
            mock_analysis.commands = {}

            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_analysis
            mock_instance.generate_nexus_md.return_value = "# NEXUS.md content"
            mock_auto.return_value = mock_instance

            bootstrap_service.bootstrap(None)
            # Should attempt to use current directory
            mock_console.print.assert_called()

    def test_bootstrap_success_new_project(self, bootstrap_service, mock_console, temp_project):
        """Test successful bootstrap on new project."""
        with patch("core.infrastructure.bootstrap.AutoBootstrap") as mock_auto:
            mock_analysis = MagicMock()
            mock_analysis.project_name = "TestProject"
            mock_analysis.languages = ["python"]
            mock_analysis.frameworks = []
            mock_analysis.databases = []
            mock_analysis.tools = []
            mock_analysis.has_tests = False
            mock_analysis.has_docs = True
            mock_analysis.has_ci = False
            mock_analysis.commands = {"test": "pytest"}

            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_analysis
            mock_instance.generate_nexus_md.return_value = "# NEXUS.md\nGenerated content"
            mock_auto.return_value = mock_instance

            result = bootstrap_service.bootstrap(temp_project)

            assert result.success is True
            assert result.data is not None
            assert result.data["project_name"] == "TestProject"
            assert "python" in result.data["languages"]
            mock_instance.save.assert_called_once()

    def test_bootstrap_existing_nexus_md_cancelled(self, bootstrap_service, mock_console, temp_project):
        """Test bootstrap cancelled when NEXUS.md exists and user says no."""
        # Create existing NEXUS.md
        nexus_md = temp_project / "NEXUS.md"
        nexus_md.write_text("# Existing NEXUS.md\n" * 100)

        with patch("core.infrastructure.bootstrap.AutoBootstrap") as mock_auto:
            mock_analysis = MagicMock()
            mock_analysis.project_name = "Test"
            mock_analysis.languages = []
            mock_analysis.frameworks = []
            mock_analysis.databases = []
            mock_analysis.tools = []
            mock_analysis.has_tests = False
            mock_analysis.has_docs = False
            mock_analysis.has_ci = False
            mock_analysis.commands = {}

            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_analysis
            mock_instance.generate_nexus_md.return_value = "# New content"
            mock_auto.return_value = mock_instance

            with patch("builtins.input", return_value="n"):
                result = bootstrap_service.bootstrap(temp_project)

        assert result.success is False
        assert result.message == "Cancelled by user"

    def test_bootstrap_existing_nexus_md_overwrite(self, bootstrap_service, mock_console, temp_project):
        """Test bootstrap overwrites when user confirms."""
        # Create existing NEXUS.md
        nexus_md = temp_project / "NEXUS.md"
        nexus_md.write_text("# Existing NEXUS.md")

        with patch("core.infrastructure.bootstrap.AutoBootstrap") as mock_auto:
            mock_analysis = MagicMock()
            mock_analysis.project_name = "Test"
            mock_analysis.languages = []
            mock_analysis.frameworks = []
            mock_analysis.databases = []
            mock_analysis.tools = []
            mock_analysis.has_tests = False
            mock_analysis.has_docs = False
            mock_analysis.has_ci = False
            mock_analysis.commands = {}

            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_analysis
            mock_instance.generate_nexus_md.return_value = "# New NEXUS.md content"
            mock_auto.return_value = mock_instance

            with patch("builtins.input", return_value="y"):
                result = bootstrap_service.bootstrap(temp_project)

        assert result.success is True
        # Backup should have been created
        assert (temp_project / "NEXUS.md.bak").exists()

    def test_bootstrap_exception_handling(self, bootstrap_service, mock_console, temp_project):
        """Test bootstrap handles exceptions gracefully."""
        with patch("core.infrastructure.bootstrap.AutoBootstrap") as mock_auto:
            mock_auto.side_effect = Exception("Analysis failed")

            result = bootstrap_service.bootstrap(temp_project)

        assert result.success is False
        assert "Analysis failed" in result.error
        mock_console.print_error.assert_called()


class TestGetBootstrapService:
    """Test _get_bootstrap_service helper function."""

    def test_get_service_from_extras(self):
        """Test getting service from context extras."""
        from core.infrastructure.bootstrap.service import _get_bootstrap_service

        mock_service = MagicMock()
        mock_context = MagicMock()
        mock_context.extras = {"bootstrap_service": mock_service}

        result = _get_bootstrap_service(mock_context)
        assert result is mock_service

    def test_get_service_creates_new(self):
        """Test creating new service when not in extras."""
        from core.infrastructure.bootstrap.service import BootstrapService, _get_bootstrap_service

        mock_context = MagicMock()
        mock_context.extras = {}
        mock_context.console = MagicMock()

        result = _get_bootstrap_service(mock_context)
        assert isinstance(result, BootstrapService)
