#!/usr/bin/env python3
"""
Run a one-shot Shadow Red Team pass and write a JSON snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from core.security_pkg.security.shadow_tester import ShadowRedTeam


async def _run_snapshot(output_path: Path) -> None:
    shadow_team = ShadowRedTeam(
        test_interval=1,
        alert_on_bypass=False,
        log_results=False,
        metrics_file=output_path.with_suffix(".jsonl"),
    )
    results = await shadow_team._run_attack_suite()
    shadow_team._update_metrics(results)

    attacks = [result for result in results if result.attack_type != "benign"]
    benign = [result for result in results if result.attack_type == "benign"]
    bypassed = [result for result in attacks if not result.blocked]
    false_positives = [result for result in benign if result.blocked]

    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_results": len(results),
        "total_attacks": len(attacks),
        "total_benign": len(benign),
        "blocked_attacks": shadow_team.metrics.blocked_attacks,
        "bypassed_attacks": shadow_team.metrics.bypassed_attacks,
        "false_positives": shadow_team.metrics.false_positives,
        "attack_success_rate": shadow_team.metrics.attack_success_rate,
        "false_positive_rate": shadow_team.metrics.false_positive_rate,
        "attack_categories": sorted({result.attack_type for result in attacks}),
        "bypassed_examples": [
            {
                "attack_type": result.attack_type,
                "payload": result.attack_payload,
                "risk_score": result.risk_score,
                "reason": result.reason,
            }
            for result in bypassed[:5]
        ],
        "false_positive_examples": [
            {
                "payload": result.attack_payload,
                "risk_score": result.risk_score,
                "reason": result.reason,
            }
            for result in false_positives[:5]
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Shadow Red Team snapshot and write a JSON report.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/shadow-redteam-summary.json"),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    asyncio.run(_run_snapshot(args.output))
    print(f"Shadow Red Team snapshot written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
