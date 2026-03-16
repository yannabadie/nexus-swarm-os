"""
Torture Protocol V8 - Metrics Collector

Tracks test results and calculates success/recovery/panic rates.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ScenarioMetrics:
    """Metrics for a single test scenario."""

    name: str
    success: bool
    duration_ms: float
    recovery_attempted: bool = False
    recovery_succeeded: bool = False
    panic_occurred: bool = False
    error_message: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "recovery_attempted": self.recovery_attempted,
            "recovery_succeeded": self.recovery_succeeded,
            "panic_occurred": self.panic_occurred,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


@dataclass
class MetricsCollector:
    """
    Collects and calculates torture test metrics.

    Target Metrics (from ROADMAP):
    - Success rate: >95%
    - Recovery rate (post-error): >90%
    - Panic rate: <1%
    - Hot-Swap effectiveness: >80%
    """

    scenarios: list[ScenarioMetrics] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)

    def record_test(
        self,
        name: str,
        success: bool,
        duration_ms: float,
        recovery_attempted: bool = False,
        recovery_succeeded: bool = False,
        panic_occurred: bool = False,
        error: str | None = None,
    ):
        """
        Record a test result.

        Args:
            name: Test name (e.g., "saga_crash:CR-001")
            success: Whether test passed
            duration_ms: Test duration in milliseconds
            recovery_attempted: Whether recovery was attempted
            recovery_succeeded: Whether recovery succeeded
            panic_occurred: Whether panic (SystemExit/KeyboardInterrupt) occurred
            error: Error message if any
        """
        self.scenarios.append(
            ScenarioMetrics(
                name=name,
                success=success,
                duration_ms=duration_ms,
                recovery_attempted=recovery_attempted,
                recovery_succeeded=recovery_succeeded,
                panic_occurred=panic_occurred,
                error_message=error,
            )
        )

    def calculate_rates(self) -> dict[str, Any]:
        """
        Calculate success, recovery, and panic rates.

        Returns:
            Dict with:
            - total_tests: int
            - success_rate: float (0-100)
            - recovery_rate: float (0-100)
            - panic_rate: float (0-100)
            - hot_swap_effectiveness: float (0-100)
            - avg_duration_ms: float
        """
        total = len(self.scenarios)
        if total == 0:
            return {
                "total_tests": 0,
                "success_rate": 0.0,
                "recovery_rate": 100.0,  # No failures = 100% recovery
                "panic_rate": 0.0,
                "hot_swap_effectiveness": 100.0,
                "avg_duration_ms": 0.0,
            }

        # Success rate
        success_count = sum(1 for s in self.scenarios if s.success)
        success_rate = (success_count / total) * 100

        # Recovery rate (of those that attempted recovery)
        recovery_attempts = [s for s in self.scenarios if s.recovery_attempted]
        if recovery_attempts:
            recovery_success = sum(1 for s in recovery_attempts if s.recovery_succeeded)
            recovery_rate = (recovery_success / len(recovery_attempts)) * 100
        else:
            recovery_rate = 100.0  # No recovery needed = 100%

        # Panic rate
        panic_count = sum(1 for s in self.scenarios if s.panic_occurred)
        panic_rate = (panic_count / total) * 100

        # Hot-swap effectiveness
        hot_swap_rate = self._calculate_hot_swap_rate()

        # Average duration
        avg_duration = sum(s.duration_ms for s in self.scenarios) / total

        return {
            "total_tests": total,
            "success_rate": round(success_rate, 2),
            "recovery_rate": round(recovery_rate, 2),
            "panic_rate": round(panic_rate, 2),
            "hot_swap_effectiveness": round(hot_swap_rate, 2),
            "avg_duration_ms": round(avg_duration, 2),
            "passed": success_count,
            "failed": total - success_count,
            "panics": panic_count,
        }

    def _calculate_hot_swap_rate(self) -> float:
        """Calculate hot-swap effectiveness from relevant tests."""
        hot_swap_scenarios = [
            s for s in self.scenarios if "hot_swap" in s.name.lower() or "lead_swap" in s.name.lower()
        ]
        if not hot_swap_scenarios:
            return 100.0  # No hot-swap tests = assume 100%

        success = sum(1 for s in hot_swap_scenarios if s.success)
        return (success / len(hot_swap_scenarios)) * 100

    def get_failures(self) -> list[ScenarioMetrics]:
        """Get list of failed scenarios."""
        return [s for s in self.scenarios if not s.success]

    def get_panics(self) -> list[ScenarioMetrics]:
        """Get list of panic scenarios."""
        return [s for s in self.scenarios if s.panic_occurred]

    def get_slowest(self, n: int = 5) -> list[ScenarioMetrics]:
        """Get N slowest scenarios."""
        sorted_scenarios = sorted(self.scenarios, key=lambda s: s.duration_ms, reverse=True)
        return sorted_scenarios[:n]

    def to_jsonl(self, filepath: Path):
        """
        Write metrics to JSONL file.

        Format:
        - One JSON object per line for each scenario
        - Final line is summary with "_summary" key
        """
        with open(filepath, "w", encoding="utf-8") as f:
            for scenario in self.scenarios:
                f.write(json.dumps(scenario.to_dict()) + "\n")

            # Write summary as final line
            summary = self.calculate_rates()
            summary["_type"] = "summary"
            summary["start_time"] = self.start_time.isoformat()
            summary["end_time"] = datetime.now().isoformat()
            f.write(json.dumps(summary) + "\n")

    def to_dict(self) -> dict[str, Any]:
        """Convert full metrics to dictionary."""
        return {
            "rates": self.calculate_rates(),
            "scenarios": [s.to_dict() for s in self.scenarios],
            "failures": [s.to_dict() for s in self.get_failures()],
            "panics": [s.to_dict() for s in self.get_panics()],
            "slowest": [s.to_dict() for s in self.get_slowest()],
        }

    def summary(self) -> str:
        """Generate human-readable summary."""
        rates = self.calculate_rates()
        lines = [
            "=" * 50,
            "TORTURE PROTOCOL V8 METRICS SUMMARY",
            "=" * 50,
            f"Total Tests:      {rates['total_tests']}",
            f"Passed:           {rates['passed']}",
            f"Failed:           {rates['failed']}",
            f"Panics:           {rates['panics']}",
            "",
            f"Success Rate:     {rates['success_rate']:.1f}%",
            f"Recovery Rate:    {rates['recovery_rate']:.1f}%",
            f"Panic Rate:       {rates['panic_rate']:.1f}%",
            f"Hot-Swap Effect:  {rates['hot_swap_effectiveness']:.1f}%",
            f"Avg Duration:     {rates['avg_duration_ms']:.1f}ms",
            "=" * 50,
        ]
        return "\n".join(lines)

    def assert_targets(
        self,
        success_target: float = 95.0,
        recovery_target: float = 90.0,
        panic_target: float = 1.0,
        hot_swap_target: float = 80.0,
    ):
        """
        Assert metrics meet targets.

        Raises:
            AssertionError: If any target is not met
        """
        rates = self.calculate_rates()

        errors = []

        if rates["success_rate"] < success_target:
            errors.append(f"Success rate {rates['success_rate']:.1f}% < target {success_target}%")

        if rates["recovery_rate"] < recovery_target:
            errors.append(f"Recovery rate {rates['recovery_rate']:.1f}% < target {recovery_target}%")

        if rates["panic_rate"] > panic_target:
            errors.append(f"Panic rate {rates['panic_rate']:.1f}% > target {panic_target}%")

        if rates["hot_swap_effectiveness"] < hot_swap_target:
            errors.append(f"Hot-swap effectiveness {rates['hot_swap_effectiveness']:.1f}% < target {hot_swap_target}%")

        if errors:
            # Print failures for debugging
            print("\n--- FAILED SCENARIOS ---")
            for failure in self.get_failures()[:10]:  # Show first 10
                print(f"  {failure.name}: {failure.error_message}")

            raise AssertionError("Torture Protocol targets not met:\n" + "\n".join(f"  - {e}" for e in errors))
