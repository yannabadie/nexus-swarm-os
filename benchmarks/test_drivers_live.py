"""
Live integration test for all 5 available LLM providers.

Calls each SDK driver with a simple arithmetic prompt, measures latency,
validates the response, and prints a summary table.

NO MOCKS -- every call hits the real API using keys from .env.

Drivers are created directly (not via AsyncDriverFactory) to bypass known
post-processing bugs in the factory's shared ResponseCache and BudgetTracker
wiring.  This isolates the test to pure API connectivity.

Usage:
    cd /c/Code/NEXUS-NX-CG
    python benchmarks/test_drivers_live.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is on sys.path and .env is loaded
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from core.drivers.protocol import DriverResponseStatus

# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------
PROMPT = "What is 2+2? Answer with just the number."
RESULTS_PATH = PROJECT_ROOT / "benchmarks" / "driver_test_results.json"

# Provider -> (driver class import path, env var for API key, default model)
PROVIDERS: list[dict] = [
    {
        "name": "google",
        "module": "core.drivers.google_genai_sdk_driver",
        "class": "GoogleGenAISDKDriver",
        "env_key": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "default_model": "gemini-2.5-flash",
    },
    {
        "name": "openai",
        "module": "core.drivers.openai_sdk_driver",
        "class": "OpenAISDKDriver",
        "env_key": ["OPENAI_API_KEY"],
        "default_model": "gpt-4o-mini",
    },
    {
        "name": "deepseek",
        "module": "core.drivers.deepseek_sdk_driver",
        "class": "DeepSeekSDKDriver",
        "env_key": ["DEEPSEEK_API_KEY"],
        "default_model": "deepseek-chat",
    },
    {
        "name": "kimi",
        "module": "core.drivers.kimi_sdk_driver",
        "class": "KimiSDKDriver",
        "env_key": ["KIMI_API_KEY"],
        "default_model": "kimi-k2.5",
    },
    {
        "name": "minimax",
        "module": "core.drivers.minimax_sdk_driver",
        "class": "MiniMaxSDKDriver",
        "env_key": ["MINIMAX_API_KEY"],
        "default_model": "MiniMax-M2.5",
    },
]


def _resolve_key(env_keys: list[str]) -> str | None:
    """Return the first non-empty env var from the list."""
    for key in env_keys:
        val = os.getenv(key)
        if val:
            return val
    return None


def _create_driver(spec: dict, api_key: str):
    """Import the driver class and instantiate it directly -- no factory."""
    import importlib

    mod = importlib.import_module(spec["module"])
    cls = getattr(mod, spec["class"])

    # All SDK drivers accept (model, api_key, ...).  We pass response_cache=None
    # and enable_caching=False to sidestep the ResponseCache.set() bug.
    kwargs: dict = {
        "model": spec["default_model"],
        "api_key": api_key,
        "timeout": 60.0,
        "response_cache": None,
    }
    # GoogleGenAISDKDriver does not accept enable_caching/max_tokens
    if spec["name"] != "google":
        kwargs["enable_caching"] = False
        kwargs["max_tokens"] = 1024

    driver = cls(**kwargs)
    # Ensure no budget tracker or health monitor is wired (avoid record_cost bug)
    driver._budget_tracker = None
    driver._health_monitor = None
    return driver


# ---------------------------------------------------------------------------
# Single-provider test
# ---------------------------------------------------------------------------
async def test_provider(spec: dict, api_key: str) -> dict:
    """Call one provider and return a result dict."""
    result: dict = {
        "provider": spec["name"],
        "model": spec["default_model"],
        "latency_ms": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "status": "fail",
        "response_snippet": "",
        "contains_4": False,
        "error": None,
    }

    try:
        driver = _create_driver(spec, api_key)
        result["model"] = driver.model

        t0 = time.monotonic()
        response = await driver.invoke(PROMPT, timeout=60.0)
        elapsed_ms = (time.monotonic() - t0) * 1000

        result["latency_ms"] = round(elapsed_ms, 1)
        result["input_tokens"] = response.input_tokens
        result["output_tokens"] = response.output_tokens

        content = response.content.strip()
        result["response_snippet"] = content[:120]
        result["contains_4"] = "4" in content

        if response.status == DriverResponseStatus.SUCCESS and content:
            result["status"] = "success"
        else:
            result["status"] = "fail"
            result["error"] = response.error_message or "empty response"

    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> list[dict]:
    print("=" * 80)
    print("  NEXUS Live Driver Integration Test")
    print(f"  Prompt: {PROMPT!r}")
    print(f"  Time:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)
    print()

    # Pre-flight: check which keys are available
    for spec in PROVIDERS:
        key = _resolve_key(spec["env_key"])
        tag = "OK" if key else "MISSING KEY"
        print(f"  [{tag:>11s}]  {spec['name']:<10}  ({spec['default_model']})")
    print()

    results: list[dict] = []

    for spec in PROVIDERS:
        api_key = _resolve_key(spec["env_key"])
        if not api_key:
            results.append({
                "provider": spec["name"],
                "model": spec["default_model"],
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "status": "skipped",
                "response_snippet": "",
                "contains_4": False,
                "error": "API key not configured",
            })
            continue

        print(f"  Testing {spec['name']}...", end="", flush=True)
        result = await test_provider(spec, api_key)
        tag = "OK" if result["status"] == "success" else "FAIL"
        print(f"  [{tag}]  {result['latency_ms']}ms")
        results.append(result)

    return results


def print_table(results: list[dict]) -> None:
    """Pretty-print results as an aligned table."""
    header = (
        f"{'Provider':<10} {'Model':<28} {'Latency':>9} "
        f"{'In Tok':>8} {'Out Tok':>8} {'Has 4':>6} {'Status':<8} Response"
    )
    print()
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    for r in results:
        model = (r["model"] or "n/a")[:27]
        latency = f"{r['latency_ms']:.0f}ms" if r["latency_ms"] else "-"
        in_tok = str(r["input_tokens"]) if r["input_tokens"] else "-"
        out_tok = str(r["output_tokens"]) if r["output_tokens"] else "-"
        has_4 = "yes" if r["contains_4"] else "no"
        snippet = (r["response_snippet"] or r.get("error") or "")[:40]

        print(
            f"{r['provider']:<10} {model:<28} {latency:>9} "
            f"{in_tok:>8} {out_tok:>8} {has_4:>6} {r['status']:<8} {snippet}"
        )

    print("-" * len(header))

    ok = sum(1 for r in results if r["status"] == "success")
    total = sum(1 for r in results if r["status"] != "skipped")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"\n  Result: {ok}/{total} passed", end="")
    if skipped:
        print(f" ({skipped} skipped -- missing API key)", end="")
    print()


def save_results(results: list[dict]) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": PROMPT,
        "results": results,
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    results = asyncio.run(main())
    print_table(results)
    save_results(results)

    # Exit with non-zero if any tested provider failed
    failures = [r for r in results if r["status"] not in ("success", "skipped")]
    sys.exit(1 if failures else 0)
