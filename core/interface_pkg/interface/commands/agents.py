"""
V9.1 Agent Commands - /spawn, /agents, /pool-stats

These commands manage spawned agents and the agent pool.
Uses AgentService for business logic (Service Layer Pattern).
"""

from .registry import Command, CommandContext, CommandRegistry, CommandResult, CommandStatus


def _get_agent_service(context: CommandContext):
    """
    Get or create AgentService from context.

    AgentService requires orchestrator, workspace_path, and console.
    These are available through the CommandContext.
    """
    from core.foundation.agents import AgentService

    # Try to get cached service from extras
    service = context.extras.get("agent_service")
    if service:
        return service

    # Get workspace_path from extras or orchestrator
    workspace_path = context.extras.get("workspace_path")
    if not workspace_path and hasattr(context.orchestrator, "workspace_path"):
        workspace_path = context.orchestrator.workspace_path

    if not workspace_path:
        # Fallback: try to get from repl if available
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "workspace_path"):
            workspace_path = repl.workspace_path

    if not workspace_path:
        raise ValueError("workspace_path not available in context")

    return AgentService(orchestrator=context.orchestrator, workspace_path=workspace_path, console=context.console)


class SpawnCommand(Command):
    """Spawn a new specialized agent."""

    @property
    def name(self) -> str:
        return "/spawn"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Spawn a new specialized agent with a specific role"

    @property
    def usage(self) -> str:
        return "/spawn <role> (e.g., /spawn SQL Expert)"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute spawn command using AgentService."""
        if not args.strip():
            return CommandResult(
                status=CommandStatus.INVALID_ARGS, message="Usage: /spawn <role> (e.g., /spawn SQL Expert)"
            )

        try:
            service = _get_agent_service(context)
            result = service.spawn(args.strip())

            if result.success:
                return CommandResult(status=CommandStatus.SUCCESS, message="")
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Spawn failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Failed to spawn agent: {e}")


class AgentsCommand(Command):
    """List all registered agents."""

    @property
    def name(self) -> str:
        return "/agents"

    @property
    def aliases(self) -> list[str]:
        return ["/a"]

    @property
    def description(self) -> str:
        return "List all registered agents and their capabilities"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute agents command using AgentService."""
        try:
            service = _get_agent_service(context)
            service.list_agents()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Failed to list agents: {e}")


class PoolStatsCommand(Command):
    """Show agent pool statistics."""

    @property
    def name(self) -> str:
        return "/pool-stats"

    @property
    def aliases(self) -> list[str]:
        return ["/ps"]

    @property
    def description(self) -> str:
        return "Show agent pool statistics and usage metrics"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute pool-stats command using AgentService."""
        try:
            service = _get_agent_service(context)
            service.get_pool_stats()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Failed to get pool stats: {e}")


def register_agent_commands(registry: "CommandRegistry") -> None:
    """Register all agent commands with a registry."""
    registry.register(SpawnCommand())
    registry.register(AgentsCommand())
    registry.register(PoolStatsCommand())
