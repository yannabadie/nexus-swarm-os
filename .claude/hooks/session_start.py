#!/usr/bin/env python3
"""NEXUS Claude Code Session Start Hook.

Cross-platform hook called at the beginning of each Claude Code session.
Displays environment info and available commands.
"""

import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], default: str = "unknown") -> str:
    """Run a command and return output, or default on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else default
    except Exception:
        return default


def main():
    print("=" * 50)
    print("  NEXUS V12.4 Development Environment")
    print("=" * 50)
    print()

    # Git info
    branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], "not a git repo")
    print(f"Branch: {branch}")

    # Check for uncommitted changes
    status = run_cmd(["git", "status", "--porcelain"])
    if status:
        print("Working tree: uncommitted changes detected")
    else:
        print("Working tree: clean")

    # Python version
    print(f"Python: {sys.version.split()[0]}")

    # Test count
    tests_dir = Path("tests")
    if tests_dir.exists():
        test_files = list(tests_dir.rglob("test_*.py"))
        print(f"Test files: {len(test_files)}")
    else:
        print("Test files: tests/ not found")

    # Check pytest
    try:
        import pytest
        print("Pytest: available")
    except ImportError:
        print("Pytest: NOT FOUND - run 'pip install pytest'")

    print()
    print("=" * 50)
    print("  Available Commands")
    print("=" * 50)
    print("/dev     - Development automation (feature implementation)")
    print("/debug   - Debug test failures iteratively")
    print("/docs    - Documentation generation/audit")
    print("/test    - Run test suite with analysis")
    print("/review  - Code review for quality/security")
    print()
    print("Ready for autonomous development!")


if __name__ == "__main__":
    main()
