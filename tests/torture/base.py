"""
Torture Protocol V8 - Base Classes and Fixtures

Provides TortureBase class and common fixtures for all torture scenarios.
"""

import asyncio
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from .metrics_collector import MetricsCollector


@dataclass
class TortureResultV8:
    """Result of a single torture test."""

    scenario: str
    test_id: str
    success: bool
    duration_ms: float
    recovery_attempted: bool = False
    recovery_succeeded: bool = False
    panic_occurred: bool = False
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class TortureBase:
    """
    Base class for Torture Protocol V8.

    Provides workspace setup, result logging, and metrics collection.
    """

    def __init__(self, workspace_name: str = "torture_v8"):
        self.workspace = Path("workspace") / workspace_name
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Create required subdirectories
        (self.workspace / ".nexus" / "sagas").mkdir(parents=True, exist_ok=True)
        (self.workspace / "logs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "agents").mkdir(parents=True, exist_ok=True)

        self.results: list[TortureResultV8] = []
        self.metrics = MetricsCollector()
        self.lock = threading.Lock()

        # Log file
        self.log_file = self.workspace / "logs" / "torture_v8.jsonl"

    @property
    def sagas_dir(self) -> Path:
        """Get saga directory path."""
        return self.workspace / ".nexus" / "sagas"

    def log_result(self, result: TortureResultV8):
        """Thread-safe result logging."""
        with self.lock:
            self.results.append(result)

            # Record to metrics collector
            self.metrics.record_test(
                name=f"{result.scenario}:{result.test_id}",
                success=result.success,
                duration_ms=result.duration_ms,
                recovery_attempted=result.recovery_attempted,
                recovery_succeeded=result.recovery_succeeded,
                panic_occurred=result.panic_occurred,
                error=result.error,
            )

            # Append to JSONL log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.__dict__, default=str) + "\n")

            # Print status
            status = "PASS" if result.success else "FAIL"
            print(f"[{status}] {result.scenario}:{result.test_id} ({result.duration_ms:.1f}ms)")
            if result.error:
                print(f"   ERROR: {result.error[:100]}")

    def run_test(self, scenario: str, test_id: str, test_func, expect_recovery: bool = False) -> TortureResultV8:
        """
        Run a single test and capture result.

        Args:
            scenario: Scenario category (e.g., "saga_crash")
            test_id: Test identifier (e.g., "CR-001")
            test_func: Async or sync test function
            expect_recovery: Whether this test involves recovery

        Returns:
            TortureResultV8 with test outcome
        """
        start = time.time()
        recovery_attempted = False
        recovery_succeeded = False
        panic_occurred = False
        error = None
        success = False

        try:
            # Run test (handle both async and sync)
            if asyncio.iscoroutinefunction(test_func):
                result = asyncio.run(test_func())
            else:
                result = test_func()

            # Check result
            if isinstance(result, dict):
                success = result.get("success", True)
                recovery_attempted = result.get("recovery_attempted", expect_recovery)
                recovery_succeeded = result.get("recovery_succeeded", False)
                error = result.get("error")
            else:
                success = bool(result) if result is not None else True

        except SystemExit:
            panic_occurred = True
            error = "SystemExit (PANIC)"
        except KeyboardInterrupt:
            panic_occurred = True
            error = "KeyboardInterrupt (PANIC)"
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)}"
            # Check if this was expected failure for recovery test
            if expect_recovery:
                recovery_attempted = True
                # Try recovery if test provides it
                success = False

        duration_ms = (time.time() - start) * 1000

        result = TortureResultV8(
            scenario=scenario,
            test_id=test_id,
            success=success,
            duration_ms=duration_ms,
            recovery_attempted=recovery_attempted,
            recovery_succeeded=recovery_succeeded,
            panic_occurred=panic_occurred,
            error=error,
        )

        self.log_result(result)
        return result

    def generate_report(self):
        """Generate and print metrics report."""
        rates = self.metrics.calculate_rates()

        print("\n" + "=" * 50)
        print("NEXUS V8.2.0d TORTURE PROTOCOL REPORT")
        print("=" * 50)
        print(f"Total Tests:          {rates['total_tests']}")
        print(f"Success Rate:         {rates['success_rate']:.1f}% (target: >95%)")
        print(f"Recovery Rate:        {rates['recovery_rate']:.1f}% (target: >90%)")
        print(f"Panic Rate:           {rates['panic_rate']:.1f}% (target: <1%)")
        print(f"Hot-Swap Effect:      {rates['hot_swap_effectiveness']:.1f}% (target: >80%)")
        print("=" * 50)

        # Write full metrics to file
        metrics_file = self.workspace / "logs" / "torture_metrics.jsonl"
        self.metrics.to_jsonl(metrics_file)
        print(f"\nMetrics saved to: {metrics_file}")

        return rates

    def assert_targets(
        self,
        success_target: float = 95.0,
        recovery_target: float = 90.0,
        panic_target: float = 1.0,
        hot_swap_target: float = 80.0,
    ):
        """Assert metrics meet targets."""
        self.metrics.assert_targets(
            success_target=success_target,
            recovery_target=recovery_target,
            panic_target=panic_target,
            hot_swap_target=hot_swap_target,
        )

    def cleanup(self):
        """Clean up workspace after tests."""
        import shutil

        if self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)


# ============================================================================
# Pytest Fixtures
# ============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "torture: marks test as torture test")
    config.addinivalue_line("markers", "torture_saga: marks test as saga-specific torture")
    config.addinivalue_line("markers", "torture_hive: marks test as HiveMind integration torture")
    config.addinivalue_line("markers", "torture_concurrency: marks test as concurrency torture")
    config.addinivalue_line("markers", "torture_slow: marks test as slow torture (>30s)")
    config.addinivalue_line("markers", "nightly: marks test for nightly CI only")


# Fixture functions for pytest
def create_torture_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace with proper structure."""
    workspace = tmp_path / "torture_workspace"
    workspace.mkdir()
    (workspace / ".nexus" / "sagas").mkdir(parents=True)
    (workspace / "logs").mkdir()
    (workspace / "agents").mkdir()
    return workspace


def create_saga_dir(workspace: Path) -> Path:
    """Get saga directory path from workspace."""
    return workspace / ".nexus" / "sagas"
