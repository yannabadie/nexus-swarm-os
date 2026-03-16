"""
Rate Limiter - Contrôle des générations évolutives

Applique les limites définies dans config.py:
- max_generations_per_day: 3 générations/jour
- min_hours_between_generations: 8h entre chaque
- max_children_per_generation: 3 enfants max

Historique stocké dans workspace/.nexus/evolution_history.json
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


class EvolutionRateLimiter:
    """
    Enforces rate limits on evolution cycles
    """

    def __init__(self, workspace_path: Path, config):
        self.workspace_path = workspace_path
        self.history_file = workspace_path / ".nexus" / "evolution_history.json"

        # Limites depuis config
        self.max_gen_per_day = config.max_generations_per_day
        self.min_hours_between = config.min_hours_between_generations
        self.max_children = config.max_children_per_generation

        # Ensure history file exists
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self._init_history()

    def _init_history(self):
        """Initialize empty history"""
        self.history_file.write_text(
            json.dumps(
                {"evolutions": [], "stats": {"total_evolutions": 0, "total_children": 0, "last_evolution": None}},
                indent=2,
            ),
            encoding="utf-8",
        )

    def _load_history(self) -> dict:
        """Load evolution history"""
        return json.loads(self.history_file.read_text(encoding="utf-8"))

    def _save_history(self, history: dict):
        """Save evolution history"""
        self.history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def can_evolve(self, num_children: int) -> tuple[bool, str]:
        """
        Check if evolution is allowed

        Args:
            num_children: Number of children requested

        Returns:
            (allowed: bool, reason: str)
        """
        history = self._load_history()
        evolutions = history["evolutions"]

        # Check 1: Children count
        if num_children > self.max_children:
            return False, f"Max {self.max_children} children per generation (requested: {num_children})"

        # Check 2: Daily limit
        today = datetime.now().date()
        today_count = sum(1 for ev in evolutions if datetime.fromisoformat(ev["timestamp"]).date() == today)

        if today_count >= self.max_gen_per_day:
            return False, f"Daily limit reached ({today_count}/{self.max_gen_per_day} evolutions today)"

        # Check 3: Time between evolutions
        if evolutions:
            last_evolution = datetime.fromisoformat(evolutions[-1]["timestamp"])
            hours_since = (datetime.now() - last_evolution).total_seconds() / 3600

            if hours_since < self.min_hours_between:
                hours_remaining = self.min_hours_between - hours_since
                return False, f"Wait {hours_remaining:.1f}h (min {self.min_hours_between}h between evolutions)"

        return True, "Evolution allowed"

    def record_evolution(self, generation: int, num_children: int, parent_id: str):
        """
        Record evolution in history

        Args:
            generation: Generation number
            num_children: Number of children created
            parent_id: Parent ID (ex: "NEXUS_V6.0")
        """
        history = self._load_history()

        evolution_record = {
            "timestamp": datetime.now().isoformat(),
            "generation": generation,
            "parent_id": parent_id,
            "num_children": num_children,
        }

        history["evolutions"].append(evolution_record)
        history["stats"]["total_evolutions"] += 1
        history["stats"]["total_children"] += num_children
        history["stats"]["last_evolution"] = evolution_record["timestamp"]

        self._save_history(history)

    def get_stats(self) -> dict:
        """Get evolution statistics"""
        history = self._load_history()
        stats = history["stats"].copy()

        # Calculate today's evolutions
        today = datetime.now().date()
        today_count = sum(1 for ev in history["evolutions"] if datetime.fromisoformat(ev["timestamp"]).date() == today)
        stats["today_evolutions"] = today_count
        stats["remaining_today"] = max(0, self.max_gen_per_day - today_count)

        # Calculate time since last
        if stats["last_evolution"]:
            last = datetime.fromisoformat(stats["last_evolution"])
            hours_since = (datetime.now() - last).total_seconds() / 3600
            stats["hours_since_last"] = round(hours_since, 1)
            stats["can_evolve_at"] = (last + timedelta(hours=self.min_hours_between)).isoformat()

        return stats

    def reset_daily(self):
        """
        Reset daily counters (admin command)
        Use with caution!
        """
        history = self._load_history()

        # Keep only non-today evolutions
        today = datetime.now().date()
        history["evolutions"] = [
            ev for ev in history["evolutions"] if datetime.fromisoformat(ev["timestamp"]).date() != today
        ]

        self._save_history(history)
