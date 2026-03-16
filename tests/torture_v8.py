#!/usr/bin/env python3
"""
NEXUS V8.2.0d - Torture Protocol V8

Comprehensive stress testing for SagaManager + HiveMind integration.
75+ tests across 5 scenario categories.

Usage:
    # Run all torture tests via pytest
    pytest tests/torture_v8.py -m torture -v --tb=short

    # Run specific categories
    pytest tests/torture_v8.py -m torture_saga -v      # Saga tests only
    pytest tests/torture_v8.py -m torture_hive -v      # HiveMind tests only
    pytest tests/torture_v8.py -m torture_slow -v      # Slow tests only

    # Run as standalone
    python tests/torture_v8.py

Target Metrics:
    - Success Rate:     >95%
    - Recovery Rate:    >90%
    - Panic Rate:       <1%
    - Hot-Swap Effect:  >80%
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.torture.base import TortureBase, TortureResultV8
from tests.torture.metrics_collector import MetricsCollector

# Import scenario modules
from tests.torture.scenarios import (
    compensation,
    context_edge,
    hive_integration,
    saga_concurrency,
    saga_crash,
)


class TortureProtocolV8(TortureBase):
    """
    Main coordinator for Torture Protocol V8.

    Runs all scenario categories and generates comprehensive report.
    """

    VERSION = "8.2.0d"

    # Target metrics from ROADMAP
    TARGETS = {"success_rate": 95.0, "recovery_rate": 90.0, "panic_rate": 1.0, "hot_swap_effectiveness": 80.0}

    def __init__(self, workspace_name: str = "torture_v8"):
        """Initialize Torture Protocol."""
        super().__init__(workspace_name)
        self.start_time: float | None = None
        self.end_time: float | None = None
        self._scenario_results: dict[str, list[TortureResultV8]] = {}

    def run_all(self, include_slow: bool = False) -> MetricsCollector:
        """
        Run all torture test scenarios.

        Args:
            include_slow: Include slow/stress tests (default: False)

        Returns:
            MetricsCollector with all results
        """
        self.start_time = time.time()

        print("\n" + "=" * 60)
        print(f" TORTURE PROTOCOL V{self.VERSION}")
        print(f" Started: {datetime.now().isoformat()}")
        print("=" * 60)

        # Run each scenario category
        categories = [
            ("Saga Crash Recovery", saga_crash, 15),
            ("Saga Concurrency", saga_concurrency, 12),
            ("Context Edge Cases", context_edge, 10),
            ("Compensation Failures", compensation, 8),
            ("HiveMind Integration", hive_integration, 30),
        ]

        for name, module, expected_count in categories:
            print(f"\n>>> Running: {name} ({expected_count} tests)")
            module.run_all(self.metrics)
            self._scenario_results[name] = []

        self.end_time = time.time()

        # Generate report
        self.generate_report()

        # Assert targets
        try:
            self.assert_targets()
            print("\n[PASS] All target metrics met!")
        except AssertionError as e:
            print(f"\n[FAIL] Target metrics not met: {e}")

        return self.metrics

    def generate_report(self):
        """Generate comprehensive torture report."""
        if not self.end_time:
            self.end_time = time.time()

        duration = self.end_time - (self.start_time or self.end_time)
        rates = self.metrics.calculate_rates()

        print("\n" + "=" * 60)
        print(" TORTURE PROTOCOL REPORT")
        print("=" * 60)

        print(f"\nVersion:          {self.VERSION}")
        print(f"Duration:         {duration:.2f}s")
        print(f"Total Tests:      {len(self.metrics.scenarios)}")

        print("\n--- METRICS ---")
        print(f"Success Rate:     {rates['success_rate']:.1f}% (target: >{self.TARGETS['success_rate']}%)")
        print(f"Recovery Rate:    {rates['recovery_rate']:.1f}% (target: >{self.TARGETS['recovery_rate']}%)")
        print(f"Panic Rate:       {rates['panic_rate']:.1f}% (target: <{self.TARGETS['panic_rate']}%)")
        print(
            f"Hot-Swap Effect:  {rates['hot_swap_effectiveness']:.1f}% (target: >{self.TARGETS['hot_swap_effectiveness']}%)"
        )

        # Status indicators
        print("\n--- STATUS ---")
        success_ok = rates["success_rate"] >= self.TARGETS["success_rate"]
        recovery_ok = rates["recovery_rate"] >= self.TARGETS["recovery_rate"]
        panic_ok = rates["panic_rate"] <= self.TARGETS["panic_rate"]
        hotswap_ok = rates["hot_swap_effectiveness"] >= self.TARGETS["hot_swap_effectiveness"]

        print(f"Success Rate:     {'PASS' if success_ok else 'FAIL'}")
        print(f"Recovery Rate:    {'PASS' if recovery_ok else 'FAIL'}")
        print(f"Panic Rate:       {'PASS' if panic_ok else 'FAIL'}")
        print(f"Hot-Swap Effect:  {'PASS' if hotswap_ok else 'FAIL'}")

        # Failed tests summary
        failed = [s for s in self.metrics.scenarios if not s.success]
        if failed:
            print(f"\n--- FAILED TESTS ({len(failed)}) ---")
            for scenario in failed[:10]:  # Show first 10
                error_msg = scenario.error_message[:50] if scenario.error_message else "Unknown"
                print(f"  - {scenario.name}: {error_msg}")
            if len(failed) > 10:
                print(f"  ... and {len(failed) - 10} more")

        print("\n" + "=" * 60)

        # Save report to workspace
        report_path = self.workspace / "reports" / f"torture_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, "w") as f:
            f.write(f"TORTURE PROTOCOL V{self.VERSION} REPORT\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write(f"Duration: {duration:.2f}s\n")
            f.write(f"Total Tests: {len(self.metrics.scenarios)}\n\n")
            f.write("METRICS:\n")
            f.write(f"  Success Rate: {rates['success_rate']:.1f}%\n")
            f.write(f"  Recovery Rate: {rates['recovery_rate']:.1f}%\n")
            f.write(f"  Panic Rate: {rates['panic_rate']:.1f}%\n")
            f.write(f"  Hot-Swap Effect: {rates['hot_swap_effectiveness']:.1f}%\n")

        print(f"\nReport saved to: {report_path}")


# ============================================================================
# Pytest Integration
# ============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "torture: mark as torture protocol test")
    config.addinivalue_line("markers", "torture_saga: mark as saga-specific torture test")
    config.addinivalue_line("markers", "torture_hive: mark as HiveMind torture test")
    config.addinivalue_line("markers", "torture_slow: mark as slow torture test (>5s)")


# Re-export all tests for pytest discovery
from tests.torture.scenarios.compensation import *  # noqa: E402, F403  # after conftest setup
from tests.torture.scenarios.context_edge import *  # noqa: E402, F403
from tests.torture.scenarios.hive_integration import *  # noqa: E402, F403
from tests.torture.scenarios.saga_concurrency import *  # noqa: E402, F403
from tests.torture.scenarios.saga_crash import *  # noqa: E402, F403

# ============================================================================
# Standalone Execution
# ============================================================================


def main():
    """Main entry point for standalone execution."""
    parser = argparse.ArgumentParser(description="NEXUS Torture Protocol V8 - Stress Testing Suite")
    parser.add_argument("--include-slow", action="store_true", help="Include slow/stress tests")
    parser.add_argument("--output", type=str, default=None, help="Output path for JSONL metrics")
    parser.add_argument(
        "--category",
        type=str,
        choices=["saga", "hive", "context", "compensation", "all"],
        default="all",
        help="Test category to run",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(" NEXUS TORTURE PROTOCOL V8")
    print(" Stress Testing for SagaManager + HiveMind")
    print("=" * 60)

    if args.category != "all":
        print("\nNote: Category filtering requires pytest.")
        print(f"Run: pytest tests/torture_v8.py -m torture_{args.category} -v")
        return

    print("\nFor full test execution, use pytest:")
    print("  pytest tests/torture_v8.py -m torture -v --tb=short")
    print("\nFor specific categories:")
    print("  pytest tests/torture_v8.py -m torture_saga -v")
    print("  pytest tests/torture_v8.py -m torture_hive -v")
    print("\nFor slow tests:")
    print("  pytest tests/torture_v8.py -m 'torture and torture_slow' -v")

    # Quick sanity check
    print("\n--- Quick Module Sanity Check ---")

    try:
        from tests.torture.base import TortureBase  # noqa: F401  # availability check

        print("[OK] torture.base")
    except ImportError as e:
        print(f"[FAIL] torture.base: {e}")

    try:
        from tests.torture.metrics_collector import MetricsCollector  # noqa: F401  # availability check

        print("[OK] torture.metrics_collector")
    except ImportError as e:
        print(f"[FAIL] torture.metrics_collector: {e}")

    try:
        from tests.torture.chaos_injectors import CrashInjector  # noqa: F401  # availability check

        print("[OK] torture.chaos_injectors")
    except ImportError as e:
        print(f"[FAIL] torture.chaos_injectors: {e}")

    try:
        from tests.torture.scenarios.saga_crash import (
            test_cr001_partial_checkpoint_write,  # noqa: F401  # availability check
        )

        print("[OK] torture.scenarios.saga_crash (15 tests)")
    except ImportError as e:
        print(f"[FAIL] torture.scenarios.saga_crash: {e}")

    try:
        from tests.torture.scenarios.saga_concurrency import (
            test_cc001_simultaneous_checkpoints,  # noqa: F401  # availability check
        )

        print("[OK] torture.scenarios.saga_concurrency (12 tests)")
    except ImportError as e:
        print(f"[FAIL] torture.scenarios.saga_concurrency: {e}")

    try:
        from tests.torture.scenarios.context_edge import (
            test_ce001_context_index_out_of_bounds,  # noqa: F401  # availability check
        )

        print("[OK] torture.scenarios.context_edge (10 tests)")
    except ImportError as e:
        print(f"[FAIL] torture.scenarios.context_edge: {e}")

    try:
        from tests.torture.scenarios.compensation import (
            test_cf001_compensation_exception,  # noqa: F401  # availability check
        )

        print("[OK] torture.scenarios.compensation (8 tests)")
    except ImportError as e:
        print(f"[FAIL] torture.scenarios.compensation: {e}")

    try:
        from tests.torture.scenarios.hive_integration import (
            test_hm001_crash_between_checkpoint_and_context,  # noqa: F401  # availability check
        )

        print("[OK] torture.scenarios.hive_integration (30 tests)")
    except ImportError as e:
        print(f"[FAIL] torture.scenarios.hive_integration: {e}")

    print("\n--- Summary ---")
    print("Total test scenarios: 75")
    print("Categories: 5 (saga_crash, saga_concurrency, context_edge, compensation, hive_integration)")
    print("\nRun full suite with: pytest tests/torture_v8.py -m torture -v")


if __name__ == "__main__":
    main()
