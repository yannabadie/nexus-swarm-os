"""
Tests for SpinoffService (V9.1 Service Layer)

These tests verify the SpinoffService extracted from repl.py works correctly.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSpinoffService:
    """Test SpinoffService functionality."""

    @pytest.fixture
    def mock_console(self):
        """Create a mock console."""
        console = MagicMock()
        console.print = MagicMock()
        console.print_error = MagicMock()
        console.console = MagicMock()
        console.console.print = MagicMock()
        console.display_result = MagicMock()
        return console

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator."""
        orchestrator = MagicMock()
        orchestrator.blackboard = {"recent_history": []}
        orchestrator.memory = MagicMock()
        orchestrator.memory.save_to_disk = MagicMock()
        orchestrator._transition_to = MagicMock()
        orchestrator.process_turn = MagicMock(
            return_value={
                "state": "IDLE",
                "output": '```json\n[{"file": "test.py", "change": "# new code"}]\n```',
                "finished": True,
            }
        )
        return orchestrator

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Create .nexus directory for lineage
            nexus_dir = workspace / ".nexus"
            nexus_dir.mkdir()

            # Create lineage file
            lineage = {"parent_id": "NEXUS_ROOT", "generations": [{"id": "NEXUS_ROOT", "created": "2024-01-01"}]}
            (nexus_dir / "lineage.json").write_text(json.dumps(lineage))

            yield workspace

    @pytest.fixture
    def temp_nexus_root(self):
        """Create a temporary NEXUS root directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nexus_root = Path(tmpdir) / "NEXUS_ROOT"
            nexus_root.mkdir()

            # Create minimal NEXUS structure
            (nexus_root / "nexus7.py").write_text("# main entry")
            (nexus_root / "core").mkdir()
            (nexus_root / "prompts").mkdir()

            # Create parent directory for GENERATION_ACTIVE
            (nexus_root.parent / "GENERATION_ACTIVE").mkdir(exist_ok=True)

            yield nexus_root

    @pytest.fixture
    def spinoff_service(self, mock_orchestrator, mock_console, temp_workspace, temp_nexus_root):
        """Create a SpinoffService instance."""
        from core.infrastructure.bootstrap.service import SpinoffService

        return SpinoffService(
            orchestrator=mock_orchestrator,
            console=mock_console,
            workspace_path=temp_workspace,
            nexus_root=temp_nexus_root,
        )

    # ==================== specialize() tests ====================

    def test_specialize_success(self, spinoff_service, mock_console, mock_orchestrator, temp_nexus_root):
        """Test successful specialization."""
        # Mock brainstorming result
        mutations = [{"file": "prompts/test.md", "change": "# New prompt"}]

        with (
            patch.object(spinoff_service, "_brainstorm_spinoff", return_value=mutations),
            patch("core.intelligence.evolution.lineage.load_lineage") as mock_lineage,
            patch("core.intelligence.evolution.lineage.get_current_parent") as mock_parent,
        ):
            mock_lineage.return_value = {"generations": []}
            mock_parent.return_value = {"id": "NEXUS_ROOT"}

            result = spinoff_service.specialize("Test API Expert")

        assert result.success is True
        assert result.data is not None
        assert "spinoff_id" in result.data
        assert "TEST_API_EXPERT" in result.data["spinoff_id"]

    def test_specialize_no_mutations(self, spinoff_service, mock_console):
        """Test specialization fails when no mutations generated."""
        with (
            patch.object(spinoff_service, "_brainstorm_spinoff", return_value=[]),
            patch("core.intelligence.evolution.lineage.load_lineage") as mock_lineage,
            patch("core.intelligence.evolution.lineage.get_current_parent") as mock_parent,
        ):
            mock_lineage.return_value = {"generations": []}
            mock_parent.return_value = {"id": "NEXUS_ROOT"}

            result = spinoff_service.specialize("Test Mission")

        assert result.success is False
        assert "mutations" in result.error.lower()

    def test_specialize_exception_handling(self, spinoff_service, mock_console):
        """Test specialization handles exceptions gracefully."""
        with patch("core.intelligence.evolution.lineage.load_lineage") as mock_lineage:
            mock_lineage.side_effect = Exception("Lineage file not found")

            result = spinoff_service.specialize("Test Mission")

        assert result.success is False
        mock_console.print_error.assert_called()

    def test_specialize_mission_slug_sanitization(self, spinoff_service, mock_console, temp_nexus_root):
        """Test mission string is properly sanitized for folder name."""
        mutations = [{"file": "test.py", "change": "# code"}]

        with (
            patch.object(spinoff_service, "_brainstorm_spinoff", return_value=mutations),
            patch("core.intelligence.evolution.lineage.load_lineage") as mock_lineage,
            patch("core.intelligence.evolution.lineage.get_current_parent") as mock_parent,
        ):
            mock_lineage.return_value = {"generations": []}
            mock_parent.return_value = {"id": "NEXUS_ROOT"}

            # Use mission with special characters
            result = spinoff_service.specialize("Test: API/Expert!")

        assert result.success is True
        # Special chars should be replaced with underscores
        assert "_" in result.data["spinoff_id"]
        assert ":" not in result.data["spinoff_id"]
        assert "/" not in result.data["spinoff_id"]

    # ==================== _brainstorm_spinoff() tests ====================

    def test_brainstorm_spinoff_success(self, spinoff_service, mock_orchestrator, mock_console, temp_nexus_root):
        """Test successful brainstorming."""
        # Mock prompt loading
        with patch("core.memory_pkg.prompts.load_prompt") as mock_load:
            mock_load.return_value = "Brainstorm prompt"

            # Mock JSON extraction
            with patch("core.utils.json_extractor.extract_json_safe") as mock_extract:
                mock_extract.return_value = ([{"file": "test.py", "change": "code"}], None)

                result = spinoff_service._brainstorm_spinoff(
                    parent_id="NEXUS_ROOT", parent_path=temp_nexus_root, mission="Test Mission"
                )

        assert len(result) == 1
        assert result[0]["file"] == "test.py"
        mock_orchestrator._transition_to.assert_called()

    def test_brainstorm_spinoff_prompt_not_found(self, spinoff_service, mock_console, temp_nexus_root):
        """Test brainstorming fails when prompt file missing."""
        with patch("core.memory_pkg.prompts.load_prompt") as mock_load:
            mock_load.side_effect = FileNotFoundError("Prompt not found")

            result = spinoff_service._brainstorm_spinoff(
                parent_id="NEXUS_ROOT", parent_path=temp_nexus_root, mission="Test Mission"
            )

        assert result == []
        mock_console.print_error.assert_called()

    def test_brainstorm_spinoff_json_extraction_fails(
        self, spinoff_service, mock_orchestrator, mock_console, temp_nexus_root
    ):
        """Test brainstorming raises when JSON extraction fails."""
        with patch("core.memory_pkg.prompts.load_prompt") as mock_load:
            mock_load.return_value = "Brainstorm prompt"

            with patch("core.utils.json_extractor.extract_json_safe") as mock_extract:
                mock_extract.return_value = ([], None)  # No proposals

                with pytest.raises(ValueError) as exc_info:
                    spinoff_service._brainstorm_spinoff(
                        parent_id="NEXUS_ROOT", parent_path=temp_nexus_root, mission="Test Mission"
                    )

        assert "Failed to extract" in str(exc_info.value)


class TestGetSpinoffService:
    """Test _get_spinoff_service helper function."""

    def test_get_service_from_extras(self):
        """Test getting service from context extras."""
        from core.infrastructure.bootstrap.service import _get_spinoff_service

        mock_service = MagicMock()
        mock_context = MagicMock()
        mock_context.extras = {"spinoff_service": mock_service}

        result = _get_spinoff_service(mock_context)
        assert result is mock_service

    def test_get_service_requires_repl(self):
        """Test creating service requires REPL in context."""
        from core.infrastructure.bootstrap.service import _get_spinoff_service

        mock_context = MagicMock()
        mock_context.extras = {}  # No repl

        with pytest.raises(RuntimeError) as exc_info:
            _get_spinoff_service(mock_context)

        assert "REPL instance required" in str(exc_info.value)

    def test_get_service_creates_from_repl(self):
        """Test creating service from REPL in context."""
        from core.infrastructure.bootstrap.service import SpinoffService, _get_spinoff_service

        mock_repl = MagicMock()
        mock_repl.workspace_path = Path("/tmp/workspace")
        mock_repl.nexus_root = Path("/tmp/nexus")

        mock_context = MagicMock()
        mock_context.extras = {"repl": mock_repl}
        mock_context.orchestrator = MagicMock()
        mock_context.console = MagicMock()

        result = _get_spinoff_service(mock_context)
        assert isinstance(result, SpinoffService)
