# NEXUS Evidence Pack Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone `nexus-evidence` Python package that transforms PR diffs into verifiable evidence packs via dual-agent analysis (Claude + Gemini), distributed as CLI + MCP server.

**Architecture:** Separate repo `nexus-evidence/` with 5-step pipeline (COLLECT -> DUAL ANALYZE -> CROSS-CHECK -> SYNTHESIZE -> PACKAGE). Mock mode first, live drivers added in S4. MCP server exposes 2 tools for Claude Desktop + VS Code.

**Tech Stack:** Python 3.11+, Pydantic V2, Click (CLI), FastMCP (MCP server), Anthropic SDK, Google GenAI SDK

---

## Week 1 (S1): Package Scaffold + Models + Mock Mode

### Task 1: Create repo and package scaffold

**Files:**
- Create: `C:/Code/nexus-evidence/pyproject.toml`
- Create: `C:/Code/nexus-evidence/README.md`
- Create: `C:/Code/nexus-evidence/src/nexus_evidence/__init__.py`
- Create: `C:/Code/nexus-evidence/.gitignore`
- Create: `C:/Code/nexus-evidence/.github/workflows/ci.yml`

**Step 1: Create repo directory and init git**

```bash
mkdir -p /c/Code/nexus-evidence
cd /c/Code/nexus-evidence
git init
```

**Step 2: Write pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "nexus-evidence"
version = "0.1.0"
description = "Verifiable evidence packs from dual-agent PR review"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [{name = "Yann Abadie"}]
dependencies = [
    "pydantic>=2.0.0",
    "click>=8.0.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
sdk = ["anthropic>=0.70.0", "google-genai>=1.0.0"]
mcp = ["mcp>=1.0.0"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.9.0"]
all = ["nexus-evidence[sdk,mcp,dev]"]

[project.scripts]
nexus-evidence = "nexus_evidence.cli:main"
nexus-evidence-mcp = "nexus_evidence.mcp_server:main"

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM"]
ignore = ["E501", "SIM108"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 3: Write minimal __init__.py**

```python
"""NEXUS Evidence Pack - Verifiable evidence from dual-agent analysis."""
__version__ = "0.1.0"
```

**Step 4: Write .gitignore**

Standard Python .gitignore (venv, __pycache__, .egg-info, dist, build, .env)

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: package scaffold with pyproject.toml and CI"
```

---

### Task 2: Evidence Pack Pydantic models

**Files:**
- Create: `src/nexus_evidence/models/__init__.py`
- Create: `src/nexus_evidence/models/evidence.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
from nexus_evidence.models.evidence import (
    AnalysisResult, EvidencePack, Metrics, Risk, Source, TraceEntry,
)

def test_evidence_pack_creation():
    pack = EvidencePack(
        id="test-001",
        query="Review this PR",
        report_md="# Report\nLooks good.",
        sources=[Source(path="src/main.py", excerpt="def main():", relevance=0.9)],
        trace=[TraceEntry(agent="claude", step="analyze", prompt="review", response="ok", duration_ms=100, cost_usd=0.01)],
        metrics=Metrics(input_tokens=500, output_tokens=200, total_cost_usd=0.01, duration_ms=1500, confidence=0.85, models_used=["claude-sonnet-4-6"]),
        risks=[Risk(severity="high", description="No error handling", file="src/main.py", line=42)],
    )
    assert pack.id == "test-001"
    assert pack.metrics.confidence == 0.85
    assert len(pack.risks) == 1

def test_manifest_generation():
    pack = EvidencePack(
        id="test-002", query="test", report_md="# Test",
        sources=[], trace=[], risks=[],
        metrics=Metrics(input_tokens=0, output_tokens=0, total_cost_usd=0, duration_ms=0, confidence=0, models_used=[]),
    )
    manifest = pack.generate_manifest()
    assert "report.md" in manifest
    assert all(len(v) == 64 for v in manifest.values())  # SHA-256 hex
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Code/nexus-evidence && pip install -e ".[dev]" && pytest tests/test_models.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

```python
# src/nexus_evidence/models/evidence.py
"""Pydantic models for Evidence Pack artefacts."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class Source(BaseModel):
    path: str
    excerpt: str = ""
    relevance: float = 0.0
    url: str | None = None

class Risk(BaseModel):
    severity: str  # "critical", "high", "medium", "low", "info"
    description: str
    file: str | None = None
    line: int | None = None
    suggestion: str | None = None

class TraceEntry(BaseModel):
    agent: str
    step: str
    prompt: str
    response: str
    duration_ms: float
    cost_usd: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AnalysisResult(BaseModel):
    agent: str
    risks: list[Risk] = []
    suggestions: list[str] = []
    tests_missing: list[str] = []
    confidence: float = 0.0
    raw_response: str = ""

class Metrics(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: float = 0.0
    confidence: float = 0.0
    models_used: list[str] = []

class EvidencePack(BaseModel):
    id: str
    query: str
    report_md: str = ""
    sources: list[Source] = []
    trace: list[TraceEntry] = []
    metrics: Metrics = Field(default_factory=Metrics)
    risks: list[Risk] = []
    analyses: list[AnalysisResult] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reasoning_graph_mmd: str = ""
    pr_comment: str = ""

    def generate_manifest(self) -> dict[str, str]:
        """Generate SHA-256 manifest for all artefacts."""
        artefacts = {
            "report.md": self.report_md,
            "sources.json": json.dumps([s.model_dump() for s in self.sources], default=str),
            "trace.jsonl": "\n".join(json.dumps(t.model_dump(), default=str) for t in self.trace),
            "reasoning_graph.mmd": self.reasoning_graph_mmd,
            "metrics.json": json.dumps(self.metrics.model_dump(), default=str),
        }
        return {name: hashlib.sha256(content.encode()).hexdigest() for name, content in artefacts.items()}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: Evidence Pack Pydantic models with manifest generation"
```

---

### Task 3: Mock driver

**Files:**
- Create: `src/nexus_evidence/drivers/__init__.py`
- Create: `src/nexus_evidence/drivers/protocol.py`
- Create: `src/nexus_evidence/drivers/mock.py`
- Test: `tests/test_mock_driver.py`

**Step 1: Write the failing test**

```python
# tests/test_mock_driver.py
import pytest
from nexus_evidence.drivers.mock import MockDriver

@pytest.mark.asyncio
async def test_mock_invoke_returns_analysis():
    driver = MockDriver(agent_name="claude")
    response = await driver.invoke("Review this PR diff")
    assert response.content != ""
    assert response.input_tokens > 0
    assert response.output_tokens > 0
    assert response.cost_usd >= 0

@pytest.mark.asyncio
async def test_mock_driver_deterministic():
    driver = MockDriver(agent_name="gemini", seed=42)
    r1 = await driver.invoke("test")
    r2 = await driver.invoke("test")
    assert r1.content == r2.content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_mock_driver.py -v`
Expected: FAIL

**Step 3: Write protocol.py (minimal from NEXUS)**

```python
# src/nexus_evidence/drivers/protocol.py
"""Driver protocol - simplified from NEXUS core/drivers/protocol.py."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

class DriverStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"

@dataclass
class DriverResponse:
    content: str = ""
    status: DriverStatus = DriverStatus.SUCCESS
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    error: str | None = None

class BaseDriver(ABC):
    @abstractmethod
    async def invoke(self, prompt: str, system_prompt: str | None = None) -> DriverResponse: ...
```

**Step 4: Write mock.py**

```python
# src/nexus_evidence/drivers/mock.py
"""Mock driver for zero-key demos and testing."""
from __future__ import annotations
import json
from .protocol import BaseDriver, DriverResponse, DriverStatus

MOCK_CLAUDE_RESPONSE = json.dumps({
    "risks": [
        {"severity": "high", "description": "Missing error handling in main loop", "file": "src/main.py", "line": 42},
        {"severity": "medium", "description": "No input validation on user data", "file": "src/api.py", "line": 15},
    ],
    "suggestions": ["Add try/except around the database call", "Validate input with Pydantic"],
    "tests_missing": ["test_main_error_handling", "test_api_input_validation"],
    "confidence": 0.82,
})

MOCK_GEMINI_RESPONSE = json.dumps({
    "risks": [
        {"severity": "high", "description": "N+1 query pattern in user list endpoint", "file": "src/api.py", "line": 30},
        {"severity": "low", "description": "Unused import", "file": "src/main.py", "line": 3},
    ],
    "suggestions": ["Use eager loading for user relations", "Remove unused import os"],
    "tests_missing": ["test_user_list_performance", "test_query_count"],
    "confidence": 0.78,
})

class MockDriver(BaseDriver):
    def __init__(self, agent_name: str = "claude", seed: int | None = None):
        self.agent_name = agent_name
        self.seed = seed
        self._response = MOCK_CLAUDE_RESPONSE if "claude" in agent_name else MOCK_GEMINI_RESPONSE

    async def invoke(self, prompt: str, system_prompt: str | None = None) -> DriverResponse:
        return DriverResponse(
            content=self._response,
            status=DriverStatus.SUCCESS,
            input_tokens=len(prompt.split()) * 2,
            output_tokens=len(self._response.split()) * 2,
            cost_usd=0.001,
            model=f"mock-{self.agent_name}",
        )
```

**Step 5: Run tests, verify pass, commit**

Run: `pytest tests/test_mock_driver.py -v`
Expected: 2 PASSED

```bash
git add -A && git commit -m "feat: mock driver with realistic PR review responses"
```

---

### Task 4: Config model

**Files:**
- Create: `src/nexus_evidence/models/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py
from nexus_evidence.models.config import EvidenceConfig

def test_default_config_is_mock():
    config = EvidenceConfig()
    assert config.mode == "mock"

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")
    config = EvidenceConfig.from_env()
    assert config.mode == "live"
    assert config.anthropic_key == "sk-test"

def test_config_mock_mode_no_keys():
    config = EvidenceConfig(mode="mock")
    assert config.anthropic_key is None
```

**Step 2: Run to verify fail, Step 3: Write implementation**

```python
# src/nexus_evidence/models/config.py
"""Configuration for nexus-evidence."""
from __future__ import annotations
import os
from pydantic import BaseModel

class EvidenceConfig(BaseModel):
    mode: str = "mock"  # "mock" or "live"
    anthropic_key: str | None = None
    gemini_key: str | None = None
    output_dir: str = "./evidence-packs"
    budget_limit_usd: float = 1.0
    claude_model: str = "claude-sonnet-4-6"
    gemini_model: str = "gemini-3.1-pro-preview"

    @classmethod
    def from_env(cls) -> EvidenceConfig:
        anthropic = os.getenv("ANTHROPIC_API_KEY")
        gemini = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        mode = "live" if (anthropic or gemini) else "mock"
        return cls(mode=mode, anthropic_key=anthropic, gemini_key=gemini)
```

**Step 4: Run tests, Step 5: Commit**

```bash
pytest tests/test_config.py -v
git add -A && git commit -m "feat: EvidenceConfig with env detection and mock/live modes"
```

---

## Week 2 (S2): Collector + Packager (mock end-to-end)

### Task 5: PR Diff Collector

**Files:**
- Create: `src/nexus_evidence/core/__init__.py`
- Create: `src/nexus_evidence/core/collector.py`
- Test: `tests/test_collector.py`

**Step 1: Write the failing test**

```python
# tests/test_collector.py
import pytest
from pathlib import Path
from nexus_evidence.core.collector import PRCollector

def test_collect_from_git_repo(tmp_path):
    # Create a fake git repo with a diff
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    (tmp_path / "main.py").write_text("def hello():\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path, capture_output=True)
    (tmp_path / "main.py").write_text("def hello():\n    print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=tmp_path, capture_output=True)

    collector = PRCollector(repo_path=tmp_path, branch="feature", base="main")
    context = collector.collect()

    assert context.diff != ""
    assert "main.py" in context.files_changed
    assert len(context.files_changed) == 1

def test_collect_mock_mode():
    collector = PRCollector.mock()
    context = collector.collect()
    assert context.diff != ""
    assert len(context.files_changed) > 0
```

**Step 3: Write implementation** (subprocess git diff + mock fallback)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: PRCollector with git diff extraction and mock mode"
```

---

### Task 6: Evidence Packager (writes 6 artefacts to disk)

**Files:**
- Create: `src/nexus_evidence/core/packager.py`
- Create: `src/nexus_evidence/formats/__init__.py`
- Create: `src/nexus_evidence/formats/markdown.py`
- Create: `src/nexus_evidence/formats/mermaid.py`
- Test: `tests/test_packager.py`

**Step 1: Write the failing test**

```python
# tests/test_packager.py
from pathlib import Path
from nexus_evidence.core.packager import Packager
from nexus_evidence.models.evidence import EvidencePack, Metrics

def test_write_evidence_pack(tmp_path):
    pack = EvidencePack(
        id="pack-001", query="Review PR",
        report_md="# Analysis\nLooks good.",
        sources=[], trace=[], risks=[],
        metrics=Metrics(input_tokens=100, output_tokens=50, total_cost_usd=0.005, duration_ms=500, confidence=0.9, models_used=["mock"]),
        reasoning_graph_mmd="graph TD\n  A[Collect] --> B[Analyze]",
    )
    packager = Packager(output_dir=tmp_path)
    pack_dir = packager.write(pack)

    assert (pack_dir / "report.md").exists()
    assert (pack_dir / "sources.json").exists()
    assert (pack_dir / "trace.jsonl").exists()
    assert (pack_dir / "reasoning_graph.mmd").exists()
    assert (pack_dir / "metrics.json").exists()
    assert (pack_dir / "manifest.sha256").exists()

    # Verify manifest
    manifest_text = (pack_dir / "manifest.sha256").read_text()
    assert "report.md" in manifest_text
```

**Step 3: Implement Packager (JSON writer + manifest), markdown.py, mermaid.py**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: Packager writes 6 artefacts with SHA-256 manifest"
```

---

### Task 7: Mock end-to-end pipeline

**Files:**
- Create: `src/nexus_evidence/core/pipeline.py`
- Test: `tests/test_pipeline_mock.py`

**Step 1: Write the failing test**

```python
# tests/test_pipeline_mock.py
import pytest
from pathlib import Path
from nexus_evidence.core.pipeline import EvidencePipeline
from nexus_evidence.models.config import EvidenceConfig

@pytest.mark.asyncio
async def test_mock_pipeline_produces_pack(tmp_path):
    config = EvidenceConfig(mode="mock", output_dir=str(tmp_path))
    pipeline = EvidencePipeline(config)
    pack_dir = await pipeline.run(query="Review this PR")

    assert pack_dir.exists()
    assert (pack_dir / "report.md").exists()
    assert (pack_dir / "manifest.sha256").exists()

    report = (pack_dir / "report.md").read_text()
    assert "Risk" in report or "risk" in report
```

**Step 3: Implement pipeline.py** (orchestrates COLLECT -> ANALYZE -> SYNTHESIZE -> PACKAGE using mock drivers)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: mock end-to-end pipeline produces complete Evidence Pack"
```

---

### Task 8: CLI entry point

**Files:**
- Create: `src/nexus_evidence/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write test** (Click testing with CliRunner)

```python
# tests/test_cli.py
from click.testing import CliRunner
from nexus_evidence.cli import main

def test_cli_mock_mode(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["review", str(tmp_path), "--mode", "mock"])
    assert result.exit_code == 0
    assert "Evidence Pack" in result.output
```

**Step 3: Implement cli.py** with Click commands: `review`, `version`

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: CLI entry point with review command"
```

---

## Week 3 (S3): MCP Server + IDE configs

### Task 9: MCP server with 2 tools

**Files:**
- Create: `src/nexus_evidence/mcp_server.py`
- Test: `tests/test_mcp_server.py`
- Create: `examples/claude_desktop_config.json`
- Create: `examples/vscode_mcp_settings.json`

**Step 1: Write test** for tool registration and mock invocation

**Step 3: Implement** FastMCP server with `review_pr` and `get_evidence` tools

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: MCP server with review_pr and get_evidence tools"
```

---

### Task 10: IDE configuration examples

**Files:**
- Create: `examples/claude_desktop_config.json`
- Create: `examples/vscode_mcp_settings.json`
- Update: `README.md` with installation + config instructions

**Commit:**

```bash
git add -A && git commit -m "docs: Claude Desktop + VS Code MCP configuration examples"
```

---

## Week 4 (S4): Live drivers + dual-agent analysis

### Task 11: Claude driver (simplified from NEXUS)

**Files:**
- Create: `src/nexus_evidence/drivers/claude.py`
- Test: `tests/test_claude_driver.py`

Extract minimal invoke() from NEXUS `core/drivers/anthropic_sdk_driver.py` (~200 LOC vs 677). Only needs: invoke(prompt, system_prompt) -> DriverResponse.

**Commit:** `feat: Claude SDK driver (simplified from NEXUS)`

---

### Task 12: Gemini driver (simplified from NEXUS)

**Files:**
- Create: `src/nexus_evidence/drivers/gemini.py`
- Test: `tests/test_gemini_driver.py`

Same extraction from `core/drivers/google_genai_sdk_driver.py`.

**Commit:** `feat: Gemini SDK driver (simplified from NEXUS)`

---

### Task 13: Dual-agent analyzer

**Files:**
- Create: `src/nexus_evidence/core/analyzer.py`
- Test: `tests/test_analyzer.py`

Run Claude and Gemini in parallel (asyncio.gather), parse both responses into AnalysisResult.

**Commit:** `feat: dual-agent analyzer with parallel Claude+Gemini invocation`

---

## Week 5 (S5): Cross-check + PR comment + polish

### Task 14: Cross-check engine

**Files:**
- Create: `src/nexus_evidence/core/crosscheck.py`
- Test: `tests/test_crosscheck.py`

Compare two AnalysisResults, find agreements/divergences, calculate confidence.

**Commit:** `feat: cross-check engine with agreement/divergence detection`

---

### Task 15: PR comment formatter

**Files:**
- Create: `src/nexus_evidence/formats/pr_comment.py`
- Test: `tests/test_pr_comment.py`

Generate GitHub/GitLab-compatible markdown comment from EvidencePack.

**Commit:** `feat: PR comment formatter (GitHub/GitLab markdown)`

---

### Task 16: Synthesizer (confidence scoring + Mermaid graph)

**Files:**
- Create: `src/nexus_evidence/core/synthesizer.py`
- Test: `tests/test_synthesizer.py`

Calculate global confidence from dual-agent agreement. Generate Mermaid reasoning graph.

**Commit:** `feat: synthesizer with confidence scoring and Mermaid graph generation`

---

## Week 6 (S6): Release + distribution

### Task 17: CI workflow

**Files:**
- Update: `.github/workflows/ci.yml`

Ruff lint + pytest + py_compile on Python 3.11/3.12/3.13.

**Commit:** `ci: GitHub Actions workflow with lint + test matrix`

---

### Task 18: README polish

**Files:**
- Update: `README.md`

Installation, quickstart (mock + live), MCP config, 90-second demo script.

**Commit:** `docs: README with installation, quickstart, and MCP config`

---

### Task 19: PyPI release

```bash
pip install build twine
python -m build
twine upload dist/*
```

**Commit:** `chore: v0.1.0 release`

---

### Task 20: MCP Registry submission

Submit to GitHub MCP Registry (if available) or document manual install.

**Commit:** `docs: MCP registry submission instructions`

---

## Verification Checklist

After all tasks:

- [ ] `nexus-evidence review --mode mock ./repo` produces 6 artefacts in <5s
- [ ] `nexus-evidence-mcp` starts and exposes 2 tools
- [ ] Claude Desktop config works (tool appears in Claude)
- [ ] VS Code MCP config works (tool appears in Copilot)
- [ ] Live mode with real API keys produces dual-agent analysis
- [ ] `pip install nexus-evidence` installs cleanly from PyPI
- [ ] CI green on 3 Python versions
- [ ] README has 90-second quickstart
