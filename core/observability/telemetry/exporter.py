"""
Telemetry Exporter - Phase 13c

Export telemetry data to CSV format and generate performance reports.

Usage:
    from core.observability.telemetry.exporter import TelemetryExporter

    exporter = TelemetryExporter(workspace_path)

    # Export to CSV
    csv_path = exporter.export_to_csv()

    # Generate report
    report = exporter.generate_report(days=7)

Author: Claude (NEXUS V7.6)
Date: 2025-12-04
"""

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


@dataclass
class TelemetryEvent:
    """Parsed telemetry event from JSONL."""

    event_type: str
    session_id: str
    timestamp: datetime
    data: dict[str, Any]

    @classmethod
    def from_json(cls, line: str) -> Optional["TelemetryEvent"]:
        """Parse a JSONL line into TelemetryEvent."""
        try:
            obj = json.loads(line.strip())
            timestamp_str = obj.get("timestamp", "")
            # Handle ISO format with Z suffix (legacy data)
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1]
            timestamp = datetime.fromisoformat(timestamp_str)
            # Ensure timezone-aware (legacy naive timestamps treated as UTC)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)

            return cls(
                event_type=obj.get("type", "unknown"),
                session_id=obj.get("session_id", ""),
                timestamp=timestamp,
                data=obj.get("data", {}),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return None


class TelemetryExporter:
    """
    Export telemetry data and generate performance reports.

    Phase 13c: Telemetry Export functionality.

    Reads from workspace/telemetry.jsonl and provides:
    - CSV export for external analysis (Excel, Grafana, etc.)
    - Summary reports with aggregated metrics
    """

    def __init__(self, workspace_path: Path, telemetry_file: str | None = None):
        """
        Initialize TelemetryExporter.

        Args:
            workspace_path: Path to workspace directory.
            telemetry_file: Override telemetry filename (default: telemetry.jsonl).
        """
        self.workspace_path = Path(workspace_path)
        self.telemetry_file = self.workspace_path / (telemetry_file or "telemetry.jsonl")

    def _iter_events(
        self, since: datetime | None = None, event_types: list[str] | None = None
    ) -> Iterator[TelemetryEvent]:
        """
        Iterate over telemetry events with optional filtering.

        Args:
            since: Only include events after this timestamp.
            event_types: Only include these event types.

        Yields:
            TelemetryEvent objects.
        """
        if not self.telemetry_file.exists():
            return

        try:
            with open(self.telemetry_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue

                    event = TelemetryEvent.from_json(line)
                    if event is None:
                        continue

                    # Filter by time
                    if since and event.timestamp < since:
                        continue

                    # Filter by type
                    if event_types and event.event_type not in event_types:
                        continue

                    yield event
        except OSError:
            return

    def get_event_count(self) -> int:
        """Get total number of events in telemetry file."""
        if not self.telemetry_file.exists():
            return 0

        count = 0
        try:
            with open(self.telemetry_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
        except OSError:
            pass
        return count

    def read_events(self, days: int = 1, event_types: list[str] | None = None) -> list[TelemetryEvent]:
        """
        Read telemetry events from the last N days.

        V9.1: Added to fix bug in repl.py _budget_show_history().

        Args:
            days: Number of days to look back (default: 1).
            event_types: Optional list of event types to filter.

        Returns:
            List of TelemetryEvent objects.
        """
        since = datetime.now(UTC) - timedelta(days=days)
        return list(self._iter_events(since=since, event_types=event_types))

    def export_to_csv(self, output_dir: Path | None = None, days: int | None = None) -> Path:
        """
        Export telemetry to CSV format.

        Args:
            output_dir: Output directory (default: workspace/).
            days: Only export last N days (default: all).

        Returns:
            Path to generated CSV file.
        """
        output_dir = Path(output_dir) if output_dir else self.workspace_path
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with date
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = output_dir / f"telemetry_export_{timestamp}.csv"

        # Calculate time filter
        since = None
        if days:
            since = datetime.now(UTC) - timedelta(days=days)

        # CSV columns
        fieldnames = [
            "timestamp",
            "event_type",
            "session_id",
            "mode",
            "complexity",
            "duration_seconds",
            "status",
            "tokens_in",
            "tokens_out",
            "provider",
            "model",
            "tool_name",
            "error",
        ]

        rows_written = 0

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()

            for event in self._iter_events(since=since):
                row = self._event_to_csv_row(event)
                writer.writerow(row)
                rows_written += 1

        return csv_path

    def _event_to_csv_row(self, event: TelemetryEvent) -> dict[str, Any]:
        """Convert TelemetryEvent to CSV row dictionary."""
        data = event.data

        row = {
            "timestamp": event.timestamp.isoformat(),
            "event_type": event.event_type,
            "session_id": event.session_id,
            "mode": "",
            "complexity": "",
            "duration_seconds": "",
            "status": "",
            "tokens_in": "",
            "tokens_out": "",
            "provider": "",
            "model": "",
            "tool_name": "",
            "error": "",
        }

        if event.event_type == "swarm_task":
            row["mode"] = data.get("mode", "")
            row["duration_seconds"] = data.get("duration_seconds", "")
            row["status"] = "success" if data.get("success") else "failed"

        elif event.event_type == "api_call":
            row["provider"] = data.get("provider", "")
            row["model"] = data.get("model", "")
            row["tokens_in"] = data.get("tokens_in", "")
            row["tokens_out"] = data.get("tokens_out", "")
            row["duration_seconds"] = data.get("latency_seconds", "")
            row["status"] = "success" if data.get("success") else "failed"
            row["error"] = data.get("error", "") or ""

        elif event.event_type == "tool_execution":
            row["tool_name"] = data.get("tool_name", "")
            row["duration_seconds"] = data.get("duration_seconds", "")
            row["status"] = "success" if data.get("success") else "failed"
            row["error"] = data.get("error", "") or ""

        elif event.event_type == "error":
            row["error"] = f"{data.get('error_type', '')}: {data.get('message', '')}"
            row["status"] = "error"

        return row

    def generate_report(self, days: int = 7) -> dict[str, Any]:
        """
        Generate a performance report for the last N days.

        Args:
            days: Number of days to include (default: 7).

        Returns:
            Dictionary with aggregated metrics:
            - total_events: Total event count
            - success_rate: Overall success percentage
            - avg_latency_by_mode: Average duration per swarm mode
            - avg_tokens: Average token usage per API call
            - error_count: Total errors
            - top_modes: Most used collaboration modes
            - provider_distribution: API calls per provider
        """
        since = datetime.now(UTC) - timedelta(days=days)

        # Counters
        total_events = 0
        successes = 0
        failures = 0
        errors = 0

        # Mode metrics
        mode_durations: dict[str, list[float]] = {}
        mode_counts: dict[str, int] = {}

        # Token metrics
        total_tokens_in = 0
        total_tokens_out = 0
        api_calls = 0

        # Provider distribution
        provider_counts: dict[str, int] = {}

        # Tool metrics
        tool_counts: dict[str, int] = {}

        for event in self._iter_events(since=since):
            total_events += 1
            data = event.data

            if event.event_type == "swarm_task":
                mode = data.get("mode", "unknown")
                duration = data.get("duration_seconds", 0)

                mode_counts[mode] = mode_counts.get(mode, 0) + 1

                if mode not in mode_durations:
                    mode_durations[mode] = []
                mode_durations[mode].append(duration)

                if data.get("success"):
                    successes += 1
                else:
                    failures += 1

            elif event.event_type == "api_call":
                api_calls += 1
                total_tokens_in += data.get("tokens_in", 0)
                total_tokens_out += data.get("tokens_out", 0)

                provider = data.get("provider", "unknown")
                provider_counts[provider] = provider_counts.get(provider, 0) + 1

                if data.get("success"):
                    successes += 1
                else:
                    failures += 1

            elif event.event_type == "tool_execution":
                tool = data.get("tool_name", "unknown")
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

                if data.get("success"):
                    successes += 1
                else:
                    failures += 1

            elif event.event_type == "error":
                errors += 1

        # Calculate averages
        avg_latency_by_mode = {}
        for mode, durations in mode_durations.items():
            if durations:
                avg_latency_by_mode[mode] = round(sum(durations) / len(durations), 2)

        total_operations = successes + failures
        success_rate = round(successes / total_operations * 100, 1) if total_operations > 0 else 0.0

        avg_tokens_in = round(total_tokens_in / api_calls, 0) if api_calls > 0 else 0
        avg_tokens_out = round(total_tokens_out / api_calls, 0) if api_calls > 0 else 0

        # Top modes (sorted by count)
        top_modes = sorted(mode_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "period_days": days,
            "period_start": since.isoformat(),
            "period_end": datetime.now(UTC).isoformat(),
            "total_events": total_events,
            "success_rate": success_rate,
            "successes": successes,
            "failures": failures,
            "error_count": errors,
            "api_calls": api_calls,
            "total_tokens": {
                "input": total_tokens_in,
                "output": total_tokens_out,
                "total": total_tokens_in + total_tokens_out,
            },
            "avg_tokens_per_call": {"input": int(avg_tokens_in), "output": int(avg_tokens_out)},
            "avg_latency_by_mode": avg_latency_by_mode,
            "top_modes": dict(top_modes),
            "provider_distribution": provider_counts,
            "tool_usage": dict(sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
        }

    def format_report_for_console(self, report: dict[str, Any]) -> str:
        """
        Format a report dictionary for console display.

        Args:
            report: Report from generate_report().

        Returns:
            Formatted string for console output.
        """
        lines = []
        lines.append("=" * 60)
        lines.append("  NEXUS TELEMETRY REPORT")
        lines.append("=" * 60)
        lines.append("")

        # Period
        lines.append(f"Period: Last {report['period_days']} days")
        lines.append(f"Events: {report['total_events']:,}")
        lines.append("")

        # Success rate
        lines.append("--- Performance ---")
        success_rate = report["success_rate"]
        status_icon = "[OK]" if success_rate >= 80 else "[warning]" if success_rate >= 50 else "[NO]"
        lines.append(f"Success Rate: {status_icon} {success_rate}%")
        lines.append(f"  Successes: {report['successes']:,}")
        lines.append(f"  Failures: {report['failures']:,}")
        lines.append(f"  Errors: {report['error_count']:,}")
        lines.append("")

        # Tokens
        if report["api_calls"] > 0:
            lines.append("--- API Usage ---")
            lines.append(f"API Calls: {report['api_calls']:,}")
            lines.append(f"Total Tokens: {report['total_tokens']['total']:,}")
            lines.append(f"  Input: {report['total_tokens']['input']:,}")
            lines.append(f"  Output: {report['total_tokens']['output']:,}")
            lines.append(
                f"Avg/Call: {report['avg_tokens_per_call']['input']} in / {report['avg_tokens_per_call']['output']} out"
            )
            lines.append("")

        # Provider distribution
        if report["provider_distribution"]:
            lines.append("--- Providers ---")
            for provider, count in report["provider_distribution"].items():
                pct = round(count / report["api_calls"] * 100, 1) if report["api_calls"] > 0 else 0
                lines.append(f"  {provider}: {count:,} ({pct}%)")
            lines.append("")

        # Modes
        if report["top_modes"]:
            lines.append("--- Swarm Modes ---")
            for mode, count in report["top_modes"].items():
                latency = report["avg_latency_by_mode"].get(mode, 0)
                lines.append(f"  {mode}: {count}x (avg {latency}s)")
            lines.append("")

        # Tools
        if report["tool_usage"]:
            lines.append("--- Top Tools ---")
            for tool, count in list(report["tool_usage"].items())[:5]:
                lines.append(f"  {tool}: {count}x")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)
