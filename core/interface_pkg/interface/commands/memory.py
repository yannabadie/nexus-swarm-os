"""
V9.1 Memory Commands - /learn, /forget, /memory-status, /rag

These commands manage Project Memory (RAG) for context retrieval.
Uses MemoryService for business logic (Service Layer Pattern).
"""

from .registry import Command, CommandContext, CommandRegistry, CommandResult, CommandStatus


def _get_memory_service(context: CommandContext):
    """
    Get or create MemoryService from context.

    MemoryService requires project_memory, workspace_path, and console.
    These are available through the CommandContext.
    """
    from core.memory_pkg.memory import MemoryService

    # Try to get cached service from extras
    service = context.extras.get("memory_service")
    if service:
        return service

    # Get project_memory from orchestrator
    project_memory = None
    if hasattr(context.orchestrator, "project_memory"):
        project_memory = context.orchestrator.project_memory

    if not project_memory:
        raise ValueError("Project memory not available")

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

    return MemoryService(project_memory=project_memory, workspace_path=workspace_path, console=context.console)


class LearnCommand(Command):
    """Add knowledge to Project Memory."""

    @property
    def name(self) -> str:
        return "/learn"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Index file or directory into Project Memory (RAG)"

    @property
    def usage(self) -> str:
        return "/learn <path> (e.g., /learn core/)"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute learn command using MemoryService."""
        try:
            service = _get_memory_service(context)
            result = service.learn(args.strip() if args else "")

            if result.success:
                return CommandResult(status=CommandStatus.SUCCESS, message="")
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Learn failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Learn command failed: {e}")


class ForgetCommand(Command):
    """Remove knowledge from Project Memory."""

    @property
    def name(self) -> str:
        return "/forget"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "Remove file or directory from Project Memory"

    @property
    def usage(self) -> str:
        return "/forget <path>"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute forget command using MemoryService."""
        try:
            service = _get_memory_service(context)
            result = service.forget(args.strip() if args else "")

            if result.success:
                return CommandResult(status=CommandStatus.SUCCESS, message="")
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Forget failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Forget command failed: {e}")


class MemoryStatusCommand(Command):
    """Show Project Memory status."""

    @property
    def name(self) -> str:
        return "/memory-status"

    @property
    def aliases(self) -> list[str]:
        return ["/ms"]

    @property
    def description(self) -> str:
        return "Show Project Memory (RAG) status and statistics"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute memory-status command using MemoryService."""
        try:
            service = _get_memory_service(context)
            service.get_status()
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Failed to get memory status: {e}")


class RagCommand(Command):
    """RAG operations for Project Memory."""

    @property
    def name(self) -> str:
        return "/rag"

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def description(self) -> str:
        return "RAG operations: init, clear, query"

    @property
    def usage(self) -> str:
        return "/rag <init|clear|query <text>>"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute rag command using MemoryService."""
        try:
            service = _get_memory_service(context)
            service.handle_rag_command(args.strip() if args else "")
            return CommandResult(status=CommandStatus.SUCCESS, message="")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"RAG command failed: {e}")


def register_memory_commands(registry: "CommandRegistry") -> None:
    """Register all memory commands with a registry."""
    registry.register(LearnCommand())
    registry.register(ForgetCommand())
    registry.register(MemoryStatusCommand())
    registry.register(RagCommand())
