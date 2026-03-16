"""Session runtime facade used by interactive and non-interactive entry points."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.orchestration_v7 import OrchestratorV7
from core.security_pkg.interaction import HeadlessProvider, reset_interaction_provider, set_interaction_provider


@dataclass
class HeadlessExecutionResult:
    """Strict JSON result for headless execution."""

    nexus_version: str
    codename: str
    mode: str
    timestamp: str
    task: str | None
    status: str
    driver: str | None = None
    output: str | None = None
    error: str | None = None
    error_code: str | None = None
    warnings: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    state: str | None = None
    iterations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NexusSessionRuntime:
    """Shared session runtime facade for all NEXUS surfaces."""

    TERMINAL_STATES = {"IDLE", "ERROR", "PANIC", "FINISHED"}

    def __init__(
        self,
        workspace_path: Path,
        config: Any,
        gemini_info: dict[str, Any],
        claude_info: dict[str, Any],
        interaction_mode: str = "cli",
        strict_interaction: bool = False,
    ):
        self.workspace_path = Path(workspace_path)
        self.config = config
        self.gemini_info = gemini_info
        self.claude_info = claude_info
        self.interaction_mode = interaction_mode
        self.strict_interaction = strict_interaction
        self._configure_interaction()
        self.orchestrator = OrchestratorV7(self.workspace_path, config, gemini_info, claude_info)

    @classmethod
    def from_config(
        cls,
        config: Any,
        workspace_path: Path | None = None,
        interaction_mode: str = "cli",
        strict_interaction: bool = False,
    ) -> NexusSessionRuntime:
        workspace = Path(workspace_path or getattr(config, "workspace_path", "./workspace"))
        gemini_info = {"model": config.gemini_pro_model, "provider": "gemini"}
        claude_info = {"model": config.claude_opus_model, "provider": "claude"}
        return cls(workspace, config, gemini_info, claude_info, interaction_mode, strict_interaction)

    def _configure_interaction(self) -> None:
        if self.interaction_mode == "cli":
            reset_interaction_provider()
            return
        set_interaction_provider(HeadlessProvider(strict=self.strict_interaction, publish_events=False))

    def _resolve_driver_label(self) -> str | None:
        driver_mode = getattr(self.config, "driver_mode", "auto")
        anthropic = bool(getattr(self.config, "anthropic_api_key", None))
        google = bool(getattr(self.config, "google_api_key", None))

        if driver_mode == "sdk":
            if anthropic:
                return "anthropic_sdk"
            if google:
                return "google_genai_sdk"
            return None

        if driver_mode == "cli":
            return "cli_orchestrator"

        if anthropic:
            return "anthropic_sdk"
        if google:
            return "google_genai_sdk"
        return "cli_orchestrator"

    def execute_task(self, task: str, max_iterations: int = 50) -> tuple[dict[str, Any], int]:
        """Run a task through the orchestrator until it reaches a terminal state."""
        self.orchestrator.reset_to_idle(clear_task=True)
        result = self.orchestrator.process_turn(task)
        iterations = 0

        while result.get("state") not in self.TERMINAL_STATES and iterations < max_iterations:
            result = self.orchestrator.process_turn()
            iterations += 1

        if result.get("state") not in self.TERMINAL_STATES:
            return (
                {
                    "state": result.get("state", "ERROR"),
                    "output": result.get("output"),
                    "error": f"Max iterations reached ({max_iterations})",
                    "finished": False,
                },
                iterations,
            )

        return result, iterations

    def execute_headless(self, task: str | None, timestamp: str) -> HeadlessExecutionResult:
        """Execute a headless task with strict result semantics."""
        warnings = list(getattr(self.config, "provider_snapshot", {}).get("warnings", []))

        if task is None:
            return HeadlessExecutionResult(
                nexus_version=self.config.nexus_version,
                codename=self.config.nexus_codename,
                mode="headless",
                timestamp=timestamp,
                task=None,
                status="success",
                driver=self._resolve_driver_label(),
                output="Headless boot validation successful",
                warnings=warnings,
            )

        result, iterations = self.execute_task(task)
        status = "success" if result.get("finished") and not result.get("error") else "failure"
        error_code = None
        if result.get("error"):
            error_code = str(result["error"]).upper().replace(" ", "_")
        elif not result.get("finished"):
            error_code = "HEADLESS_TASK_INCOMPLETE"

        return HeadlessExecutionResult(
            nexus_version=self.config.nexus_version,
            codename=self.config.nexus_codename,
            mode="headless",
            timestamp=timestamp,
            task=task,
            status=status,
            driver=self._resolve_driver_label(),
            output=result.get("output"),
            error=result.get("error"),
            error_code=error_code,
            warnings=warnings,
            state=result.get("state"),
            iterations=iterations,
        )
