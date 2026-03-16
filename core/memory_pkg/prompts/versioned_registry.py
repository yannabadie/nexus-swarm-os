"""
Versioned Prompt Registry - Version tracking and management for prompt templates.

V12.4 COGNITIVE BOOST - Task #35

Extends the prompt loader with version tracking, history, diff, and rollback.
Each prompt template gets version metadata (version, author, timestamp, changelog).

Usage:
    from core.memory_pkg.prompts.versioned_registry import PromptRegistry

    registry = PromptRegistry(storage_path=Path("workspace/prompts"))

    # Register a versioned prompt
    registry.register("system_gemini", content="...", author="claude",
                       changelog="Initial version")

    # Update with new version
    registry.update("system_gemini", content="...(v2)", author="claude",
                     changelog="Added tool instructions")

    # Get current version
    prompt = registry.get("system_gemini")

    # Diff between versions
    diff = registry.diff("system_gemini", version_a=1, version_b=2)

    # Rollback
    registry.rollback("system_gemini", target_version=1)
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class PromptVersion:
    """A single version of a prompt template."""

    version: int
    content: str
    content_hash: str
    author: str = ""
    changelog: str = ""
    created_at: str = ""
    variables: list[str] = field(default_factory=list)
    line_count: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.line_count:
            self.line_count = len(self.content.splitlines())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "content_hash": self.content_hash,
            "author": self.author,
            "changelog": self.changelog,
            "created_at": self.created_at,
            "variables": self.variables,
            "line_count": self.line_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], content: str = "") -> PromptVersion:
        return cls(
            version=data["version"],
            content=content,
            content_hash=data.get("content_hash", ""),
            author=data.get("author", ""),
            changelog=data.get("changelog", ""),
            created_at=data.get("created_at", ""),
            variables=data.get("variables", []),
            line_count=data.get("line_count", 0),
        )


@dataclass
class PromptEntry:
    """A prompt template with its full version history."""

    name: str
    current_version: int = 0
    versions: list[PromptVersion] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    description: str = ""

    @property
    def latest(self) -> PromptVersion | None:
        if not self.versions:
            return None
        return self.versions[-1]

    @property
    def version_count(self) -> int:
        return len(self.versions)

    def get_version(self, version: int) -> PromptVersion | None:
        for v in self.versions:
            if v.version == version:
                return v
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current_version": self.current_version,
            "version_count": self.version_count,
            "tags": self.tags,
            "description": self.description,
            "versions": [v.to_dict() for v in self.versions],
        }


# =============================================================================
# Prompt Registry
# =============================================================================


class PromptRegistry:
    """
    Versioned prompt template registry.

    Tracks prompt versions with metadata, supports diffs between versions,
    and enables rollback to previous versions. Persists to disk.
    """

    def __init__(self, storage_path: Path | None = None):
        """
        Initialize the prompt registry.

        Args:
            storage_path: Directory for storing versioned prompts (None = in-memory)
        """
        self._storage_path = Path(storage_path) if storage_path else None
        self._entries: dict[str, PromptEntry] = {}

        if self._storage_path:
            self._load()

    def register(
        self,
        name: str,
        content: str,
        *,
        author: str = "",
        changelog: str = "",
        tags: list[str] | None = None,
        description: str = "",
    ) -> PromptVersion:
        """
        Register a new prompt or create the first version.

        Args:
            name: Prompt template name (unique identifier)
            content: Prompt content
            author: Author of this version
            changelog: Description of changes
            tags: Optional tags for categorization
            description: Optional description of the prompt

        Returns:
            The created PromptVersion

        Raises:
            ValueError: If prompt already exists (use update() instead)
        """
        if name in self._entries:
            raise ValueError(f"Prompt '{name}' already exists. Use update() to add a new version.")

        content_hash = self._hash_content(content)
        variables = self._extract_variables(content)

        version = PromptVersion(
            version=1,
            content=content,
            content_hash=content_hash,
            author=author,
            changelog=changelog or "Initial version",
            variables=variables,
        )

        entry = PromptEntry(
            name=name,
            current_version=1,
            versions=[version],
            tags=tags or [],
            description=description,
        )

        self._entries[name] = entry
        self._save()

        _logger.info(f"Registered prompt '{name}' v1")
        return version

    def update(
        self,
        name: str,
        content: str,
        *,
        author: str = "",
        changelog: str = "",
    ) -> PromptVersion:
        """
        Add a new version of an existing prompt.

        Args:
            name: Prompt name
            content: New content
            author: Author of this version
            changelog: Description of changes

        Returns:
            The created PromptVersion

        Raises:
            KeyError: If prompt doesn't exist
            ValueError: If content is identical to current version
        """
        if name not in self._entries:
            raise KeyError(f"Prompt '{name}' not found. Use register() first.")

        entry = self._entries[name]
        content_hash = self._hash_content(content)

        # Check for duplicate content
        if entry.latest and entry.latest.content_hash == content_hash:
            raise ValueError("Content is identical to the current version")

        new_version_num = entry.current_version + 1
        variables = self._extract_variables(content)

        version = PromptVersion(
            version=new_version_num,
            content=content,
            content_hash=content_hash,
            author=author,
            changelog=changelog,
            variables=variables,
        )

        entry.versions.append(version)
        entry.current_version = new_version_num
        self._save()

        _logger.info(f"Updated prompt '{name}' to v{new_version_num}")
        return version

    def get(self, name: str, version: int | None = None) -> str | None:
        """
        Get prompt content.

        Args:
            name: Prompt name
            version: Specific version (None = latest)

        Returns:
            Prompt content string or None if not found
        """
        entry = self._entries.get(name)
        if not entry:
            return None

        if version is not None:
            v = entry.get_version(version)
            return v.content if v else None

        return entry.latest.content if entry.latest else None

    def get_version_info(self, name: str, version: int | None = None) -> PromptVersion | None:
        """
        Get full version metadata.

        Args:
            name: Prompt name
            version: Specific version (None = latest)

        Returns:
            PromptVersion or None
        """
        entry = self._entries.get(name)
        if not entry:
            return None

        if version is not None:
            return entry.get_version(version)

        return entry.latest

    def get_entry(self, name: str) -> PromptEntry | None:
        """Get the full prompt entry with all versions."""
        return self._entries.get(name)

    def diff(
        self,
        name: str,
        version_a: int,
        version_b: int,
    ) -> str | None:
        """
        Generate a unified diff between two versions.

        Args:
            name: Prompt name
            version_a: First version number
            version_b: Second version number

        Returns:
            Unified diff string, or None if versions not found
        """
        entry = self._entries.get(name)
        if not entry:
            return None

        va = entry.get_version(version_a)
        vb = entry.get_version(version_b)
        if not va or not vb:
            return None

        diff_lines = difflib.unified_diff(
            va.content.splitlines(keepends=True),
            vb.content.splitlines(keepends=True),
            fromfile=f"{name} v{version_a}",
            tofile=f"{name} v{version_b}",
        )

        return "".join(diff_lines)

    def rollback(self, name: str, target_version: int) -> PromptVersion:
        """
        Rollback to a previous version (creates a new version with old content).

        Args:
            name: Prompt name
            target_version: Version to rollback to

        Returns:
            The new version (which is a copy of the target)

        Raises:
            KeyError: If prompt not found
            ValueError: If target version not found
        """
        entry = self._entries.get(name)
        if not entry:
            raise KeyError(f"Prompt '{name}' not found")

        target = entry.get_version(target_version)
        if not target:
            raise ValueError(f"Version {target_version} not found for prompt '{name}'")

        return self.update(
            name,
            content=target.content,
            author="system",
            changelog=f"Rollback to v{target_version}",
        )

    def list_prompts(self) -> list[dict[str, Any]]:
        """
        List all registered prompts with summary info.

        Returns:
            List of dicts with name, current_version, tags, description
        """
        return [
            {
                "name": entry.name,
                "current_version": entry.current_version,
                "version_count": entry.version_count,
                "tags": entry.tags,
                "description": entry.description,
            }
            for entry in self._entries.values()
        ]

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        """
        List all versions of a prompt.

        Args:
            name: Prompt name

        Returns:
            List of version metadata dicts
        """
        entry = self._entries.get(name)
        if not entry:
            return []

        return [v.to_dict() for v in entry.versions]

    def remove(self, name: str) -> bool:
        """
        Remove a prompt entirely.

        Args:
            name: Prompt name

        Returns:
            True if removed
        """
        if name in self._entries:
            del self._entries[name]
            self._save()
            return True
        return False

    def search(self, query: str) -> list[str]:
        """
        Search prompts by name, tags, or description.

        Args:
            query: Search string (case-insensitive)

        Returns:
            List of matching prompt names
        """
        query_lower = query.lower()
        results = []
        for name, entry in self._entries.items():
            if (
                query_lower in name.lower()
                or query_lower in entry.description.lower()
                or any(query_lower in t.lower() for t in entry.tags)
            ):
                results.append(name)
        return results

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _hash_content(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _extract_variables(self, content: str) -> list[str]:
        """Extract {variable} placeholders from content."""
        import re

        return sorted(set(re.findall(r"\{(\w+)\}", content)))

    def _save(self) -> None:
        if not self._storage_path:
            return

        self._storage_path.mkdir(parents=True, exist_ok=True)
        registry_file = self._storage_path / "registry.json"

        # Save metadata (without full content)
        metadata = {
            "version": "1.0",
            "updated_at": datetime.now(UTC).isoformat(),
            "prompts": {name: entry.to_dict() for name, entry in self._entries.items()},
        }
        registry_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        # Save content files
        content_dir = self._storage_path / "content"
        content_dir.mkdir(exist_ok=True)
        for name, entry in self._entries.items():
            for v in entry.versions:
                content_file = content_dir / f"{name}_v{v.version}.txt"
                content_file.write_text(v.content, encoding="utf-8")

    def _load(self) -> None:
        if not self._storage_path:
            return

        registry_file = self._storage_path / "registry.json"
        if not registry_file.exists():
            return

        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
            content_dir = self._storage_path / "content"

            for name, entry_data in data.get("prompts", {}).items():
                versions = []
                for v_data in entry_data.get("versions", []):
                    content = ""
                    content_file = content_dir / f"{name}_v{v_data['version']}.txt"
                    if content_file.exists():
                        content = content_file.read_text(encoding="utf-8")
                    versions.append(PromptVersion.from_dict(v_data, content=content))

                self._entries[name] = PromptEntry(
                    name=name,
                    current_version=entry_data.get("current_version", 0),
                    versions=versions,
                    tags=entry_data.get("tags", []),
                    description=entry_data.get("description", ""),
                )

            _logger.debug(f"Loaded {len(self._entries)} prompts from registry")
        except (json.JSONDecodeError, KeyError) as e:
            _logger.warning(f"Failed to load prompt registry: {e}")

    def to_dict(self) -> dict[str, Any]:
        """Export registry state."""
        return {
            "prompt_count": len(self._entries),
            "total_versions": sum(e.version_count for e in self._entries.values()),
            "prompts": {name: entry.to_dict() for name, entry in self._entries.items()},
        }
