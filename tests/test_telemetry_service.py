"""
Tests for TelemetryService (V9.1 Service Layer)

These tests verify the TelemetryService extracted from repl.py works correctly.
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestTelemetryService:
    """Test TelemetryService functionality."""

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
    def telemetry_service(self, temp_workspace, mock_console):
        """Create a TelemetryService instance."""
        from core.observability.telemetry.service import TelemetryService

        return TelemetryService(workspace_path=temp_workspace, console=mock_console)

    @pytest.fixture
    def workspace_with_telemetry(self, temp_workspace):
        """Create workspace with sample telemetry data."""
        telemetry_file = temp_workspace / "telemetry.jsonl"

        # Write sample events
        events = [
            {
                "type": "api_call",
                "session_id": "test-session",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "provider": "anthropic",
                    "model": "claude-3",
                    "tokens_in": 100,
                    "tokens_out": 200,
                    "success": True,
                },
            },
            {
                "type": "swarm_task",
                "session_id": "test-session",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"mode": "parallel", "duration_seconds": 5.5, "success": True},
            },
        ]

        with open(telemetry_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        return temp_workspace

    # ==================== report() tests ====================

    def test_report_no_data(self, telemetry_service, mock_console):
        """Test report with no telemetry data."""
        result = telemetry_service.report(days=7)

        assert result.success is True
        assert result.message == "No data"
        mock_console.print.assert_any_call("[dim]No telemetry data available yet.[/dim]")

    def test_report_with_data(self, workspace_with_telemetry, mock_console):
        """Test report with telemetry data."""
        from core.observability.telemetry.service import TelemetryService

        service = TelemetryService(workspace_path=workspace_with_telemetry, console=mock_console)

        result = service.report(days=7)

        assert result.success is True
        assert result.data is not None
        assert "api_calls" in result.data

    # ==================== status() tests ====================

    def test_status_no_file(self, telemetry_service, mock_console):
        """Test status when telemetry file doesn't exist."""
        result = telemetry_service.status()

        assert result.success is True
        assert result.data["file_exists"] is False
        assert result.data["event_count"] == 0

    def test_status_with_data(self, workspace_with_telemetry, mock_console):
        """Test status with telemetry data."""
        from core.observability.telemetry.service import TelemetryService

        service = TelemetryService(workspace_path=workspace_with_telemetry, console=mock_console)

        result = service.status()

        assert result.success is True
        assert result.data["file_exists"] is True
        assert result.data["event_count"] == 2

    # ==================== export() tests ====================

    def test_export_no_data(self, telemetry_service, mock_console):
        """Test export with no data."""
        result = telemetry_service.export()

        assert result.success is False
        assert "No data" in result.error
        # Service prints with newline
        mock_console.print.assert_any_call("\n[yellow]No telemetry data to export.[/yellow]")

    def test_export_success(self, workspace_with_telemetry, mock_console):
        """Test successful export to CSV."""
        from core.observability.telemetry.service import TelemetryService

        service = TelemetryService(workspace_path=workspace_with_telemetry, console=mock_console)

        result = service.export()

        assert result.success is True
        assert "path" in result.data
        assert result.data["events"] == 2

        # Verify CSV was created
        csv_path = Path(result.data["path"])
        assert csv_path.exists()

    def test_export_with_days_filter(self, workspace_with_telemetry, mock_console):
        """Test export with days filter."""
        from core.observability.telemetry.service import TelemetryService

        service = TelemetryService(workspace_path=workspace_with_telemetry, console=mock_console)

        result = service.export(days=1)

        assert result.success is True


class TestServiceResult:
    """Test ServiceResult dataclass."""

    def test_service_result_success(self):
        """Test successful ServiceResult."""
        from core.observability.telemetry.service import ServiceResult

        result = ServiceResult(success=True, message="OK")
        assert result.success is True
        assert result.message == "OK"
        assert result.error is None
        assert result.data is None

    def test_service_result_failure(self):
        """Test failed ServiceResult."""
        from core.observability.telemetry.service import ServiceResult

        result = ServiceResult(success=False, error="Something failed")
        assert result.success is False
        assert result.error == "Something failed"

    def test_service_result_with_data(self):
        """Test ServiceResult with data."""
        from core.observability.telemetry.service import ServiceResult

        result = ServiceResult(success=True, data={"key": "value", "count": 42})
        assert result.data["key"] == "value"
        assert result.data["count"] == 42


class TestGetTelemetryService:
    """Test _get_telemetry_service helper function."""

    def test_get_service_from_extras(self):
        """Test getting service from context extras."""
        from core.observability.telemetry.service import _get_telemetry_service

        mock_service = MagicMock()
        mock_context = MagicMock()
        mock_context.extras = {"telemetry_service": mock_service}

        result = _get_telemetry_service(mock_context)
        assert result is mock_service

    def test_get_service_creates_new(self):
        """Test creating new service when not in extras."""
        from core.observability.telemetry.service import TelemetryService, _get_telemetry_service

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_context = MagicMock()
            mock_context.extras = {"workspace_path": Path(tmpdir)}
            mock_context.console = MagicMock()
            mock_context.config = None

            result = _get_telemetry_service(mock_context)
            assert isinstance(result, TelemetryService)
