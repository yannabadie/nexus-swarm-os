"""
NEXUS Telemetry Metrics Collector

Simple file-based telemetry that logs events to JSONL format.
Designed for future integration with Langfuse, OTLP, etc.

Usage:
    telemetry = TelemetryCollector(config)
    telemetry.record_api_call("gemini", "gemini-3-pro", 1500, 0.8, True)
    telemetry.record_swarm_task("ping_pong", 3, 5.2, True)

    # Get session summary
    summary = telemetry.get_session_summary()
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any

from core.observability.telemetry.budget_tracker import (
    BudgetTracker,
)

_logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics tracked"""

    API_CALL = "api_call"
    SWARM_TASK = "swarm_task"
    TOOL_EXECUTION = "tool_execution"
    ERROR = "error"
    SESSION = "session"
    EVOLUTION = "evolution"


@dataclass
class APICallMetric:
    """Metrics for a single API call"""

    timestamp: str
    provider: str  # gemini, claude
    model: str
    tokens_in: int
    tokens_out: int
    latency_seconds: float
    success: bool
    task_type: str | None = None
    error: str | None = None


@dataclass
class SwarmTaskMetric:
    """Metrics for a Swarm task"""

    timestamp: str
    mode: str  # ping_pong, parallel, lead_support, etc.
    rounds: int
    duration_seconds: float
    success: bool
    agents_used: list[str] = None
    negotiation_turns: int = 0


@dataclass
class SessionMetric:
    """Metrics for a session"""

    session_id: str
    start_time: str
    total_api_calls: int
    total_tokens: int
    total_errors: int
    swarm_tasks: int
    tool_executions: int
    duration_seconds: float


class TelemetryCollector:
    """
    Collects and persists telemetry metrics.

    Thread-safe and designed for minimal overhead.
    """

    def __init__(self, config=None, output_file: Path | None = None):
        """
        Initialize TelemetryCollector.

        Args:
            config: NEXUS config (uses telemetry_file if available)
            output_file: Override output file path
        """
        self.enabled = True
        self.config = config
        if config:
            self.enabled = getattr(config, "telemetry_enabled", True)
            default_file = getattr(config, "telemetry_file", "workspace/telemetry.jsonl")
            self.output_file = output_file or Path(default_file)
        else:
            self.output_file = output_file or Path("workspace/telemetry.jsonl")

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start = time.time()
        self._lock = Lock()

        # In-memory counters for session summary
        self._api_calls = 0
        self._total_tokens = 0
        self._total_cost_usd = 0.0
        self._errors = 0
        self._swarm_tasks = 0
        self._tool_executions = 0

        # Budget tracking (Phase 14d)
        workspace_path = getattr(config, "workspace_path", None) if config else None
        self._budget_tracker: BudgetTracker | None = None
        if self.enabled:
            try:
                self._budget_tracker = BudgetTracker(config, workspace_path)
            except Exception as e:
                _logger.error("Budget tracker init error: %s", e, exc_info=True)

        # Ensure output directory exists
        if self.enabled:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)

    def _write_event(self, event_type: MetricType, data: dict[str, Any]):
        """Write an event to the telemetry file (thread-safe)"""
        if not self.enabled:
            return

        event = {
            "type": event_type.value,
            "session_id": self.session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }

        with self._lock:
            try:
                with open(self.output_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as e:
                _logger.warning("Telemetry write error: %s", e)

    def record_api_call(
        self,
        provider: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_seconds: float = 0.0,
        success: bool = True,
        task_type: str | None = None,
        error: str | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
    ):
        """
        Record an API call metric and track cost.

        Args:
            provider: "gemini" or "claude"
            model: Model name (e.g., "gemini-3-pro-preview")
            tokens_in: Input tokens (0 to estimate from input_text)
            tokens_out: Output tokens (0 to estimate from output_text)
            latency_seconds: Call duration
            success: Whether call succeeded
            task_type: Optional task type (brainstorm, tool, etc.)
            error: Error message if failed
            input_text: Input text for token estimation
            output_text: Output text for token estimation
        """
        self._api_calls += 1
        self._total_tokens += tokens_in + tokens_out
        if not success:
            self._errors += 1

        # Track cost via budget tracker (Phase 14d)
        cost_usd = 0.0
        if self._budget_tracker:
            try:
                cost_usd = self._budget_tracker.track_cost(
                    model=model,
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    input_text=input_text,
                    output_text=output_text,
                )
                self._total_cost_usd += cost_usd
            except Exception as e:
                _logger.error("Cost tracking error: %s", e, exc_info=True)

        metric = APICallMetric(
            timestamp=datetime.now(UTC).isoformat(),
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_seconds=latency_seconds,
            success=success,
            task_type=task_type,
            error=error,
        )

        # Add cost to metric data
        metric_data = asdict(metric)
        metric_data["cost_usd"] = round(cost_usd, 6)

        self._write_event(MetricType.API_CALL, metric_data)

    def record_swarm_task(
        self,
        mode: str,
        rounds: int,
        duration_seconds: float,
        success: bool,
        agents_used: list[str] | None = None,
        negotiation_turns: int = 0,
    ):
        """
        Record a Swarm task metric.

        Args:
            mode: Collaboration mode used
            rounds: Number of execution rounds
            duration_seconds: Total duration
            success: Whether task completed successfully
            agents_used: List of agent IDs that participated
            negotiation_turns: Turns spent in negotiation
        """
        self._swarm_tasks += 1
        if not success:
            self._errors += 1

        metric = SwarmTaskMetric(
            timestamp=datetime.now(UTC).isoformat(),
            mode=mode,
            rounds=rounds,
            duration_seconds=duration_seconds,
            success=success,
            agents_used=agents_used or [],
            negotiation_turns=negotiation_turns,
        )

        self._write_event(MetricType.SWARM_TASK, asdict(metric))

    def record_tool_execution(self, tool_name: str, duration_seconds: float, success: bool, error: str | None = None):
        """Record a tool execution metric"""
        self._tool_executions += 1
        if not success:
            self._errors += 1

        self._write_event(
            MetricType.TOOL_EXECUTION,
            {"tool_name": tool_name, "duration_seconds": duration_seconds, "success": success, "error": error},
        )

    def record_error(self, error_type: str, message: str, context: dict | None = None):
        """Record an error event"""
        self._errors += 1

        self._write_event(MetricType.ERROR, {"error_type": error_type, "message": message, "context": context or {}})

    def record_evolution(
        self,
        generation: int,
        child_id: str,
        parent_score: float,
        child_score: float,
        promoted: bool,
        mutations: list[str],
    ):
        """Record an evolution cycle metric"""
        self._write_event(
            MetricType.EVOLUTION,
            {
                "generation": generation,
                "child_id": child_id,
                "parent_score": parent_score,
                "child_score": child_score,
                "improvement_pct": ((child_score - parent_score) / parent_score * 100) if parent_score > 0 else 0,
                "promoted": promoted,
                "mutations": mutations,
            },
        )

    def get_session_summary(self) -> SessionMetric:
        """Get summary metrics for the current session"""
        duration = time.time() - self.session_start

        return SessionMetric(
            session_id=self.session_id,
            start_time=datetime.fromtimestamp(self.session_start).isoformat(),
            total_api_calls=self._api_calls,
            total_tokens=self._total_tokens,
            total_errors=self._errors,
            swarm_tasks=self._swarm_tasks,
            tool_executions=self._tool_executions,
            duration_seconds=round(duration, 2),
        )

    def write_session_summary(self):
        """Write session summary to telemetry file"""
        summary = self.get_session_summary()
        self._write_event(MetricType.SESSION, asdict(summary))

    def print_summary(self):
        """Print session summary to console"""
        summary = self.get_session_summary()
        print(f"\n{'=' * 50}")
        print("TELEMETRY SESSION SUMMARY")
        print(f"{'=' * 50}")
        print(f"Session ID: {summary.session_id}")
        print(f"Duration: {summary.duration_seconds:.1f}s")
        print(f"API Calls: {summary.total_api_calls}")
        print(f"Total Tokens: {summary.total_tokens:,}")
        print(f"Session Cost: ${self._total_cost_usd:.4f}")
        print(f"Swarm Tasks: {summary.swarm_tasks}")
        print(f"Tool Executions: {summary.tool_executions}")
        print(f"Errors: {summary.total_errors}")
        if self._budget_tracker:
            stats = self._budget_tracker.get_stats()
            print(
                f"Budget: ${stats['spent_today_usd']:.2f} / ${stats['limit_usd']:.2f} ({stats['percentage_used']:.1f}%)"
            )
        print(f"{'=' * 50}\n")

    # =========================================================================
    # Budget Enforcement (Phase 14d)
    # =========================================================================

    def enforce_budget(self) -> bool:
        """
        Check and enforce budget limit.

        Returns:
            True if within budget

        Raises:
            BudgetExceededError: If daily budget limit exceeded
        """
        if not self._budget_tracker:
            return True
        return self._budget_tracker.check_budget()

    def get_budget_stats(self) -> dict | None:
        """
        Get current budget statistics.

        Returns:
            Dict with budget stats or None if tracker not available
        """
        if not self._budget_tracker:
            return None
        return self._budget_tracker.get_stats()

    def get_budget_warning_level(self) -> str | None:
        """
        Get current budget warning level.

        Returns:
            "warning" at 80%, "critical" at 90%, None otherwise
        """
        if not self._budget_tracker:
            return None
        return self._budget_tracker.get_warning_level()


# Singleton instance for easy access
_collector: TelemetryCollector | None = None


def get_telemetry(config=None) -> TelemetryCollector:
    """Get or create the global telemetry collector"""
    global _collector
    if _collector is None:
        _collector = TelemetryCollector(config)
    return _collector
