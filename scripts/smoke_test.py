#!/usr/bin/env python3
"""
NEXUS FORGE 2026 - Smoke Test Suite

Verifies the Golden Path commands work without external dependencies.
Runs in <60s, requires no API keys.

Usage:
    python scripts/smoke_test.py
"""

import subprocess
import sys
import time
from pathlib import Path

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"

results: list[tuple[str, str, str]] = []


def run_test(name: str, func):
    """Run a test and record the result."""
    try:
        msg = func()
        results.append((name, "PASS", msg or ""))
        print(f"  [{PASS}] {name}")
    except ImportError as e:
        results.append((name, "SKIP", str(e)))
        print(f"  [{SKIP}] {name} ({e})")
    except Exception as e:
        results.append((name, "FAIL", str(e)))
        print(f"  [{FAIL}] {name} ({e})")


def test_core_config():
    """Test 1: Base import - core.config must work with base-only install."""
    from core.config import Config
    cfg = Config()
    assert cfg.nexus_version == "12.4.0", f"Expected 12.4.0, got {cfg.nexus_version}"
    return f"v{cfg.nexus_version}"


def test_core_import():
    """Test 2: core package import."""
    import core
    assert hasattr(core, "__version__")
    return f"v{core.__version__}"


def test_research_mock():
    """Test 3: Research mock mode (no API keys needed)."""
    result = subprocess.run(
        [sys.executable, "nexus_research.py", "--mode", "mock", "test query", "--limit", "1"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr[-200:]}"
    assert "Evidence pack written to:" in result.stderr or "Evidence pack written to:" in result.stdout
    return "evidence pack generated"


def test_cerebro_import():
    """Test 4: CEREBRO app factory (requires [api] extras)."""
    from core.api.cerebro.app import create_cerebro_app
    app = create_cerebro_app()
    assert app is not None
    return "app created"


def test_mcp_import():
    """Test 5: MCP server import (requires [mcp] extras)."""
    from core.interface_pkg.mcp.server import main
    assert callable(main)
    return "main() callable"


def test_project_memory():
    """Test 6: ProjectMemory with sparse backend."""
    from core.memory_pkg.memory.project_memory import ProjectMemory
    pm = ProjectMemory(nexus_root=Path(__file__).parent.parent)
    assert pm is not None
    return "initialized OK"


def test_pydantic_models():
    """Test 7: Core pydantic models load."""
    from core.synapse.protocol_v7 import LightMessageV7
    msg = LightMessageV7(
        content="test",
        agent_id="test-agent",
        sender="user",
        action_type="message",
    )
    assert msg.content == "test"
    assert msg.sender is not None
    return "LightMessageV7 OK"


def test_feature_flags():
    """Test 8: Feature flags from env."""
    from core.config import FeatureFlags
    flags = FeatureFlags.from_env()
    assert isinstance(flags.rag_datamarking, bool)
    return f"{len(flags.__dataclass_fields__)} flags"


def main():
    print("\n" + "=" * 60)
    print("  NEXUS FORGE 2026 - Smoke Test Suite")
    print("=" * 60 + "\n")

    start = time.time()

    run_test("Core config import", test_core_config)
    run_test("Core package import", test_core_import)
    run_test("Research mock mode", test_research_mock)
    run_test("CEREBRO app factory", test_cerebro_import)
    run_test("MCP server import", test_mcp_import)
    run_test("ProjectMemory (sparse)", test_project_memory)
    run_test("Pydantic models", test_pydantic_models)
    run_test("Feature flags", test_feature_flags)

    elapsed = time.time() - start

    # Summary
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    skipped = sum(1 for _, s, _ in results if s == "SKIP")

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped ({elapsed:.1f}s)")
    print(f"{'=' * 60}\n")

    if failed > 0:
        print("Failed tests:")
        for name, status, msg in results:
            if status == "FAIL":
                print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print("All smoke tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
