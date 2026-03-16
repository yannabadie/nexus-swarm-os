"""
Auto-Memory - NEXUS V7.5 HIVE MIND

Tracks successful and failed patterns to improve future decisions.
NEXUS learns what works and reuses effective strategies.

Storage:
- workspace/memory/successes.jsonl - Successful task patterns
- workspace/memory/failures.jsonl - Failed approaches to avoid
- workspace/memory/fitness_scores.json - Agent fitness history

Usage:
    memory = AutoMemory()
    memory.record_success(task_type="code_review", swarm_mode="PING_PONG", lead="claude")
    memory.record_failure(task_type="security_audit", swarm_mode="PARALLEL", reason="timeout")
    best_mode = memory.suggest_mode("code_review")  # Returns "PING_PONG"
"""

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    """A single memory entry (success or failure)."""

    timestamp: str
    task_type: str
    task_description: str
    swarm_mode: str
    lead_agent: str
    duration_seconds: float
    outcome: str  # "success" or "failure"
    reason: str | None = None  # For failures
    score: float | None = None  # Quality score 0-1


class AutoMemory:
    """
    Auto-Memory system for learning from successes and failures.

    NEXUS uses this to:
    1. Remember what worked for similar tasks
    2. Avoid repeating failed approaches
    3. Build fitness profiles for agents
    """

    def __init__(self, workspace_path: Path = None):
        self.workspace = workspace_path or Path("workspace")
        self.memory_dir = self.workspace / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.successes_file = self.memory_dir / "successes.jsonl"
        self.failures_file = self.memory_dir / "failures.jsonl"
        self.fitness_file = self.memory_dir / "fitness_scores.json"

        # In-memory cache for quick lookups
        self._success_cache: dict[str, list[dict]] = defaultdict(list)
        self._failure_cache: dict[str, list[dict]] = defaultdict(list)
        self._load_cache()

    def _load_cache(self):
        """Load existing memory into cache."""
        if self.successes_file.exists():
            try:
                with open(self.successes_file, encoding="utf-8") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        self._success_cache[entry.get("task_type", "unknown")].append(entry)
            except Exception:
                pass

        if self.failures_file.exists():
            try:
                with open(self.failures_file, encoding="utf-8") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        self._failure_cache[entry.get("task_type", "unknown")].append(entry)
            except Exception:
                pass

    def record_success(
        self,
        task_type: str,
        task_description: str,
        swarm_mode: str,
        lead_agent: str,
        duration_seconds: float,
        score: float = 1.0,
    ):
        """
        Record a successful task completion.

        Args:
            task_type: Category of task (e.g., "code_review", "debugging")
            task_description: Brief description of the task
            swarm_mode: Swarm mode used (e.g., "PING_PONG", "PARALLEL")
            lead_agent: Agent that led (e.g., "gemini", "claude")
            duration_seconds: How long it took
            score: Quality score 0-1 (default 1.0 for success)
        """
        entry = MemoryEntry(
            timestamp=datetime.now().isoformat(),
            task_type=task_type,
            task_description=task_description[:200],  # Truncate
            swarm_mode=swarm_mode,
            lead_agent=lead_agent,
            duration_seconds=duration_seconds,
            outcome="success",
            score=score,
        )

        self._append_to_file(self.successes_file, asdict(entry))
        self._success_cache[task_type].append(asdict(entry))
        self._update_fitness(lead_agent, task_type, score)

    def record_failure(
        self,
        task_type: str,
        task_description: str,
        swarm_mode: str,
        lead_agent: str,
        duration_seconds: float,
        reason: str,
    ):
        """
        Record a failed task attempt.

        Args:
            task_type: Category of task
            task_description: Brief description
            swarm_mode: Swarm mode used
            lead_agent: Agent that led
            duration_seconds: Time spent before failure
            reason: Why it failed
        """
        entry = MemoryEntry(
            timestamp=datetime.now().isoformat(),
            task_type=task_type,
            task_description=task_description[:200],
            swarm_mode=swarm_mode,
            lead_agent=lead_agent,
            duration_seconds=duration_seconds,
            outcome="failure",
            reason=reason,
            score=0.0,
        )

        self._append_to_file(self.failures_file, asdict(entry))
        self._failure_cache[task_type].append(asdict(entry))
        self._update_fitness(lead_agent, task_type, 0.0)

    def _append_to_file(self, filepath: Path, entry: dict):
        """Append entry to JSONL file."""
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _update_fitness(self, agent: str, task_type: str, score: float):
        """Update fitness scores for agent."""
        fitness_data = {}
        if self.fitness_file.exists():
            try:
                with open(self.fitness_file, encoding="utf-8") as f:
                    fitness_data = json.load(f)
            except Exception:
                pass

        if agent not in fitness_data:
            fitness_data[agent] = {"tasks": {}, "overall": 0.7}

        if task_type not in fitness_data[agent]["tasks"]:
            fitness_data[agent]["tasks"][task_type] = {"scores": [], "avg": 0.7}

        # Keep last 20 scores per task type
        scores = fitness_data[agent]["tasks"][task_type]["scores"]
        scores.append(score)
        if len(scores) > 20:
            scores = scores[-20:]
        fitness_data[agent]["tasks"][task_type]["scores"] = scores
        fitness_data[agent]["tasks"][task_type]["avg"] = sum(scores) / len(scores)

        # Update overall
        all_avgs = [t["avg"] for t in fitness_data[agent]["tasks"].values()]
        fitness_data[agent]["overall"] = sum(all_avgs) / len(all_avgs) if all_avgs else 0.7

        with open(self.fitness_file, "w", encoding="utf-8") as f:
            json.dump(fitness_data, f, indent=2, ensure_ascii=False)

    def _apply_time_decay(self, score: float, timestamp_str: str, decay_coefficient: float = 0.003) -> float:
        """
        V11.2 MEMORIA: Apply exponential time decay to score.

        Mirrors SuccessMemory's decay for consistency across memory systems.

        Formula: decayed_score = score * exp(-decay_coefficient * age_days)

        Decay examples with coefficient=0.003:
        - 1 week old (7d):   0.98x (2% decay)
        - 4 weeks old (28d): 0.92x (8% decay)
        - 12 weeks old (84d): 0.78x (22% decay)

        Args:
            score: Original score to decay
            timestamp_str: ISO timestamp string from entry
            decay_coefficient: Decay rate per day (default 0.003)

        Returns:
            Decayed score (capped at original if parsing fails)
        """
        try:
            entry_time = datetime.fromisoformat(timestamp_str)
            now = datetime.now()
            age_days = max(0, (now - entry_time).days)
            decay_factor = math.exp(-decay_coefficient * age_days)
            return score * decay_factor
        except (ValueError, TypeError):
            # If timestamp parsing fails, return original score
            return score

    def suggest_mode(self, task_type: str, apply_decay: bool = True) -> str | None:
        """
        Suggest best swarm mode for a task type based on history.

        V11.2 MEMORIA: Now applies time decay to weight recent successes more.

        Args:
            task_type: Task type to look up
            apply_decay: Whether to apply time decay (default True)

        Returns:
            Best performing swarm mode or None if no data
        """
        successes = self._success_cache.get(task_type, [])
        if not successes:
            return None

        # Count successes by mode, weighted by score (V11.2: with time decay)
        mode_scores = defaultdict(float)
        mode_counts = defaultdict(int)

        for entry in successes:
            mode = entry.get("swarm_mode", "unknown")
            score = entry.get("score", 1.0)

            # V11.2 MEMORIA: Apply time decay
            if apply_decay:
                timestamp = entry.get("timestamp", "")
                score = self._apply_time_decay(score, timestamp)

            mode_scores[mode] += score
            mode_counts[mode] += 1

        # Average score per mode
        mode_avg = {m: mode_scores[m] / mode_counts[m] for m in mode_scores}

        if not mode_avg:
            return None

        best_mode = max(mode_avg, key=mode_avg.get)
        return best_mode

    def suggest_lead(self, task_type: str, apply_decay: bool = True) -> str | None:
        """
        Suggest best lead agent for a task type based on history.

        V11.2 MEMORIA: Now applies time decay to weight recent successes more.

        Args:
            task_type: Task type to look up
            apply_decay: Whether to apply time decay (default True)

        Returns:
            Best performing agent or None if no data
        """
        successes = self._success_cache.get(task_type, [])
        if not successes:
            return None

        agent_scores = defaultdict(float)
        agent_counts = defaultdict(int)

        for entry in successes:
            agent = entry.get("lead_agent", "unknown")
            score = entry.get("score", 1.0)

            # V11.2 MEMORIA: Apply time decay
            if apply_decay:
                timestamp = entry.get("timestamp", "")
                score = self._apply_time_decay(score, timestamp)

            agent_scores[agent] += score
            agent_counts[agent] += 1

        agent_avg = {a: agent_scores[a] / agent_counts[a] for a in agent_scores}

        if not agent_avg:
            return None

        return max(agent_avg, key=agent_avg.get)

    def should_avoid(self, task_type: str, swarm_mode: str) -> bool:
        """
        Check if a mode should be avoided for a task type.

        Returns True if mode has >50% failure rate for this task type.
        """
        failures = [e for e in self._failure_cache.get(task_type, []) if e.get("swarm_mode") == swarm_mode]
        successes = [e for e in self._success_cache.get(task_type, []) if e.get("swarm_mode") == swarm_mode]

        total = len(failures) + len(successes)
        if total < 3:  # Not enough data
            return False

        failure_rate = len(failures) / total
        return failure_rate > 0.5

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        total_successes = sum(len(v) for v in self._success_cache.values())
        total_failures = sum(len(v) for v in self._failure_cache.values())

        return {
            "total_successes": total_successes,
            "total_failures": total_failures,
            "success_rate": total_successes / (total_successes + total_failures)
            if (total_successes + total_failures) > 0
            else 0,
            "task_types_tracked": list(set(list(self._success_cache.keys()) + list(self._failure_cache.keys()))),
            "memory_files": {
                "successes": str(self.successes_file),
                "failures": str(self.failures_file),
                "fitness": str(self.fitness_file),
            },
        }

    def get_recommendation(self, task_type: str, task_description: str = "") -> dict[str, Any]:
        """
        Get full recommendation for a task based on memory.

        Returns:
            {
                "suggested_mode": str or None,
                "suggested_lead": str or None,
                "modes_to_avoid": List[str],
                "confidence": float,
                "based_on_samples": int
            }
        """
        successes = self._success_cache.get(task_type, [])
        failures = self._failure_cache.get(task_type, [])
        total_samples = len(successes) + len(failures)

        modes_to_avoid = []
        for mode in set(e.get("swarm_mode") for e in successes + failures):
            if mode and self.should_avoid(task_type, mode):
                modes_to_avoid.append(mode)

        confidence = min(1.0, total_samples / 10)  # 10+ samples = full confidence

        return {
            "suggested_mode": self.suggest_mode(task_type),
            "suggested_lead": self.suggest_lead(task_type),
            "modes_to_avoid": modes_to_avoid,
            "confidence": confidence,
            "based_on_samples": total_samples,
        }


# =============================================================================
# V10 PRISM: Multi-Tenant Auto Memory Access
# =============================================================================

_auto_memory: AutoMemory | None = None


def get_auto_memory(workspace_path: Path = None) -> AutoMemory:
    """
    Get the AutoMemory for the current tenant context.

    V10 PRISM: Returns tenant-scoped instance via ServiceFactory.
    Falls back to global singleton if no context is active.

    Args:
        workspace_path: Workspace path (required on first call in legacy mode)

    Returns:
        AutoMemory instance scoped to current tenant
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_auto_memory()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    global _auto_memory
    if _auto_memory is None:
        _auto_memory = AutoMemory(workspace_path)
    return _auto_memory


def reset_auto_memory() -> None:
    """
    Reset the global AutoMemory instance (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _auto_memory
    _auto_memory = None

    # V10: Also clear factory cache
    try:
        from ..context import get_current_session_or_none
        from ..factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
