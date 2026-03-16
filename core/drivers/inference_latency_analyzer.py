"""
Inference Latency Analyzer - Track and analyze LLM inference latency.

V12.4 COGNITIVE BOOST

Tracks per-model inference latency, time-to-first-token (TTFT), throughput
(tokens/second), and anomaly detection. Provides model-level profiles for
intelligent routing decisions and performance diagnostics.

Usage:
    from core.drivers.inference_latency_analyzer import get_latency_analyzer

    analyzer = get_latency_analyzer()

    # Record a sample
    sample = analyzer.record_sample(
        model_id="claude-opus-4-5",
        latency_ms=1250.0,
        prompt_tokens=500,
        response_tokens=1200,
        ttft_ms=320.0,
        task_type="brainstorm",
    )

    # Query profiles
    profile = analyzer.get_model_profile("claude-opus-4-5")
    print(profile.avg_latency_ms)       # Average latency
    print(profile.avg_tokens_per_second) # Throughput

    # Get fastest models
    fastest = analyzer.get_fastest_models(limit=3)

    # Detect anomalies
    anomalies = analyzer.get_anomalies(limit=10)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_SAMPLES = 50000
LATENCY_ANOMALY_THRESHOLD_MS = 30000.0  # 30s — above this is anomalous


# =============================================================================
# Types
# =============================================================================


@dataclass
class LatencySample:
    """A single inference call measurement."""

    sample_id: str = ""
    model_id: str = ""
    prompt_tokens: int = 0
    response_tokens: int = 0
    latency_ms: float = 0.0
    ttft_ms: float = 0.0
    timestamp: str = ""
    task_type: str = ""
    success: bool = True
    error: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    @property
    def is_anomalous(self) -> bool:
        """Whether this sample exceeds the anomaly threshold."""
        return self.latency_ms > LATENCY_ANOMALY_THRESHOLD_MS

    @property
    def tokens_per_second(self) -> float:
        """Throughput: response tokens per second."""
        if self.latency_ms > 0:
            return self.response_tokens / (self.latency_ms / 1000.0)
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "model_id": self.model_id,
            "prompt_tokens": self.prompt_tokens,
            "response_tokens": self.response_tokens,
            "latency_ms": round(self.latency_ms, 2),
            "ttft_ms": round(self.ttft_ms, 2),
            "timestamp": self.timestamp,
            "task_type": self.task_type,
            "success": self.success,
            "error": self.error,
            "is_anomalous": self.is_anomalous,
            "tokens_per_second": round(self.tokens_per_second, 2),
        }


@dataclass
class ModelLatencyProfile:
    """Aggregated latency statistics for a single model."""

    model_id: str = ""
    sample_count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_response_tokens: int = 0
    anomaly_count: int = 0

    @property
    def avg_latency_ms(self) -> float:
        """Average latency across all samples."""
        if self.sample_count == 0:
            return 0.0
        return self.total_latency_ms / self.sample_count

    @property
    def avg_tokens_per_second(self) -> float:
        """Average throughput: total response tokens / total time."""
        if self.total_latency_ms > 0:
            return self.total_response_tokens / (self.total_latency_ms / 1000.0)
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "sample_count": self.sample_count,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "min_latency_ms": round(self.min_latency_ms, 2),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_response_tokens": self.total_response_tokens,
            "anomaly_count": self.anomaly_count,
            "avg_tokens_per_second": round(self.avg_tokens_per_second, 2),
        }


@dataclass
class AnalyzerStats:
    """Overall latency analyzer statistics."""

    total_samples: int = 0
    unique_models: int = 0
    total_anomalies: int = 0
    overall_avg_latency_ms: float = 0.0
    fastest_model: str = ""
    slowest_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "unique_models": self.unique_models,
            "total_anomalies": self.total_anomalies,
            "overall_avg_latency_ms": round(self.overall_avg_latency_ms, 2),
            "fastest_model": self.fastest_model,
            "slowest_model": self.slowest_model,
        }


# =============================================================================
# Inference Latency Analyzer
# =============================================================================


class InferenceLatencyAnalyzer:
    """
    Tracks and analyzes LLM inference latency across models.

    Features:
    - Per-sample recording with auto-generated IDs
    - Per-model latency profiles (min/max/avg, throughput, anomalies)
    - Anomaly detection (samples exceeding threshold)
    - Fastest/slowest model ranking
    - Bounded history with FIFO eviction
    - Thread-safe with non-reentrant lock
    """

    def __init__(self, max_samples: int = MAX_SAMPLES):
        self._samples: list[LatencySample] = []
        self._profiles: dict[str, ModelLatencyProfile] = {}
        self._max_samples = max_samples
        self._lock = threading.Lock()
        self._counter = 0

    # =========================================================================
    # Record
    # =========================================================================

    def record_sample(
        self,
        model_id: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        response_tokens: int = 0,
        ttft_ms: float = 0.0,
        task_type: str = "",
        success: bool = True,
        error: str = "",
    ) -> LatencySample:
        """
        Record a single inference latency measurement.

        Args:
            model_id: Model identifier (e.g. "claude-opus-4-5")
            latency_ms: Total wall-clock time in milliseconds
            prompt_tokens: Number of prompt/input tokens
            response_tokens: Number of response/output tokens
            ttft_ms: Time to first token in milliseconds
            task_type: Task category (e.g. "brainstorm", "tool_exec")
            success: Whether the inference call succeeded
            error: Error message if failed

        Returns:
            The recorded LatencySample
        """
        with self._lock:
            sample_id = f"ls_{self._counter:06d}"
            self._counter += 1

            sample = LatencySample(
                sample_id=sample_id,
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                response_tokens=response_tokens,
                latency_ms=latency_ms,
                ttft_ms=ttft_ms,
                task_type=task_type,
                success=success,
                error=error,
            )

            # Update model profile
            profile = self._profiles.get(model_id)
            if profile is None:
                profile = ModelLatencyProfile(
                    model_id=model_id,
                    sample_count=1,
                    total_latency_ms=latency_ms,
                    min_latency_ms=latency_ms,
                    max_latency_ms=latency_ms,
                    total_prompt_tokens=prompt_tokens,
                    total_response_tokens=response_tokens,
                    anomaly_count=1 if sample.is_anomalous else 0,
                )
                self._profiles[model_id] = profile
            else:
                profile.sample_count += 1
                profile.total_latency_ms += latency_ms
                profile.total_prompt_tokens += prompt_tokens
                profile.total_response_tokens += response_tokens
                if latency_ms < profile.min_latency_ms:
                    profile.min_latency_ms = latency_ms
                if latency_ms > profile.max_latency_ms:
                    profile.max_latency_ms = latency_ms
                if sample.is_anomalous:
                    profile.anomaly_count += 1

            # FIFO eviction
            if len(self._samples) >= self._max_samples:
                self._samples.pop(0)

            self._samples.append(sample)
            return sample

    # =========================================================================
    # Queries
    # =========================================================================

    def get_model_profile(self, model_id: str) -> ModelLatencyProfile | None:
        """
        Get the latency profile for a specific model.

        Args:
            model_id: Model identifier

        Returns:
            ModelLatencyProfile or None if no samples recorded
        """
        with self._lock:
            return self._profiles.get(model_id)

    def get_all_profiles(self) -> list[ModelLatencyProfile]:
        """
        Get all model profiles sorted by sample count (descending).

        Returns:
            List of ModelLatencyProfile sorted by sample_count desc
        """
        with self._lock:
            profiles = list(self._profiles.values())
        return sorted(profiles, key=lambda p: p.sample_count, reverse=True)

    def get_fastest_models(self, limit: int = 5) -> list[ModelLatencyProfile]:
        """
        Get models ranked by average latency (ascending).

        Only includes models with at least one sample.

        Args:
            limit: Maximum number of models to return

        Returns:
            List of ModelLatencyProfile sorted by avg_latency_ms ascending
        """
        with self._lock:
            profiles = [p for p in self._profiles.values() if p.sample_count > 0]
        sorted_profiles = sorted(profiles, key=lambda p: p.avg_latency_ms)
        return sorted_profiles[:limit]

    def get_anomalies(self, limit: int = 20) -> list[LatencySample]:
        """
        Get anomalous samples sorted by latency (descending).

        Args:
            limit: Maximum number of anomalies to return

        Returns:
            List of LatencySample where is_anomalous is True
        """
        with self._lock:
            anomalies = [s for s in self._samples if s.is_anomalous]
        sorted_anomalies = sorted(
            anomalies,
            key=lambda s: s.latency_ms,
            reverse=True,
        )
        return sorted_anomalies[:limit]

    def get_recent_samples(
        self,
        limit: int = 20,
        model_id: str = "",
    ) -> list[LatencySample]:
        """
        Get the most recent samples, optionally filtered by model.

        Args:
            limit: Maximum number of samples to return
            model_id: If non-empty, only return samples for this model

        Returns:
            List of LatencySample (most recent last)
        """
        with self._lock:
            if model_id:
                filtered = [s for s in self._samples if s.model_id == model_id]
            else:
                filtered = list(self._samples)
        return filtered[-limit:]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> AnalyzerStats:
        """Get overall analyzer statistics."""
        with self._lock:
            total_samples = len(self._samples)
            unique_models = len(self._profiles)
            total_anomalies = sum(p.anomaly_count for p in self._profiles.values())

            # Overall average latency
            total_latency = sum(p.total_latency_ms for p in self._profiles.values())
            total_count = sum(p.sample_count for p in self._profiles.values())
            overall_avg = total_latency / total_count if total_count > 0 else 0.0

            # Fastest / slowest by average latency
            fastest = ""
            slowest = ""
            profiles_with_samples = [p for p in self._profiles.values() if p.sample_count > 0]
            if profiles_with_samples:
                fastest_profile = min(
                    profiles_with_samples,
                    key=lambda p: p.avg_latency_ms,
                )
                slowest_profile = max(
                    profiles_with_samples,
                    key=lambda p: p.avg_latency_ms,
                )
                fastest = fastest_profile.model_id
                slowest = slowest_profile.model_id

        return AnalyzerStats(
            total_samples=total_samples,
            unique_models=unique_models,
            total_anomalies=total_anomalies,
            overall_avg_latency_ms=overall_avg,
            fastest_model=fastest,
            slowest_model=slowest,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def sample_count(self) -> int:
        """Current number of stored samples."""
        return len(self._samples)

    def clear(self) -> None:
        """Clear all samples and profiles."""
        with self._lock:
            self._samples.clear()
            self._profiles.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """Export analyzer state for diagnostics."""
        # CRITICAL: call get_stats() BEFORE acquiring self._lock to avoid
        # deadlock — get_stats() acquires the lock internally, and
        # threading.Lock is non-reentrant.
        stats = self.get_stats()
        with self._lock:
            return {
                "max_samples": self._max_samples,
                "sample_count": len(self._samples),
                "model_count": len(self._profiles),
                "counter": self._counter,
                "profiles": {mid: p.to_dict() for mid, p in self._profiles.items()},
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_analyzer: InferenceLatencyAnalyzer | None = None
_analyzer_lock = threading.Lock()


def get_latency_analyzer() -> InferenceLatencyAnalyzer:
    """Get or create the global inference latency analyzer singleton."""
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = InferenceLatencyAnalyzer()
    return _analyzer


def reset_latency_analyzer() -> None:
    """Reset the global latency analyzer (for testing)."""
    global _analyzer
    _analyzer = None
