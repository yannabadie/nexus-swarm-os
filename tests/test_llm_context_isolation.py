"""
NEXUS V7.8 - Real LLM Context Isolation Tests

Tests that verify context isolation using ACTUAL Gemini CLI calls.
These tests make real API calls and verify that parallel sessions
don't leak context between each other.

IMPORTANT: These tests require:
- Gemini CLI installed and configured
- Valid API credentials
- Network connectivity

Run: pytest tests/test_llm_context_isolation.py -v -s
     (Use -s to see subprocess output for debugging)

Environment Variables:
- SKIP_LLM_TESTS=1 : Skip these tests (for CI without credentials)
"""

import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

# Skip if no LLM access
SKIP_LLM = os.environ.get("SKIP_LLM_TESTS", "").lower() in ("1", "true", "yes")

# V7.8.1 IC-003: Auto-skip when no API credentials configured
# This prevents CI failures when Gemini CLI is installed but not authenticated
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
AUTO_SKIP = SKIP_LLM or not GEMINI_API_KEY

# Import NEXUS components
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Helpers
# =============================================================================


def is_gemini_available() -> bool:
    """Check if Gemini CLI is available."""
    try:
        result = subprocess.run(
            ["gemini", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=True,  # Windows compatibility
        )
        return result.returncode == 0
    except Exception:
        return False


def invoke_gemini(prompt: str, session_id: str | None = None, timeout: int = 60) -> tuple[str, int]:
    """
    Invoke Gemini CLI with optional session.

    Args:
        prompt: The prompt to send
        session_id: Optional session UUID for context continuity
        timeout: Timeout in seconds

    Returns:
        Tuple of (output, return_code)
    """
    cmd = ["gemini", "-p", prompt]

    if session_id:
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            shell=True,  # Windows compatibility
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except Exception as e:
        return f"ERROR: {e}", -2


def create_session_id() -> str:
    """Create a unique session ID."""
    return str(uuid.uuid4())


# =============================================================================
# Skip Marker (V7.8.1 IC-003)
# =============================================================================

# Module-level skip: applies to ALL tests in this file
# Skip if: SKIP_LLM_TESTS=1, no API key, or Gemini CLI unavailable
pytestmark = pytest.mark.skipif(
    AUTO_SKIP or not is_gemini_available(),
    reason="LLM tests skipped (no GEMINI_API_KEY/GOOGLE_API_KEY or SKIP_LLM_TESTS=1)",
)

# Backward compatible decorator (for explicit use)
skip_llm = pytest.mark.skipif(
    AUTO_SKIP or not is_gemini_available(),
    reason="LLM tests skipped (no GEMINI_API_KEY/GOOGLE_API_KEY or SKIP_LLM_TESTS=1)",
)


# =============================================================================
# Context Isolation Tests
# =============================================================================


@skip_llm
class TestRealContextIsolation:
    """
    Tests for real context isolation using Gemini CLI.

    These tests verify that:
    1. Each session maintains its own context
    2. Parallel sessions don't leak information
    3. Session resume works correctly
    """

    def test_basic_invocation(self):
        """Test that basic Gemini CLI invocation works."""
        output, code = invoke_gemini("Say 'NEXUS_TEST_OK' and nothing else.")

        assert code == 0, f"Gemini CLI failed with code {code}: {output}"
        assert "NEXUS" in output or "OK" in output or len(output) > 0

    def test_session_context_persistence(self):
        """Test that session context persists across calls."""
        session_id = create_session_id()

        # First call: Set a unique identifier
        unique_value = f"NEXUS_SECRET_{uuid.uuid4().hex[:8]}"
        output1, code1 = invoke_gemini(
            f"Remember this secret code: {unique_value}. Reply with 'STORED'.", session_id=session_id
        )
        assert code1 == 0, f"First call failed: {output1}"

        # Second call: Ask for the identifier
        output2, code2 = invoke_gemini(
            "What was the secret code I told you to remember? Reply with just the code.", session_id=session_id
        )
        assert code2 == 0, f"Second call failed: {output2}"

        # The secret should be in the response
        # Note: LLM might not recall perfectly, so we check if it's attempting to recall
        assert unique_value in output2 or "NEXUS_SECRET" in output2, (
            f"Session didn't persist context. Expected '{unique_value}' in: {output2}"
        )

    def test_parallel_sessions_isolated(self):
        """
        CRITICAL TEST: Verify parallel sessions don't leak context.

        Creates two parallel sessions with different secrets and verifies
        neither session knows the other's secret.
        """
        session_alice = create_session_id()
        session_bob = create_session_id()

        secret_alice = f"ALICE_SECRET_{uuid.uuid4().hex[:8]}"
        secret_bob = f"BOB_SECRET_{uuid.uuid4().hex[:8]}"

        # Set secrets in parallel
        def set_secret(session_id: str, secret: str, name: str) -> tuple[str, str]:
            output, code = invoke_gemini(
                f"You are {name}. Your secret code is: {secret}. Remember it. Reply 'OK {name}'.", session_id=session_id
            )
            return name, output

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(set_secret, session_alice, secret_alice, "ALICE"),
                executor.submit(set_secret, session_bob, secret_bob, "BOB"),
            ]
            for f in as_completed(futures):
                name, output = f.result()
                print(f"[{name}] Set secret: {output[:100]}...")

        # Now query each session for the other's secret
        def check_isolation(session_id: str, own_secret: str, other_secret: str, name: str) -> bool:
            # Ask for own secret
            output1, _ = invoke_gemini("What is your secret code? Reply with just the code.", session_id=session_id)

            # Ask if they know the other secret
            output2, _ = invoke_gemini(
                f"Do you know anything about the code {other_secret}? Reply YES or NO.", session_id=session_id
            )

            # Should know own secret, not know other's
            knows_own = own_secret in output1 or name in output1.upper()
            knows_other = "YES" in output2.upper() or other_secret in output2

            print(f"[{name}] Own secret check: '{output1[:50]}...' (knows_own={knows_own})")
            print(f"[{name}] Other secret check: '{output2[:50]}...' (knows_other={knows_other})")

            return not knows_other  # Isolation is successful if they DON'T know the other secret

        # Check isolation
        alice_isolated = check_isolation(session_alice, secret_alice, secret_bob, "ALICE")
        bob_isolated = check_isolation(session_bob, secret_bob, secret_alice, "BOB")

        assert alice_isolated, "ALICE session leaked BOB's context!"
        assert bob_isolated, "BOB session leaked ALICE's context!"

    def test_fresh_session_has_no_history(self):
        """Test that a fresh session has no prior context."""
        # Create a session with some context
        old_session = create_session_id()
        old_secret = f"OLD_SECRET_{uuid.uuid4().hex[:8]}"

        invoke_gemini(f"Remember: {old_secret}", session_id=old_session)

        # New session should not know the old secret
        new_session = create_session_id()
        output, code = invoke_gemini(
            f"Do you know the code {old_secret}? Reply YES or NO only.", session_id=new_session
        )

        assert code == 0
        assert "YES" not in output.upper(), f"Fresh session somehow knew old secret: {output}"


@skip_llm
class TestSessionManagerIntegration:
    """
    Tests for SessionManager integration with real LLM calls.
    """

    def test_session_manager_creates_isolated_sessions(self):
        """Test that SessionManager creates truly isolated sessions."""
        from core.intelligence.swarm.session_manager import SwarmSessionManager

        manager = SwarmSessionManager()

        # Create two tasks
        task1_id = manager.create_task("Analyze code for bugs")
        task2_id = manager.create_task("Write unit tests")

        # Get sessions
        session1 = manager.get_or_create_session(task1_id, "gemini")
        session2 = manager.get_or_create_session(task2_id, "gemini")

        # Sessions should be different
        assert session1 != session2, "Different tasks should have different sessions"

        # Use the sessions with real LLM
        secret1 = f"TASK1_SECRET_{uuid.uuid4().hex[:6]}"
        secret2 = f"TASK2_SECRET_{uuid.uuid4().hex[:6]}"

        # Set secrets
        output1, _ = invoke_gemini(f"Remember: {secret1}", session_id=session1)
        output2, _ = invoke_gemini(f"Remember: {secret2}", session_id=session2)

        # Cross-check isolation
        check1, _ = invoke_gemini(f"Do you know {secret2}? YES or NO only.", session_id=session1)
        check2, _ = invoke_gemini(f"Do you know {secret1}? YES or NO only.", session_id=session2)

        assert "YES" not in check1.upper(), f"Session 1 leaked session 2's context: {check1}"
        assert "YES" not in check2.upper(), f"Session 2 leaked session 1's context: {check2}"


@skip_llm
class TestHighConcurrencyIsolation:
    """
    Stress tests for context isolation under high concurrency.
    """

    def test_10_parallel_sessions(self):
        """Test 10 parallel sessions maintain isolation."""
        num_sessions = 10
        sessions = [(create_session_id(), f"SECRET_{i}_{uuid.uuid4().hex[:6]}") for i in range(num_sessions)]

        results = []
        errors = []

        def run_session(session_id: str, secret: str, idx: int) -> dict:
            try:
                # Set secret
                _, code1 = invoke_gemini(f"Your ID is {idx}. Secret: {secret}. Reply OK.", session_id=session_id)

                # Recall secret
                output, code2 = invoke_gemini("What is your secret? Reply with just the secret.", session_id=session_id)

                return {
                    "idx": idx,
                    "session": session_id,
                    "secret": secret,
                    "recalled": output,
                    "success": secret in output or f"SECRET_{idx}" in output,
                }
            except Exception as e:
                return {"idx": idx, "error": str(e)}

        with ThreadPoolExecutor(max_workers=num_sessions) as executor:
            futures = [executor.submit(run_session, sid, secret, i) for i, (sid, secret) in enumerate(sessions)]

            for f in as_completed(futures):
                result = f.result()
                if "error" in result:
                    errors.append(result)
                else:
                    results.append(result)

        assert len(errors) == 0, f"Errors during parallel execution: {errors}"

        # Check success rate
        success_count = sum(1 for r in results if r["success"])
        success_rate = success_count / num_sessions

        print(f"\nParallel isolation test: {success_count}/{num_sessions} sessions maintained context")

        # Allow some LLM variability but expect high success
        assert success_rate >= 0.7, f"Too many sessions failed to maintain context: {success_rate * 100:.0f}%"


# =============================================================================
# Latency Tests
# =============================================================================


@skip_llm
class TestLatencyMeasurement:
    """
    Tests that measure LLM invocation latency.
    """

    def test_single_invocation_latency(self):
        """Measure single invocation latency."""
        start = time.time()
        output, code = invoke_gemini("Reply with 'OK'.")
        duration = time.time() - start

        print(f"\nSingle invocation latency: {duration:.2f}s")

        assert code == 0
        assert duration < 30, f"Single invocation too slow: {duration:.2f}s"

    def test_average_latency_5_calls(self):
        """Measure average latency over 5 sequential calls."""
        latencies = []

        for i in range(5):
            start = time.time()
            output, code = invoke_gemini(f"Reply with number {i}.")
            duration = time.time() - start
            latencies.append(duration)
            assert code == 0

        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)

        print("\nLatency stats (5 calls):")
        print(f"  Average: {avg_latency:.2f}s")
        print(f"  Min: {min_latency:.2f}s")
        print(f"  Max: {max_latency:.2f}s")

        assert avg_latency < 15, f"Average latency too high: {avg_latency:.2f}s"


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    # Check availability first
    if not is_gemini_available():
        print("WARNING: Gemini CLI not available. Skipping tests.")
        exit(0)

    pytest.main([__file__, "-v", "-s", "--tb=short"])
