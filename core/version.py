"""
Canonical NEXUS project metadata.

The source of truth is:
1. Installed package metadata (when available)
2. pyproject.toml in the repo root
3. Safe fallbacks
"""

from __future__ import annotations

import tomllib
from contextlib import suppress
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

PACKAGE_NAME = "nexus-swarm-os"
_FALLBACK_VERSION = "12.4.0"
_FALLBACK_CODENAME = "COGNITIVE BOOST"
_FALLBACK_CANONICAL_BRANCH = "NX-CG"


@lru_cache(maxsize=1)
def _load_project_metadata() -> dict[str, str]:
    version = None
    codename = None
    canonical_branch = _FALLBACK_CANONICAL_BRANCH

    with suppress(PackageNotFoundError):
        version = package_version(PACKAGE_NAME)

    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as handle:
            data = tomllib.load(handle)
        project_section = data.get("project", {})
        tool_section = data.get("tool", {}).get("nexus", {})
        version = version or project_section.get("version")
        codename = tool_section.get("codename", codename)
        canonical_branch = tool_section.get("canonical_branch", canonical_branch)

    return {
        "version": version or _FALLBACK_VERSION,
        "codename": codename or _FALLBACK_CODENAME,
        "canonical_branch": canonical_branch or _FALLBACK_CANONICAL_BRANCH,
    }


NEXUS_VERSION = _load_project_metadata()["version"]
NEXUS_CODENAME = _load_project_metadata()["codename"]
NEXUS_CANONICAL_BRANCH = _load_project_metadata()["canonical_branch"]


__all__ = ["NEXUS_CANONICAL_BRANCH", "NEXUS_CODENAME", "NEXUS_VERSION"]
