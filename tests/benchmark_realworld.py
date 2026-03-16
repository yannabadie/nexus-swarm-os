#!/usr/bin/env python3
"""
NEXUS V7.8 - Real-World DUAL-BRAIN Benchmark Suite

Tests NEXUS with ACTUAL LLM calls - no mocks.
Tests BOTH Gemini AND Claude for complete Hybrid Swarm validation.

Tests:
1. Gemini CLI Basic Invocation & Isolation
2. Claude CLI Basic Invocation & Isolation
3. Parallel Session Isolation (CRITICAL)
4. SYMBIOSIS Test - Gemini + Claude simultaneous
5. Latency Profiling
6. Context Window Stress

Run: python tests/benchmark_realworld.py

WARNING: This benchmark makes real API calls and costs money!
"""

import json
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

# NEXUS imports
from core.intelligence.swarm.session_manager import SwarmSessionManager
from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskComplexity

# =============================================================================
# Configuration
# =============================================================================

WORKSPACE = Path("workspace/benchmark_realworld")
WORKSPACE.mkdir(parents=True, exist_ok=True)

LOG_FILE = WORKSPACE / f"realworld_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

# Timeouts
GEMINI_TIMEOUT = 60  # seconds per call
TOTAL_TIMEOUT = 600  # 10 minutes max


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TestResult:
    name: str
    category: str
    passed: bool
    duration: float
    details: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self):
        return {
            "name": self.name,
            "category": self.category,
            "passed": self.passed,
            "duration": round(self.duration, 3),
            "details": self.details,
            "error": self.error,
            "timestamp": datetime.now().isoformat(),
        }


# =============================================================================
# Helpers
# =============================================================================


def log_result(result: TestResult):
    """Log result to JSONL file."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")

    status = "[PASS]" if result.passed else "[FAIL]"
    print(f"  {status} {result.name} ({result.duration:.2f}s)")
    if result.error:
        print(f"         Error: {result.error[:100]}")


def invoke_gemini(prompt: str, session_id: str | None = None, timeout: int = GEMINI_TIMEOUT) -> tuple[str, int, float]:
    """
    Invoke Gemini CLI.

    Returns: (output, return_code, duration)
    """
    cmd = ["gemini", "-p", prompt]
    if session_id:
        cmd.extend(["--resume", session_id])

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            shell=True,  # Windows
        )
        duration = time.time() - start
        return result.stdout.strip(), result.returncode, duration
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1, time.time() - start
    except Exception as e:
        return f"ERROR: {e}", -2, time.time() - start


def generate_session_id() -> str:
    return str(uuid.uuid4())


def invoke_claude(prompt: str, timeout: int = GEMINI_TIMEOUT) -> tuple[str, int, float]:
    """
    Invoke Claude CLI.

    Note: Claude CLI doesn't have session resumption like Gemini.
    Each invocation is independent.

    Returns: (output, return_code, duration)
    """
    # Claude uses -p for prompt
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            shell=True,  # Windows
        )
        duration = time.time() - start
        return result.stdout.strip(), result.returncode, duration
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1, time.time() - start
    except Exception as e:
        return f"ERROR: {e}", -2, time.time() - start


def is_claude_available() -> bool:
    """Check if Claude CLI is available."""
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10, shell=True)
        return result.returncode == 0
    except Exception:
        return False


def is_gemini_available() -> bool:
    """Check if Gemini CLI is available."""
    try:
        result = subprocess.run(["gemini", "--version"], capture_output=True, text=True, timeout=10, shell=True)
        return result.returncode == 0
    except Exception:
        return False


# =============================================================================
# Test Suite
# =============================================================================


class RealWorldBenchmark:
    def __init__(self):
        self.results: list[TestResult] = []
        self.session_manager = SwarmSessionManager(WORKSPACE)
        self.task_analyzer = TaskAnalyzer()

        # Check CLI availability
        self.gemini_available = is_gemini_available()
        self.claude_available = is_claude_available()

    def run_all(self):
        print("=" * 70)
        print("NEXUS V7.8 - DUAL-BRAIN REAL-WORLD BENCHMARK")
        print("=" * 70)
        print(f"Log: {LOG_FILE}")
        print(f"Gemini CLI: {'available' if self.gemini_available else 'NOT FOUND'}")
        print(f"Claude CLI: {'available' if self.claude_available else 'NOT FOUND'}")
        print("WARNING: Real API calls - this costs money!")
        print("=" * 70)

        start = time.time()

        # Layer 1: Basic Connectivity - GEMINI
        print("\n[LAYER 1] GEMINI CONNECTIVITY")
        print("-" * 40)
        if self.gemini_available:
            self.test_gemini_basic()
            self.test_gemini_json_output()
        else:
            print("  [SKIP] Gemini CLI not available")

        # Layer 1b: Basic Connectivity - CLAUDE
        print("\n[LAYER 1b] CLAUDE CONNECTIVITY")
        print("-" * 40)
        if self.claude_available:
            self.test_claude_basic()
        else:
            print("  [SKIP] Claude CLI not available")

        # Layer 2: Session Isolation - GEMINI
        print("\n[LAYER 2] GEMINI SESSION ISOLATION (CRITICAL)")
        print("-" * 40)
        if self.gemini_available:
            self.test_gemini_parallel_isolation()
        else:
            print("  [SKIP] Gemini CLI not available")

        # Layer 2b: Session Isolation - CLAUDE
        print("\n[LAYER 2b] CLAUDE ISOLATION")
        print("-" * 40)
        if self.claude_available:
            self.test_claude_parallel_isolation()
        else:
            print("  [SKIP] Claude CLI not available")

        # Layer 2c: SYMBIOSIS - Both models simultaneously
        print("\n[LAYER 2c] SYMBIOSIS TEST (GEMINI + CLAUDE)")
        print("-" * 40)
        if self.gemini_available and self.claude_available:
            self.test_symbiosis()
        else:
            print("  [SKIP] Both CLIs required for symbiosis test")

        # Layer 3: Task Analysis Integration
        print("\n[LAYER 3] TASK ANALYSIS")
        print("-" * 40)
        self.test_real_task_analysis()

        # Layer 4: Latency Profiling
        print("\n[LAYER 4] LATENCY PROFILING")
        print("-" * 40)
        self.test_latency_profile()

        # Layer 5: Stress Tests
        print("\n[LAYER 5] STRESS TESTS")
        print("-" * 40)
        self.test_concurrent_sessions()

        # Summary
        total_duration = time.time() - start
        self.print_summary(total_duration)

    def test_gemini_basic(self):
        """Test basic Gemini CLI connectivity."""
        start = time.time()

        output, code, duration = invoke_gemini("Reply with exactly: NEXUS_OK")

        passed = code == 0 and len(output) > 0

        result = TestResult(
            name="gemini_basic_connectivity",
            category="connectivity",
            passed=passed,
            duration=time.time() - start,
            details={"output_length": len(output), "return_code": code},
            error=output[:200] if not passed else None,
        )
        self.results.append(result)
        log_result(result)

    def test_gemini_json_output(self):
        """Test Gemini can output valid JSON."""
        start = time.time()

        prompt = 'Return a JSON object with keys "status" and "value". Example: {"status": "ok", "value": 42}'
        output, code, duration = invoke_gemini(prompt)

        # Try to extract JSON from response
        passed = False
        json_found = None
        try:
            # Look for JSON in output
            import re

            json_match = re.search(r"\{[^}]+\}", output)
            if json_match:
                json_found = json.loads(json_match.group())
                passed = "status" in json_found or "value" in json_found
        except Exception:
            pass

        result = TestResult(
            name="gemini_json_output",
            category="gemini_connectivity",
            passed=passed,
            duration=time.time() - start,
            details={"json_found": json_found is not None, "output_preview": output[:100]},
            error=None if passed else "Could not extract valid JSON",
        )
        self.results.append(result)
        log_result(result)

    def test_claude_basic(self):
        """Test basic Claude CLI connectivity."""
        start = time.time()

        output, code, duration = invoke_claude("Reply with exactly: NEXUS_CLAUDE_OK")

        passed = code == 0 and len(output) > 0

        result = TestResult(
            name="claude_basic_connectivity",
            category="claude_connectivity",
            passed=passed,
            duration=time.time() - start,
            details={"output_length": len(output), "return_code": code, "output_preview": output[:100]},
            error=output[:200] if not passed else None,
        )
        self.results.append(result)
        log_result(result)

    def test_gemini_parallel_isolation(self):
        """
        Test Gemini parallel session isolation.

        Creates 2 independent Gemini invocations with different secrets.
        Since Gemini CLI doesn't maintain state between invocations without
        explicit session resume, this tests that parallel calls don't interfere.
        """
        start = time.time()

        secret_a = f"GEMINI_A_{uuid.uuid4().hex[:6]}"
        secret_b = f"GEMINI_B_{uuid.uuid4().hex[:6]}"

        results_detail = {}

        def ask_gemini(secret, name):
            """Ask Gemini to identify a secret and check for contamination."""
            prompt = f"I am {name}. My secret code is {secret}. Repeat my name and secret code only."
            output, code, _ = invoke_gemini(prompt)
            return {
                "name": name,
                "secret": secret,
                "output": output[:200],
                "contains_own_secret": secret in output,
                "code": code,
            }

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(ask_gemini, secret_a, "ALPHA"), executor.submit(ask_gemini, secret_b, "BRAVO")]
            for f in as_completed(futures):
                res = f.result()
                results_detail[res["name"]] = res

        # Check for cross-contamination
        alpha = results_detail.get("ALPHA", {})
        bravo = results_detail.get("BRAVO", {})

        # Isolation passes if neither output contains the other's secret
        alpha_contaminated = secret_b in alpha.get("output", "")
        bravo_contaminated = secret_a in bravo.get("output", "")

        passed = not alpha_contaminated and not bravo_contaminated

        result = TestResult(
            name="gemini_parallel_isolation",
            category="gemini_isolation",
            passed=passed,
            duration=time.time() - start,
            details={
                "alpha": alpha,
                "bravo": bravo,
                "alpha_contaminated": alpha_contaminated,
                "bravo_contaminated": bravo_contaminated,
            },
            error=None if passed else "Cross-contamination detected between Gemini sessions!",
        )
        self.results.append(result)
        log_result(result)

    def test_claude_parallel_isolation(self):
        """
        Test Claude parallel session isolation.

        Creates 2 independent Claude invocations with different secrets.
        Verifies no cross-contamination between parallel Claude calls.
        """
        start = time.time()

        secret_a = f"CLAUDE_RED_{uuid.uuid4().hex[:6]}"
        secret_b = f"CLAUDE_BLUE_{uuid.uuid4().hex[:6]}"

        results_detail = {}

        def ask_claude(secret, name):
            """Ask Claude to identify a secret and check for contamination."""
            prompt = f"I am {name}. My secret code is {secret}. Repeat my name and secret code only, nothing else."
            output, code, _ = invoke_claude(prompt)
            return {
                "name": name,
                "secret": secret,
                "output": output[:200],
                "contains_own_secret": secret in output,
                "code": code,
            }

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(ask_claude, secret_a, "RED"), executor.submit(ask_claude, secret_b, "BLUE")]
            for f in as_completed(futures):
                res = f.result()
                results_detail[res["name"]] = res

        # Check for cross-contamination
        red = results_detail.get("RED", {})
        blue = results_detail.get("BLUE", {})

        # Isolation passes if neither output contains the other's secret
        red_contaminated = secret_b in red.get("output", "")
        blue_contaminated = secret_a in blue.get("output", "")

        passed = not red_contaminated and not blue_contaminated

        result = TestResult(
            name="claude_parallel_isolation",
            category="claude_isolation",
            passed=passed,
            duration=time.time() - start,
            details={
                "red": red,
                "blue": blue,
                "red_contaminated": red_contaminated,
                "blue_contaminated": blue_contaminated,
            },
            error=None if passed else "Cross-contamination detected between Claude sessions!",
        )
        self.results.append(result)
        log_result(result)

    def test_symbiosis(self):
        """
        SYMBIOSIS TEST: Verify Gemini and Claude don't cross-contaminate.

        This is the DUAL-BRAIN test - both models run simultaneously
        with different secrets and must maintain isolation.
        """
        start = time.time()

        gemini_secret = f"GEMINI_1234_{uuid.uuid4().hex[:4]}"
        claude_secret = f"CLAUDE_9876_{uuid.uuid4().hex[:4]}"

        results_detail = {}

        def invoke_model(model_name, secret, invoke_fn):
            """Invoke a model and check for cross-contamination."""
            prompt = f"You are {model_name}. Your secret code is: {secret}. State your name and secret code."
            output, code, duration = invoke_fn(prompt)

            # Check for the OTHER model's secret in output
            other_secret = claude_secret if model_name == "GEMINI" else gemini_secret

            return {
                "model": model_name,
                "own_secret": secret,
                "other_secret": other_secret,
                "output": output[:300],
                "contains_own": secret in output,
                "contains_other": other_secret in output,
                "code": code,
                "duration": duration,
            }

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(invoke_model, "GEMINI", gemini_secret, invoke_gemini),
                executor.submit(invoke_model, "CLAUDE", claude_secret, invoke_claude),
            ]
            for f in as_completed(futures):
                res = f.result()
                results_detail[res["model"]] = res

        gemini_res = results_detail.get("GEMINI", {})
        claude_res = results_detail.get("CLAUDE", {})

        # CRITICAL: Neither should know the other's secret
        gemini_leaked = gemini_res.get("contains_other", False)
        claude_leaked = claude_res.get("contains_other", False)

        passed = not gemini_leaked and not claude_leaked

        result = TestResult(
            name="symbiosis_dual_brain",
            category="symbiosis",
            passed=passed,
            duration=time.time() - start,
            details={
                "gemini": gemini_res,
                "claude": claude_res,
                "gemini_leaked_claude_secret": gemini_leaked,
                "claude_leaked_gemini_secret": claude_leaked,
            },
            error=None if passed else "CRITICAL: Cross-model context bleeding detected!",
        )
        self.results.append(result)
        log_result(result)

        if not passed:
            print("         *** CRITICAL: Dual-brain context bleeding! ***")

    def test_session_context_persistence(self):
        """Test that session context persists across calls."""
        start = time.time()

        session_id = generate_session_id()
        secret = f"NEXUS_SECRET_{uuid.uuid4().hex[:8]}"

        # Store secret
        output1, code1, _ = invoke_gemini(f"Remember this code: {secret}. Reply 'STORED'.", session_id=session_id)

        # Recall secret
        output2, code2, _ = invoke_gemini(
            "What was the code I asked you to remember? Reply with just the code.", session_id=session_id
        )

        # Check if secret was recalled
        passed = secret in output2 or "NEXUS_SECRET" in output2

        result = TestResult(
            name="session_context_persistence",
            category="session_isolation",
            passed=passed,
            duration=time.time() - start,
            details={
                "secret": secret,
                "store_response": output1[:50],
                "recall_response": output2[:100],
                "secret_found": passed,
            },
            error=None if passed else f"Secret not recalled. Got: {output2[:100]}",
        )
        self.results.append(result)
        log_result(result)

    def test_parallel_session_isolation(self):
        """
        CRITICAL TEST: Verify parallel sessions don't leak context.

        Creates 2 sessions with different secrets simultaneously,
        then verifies neither knows the other's secret.
        """
        start = time.time()

        session_a = generate_session_id()
        session_b = generate_session_id()

        secret_a = f"ALPHA_{uuid.uuid4().hex[:6]}"
        secret_b = f"BRAVO_{uuid.uuid4().hex[:6]}"

        # Set secrets in parallel
        def set_secret(session_id, secret, name):
            output, code, duration = invoke_gemini(
                f"You are {name}. Your secret is: {secret}. Reply 'OK {name}'.", session_id=session_id
            )
            return name, output, code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(set_secret, session_a, secret_a, "ALPHA"),
                executor.submit(set_secret, session_b, secret_b, "BRAVO"),
            ]
            [f.result() for f in as_completed(futures)]

        # Check cross-contamination
        def check_isolation(session_id, own_secret, other_secret, name):
            # Ask about own secret
            output1, _, _ = invoke_gemini("What is your secret? Reply with just the secret.", session_id=session_id)

            # Ask about other's secret
            output2, _, _ = invoke_gemini(
                f"Do you know anything about {other_secret}? Reply YES or NO only.", session_id=session_id
            )

            knows_own = own_secret in output1 or name in output1
            knows_other = "YES" in output2.upper() and other_secret not in output2

            return {
                "name": name,
                "knows_own": knows_own,
                "knows_other": knows_other,
                "own_response": output1[:50],
                "other_response": output2[:50],
            }

        check_a = check_isolation(session_a, secret_a, secret_b, "ALPHA")
        check_b = check_isolation(session_b, secret_b, secret_a, "BRAVO")

        # Isolation is successful if neither knows the other's secret
        passed = not check_a["knows_other"] and not check_b["knows_other"]

        result = TestResult(
            name="parallel_session_isolation",
            category="session_isolation",
            passed=passed,
            duration=time.time() - start,
            details={"alpha": check_a, "bravo": check_b, "isolation_maintained": passed},
            error=None if passed else "Context bleeding detected!",
        )
        self.results.append(result)
        log_result(result)

        if not passed:
            print("         *** CRITICAL: Context bleeding detected! ***")

    def test_real_task_analysis(self):
        """Test TaskAnalyzer with Gemini-augmented analysis."""
        start = time.time()

        test_cases = [
            ("hello", TaskComplexity.TRIVIAL),
            ("Fix the bug in auth.py line 42", TaskComplexity.SIMPLE),
            ("Implement OAuth2 authentication with refresh tokens", TaskComplexity.MODERATE),
            ("Design a microservices architecture for e-commerce with CQRS", TaskComplexity.COMPLEX),
        ]

        results_detail = []
        correct = 0

        for task_input, expected in test_cases:
            analysis = self.task_analyzer.analyze(task_input)
            actual = analysis.complexity

            # Allow 1 level tolerance (SIMPLE vs MODERATE is OK)
            complexity_order = [
                TaskComplexity.TRIVIAL,
                TaskComplexity.SIMPLE,
                TaskComplexity.MODERATE,
                TaskComplexity.COMPLEX,
                TaskComplexity.EXPERT,
            ]
            expected_idx = complexity_order.index(expected)
            actual_idx = complexity_order.index(actual)

            is_close = abs(expected_idx - actual_idx) <= 1
            if is_close:
                correct += 1

            results_detail.append(
                {"input": task_input[:40], "expected": expected.value, "actual": actual.value, "close_enough": is_close}
            )

        accuracy = correct / len(test_cases)
        passed = accuracy >= 0.75  # 75% tolerance

        result = TestResult(
            name="task_analysis_accuracy",
            category="task_analysis",
            passed=passed,
            duration=time.time() - start,
            details={
                "accuracy": f"{accuracy * 100:.0f}%",
                "correct": correct,
                "total": len(test_cases),
                "results": results_detail,
            },
            error=None if passed else f"Accuracy too low: {accuracy * 100:.0f}%",
        )
        self.results.append(result)
        log_result(result)

    def test_latency_profile(self):
        """Profile Gemini CLI latency over multiple calls."""
        start = time.time()

        latencies = []
        for i in range(5):
            _, code, duration = invoke_gemini(f"Reply with number: {i}")
            if code == 0:
                latencies.append(duration)

        if latencies:
            avg = sum(latencies) / len(latencies)
            min_lat = min(latencies)
            max_lat = max(latencies)
            passed = avg < 15  # Average under 15 seconds
        else:
            avg = min_lat = max_lat = 0
            passed = False

        result = TestResult(
            name="latency_profile",
            category="performance",
            passed=passed,
            duration=time.time() - start,
            details={
                "samples": len(latencies),
                "avg_seconds": round(avg, 2),
                "min_seconds": round(min_lat, 2),
                "max_seconds": round(max_lat, 2),
            },
            error=None if passed else f"Latency too high: {avg:.2f}s avg",
        )
        self.results.append(result)
        log_result(result)

        print(f"         Latency: avg={avg:.2f}s, min={min_lat:.2f}s, max={max_lat:.2f}s")

    def test_concurrent_sessions(self):
        """Test multiple concurrent sessions."""
        start = time.time()

        num_sessions = 5
        sessions = [(generate_session_id(), f"SECRET_{i}") for i in range(num_sessions)]

        results_list = []
        errors = []

        def run_session(session_id, secret, idx):
            try:
                # Set
                output1, code1, _ = invoke_gemini(f"Remember: {secret}. Reply OK.", session_id=session_id)
                if code1 != 0:
                    return {"idx": idx, "success": False, "error": "set failed"}

                # Get
                output2, code2, _ = invoke_gemini("What did I ask you to remember?", session_id=session_id)

                found = secret in output2 or f"SECRET_{idx}" in output2
                return {"idx": idx, "success": found, "response": output2[:50]}
            except Exception as e:
                return {"idx": idx, "success": False, "error": str(e)}

        with ThreadPoolExecutor(max_workers=num_sessions) as executor:
            futures = [executor.submit(run_session, sid, secret, i) for i, (sid, secret) in enumerate(sessions)]

            for f in as_completed(futures):
                res = f.result()
                results_list.append(res)
                if not res.get("success"):
                    errors.append(res)

        success_count = sum(1 for r in results_list if r.get("success"))
        success_rate = success_count / num_sessions
        passed = success_rate >= 0.8  # 80% success rate

        result = TestResult(
            name="concurrent_sessions",
            category="stress",
            passed=passed,
            duration=time.time() - start,
            details={
                "sessions": num_sessions,
                "successful": success_count,
                "success_rate": f"{success_rate * 100:.0f}%",
                "errors": len(errors),
            },
            error=None if passed else f"Too many failures: {len(errors)}/{num_sessions}",
        )
        self.results.append(result)
        log_result(result)

    def print_summary(self, total_duration: float):
        """Print final summary."""
        print("\n" + "=" * 70)
        print("BENCHMARK SUMMARY")
        print("=" * 70)

        passed = sum(1 for r in self.results if r.passed)
        len(self.results) - passed

        # Group by category
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"passed": 0, "failed": 0}
            if r.passed:
                categories[r.category]["passed"] += 1
            else:
                categories[r.category]["failed"] += 1

        print(f"\nTotal: {passed}/{len(self.results)} passed ({passed / len(self.results) * 100:.0f}%)")
        print(f"Duration: {total_duration:.1f}s")
        print("\nBy Category:")
        for cat, stats in categories.items():
            total = stats["passed"] + stats["failed"]
            pct = stats["passed"] / total * 100 if total > 0 else 0
            status = "OK" if stats["failed"] == 0 else "ISSUES"
            print(f"  {cat}: {stats['passed']}/{total} ({pct:.0f}%) [{status}]")

        # Critical failures
        critical_cats = ["session_isolation"]
        critical_failures = [r for r in self.results if not r.passed and r.category in critical_cats]

        if critical_failures:
            print("\n*** CRITICAL FAILURES ***")
            for r in critical_failures:
                print(f"  - {r.name}: {r.error}")
        else:
            print("\nNo critical failures.")

        print("\n" + "=" * 70)
        print(f"Log saved: {LOG_FILE}")
        print("=" * 70)


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    benchmark = RealWorldBenchmark()
    benchmark.run_all()
