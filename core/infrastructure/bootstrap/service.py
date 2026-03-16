"""
NEXUS V9.1 - BootstrapService & SpinoffService

Service Layer for Bootstrap and Specialization operations.
Wraps AutoBootstrap and orchestrator brainstorming with UI output.

This service handles:
- Project analysis and NEXUS.md generation (BootstrapService)
- Specialized agent creation via collaborative brainstorming (SpinoffService)

Usage:
    from core.infrastructure.bootstrap.service import BootstrapService, SpinoffService

    bootstrap_service = BootstrapService(console)
    bootstrap_service.bootstrap(project_path)

    spinoff_service = SpinoffService(orchestrator, console, workspace_path, nexus_root)
    spinoff_service.specialize(mission)
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.interface_pkg.interface.console_v7 import ConsoleV7
    from core.orchestration_v7 import OrchestratorV7
    from core.security_pkg.interaction import InteractionProvider

# V9.1: Import ServiceResult from telemetry (single source of truth)
from core.observability.telemetry.service import ServiceResult


class BootstrapService:
    """
    Service for Bootstrap operations.

    Wraps AutoBootstrap with console UI output.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.

    V9.8 DETOX: Supports headless mode via InteractionProvider.
    """

    def __init__(self, console: ConsoleV7, interaction: InteractionProvider | None = None):
        """
        Initialize BootstrapService.

        Args:
            console: Console for output
            interaction: Optional interaction provider for headless mode.
                        If None, uses get_interaction_provider().
        """
        self.console = console
        self._interaction = interaction

    # ==================== PUBLIC API ====================

    def bootstrap(self, project_path: Path | None = None) -> ServiceResult:
        """
        Run AutoBootstrap to analyze project and generate NEXUS.md.

        Args:
            project_path: Path to project directory (default: current directory)

        Returns:
            ServiceResult with bootstrap outcome
        """
        from core.infrastructure.bootstrap import AutoBootstrap

        # Default to current directory
        if project_path is None:
            project_path = Path.cwd()
        else:
            project_path = Path(project_path).resolve()

        # Validate path
        if not project_path.exists():
            self.console.print_error(f"Path does not exist: {project_path}")
            return ServiceResult(success=False, error=f"Path does not exist: {project_path}")

        if not project_path.is_dir():
            self.console.print_error(f"Path is not a directory: {project_path}")
            return ServiceResult(success=False, error=f"Path is not a directory: {project_path}")

        self.console.print(f"  Analyzing project: {project_path}")

        try:
            # Run analysis
            bootstrap = AutoBootstrap(project_path)
            analysis = bootstrap.analyze()

            # Display results
            self.console.print("\n  Analysis Results:")
            self.console.print(f"   Project: {analysis.project_name}")
            self.console.print(f"   Languages: {', '.join(analysis.languages) or 'None detected'}")
            self.console.print(f"   Frameworks: {', '.join(analysis.frameworks) or 'None detected'}")
            self.console.print(f"   Databases: {', '.join(analysis.databases) or 'None detected'}")
            self.console.print(f"   Tools: {', '.join(analysis.tools) or 'None detected'}")
            self.console.print(f"   Has tests: {'Yes' if analysis.has_tests else 'No'}")
            self.console.print(f"   Has docs: {'Yes' if analysis.has_docs else 'No'}")
            self.console.print(f"   Has CI: {'Yes' if analysis.has_ci else 'No'}")

            if analysis.commands:
                self.console.print("\n  Commands discovered:")
                for cmd, desc in list(analysis.commands.items())[:5]:
                    self.console.print(f"   {cmd}: {desc}")

            # Generate NEXUS.md
            nexus_md = bootstrap.generate_nexus_md(analysis)

            # Check if NEXUS.md already exists
            nexus_path = project_path / "NEXUS.md"
            if nexus_path.exists():
                existing_size = len(nexus_path.read_text(encoding="utf-8"))
                self.console.print(f"\n  NEXUS.md already exists at {nexus_path}")
                self.console.print(f"   Existing file size: {existing_size} characters")
                self.console.print(f"   New file size: {len(nexus_md)} characters")

                if existing_size > len(nexus_md) * 2:
                    self.console.print("\n   [bold red]WARNING: Existing file is much larger![/bold red]")
                    self.console.print("   The existing NEXUS.md may contain important documentation.")

                # V9.8 DETOX: Use interaction provider instead of raw input()
                try:
                    confirmed = self._confirm_overwrite()
                    if not confirmed:
                        self.console.print("   Cancelled.")
                        return ServiceResult(success=False, message="Cancelled by user")
                except (EOFError, KeyboardInterrupt):
                    self.console.print("   Cancelled.")
                    return ServiceResult(success=False, message="Cancelled by user")

                # Create backup before overwriting
                backup_path = project_path / "NEXUS.md.bak"
                shutil.copy2(nexus_path, backup_path)
                self.console.print(f"   Backup created: {backup_path}")

            # Save
            bootstrap.save(nexus_md)
            self.console.print(f"\n  Generated: {nexus_path}")
            self.console.print(f"   Size: {len(nexus_md)} characters")

            return ServiceResult(
                success=True,
                data={
                    "path": str(nexus_path),
                    "size": len(nexus_md),
                    "project_name": analysis.project_name,
                    "languages": analysis.languages,
                },
            )

        except Exception as e:
            self.console.print_error(f"Bootstrap failed: {e}")
            return ServiceResult(success=False, error=str(e))

    def _confirm_overwrite(self) -> bool:
        """
        Ask user to confirm overwrite of existing NEXUS.md.

        V9.8 DETOX: Uses InteractionProvider for headless compatibility.

        Returns:
            True if user confirms, False otherwise.
        """
        if self._interaction is not None:
            # V11.4 ASYNC: Use run_coroutine_threadsafe when loop is running
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self._interaction.confirm("Create backup and overwrite?", default=False), loop
                )
                return future.result(timeout=30)
            except RuntimeError:
                # No running loop - create one
                return asyncio.run(self._interaction.confirm("Create backup and overwrite?", default=False))
        else:
            # Fallback: Use provider from factory
            from core.security_pkg.interaction import get_interaction_provider

            provider = get_interaction_provider()

            if provider.is_interactive:
                # Direct sync input for CLI (avoid event loop issues)
                response = input("   Create backup and overwrite? (y/N): ").strip().lower()
                return response == "y"
            else:
                # V11.4 ASYNC: Use run_coroutine_threadsafe when loop is running
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        provider.confirm("Create backup and overwrite?", default=False), loop
                    )
                    return future.result(timeout=30)
                except RuntimeError:
                    # No running loop - create one
                    return asyncio.run(provider.confirm("Create backup and overwrite?", default=False))


class SpinoffService:
    """
    Service for Specialization/Spinoff operations.

    Handles collaborative brainstorming with Gemini+Claude to create
    specialized NEXUS spinoffs for specific missions.

    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.
    """

    def __init__(
        self,
        orchestrator: OrchestratorV7,
        console: ConsoleV7,
        workspace_path: Path,
        nexus_root: Path,
    ):
        """
        Initialize SpinoffService.

        Args:
            orchestrator: The orchestrator for AI brainstorming
            console: Console for output
            workspace_path: Path to workspace directory
            nexus_root: Path to NEXUS root directory
        """
        self.orchestrator = orchestrator
        self.console = console
        self.workspace_path = Path(workspace_path)
        self.nexus_root = Path(nexus_root)

    # ==================== PUBLIC API ====================

    def specialize(self, mission: str) -> ServiceResult:
        """
        Create a specialized NEXUS spinoff for a specific mission.

        Args:
            mission: Mission description for the specialist

        Returns:
            ServiceResult with spinoff outcome
        """
        from core.intelligence.evolution.lineage import get_current_parent, load_lineage

        self.console.print("\n" + "=" * 60)
        self.console.print("  SPECIALIZATION CYCLE STARTED")
        self.console.print("=" * 60)

        try:
            lineage = load_lineage(self.workspace_path)
            parent = get_current_parent(lineage)
            parent_id = parent["id"]

            parent_path = self.nexus_root

            # 1. Brainstorm mutations
            mutations = self._brainstorm_spinoff(parent_id, parent_path, mission)

            if not mutations:
                return ServiceResult(success=False, error="Failed to generate specialization mutations")

            # 2. Create Spinoff ID
            mission_slug = "".join(c if c.isalnum() else "_" for c in mission)[:30].upper()
            spinoff_id = f"NEXUS_SPECIALIST_{mission_slug}_{datetime.now().strftime('%Y%m%d')}"

            self.console.print(f"\n{'-' * 60}")
            self.console.print(f"Creating Specialist: {spinoff_id}")
            self.console.print(f"{'-' * 60}")

            # 3. Create Directory
            child_dir = parent_path.parent / "GENERATION_ACTIVE" / spinoff_id
            if child_dir.exists():
                shutil.rmtree(child_dir)
            child_dir.mkdir(parents=True, exist_ok=True)

            # 4. Copy Parent
            shutil.copytree(
                parent_path,
                child_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".nexus", "workspace", ".git"),
                dirs_exist_ok=True,
            )
            self.console.print("  Copied parent base")

            # Copy KERNEL.py from project root (alignment file)
            project_root = parent_path.parent
            kernel_path = project_root / "KERNEL.py"
            kernel_hash_path = project_root / "KERNEL_HASH.txt"
            if kernel_path.exists():
                shutil.copy2(kernel_path, child_dir / "KERNEL.py")
                if kernel_hash_path.exists():
                    shutil.copy2(kernel_hash_path, child_dir / "KERNEL_HASH.txt")
                self.console.print("  Copied KERNEL.py (alignment file)")

            # Create workspace directories required by drivers
            child_workspace = child_dir / "workspace"
            child_workspace.mkdir(exist_ok=True)
            (child_workspace / "_IO_BUFFER").mkdir(exist_ok=True)
            (child_workspace / ".nexus").mkdir(exist_ok=True)
            (child_workspace / "logs").mkdir(exist_ok=True)
            self.console.print("  Created workspace directories")

            # 5. Apply Mutations
            for mutation in mutations:
                target_file = child_dir / mutation["file"]
                if target_file.exists():
                    original = target_file.read_text(encoding="utf-8")
                    updated = original + "\n\n" + mutation["change"]
                    target_file.write_text(updated, encoding="utf-8")
                    self.console.print(f"  Applied mutation to {mutation['file']}")
                else:
                    self.console.print(f"  [yellow]File not found: {mutation['file']}[/yellow]")

            # 6. Spinoff Certificate
            cert = {
                "id": spinoff_id,
                "type": "SPECIALIST",
                "mission": mission,
                "parent": parent_id,
                "created_at": datetime.now().isoformat(),
                "mutations": mutations,
            }
            (child_dir / "SPINOFF_CERTIFICATE.json").write_text(json.dumps(cert, indent=2), encoding="utf-8")

            self.console.print("\n" + "=" * 60)
            self.console.print(f"  SPECIALIST CREATED: {spinoff_id}")
            self.console.print(f"Location: GENERATION_ACTIVE/{spinoff_id}")
            self.console.print("To use: cd into directory and run nexus7.py")
            self.console.print("=" * 60 + "\n")

            return ServiceResult(
                success=True,
                data={
                    "spinoff_id": spinoff_id,
                    "location": str(child_dir),
                    "mission": mission,
                    "mutations_count": len(mutations),
                },
            )

        except Exception as e:
            self.console.print_error(f"Specialization failed: {e}")
            import traceback

            traceback.print_exc()
            return ServiceResult(success=False, error=str(e))

    def _brainstorm_spinoff(self, parent_id: str, parent_path: Path, mission: str) -> list[dict[str, Any]]:
        """
        Collaborative brainstorming for specialization.

        Gemini+Claude design a specific child optimized for a mission.

        Args:
            parent_id: ID of the parent agent
            parent_path: Path to parent directory
            mission: Mission description

        Returns:
            List of mutation dictionaries
        """
        from core.fsm.states import OrchestratorState
        from core.memory_pkg.prompts import load_prompt
        from core.utils.json_extractor import extract_json_safe as robust_extract_json

        self.console.print("\n" + "=" * 60)
        self.console.print(f"  MISSION SPECIALIZATION: {mission}")
        self.console.print("=" * 60)
        self.console.print("Gemini + Claude will now design a Specialist NEXUS\n")

        # Clear history for focused brainstorming
        self.console.print("  Clearing short-term memory for focused brainstorming...")
        self.orchestrator.blackboard["recent_history"] = []
        self.orchestrator.memory.save_to_disk()

        # Load prompt with includes resolved
        try:
            brainstorm_task = load_prompt("specialization_mission", {"mission": mission})
        except FileNotFoundError as e:
            self.console.print_error(f"Missing prompt file: {e}")
            return []

        # Switch to EVOLUTION_BRAINSTORM mode (reused for debate)
        self.orchestrator._transition_to(OrchestratorState.EVOLUTION_BRAINSTORM)
        self.console.print("[FSM] Mode: MISSION_SPECIALIZATION (via EVOLUTION_BRAINSTORM)\n")

        # Start brainstorming
        result = self.orchestrator.process_turn(brainstorm_task)
        self.console.display_result(result)

        # Loop until completion
        max_iterations = 30
        iterations = 0

        while result["state"] not in ["IDLE", "ERROR", "PANIC"] and iterations < max_iterations:
            result = self.orchestrator.process_turn()
            self.console.display_result(result)
            iterations += 1
            if result.get("finished"):
                break

        self.orchestrator._transition_to(OrchestratorState.IDLE)

        # Extract JSON
        final_content = result.get("output") or ""

        # Use robust extractor
        proposals, _ = robust_extract_json(final_content, verbose=True)

        if not proposals:
            raise ValueError("Failed to extract specialization plan")

        return proposals


def _get_bootstrap_service(context) -> BootstrapService:
    """Get or create BootstrapService from command context."""
    service = context.extras.get("bootstrap_service")
    if service:
        return service

    return BootstrapService(console=context.console)


def _get_spinoff_service(context) -> SpinoffService:
    """Get or create SpinoffService from command context."""
    service = context.extras.get("spinoff_service")
    if service:
        return service

    # Get required components from context
    repl = context.extras.get("repl")
    if not repl:
        raise RuntimeError("REPL instance required for SpinoffService")

    return SpinoffService(
        orchestrator=context.orchestrator,
        console=context.console,
        workspace_path=repl.workspace_path,
        nexus_root=repl.nexus_root,
    )
