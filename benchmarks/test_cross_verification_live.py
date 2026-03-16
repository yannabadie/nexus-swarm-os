"""
NEXUS V12.4 - Cross-Model Verification Benchmark (LIVE)

Tests the Cognitive Feedback Loop (CFL): one model generates code,
a DIFFERENT model validates it for correctness and security.

NO MOCKS. Real API calls to all providers.

Cross-verification pairs:
  1. Gemini generates   -> DeepSeek validates
  2. Kimi generates     -> Gemini validates
  3. DeepSeek generates -> Kimi validates
  4. Deliberate failure: hardcoded wrong code -> each validator should catch it

Usage:
    python benchmarks/test_cross_verification_live.py

Results saved to: benchmarks/cross_verification_results.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from core.drivers.protocol import DriverResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cfl-bench")

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PairResult:
    pair_name: str
    model_a: str
    model_b: str
    model_a_provider: str
    model_b_provider: str
    task: str
    model_a_response_snippet: str = ""
    model_b_verdict: str = ""  # [OK] or [NO]
    model_b_full_response: str = ""
    model_a_latency_ms: float = 0.0
    model_b_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    model_a_cost_usd: float = 0.0
    model_b_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    success: bool = False
    error: str | None = None
    is_deliberate_failure_test: bool = False
    validator_caught_error: bool | None = None


@dataclass
class BenchmarkResults:
    timestamp: str = ""
    total_pairs: int = 0
    successful_pairs: int = 0
    failed_pairs: int = 0
    deliberate_failure_caught: int = 0
    deliberate_failure_missed: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    pairs: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Driver creation helpers (direct instantiation, no factory overhead)
# ---------------------------------------------------------------------------

def create_gemini_driver():
    """Create Gemini SDK driver directly."""
    from core.drivers.google_genai_sdk_driver import GoogleGenAISDKDriver
    return GoogleGenAISDKDriver(
        model="gemini-2.5-flash",
        timeout=120.0,
    )


def create_deepseek_driver():
    """Create DeepSeek SDK driver directly."""
    from core.drivers.deepseek_sdk_driver import DeepSeekSDKDriver
    return DeepSeekSDKDriver(
        model="deepseek-chat",
        max_tokens=4096,
        timeout=120.0,
    )


def create_kimi_driver():
    """Create Kimi SDK driver (turbo variant for faster responses)."""
    from core.drivers.kimi_sdk_driver import KimiSDKDriver
    return KimiSDKDriver(
        model="kimi-k2-thinking-turbo",
        max_tokens=4096,
        timeout=180.0,
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

GENERATION_TASK = (
    "Write a Python function called `is_prime(n)` that checks if a number is prime. "
    "Include handling for edge cases (negative numbers, 0, 1, 2, even numbers). "
    "Return True if prime, False otherwise. Only output the Python code, no explanation."
)

VALIDATION_PROMPT_TEMPLATE = (
    "You are a code reviewer. Review the following Python code for correctness and security.\n\n"
    "```python\n{code}\n```\n\n"
    "Is this code a correct implementation of a primality check? "
    "Check edge cases (0, 1, 2, negative numbers, even numbers, large primes).\n\n"
    "Reply EXACTLY with [OK] on the first line if the code is correct, "
    "or [NO] on the first line followed by an explanation if it is incorrect.\n"
    "Your first line MUST be either [OK] or [NO]."
)

DELIBERATELY_WRONG_CODE = '''\
def is_prime(n):
    """Check if a number is prime."""
    return n % 2 == 0
'''

# ---------------------------------------------------------------------------
# Core CFL logic
# ---------------------------------------------------------------------------

def extract_verdict(response_text: str) -> str:
    """Extract [OK] or [NO] from the validator response."""
    text = response_text.strip()
    if not text:
        return "[UNCLEAR:empty]"
    for line in text.split("\n"):
        line = line.strip()
        if "[OK]" in line:
            return "[OK]"
        if "[NO]" in line:
            return "[NO]"
    # Fallback: check whole text
    if "[OK]" in text:
        return "[OK]"
    if "[NO]" in text:
        return "[NO]"
    # Heuristic fallback for models that don't follow exact format
    lower = text.lower()
    if any(w in lower for w in ["correct", "looks good", "is correct", "correctly"]):
        return "[OK]*"
    if any(w in lower for w in ["incorrect", "wrong", "bug", "error", "flaw", "issue"]):
        return "[NO]*"
    return "[UNCLEAR]"


def snippet(text: str, max_len: int = 200) -> str:
    """Truncate text to a readable snippet."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


async def run_pair(
    pair_name: str,
    generator,
    validator,
    task: str,
    hardcoded_response: str | None = None,
) -> PairResult:
    """
    Run one CFL pair: generator produces code, validator reviews it.

    If hardcoded_response is provided, skip the generator call and use it directly
    (for deliberate failure testing).
    """
    result = PairResult(
        pair_name=pair_name,
        model_a=generator.model,
        model_b=validator.model,
        model_a_provider=generator.provider,
        model_b_provider=validator.provider,
        task=task,
        is_deliberate_failure_test=hardcoded_response is not None,
    )

    total_start = time.monotonic()

    # --- Step 1: Generate (or use hardcoded) ---
    if hardcoded_response is not None:
        gen_content = hardcoded_response
        result.model_a_response_snippet = snippet(gen_content)
        result.model_a_latency_ms = 0.0
        result.model_a_cost_usd = 0.0
        log.info(
            f"  [{pair_name}] Using hardcoded WRONG code (deliberate failure test)"
        )
    else:
        log.info(f"  [{pair_name}] Generator ({generator.provider}/{generator.model}) working...")
        try:
            gen_resp: DriverResponse = await generator.invoke(
                task,
                system_prompt="You are an expert Python programmer. Output only code, no markdown fences unless necessary.",
                temperature=0.3,
            )
            if not gen_resp.is_success:
                result.error = f"Generator failed: {gen_resp.error_message}"
                log.error(f"  [{pair_name}] {result.error}")
                return result

            gen_content = gen_resp.content
            result.model_a_response_snippet = snippet(gen_content)
            result.model_a_latency_ms = gen_resp.latency_ms
            result.model_a_cost_usd = gen_resp.cost_usd
            log.info(
                f"  [{pair_name}] Generator done: {gen_resp.latency_ms:.0f}ms, "
                f"${gen_resp.cost_usd:.6f}"
            )
        except Exception as exc:
            result.error = f"Generator exception: {type(exc).__name__}: {exc}"
            log.error(f"  [{pair_name}] {result.error}")
            return result

    # --- Step 2: Validate ---
    validation_prompt = VALIDATION_PROMPT_TEMPLATE.format(code=gen_content)
    log.info(f"  [{pair_name}] Validator ({validator.provider}/{validator.model}) reviewing...")

    try:
        val_resp: DriverResponse = await validator.invoke(
            validation_prompt,
            system_prompt="You are a meticulous code reviewer. Always start your response with [OK] or [NO].",
            temperature=0.2,
        )
        if not val_resp.is_success:
            result.error = f"Validator failed: {val_resp.error_message}"
            log.error(f"  [{pair_name}] {result.error}")
            return result

        result.model_b_full_response = val_resp.content
        result.model_b_verdict = extract_verdict(val_resp.content)
        result.model_b_latency_ms = val_resp.latency_ms
        result.model_b_cost_usd = val_resp.cost_usd
        log.info(
            f"  [{pair_name}] Validator done: {val_resp.latency_ms:.0f}ms, "
            f"${val_resp.cost_usd:.6f}, verdict={result.model_b_verdict}"
        )
    except Exception as exc:
        result.error = f"Validator exception: {type(exc).__name__}: {exc}"
        log.error(f"  [{pair_name}] {result.error}")
        return result

    # --- Finalize ---
    total_ms = (time.monotonic() - total_start) * 1000
    result.total_latency_ms = total_ms
    result.total_cost_usd = result.model_a_cost_usd + result.model_b_cost_usd
    result.success = True

    if result.is_deliberate_failure_test:
        result.validator_caught_error = result.model_b_verdict == "[NO]"
        status = "CAUGHT" if result.validator_caught_error else "MISSED"
        log.info(f"  [{pair_name}] Deliberate failure test: {status}")

    return result


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

async def main():
    log.info("=" * 70)
    log.info("NEXUS CFL Cross-Model Verification Benchmark (LIVE)")
    log.info("=" * 70)

    # Verify API keys are present
    required_keys = {
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY"),
        "KIMI_API_KEY": os.getenv("KIMI_API_KEY"),
    }
    missing = [k for k, v in required_keys.items() if not v]
    if missing:
        log.error(f"Missing API keys: {', '.join(missing)}")
        log.error("Set them in .env or environment variables.")
        sys.exit(1)

    log.info("All API keys present. Creating drivers...")

    # Create drivers (3 providers, each used as both generator and validator)
    gemini = create_gemini_driver()
    deepseek = create_deepseek_driver()
    kimi = create_kimi_driver()

    log.info(f"  Gemini:   {gemini.model}")
    log.info(f"  DeepSeek: {deepseek.model}")
    log.info(f"  Kimi:     {kimi.model}")
    log.info("")

    # Define cross-verification pairs: every model generates AND validates
    # Each pair uses two DIFFERENT models (true cross-verification).
    pairs = [
        ("gemini->deepseek", gemini, deepseek, GENERATION_TASK, None),
        ("kimi->gemini", kimi, gemini, GENERATION_TASK, None),
        ("deepseek->kimi", deepseek, kimi, GENERATION_TASK, None),
    ]

    # Deliberate failure tests: each validator checks known-bad code
    failure_pairs = [
        ("FAIL:deepseek-validates", gemini, deepseek, GENERATION_TASK, DELIBERATELY_WRONG_CODE),
        ("FAIL:gemini-validates", deepseek, gemini, GENERATION_TASK, DELIBERATELY_WRONG_CODE),
        ("FAIL:kimi-validates", kimi, kimi, GENERATION_TASK, DELIBERATELY_WRONG_CODE),
    ]

    all_results: list[PairResult] = []
    bench_start = time.monotonic()

    # --- Run normal pairs sequentially (to avoid rate limits) ---
    log.info("-" * 70)
    log.info("PHASE 1: Cross-model generation + validation")
    log.info("-" * 70)
    for pair_name, gen, val, task, hardcoded in pairs:
        log.info(f"\n[{pair_name}]")
        result = await run_pair(pair_name, gen, val, task, hardcoded)
        all_results.append(result)

    # --- Run deliberate failure pairs ---
    log.info("")
    log.info("-" * 70)
    log.info("PHASE 2: Deliberate failure detection")
    log.info("-" * 70)
    for pair_name, gen, val, task, hardcoded in failure_pairs:
        log.info(f"\n[{pair_name}]")
        result = await run_pair(pair_name, gen, val, task, hardcoded)
        all_results.append(result)

    total_bench_ms = (time.monotonic() - bench_start) * 1000

    # --- Aggregate results ---
    successful = [r for r in all_results if r.success]
    failed = [r for r in all_results if not r.success]
    deliberate = [r for r in all_results if r.is_deliberate_failure_test and r.success]
    caught = [r for r in deliberate if r.validator_caught_error]
    missed = [r for r in deliberate if not r.validator_caught_error]

    total_cost = sum(r.total_cost_usd for r in all_results)

    bench = BenchmarkResults(
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_pairs=len(all_results),
        successful_pairs=len(successful),
        failed_pairs=len(failed),
        deliberate_failure_caught=len(caught),
        deliberate_failure_missed=len(missed),
        total_latency_ms=total_bench_ms,
        total_cost_usd=round(total_cost, 6),
        pairs=[
            {
                "pair_name": r.pair_name,
                "model_a": r.model_a,
                "model_b": r.model_b,
                "model_a_provider": r.model_a_provider,
                "model_b_provider": r.model_b_provider,
                "task": r.task[:80] + "...",
                "model_a_response_snippet": r.model_a_response_snippet,
                "model_b_verdict": r.model_b_verdict,
                "model_b_full_response": r.model_b_full_response[:500],
                "model_a_latency_ms": round(r.model_a_latency_ms, 1),
                "model_b_latency_ms": round(r.model_b_latency_ms, 1),
                "total_latency_ms": round(r.total_latency_ms, 1),
                "model_a_cost_usd": round(r.model_a_cost_usd, 6),
                "model_b_cost_usd": round(r.model_b_cost_usd, 6),
                "total_cost_usd": round(r.total_cost_usd, 6),
                "success": r.success,
                "error": r.error,
                "is_deliberate_failure_test": r.is_deliberate_failure_test,
                "validator_caught_error": r.validator_caught_error,
            }
            for r in all_results
        ],
    )

    # --- Save results ---
    results_path = PROJECT_ROOT / "benchmarks" / "cross_verification_results.json"
    results_path.write_text(json.dumps(asdict(bench), indent=2, ensure_ascii=False))
    log.info("")
    log.info("=" * 70)
    log.info("RESULTS SUMMARY")
    log.info("=" * 70)

    # Print per-pair summary
    for r in all_results:
        marker = ""
        if r.is_deliberate_failure_test:
            if r.validator_caught_error:
                marker = " [CAUGHT ERROR]"
            elif r.validator_caught_error is False:
                marker = " [MISSED ERROR!]"
        status = "OK" if r.success else "FAIL"
        log.info(
            f"  {r.pair_name:30s}  {status:4s}  verdict={r.model_b_verdict:10s}  "
            f"latency={r.total_latency_ms:8.0f}ms  cost=${r.total_cost_usd:.6f}{marker}"
        )

    log.info("")
    log.info(f"Total pairs:              {bench.total_pairs}")
    log.info(f"Successful:               {bench.successful_pairs}")
    log.info(f"Failed (API errors):      {bench.failed_pairs}")
    log.info(f"Deliberate errors caught: {bench.deliberate_failure_caught}/{len(deliberate)}")
    log.info(f"Total latency:            {bench.total_latency_ms:.0f}ms")
    log.info(f"Total cost:               ${bench.total_cost_usd:.6f}")
    log.info(f"Results saved to:         {results_path}")
    log.info("=" * 70)

    # Exit code: non-zero if any deliberate failures were missed
    if missed:
        log.warning(f"{len(missed)} validator(s) failed to catch deliberately wrong code!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
