"""
NEXUS V9.8 DETOX - Headless Mode Smoke Test

This test verifies that NEXUS can run in headless mode without blocking.
It is a smoke check for the DETOX operation, not a formal proof artifact.

Run with:
    python tests/proofs/verify_headless_mode.py

Expected output:
    All tests should pass without any blocking or timeout.

References:
- https://bbc.github.io/cloudfit-public-docs/asyncio/testing.html
- https://docs.python.org/3/library/unittest.mock.html
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Ensure NEXUS root is in path
NEXUS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(NEXUS_ROOT))

# Set headless mode BEFORE any imports
os.environ["NEXUS_INTERACTION_MODE"] = "headless"


def test_1_interaction_provider_headless():
    """Test 1: InteractionProvider returns HeadlessProvider in headless mode."""
    print("\n" + "=" * 60)
    print("TEST 1: InteractionProvider Factory")
    print("=" * 60)

    # Reset provider to pick up env var
    from core.security_pkg.interaction import get_interaction_provider, reset_interaction_provider

    reset_interaction_provider()

    provider = get_interaction_provider()
    print(f"  Provider type: {type(provider).__name__}")
    print(f"  is_interactive: {provider.is_interactive}")

    assert not provider.is_interactive, "Provider should NOT be interactive in headless mode"
    assert type(provider).__name__ == "HeadlessProvider", "Should be HeadlessProvider"

    print("  [PASS] InteractionProvider correctly returns HeadlessProvider")
    return True


def test_2_headless_confirm_no_block():
    """Test 2: HeadlessProvider.confirm() returns immediately without blocking."""
    print("\n" + "=" * 60)
    print("TEST 2: HeadlessProvider.confirm() Non-Blocking")
    print("=" * 60)

    from core.security_pkg.interaction import HeadlessProvider

    provider = HeadlessProvider(strict=False)

    # Measure time for confirm
    start = time.time()

    async def run_confirm():
        return await provider.confirm("This should not block", default=True)

    result = asyncio.get_event_loop().run_until_complete(run_confirm())
    elapsed = time.time() - start

    print(f"  Result: {result}")
    print(f"  Elapsed: {elapsed:.4f}s")

    assert result is True, "Should return default (True)"
    assert elapsed < 0.1, f"Should complete in <0.1s, took {elapsed:.4f}s"

    print("  [PASS] confirm() returns immediately with default")
    return True


def test_3_headless_ask_no_block():
    """Test 3: HeadlessProvider.ask() returns immediately without blocking."""
    print("\n" + "=" * 60)
    print("TEST 3: HeadlessProvider.ask() Non-Blocking")
    print("=" * 60)

    from core.security_pkg.interaction import HeadlessProvider

    provider = HeadlessProvider(strict=False)

    start = time.time()

    async def run_ask():
        return await provider.ask("Enter name", default="Anonymous")

    result = asyncio.get_event_loop().run_until_complete(run_ask())
    elapsed = time.time() - start

    print(f"  Result: '{result}'")
    print(f"  Elapsed: {elapsed:.4f}s")

    assert result == "Anonymous", "Should return default"
    assert elapsed < 0.1, f"Should complete in <0.1s, took {elapsed:.4f}s"

    print("  [PASS] ask() returns immediately with default")
    return True


def test_4_headless_strict_raises():
    """Test 4: HeadlessProvider in strict mode raises on missing default."""
    print("\n" + "=" * 60)
    print("TEST 4: HeadlessProvider Strict Mode")
    print("=" * 60)

    from core.security_pkg.interaction import HeadlessProvider, InteractionRequiredError

    provider = HeadlessProvider(strict=True)

    async def run_strict_ask():
        return await provider.ask("Required input", required=True)

    try:
        asyncio.get_event_loop().run_until_complete(run_strict_ask())
        print("  [FAIL] Should have raised InteractionRequiredError")
        return False
    except InteractionRequiredError as e:
        print(f"  Caught expected error: {e}")
        print("  [PASS] Strict mode raises InteractionRequiredError")
        return True


def test_5_bootstrap_service_headless():
    """Test 5: BootstrapService._confirm_overwrite() works in headless mode."""
    print("\n" + "=" * 60)
    print("TEST 5: BootstrapService Headless Compatibility")
    print("=" * 60)

    from core.infrastructure.bootstrap.service import BootstrapService
    from core.security_pkg.interaction import HeadlessProvider

    # Mock console
    mock_console = MagicMock()

    # Create service with headless provider
    provider = HeadlessProvider(strict=False)
    service = BootstrapService(console=mock_console, interaction=provider)

    # Test _confirm_overwrite (should return False by default in headless)
    start = time.time()
    result = service._confirm_overwrite()
    elapsed = time.time() - start

    print(f"  Result: {result}")
    print(f"  Elapsed: {elapsed:.4f}s")

    assert result is False, "Should return default (False) for destructive action"
    assert elapsed < 0.5, f"Should complete quickly, took {elapsed:.4f}s"

    print("  [PASS] BootstrapService works in headless mode")
    return True


def test_6_budget_service_headless():
    """Test 6: BudgetService._confirm_reset() works in headless mode."""
    print("\n" + "=" * 60)
    print("TEST 6: BudgetService Headless Compatibility")
    print("=" * 60)

    from core.observability.telemetry.service import BudgetService
    from core.security_pkg.interaction import HeadlessProvider

    # Mock console and config
    mock_console = MagicMock()
    mock_config = MagicMock()
    mock_config.budget_daily_limit_usd = 10.0

    # Create service with headless provider
    provider = HeadlessProvider(strict=False)
    service = BudgetService(
        workspace_path=NEXUS_ROOT / "workspace", console=mock_console, config=mock_config, interaction=provider
    )

    # Test _confirm_reset (should return False by default in headless)
    start = time.time()
    result = service._confirm_reset()
    elapsed = time.time() - start

    print(f"  Result: {result}")
    print(f"  Elapsed: {elapsed:.4f}s")

    assert result is False, "Should return default (False) for reset action"
    assert elapsed < 0.5, f"Should complete quickly, took {elapsed:.4f}s"

    print("  [PASS] BudgetService works in headless mode")
    return True


def test_7_user_interaction_headless():
    """Test 7: UserInteractionHandler works in headless mode."""
    print("\n" + "=" * 60)
    print("TEST 7: UserInteractionHandler Headless Compatibility")
    print("=" * 60)

    from core.intelligence.hive_mind.types import BreakpointOption, UserBreakpoint
    from core.intelligence.hive_mind.user_interaction import UserInteractionHandler
    from core.security_pkg.interaction import HeadlessProvider

    # Create handler with headless provider
    provider = HeadlessProvider(strict=False)
    handler = UserInteractionHandler(default_timeout=5, enable_rich=False, auto_accept=False, interaction=provider)

    # Test breakpoint request
    start = time.time()
    response = handler.request_breakpoint_sync(
        breakpoint_type=UserBreakpoint.AFTER_DEBATE,
        context="Test context",
        recommendation="Accept the approach",
        options=[
            BreakpointOption("accept", "Accept", "Proceed", is_recommended=True),
            BreakpointOption("reject", "Reject", "Cancel"),
        ],
    )
    elapsed = time.time() - start

    print(f"  Chosen option: {response.chosen_option}")
    print(f"  Was timeout: {response.was_timeout}")
    print(f"  Elapsed: {elapsed:.4f}s")

    assert response.chosen_option == "accept", "Should choose recommended option"
    assert elapsed < 0.5, f"Should complete quickly, took {elapsed:.4f}s"

    print("  [PASS] UserInteractionHandler works in headless mode")
    return True


def test_8_spinoff_service_no_input():
    """Test 8: SpinoffService has no input() calls (analysis only)."""
    print("\n" + "=" * 60)
    print("TEST 8: SpinoffService Code Analysis")
    print("=" * 60)

    import inspect

    from core.infrastructure.bootstrap.service import SpinoffService

    # Get source code
    source = inspect.getsource(SpinoffService)

    # Check for raw input() calls (not in comments)
    lines = source.split("\n")
    input_calls = []
    for i, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "input(" in line and "provider" not in line.lower():
            input_calls.append((i, line.strip()))

    if input_calls:
        print("  [WARN] Found potential input() calls:")
        for line_no, line in input_calls:
            print(f"    Line {line_no}: {line[:60]}...")
        print("  [FAIL] SpinoffService may have blocking input()")
        return False
    else:
        print("  No raw input() calls found in SpinoffService")
        print("  [PASS] SpinoffService is headless-compatible (no user input)")
        return True


def main():
    """Run all smoke tests."""
    print("\n" + "=" * 60)
    print("   NEXUS V9.8 DETOX - HEADLESS MODE SMOKE TEST")
    print("=" * 60)
    print(f"NEXUS_INTERACTION_MODE = {os.environ.get('NEXUS_INTERACTION_MODE')}")

    tests = [
        test_1_interaction_provider_headless,
        test_2_headless_confirm_no_block,
        test_3_headless_ask_no_block,
        test_4_headless_strict_raises,
        test_5_bootstrap_service_headless,
        test_6_budget_service_headless,
        test_7_user_interaction_headless,
        test_8_spinoff_service_no_input,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append((test.__name__, result))
        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback

            traceback.print_exc()
            results.append((test.__name__, False))

    # Summary
    print("\n" + "=" * 60)
    print("   SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  === HEADLESS MODE VERIFICATION: SUCCESS ===")
        return 0
    else:
        print("\n  === HEADLESS MODE VERIFICATION: FAILED ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
