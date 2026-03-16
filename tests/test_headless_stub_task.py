import json
import subprocess
import sys
from pathlib import Path


def test_headless_stub_task_script(tmp_path: Path) -> None:
    output_path = tmp_path / "headless-task-success.json"
    script_path = Path(__file__).parent.parent / "scripts" / "run_headless_stub_task.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--task",
            "Validate orchestrated stub task",
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["task"] == "Validate orchestrated stub task"
    assert payload["output"] == "Stub task execution successful"
    assert payload["driver"] == "anthropic_sdk"
