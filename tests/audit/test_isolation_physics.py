"""
ISOLATION PHYSICS PROOF - OBSIDIAN V2.0 Audit
NEXUS V9.7.1 HOME Spoofing Verification

Must be EXECUTED, not just read.
Proves subprocess isolation at the OS level.

Author: NEXUS PRIME (Obsidian Protocol)
Date: 2025-12-13
"""

import json
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class IsolationPhysicsProof:
    """
    Executable proofs of subprocess isolation.

    These tests verify ACTUAL isolation at the OS level,
    not just Python code analysis.
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.results = {}
        self.proof_dir = self.workspace / "_isolation_proof"
        self.proof_dir.mkdir(exist_ok=True)

    def test_home_isolation(self) -> dict:
        """
        PROOF: Two concurrent subprocesses get DIFFERENT $HOME directories.

        Method: Each subprocess writes its HOME to a unique file.
        We compare the paths - they MUST differ.

        This proves V9.7.1 HOME spoofing works at the OS level.
        """
        test_name = "HOME_ISOLATION"
        uuid_a = f"proof_agent_A_{uuid.uuid4().hex[:8]}"
        uuid_b = f"proof_agent_B_{uuid.uuid4().hex[:8]}"

        def get_subprocess_home(session_id: str) -> dict:
            """Spawn subprocess with isolated env, capture its HOME."""
            try:
                from core.infrastructure.session.home_isolator import HomeIsolator

                isolator = HomeIsolator(self.workspace)
                isolated_env = isolator.get_isolated_env(session_id)

                # Cross-platform HOME detection script
                script = """
import os
import sys
import json

home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "UNKNOWN"
cwd = os.getcwd()

result = {
    "home": home,
    "cwd": cwd,
    "platform": sys.platform
}
print(json.dumps(result))
"""
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    env=isolated_env,
                    capture_output=True,
                    text=True,
                    cwd=str(self.workspace),
                    timeout=30,
                )

                if result.returncode != 0:
                    return {"error": result.stderr, "session_id": session_id}

                return json.loads(result.stdout.strip())

            except Exception as e:
                return {"error": str(e), "session_id": session_id}

        # Run concurrently to simulate real swarm
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(get_subprocess_home, uuid_a)
            future_b = executor.submit(get_subprocess_home, uuid_b)

            result_a = future_a.result()
            result_b = future_b.result()

        # Check for errors
        if "error" in result_a or "error" in result_b:
            return {
                "test": test_name,
                "PASS": False,
                "verdict": "CRITICAL: Test execution failed",
                "error_a": result_a.get("error"),
                "error_b": result_b.get("error"),
            }

        home_a = result_a.get("home", "")
        home_b = result_b.get("home", "")

        # PROOF LOGIC
        homes_different = home_a != home_b
        a_contains_uuid = uuid_a in home_a
        b_contains_uuid = uuid_b in home_b

        passed = homes_different and a_contains_uuid and b_contains_uuid

        return {
            "test": test_name,
            "home_a": home_a,
            "home_b": home_b,
            "uuid_a": uuid_a,
            "uuid_b": uuid_b,
            "homes_different": homes_different,
            "a_contains_session_id": a_contains_uuid,
            "b_contains_session_id": b_contains_uuid,
            "PASS": passed,
            "verdict": "ISOLATED - Each agent has unique HOME" if passed else "CRITICAL: HOME NOT ISOLATED",
        }

    def test_cwd_preservation(self) -> dict:
        """
        PROOF: Subprocess CWD remains at workspace root despite HOME change.

        Critical for: File operations must target correct directory.
        V9.7 bug: CWD isolation caused "ghost files" in wrong directory.
        V9.7.1 fix: Only HOME changes, CWD stays at workspace.
        """
        test_name = "CWD_PRESERVATION"

        try:
            from core.infrastructure.session.home_isolator import HomeIsolator

            isolator = HomeIsolator(self.workspace)
            isolated_env = isolator.get_isolated_env("cwd_proof_test")

            script = "import os; print(os.getcwd())"
            result = subprocess.run(
                [sys.executable, "-c", script],
                env=isolated_env,
                capture_output=True,
                text=True,
                cwd=str(self.workspace),
                timeout=30,
            )

            subprocess_cwd = Path(result.stdout.strip()).resolve()
            expected_cwd = self.workspace.resolve()

            passed = subprocess_cwd == expected_cwd

            return {
                "test": test_name,
                "subprocess_cwd": str(subprocess_cwd),
                "expected_cwd": str(expected_cwd),
                "PASS": passed,
                "verdict": "CWD PRESERVED at workspace root" if passed else "CRITICAL: CWD CHANGED (Ghost Files Risk!)",
            }

        except Exception as e:
            return {"test": test_name, "PASS": False, "verdict": f"CRITICAL: Test failed - {e}"}

    def test_env_leak_prevention(self) -> dict:
        """
        PROOF: Environment variables don't leak between isolated sessions.

        Scenario: Agent A sets SECRET_A. Agent B must NOT see it.
        This is critical for multi-tenant security.
        """
        test_name = "ENV_LEAK_PREVENTION"

        try:
            from core.infrastructure.session.home_isolator import HomeIsolator

            isolator = HomeIsolator(self.workspace)

            # Agent A's environment with secret
            secret_value = f"TOP_SECRET_{uuid.uuid4().hex}"
            env_a = isolator.get_isolated_env("leak_test_agent_A")
            env_a["SECRET_AGENT_A"] = secret_value

            # Agent B's environment (clean, different session)
            env_b = isolator.get_isolated_env("leak_test_agent_B")

            # Verify B cannot see A's secret
            script = 'import os; print(os.environ.get("SECRET_AGENT_A", "NOT_FOUND"))'

            result_b = subprocess.run(
                [sys.executable, "-c", script], env=env_b, capture_output=True, text=True, timeout=30
            )

            value_seen_by_b = result_b.stdout.strip()
            leaked = value_seen_by_b != "NOT_FOUND"

            return {
                "test": test_name,
                "secret_set_in": "Agent A",
                "secret_value": secret_value[:20] + "...",
                "checked_in": "Agent B",
                "value_seen_by_b": value_seen_by_b,
                "leaked": leaked,
                "PASS": not leaked,
                "verdict": "CRITICAL: ENV LEAK DETECTED!" if leaked else "NO LEAK - Environments isolated",
            }

        except Exception as e:
            return {"test": test_name, "PASS": False, "verdict": f"CRITICAL: Test failed - {e}"}

    def test_concurrent_isolation(self) -> dict:
        """
        PROOF: Multiple concurrent sessions maintain isolation under load.

        Spawns 5 concurrent agents, each verifying their HOME is unique.
        """
        test_name = "CONCURRENT_ISOLATION"

        try:
            from core.infrastructure.session.home_isolator import HomeIsolator

            isolator = HomeIsolator(self.workspace)

            def get_home_for_session(session_id: str) -> tuple:
                env = isolator.get_isolated_env(session_id)
                script = """
import os
home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "UNKNOWN"
print(home)
"""
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    env=env,
                    capture_output=True,
                    text=True,
                    cwd=str(self.workspace),
                    timeout=30,
                )
                return (session_id, result.stdout.strip())

            # Spawn 5 concurrent agents
            session_ids = [f"concurrent_agent_{i}_{uuid.uuid4().hex[:6]}" for i in range(5)]

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(get_home_for_session, sid) for sid in session_ids]
                results = [f.result() for f in futures]

            # Check all HOMEs are unique
            homes = [r[1] for r in results]
            unique_homes = set(homes)
            all_unique = len(unique_homes) == len(homes)

            return {
                "test": test_name,
                "agents_spawned": len(session_ids),
                "unique_homes_count": len(unique_homes),
                "all_unique": all_unique,
                "homes": dict(results),
                "PASS": all_unique,
                "verdict": f"All {len(session_ids)} agents isolated"
                if all_unique
                else "CRITICAL: HOME COLLISION DETECTED",
            }

        except Exception as e:
            return {"test": test_name, "PASS": False, "verdict": f"CRITICAL: Test failed - {e}"}

    def test_cleanup_works(self) -> dict:
        """
        PROOF: Isolated HOME directories can be cleaned up.

        Verifies cleanup doesn't leave orphan directories.
        """
        test_name = "CLEANUP_VERIFICATION"

        try:
            from core.infrastructure.session.home_isolator import HomeIsolator

            isolator = HomeIsolator(self.workspace)

            # Create a session
            session_id = f"cleanup_test_{uuid.uuid4().hex[:8]}"
            isolator.get_isolated_env(session_id)

            # Verify directory was created
            home_path = isolator.get_home_path(session_id)
            created = home_path is not None and home_path.exists()

            # Cleanup
            cleanup_result = isolator.cleanup_home(session_id)

            # Verify directory was removed
            removed = not home_path.exists() if home_path else True

            return {
                "test": test_name,
                "session_id": session_id,
                "directory_created": created,
                "cleanup_returned": cleanup_result,
                "directory_removed": removed,
                "PASS": created and cleanup_result and removed,
                "verdict": "Cleanup working correctly" if (created and removed) else "CRITICAL: Cleanup failed",
            }

        except Exception as e:
            return {"test": test_name, "PASS": False, "verdict": f"CRITICAL: Test failed - {e}"}

    def run_all(self) -> dict:
        """Run all isolation proofs and return comprehensive results."""
        print("=" * 70)
        print("ISOLATION PHYSICS PROOF - OBSIDIAN V2.0")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Workspace: {self.workspace}")
        print("=" * 70)

        tests = [
            ("home_isolation", self.test_home_isolation),
            ("cwd_preservation", self.test_cwd_preservation),
            ("env_leak_prevention", self.test_env_leak_prevention),
            ("concurrent_isolation", self.test_concurrent_isolation),
            ("cleanup_verification", self.test_cleanup_works),
        ]

        results = {}
        for name, test_func in tests:
            print(f"\n[RUNNING] {name}...")
            try:
                result = test_func()
                results[name] = result
                status = "PASS" if result.get("PASS") else "FAIL"
                print(f"[{status}] {result.get('verdict', 'No verdict')}")
            except Exception as e:
                results[name] = {"PASS": False, "error": str(e)}
                print(f"[FAIL] Exception: {e}")

        # Calculate overall result
        all_pass = all(r.get("PASS", False) for r in results.values())

        results["_summary"] = {
            "total_tests": len(tests),
            "passed": sum(1 for r in results.values() if r.get("PASS", False)),
            "failed": sum(1 for r in results.values() if not r.get("PASS", True)),
            "overall_pass": all_pass,
            "timestamp": datetime.now().isoformat(),
            "workspace": str(self.workspace),
        }

        print("\n" + "=" * 70)
        print(
            f"OVERALL VERDICT: {'PASS - ALL ISOLATION PROOFS VERIFIED' if all_pass else 'FAIL - ISOLATION COMPROMISED'}"
        )
        print("=" * 70)

        return results

    def cleanup(self):
        """Clean up proof directory."""
        import shutil

        if self.proof_dir.exists():
            shutil.rmtree(self.proof_dir, ignore_errors=True)


if __name__ == "__main__":
    workspace = Path(__file__).parent.parent.parent

    proof = IsolationPhysicsProof(workspace)
    try:
        results = proof.run_all()

        # Write results to file
        output_file = workspace / "audit" / "ISOLATION_PROOF.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)

        print(f"\nResults saved to: {output_file}")

        # Exit with appropriate code
        sys.exit(0 if results["_summary"]["overall_pass"] else 1)

    finally:
        proof.cleanup()
