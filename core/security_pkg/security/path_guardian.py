"""
PathGuardian - Centralizes ALL path validation for NEXUS V7.

Guarantees that no path can escape allowed zones:
- READ: workspace + parent (agents can read parent code)
- WRITE: workspace + GENERATION_ACTIVE (children only)

Security Properties:
- Rejects absolute paths for write (ALWAYS)
- Resolves symlinks before validation
- Protects sacred files (KERNEL.py, MISSION.md, .env)
- Uses .resolve().relative_to() for proper containment check
"""

from pathlib import Path


class PathGuardian:
    """Guardian of paths - validates all file operations."""

    def __init__(self, workspace_path: Path, parent_path: Path, generation_active: Path | None = None):
        """
        Initialize PathGuardian with zone boundaries.

        Args:
            workspace_path: The workspace directory (write allowed)
            parent_path: The parent code directory (read-only)
            generation_active: Evolution children directory (write in evolution mode)
        """
        self.workspace = workspace_path.resolve()
        self.parent = parent_path.resolve()
        self.generation_active = generation_active.resolve() if generation_active else None

        # Zones autorisées en LECTURE
        self.read_zones: list[Path] = [
            self.workspace,
            self.parent,  # Lecture parent autorisée
        ]

        # Zones autorisées en ÉCRITURE (base)
        self.write_zones: list[Path] = [
            self.workspace,
        ]

        # Ajouter GENERATION_ACTIVE si spécifié
        if self.generation_active:
            self.write_zones.append(self.generation_active)

        # Fichiers JAMAIS modifiables (même dans write_zones)
        self.sacred_files = {
            "KERNEL.py",
            "MISSION.md",
            ".env",
            ".env.local",
            "credentials.json",
        }

        # Patterns de fichiers sacrés (regex-like)
        self.sacred_patterns = [
            ".env",  # Tout fichier commençant par .env
        ]

    def validate_read(self, file_path: str) -> tuple[bool, Path, str]:
        """
        Validate a path for read operation.

        Args:
            file_path: Relative or absolute path to validate

        Returns:
            (is_valid, resolved_path, message)
            - is_valid: True if read is allowed
            - resolved_path: The canonicalized path
            - message: "OK" or error description
        """
        try:
            path = Path(file_path)

            # Chemins absolus: résoudre directement
            if path.is_absolute():
                resolved = path.resolve()
            else:
                # Chemins relatifs: résoudre depuis workspace
                resolved = (self.workspace / file_path).resolve()

            # Résoudre symlinks si le fichier existe
            if resolved.exists() and resolved.is_symlink():
                resolved = resolved.readlink().resolve()

            # Vérifier dans zones autorisées
            in_allowed_zone = any(self._is_under(resolved, zone) for zone in self.read_zones)

            if not in_allowed_zone:
                return False, resolved, f"[SECURITY] Read outside allowed zones: {resolved}"

            # V9 SECURITY: Check sacred files for READ operations too
            # These files (like .env) contain credentials that should NEVER be readable by agents
            if self._is_sacred(resolved):
                return False, resolved, f"[SECURITY] Protected file cannot be read: {resolved.name}"

            return True, resolved, "OK"

        except Exception as e:
            return False, Path(file_path), f"[SECURITY] Path validation error: {e}"

    def validate_write(self, file_path: str, is_evolution_mode: bool = False) -> tuple[bool, Path, str]:
        """
        Validate a path for write operation.

        Args:
            file_path: Path to validate (should be relative)
            is_evolution_mode: If True, allows writing to GENERATION_ACTIVE

        Returns:
            (is_valid, resolved_path, message)
            - is_valid: True if write is allowed
            - resolved_path: The canonicalized path
            - message: "OK" or error description
        """
        try:
            path = Path(file_path)

            # 1. BLOQUER chemins absolus (TOUJOURS - règle fondamentale)
            if path.is_absolute():
                return False, path, "[SACRED] Absolute paths NEVER allowed for write operations"

            # 2. Résoudre chemin depuis workspace
            resolved = (self.workspace / file_path).resolve()

            # 3. Vérifier fichiers sacrés
            if self._is_sacred(resolved):
                return False, resolved, f"[SACRED] Protected file: {resolved.name}"

            # 4. Déterminer zones d'écriture autorisées
            allowed_zones = [self.workspace]

            if is_evolution_mode and self.generation_active:
                allowed_zones.append(self.generation_active)

            # 5. Vérifier que le chemin est dans une zone autorisée
            in_allowed_zone = any(self._is_under(resolved, zone) for zone in allowed_zones)

            if not in_allowed_zone:
                return False, resolved, f"[SACRED] Write outside allowed zones: {resolved}"

            # 6. PROTECTION PARENT: S'assurer qu'on n'écrit pas dans le parent
            # (sauf si le parent EST le workspace, ce qui serait une config invalide)
            if self._is_under(resolved, self.parent):
                # Est-ce aussi sous workspace ou generation_active?
                under_workspace = self._is_under(resolved, self.workspace)
                under_generation = self.generation_active and self._is_under(resolved, self.generation_active)

                if not under_workspace and not under_generation:
                    return False, resolved, "[SACRED] WRITE TO PARENT CODE BLOCKED - Parent is READ-ONLY"

            return True, resolved, "OK"

        except Exception as e:
            return False, Path(file_path), f"[SECURITY] Path validation error: {e}"

    def _is_under(self, path: Path, parent: Path) -> bool:
        """
        Check if path is under parent directory.

        Uses relative_to() for proper containment check,
        immune to startswith() bypass attacks.
        """
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _is_sacred(self, path: Path) -> bool:
        """Check if a file is sacred (never modifiable)."""
        # Exact match
        if path.name in self.sacred_files:
            return True

        # Pattern match (e.g., .env.*)
        return any(path.name.startswith(pattern) for pattern in self.sacred_patterns)

    def get_zone_info(self) -> dict:
        """Return information about configured zones (for debugging)."""
        return {
            "workspace": str(self.workspace),
            "parent": str(self.parent),
            "generation_active": str(self.generation_active) if self.generation_active else None,
            "read_zones": [str(z) for z in self.read_zones],
            "write_zones": [str(z) for z in self.write_zones],
            "sacred_files": list(self.sacred_files),
        }
