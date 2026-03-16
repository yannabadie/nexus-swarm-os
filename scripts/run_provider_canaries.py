#!/usr/bin/env python3
"""
Run live provider canaries and export a JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from core.drivers.provider_canaries import ProviderCanaryRunner


async def _run(output_path: Path) -> None:
    runner = ProviderCanaryRunner()
    report = await runner.run()
    await runner.write_report(report, output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live provider canaries and export a JSON report.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/provider-canaries.json"),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    asyncio.run(_run(args.output))
    print(f"Provider canary report written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
