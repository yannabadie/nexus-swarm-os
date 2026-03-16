"""
E2E tests for NEXUS headless mode.

Validates that:
1. --headless boots without TTY blocking
2. --headless produces valid JSON output
3. Exit codes are deterministic (0 success, 1 failure)
4. --headless --task works with task description
5. --headless --output writes to file
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

NEXUS_ENTRY = str(Path(__file__).parent.parent / "nexus7.py")
NEXUS_CWD = str(Path(NEXUS_ENTRY).parent)
SDK_ENV = {
    "NEXUS_DRIVER_MODE": "sdk",
    "GOOGLE_API_KEY": "test-google-key",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
}
NO_PROVIDER_ENV = {
    "NEXUS_DRIVER_MODE": "cli",
    "GOOGLE_API_KEY": "",
    "GEMINI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "PATH": "",
}


def run_nexus(
    *args: str, timeout: int = 60, stdin=None, env_updates: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run nexus7.py with deterministic environment overrides."""
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if env_updates:
        env.update(env_updates)
    return subprocess.run(
        [sys.executable, NEXUS_ENTRY, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=stdin,
        cwd=NEXUS_CWD,
        env=env,
    )


def build_fake_cli_env(tmp_dir: Path) -> dict[str, str]:
    """Create deterministic fake gemini/claude CLIs for bootstrap tests."""
    cli_dir = tmp_dir / "fake-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        gemini_path = cli_dir / "gemini.cmd"
        claude_path = cli_dir / "claude.cmd"
        gemini_path.write_text(
            "@echo off\n"
            'if "%1"=="--version" (\n'
            "  echo gemini-cli 1.0.0\n"
            "  exit /b 0\n"
            ")\n"
            'if "%1"=="models" (\n'
            "  echo gemini-3.1-pro-preview\n"
            "  exit /b 0\n"
            ")\n"
            "echo gemini-cli\n",
            encoding="utf-8",
        )
        claude_path.write_text(
            "@echo off\necho Claude Code 1.0.0\n",
            encoding="utf-8",
        )
    else:
        gemini_path = cli_dir / "gemini"
        claude_path = cli_dir / "claude"
        gemini_path.write_text(
            "#!/usr/bin/env sh\n"
            'if [ "$1" = "--version" ]; then\n'
            "  echo gemini-cli 1.0.0\n"
            "  exit 0\n"
            "fi\n"
            'if [ "$1" = "models" ]; then\n'
            "  echo gemini-3.1-pro-preview\n"
            "  exit 0\n"
            "fi\n"
            "echo gemini-cli\n",
            encoding="utf-8",
        )
        claude_path.write_text(
            "#!/usr/bin/env sh\necho Claude Code 1.0.0\n",
            encoding="utf-8",
        )
        gemini_path.chmod(0o755)
        claude_path.chmod(0o755)

    return {
        "NEXUS_DRIVER_MODE": "cli",
        "GOOGLE_API_KEY": "",
        "GEMINI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "PATH": f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }


class TestHeadlessBootValidation:
    """Test that headless mode boots cleanly."""

    def test_headless_boot_produces_json(self):
        """Headless boot should succeed in SDK mode without requiring CLIs."""
        result = run_nexus("--headless", env_updates=SDK_ENV)

        # Should exit 0 (boot validation success)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Output should be valid JSON
        output = json.loads(result.stdout)
        assert output["mode"] == "headless"
        assert output["status"] == "success"
        assert output["driver"] == "anthropic_sdk"
        assert output["output"] == "Headless boot validation successful"
        assert "nexus_version" in output
        assert "timestamp" in output

    def test_headless_boot_no_tty_prompts(self):
        """Headless mode must never prompt for input."""
        result = run_nexus("--headless", timeout=30, stdin=subprocess.DEVNULL, env_updates=SDK_ENV)

        assert result.returncode == 0
        # No interactive prompts in output
        assert ">>>" not in result.stdout
        assert "nexus7>" not in result.stdout

    def test_headless_version_in_output(self):
        """JSON output includes correct version."""
        result = run_nexus("--headless", timeout=30, env_updates=SDK_ENV)

        output = json.loads(result.stdout)
        assert output["nexus_version"] == "12.4.0"
        assert output["codename"] == "COGNITIVE BOOST"


class TestHeadlessTaskExecution:
    """Test headless mode with --task flag."""

    def test_headless_with_task(self):
        """A task run must fail cleanly when no valid provider path exists."""
        result = run_nexus(
            "--headless",
            "--task",
            "Validate system health",
            timeout=60,
            stdin=subprocess.DEVNULL,
            env_updates=NO_PROVIDER_ENV,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["task"] == "Validate system health"
        assert output["mode"] == "headless"
        assert output["status"] == "failure"
        assert output["error_code"] == "RUNTIMEERROR"
        assert output["output"] is None
        assert output["output"] != "Headless boot validation successful"
        assert "required for the selected runtime path" in output["error"]

    def test_headless_boot_fails_without_valid_provider(self):
        """Boot validation should not report success when no provider path is usable."""
        result = run_nexus("--headless", timeout=30, env_updates=NO_PROVIDER_ENV)

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["status"] == "failure"
        assert output["error_code"] == "RUNTIMEERROR"

    def test_headless_output_to_file(self):
        """--output should write JSON to file instead of stdout."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            result = run_nexus("--headless", "--output", output_path, timeout=30, env_updates=SDK_ENV)

            assert result.returncode == 0
            assert result.stdout == ""

            # File should contain valid JSON
            with open(output_path) as f:
                output = json.loads(f.read())
            assert output["mode"] == "headless"
            assert output["status"] == "success"
        finally:
            Path(output_path).unlink(missing_ok=True)


class TestHeadlessExitCodes:
    """Test that exit codes are deterministic."""

    def test_version_flag_exits_zero(self):
        """--version should exit 0."""
        result = run_nexus("--version", timeout=10)
        assert result.returncode == 0

    def test_verify_flag_exits_deterministically(self):
        """--verify should pass in CLI mode when valid CLIs are present."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = run_nexus("--verify", timeout=120, env_updates=build_fake_cli_env(Path(tmp_dir)))
        assert result.returncode == 0


class TestHeadlessJSONSchema:
    """Test the JSON output schema is consistent."""

    def test_output_schema_completeness(self):
        """All required fields must be present in JSON output."""
        result = run_nexus("--headless", timeout=30, env_updates=SDK_ENV)

        output = json.loads(result.stdout)

        required_fields = [
            "nexus_version",
            "codename",
            "mode",
            "timestamp",
            "task",
            "status",
            "driver",
            "output",
            "error",
            "error_code",
            "warnings",
            "artifacts",
            "state",
            "iterations",
        ]
        for field in required_fields:
            assert field in output, f"Missing required field: {field}"

    def test_output_timestamp_is_iso8601(self):
        """Timestamp must be valid ISO 8601."""
        from datetime import datetime

        result = run_nexus("--headless", timeout=30, env_updates=SDK_ENV)

        output = json.loads(result.stdout)
        # Should not raise ValueError
        datetime.fromisoformat(output["timestamp"])
