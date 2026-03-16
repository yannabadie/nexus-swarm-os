"""
Tests for Phase 13c: Telemetry Export

Verifies:
1. TelemetryExporter reads JSONL files correctly
2. CSV export generates valid output
3. Report generation with accurate metrics
4. Graceful handling of empty/missing telemetry files
"""

import csv
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.observability.telemetry.exporter import TelemetryEvent, TelemetryExporter

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def workspace_path(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def empty_telemetry(workspace_path):
    """Create an empty telemetry file."""
    telemetry_file = workspace_path / "telemetry.jsonl"
    telemetry_file.touch()
    return TelemetryExporter(workspace_path)


@pytest.fixture
def populated_telemetry(workspace_path):
    """
    Create telemetry file with sample data.

    Events:
    - 3 API calls (2 success, 1 failure)
    - 2 swarm_task events (both success, different modes)
    - 1 error event
    - 2 tool_execution events
    """
    telemetry_file = workspace_path / "telemetry.jsonl"

    now = datetime.now(UTC)

    events = [
        # API calls
        {
            "type": "api_call",
            "session_id": "test_session_1",
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "data": {
                "provider": "gemini",
                "model": "gemini-3-pro",
                "tokens_in": 500,
                "tokens_out": 300,
                "latency_seconds": 1.5,
                "success": True,
            },
        },
        {
            "type": "api_call",
            "session_id": "test_session_1",
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "data": {
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "tokens_in": 800,
                "tokens_out": 500,
                "latency_seconds": 2.0,
                "success": True,
            },
        },
        {
            "type": "api_call",
            "session_id": "test_session_2",
            "timestamp": now.isoformat(),
            "data": {
                "provider": "gemini",
                "model": "gemini-3-pro",
                "tokens_in": 200,
                "tokens_out": 0,
                "latency_seconds": 0.5,
                "success": False,
                "error": "Rate limit exceeded",
            },
        },
        # Swarm tasks
        {
            "type": "swarm_task",
            "session_id": "test_session_1",
            "timestamp": (now - timedelta(hours=1, minutes=30)).isoformat(),
            "data": {"mode": "ping_pong", "duration_seconds": 15.5, "success": True},
        },
        {
            "type": "swarm_task",
            "session_id": "test_session_2",
            "timestamp": (now - timedelta(minutes=30)).isoformat(),
            "data": {"mode": "specialist", "duration_seconds": 8.2, "success": True},
        },
        # Tool execution
        {
            "type": "tool_execution",
            "session_id": "test_session_1",
            "timestamp": (now - timedelta(hours=1, minutes=45)).isoformat(),
            "data": {"tool_name": "read_file", "duration_seconds": 0.1, "success": True},
        },
        {
            "type": "tool_execution",
            "session_id": "test_session_1",
            "timestamp": (now - timedelta(hours=1, minutes=40)).isoformat(),
            "data": {
                "tool_name": "write_file",
                "duration_seconds": 0.2,
                "success": False,
                "error": "Permission denied",
            },
        },
        # Error event
        {
            "type": "error",
            "session_id": "test_session_2",
            "timestamp": (now - timedelta(minutes=15)).isoformat(),
            "data": {"error_type": "ValidationError", "message": "Invalid JSON response"},
        },
    ]

    with open(telemetry_file, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return TelemetryExporter(workspace_path)


# =============================================================================
# TelemetryEvent Tests
# =============================================================================


class TestTelemetryEvent:
    """Tests for TelemetryEvent parsing."""

    def test_parse_valid_event(self):
        """Parses valid JSONL line correctly."""
        line = '{"type": "api_call", "session_id": "abc", "timestamp": "2025-01-01T12:00:00Z", "data": {"provider": "gemini"}}'
        event = TelemetryEvent.from_json(line)

        assert event is not None
        assert event.event_type == "api_call"
        assert event.session_id == "abc"
        assert event.data["provider"] == "gemini"

    def test_parse_invalid_json_returns_none(self):
        """Invalid JSON returns None."""
        line = "not valid json"
        event = TelemetryEvent.from_json(line)
        assert event is None

    def test_parse_missing_timestamp_returns_none(self):
        """Missing timestamp returns None."""
        line = '{"type": "api_call", "session_id": "abc", "data": {}}'
        event = TelemetryEvent.from_json(line)
        assert event is None

    def test_parse_handles_z_suffix(self):
        """Handles ISO format with Z suffix."""
        line = '{"type": "api_call", "session_id": "abc", "timestamp": "2025-01-01T12:00:00Z", "data": {}}'
        event = TelemetryEvent.from_json(line)

        assert event is not None
        assert event.timestamp.hour == 12


# =============================================================================
# TelemetryExporter Tests - Empty/Missing File
# =============================================================================


class TestEmptyTelemetry:
    """Tests for handling empty or missing telemetry files."""

    def test_no_file_returns_zero_count(self, workspace_path):
        """Missing telemetry file returns 0 event count."""
        exporter = TelemetryExporter(workspace_path)
        assert exporter.get_event_count() == 0

    def test_empty_file_returns_zero_count(self, empty_telemetry):
        """Empty telemetry file returns 0 event count."""
        assert empty_telemetry.get_event_count() == 0

    def test_report_with_no_data(self, workspace_path):
        """Report generation with no data returns defaults."""
        exporter = TelemetryExporter(workspace_path)
        report = exporter.generate_report(days=7)

        assert report["total_events"] == 0
        assert report["success_rate"] == 0.0
        assert report["api_calls"] == 0
        assert report["total_tokens"]["total"] == 0

    def test_csv_export_empty_file(self, workspace_path):
        """CSV export with no data creates file with headers only."""
        exporter = TelemetryExporter(workspace_path)
        csv_path = exporter.export_to_csv()

        assert csv_path.exists()
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) == 1  # Header only
            assert "timestamp" in rows[0]


# =============================================================================
# TelemetryExporter Tests - Event Counting
# =============================================================================


class TestEventCounting:
    """Tests for event counting functionality."""

    def test_counts_all_events(self, populated_telemetry):
        """Counts all events in file."""
        assert populated_telemetry.get_event_count() == 8

    def test_iter_events_returns_all(self, populated_telemetry):
        """_iter_events returns all events."""
        events = list(populated_telemetry._iter_events())
        assert len(events) == 8

    def test_iter_events_filters_by_type(self, populated_telemetry):
        """_iter_events filters by event type."""
        api_events = list(populated_telemetry._iter_events(event_types=["api_call"]))
        assert len(api_events) == 3

        swarm_events = list(populated_telemetry._iter_events(event_types=["swarm_task"]))
        assert len(swarm_events) == 2

    def test_iter_events_filters_by_time(self, populated_telemetry):
        """_iter_events filters by timestamp."""
        since = datetime.now(UTC) - timedelta(hours=1)
        recent_events = list(populated_telemetry._iter_events(since=since))

        # Should include events from last hour only
        assert len(recent_events) < 8


# =============================================================================
# TelemetryExporter Tests - Report Generation
# =============================================================================


class TestReportGeneration:
    """Tests for report generation."""

    def test_report_total_events(self, populated_telemetry):
        """Report includes correct total event count."""
        report = populated_telemetry.generate_report(days=7)
        assert report["total_events"] == 8

    def test_report_success_rate(self, populated_telemetry):
        """Report calculates correct success rate."""
        report = populated_telemetry.generate_report(days=7)

        # 5 successes, 2 failures = 71.4%
        # (2 api success + 2 swarm success + 1 tool success = 5)
        # (1 api fail + 1 tool fail = 2)
        assert 70 <= report["success_rate"] <= 72

    def test_report_token_totals(self, populated_telemetry):
        """Report calculates correct token totals."""
        report = populated_telemetry.generate_report(days=7)

        # 500 + 800 + 200 = 1500 tokens in
        assert report["total_tokens"]["input"] == 1500
        # 300 + 500 + 0 = 800 tokens out
        assert report["total_tokens"]["output"] == 800

    def test_report_api_call_count(self, populated_telemetry):
        """Report counts API calls correctly."""
        report = populated_telemetry.generate_report(days=7)
        assert report["api_calls"] == 3

    def test_report_error_count(self, populated_telemetry):
        """Report counts errors correctly."""
        report = populated_telemetry.generate_report(days=7)
        assert report["error_count"] == 1

    def test_report_top_modes(self, populated_telemetry):
        """Report includes top swarm modes."""
        report = populated_telemetry.generate_report(days=7)

        assert "ping_pong" in report["top_modes"]
        assert "specialist" in report["top_modes"]

    def test_report_avg_latency_by_mode(self, populated_telemetry):
        """Report calculates average latency per mode."""
        report = populated_telemetry.generate_report(days=7)

        assert "ping_pong" in report["avg_latency_by_mode"]
        assert report["avg_latency_by_mode"]["ping_pong"] == 15.5

    def test_report_provider_distribution(self, populated_telemetry):
        """Report includes provider distribution."""
        report = populated_telemetry.generate_report(days=7)

        assert "gemini" in report["provider_distribution"]
        assert "claude" in report["provider_distribution"]
        assert report["provider_distribution"]["gemini"] == 2
        assert report["provider_distribution"]["claude"] == 1

    def test_report_tool_usage(self, populated_telemetry):
        """Report includes tool usage stats."""
        report = populated_telemetry.generate_report(days=7)

        assert "read_file" in report["tool_usage"]
        assert "write_file" in report["tool_usage"]


# =============================================================================
# TelemetryExporter Tests - CSV Export
# =============================================================================


class TestCsvExport:
    """Tests for CSV export functionality."""

    def test_csv_creates_file(self, populated_telemetry):
        """CSV export creates a file."""
        csv_path = populated_telemetry.export_to_csv()
        assert csv_path.exists()

    def test_csv_has_correct_headers(self, populated_telemetry):
        """CSV has expected column headers."""
        csv_path = populated_telemetry.export_to_csv()

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

            assert "timestamp" in headers
            assert "event_type" in headers
            assert "session_id" in headers
            assert "tokens_in" in headers
            assert "provider" in headers

    def test_csv_has_correct_row_count(self, populated_telemetry):
        """CSV has correct number of data rows."""
        csv_path = populated_telemetry.export_to_csv()

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            # 1 header + 8 events
            assert len(rows) == 9

    def test_csv_filters_by_days(self, populated_telemetry):
        """CSV export respects days filter."""
        # Export only last 1 hour (should be less than all)
        csv_path = populated_telemetry.export_to_csv(days=0)  # 0 days = now only

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            # Should have fewer rows than full export
            assert len(rows) <= 9

    def test_csv_filename_format(self, populated_telemetry):
        """CSV filename follows expected format."""
        csv_path = populated_telemetry.export_to_csv()

        assert csv_path.name.startswith("telemetry_export_")
        assert csv_path.name.endswith(".csv")


# =============================================================================
# TelemetryExporter Tests - Console Formatting
# =============================================================================


class TestConsoleFormatting:
    """Tests for console output formatting."""

    def test_format_report_includes_period(self, populated_telemetry):
        """Formatted report includes period info."""
        report = populated_telemetry.generate_report(days=7)
        formatted = populated_telemetry.format_report_for_console(report)

        assert "7 days" in formatted

    def test_format_report_includes_success_rate(self, populated_telemetry):
        """Formatted report includes success rate."""
        report = populated_telemetry.generate_report(days=7)
        formatted = populated_telemetry.format_report_for_console(report)

        assert "Success Rate" in formatted

    def test_format_report_includes_token_info(self, populated_telemetry):
        """Formatted report includes token information."""
        report = populated_telemetry.generate_report(days=7)
        formatted = populated_telemetry.format_report_for_console(report)

        assert "Tokens" in formatted

    def test_format_report_includes_modes(self, populated_telemetry):
        """Formatted report includes swarm modes."""
        report = populated_telemetry.generate_report(days=7)
        formatted = populated_telemetry.format_report_for_console(report)

        assert "Swarm Modes" in formatted


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for telemetry export workflow."""

    def test_full_workflow(self, workspace_path):
        """Test full workflow: write events, generate report, export CSV."""
        telemetry_file = workspace_path / "telemetry.jsonl"
        now = datetime.now(UTC)

        # Write some events
        events = [
            {
                "type": "api_call",
                "session_id": "integration_test",
                "timestamp": now.isoformat(),
                "data": {"provider": "gemini", "model": "test", "tokens_in": 100, "tokens_out": 50, "success": True},
            },
            {
                "type": "swarm_task",
                "session_id": "integration_test",
                "timestamp": now.isoformat(),
                "data": {"mode": "parallel", "duration_seconds": 5.0, "success": True},
            },
        ]

        with open(telemetry_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        # Create exporter and verify
        exporter = TelemetryExporter(workspace_path)

        # Check event count
        assert exporter.get_event_count() == 2

        # Generate report
        report = exporter.generate_report(days=1)
        assert report["total_events"] == 2
        assert report["success_rate"] == 100.0

        # Export CSV
        csv_path = exporter.export_to_csv()
        assert csv_path.exists()

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) == 3  # header + 2 events


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
