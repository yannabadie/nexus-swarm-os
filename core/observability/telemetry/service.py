"""
NEXUS V9.1 - TelemetryService & BudgetService

Service Layer for Telemetry and Budget operations.
Wraps TelemetryExporter and BudgetTracker with UI output (console callbacks).

This service handles:
- Telemetry report display
- Telemetry status
- CSV export
- Budget status display
- Budget reset/add credit
- Cost history display

Usage:
    from core.observability.telemetry.service import TelemetryService, BudgetService

    telemetry_service = TelemetryService(workspace_path, console)
    telemetry_service.report(days=7)
    telemetry_service.status()
    telemetry_service.export(days=30)

    budget_service = BudgetService(workspace_path, console)
    budget_service.status()
    budget_service.reset()
    budget_service.add_credit(10.0)
    budget_service.history()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config
    from core.interface_pkg.interface.console_v7 import ConsoleV7
    from core.security_pkg.interaction import InteractionProvider


@dataclass
class ServiceResult:
    """Result of a service operation."""

    success: bool
    message: str | None = None
    error: str | None = None
    data: dict[str, Any] | None = None


class TelemetryService:
    """
    Service for Telemetry operations.

    Wraps TelemetryExporter with console UI output.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.
    """

    def __init__(
        self,
        workspace_path: Path,
        console: ConsoleV7,
        config: Config | None = None,
    ):
        """
        Initialize TelemetryService.

        Args:
            workspace_path: Path to workspace directory
            console: Console for output
            config: Optional configuration object
        """
        self.workspace_path = Path(workspace_path)
        self.console = console
        self.config = config

    def _get_exporter(self):
        """Get TelemetryExporter instance."""
        from core.observability.telemetry import TelemetryExporter

        return TelemetryExporter(self.workspace_path)

    # ==================== PUBLIC API ====================

    def report(self, days: int = 7) -> ServiceResult:
        """
        Display telemetry performance report.

        Args:
            days: Number of days to include in report (default: 7)

        Returns:
            ServiceResult with report data
        """
        exporter = self._get_exporter()
        event_count = exporter.get_event_count()

        if event_count == 0:
            self.console.print("\n  Telemetry Report\n")
            self.console.print("[dim]No telemetry data available yet.[/dim]")
            self.console.print("[dim]Telemetry is recorded when you use /swarm, API calls, etc.[/dim]\n")
            return ServiceResult(success=True, message="No data")

        report = exporter.generate_report(days=days)
        formatted = exporter.format_report_for_console(report)
        self.console.console.print(formatted)

        return ServiceResult(success=True, data=report)

    def status(self) -> ServiceResult:
        """
        Display detailed telemetry status.

        Returns:
            ServiceResult with status data
        """
        from rich.panel import Panel

        exporter = self._get_exporter()
        event_count = exporter.get_event_count()
        file_exists = exporter.telemetry_file.exists()
        file_size = exporter.telemetry_file.stat().st_size if file_exists else 0

        # Format file size
        if file_size < 1024:
            size_str = f"{file_size} B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"

        status_lines = [
            f"  File: {exporter.telemetry_file}",
            f"   Exists: {'Yes' if file_exists else 'No'}",
            f"   Size: {size_str}",
            f"   Events: {event_count:,}",
        ]

        if self.config:
            status_lines.extend(
                [
                    "",
                    "  Config:",
                    f"   Enabled: {getattr(self.config, 'telemetry_enabled', True)}",
                    f"   File: {getattr(self.config, 'telemetry_file', 'telemetry.jsonl')}",
                ]
            )

        if event_count > 0:
            report = exporter.generate_report(days=7)
            status_lines.extend(
                [
                    "",
                    "  Last 7 Days:",
                    f"   API Calls: {report['api_calls']:,}",
                    f"   Success Rate: {report['success_rate']}%",
                    f"   Total Tokens: {report['total_tokens']['total']:,}",
                ]
            )

        panel = Panel("\n".join(status_lines), title="[bold]Telemetry Status[/bold]", border_style="blue")
        self.console.console.print(panel)

        return ServiceResult(
            success=True,
            data={
                "file_exists": file_exists,
                "file_size": file_size,
                "event_count": event_count,
            },
        )

    def export(self, days: int | None = None) -> ServiceResult:
        """
        Export telemetry to CSV file.

        Args:
            days: Number of days to export (None = all)

        Returns:
            ServiceResult with export path
        """
        exporter = self._get_exporter()
        event_count = exporter.get_event_count()

        if event_count == 0:
            self.console.print("\n[yellow]No telemetry data to export.[/yellow]")
            self.console.print("[dim]Start using /swarm to generate telemetry data.[/dim]\n")
            return ServiceResult(success=False, error="No data to export")

        try:
            csv_path = exporter.export_to_csv(days=days)
            period = f" (last {days} days)" if days else " (all time)"

            self.console.print(f"\n  Telemetry exported successfully{period}")
            self.console.print(f"   File: {csv_path}")
            self.console.print(f"   Events: {event_count:,}")
            self.console.print("\n[dim]Import in Excel, Grafana, or analyze with pandas.[/dim]\n")

            return ServiceResult(success=True, data={"path": str(csv_path), "events": event_count})

        except OSError as e:
            self.console.print_error(f"Export failed: {e}")
            return ServiceResult(success=False, error=str(e))


class BudgetService:
    """
    Service for Budget Tracker operations.

    Wraps BudgetTracker with console UI output.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.

    V9.8 DETOX: Supports headless mode via InteractionProvider.
    """

    def __init__(
        self,
        workspace_path: Path,
        console: ConsoleV7,
        config: Config | None = None,
        interaction: InteractionProvider | None = None,
    ):
        """
        Initialize BudgetService.

        Args:
            workspace_path: Path to workspace directory
            console: Console for output
            config: Optional configuration object
            interaction: Optional interaction provider for headless mode
        """
        self.workspace_path = Path(workspace_path)
        self.console = console
        self.config = config
        self._interaction = interaction

    def _get_tracker(self):
        """Get BudgetTracker instance."""
        from core.observability.telemetry import BudgetTracker

        return BudgetTracker(self.config, self.workspace_path)

    # ==================== PUBLIC API ====================

    def status(self) -> ServiceResult:
        """
        Display current budget status.

        Returns:
            ServiceResult with budget stats
        """
        tracker = self._get_tracker()
        stats = tracker.get_stats()
        warning = tracker.get_warning_level()

        # Build status display
        lines = [
            "",
            "=" * 64,
            "                    BUDGET STATUS                          ",
            "=" * 64,
            "",
        ]

        # Progress bar
        pct = stats["percentage_used"]
        bar_width = 40
        filled = int(bar_width * pct / 100)
        bar = "#" * filled + "-" * (bar_width - filled)

        if warning == "critical":
            color = "[bold red]"
        elif warning == "warning":
            color = "[yellow]"
        else:
            color = "[green]"

        lines.append(f"  {color}[{bar}] {pct:.1f}%[/{color.split('[')[1]}")
        lines.append("")
        lines.append(f"  Spent Today:    ${stats['spent_today_usd']:.4f}")
        lines.append(f"  Daily Limit:    ${stats['limit_usd']:.2f}")
        lines.append(f"  Remaining:      ${stats['remaining_usd']:.4f}")
        lines.append("")
        lines.append(f"  API Calls:      {stats['api_calls_today']}")
        lines.append(f"  Reset Date:     {stats['reset_date']}")

        if warning:
            lines.append("")
            if warning == "critical":
                lines.append("  [bold red]CRITICAL: Budget at 90%+! Consider /budget add[/bold red]")
            else:
                lines.append("  [yellow]WARNING: Budget at 80%+[/yellow]")

        lines.append("")
        lines.append("-" * 64)
        lines.append("  /budget reset     Reset counter (emergency)")
        lines.append("  /budget add <n>   Add credit ($)")
        lines.append("  /budget history   Show recent costs")
        lines.append("")

        for line in lines:
            self.console.console.print(line)

        return ServiceResult(success=True, data=stats)

    def reset(self, confirmed: bool = False) -> ServiceResult:
        """
        Reset daily budget counter.

        Args:
            confirmed: If True, skip confirmation prompt

        Returns:
            ServiceResult with reset status
        """
        tracker = self._get_tracker()

        if not confirmed:
            # Ask for confirmation
            self.console.print("\n[yellow]This will reset your daily budget counter.[/yellow]")
            self.console.print("    Current spent amount will be set to $0.00.")
            try:
                user_confirmed = self._confirm_reset()
                if not user_confirmed:
                    self.console.print("\n[dim]Reset cancelled.[/dim]\n")
                    return ServiceResult(success=False, message="Cancelled by user")
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]Reset cancelled.[/dim]\n")
                return ServiceResult(success=False, message="Cancelled by user")

        tracker.reset_daily()
        self.console.print("\n[green]Budget counter reset successfully.[/green]")
        self.console.print("   Daily spent: $0.00\n")

        return ServiceResult(success=True, message="Budget reset")

    def _confirm_reset(self) -> bool:
        """
        Ask user to confirm budget reset.

        V9.8 DETOX: Uses InteractionProvider for headless compatibility.

        Returns:
            True if user confirms, False otherwise.
        """
        if self._interaction is not None:
            # V11.4 ASYNC: Use run_coroutine_threadsafe when loop is running
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self._interaction.confirm("Reset budget counter?", default=False), loop
                )
                return future.result(timeout=30)
            except RuntimeError:
                # No running loop - create one
                return asyncio.run(self._interaction.confirm("Reset budget counter?", default=False))
        else:
            # Fallback: Use provider from factory
            from core.security_pkg.interaction import get_interaction_provider

            provider = get_interaction_provider()

            if provider.is_interactive:
                # Direct sync input for CLI (avoid event loop issues)
                response = input("\n    Type 'yes' to confirm: ").strip().lower()
                return response == "yes"
            else:
                # V11.4 ASYNC: Use run_coroutine_threadsafe when loop is running
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        provider.confirm("Reset budget counter?", default=False), loop
                    )
                    return future.result(timeout=30)
                except RuntimeError:
                    # No running loop - create one
                    return asyncio.run(provider.confirm("Reset budget counter?", default=False))

    def add_credit(self, amount: float) -> ServiceResult:
        """
        Add emergency credit to budget.

        Args:
            amount: Amount in USD to add

        Returns:
            ServiceResult with new budget info
        """
        if amount <= 0:
            self.console.print_error("Amount must be positive")
            return ServiceResult(success=False, error="Amount must be positive")

        tracker = self._get_tracker()
        old_limit = tracker.limit_usd
        tracker.add_credit(amount)
        new_limit = tracker.limit_usd

        self.console.print(f"\n[green]Added ${amount:.2f} to daily budget.[/green]")
        self.console.print(f"   Previous limit: ${old_limit:.2f}")
        self.console.print(f"   New limit:      ${new_limit:.2f}")
        self.console.print(f"   Remaining:      ${tracker.get_remaining():.4f}\n")

        return ServiceResult(
            success=True,
            data={
                "old_limit": old_limit,
                "new_limit": new_limit,
                "remaining": tracker.get_remaining(),
            },
        )

    def history(self) -> ServiceResult:
        """
        Show recent API costs from telemetry.

        Returns:
            ServiceResult with history data
        """
        from core.observability.telemetry import TelemetryExporter

        exporter = TelemetryExporter(self.workspace_path)
        events = exporter.read_events(days=1)

        # Filter api_call events
        api_calls = [e for e in events if e.event_type == "api_call"]

        if not api_calls:
            self.console.print("\n  Recent API Costs\n")
            self.console.print("[dim]No API calls recorded in the last 24 hours.[/dim]\n")
            return ServiceResult(success=True, message="No API calls", data={"count": 0})

        lines = [
            "",
            "=" * 64,
            "                  RECENT API COSTS (24h)                   ",
            "=" * 64,
            "",
            "  Time          Provider    Model              Tokens (I/O)",
            "  " + "-" * 61,
        ]

        # Show last 10 calls
        for event in api_calls[-10:]:
            data = event.data
            time_str = event.timestamp.strftime("%H:%M:%S")
            provider = data.get("provider", "?")[:10]
            model = data.get("model", "?")[:18]
            tokens_in = data.get("tokens_in", 0)
            tokens_out = data.get("tokens_out", 0)
            lines.append(f"  {time_str}    {provider:<10} {model:<18} {tokens_in:>6}/{tokens_out:<6}")

        lines.append("")
        lines.append(f"  Total calls (24h): {len(api_calls)}")
        lines.append("")

        for line in lines:
            self.console.console.print(line)

        return ServiceResult(success=True, data={"count": len(api_calls)})


def _get_telemetry_service(context) -> TelemetryService:
    """Get or create TelemetryService from command context."""
    service = context.extras.get("telemetry_service")
    if service:
        return service

    workspace_path = context.extras.get("workspace_path")
    if not workspace_path:
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "workspace_path"):
            workspace_path = repl.workspace_path

    config = context.config or context.extras.get("config")

    return TelemetryService(
        workspace_path=workspace_path,
        console=context.console,
        config=config,
    )


def _get_budget_service(context) -> BudgetService:
    """Get or create BudgetService from command context."""
    service = context.extras.get("budget_service")
    if service:
        return service

    workspace_path = context.extras.get("workspace_path")
    if not workspace_path:
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "workspace_path"):
            workspace_path = repl.workspace_path

    config = context.config or context.extras.get("config")

    return BudgetService(
        workspace_path=workspace_path,
        console=context.console,
        config=config,
    )
