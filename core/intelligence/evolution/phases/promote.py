"""
Promote Phase - V7.5 Phase 0a

Winner promotion and rejected child archiving.
Extracted from repl.py:_promote_child() and _archive_rejected_child()

This implements EVOLUTION_PROTOCOL.md Phase 5:
- Winner becomes new parent
- Old parent archived to ARCHIVE/GEN_XXX/
- Rejected children archived to ARCHIVE/rejected/
"""

import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from core.intelligence.evolution.lineage import (
    archive_generation,
    load_lineage,
    promote_child_to_parent,
    save_lineage,
)
from core.intelligence.evolution.models import ArchiveResult, PromotionResult

# Type alias for progress callback
ProgressCallback = Callable[[str, float], None]


class PromotePhase:
    """
    Phase 5: Winner promotion and archiving.

    Handles:
    - Promoting winning child to become new parent
    - Archiving old parent to ARCHIVE/GEN_XXX/
    - Archiving rejected children to ARCHIVE/rejected/
    - Git commits for traceability
    """

    def __init__(
        self,
        workspace_path: Path,
        nexus_root: Path,
        progress_callback: ProgressCallback | None = None,
    ):
        """
        Initialize promote phase.

        Args:
            workspace_path: Path to workspace directory
            nexus_root: Path to NEXUS installation root
            progress_callback: Optional callback for progress updates
        """
        self.workspace_path = workspace_path
        self.nexus_root = nexus_root
        self.project_root = nexus_root.parent
        self.progress_callback = progress_callback

    def _report_progress(self, message: str, progress: float = 0.0):
        """Report progress to callback if available"""
        if self.progress_callback:
            self.progress_callback(message, progress)

    def promote_child(
        self,
        child_id: str,
        fitness_score: float,
        generation: int,
        child_metadata: dict[str, Any] | None = None,
    ) -> PromotionResult:
        """
        Promote approved child to become the new active parent.

        Steps:
        1. Archive current parent to ARCHIVE/GEN_XXX/
        2. Move child from GENERATION_ACTIVE/ to NEXUS root
        3. Update LINEAGE.json via promote_child_to_parent()
        4. Git commit the promotion

        Args:
            child_id: ID of child to promote
            fitness_score: Final fitness score
            generation: Current generation number
            child_metadata: Optional additional metadata

        Returns:
            PromotionResult with promotion details
        """
        self._report_progress(f"Promoting {child_id}...", 0.0)
        errors = []
        child_metadata = child_metadata or {}

        # Paths
        parent_path = self.nexus_root
        child_path = self.project_root / "GENERATION_ACTIVE" / child_id
        archive_dir = self.project_root / "ARCHIVE" / f"GEN_{generation - 1:03d}"

        # Validate child exists
        if not child_path.exists():
            return PromotionResult(
                success=False,
                child_id=child_id,
                errors=[f"Child not found: {child_path}"],
            )

        try:
            # 1. Load lineage
            self._report_progress("Loading lineage...", 0.1)
            lineage = load_lineage(self.workspace_path)
            old_parent = lineage.get("current_parent", {})
            old_parent_id = old_parent.get("id", "unknown")

            # 2. Archive old parent
            self._report_progress(f"Archiving {old_parent_id}...", 0.2)
            archive_dir.mkdir(parents=True, exist_ok=True)

            archive_parent_path = archive_dir / old_parent_id
            if not archive_parent_path.exists():
                shutil.copytree(
                    parent_path, archive_parent_path, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "workspace")
                )

            # Update lineage with archive info
            lineage = archive_generation(
                lineage, old_parent_id, archive_parent_path, reason=f"Superseded by {child_id}"
            )

            # 3. Promote child - copy child files over parent
            self._report_progress(f"Promoting {child_id}...", 0.4)

            # Remove old parent files (except workspace and .git)
            for item in parent_path.iterdir():
                if item.name in ["workspace", ".git", "__pycache__"]:
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            # Copy child files to parent location
            for item in child_path.iterdir():
                if item.name in ["__pycache__", "workspace"]:
                    continue
                dest = parent_path / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            # 4. Update LINEAGE.json
            self._report_progress("Updating lineage...", 0.6)
            birth_cert_path = child_metadata.get(
                "birth_cert_path", f"GENERATION_ACTIVE/{child_id}/BIRTH_CERTIFICATE.json"
            )
            notable_features = [child_metadata.get("improvements_summary", "Emergent mutation")]

            lineage = promote_child_to_parent(
                lineage=lineage,
                child_id=child_id,
                child_path=parent_path,
                fitness_score=fitness_score,
                birth_cert_path=birth_cert_path,
                notable_features=notable_features,
            )

            save_lineage(lineage, self.workspace_path)

            # 5. Clean up GENERATION_ACTIVE
            self._report_progress("Cleaning up...", 0.8)
            shutil.rmtree(child_path)

            # 6. Git commit
            self._report_progress("Git commit...", 0.9)
            try:
                subprocess.run(["git", "add", "-A"], cwd=self.project_root, check=True, capture_output=True)
                commit_msg = (
                    f"evolution(promote): {child_id} -> active parent (Gen {generation})\n\n"
                    f"Fitness Score: {fitness_score:.3f}\n"
                    f"Archived: {old_parent_id}\n\n"
                    f"Generated with NEXUS Evolution Engine"
                )
                subprocess.run(
                    ["git", "commit", "-m", commit_msg], cwd=self.project_root, check=True, capture_output=True
                )
            except subprocess.CalledProcessError:
                errors.append("Git commit failed (manual commit recommended)")

            self._report_progress("Promotion complete", 1.0)

            return PromotionResult(
                success=True,
                child_id=child_id,
                new_generation=generation,
                backup_path=str(archive_parent_path),
                errors=errors,
            )

        except Exception as e:
            return PromotionResult(
                success=False,
                child_id=child_id,
                errors=[f"Promotion failed: {str(e)}"] + errors,
            )

    def archive_rejected_child(
        self,
        child_id: str,
        generation: int,
        reason: str = "manual_review_rejection",
        fitness_score: float = 0.0,
    ) -> ArchiveResult:
        """
        Archive a rejected child to prevent accumulation in GENERATION_ACTIVE.

        Steps:
        1. Create archive directory for rejected children
        2. Move child from GENERATION_ACTIVE/ to ARCHIVE/rejected/GEN_XXX/
        3. Update lineage with rejection reason

        Args:
            child_id: ID of child to archive
            generation: Generation number
            reason: Reason for rejection
            fitness_score: Final fitness score

        Returns:
            ArchiveResult with archive details
        """
        self._report_progress(f"Archiving rejected {child_id}...", 0.0)

        # Paths
        child_path = self.project_root / "GENERATION_ACTIVE" / child_id
        archive_dir = self.project_root / "ARCHIVE" / "rejected" / f"GEN_{generation:03d}"

        # Validate child exists
        if not child_path.exists():
            return ArchiveResult(
                success=False,
                child_id=child_id,
                reason=f"Child not found: {child_path}",
            )

        try:
            # 1. Create archive directory
            self._report_progress("Creating archive directory...", 0.2)
            archive_dir.mkdir(parents=True, exist_ok=True)

            # 2. Move child to archive
            self._report_progress("Moving to archive...", 0.4)
            archive_child_path = archive_dir / child_id
            if archive_child_path.exists():
                # If already exists, add timestamp to avoid collision
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_child_path = archive_dir / f"{child_id}_rejected_{timestamp}"

            shutil.move(str(child_path), str(archive_child_path))

            # 3. Update lineage with rejection
            self._report_progress("Updating lineage...", 0.7)
            try:
                lineage = load_lineage(self.workspace_path)
                if "rejected_children" not in lineage:
                    lineage["rejected_children"] = []

                lineage["rejected_children"].append(
                    {
                        "id": child_id,
                        "generation": generation,
                        "rejected_at": datetime.now().isoformat(),
                        "reason": reason,
                        "archive_path": str(archive_child_path),
                        "fitness_score": fitness_score,
                    }
                )

                save_lineage(lineage, self.workspace_path)
            except Exception:
                # Non-fatal, continue even if lineage update fails
                pass

            self._report_progress("Archive complete", 1.0)

            return ArchiveResult(
                success=True,
                child_id=child_id,
                archive_path=str(archive_child_path),
                reason=reason,
            )

        except Exception as e:
            return ArchiveResult(
                success=False,
                child_id=child_id,
                reason=f"Archive failed: {str(e)}",
            )


def promote_child(
    workspace_path: Path,
    nexus_root: Path,
    child_id: str,
    fitness_score: float,
    generation: int,
    child_metadata: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PromotionResult:
    """
    Convenience function to promote a child.

    Args:
        workspace_path: Path to workspace directory
        nexus_root: Path to NEXUS installation root
        child_id: ID of child to promote
        fitness_score: Final fitness score
        generation: Current generation number
        child_metadata: Optional additional metadata
        progress_callback: Optional callback for progress updates

    Returns:
        PromotionResult with promotion details
    """
    phase = PromotePhase(workspace_path, nexus_root, progress_callback)
    return phase.promote_child(child_id, fitness_score, generation, child_metadata)


def archive_child(
    workspace_path: Path,
    nexus_root: Path,
    child_id: str,
    generation: int,
    reason: str = "rejected",
    fitness_score: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> ArchiveResult:
    """
    Convenience function to archive a rejected child.

    Args:
        workspace_path: Path to workspace directory
        nexus_root: Path to NEXUS installation root
        child_id: ID of child to archive
        generation: Generation number
        reason: Reason for rejection
        fitness_score: Final fitness score
        progress_callback: Optional callback for progress updates

    Returns:
        ArchiveResult with archive details
    """
    phase = PromotePhase(workspace_path, nexus_root, progress_callback)
    return phase.archive_rejected_child(child_id, generation, reason, fitness_score)
