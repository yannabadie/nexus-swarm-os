"""
NEXUS V12.4 P4.1 - OTel Profiling Workload

Runs 100 realistic tasks across complexity levels to profile hot paths.

Usage:
    # 1. Enable OTel
    export NEXUS_FF_OTEL_ENABLED=true

    # 2. Start observability stack
    docker compose --profile observability up -d

    # 3. Run benchmark
    python scripts/benchmark_workload.py

    # 4. Analyze traces
    python scripts/analyze_traces.py

    # 5. View in Jaeger
    open http://localhost:16686
"""

import asyncio
import logging
from pathlib import Path
from datetime import datetime

# Add NEXUS root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestration_v7 import OrchestratorV7
from core.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Benchmark task dataset (100 tasks total)
BENCHMARK_TASKS = [
    # TRIVIAL (10x) - Fast path, no LLM
    *["Hello, how are you?"] * 3,
    *["Thanks!"] * 3,
    *["What's your name?"] * 4,

    # SIMPLE (20x) - Single agent, quick response
    *["Explain Python decorators"] * 5,
    *["What is a binary search tree?"] * 5,
    *["How do I use list comprehensions?"] * 5,
    *["What's the difference between == and is?"] * 5,

    # MODERATE (30x) - Swarm/HiveMind, requires analysis
    *["Analyze this codebase and suggest improvements"] * 10,
    *["Find all uses of the Config class"] * 10,
    *["Explain the FSM state machine architecture"] * 10,

    # COMPLEX (30x) - Multi-phase HiveMind, tool usage
    *["Implement a distributed task queue with Redis"] * 10,
    *["Add error handling to the memory backend"] * 10,
    *["Refactor the orchestrator to use async/await"] * 10,

    # EXPERT (10x) - Full HiveMind pipeline, evolution
    *["Design a fault-tolerant microservices architecture"] * 5,
    *["Optimize the RAG retrieval performance"] * 5,
]


async def run_benchmark():
    """
    Run benchmark workload with OTel tracing.

    Executes 100 tasks across complexity levels to profile:
    - Hot paths (>100ms average latency)
    - High call counts (>1000 invocations)
    - CPU bottlenecks (>50% time in function)
    """
    # Verify OTel is enabled
    config = Config()
    if not config.features.otel_enabled:
        logger.error("[NO] NEXUS_FF_OTEL_ENABLED=true required for profiling!")
        logger.error("Set in .env or environment: export NEXUS_FF_OTEL_ENABLED=true")
        return

    logger.info("🔬 Starting NEXUS Profiling Workload")
    logger.info(f"Tasks: {len(BENCHMARK_TASKS)}")
    logger.info(f"OTel: Enabled")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")

    orchestrator = OrchestratorV7()

    start_time = datetime.now()
    completed = 0
    failed = 0

    for i, task in enumerate(BENCHMARK_TASKS, 1):
        logger.info(f"[{i}/{len(BENCHMARK_TASKS)}] Processing: {task[:60]}...")

        try:
            # Note: process_turn is synchronous in orchestrator
            # This benchmarks the actual execution path
            result = orchestrator.process_turn(task)

            if result.get("finished", False):
                completed += 1
            else:
                logger.warning(f"Task {i} not finished: {result.get('state')}")
                failed += 1

        except Exception as e:
            logger.error(f"Task {i} failed: {e}")
            failed += 1

        # Small delay to avoid overwhelming the system
        await asyncio.sleep(0.5)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("=" * 80)
    logger.info("🎯 Benchmark Complete")
    logger.info(f"Total tasks: {len(BENCHMARK_TASKS)}")
    logger.info(f"Completed: {completed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Duration: {duration:.2f}s")
    logger.info(f"Avg time/task: {duration / len(BENCHMARK_TASKS):.2f}s")
    logger.info("=" * 80)
    logger.info("")
    logger.info("📊 Next steps:")
    logger.info("1. View traces: http://localhost:16686")
    logger.info("2. Analyze hot paths: python scripts/analyze_traces.py")
    logger.info("3. Review todomig.md for Rust migration candidates")


def main():
    """Entry point for benchmark workload."""
    asyncio.run(run_benchmark())


if __name__ == "__main__":
    main()
