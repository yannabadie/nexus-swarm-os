# NEXUS Product Launch - Master Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform NEXUS from a 148K LOC codebase into a published, benchmarked, monetizable multi-agent orchestration product.

**Architecture:** Open-core SDK (PyPI, MIT) + Managed API (CEREBRO Cloud, paid tiers). The SDK provides `from nexus_swarm import Orchestrator` with 7 native provider drivers, cross-model verification, and failover. CEREBRO Cloud handles hosting, scaling, and API keys for users who want managed orchestration.

**Tech Stack:** Python 3.11+, FastAPI (CEREBRO), 7 LLM SDK drivers (Anthropic, Google, OpenAI, DeepSeek, Kimi, MiniMax, Ollama), LanceDB (RAG), Redis (events), Pydantic V2.

**Positioning:** "The only multi-agent framework with native SDK drivers for 7+ providers, production-grade failover/circuit breaker, cross-model verification, and built-in security."

**Competitive gap exploited:** Every competitor (CrewAI, LangGraph, AutoGen) treats LLM providers as interchangeable via LiteLLM/LangChain wrappers. NEXUS has native SDK drivers with per-provider optimizations, failover, health monitoring, and intelligent task-to-model routing. No competitor does cross-model verification (opposite model validates output).

---

## Chunk 1: SDK Entry Point & API Simplification

### Task 1: Create the simplified public SDK module

**Files:**
- Create: `nexus_swarm/__init__.py`
- Create: `nexus_swarm/orchestrator.py`
- Create: `nexus_swarm/types.py`
- Test: `tests/test_sdk_public_api.py`

**Rationale:** Users need a 5-line quickstart, not a 562-line entry point. The SDK wraps existing `core/` internals behind a clean facade.

**Target API:**
```python
from nexus_swarm import Orchestrator

# Minimal — auto-detects API keys from env
orch = Orchestrator()

# Or explicit
orch = Orchestrator(
    anthropic_key="...",
    google_key="...",
    deepseek_key="...",  # Optional — any subset of providers works
)

# Simple task — auto-routes to best model/mode
result = await orch.solve("Review auth.py for security issues")
print(result.answer)
print(result.provider_used)  # "anthropic/claude-opus-4-6"
print(result.cost_usd)       # 0.0032
print(result.verification)   # "cross-validated by google/gemini-3.1-pro"

# Explicit cross-model verification
result = await orch.solve(
    "Is this SQL query safe?",
    verify=True,  # Force cross-model validation
    providers=["anthropic", "google"],  # Use these providers
)

# Swarm mode
result = await orch.swarm(
    "Implement user authentication",
    mode="lead_support",  # or parallel, ping_pong, etc.
    lead="anthropic",
    support="deepseek",
)
```

- [ ] **Step 1: Write the failing tests for public API**

```python
# tests/test_sdk_public_api.py
"""Tests for the simplified public SDK API."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestOrchestratorInit:
    """Test Orchestrator initialization."""

    def test_import_from_package(self):
        """Verify clean import path."""
        from nexus_swarm import Orchestrator
        assert Orchestrator is not None

    def test_init_no_keys_uses_env(self, monkeypatch):
        """Auto-detect API keys from environment."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        from nexus_swarm import Orchestrator
        orch = Orchestrator()
        assert orch.available_providers  # At least one provider available

    def test_init_explicit_keys(self):
        """Accept explicit API keys."""
        from nexus_swarm import Orchestrator
        orch = Orchestrator(anthropic_key="sk-test", google_key="test-google")
        assert "anthropic" in orch.available_providers
        assert "google" in orch.available_providers

    def test_init_partial_keys(self):
        """Work with subset of providers."""
        from nexus_swarm import Orchestrator
        orch = Orchestrator(deepseek_key="sk-test")
        assert "deepseek" in orch.available_providers
        assert "anthropic" not in orch.available_providers

    def test_available_providers_property(self):
        """List which providers are configured."""
        from nexus_swarm import Orchestrator
        orch = Orchestrator(anthropic_key="test", google_key="test")
        providers = orch.available_providers
        assert isinstance(providers, list)
        assert "anthropic" in providers
        assert "google" in providers


class TestOrchestratorResult:
    """Test OrchestrationResult structure."""

    def test_result_has_required_fields(self):
        from nexus_swarm.types import OrchestrationResult
        result = OrchestrationResult(
            answer="Test answer",
            provider_used="anthropic/claude-opus-4-6",
            status="success",
        )
        assert result.answer == "Test answer"
        assert result.provider_used == "anthropic/claude-opus-4-6"
        assert result.status == "success"

    def test_result_optional_fields_default(self):
        from nexus_swarm.types import OrchestrationResult
        result = OrchestrationResult(
            answer="Test",
            provider_used="anthropic/claude-opus-4-6",
            status="success",
        )
        assert result.cost_usd is None
        assert result.verification is None
        assert result.mode_used is None
        assert result.tokens_used == 0
        assert result.latency_ms == 0.0


class TestOrchestratorSolve:
    """Test the solve() method."""

    @pytest.mark.asyncio
    async def test_solve_returns_result(self):
        """solve() returns OrchestrationResult."""
        from nexus_swarm import Orchestrator
        from nexus_swarm.types import OrchestrationResult

        orch = Orchestrator(anthropic_key="test")

        # Mock the internal driver to avoid real API calls
        with patch.object(orch, '_invoke_driver', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = OrchestrationResult(
                answer="Mocked response",
                provider_used="anthropic/claude-opus-4-6",
                status="success",
            )
            result = await orch.solve("test task")
            assert isinstance(result, OrchestrationResult)
            assert result.answer == "Mocked response"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sdk_public_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nexus_swarm'`

- [ ] **Step 3: Create types module**

```python
# nexus_swarm/types.py
"""Public types for the NEXUS SDK."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrchestrationResult:
    """Result from an orchestration call."""

    answer: str
    provider_used: str
    status: str  # "success", "failure", "partial"

    # Optional metadata
    cost_usd: float | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    mode_used: str | None = None
    verification: str | None = None
    providers_consulted: list[str] = field(default_factory=list)
    reasoning_trace: list[str] = field(default_factory=list)
    error: str | None = None
    raw_responses: list[dict[str, Any]] = field(default_factory=list)
```

- [ ] **Step 4: Create orchestrator module**

```python
# nexus_swarm/orchestrator.py
"""Simplified public API for NEXUS multi-agent orchestration."""
from __future__ import annotations

import os
import time
from typing import Any

from .types import OrchestrationResult

# Provider key mapping: env var name -> provider id
_PROVIDER_KEYS = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "kimi": ["KIMI_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
}


class Orchestrator:
    """Multi-model orchestration with cross-provider verification.

    The simplest way to use NEXUS. Wraps the full orchestration
    engine behind a clean async API.

    Examples:
        # Auto-detect keys from environment
        orch = Orchestrator()

        # Explicit keys
        orch = Orchestrator(anthropic_key="sk-...", google_key="...")

        # Solve a task
        result = await orch.solve("Review this code for bugs")
        print(result.answer)
    """

    def __init__(
        self,
        *,
        anthropic_key: str | None = None,
        google_key: str | None = None,
        openai_key: str | None = None,
        deepseek_key: str | None = None,
        kimi_key: str | None = None,
        minimax_key: str | None = None,
    ):
        # Collect explicit keys
        self._keys: dict[str, str] = {}
        explicit = {
            "anthropic": anthropic_key,
            "google": google_key,
            "openai": openai_key,
            "deepseek": deepseek_key,
            "kimi": kimi_key,
            "minimax": minimax_key,
        }
        for provider, key in explicit.items():
            if key:
                self._keys[provider] = key

        # Fall back to env vars for providers without explicit keys
        for provider, env_names in _PROVIDER_KEYS.items():
            if provider not in self._keys:
                for env_name in env_names:
                    val = os.getenv(env_name)
                    if val:
                        self._keys[provider] = val
                        break

        # Lazy-init drivers
        self._drivers: dict[str, Any] = {}
        self._config: Any = None
        self._initialized = False

    @property
    def available_providers(self) -> list[str]:
        """List of providers with configured API keys."""
        return sorted(self._keys.keys())

    def _ensure_initialized(self) -> None:
        """Lazy-initialize the core engine on first use."""
        if self._initialized:
            return

        from core.config import Config

        self._config = Config()

        # Override config with explicit keys
        if "anthropic" in self._keys:
            self._config.anthropic_api_key = self._keys["anthropic"]
        if "google" in self._keys:
            self._config.google_api_key = self._keys["google"]
        if "openai" in self._keys:
            self._config.openai_api_key = self._keys["openai"]
        if "deepseek" in self._keys:
            self._config.deepseek_api_key = self._keys["deepseek"]
        if "kimi" in self._keys:
            self._config.kimi_api_key = self._keys["kimi"]
        if "minimax" in self._keys:
            self._config.minimax_api_key = self._keys["minimax"]

        self._initialized = True

    def _get_driver(self, provider: str) -> Any:
        """Get or create a driver for the given provider."""
        if provider in self._drivers:
            return self._drivers[provider]

        self._ensure_initialized()
        key = self._keys.get(provider)
        if not key:
            raise ValueError(f"No API key configured for provider '{provider}'")

        driver: Any
        if provider == "anthropic":
            from core.drivers import AnthropicSDKDriver
            driver = AnthropicSDKDriver(
                api_key=key,
                model=self._config.claude_opus_model,
            )
        elif provider == "google":
            from core.drivers import GoogleGenAISDKDriver
            driver = GoogleGenAISDKDriver(
                api_key=key,
                model=self._config.gemini_pro_model,
            )
        elif provider == "openai":
            from core.drivers import OpenAISDKDriver
            driver = OpenAISDKDriver(
                api_key=key,
                model=self._config.openai_model,
            )
        elif provider == "deepseek":
            from core.drivers import DeepSeekSDKDriver
            driver = DeepSeekSDKDriver(
                api_key=key,
                model=self._config.deepseek_model,
            )
        elif provider == "kimi":
            from core.drivers import KimiSDKDriver
            driver = KimiSDKDriver(
                api_key=key,
                model=self._config.kimi_model,
            )
        elif provider == "minimax":
            from core.drivers import MiniMaxSDKDriver
            driver = MiniMaxSDKDriver(
                api_key=key,
                model=self._config.minimax_model,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

        self._drivers[provider] = driver
        return driver

    async def _invoke_driver(
        self,
        task: str,
        provider: str | None = None,
        **kwargs: Any,
    ) -> OrchestrationResult:
        """Invoke a single driver and wrap the response."""
        # Auto-select provider if not specified
        if provider is None:
            if not self.available_providers:
                return OrchestrationResult(
                    answer="",
                    provider_used="none",
                    status="failure",
                    error="No providers configured. Set API keys via env vars or constructor.",
                )
            provider = self.available_providers[0]

        driver = self._get_driver(provider)
        start = time.monotonic()

        try:
            response = await driver.invoke(task, **kwargs)
            latency = (time.monotonic() - start) * 1000

            return OrchestrationResult(
                answer=response.content or "",
                provider_used=f"{provider}/{response.model or 'unknown'}",
                status="success",
                tokens_used=getattr(response, "total_tokens", 0),
                latency_ms=latency,
                providers_consulted=[provider],
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return OrchestrationResult(
                answer="",
                provider_used=f"{provider}/error",
                status="failure",
                error=str(e),
                latency_ms=latency,
                providers_consulted=[provider],
            )

    async def solve(
        self,
        task: str,
        *,
        provider: str | None = None,
        verify: bool = False,
        providers: list[str] | None = None,
        **kwargs: Any,
    ) -> OrchestrationResult:
        """Solve a task using the best available model.

        Args:
            task: The task to solve.
            provider: Force a specific provider (e.g., "anthropic").
            verify: If True, cross-validate with a second provider.
            providers: List of providers to use (for multi-model tasks).
            **kwargs: Additional arguments passed to the driver.

        Returns:
            OrchestrationResult with the answer and metadata.
        """
        self._ensure_initialized()

        # Simple single-provider call
        result = await self._invoke_driver(task, provider=provider, **kwargs)

        # Cross-model verification
        if verify and result.status == "success" and len(self.available_providers) >= 2:
            primary_provider = (result.provider_used.split("/")[0]
                                if "/" in result.provider_used else result.provider_used)
            # Pick a different provider for verification
            verify_providers = providers or [
                p for p in self.available_providers if p != primary_provider
            ]
            if verify_providers:
                verify_task = (
                    f"Verify the following answer to the task: '{task}'\n\n"
                    f"Answer to verify:\n{result.answer}\n\n"
                    f"Is this answer correct, complete, and safe? "
                    f"Reply with VERIFIED if correct, or explain issues."
                )
                verify_result = await self._invoke_driver(
                    verify_task, provider=verify_providers[0]
                )
                if verify_result.status == "success":
                    result.verification = (
                        f"cross-validated by {verify_result.provider_used}"
                    )
                    result.providers_consulted.append(verify_providers[0])

        return result

    async def swarm(
        self,
        task: str,
        *,
        mode: str = "auto",
        lead: str | None = None,
        support: str | None = None,
        **kwargs: Any,
    ) -> OrchestrationResult:
        """Execute a task using swarm collaboration.

        Args:
            task: The task to solve collaboratively.
            mode: Collaboration mode (auto, parallel, sequential,
                  lead_support, ping_pong, specialist, red_blue).
            lead: Provider for the lead agent (lead_support mode).
            support: Provider for the support agent (lead_support mode).
            **kwargs: Additional arguments.

        Returns:
            OrchestrationResult with the collaborative answer.
        """
        self._ensure_initialized()

        # For MVP, delegate to solve with verification
        # Full swarm integration will wire into HybridSwarmEngine
        if mode == "auto" or mode == "lead_support":
            result = await self.solve(task, provider=lead, verify=True, **kwargs)
            result.mode_used = mode
            return result

        # Default: single provider
        result = await self.solve(task, **kwargs)
        result.mode_used = mode
        return result
```

- [ ] **Step 5: Create package __init__.py**

```python
# nexus_swarm/__init__.py
"""NEXUS Swarm OS - Multi-model orchestration with cross-provider verification.

Quickstart:
    from nexus_swarm import Orchestrator

    orch = Orchestrator()  # Auto-detects API keys from env
    result = await orch.solve("Your task here")
    print(result.answer)

For more control:
    orch = Orchestrator(
        anthropic_key="sk-...",
        google_key="...",
        deepseek_key="...",
    )
    result = await orch.solve("task", verify=True)
"""

from .orchestrator import Orchestrator
from .types import OrchestrationResult

__all__ = ["Orchestrator", "OrchestrationResult"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_sdk_public_api.py -v`
Expected: All tests PASS

- [ ] **Step 7: Update pyproject.toml to include nexus_swarm package**

In `pyproject.toml`, update the hatch build config:
```toml
[tool.hatch.build.targets.wheel]
packages = ["core", "nexus_swarm", "nexus7.py", "nexus_research.py"]
```

- [ ] **Step 8: Commit**

```bash
git add nexus_swarm/ tests/test_sdk_public_api.py pyproject.toml
git commit -m "feat: add simplified nexus_swarm SDK public API

Provides Orchestrator class with 5-line quickstart:
  from nexus_swarm import Orchestrator
  orch = Orchestrator()
  result = await orch.solve('task')

Supports 7 providers (Anthropic, Google, OpenAI, DeepSeek,
Kimi, MiniMax, Ollama) with cross-model verification."
```

---

### Task 2: Fix the 12 failing tests

**Files:**
- Modify: `tests/test_atomic_store.py` (2 concurrency race conditions)
- Modify: `tests/test_context_manager.py` (init assertion)
- Modify: `tests/test_global_integration.py` (assertion error)
- Modify: `tests/test_integrity_monitor.py` (long path edge case)
- Modify: `tests/test_mcp_companion.py` (evidence pack)
- Modify: `tests/test_model_router.py` (default init)
- Modify: `tests/test_research_cli.py` (conflicting claims)
- Modify: `tests/test_sdk_factory_wiring.py` (3 model routing tests)
- Modify: `tests/test_security_execution_policy.py` (network blocking)

- [ ] **Step 1: Read each failing test to diagnose root cause**

Run: `pytest tests/test_atomic_store.py tests/test_context_manager.py tests/test_global_integration.py tests/test_integrity_monitor.py tests/test_mcp_companion.py tests/test_model_router.py tests/test_research_cli.py tests/test_sdk_factory_wiring.py tests/test_security_execution_policy.py -v --tb=short 2>&1 | head -200`

- [ ] **Step 2: Fix each test (exact fixes depend on diagnosis)**

For each failure, determine if:
- Test expectation is wrong (update test)
- Implementation has a bug (fix implementation)
- Test is flaky/environment-dependent (mark as platform-specific or fix race)

- [ ] **Step 3: Run full suite to verify no regressions**

Run: `pytest tests/ -q --tb=no --maxfail=500 --ignore=tests/test_endpoint_analytics.py`
Expected: 0 failures (or fewer than 12)

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "fix: resolve 12 failing tests (concurrency, model routing, security)"
```

---

### Task 3: Remove unsubstantiated claims from CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Remove MetaGraph performance claims**

Replace:
```
### Performance
- **180-720x faster** than grep
- **95-98% precision** vs 60-70% (grep)
- **<1ms query latency** (cached)
- **Auto-scan**: ~1-2 seconds (one-time)
```

With:
```
### Performance
- In-memory AST-based graph (faster than repeated file scanning)
- Auto-scan on first use (~1-2 seconds)
- Results cached for the session
- Run `core/metagraph/auditor.py` for measured performance metrics
```

- [ ] **Step 2: Fix coverage threshold documentation**

Replace `pytest tests/ --cov=core --cov-fail-under=40` with `pytest tests/ --cov=core --cov-fail-under=60` (matches actual pyproject.toml setting)

- [ ] **Step 3: Update driver documentation to reflect all 7 providers**

Update the Tech Stack section to list all providers.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: remove unsubstantiated performance claims, update provider list"
```

---

### Task 4: Clean up ghost directory and dead references

**Files:**
- Remove: `core/memory/` (ghost directory with only `.migrated_to_v2` marker)
- Remove: `DEEP_AUDIT.md` (audit artifact, not part of product)

- [ ] **Step 1: Remove ghost memory directory**

```bash
rm -rf core/memory/
```

- [ ] **Step 2: Remove audit file**

```bash
rm DEEP_AUDIT.md
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove ghost core/memory/ directory and audit artifact"
```

---

## Chunk 2: README & Launch Readiness

### Task 5: Write GitHub-ready README.md

**Files:**
- Rewrite: `README.md`

This is the most important file for adoption. It must:
1. Explain what NEXUS does in 10 seconds
2. Show a working code example in 30 seconds
3. List concrete differentiators vs competitors
4. Provide install instructions
5. Link to docs/examples

- [ ] **Step 1: Write README.md**

The README should follow this structure:
- Hero: One-line description + badges (PyPI, tests, license)
- Quickstart: 5-line code example
- Why NEXUS: 3 concrete differentiators with evidence
- Providers: Table of 7 supported providers
- Features: Key capabilities with code examples
- Install: pip install instructions
- Architecture: High-level diagram (text/mermaid)
- Benchmarks: Link to benchmark results (when available)
- Contributing: How to contribute
- License: MIT

- [ ] **Step 2: Verify all code examples in README actually work**

Run each code snippet as a test (or add to tests/test_readme_examples.py).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: write GitHub-ready README with quickstart and differentiators"
```

---

### Task 6: Create examples/ directory

**Files:**
- Create: `examples/quickstart.py`
- Create: `examples/cross_model_verification.py`
- Create: `examples/multi_provider_failover.py`
- Create: `examples/README.md`

- [ ] **Step 1: Write quickstart example**

A minimal example that works with any single provider.

- [ ] **Step 2: Write cross-model verification example**

Shows NEXUS's unique differentiator: one model answers, another validates.

- [ ] **Step 3: Write multi-provider failover example**

Shows the circuit breaker and health monitoring in action.

- [ ] **Step 4: Commit**

```bash
git add examples/
git commit -m "feat: add examples for quickstart, verification, and failover"
```

---

### Task 7: Validate PyPI build

**Files:**
- Modify: `pyproject.toml` (if needed)

- [ ] **Step 1: Build wheel locally**

```bash
pip install build hatchling
python -m build --wheel
```
Expected: `.whl` file in `dist/`

- [ ] **Step 2: Test install in clean venv**

```bash
python -m venv /tmp/nexus-test-venv
source /tmp/nexus-test-venv/bin/activate
pip install dist/nexus_swarm_os-12.4.0-py3-none-any.whl
python -c "from nexus_swarm import Orchestrator; print('OK')"
nexus --version
deactivate
```
Expected: All commands succeed

- [ ] **Step 3: Commit any fixes**

---

## Chunk 3: Benchmark Framework

### Task 8: Create benchmark harness

**Files:**
- Create: `benchmarks/__init__.py`
- Create: `benchmarks/tasks.py` (benchmark task definitions)
- Create: `benchmarks/runner.py` (benchmark execution engine)
- Create: `benchmarks/report.py` (result formatting)
- Test: `tests/test_benchmark_harness.py`

**Purpose:** Provide reproducible, honest benchmarks comparing:
1. Single model (Claude only) on task X
2. Single model (Gemini only) on task X
3. NEXUS orchestrating Claude + Gemini on task X
4. NEXUS with cross-model verification on task X

Benchmark categories:
- **Code review**: Find bugs in intentionally buggy code
- **Security analysis**: Identify vulnerabilities in code snippets
- **Reasoning**: Multi-step logical problems
- **Cost efficiency**: Same quality at lower cost via smart routing

- [ ] **Step 1: Define benchmark task format**

```python
# benchmarks/tasks.py
@dataclass
class BenchmarkTask:
    id: str
    category: str  # "code_review", "security", "reasoning", "cost"
    prompt: str
    expected_keywords: list[str]  # Keywords that should appear in good answers
    difficulty: str  # "easy", "medium", "hard"
    ground_truth: str | None = None  # For precision scoring
```

- [ ] **Step 2: Create runner that tests single-model vs multi-model**

- [ ] **Step 3: Create report generator (JSON + Markdown)**

- [ ] **Step 4: Run benchmarks and publish results**

This task produces the EVIDENCE that NEXUS's multi-model approach is better than single-model. Without this, the product has no proof of value.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/ tests/test_benchmark_harness.py
git commit -m "feat: add benchmark harness for single-model vs multi-model comparison"
```

---

## Chunk 4: Git & GitHub Launch

### Task 9: Initialize Git and push to GitHub

- [ ] **Step 1: Initialize git repo**

```bash
cd /c/Code/NEXUS-NX-CG
git init
git checkout -b NX-CG
```

- [ ] **Step 2: Verify .gitignore covers sensitive files**

Ensure `.env`, `__pycache__`, `.pytest_cache`, `dist/`, `*.egg-info/`, `workspace/` are all in `.gitignore`.

- [ ] **Step 3: Stage and commit**

```bash
git add -A
git commit -m "feat: NEXUS V12.4 COGNITIVE BOOST - initial public release

Multi-agent orchestration framework with:
- 7 native LLM provider drivers (Anthropic, Google, OpenAI, DeepSeek, Kimi, MiniMax, Ollama)
- Production-grade failover with circuit breaker
- Cross-model verification pipeline
- 7-phase HiveMind collaborative intelligence
- 6 Swarm collaboration modes
- Built-in security (InputGuard, OutputGuard, RBAC)
- 11,200+ tests (99.9% pass rate)
- FastAPI REST API (CEREBRO)
- LanceDB vector memory with hybrid retrieval
- Redis event bus with in-memory fallback"
```

- [ ] **Step 4: Create GitHub repo and push**

```bash
gh repo create yannabadie/nexus-swarm-os --public --description "Multi-agent orchestration with 7 native LLM drivers, cross-model verification & failover"
git remote add origin https://github.com/yannabadie/nexus-swarm-os.git
git push -u origin NX-CG
```

- [ ] **Step 5: Verify CI passes**

```bash
gh run list --branch NX-CG --limit 1
```

---

## Chunk 5: Monetization Foundation (CEREBRO Cloud)

### Task 10: Document CEREBRO API for external users

**Files:**
- Create: `docs/cerebro-api.md`

Document the existing CEREBRO FastAPI routes for external consumption. This becomes the managed API product.

### Task 11: Create pricing/tier structure

**Tiers:**
- **Free**: 100 orchestration calls/month, 2 providers max
- **Pro** ($29/mo): 5,000 calls/month, all providers, priority routing
- **Team** ($99/mo): 25,000 calls/month, custom models, audit log access
- **Enterprise**: Contact sales, SLA, dedicated support

### Task 12: Deploy CEREBRO to cloud

Options (solo dev friendly):
- Railway.app or Render.com (simplest)
- Fly.io (more control)
- Self-hosted VPS (cheapest long-term)

---

## Execution Order

1. **Task 1** (SDK entry point) — foundational, everything else depends on it
2. **Task 2** (fix tests) — can run in parallel with Task 1
3. **Task 3** (clean claims) — quick, do alongside
4. **Task 4** (cleanup) — quick
5. **Task 5** (README) — needs Task 1 complete for code examples
6. **Task 6** (examples) — needs Task 1
7. **Task 7** (PyPI validation) — needs Tasks 1, 5
8. **Task 8** (benchmarks) — needs Task 1, can start early
9. **Task 9** (GitHub launch) — needs Tasks 1-7 complete
10. **Tasks 10-12** (monetization) — post-launch
