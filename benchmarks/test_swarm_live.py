#!/usr/bin/env python3
"""
NEXUS V12.4 - Live Multi-Model Swarm Orchestration Benchmark

Real API calls against multiple LLM providers. NO MOCKS.

Tests:
  1. Swarm Eval Harness   - deterministic strategy comparison
  2. Provider Canaries    - live health check across all configured providers
  3. Multi-Provider Task  - same question to 3 providers + collaborative chain
  4. Task Analyzer        - complexity classification on 5 canonical inputs

Requires API keys in .env: GOOGLE_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY,
                           KIMI_API_KEY, MINIMAX_API_KEY
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Resolve project root so imports work when running from benchmarks/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")


# ============================================================================
# Helpers
# ============================================================================

def _section(title: str) -> None:
    width = 72
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _subsection(title: str) -> None:
    print(f"\n--- {title} ---")


# ============================================================================
# TEST 1 - Swarm Eval Harness (deterministic, local)
# ============================================================================

def run_test1_swarm_eval() -> dict[str, Any]:
    """Run the deterministic swarm evaluation harness and return results."""
    _section("TEST 1: Swarm Eval Harness (deterministic)")

    from core.intelligence.swarm.eval_harness import SwarmEvalHarness

    output_root = PROJECT_ROOT / "benchmarks" / "swarm_eval"
    harness = SwarmEvalHarness(output_root=output_root)
    report = harness.run()
    output_dir = harness.write_report(report)

    report_dict = report.to_dict()

    # ---- Print summary ----
    _subsection("Strategy Comparison")
    strategies = report_dict["strategy_summaries"]
    print(f"{'Strategy':<28} {'Pass Rate':>10} {'Avg Score':>10} {'Recovery':>10} {'Avg Latency':>12}")
    print("-" * 72)

    best_strategy = None
    best_score = -1.0
    for s in strategies:
        label = s["strategy"]
        pr = f"{s['pass_rate']:.0%}"
        sc = f"{s['average_score']:.3f}"
        rc = f"{s['recovery_rate']:.0%}"
        lat = f"{s['average_latency_seconds']:.3f}s"
        print(f"{label:<28} {pr:>10} {sc:>10} {rc:>10} {lat:>12}")
        if s["average_score"] > best_score:
            best_score = s["average_score"]
            best_strategy = label

    _subsection("Winner")
    print(f"Best strategy: {best_strategy} (avg score {best_score:.3f})")
    print(f"Report written to: {output_dir}")

    return {
        "test": "swarm_eval_harness",
        "status": "completed",
        "output_dir": str(output_dir),
        "strategies": {s["strategy"]: s for s in strategies},
        "best_strategy": best_strategy,
        "best_score": best_score,
        "task_count": report_dict["task_count"],
    }


# ============================================================================
# TEST 2 - Provider Canaries (live API calls)
# ============================================================================

async def run_test2_provider_canaries() -> dict[str, Any]:
    """Run live provider canaries and return results."""
    _section("TEST 2: Provider Canaries (LIVE API calls)")

    from core.drivers.provider_canaries import ProviderCanaryRunner

    output_path = PROJECT_ROOT / "benchmarks" / "provider_canaries.json"

    runner = ProviderCanaryRunner()
    report = await runner.run()
    await runner.write_report(report, output_path)

    report_dict = report.to_dict()
    summary = report_dict["summary"]

    _subsection("Results")
    print(f"{'Provider':<14} {'Configured':>11} {'Attempted':>10} {'Passed':>8} {'Latency':>10} {'Model':>28}")
    print("-" * 83)

    for r in report_dict["results"]:
        cfg = "yes" if r["configured"] else "no"
        att = "yes" if r["attempted"] else "no"
        passed = "PASS" if r["passed"] else "FAIL"
        lat = f"{r['latency_ms']:.0f}ms" if r["latency_ms"] else "n/a"
        model = r["model"] or "n/a"
        print(f"{r['provider']:<14} {cfg:>11} {att:>10} {passed:>8} {lat:>10} {model:>28}")
        if r.get("error"):
            print(f"  -> Error: {r['error'][:100]}")

    _subsection("Summary")
    print(f"Configured: {summary['configured_providers']}, "
          f"Attempted: {summary['attempted_providers']}, "
          f"Passed: {summary['passed_providers']}, "
          f"Failed: {summary['failed_providers']}")
    print(f"Pass rate: {summary['pass_rate']:.0%}")
    print(f"Report written to: {output_path}")

    return {
        "test": "provider_canaries",
        "status": "completed",
        "output_path": str(output_path),
        "summary": summary,
        "results": report_dict["results"],
    }


# ============================================================================
# TEST 3 - Multi-Provider Task (live API calls)
# ============================================================================

async def run_test3_multi_provider() -> dict[str, Any]:
    """
    Real multi-provider orchestration:
      Part A - Same question to Gemini, DeepSeek, and OpenAI
      Part B - Collaborative chain: Gemini -> DeepSeek -> OpenAI
    """
    _section("TEST 3: Multi-Provider Task (LIVE API calls)")

    from core.config import Config
    from core.drivers.async_factory import AsyncDriverFactory

    config = Config()
    factory = AsyncDriverFactory(config, PROJECT_ROOT / "workspace")

    # ------------------------------------------------------------------
    # Part A: Same question to 3 providers, compare quality
    # ------------------------------------------------------------------
    _subsection("Part A: Same question to 3 providers")
    question = "Explain the concept of dependency injection in 3 sentences."
    print(f"Question: \"{question}\"")

    providers = {}
    provider_list = [
        ("google", "get_gemini_sdk", "gemini_sdk_available"),
        ("deepseek", "get_deepseek_sdk", "deepseek_sdk_available"),
        ("openai", "get_openai_sdk", "openai_sdk_available"),
    ]

    async def _ask_provider(name: str, method_name: str) -> dict[str, Any]:
        driver = getattr(factory, method_name)()
        t0 = time.monotonic()
        response = await driver.invoke(question, temperature=0.3, max_tokens=512)
        elapsed = time.monotonic() - t0
        return {
            "provider": name,
            "model": response.model or getattr(driver, "_model", "unknown"),
            "content": response.content.strip(),
            "latency_s": round(elapsed, 3),
            "response_length": len(response.content.strip()),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "status": response.status.name,
        }

    # Fire all 3 in parallel
    tasks_a = []
    for name, method, avail_attr in provider_list:
        if getattr(factory, avail_attr, False):
            tasks_a.append(_ask_provider(name, method))
        else:
            print(f"  [SKIP] {name}: API key not configured")

    results_a = await asyncio.gather(*tasks_a, return_exceptions=True)

    part_a_results = []
    for result in results_a:
        if isinstance(result, Exception):
            print(f"  [ERROR] {result}")
            part_a_results.append({
                "provider": "unknown",
                "error": str(result),
                "status": "ERROR",
            })
        else:
            part_a_results.append(result)
            print(f"\n  [{result['provider'].upper()}] ({result['model']}) "
                  f"latency={result['latency_s']}s  len={result['response_length']} chars")
            # Print first 200 chars of response
            preview = result["content"][:200]
            print(f"    \"{preview}{'...' if len(result['content']) > 200 else ''}\"")

    # Compute overlap: simple word-set Jaccard similarity between responses
    if len([r for r in part_a_results if "content" in r]) >= 2:
        _subsection("Content Overlap (word-set Jaccard)")
        contents = {r["provider"]: set(r["content"].lower().split())
                    for r in part_a_results if "content" in r}
        providers_done = list(contents.keys())
        for i in range(len(providers_done)):
            for j in range(i + 1, len(providers_done)):
                p1, p2 = providers_done[i], providers_done[j]
                intersection = contents[p1] & contents[p2]
                union = contents[p1] | contents[p2]
                jaccard = len(intersection) / len(union) if union else 0
                print(f"  {p1} vs {p2}: {jaccard:.2%}")

    # ------------------------------------------------------------------
    # Part B: Collaborative chain  Gemini -> DeepSeek -> OpenAI
    # ------------------------------------------------------------------
    _subsection("Part B: Collaborative Chain (Gemini -> DeepSeek -> OpenAI)")

    chain_results = []

    # Step 1: Ask Gemini to write a code review checklist
    step1_prompt = "Write a code review checklist for Python projects. Include 8-10 items."
    print(f"\n  Step 1 [Gemini]: \"{step1_prompt}\"")

    gemini = factory.get_gemini_sdk()
    t0 = time.monotonic()
    step1_resp = await gemini.invoke(step1_prompt, temperature=0.4, max_tokens=1024)
    step1_latency = round(time.monotonic() - t0, 3)
    step1_content = step1_resp.content.strip()
    chain_results.append({
        "step": 1,
        "provider": "google",
        "model": step1_resp.model or getattr(gemini, "_model", "unknown"),
        "prompt": step1_prompt,
        "response": step1_content,
        "response_length": len(step1_content),
        "latency_s": step1_latency,
        "input_tokens": step1_resp.input_tokens,
        "output_tokens": step1_resp.output_tokens,
    })
    print(f"    latency={step1_latency}s  len={len(step1_content)} chars")
    print(f"    Preview: \"{step1_content[:150]}...\"")

    # Step 2: Pass Gemini's output to DeepSeek for expansion
    step2_prompt = (
        f"Improve and expand this Python code review checklist. "
        f"Add missing items, reorder by importance, and add brief explanations:\n\n"
        f"{step1_content}"
    )
    print(f"\n  Step 2 [DeepSeek]: \"Improve and expand this checklist...\"")

    deepseek = factory.get_deepseek_sdk()
    t0 = time.monotonic()
    step2_resp = await deepseek.invoke(step2_prompt, temperature=0.4, max_tokens=1536)
    step2_latency = round(time.monotonic() - t0, 3)
    step2_content = step2_resp.content.strip()
    chain_results.append({
        "step": 2,
        "provider": "deepseek",
        "model": step2_resp.model or getattr(deepseek, "_model", "unknown"),
        "prompt": step2_prompt[:100] + "...",
        "response": step2_content,
        "response_length": len(step2_content),
        "latency_s": step2_latency,
        "input_tokens": step2_resp.input_tokens,
        "output_tokens": step2_resp.output_tokens,
    })
    print(f"    latency={step2_latency}s  len={len(step2_content)} chars")
    print(f"    Preview: \"{step2_content[:150]}...\"")

    # Step 3: Pass DeepSeek's output to OpenAI for rating
    step3_prompt = (
        f"Rate this Python code review checklist from 1 to 10 and explain your rating. "
        f"Identify its strongest and weakest points:\n\n"
        f"{step2_content}"
    )
    print(f"\n  Step 3 [OpenAI]: \"Rate this checklist 1-10 and explain...\"")

    openai_driver = factory.get_openai_sdk()
    t0 = time.monotonic()
    step3_resp = await openai_driver.invoke(step3_prompt, temperature=0.3, max_tokens=1024)
    step3_latency = round(time.monotonic() - t0, 3)
    step3_content = step3_resp.content.strip()
    chain_results.append({
        "step": 3,
        "provider": "openai",
        "model": step3_resp.model or getattr(openai_driver, "_model", "unknown"),
        "prompt": step3_prompt[:100] + "...",
        "response": step3_content,
        "response_length": len(step3_content),
        "latency_s": step3_latency,
        "input_tokens": step3_resp.input_tokens,
        "output_tokens": step3_resp.output_tokens,
    })
    print(f"    latency={step3_latency}s  len={len(step3_content)} chars")
    print(f"    Preview: \"{step3_content[:150]}...\"")

    total_chain_latency = sum(r["latency_s"] for r in chain_results)
    total_chain_tokens_in = sum(r["input_tokens"] for r in chain_results)
    total_chain_tokens_out = sum(r["output_tokens"] for r in chain_results)

    _subsection("Chain Summary")
    print(f"  Total chain latency: {total_chain_latency:.3f}s")
    print(f"  Total tokens (in/out): {total_chain_tokens_in}/{total_chain_tokens_out}")
    for cr in chain_results:
        print(f"    Step {cr['step']} [{cr['provider']}]: {cr['latency_s']}s, "
              f"{cr['response_length']} chars, "
              f"{cr['input_tokens']}/{cr['output_tokens']} tokens")

    return {
        "test": "multi_provider_task",
        "status": "completed",
        "part_a": {
            "question": question,
            "results": part_a_results,
        },
        "part_b": {
            "chain": chain_results,
            "total_latency_s": total_chain_latency,
            "total_tokens_in": total_chain_tokens_in,
            "total_tokens_out": total_chain_tokens_out,
        },
    }


# ============================================================================
# TEST 4 - Task Analyzer (classification)
# ============================================================================

def run_test4_task_analyzer() -> dict[str, Any]:
    """Classify 5 canonical tasks using the real TaskAnalyzer."""
    _section("TEST 4: Task Analyzer (complexity classification)")

    from core.intelligence.swarm import TaskAnalyzer, suggest_mode_for_complexity

    analyzer = TaskAnalyzer()

    tasks = [
        ("Hello!", "TRIVIAL"),
        ("What is Python?", "SIMPLE"),
        ("Review this code for security vulnerabilities", "MODERATE"),
        ("Design a distributed cache system", "COMPLEX"),
        (
            "Architect a new microservices platform with service mesh, "
            "distributed tracing, event sourcing, and CQRS pattern across "
            "multiple availability zones with automated failover",
            "EXPERT",
        ),
    ]

    results = []
    print(f"\n{'Task':<60} {'Expected':>10} {'Got':>10} {'Domain':<16} {'Mode':<18} {'Match':>6}")
    print("-" * 122)

    for task_text, expected in tasks:
        analysis = analyzer.analyze(task_text)
        recommended_modes = suggest_mode_for_complexity(analysis.complexity.value)
        top_mode = recommended_modes[0].value if recommended_modes else "n/a"

        label = task_text if len(task_text) <= 57 else task_text[:54] + "..."
        match = "OK" if analysis.complexity.name == expected else "MISS"

        print(f"{label:<60} {expected:>10} {analysis.complexity.name:>10} "
              f"{analysis.primary_domain.value:<16} {top_mode:<18} {match:>6}")

        results.append({
            "task": task_text,
            "expected_complexity": expected,
            "actual_complexity": analysis.complexity.name,
            "complexity_value": analysis.complexity.value,
            "primary_domain": analysis.primary_domain.value,
            "all_domains": [d.value for d in analysis.domains],
            "recommended_mode": top_mode,
            "gemini_fit": analysis.gemini_fit_score,
            "claude_fit": analysis.claude_fit_score,
            "recommended_lead": analysis.recommended_lead,
            "confidence": analysis.confidence,
            "analysis_stage": analysis.analysis_stage.name,
            "match": analysis.complexity.name == expected,
        })

    matches = sum(1 for r in results if r["match"])
    total = len(results)
    _subsection("Summary")
    print(f"Matches: {matches}/{total} ({matches/total:.0%})")

    return {
        "test": "task_analyzer",
        "status": "completed",
        "results": results,
        "match_rate": matches / total,
    }


# ============================================================================
# Main orchestrator
# ============================================================================

async def main() -> None:
    started_at = datetime.now(UTC).isoformat()
    print(f"NEXUS Multi-Model Swarm Benchmark - {started_at}")
    print(f"Project root: {PROJECT_ROOT}")

    all_results: dict[str, Any] = {
        "benchmark": "swarm_live",
        "started_at": started_at,
        "tests": {},
    }

    # Test 1: Swarm Eval Harness (local, deterministic)
    try:
        all_results["tests"]["test1_swarm_eval"] = run_test1_swarm_eval()
    except Exception as e:
        print(f"\n[ERROR] Test 1 failed: {e}")
        all_results["tests"]["test1_swarm_eval"] = {"status": "error", "error": str(e)}

    # Test 2: Provider Canaries (live)
    try:
        all_results["tests"]["test2_provider_canaries"] = await run_test2_provider_canaries()
    except Exception as e:
        print(f"\n[ERROR] Test 2 failed: {e}")
        all_results["tests"]["test2_provider_canaries"] = {"status": "error", "error": str(e)}

    # Test 3: Multi-Provider Task (live)
    try:
        all_results["tests"]["test3_multi_provider"] = await run_test3_multi_provider()
    except Exception as e:
        print(f"\n[ERROR] Test 3 failed: {e}")
        all_results["tests"]["test3_multi_provider"] = {"status": "error", "error": str(e)}

    # Test 4: Task Analyzer (local)
    try:
        all_results["tests"]["test4_task_analyzer"] = run_test4_task_analyzer()
    except Exception as e:
        print(f"\n[ERROR] Test 4 failed: {e}")
        all_results["tests"]["test4_task_analyzer"] = {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # Persist combined results
    # ------------------------------------------------------------------
    all_results["completed_at"] = datetime.now(UTC).isoformat()
    output_path = PROJECT_ROOT / "benchmarks" / "swarm_test_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Truncate long response fields for the JSON dump (full text is too large)
    def _truncate(obj: Any, max_len: int = 500) -> Any:
        if isinstance(obj, str) and len(obj) > max_len:
            return obj[:max_len] + f"... [{len(obj)} chars total]"
        if isinstance(obj, dict):
            return {k: _truncate(v, max_len) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_truncate(v, max_len) for v in obj]
        return obj

    serializable = _truncate(all_results, max_len=800)
    output_path.write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    _section("ALL TESTS COMPLETE")
    completed_tests = sum(
        1 for t in all_results["tests"].values()
        if isinstance(t, dict) and t.get("status") == "completed"
    )
    total_tests = len(all_results["tests"])
    print(f"Completed: {completed_tests}/{total_tests}")
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
