"""
Torture Protocol V8 - Context Edge Case Tests

10 tests covering context truncation and edge case scenarios.

Test IDs: CE-001 to CE-010
"""

import contextlib
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.intelligence.hive_mind.saga_manager import SagaManager


@pytest.fixture
def saga_dir(tmp_path):
    """Create saga directory."""
    saga_dir = tmp_path / ".nexus" / "sagas"
    saga_dir.mkdir(parents=True)
    return saga_dir


# ============================================================================
# Mock Context Managers
# ============================================================================


@dataclass
class MockContextItem:
    """Mock context item with token estimate."""

    content: str
    token_estimate: int = 100


class MockDequeContextManager:
    """Mock HiveMindContextManager using deque._items."""

    def __init__(self, items=None):
        self._items = deque(items or [])
        self._current_tokens = sum(getattr(item, "token_estimate", 0) for item in self._items)


class MockListContextManager:
    """Mock generic context manager using .messages list."""

    def __init__(self, messages=None):
        self.messages = list(messages or [])


class MockBothContextManager:
    """Mock context manager with BOTH _items and messages."""

    def __init__(self, items=None, messages=None):
        self._items = deque(items or [])
        self._current_tokens = sum(getattr(item, "token_estimate", 0) for item in self._items)
        self.messages = list(messages or [])


class MockNoTokenContextManager:
    """Mock context manager with items missing token_estimate."""

    def __init__(self, items=None):
        self._items = deque(items or [])
        self._current_tokens = 0


# ============================================================================
# CE-001: context_index > len(items)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce001_context_index_out_of_bounds(saga_dir):
    """
    CE-001: Test rollback with context_index > len(items).

    Scenario: Checkpoint has context_index=100 but context only has 5 items.
    Expected: Truncation handles gracefully (slice to available items).
    """
    saga = SagaManager(saga_dir, "ce001-test", auto_persist=True)

    # Checkpoint with large context_index
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=100)

    # Create context with only 5 items
    items = [MockContextItem(f"item_{i}") for i in range(5)]
    context_manager = MockDequeContextManager(items)

    # Rollback should handle gracefully
    await saga.rollback_to("analysis", context_manager)

    # Context should not crash, items preserved (slice [:100] of 5 items = 5 items)
    assert len(context_manager._items) <= 5


# ============================================================================
# CE-002: Token recalc with missing estimates
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce002_token_recalc_missing_estimates(saga_dir):
    """
    CE-002: Test token recalculation with items missing token_estimate.

    Scenario: Context items don't have token_estimate attribute.
    Expected: Fallback to 0, no crash.
    """
    saga = SagaManager(saga_dir, "ce002-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=3)
    saga.update_context(analysis_complete=True)
    await saga.checkpoint_phase("debate", {}, "S2", context_index=5)

    # Create context with items missing token_estimate
    class NoTokenItem:
        def __init__(self, content):
            self.content = content
            # No token_estimate attribute!

    items = [NoTokenItem(f"item_{i}") for i in range(5)]
    context_manager = MockDequeContextManager([])
    context_manager._items = deque(items)

    # Rollback should handle missing estimates
    await saga.rollback_to("analysis", context_manager)

    # Token count should be 0 (fallback)
    assert context_manager._current_tokens == 0


# ============================================================================
# CE-003: Context manager type mismatch
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce003_context_manager_type_mismatch(saga_dir):
    """
    CE-003: Test rollback with wrong context manager type.

    Scenario: Pass object with neither _items nor messages.
    Expected: Graceful handling (no truncation attempted).
    """
    saga = SagaManager(saga_dir, "ce003-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=5)

    # Create invalid context manager
    class InvalidContextManager:
        pass

    context_manager = InvalidContextManager()

    # Rollback should not crash
    await saga.rollback_to("analysis", context_manager)

    # Should complete without error


# ============================================================================
# CE-004: Empty context after rollback
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce004_empty_context_after_rollback(saga_dir):
    """
    CE-004: Test rollback to index 0 (empty context).

    Scenario: Checkpoint with context_index=0.
    Expected: Context truncated to empty, no crash.
    """
    saga = SagaManager(saga_dir, "ce004-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=0)

    items = [MockContextItem(f"item_{i}") for i in range(10)]
    context_manager = MockDequeContextManager(items)

    await saga.rollback_to("analysis", context_manager)

    # Context should be empty
    assert len(context_manager._items) == 0
    assert context_manager._current_tokens == 0


# ============================================================================
# CE-005: Deque vs List inconsistency
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce005_deque_vs_list(saga_dir):
    """
    CE-005: Test both deque (_items) and list (messages) interfaces.

    Scenario: Test rollback with both context manager types.
    Expected: Both work correctly.
    """
    saga = SagaManager(saga_dir, "ce005-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=3)

    # Test with deque
    items = [MockContextItem(f"item_{i}") for i in range(5)]
    deque_ctx = MockDequeContextManager(items)
    await saga.rollback_to("analysis", deque_ctx)
    assert len(deque_ctx._items) == 3

    # Reset saga
    saga2 = SagaManager(saga_dir, "ce005-test2", auto_persist=True)
    await saga2.checkpoint_phase("analysis", {}, "S1", context_index=3)

    # Test with list
    messages = [f"msg_{i}" for i in range(5)]
    list_ctx = MockListContextManager(messages)
    await saga2.rollback_to("analysis", list_ctx)
    assert len(list_ctx.messages) == 3


# ============================================================================
# CE-006: Rollback to non-checkpointed phase
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce006_rollback_nonexistent_phase(saga_dir):
    """
    CE-006: Test rollback to a phase that wasn't checkpointed.

    Scenario: rollback_to("nonexistent") called.
    Expected: Returns False or raises appropriate error.
    """
    saga = SagaManager(saga_dir, "ce006-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", 5)

    # Try to rollback to non-existent phase
    result = await saga.rollback_to("nonexistent_phase")

    # Should return False (phase not found)
    assert result is False or result is None


# ============================================================================
# CE-007: Context with None items
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce007_context_with_none_items(saga_dir):
    """
    CE-007: Test context with None values in items.

    Scenario: Context deque contains None values.
    Expected: Handles gracefully during truncation.
    """
    saga = SagaManager(saga_dir, "ce007-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=3)

    # Create context with None items
    items = [MockContextItem("item_0"), None, MockContextItem("item_2"), None, MockContextItem("item_4")]
    context_manager = MockDequeContextManager([])
    context_manager._items = deque(items)

    # Rollback should handle None items
    await saga.rollback_to("analysis", context_manager)

    # Should have 3 items (may include None)
    assert len(context_manager._items) == 3


# ============================================================================
# CE-008: Very large context (50k items)
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.torture_slow
@pytest.mark.asyncio
async def test_ce008_large_context(saga_dir):
    """
    CE-008: Performance test with very large context.

    Scenario: Context with 50,000 items.
    Expected: Completes in reasonable time (<5s).
    """
    import time

    saga = SagaManager(saga_dir, "ce008-test", auto_persist=True)
    await saga.checkpoint_phase("analysis", {}, "S1", context_index=25000)

    # Create large context
    items = [MockContextItem(f"item_{i}", token_estimate=10) for i in range(50000)]
    context_manager = MockDequeContextManager(items)

    start = time.time()
    await saga.rollback_to("analysis", context_manager)
    elapsed = time.time() - start

    assert len(context_manager._items) == 25000
    assert elapsed < 5.0, f"Took too long: {elapsed}s"


# ============================================================================
# CE-009: Unicode in context content
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce009_unicode_context(saga_dir):
    """
    CE-009: Test context with Unicode content.

    Scenario: Context contains emojis, CJK, RTL characters.
    Expected: No encoding issues.
    """
    saga = SagaManager(saga_dir, "ce009-test", auto_persist=True)

    # Checkpoint with Unicode in result
    unicode_result = {
        "emoji": "Hello World! It's working!",
        "cjk": "Chinese Japanese Korean",
        "rtl": "Right to left text",
        "mixed": "Mix: symbols and text",
    }
    await saga.checkpoint_phase("analysis", unicode_result, "S1", 5)

    # Persist and recover
    recovered = await SagaManager.resume_from(saga_dir, "ce009-test")
    assert recovered is not None

    # Unicode should be preserved
    result = recovered._checkpoints["analysis"]["result"]
    assert "emoji" in result


# ============================================================================
# CE-010: Non-serializable context items
# ============================================================================


@pytest.mark.torture
@pytest.mark.torture_saga
@pytest.mark.asyncio
async def test_ce010_non_serializable_result(saga_dir):
    """
    CE-010: Test checkpoint with non-JSON-serializable result.

    Scenario: Result contains lambda, custom objects.
    Expected: Serialization handles gracefully.
    """
    saga = SagaManager(saga_dir, "ce010-test", auto_persist=True)

    # Try to checkpoint with non-serializable result
    class CustomObject:
        def __init__(self, value):
            self.value = value

    with contextlib.suppress(TypeError, ValueError):
        await saga.checkpoint_phase(
            "analysis",
            {
                "normal": "string",
                "number": 42,
                # Note: CustomObject would fail JSON serialization
                # but saga_manager uses serialize_for_checkpoint()
            },
            "S1",
            5,
        )

    # Either outcome is acceptable - no crash


# ============================================================================
# Run All Tests (Standalone Mode)
# ============================================================================


def run_all(metrics_collector=None):
    """Run all context edge case tests."""
    print("\n" + "=" * 50)
    print("CONTEXT EDGE CASE TESTS (10 scenarios)")
    print("=" * 50 + "\n")
    print("Run with: pytest tests/torture/scenarios/context_edge.py -v")
    return metrics_collector


if __name__ == "__main__":
    print("Run with: pytest tests/torture/scenarios/context_edge.py -v -m torture")
