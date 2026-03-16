"""
Strategy Memory - Learn and recall effective collaboration strategies.

V12.4 COGNITIVE BOOST

Tracks which swarm modes work best for different task types,
enabling faster mode selection and reduced negotiation overhead.

Usage:
    from core.intelligence.swarm.strategy_memory import get_strategy_memory

    mem = get_strategy_memory()
    mem.record_strategy("coding", "medium", mode="LEAD_SUPPORT", quality=0.9)
    suggestion = mem.suggest_mode("coding", "medium")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_RECORDS = 50000
MIN_SAMPLES_FOR_SUGGESTION = 3
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


# =============================================================================
# Types
# =============================================================================


@dataclass
class StrategyRecord:
    """A single strategy execution record."""

    domain: str
    complexity: str  # trivial, simple, moderate, complex, expert
    mode: str  # PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE
    quality: float = 0.0
    success: bool = True
    duration_ms: float = 0.0
    agents: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def key(self) -> str:
        return f"{self.domain}:{self.complexity}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "complexity": self.complexity,
            "mode": self.mode,
            "quality": round(self.quality, 4),
            "success": self.success,
            "duration_ms": self.duration_ms,
            "agents": self.agents,
        }


@dataclass
class ModeEffectiveness:
    """Effectiveness of a mode for a specific domain/complexity."""

    mode: str
    total_uses: int = 0
    successes: int = 0
    average_quality: float = 0.0
    average_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.total_uses if self.total_uses > 0 else 0.0

    @property
    def score(self) -> float:
        """Composite score: weighted average of success rate and quality."""
        return 0.4 * self.success_rate + 0.6 * self.average_quality

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_uses": self.total_uses,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 4),
            "average_quality": round(self.average_quality, 4),
            "average_duration_ms": round(self.average_duration_ms, 2),
            "score": round(self.score, 4),
        }


@dataclass
class ModeSuggestion:
    """A mode suggestion with confidence."""

    mode: str
    confidence: float
    based_on_samples: int
    effectiveness: ModeEffectiveness

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": round(self.confidence, 4),
            "based_on_samples": self.based_on_samples,
            "effectiveness": self.effectiveness.to_dict(),
        }


@dataclass
class StrategyStats:
    """Strategy memory statistics."""

    total_records: int
    unique_domains: int
    unique_keys: int
    total_modes_tracked: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "unique_domains": self.unique_domains,
            "unique_keys": self.unique_keys,
            "total_modes_tracked": self.total_modes_tracked,
        }


# =============================================================================
# Strategy Memory
# =============================================================================


class StrategyMemory:
    """
    Learn and recall effective collaboration strategies.

    Features:
    - Record strategy outcomes (mode, quality, success)
    - Compute mode effectiveness per domain/complexity
    - Suggest best mode based on history
    - Thread-safe, bounded history
    """

    def __init__(self, *, max_records: int = MAX_RECORDS):
        self._max_records = max_records
        self._records: list[StrategyRecord] = []
        # key (domain:complexity) -> mode -> aggregated effectiveness
        self._effectiveness: dict[str, dict[str, ModeEffectiveness]] = defaultdict(dict)
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_strategy(
        self,
        domain: str,
        complexity: str,
        *,
        mode: str,
        quality: float = 0.0,
        success: bool = True,
        duration_ms: float = 0.0,
        agents: list[str] | None = None,
    ) -> StrategyRecord:
        """Record a strategy execution outcome."""
        q = max(0.0, min(1.0, quality))
        record = StrategyRecord(
            domain=domain,
            complexity=complexity,
            mode=mode,
            quality=q,
            success=success,
            duration_ms=duration_ms,
            agents=agents or [],
        )

        with self._lock:
            self._records.append(record)
            while len(self._records) > self._max_records:
                self._records.pop(0)

            # Update effectiveness
            key = record.key
            if mode not in self._effectiveness[key]:
                self._effectiveness[key][mode] = ModeEffectiveness(mode=mode)

            eff = self._effectiveness[key][mode]
            eff.total_uses += 1
            if success:
                eff.successes += 1
            # Running average for quality
            eff.average_quality = (eff.average_quality * (eff.total_uses - 1) + q) / eff.total_uses
            # Running average for duration
            eff.average_duration_ms = (eff.average_duration_ms * (eff.total_uses - 1) + duration_ms) / eff.total_uses

        return record

    # =========================================================================
    # Suggestions
    # =========================================================================

    def suggest_mode(
        self,
        domain: str,
        complexity: str,
        *,
        min_samples: int = MIN_SAMPLES_FOR_SUGGESTION,
    ) -> ModeSuggestion | None:
        """
        Suggest the best mode for a domain/complexity based on history.
        Returns None if insufficient data.
        """
        key = f"{domain}:{complexity}"
        modes = self._effectiveness.get(key, {})

        if not modes:
            return None

        # Filter to modes with enough samples
        candidates = {m: eff for m, eff in modes.items() if eff.total_uses >= min_samples}

        if not candidates:
            return None

        # Pick best by composite score
        best_mode = max(candidates, key=lambda m: candidates[m].score)
        eff = candidates[best_mode]

        # Confidence based on sample size (logistic-ish curve)
        total_samples = eff.total_uses
        confidence = min(1.0, total_samples / (total_samples + min_samples))

        return ModeSuggestion(
            mode=best_mode,
            confidence=confidence,
            based_on_samples=total_samples,
            effectiveness=eff,
        )

    # =========================================================================
    # Analysis
    # =========================================================================

    def get_mode_effectiveness(
        self,
        domain: str,
        complexity: str,
    ) -> list[ModeEffectiveness]:
        """Get effectiveness of all modes for a domain/complexity, sorted by score."""
        key = f"{domain}:{complexity}"
        modes = self._effectiveness.get(key, {})
        return sorted(modes.values(), key=lambda e: e.score, reverse=True)

    def get_all_effectiveness(self) -> dict[str, list[ModeEffectiveness]]:
        """Get effectiveness across all domain/complexity keys."""
        result = {}
        for key, modes in self._effectiveness.items():
            result[key] = sorted(modes.values(), key=lambda e: e.score, reverse=True)
        return result

    def get_domain_summary(self, domain: str) -> dict[str, int]:
        """Get count of records per mode for a domain (across all complexities)."""
        counts: dict[str, int] = {}
        for record in self._records:
            if record.domain == domain:
                counts[record.mode] = counts.get(record.mode, 0) + 1
        return counts

    def list_domains(self) -> list[str]:
        """List all recorded domains."""
        return sorted(set(r.domain for r in self._records))

    def list_keys(self) -> list[str]:
        """List all domain:complexity keys with data."""
        return sorted(self._effectiveness.keys())

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> StrategyStats:
        domains = set(r.domain for r in self._records)
        modes = set()
        for key_modes in self._effectiveness.values():
            modes.update(key_modes.keys())
        return StrategyStats(
            total_records=len(self._records),
            unique_domains=len(domains),
            unique_keys=len(self._effectiveness),
            total_modes_tracked=len(modes),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def record_count(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._effectiveness.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": self.record_count,
            "max_records": self._max_records,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_memory: StrategyMemory | None = None
_memory_lock = threading.Lock()


def get_strategy_memory() -> StrategyMemory:
    """Get or create the global strategy memory."""
    global _memory
    if _memory is None:
        with _memory_lock:
            if _memory is None:
                _memory = StrategyMemory()
    return _memory


def reset_strategy_memory() -> None:
    """Reset the global strategy memory (for testing)."""
    global _memory
    _memory = None
