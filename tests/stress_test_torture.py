import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine
from core.intelligence.swarm.mode_executors import ExecutionStatus
from core.synapse.memory_v7 import MemoryManagerV7

# Setup logging
LOG_FILE = Path("workspace/logs/stress_test_torture.jsonl")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class TortureResult:
    scenario: str
    success: bool
    duration: float
    error: str = None
    metrics: dict[str, Any] = None


class TortureChamber:
    def __init__(self):
        self.workspace = Path("workspace/stress_test")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.results: list[TortureResult] = []
        self.lock = threading.Lock()

        # Initialize Core Components
        self.memory_manager = MemoryManagerV7(self.workspace, None)  # Config None for test
        # Mock agent pool and router for speed (we test architecture, not LLM latency)
        self.engine = HybridSwarmEngine(
            agent_pool=None,  # Mocked internally or handles None
            model_router=None,
            config=None,
            workspace_path=self.workspace,
        )

        # Monkey patch invoke_agent to simulate LLM with variable latency/failure
        self.engine.invoke_agent = self._mock_invoke_agent

    def _mock_invoke_agent(self, agent_id: str, task_type: str, context: str) -> str:
        """Simulate an agent thinking, potentially crashing, or leaking context."""
        time.sleep(random.uniform(0.1, 0.5))  # Simulate network latency

        # Simulate Chaos Monkey (random crashes)
        if "CHAOS_MODE" in context and random.random() < 0.1:
            raise RuntimeError(f"Agent {agent_id} CRASHED intentionally!")

        # Context Bleeding Check
        if "IDENTITY_CHECK" in context:
            # Agent should only see its own assigned identity in context
            # If it sees another identity, it's bleeding.
            if "ALICE" in context and "BOB" in context:
                return "FATAL_ERROR: I see BOTH Alice and Bob!"
            if "ALICE" in context:
                return "I am ALICE."
            if "BOB" in context:
                return "I am BOB."

        return f"Agent {agent_id} processed task successfully."

    def log_result(self, result: TortureResult):
        with self.lock:
            self.results.append(result)
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(result.__dict__) + "\n")
            status = "[OK] PASS" if result.success else "[NO] FAIL"
            print(f"[{status}] {result.scenario} ({result.duration:.2f}s)")
            if result.error:
                print(f"   ERROR: {result.error}")

    # SCENARIO 1: The Flooding (Concurrency)
    def test_flooding(self, num_threads=10):
        print(f"\n🔥 STARTING SCENARIO 1: FLOODING ({num_threads} concurrent tasks)...")
        start_global = time.time()

        def run_task(i):
            start = time.time()
            try:
                # Force parallel mode to stress lock contention
                self.engine.process_task(
                    task_input=f"Task {i} requires high concurrency",
                    force_mode=CollaborationMode.PARALLEL,
                    skip_negotiation=True,
                )
                return TortureResult("Flooding_Task", True, time.time() - start)
            except Exception as e:
                return TortureResult("Flooding_Task", False, time.time() - start, str(e))

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(run_task, i) for i in range(num_threads)]
            for future in as_completed(futures):
                self.log_result(future.result())

        print(f"🔥 FLOODING COMPLETE in {time.time() - start_global:.2f}s")

    # SCENARIO 2: Context Poisoning (Isolation)
    def test_context_isolation(self):
        print("\n🧪 STARTING SCENARIO 2: CONTEXT ISOLATION...")

        def run_alice():
            start = time.time()
            try:
                # Inject a marker in the task input that acts as 'context' for the mock agent
                res = self.engine.process_task("IDENTITY_CHECK I am ALICE", force_mode=CollaborationMode.SPECIALIST)
                content = res.execution_result.final_output
                success = "I am ALICE" in content and "BOB" not in content
                err = f"Identity Crisis: {content}" if not success else None
                return TortureResult("Isolation_Alice", success, time.time() - start, err)
            except Exception as e:
                return TortureResult("Isolation_Alice", False, time.time() - start, str(e))

        def run_bob():
            start = time.time()
            try:
                res = self.engine.process_task("IDENTITY_CHECK I am BOB", force_mode=CollaborationMode.SPECIALIST)
                content = res.execution_result.final_output
                success = "I am BOB" in content and "ALICE" not in content
                err = f"Identity Crisis: {content}" if not success else None
                return TortureResult("Isolation_Bob", success, time.time() - start, err)
            except Exception as e:
                return TortureResult("Isolation_Bob", False, time.time() - start, str(e))

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_alice), executor.submit(run_bob)]
            for future in as_completed(futures):
                self.log_result(future.result())

    # SCENARIO 3: Chaos Monkey (Resilience)
    def test_chaos_monkey(self):
        print("\n🐒 STARTING SCENARIO 3: CHAOS MONKEY...")
        start = time.time()
        try:
            # Trigger chaos mode in mock agent
            # We expect the engine to catch errors, potentially fallback (if implemented) or report failure cleanly
            # It should NOT crash the main process.
            res = self.engine.process_task("CHAOS_MODE activate", force_mode=CollaborationMode.PARALLEL)

            # If it finished with FAILED or COMPLETED (due to retry) it's a success for the test harness
            # The test fails only if python crashes or throws unhandled exception
            success = res.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]
            return TortureResult("Chaos_Monkey", success, time.time() - start, f"Status: {res.status}")
        except Exception as e:
            # If we catch an exception here, the engine let it bubble up -> FAIL
            return TortureResult("Chaos_Monkey", False, time.time() - start, f"Unhandled Exception: {str(e)}")

    def run_all(self):
        print("=== 💀 NEXUS V7.8 TORTURE PROTOCOL INITIATED 💀 ===")
        self.test_flooding()
        self.test_context_isolation()
        self.log_result(self.test_chaos_monkey())

        # Summary
        total = len(self.results)
        passed = sum(1 for r in self.results if r.success)
        print("\n=== REPORT ===")
        print(f"Total Tests: {total}")
        print(f"Passed:      {passed}")
        print(f"Failed:      {total - passed}")
        score = (passed / total) * 100 if total > 0 else 0
        print(f"Robustness Score: {score:.1f}%")


if __name__ == "__main__":
    chamber = TortureChamber()
    chamber.run_all()
