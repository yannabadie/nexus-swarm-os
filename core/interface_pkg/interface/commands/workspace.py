"""
V9.1 Workspace Commands - /bootstrap, /specialize, /workspace

These commands manage workspace configuration and project specialization.
Uses WorkspaceManager, BootstrapService, SpinoffService for business logic (Service Layer Pattern).
"""

from pathlib import Path

from .registry import Command, CommandContext, CommandRegistry, CommandResult, CommandStatus


def _get_bootstrap_service(context: CommandContext):
    """Get or create BootstrapService from context."""
    from core.infrastructure.bootstrap import _get_bootstrap_service as get_service

    return get_service(context)


def _get_spinoff_service(context: CommandContext):
    """Get or create SpinoffService from context."""
    from core.infrastructure.bootstrap import _get_spinoff_service as get_service

    return get_service(context)


def _get_workspace_manager(context: CommandContext):
    """
    Get or create WorkspaceManager from context.

    WorkspaceManager requires nexus_root path.
    NOTE: P5.6 workspace module not yet implemented — raises ImportError at runtime.
    """
    try:
        from core.interface_pkg.interface_pkg.workspace import WorkspaceManager  # noqa: F401
    except (ImportError, ModuleNotFoundError) as err:
        raise ImportError("Workspace management module not yet implemented (P5.6)") from err

    # Try to get cached manager from extras
    manager = context.extras.get("workspace_manager")
    if manager:
        return manager

    # Get nexus_root from extras or orchestrator
    nexus_root = context.extras.get("nexus_root")
    if not nexus_root and hasattr(context.orchestrator, "workspace_path"):
        # workspace_path is typically nexus_root/workspace, so go up one level
        workspace_path = context.orchestrator.workspace_path
        if workspace_path:
            nexus_root = workspace_path.parent

    if not nexus_root:
        # Fallback: try to get from repl if available
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "nexus_root"):
            nexus_root = repl.nexus_root

    if not nexus_root:
        raise ValueError("nexus_root not available in context")

    return WorkspaceManager(nexus_root)


class BootstrapCommand(Command):
    """Bootstrap a new project with NEXUS.md."""

    @property
    def name(self) -> str:
        return "/bootstrap"

    @property
    def aliases(self) -> list[str]:
        return ["/bs"]

    @property
    def description(self) -> str:
        return "Generate NEXUS.md for a project directory"

    @property
    def usage(self) -> str:
        return "/bootstrap [path] (default: current directory)"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute bootstrap command using BootstrapService.

        V9.1: Delegated to BootstrapService (Service Layer Pattern).
        """
        try:
            service = _get_bootstrap_service(context)

            # Parse path argument (default: current directory)
            project_path = Path(args.strip()).resolve() if args.strip() else None

            result = service.bootstrap(project_path)

            if result.success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message="",  # Service handles its own output
                )
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Bootstrap failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Bootstrap failed: {e}")


class SpecializeCommand(Command):
    """Create a specialized NEXUS spinoff."""

    @property
    def name(self) -> str:
        return "/specialize"

    @property
    def aliases(self) -> list[str]:
        return ["/spec"]

    @property
    def description(self) -> str:
        return "Create a specialized NEXUS spinoff for a specific mission"

    @property
    def usage(self) -> str:
        return "/specialize <mission_description>"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute specialize command using SpinoffService.

        V9.1: Delegated to SpinoffService (Service Layer Pattern).
        """
        if not args.strip():
            return CommandResult(status=CommandStatus.INVALID_ARGS, message="Usage: /specialize <mission_description>")

        try:
            service = _get_spinoff_service(context)
            result = service.specialize(mission=args.strip())

            if result.success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message="",  # Service handles its own output
                )
            else:
                return CommandResult(status=CommandStatus.ERROR, message=result.error or "Specialization failed")
        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Specialization failed: {e}")


class WorkspaceCommand(Command):
    """Manage workspace settings."""

    @property
    def name(self) -> str:
        return "/workspace"

    @property
    def aliases(self) -> list[str]:
        return ["/ws"]

    @property
    def description(self) -> str:
        return "Manage workspace (show, new, list, switch)"

    @property
    def usage(self) -> str:
        return "/workspace [new [name]|list|switch <name>]"

    def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Execute workspace command using WorkspaceManager."""
        try:
            from core.interface_pkg.interface_pkg.workspace import (  # noqa: F401
                WorkspaceError,
                WorkspaceExistsError,
                WorkspaceNotFoundError,
            )
        except (ImportError, ModuleNotFoundError):
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Workspace management not available (module not implemented)",
            )

        try:
            manager = _get_workspace_manager(context)
        except (ValueError, ImportError) as e:
            return CommandResult(status=CommandStatus.ERROR, message=str(e))

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""
        sub_args = parts[1] if len(parts) > 1 else ""

        try:
            if not subcommand:
                # /workspace - Show current workspace status
                self._show_status(manager, context)

            elif subcommand == "new":
                self._create_new(manager, context, sub_args or None)

            elif subcommand == "list":
                self._show_list(manager, context)

            elif subcommand == "switch":
                if not sub_args:
                    context.console.print_error("Usage: /workspace switch <name>")
                    context.console.print("Use '/workspace list' to see available workspaces")
                    return CommandResult(status=CommandStatus.INVALID_ARGS, message="Missing workspace name")
                self._switch_workspace(manager, context, sub_args)

            else:
                context.console.print_error(f"Unknown subcommand: {subcommand}")
                context.console.print("Usage: /workspace [new|list|switch] [args]")
                return CommandResult(status=CommandStatus.INVALID_ARGS, message=f"Unknown subcommand: {subcommand}")

            return CommandResult(status=CommandStatus.SUCCESS, message="")

        except WorkspaceNotFoundError as e:
            context.console.print_error(str(e))
            suggestions = manager.get_suggestions(sub_args)
            if suggestions:
                context.console.print(f"Did you mean: {', '.join(suggestions)}?")
            return CommandResult(status=CommandStatus.ERROR, message=str(e))

        except WorkspaceExistsError as e:
            context.console.print_error(str(e))
            return CommandResult(status=CommandStatus.ERROR, message=str(e))

        except WorkspaceError as e:
            context.console.print_error(f"Workspace error: {e}")
            return CommandResult(status=CommandStatus.ERROR, message=str(e))

        except Exception as e:
            return CommandResult(status=CommandStatus.ERROR, message=f"Workspace command failed: {e}")

    def _show_status(self, manager, context: CommandContext) -> None:
        """Display current workspace info."""
        current = manager.get_current()
        if not current:
            context.console.print("No active workspace.")
            return

        lines = [
            "",
            f"[bold cyan]Current Workspace:[/bold cyan] {current.name}",
            "",
            f"[dim]Created:[/dim]     {current.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"[dim]Last used:[/dim]   {current.get_relative_time()}",
            f'[dim]Task:[/dim]        "{current.last_task[:50] + "..." if len(current.last_task or "") > 50 else current.last_task or "None"}"',
            f"[dim]Iterations:[/dim]  {current.metrics.iterations}",
            f"[dim]Size:[/dim]        {current.get_size_human()}",
            f"[dim]Files:[/dim]       {current.metrics.files_count}",
            "",
            "[dim]Commands:[/dim]",
            "   /workspace new [name]     Create fresh workspace",
            "   /workspace list           Show all workspaces",
            "   /workspace switch <name>  Switch to another workspace",
            "",
        ]

        for line in lines:
            context.console.console.print(line)

    def _show_list(self, manager, context: CommandContext) -> None:
        """Display workspace list."""
        workspaces = manager.list_workspaces()

        if not workspaces:
            context.console.print("No workspaces found.")
            return

        context.console.print("\n[bold]NEXUS Workspaces[/bold]\n")
        context.console.print(f"{'Status':<10} {'Name':<28} {'Last Used':<14} {'Size':<10}")
        context.console.print("-" * 65)

        for ws in workspaces:
            status = "[green]ACTIVE[/green]" if ws.is_current else ""
            name = ws.name[:28] if ws.name else "unnamed"
            last_used = ws.get_relative_time()
            size = ws.get_size_human()

            context.console.console.print(f"{status:<10} {name:<28} {last_used:<14} {size:<10}")

        context.console.print("\n[dim]Tip: Use /workspace switch <name> to change workspace[/dim]")

    def _create_new(self, manager, context: CommandContext, name: str = None) -> None:
        """Create new workspace."""
        current = manager.get_current()

        context.console.print("\n[package] [bold]Creating new workspace[/bold]\n")

        if current:
            context.console.print(f"  Current workspace: {current.name}")
            context.console.print(f"  Will archive to:   workspace_archive/{current.name}/")

        if name:
            context.console.print(f"\n  New workspace: {name}")
        else:
            context.console.print("\n  New workspace: [auto-generated]")

        # Note: For non-interactive mode, we proceed without confirmation
        # In interactive mode, REPL handles confirmation
        new_ws = manager.create_workspace(name=name, archive_current=True)

        context.console.print("  [checkmark] Workspace archived")
        context.console.print("  [checkmark] New workspace created")
        context.console.print(f"\n[checkmark] Workspace ready: [bold cyan]{new_ws.name}[/bold cyan]\n")

        # Reinit orchestrator if needed (REPL handles this)
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "_reinit_orchestrator"):
            repl._reinit_orchestrator(new_ws.path)

    def _switch_workspace(self, manager, context: CommandContext, name: str) -> None:
        """Switch to another workspace."""
        current = manager.get_current()

        # Find target
        target = manager.find_workspace(name)
        if not target:
            suggestions = manager.get_suggestions(name)
            if suggestions:
                context.console.print_error(f"Workspace '{name}' not found.")
                context.console.print(f"Did you mean: {', '.join(suggestions)}?")
            else:
                context.console.print_error(f"Workspace '{name}' not found.")
                context.console.print("Use '/workspace list' to see available workspaces")
            return

        # Check if already active
        if target.name == (current.name if current else ""):
            context.console.print(f"Workspace '{name}' is already active.")
            return

        context.console.print("\n[arrows] [bold]Switching workspace[/bold]\n")

        if current:
            context.console.print(f"  From: {current.name}")
        context.console.print(f"  To:   {target.name}")

        # Switch workspace
        new_ws = manager.switch_workspace(name)

        context.console.print("\n  [checkmark] Workspace switched")
        context.console.print(f"\n[checkmark] Now using: [bold cyan]{new_ws.name}[/bold cyan]\n")

        # Reinit orchestrator if needed (REPL handles this)
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "_reinit_orchestrator"):
            repl._reinit_orchestrator(new_ws.path)


def register_workspace_commands(registry: "CommandRegistry") -> None:
    """Register all workspace commands with a registry."""
    registry.register(BootstrapCommand())
    registry.register(SpecializeCommand())
    registry.register(WorkspaceCommand())
