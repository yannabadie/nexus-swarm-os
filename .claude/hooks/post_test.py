#!/usr/bin/env python3
"""NEXUS Claude Code Post-Test Hook.

Cross-platform hook called after pytest runs to summarize results.
"""

import json
from pathlib import Path


def main():
    print()
    print("-" * 40)

    # Check for failed tests
    lastfailed = Path(".pytest_cache/v/cache/lastfailed")
    if lastfailed.exists():
        try:
            with open(lastfailed) as f:
                failed = json.load(f)
            if failed:
                print(f"Test Failures Detected: {len(failed)}")
                print("Use /debug to analyze and fix failures")
        except Exception:
            pass

    # Coverage summary if available
    coverage_file = Path(".coverage")
    if coverage_file.exists():
        print("Coverage data available - run with --cov for report")

    print("-" * 40)


if __name__ == "__main__":
    main()
