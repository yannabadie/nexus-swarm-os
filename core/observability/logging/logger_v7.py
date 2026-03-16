"""
Logging System V7 - Structured logging pour development et runtime

Architecture:
- JSONL format pour parsing facile
- 3 types de logs: events, errors, trace
- Rotation automatique par jour
- Non-bloquant (append-only)
- Configurable par niveau (DEBUG, INFO, WARNING, ERROR, CRITICAL)

Fichiers créés:
- workspace/logs/events_YYYYMMDD.jsonl    # Tous les events structurés
- workspace/logs/errors_YYYYMMDD.log      # Erreurs uniquement (humain-readable)
- workspace/logs/trace_YYYYMMDD.log       # Trace complète (DEBUG)
- workspace/logs/summary_YYYYMMDD.json    # Résumé session
"""

import json
import sys
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class LogLevel(Enum):
    """Niveaux de log"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(Enum):
    """Types d'events loggés"""

    # FSM
    FSM_TRANSITION = "fsm_transition"
    FSM_STATE = "fsm_state"

    # Agents
    AGENT_INVOKE = "agent_invoke"
    AGENT_RESPONSE = "agent_response"
    AGENT_ERROR = "agent_error"

    # Tools
    TOOL_EXECUTE = "tool_execute"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # Monitoring
    STAGNATION_DETECTED = "stagnation_detected"
    PLAN_HEALTH = "plan_health"
    PANIC_TRIGGERED = "panic_triggered"
    PANIC_CLEARED = "panic_cleared"

    # Memory
    BACKUP_CREATED = "backup_created"
    STATE_ROLLBACK = "state_rollback"

    # Session
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"

    # Performance
    ITERATION_COMPLETE = "iteration_complete"


class NexusLogger:
    """
    Logger structuré pour NEXUS V7

    Features:
    - JSONL events log (machine-readable)
    - Plain text error log (human-readable)
    - Debug trace log (verbose)
    - Session summary (metrics)
    - Auto-rotation par jour
    - Non-bloquant (append-only writes)
    """

    def __init__(self, workspace_path: Path, log_level: str = "INFO"):
        """
        Args:
            workspace_path: Workspace NEXUS
            log_level: DEBUG, INFO, WARNING, ERROR, CRITICAL
        """
        self.workspace_path = workspace_path
        self.log_dir = workspace_path / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Parse log level
        try:
            self.log_level = LogLevel[log_level.upper()]
        except KeyError:
            self.log_level = LogLevel.INFO

        # Date pour rotation
        self.current_date = datetime.now().strftime("%Y%m%d")

        # Fichiers de log
        self.events_file = self.log_dir / f"events_{self.current_date}.jsonl"
        self.errors_file = self.log_dir / f"errors_{self.current_date}.log"
        self.trace_file = self.log_dir / f"trace_{self.current_date}.log"
        self.summary_file = self.log_dir / f"summary_{self.current_date}.json"

        # Session metadata
        self.session_start = datetime.now(UTC)
        self.session_id = self.session_start.strftime("%Y%m%d_%H%M%S")

        # Metrics
        self.metrics = {
            "session_id": self.session_id,
            "start_time": self.session_start.isoformat(),
            "total_iterations": 0,
            "total_tool_executions": 0,
            "total_errors": 0,
            "fsm_transitions": {},
            "agent_invocations": {"Gemini": 0, "Claude": 0},
            "tools_used": {},
            "panic_count": 0,
            "stagnation_count": 0,
        }

        # Log session start
        self.log_event(
            EventType.SESSION_START,
            {"session_id": self.session_id, "workspace": str(workspace_path), "log_level": log_level},
        )

    def log_event(self, event_type: EventType, data: dict[str, Any], level: LogLevel = LogLevel.INFO):
        """
        Log event structuré

        Args:
            event_type: Type d'event (enum)
            data: Données de l'event
            level: Niveau de log

        Format JSONL:
            {
              "timestamp": "2025-01-21T14:30:22.123456Z",
              "session_id": "20250121_143022",
              "event_type": "agent_invoke",
              "level": "INFO",
              "data": {...}
            }
        """
        # Check log level
        if self._should_log(level):
            event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "session_id": self.session_id,
                "event_type": event_type.value,
                "level": level.value,
                "data": data,
            }

            # Write to events file (JSONL)
            try:
                with open(self.events_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as e:
                # Fallback: print to stderr si log échoue
                print(f"[LOG ERROR] Failed to write event: {e}", file=sys.stderr)

            # Si ERROR ou CRITICAL, log aussi dans errors file
            if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
                self._log_error(event_type, data, level)

            # Update metrics
            self._update_metrics(event_type, data)

    def log_fsm_transition(self, from_state: str, to_state: str, iteration: int):
        """Log transition FSM"""
        self.log_event(
            EventType.FSM_TRANSITION,
            {"from_state": from_state, "to_state": to_state, "iteration": iteration},
            LogLevel.DEBUG,
        )

        # Update metrics
        transition_key = f"{from_state}->{to_state}"
        self.metrics["fsm_transitions"][transition_key] = self.metrics["fsm_transitions"].get(transition_key, 0) + 1

    def log_agent_invocation(self, agent: str, iteration: int, context_size: int = 0):
        """Log invocation agent"""
        self.log_event(
            EventType.AGENT_INVOKE,
            {"agent": agent, "iteration": iteration, "context_size": context_size},
            LogLevel.INFO,
        )

        self.metrics["agent_invocations"][agent] += 1

    def log_agent_response(self, agent: str, action_type: str, has_tool: bool, duration_ms: float):
        """Log réponse agent"""
        self.log_event(
            EventType.AGENT_RESPONSE,
            {"agent": agent, "action_type": action_type, "has_tool": has_tool, "duration_ms": round(duration_ms, 2)},
            LogLevel.INFO,
        )

    def log_agent_error(self, agent: str, error_type: str, error_msg: str):
        """Log erreur agent"""
        self.log_event(
            EventType.AGENT_ERROR,
            {"agent": agent, "error_type": error_type, "error_message": error_msg},
            LogLevel.ERROR,
        )

        self.metrics["total_errors"] += 1

    def log_tool_execution(self, tool_name: str, args: dict, iteration: int):
        """Log début exécution tool"""
        self.log_event(
            EventType.TOOL_EXECUTE, {"tool_name": tool_name, "arguments": args, "iteration": iteration}, LogLevel.INFO
        )

    def log_tool_result(self, tool_name: str, status: str, duration_ms: float, output_size: int):
        """Log résultat tool"""
        self.log_event(
            EventType.TOOL_RESULT,
            {
                "tool_name": tool_name,
                "status": status,
                "duration_ms": round(duration_ms, 2),
                "output_size": output_size,
            },
            LogLevel.INFO,
        )

        self.metrics["total_tool_executions"] += 1
        self.metrics["tools_used"][tool_name] = self.metrics["tools_used"].get(tool_name, 0) + 1

    def log_tool_error(self, tool_name: str, error_msg: str):
        """Log erreur tool"""
        self.log_event(EventType.TOOL_ERROR, {"tool_name": tool_name, "error_message": error_msg}, LogLevel.ERROR)

        self.metrics["total_errors"] += 1

    def log_stagnation(self, similarity: float, window_size: int):
        """Log détection stagnation"""
        self.log_event(
            EventType.STAGNATION_DETECTED,
            {"similarity": round(similarity, 3), "window_size": window_size},
            LogLevel.WARNING,
        )

        self.metrics["stagnation_count"] += 1

    def log_plan_health(self, status: str, message: str, turns_since_progress: int, turns_since_completion: int):
        """Log plan health"""
        level = (
            LogLevel.DEBUG
            if status == "HEALTHY"
            else LogLevel.WARNING
            if status in ["WARNING", "STAGNANT"]
            else LogLevel.ERROR
        )

        self.log_event(
            EventType.PLAN_HEALTH,
            {
                "status": status,
                "message": message,
                "turns_since_progress": turns_since_progress,
                "turns_since_completion": turns_since_completion,
            },
            level,
        )

    def log_panic(self, reason: str, details: str):
        """Log panic trigger"""
        self.log_event(EventType.PANIC_TRIGGERED, {"reason": reason, "details": details}, LogLevel.CRITICAL)

        self.metrics["panic_count"] += 1

    def log_panic_cleared(self):
        """Log panic cleared"""
        self.log_event(EventType.PANIC_CLEARED, {}, LogLevel.INFO)

    def log_backup(self, reason: str, backup_file: str):
        """Log backup created"""
        self.log_event(EventType.BACKUP_CREATED, {"reason": reason, "backup_file": backup_file}, LogLevel.DEBUG)

    def log_rollback(self, backup_file: str, success: bool):
        """Log state rollback"""
        self.log_event(
            EventType.STATE_ROLLBACK,
            {"backup_file": backup_file, "success": success},
            LogLevel.WARNING if success else LogLevel.ERROR,
        )

    def log_user_input(self, input_text: str, iteration: int):
        """Log user input"""
        self.log_event(
            EventType.USER_INPUT,
            {
                "input": input_text[:200],  # Truncate long inputs
                "iteration": iteration,
            },
            LogLevel.DEBUG,
        )

    def log_iteration_complete(self, iteration: int, state: str, duration_ms: float, success: bool):
        """Log fin d'itération"""
        self.log_event(
            EventType.ITERATION_COMPLETE,
            {"iteration": iteration, "state": state, "duration_ms": round(duration_ms, 2), "success": success},
            LogLevel.DEBUG,
        )

        self.metrics["total_iterations"] = iteration

    def debug(self, message: str, context: dict | None = None):
        """Log debug message"""
        self.log_event(EventType.FSM_STATE, {"message": message, "context": context or {}}, LogLevel.DEBUG)

    def info(self, message: str, context: dict | None = None):
        """Log info message"""
        self.log_event(EventType.FSM_STATE, {"message": message, "context": context or {}}, LogLevel.INFO)

    def warning(self, message: str, context: dict | None = None):
        """Log warning message"""
        self.log_event(EventType.FSM_STATE, {"message": message, "context": context or {}}, LogLevel.WARNING)

    def error(self, message: str, context: dict | None = None):
        """Log error message"""
        self.log_event(EventType.FSM_STATE, {"message": message, "context": context or {}}, LogLevel.ERROR)

    def critical(self, message: str, context: dict | None = None):
        """Log critical message"""
        self.log_event(EventType.FSM_STATE, {"message": message, "context": context or {}}, LogLevel.CRITICAL)

    def trace(self, message: str):
        """
        Log trace (très verbose)

        Écrit directement dans trace file (pas events JSONL)
        """
        if self.log_level == LogLevel.DEBUG:
            try:
                timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                with open(self.trace_file, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                # V9: Don't use bare except: - silently ignore trace write errors
                # but allow SystemExit and KeyboardInterrupt to propagate
                pass

    def end_session(self):
        """Termine session et écrit summary"""
        self.log_event(
            EventType.SESSION_END,
            {
                "session_id": self.session_id,
                "duration_seconds": (datetime.now(UTC) - self.session_start).total_seconds(),
            },
        )

        # Write summary
        self.metrics["end_time"] = datetime.now(UTC).isoformat()
        self.metrics["duration_seconds"] = (datetime.now(UTC) - self.session_start).total_seconds()

        try:
            with open(self.summary_file, "w", encoding="utf-8") as f:
                json.dump(self.metrics, f, indent=2, ensure_ascii=False)
        except Exception:
            # V9: Don't use bare except: - silently ignore summary write errors
            pass

    def _log_error(self, event_type: EventType, data: dict, level: LogLevel):
        """Log erreur dans error file (human-readable)"""
        try:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            with open(self.errors_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{level.value}] {event_type.value}\n")
                f.write(f"  {json.dumps(data, indent=2, ensure_ascii=False)}\n")
                f.write("-" * 80 + "\n")
        except Exception:
            # V9: Don't use bare except: - silently ignore error log write errors
            pass

    def _should_log(self, level: LogLevel) -> bool:
        """Check si on doit logger ce niveau"""
        levels_order = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]
        return levels_order.index(level) >= levels_order.index(self.log_level)

    def _update_metrics(self, event_type: EventType, data: dict):
        """Update metrics internes"""
        # Metrics are updated in specific log methods
        pass

    def get_session_summary(self) -> dict:
        """Retourne résumé session actuelle"""
        return {**self.metrics, "current_duration_seconds": (datetime.now(UTC) - self.session_start).total_seconds()}


# Singleton global logger (initialisé par orchestrator)
# V9: Thread-safe initialization with double-checked locking
import threading  # noqa: E402  # singleton setup after class definition

_global_logger: NexusLogger | None = None
_logger_lock = threading.Lock()


def init_logger(workspace_path: Path, log_level: str = "INFO") -> NexusLogger:
    """
    Initialize global logger.

    V9: Thread-safe initialization to prevent race conditions.
    """
    global _global_logger
    with _logger_lock:
        if _global_logger is None:
            _global_logger = NexusLogger(workspace_path, log_level)
    return _global_logger


def get_logger() -> NexusLogger | None:
    """Get global logger instance"""
    return _global_logger


def cleanup_old_logs(workspace_path: Path, keep_days: int = 7):
    """
    Cleanup logs plus vieux que N jours

    Args:
        workspace_path: Workspace NEXUS
        keep_days: Garder logs des N derniers jours
    """
    log_dir = workspace_path / "logs"
    if not log_dir.exists():
        return

    cutoff_date = datetime.now().timestamp() - (keep_days * 86400)

    for log_file in log_dir.glob("*"):
        if log_file.is_file():
            try:
                if log_file.stat().st_mtime < cutoff_date:
                    log_file.unlink()
            except Exception:
                # V9: Don't use bare except: - silently ignore cleanup errors
                pass
