"""
V9.1 Miscellaneous Commands - /mode, /reset, /doctor, /telemetry, /budget, /tutorial, /quickstart, /chat, /clear

These commands provide various utility functions for the REPL.

V9.1: TelemetryCommand and BudgetCommand now use Service Layer (TelemetryService, BudgetService).
"""

from .registry import Command, CommandContext, CommandRegistry, CommandResult, CommandStatus


def _get_telemetry_service(context: CommandContext):
    """Get or create TelemetryService from context."""
    from core.observability.telemetry import _get_telemetry_service as get_service

    return get_service(context)


def _get_budget_service(context: CommandContext):
    """Get or create BudgetService from context."""
    from core.observability.telemetry import _get_budget_service as get_service

    return get_service(context)


class ClearCommand(Command):
    """Clear the console screen."""

    @property
    def name(self) -> str:
        return "/clear"

    @property
    def aliases(self) -> list[str]:
        return ["/cls"]

    @property
    def description(self) -> str:
        return "Clear the console screen"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute clear command."""
        context.console.clear()
        return CommandResult(status=CommandStatus.SUCCESS, message="")


class ModeCommand(Command):
    """Change the orchestrator mode."""

    @property
    def name(self) -> str:
        return "/mode"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Change the orchestrator mode"

    @property
    def usage(self) -> str:
        return "/mode <mode_name>"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute mode command."""
        if not args.strip():
            return CommandResult(status=CommandStatus.INVALID_ARGS, message="Usage: /mode <mode_name>")

        context.orchestrator.blackboard["mode"] = args.strip()
        return CommandResult(status=CommandStatus.SUCCESS, message=f"Mode changed to: {args.strip()}")


class ResetCommand(Command):
    """Reset the orchestrator to IDLE state."""

    @property
    def name(self) -> str:
        return "/reset"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Reset the orchestrator to IDLE state"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute reset command."""
        try:
            context.orchestrator.reset_to_idle()
            return CommandResult(status=CommandStatus.SUCCESS, message="Orchestrator reset to IDLE")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Reset failed: {e}")


class DoctorCommand(Command):
    """Run system diagnostics."""

    @property
    def name(self) -> str:
        return "/doctor"

    @property
    def aliases(self) -> list[str]:
        return ["/diag"]

    @property
    def description(self) -> str:
        return "Run system diagnostics and check API connectivity"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute doctor command."""
        repl = context.extras.get("repl")
        if not repl:
            return CommandResult(status=CommandStatus.ERROR, message="REPL instance not available")

        try:
            repl.run_doctor()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Diagnostics failed: {e}")


class TelemetryCommand(Command):
    """Manage telemetry settings."""

    @property
    def name(self) -> str:
        return "/telemetry"

    @property
    def aliases(self) -> list[str]:
        return ["/tel"]

    @property
    def description(self) -> str:
        return "View or configure telemetry settings"

    @property
    def usage(self) -> str:
        return "/telemetry [status|report|export] [days]"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute telemetry command using TelemetryService.

        V9.1: Delegated to TelemetryService (Service Layer Pattern).
        """
        try:
            service = _get_telemetry_service(context)
            parts = args.strip().split()
            subcommand = parts[0] if parts else "status"

            if subcommand == "status":
                result = service.status()
            elif subcommand == "report":
                days = int(parts[1]) if len(parts) > 1 else 7
                result = service.report(days=days)
            elif subcommand == "export":
                days = int(parts[1]) if len(parts) > 1 else None
                result = service.export(days=days)
            else:
                # Default to status for unknown subcommands
                result = service.status()

            if result.success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message="",  # Service handles its own output
                )
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Telemetry command failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Telemetry command failed: {e}")


class BudgetCommand(Command):
    """Manage token budget."""

    @property
    def name(self) -> str:
        return "/budget"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "View or set token budget for API calls"

    @property
    def usage(self) -> str:
        return "/budget [status|reset|add <amount>|history]"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute budget command using BudgetService.

        V9.1: Delegated to BudgetService (Service Layer Pattern).
        """
        try:
            service = _get_budget_service(context)
            parts = args.strip().split()
            subcommand = parts[0] if parts else "status"

            if subcommand == "status" or not subcommand:
                result = service.status()
            elif subcommand == "reset":
                result = service.reset(confirmed=False)
            elif subcommand == "add":
                if len(parts) < 2:
                    return CommandResult(status=CommandStatus.INVALID_ARGS, message="Usage: /budget add <amount>")
                try:
                    amount = float(parts[1])
                    result = service.add_credit(amount)
                except ValueError:
                    return CommandResult(status=CommandStatus.INVALID_ARGS, message="Amount must be a number")
            elif subcommand == "history":
                result = service.history()
            else:
                # Default to status for unknown subcommands
                result = service.status()

            if result.success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message="",  # Service handles its own output
                )
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Budget command failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Budget command failed: {e}")


class TutorialCommand(Command):
    """Run the interactive tutorial."""

    @property
    def name(self) -> str:
        return "/tutorial"

    @property
    def aliases(self) -> list[str]:
        return ["/tut"]

    @property
    def description(self) -> str:
        return "Run the interactive NEXUS tutorial"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute tutorial command."""
        repl = context.extras.get("repl")
        if not repl:
            return CommandResult(status=CommandStatus.ERROR, message="REPL instance not available")

        try:
            repl.run_tutorial()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Tutorial failed: {e}")


class QuickstartCommand(Command):
    """Show quickstart guide."""

    @property
    def name(self) -> str:
        return "/quickstart"

    @property
    def aliases(self) -> list[str]:
        return ["/qs"]

    @property
    def description(self) -> str:
        return "Show the NEXUS quickstart guide"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute quickstart command."""
        repl = context.extras.get("repl")
        if not repl:
            return CommandResult(status=CommandStatus.ERROR, message="REPL instance not available")

        try:
            repl.show_quickstart()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Quickstart failed: {e}")


class ChatCommand(Command):
    """Toggle chat mode."""

    @property
    def name(self) -> str:
        return "/chat"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Toggle chat mode for direct AI conversation"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute chat command."""
        repl = context.extras.get("repl")
        if not repl:
            return CommandResult(status=CommandStatus.ERROR, message="REPL instance not available")

        try:
            repl.toggle_chat_mode()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Chat toggle failed: {e}")


def register_misc_commands(registry: "CommandRegistry") -> None:
    """Register all miscellaneous commands with a registry."""
    registry.register(ClearCommand())
    registry.register(ModeCommand())
    registry.register(ResetCommand())
    registry.register(DoctorCommand())
    registry.register(TelemetryCommand())
    registry.register(BudgetCommand())
    registry.register(TutorialCommand())
    registry.register(QuickstartCommand())
    registry.register(ChatCommand())
