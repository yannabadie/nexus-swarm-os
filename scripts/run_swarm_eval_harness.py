#!/usr/bin/env python3
"""
Run the deterministic swarm evaluation harness and export artifacts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from core.intelligence.swarm.eval_harness import SwarmEvalHarness


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic swarm evaluation harness.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/swarm-eval"),
        help="Directory where the harness report directory will be created.",
    )
    args = parser.parse_args()

    harness = SwarmEvalHarness(output_root=args.output_root)
    report = harness.run()
    output_dir = harness.write_report(report)
    print(f"Swarm evaluation report written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
