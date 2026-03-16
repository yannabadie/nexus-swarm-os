"""
V9.1 Swarm Commands - /swarm, /swarm-status, /swarm-fsm

These commands manage the Hybrid Swarm Engine for multi-agent collaboration.
Uses SwarmService for business logic (Service Layer Pattern).
"""

from .registry import Command, CommandContext, CommandRegistry, CommandResult, CommandStatus


def _get_swarm_service(context: CommandContext):
    """
    Get or create SwarmService from context.

    SwarmService requires orchestrator, console, and config.
    """
    from core.intelligence.swarm import SwarmService

    # Try to get cached service from extras
    service = context.extras.get("swarm_service")
    if service:
        return service

    # Get config from extras or orchestrator
    config = context.config
    if not config and hasattr(context.orchestrator, "config"):
        config = context.orchestrator.config

    if not config:
        # Fallback: try to get from repl if available
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "config"):
            config = repl.config

    return SwarmService(orchestrator=context.orchestrator, console=context.console, config=config)


class SwarmCommand(Command):
    """Execute a task using the Swarm Engine."""

    @property
    def name(self) -> str:
        return "/swarm"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Execute a task using multi-agent collaboration"

    @property
    def usage(self) -> str:
        return "/swarm <task description>"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute swarm command using SwarmService."""
        if not args.strip():
            return CommandResult(
                status=CommandStatus.INVALID_ARGS,
                message="Usage: /swarm <task description>\nExample: /swarm Analyze this codebase and find bugs",
            )

        try:
            service = _get_swarm_service(context)
            result = service.run_task(args.strip())

            if result.success:
                return CommandResult(status=CommandStatus.SUCCESS, message="")
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Swarm task failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Swarm task failed: {e}")


class SwarmStatusCommand(Command):
    """Show current Swarm Engine status."""

    @property
    def name(self) -> str:
        return "/swarm-status"

    @property
    def aliases(self) -> list[str]:
        return ["/ss"]

    @property
    def description(self) -> str:
        return "Show Swarm Engine status and DyLAN metrics"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute swarm-status command using SwarmService."""
        try:
            service = _get_swarm_service(context)
            service.get_status()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Failed to get swarm status: {e}")


class SwarmFSMCommand(Command):
    """Execute a task using FSM-based Swarm mode."""

    @property
    def name(self) -> str:
        return "/swarm-fsm"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Execute task via FSM states (debug mode)"

    @property
    def usage(self) -> str:
        return "/swarm-fsm <task description>"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute swarm-fsm command using SwarmService."""
        if not args.strip():
            return CommandResult(
                status=CommandStatus.INVALID_ARGS,
                message="Usage: /swarm-fsm <task description>\nDebug: Uses FSM states (SWARM_ANALYZING -> NEGOTIATING -> EXECUTING)",
            )

        try:
            service = _get_swarm_service(context)
            result = service.run_task_fsm(args.strip())

            if result.success:
                return CommandResult(status=CommandStatus.SUCCESS, message="")
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Swarm FSM task failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Swarm FSM task failed: {e}")


def register_swarm_commands(registry: "CommandRegistry") -> None:
    """Register all swarm commands with a registry."""
    registry.register(SwarmCommand())
    registry.register(SwarmStatusCommand())
    registry.register(SwarmFSMCommand())
