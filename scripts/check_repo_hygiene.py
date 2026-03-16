#!/usr/bin/env python3
"""
Fail CI on committed local-state artifacts and obvious public metadata hygiene regressions.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_AGENT_CARD_URL = "https://github.com/yannabadie/NEXUS/tree/NX-CG"
FORBIDDEN_TRACKED_FILES = {"workspace_registry.json"}
PATH_SCANNED_METADATA = {
    ".env.example",
    "agent_card.json",
    "core/provider_registry.json",
    ".github/pull_request_template.md",
}
TRUTH_SURFACE_FILES = (
    "README.md",
    "START_HERE.md",
    "core/README.md",
    "docs/ARCHITECTURE_MAP_GENERATED.md",
)
STALE_PATH_MARKERS = (
    "core/swarm/",
    "core/hive_mind/",
    "core/execution/",
    "core/security/",
    "core/memory/",
    "core/routing/",
    "core/evolution/",
    "core/orchestration/",
    "core/bootstrap/",
    "core/interface/",
    "nexus6.py",
)
UNSUPPORTED_MARKETING_PATTERNS = (
    re.compile(r"\b\d{2,3}%\s+cheaper\b", re.IGNORECASE),
    re.compile(r"\b\d{2,3}%\s+savings\b", re.IGNORECASE),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:\\"),
    re.compile(r"(^|[^:])//Users/"),
    re.compile(r"(^|[^:])//home/"),
    re.compile(r"(^|[^:])/Users/"),
    re.compile(r"(^|[^:])/home/"),
)
MOJIBAKE_MARKERS = ("â”", "â–", "âœ", "\ufffd")
PUBLIC_TEXT_FILES = ("README.md", "CLAUDE.md", "ROADMAP.md", "GEMINI.md")


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _should_scan_for_paths(path: str) -> bool:
    if path in PATH_SCANNED_METADATA:
        return True
    return path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))


def main() -> int:
    errors: list[str] = []
    tracked_files = _tracked_files()

    for forbidden in FORBIDDEN_TRACKED_FILES:
        if forbidden in tracked_files:
            errors.append(f"Tracked local-state artifact must not be committed: {forbidden}")

    for rel_path in tracked_files:
        if not _should_scan_for_paths(rel_path):
            continue
        file_path = REPO_ROOT / rel_path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in ABSOLUTE_PATH_PATTERNS:
            if pattern.search(content):
                errors.append(f"Absolute local path leaked into tracked metadata file: {rel_path}")
                break

    for rel_path in PUBLIC_TEXT_FILES:
        file_path = REPO_ROOT / rel_path
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            if marker in content:
                errors.append(f"Mojibake marker {marker!r} found in public text surface: {rel_path}")
                break

    for rel_path in TRUTH_SURFACE_FILES:
        file_path = REPO_ROOT / rel_path
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8")
        for marker in STALE_PATH_MARKERS:
            if marker in content:
                errors.append(f"Stale pre-consolidation path leaked into truth surface {rel_path}: {marker}")

    env_example_path = REPO_ROOT / ".env.example"
    if env_example_path.exists():
        env_text = env_example_path.read_text(encoding="utf-8")
        for pattern in UNSUPPORTED_MARKETING_PATTERNS:
            if pattern.search(env_text):
                errors.append(".env.example contains unsupported cost-marketing claims")
                break

    agent_card_path = REPO_ROOT / "agent_card.json"
    if agent_card_path.exists():
        agent_card = json.loads(agent_card_path.read_text(encoding="utf-8"))
        provider_url = agent_card.get("provider", {}).get("url")
        if provider_url != EXPECTED_AGENT_CARD_URL:
            errors.append(f"agent_card.json provider.url mismatch: {provider_url!r}")

    provider_registry_path = REPO_ROOT / "core" / "provider_registry.json"
    if provider_registry_path.exists():
        provider_registry = json.loads(provider_registry_path.read_text(encoding="utf-8"))
        sync_errors = provider_registry.get("sync_errors", [])
        if sync_errors:
            errors.append(
                "core/provider_registry.json still contains sync_errors: "
                + "; ".join(str(item) for item in sync_errors)
            )

    if errors:
        print("\n".join(errors))
        return 1

    print("Repository hygiene checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
