"""
V9.1 Evolution Commands - /evolve, /evolve-status, /review

These commands manage the evolution system for spawning and selecting
improved agent variants.

Uses EvolutionService for business logic (Service Layer Pattern).
"""

from .registry import Command, CommandContext, CommandRegistry, CommandResult, CommandStatus


def _get_evolution_service(context: CommandContext):
    """
    Get or create EvolutionService from context.

    EvolutionService requires evolution_manager, console, and config.
    """
    from core.intelligence.evolution import EvolutionService

    # Try to get cached service from extras
    service = context.extras.get("evolution_service")
    if service:
        return service

    # Get evolution_manager from extras or repl
    evolution_manager = context.extras.get("evolution_manager")
    if not evolution_manager:
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "evolution_manager"):
            evolution_manager = repl.evolution_manager
        else:
            raise RuntimeError("EvolutionManager not available")

    # Get config
    config = context.config
    if not config and hasattr(context.orchestrator, "config"):
        config = context.orchestrator.config
    if not config:
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "config"):
            config = repl.config

    # Get workspace_path and rate_limiter
    workspace_path = context.extras.get("workspace_path")
    rate_limiter = context.extras.get("rate_limiter")

    if not workspace_path and hasattr(evolution_manager, "workspace_path"):
        workspace_path = evolution_manager.workspace_path
    if not rate_limiter:
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "rate_limiter"):
            rate_limiter = repl.rate_limiter
        elif hasattr(evolution_manager, "rate_limiter"):
            rate_limiter = evolution_manager.rate_limiter

    return EvolutionService(
        evolution_manager=evolution_manager,
        console=context.console,
        config=config,
        workspace_path=workspace_path,
        rate_limiter=rate_limiter,
    )


class EvolveCommand(Command):
    """Start an evolution cycle to generate child variants."""

    @property
    def name(self) -> str:
        return "/evolve"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Start evolution cycle to generate improved agent variants"

    @property
    def usage(self) -> str:
        return "/evolve [child_count] (default: 3)"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute evolve command using EvolutionService."""
        try:
            service = _get_evolution_service(context)
            # Parse child count from args (default 3)
            child_count = int(args) if args.strip().isdigit() else 3
            result = service.evolve(child_count=child_count)

            if result.success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message="",  # Service handles its own output
                )
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Evolution failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Evolution failed: {e}")


class EvolveStatusCommand(Command):
    """Show current evolution status."""

    @property
    def name(self) -> str:
        return "/evolve-status"

    @property
    def aliases(self) -> list[str]:
        return ["/es"]

    @property
    def description(self) -> str:
        return "Show current evolution status and child variants"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute evolve-status command using EvolutionService."""
        try:
            service = _get_evolution_service(context)
            result = service.status()

            if result.success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message="",  # Service handles its own output
                )
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Failed to get status")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Failed to get evolution status: {e}")


class ReviewCommand(Command):
    """Review and select from evolved children."""

    @property
    def name(self) -> str:
        return "/review"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Review evolved children and select best variant"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute review command.

        Note: /review still uses repl.run_review() because it requires
        interactive input (keyboard prompts). Service layer handles
        the promote/archive operations.
        """
        repl = context.extras.get("repl")
        if not repl:
            return CommandResult(
                status=CommandStatus.ERROR, message="REPL instance not available (interactive review requires REPL)"
            )

        try:
            repl.run_review()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Review failed: {e}")


def register_evolution_commands(registry: "CommandRegistry") -> None:
    """Register all evolution commands with a registry."""
    registry.register(EvolveCommand())
    registry.register(EvolveStatusCommand())
    registry.register(ReviewCommand())
