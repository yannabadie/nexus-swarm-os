#!/usr/bin/env python3
"""
Run the shared headless task path with a stub runtime that returns success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import nexus7


class _FakeRuntime:
    def execute_headless(self, task: str | None, timestamp: str):
        return SimpleNamespace(
            to_dict=lambda: {
                "nexus_version": "12.4.0",
                "codename": "COGNITIVE BOOST",
                "mode": "headless",
                "timestamp": timestamp,
                "task": task,
                "status": "success",
                "driver": "anthropic_sdk",
                "output": "Stub task execution successful",
                "error": None,
                "error_code": None,
                "warnings": [],
                "artifacts": [{"kind": "stub", "path": "workspace/stub-artifact.txt"}],
                "state": "IDLE",
                "iterations": 0,
            }
        )


async def _run(task: str, output_path: Path) -> int:
    import core.runtime as runtime_module

    original_runtime = runtime_module.NexusSessionRuntime

    class _FakeRuntimeFacade:
        @classmethod
        def from_config(
            cls,
            config,  # noqa: ANN001
            workspace_path=None,  # noqa: ANN001
            interaction_mode="cli",  # noqa: ANN001
            strict_interaction=False,  # noqa: ANN001
        ):
            del cls, config, workspace_path, interaction_mode, strict_interaction
            return _FakeRuntime()

    runtime_module.NexusSessionRuntime = _FakeRuntimeFacade
    try:
        config = SimpleNamespace(
            workspace_path=output_path.parent,
            driver_mode="sdk",
            google_api_key="stub-google-key",
            anthropic_api_key="stub-anthropic-key",
            provider_snapshot={"warnings": []},
            nexus_version="12.4.0",
            nexus_codename="COGNITIVE BOOST",
        )
        return await nexus7.headless_main(
            workspace_path=output_path.parent,
            task=task,
            output_path=str(output_path),
            config=config,
        )
    finally:
        runtime_module.NexusSessionRuntime = original_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the shared headless task path with a stub runtime.")
    parser.add_argument("--task", required=True, help="Task label to inject into the stub runtime output.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/headless-task-success.json"),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    exit_code = asyncio.run(_run(args.task, args.output))
    payload = json.loads(args.output.read_text(encoding="utf-8"))
    print(f"Headless stub task written to: {args.output}")
    print(f"Status: {payload['status']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
