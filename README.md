# NEXUS

<div align="center">

**Multi-model collaborative orchestration platform with native provider drivers, cross-model verification, and built-in security.**

[![Version](https://img.shields.io/badge/version-12.4.0-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)

</div>

---

## Why NEXUS

- **7 native SDK drivers** -- Anthropic, Google, OpenAI, DeepSeek, Kimi, MiniMax, and Ollama. Each driver talks directly to the provider SDK (no LiteLLM/LangChain wrappers), with per-driver circuit breakers, failover, and latency tracking built in.

- **Cross-model verification (CFL)** -- Every tool execution is validated by the *opposite* model. If Claude issues a shell command, Gemini reviews the result before the pipeline advances. This Cognitive Feedback Loop catches hallucinated success and silent failures.

- **Security by default** -- InputGuard sanitizes prompts, OutputGuard filters responses, PathGuardian restricts filesystem access, ShadowRedTeam adversarially tests agent outputs, and RBAC + AuditLogger provide access control and audit trails. All layers are active out of the box.

---

## Architecture

```
User Input
    |
    v
+-----------+     +------------------------------------------+
|   REPL    |     |         FSM Orchestrator (12 states)      |
|   MCP     |---->|                                          |
|   API     |     |  BRAINSTORMING <-> EXECUTING_TOOL        |
|   CLI     |     |       |               |                  |
+-----------+     |       v               v                  |
                  |  VALIDATING_CFL   WAITING_USER           |
                  +--------+-----------------+---------------+
                           |                 |
              +------------+-----+    +------+--------+
              |                  |    |               |
              v                  v    v               v
     +----------------+  +----------------+  +----------------+
     |   HiveMind     |  |  Swarm Engine  |  |   Evolution    |
     |  (7 phases)    |  |  (6 modes)     |  |  (spawn/mutate)|
     +-------+--------+  +-------+--------+  +----------------+
             |                    |
             v                    v
     +---------------------------------------------+
     |           Driver Layer (7 providers)         |
     |  Anthropic | Google | OpenAI | DeepSeek      |
     |  Kimi | MiniMax | Ollama                     |
     |  + failover + circuit breaker + cache        |
     +---------------------------------------------+
             |
             v
     +---------------------------------------------+
     |  Security Layer                              |
     |  InputGuard | OutputGuard | PathGuardian     |
     |  ShadowRedTeam | RBAC | AuditLogger         |
     +---------------------------------------------+
```

**HiveMind** runs complex tasks through 7 phases: Analysis, Debate, Architecture, Execution, Diagnosis, Retry, and Consolidation. Each phase coordinates multiple agents toward consensus.

**Swarm Engine** provides 6 collaboration modes: `PARALLEL`, `SEQUENTIAL`, `LEAD_SUPPORT`, `PING_PONG`, `SPECIALIST`, and `RED_BLUE`. Mode selection is auto-routed based on task complexity or set manually.

**Evolution** spawns and mutates specialized agents with deterministic fitness evaluation (AST analysis + pytest).

---

## Products

### Research CLI (Flagship)

Local-first evidence-pack generator. Turns a research question into a reproducible bundle of artifacts: report, sources, trace, reasoning graph, metrics, and SHA-256 manifest.

```bash
nexus-research "How does the authentication module work?" \
  --mode mock \
  --path src/auth/
```

**Outputs**: `report.md`, `sources.json`, `trace.jsonl`, `reasoning_graph.mmd`, `metrics.json`, `manifest.sha256`

Mock mode requires no API keys or network access.

### MCP Server (Companion)

Exposes NEXUS capabilities as an MCP server for Claude Desktop, Cursor, and other MCP-compatible clients.

```bash
nexus-mcp
```

**Claude Desktop configuration** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "nexus": {
      "command": "python",
      "args": ["-m", "core.mcp.server"],
      "cwd": "/path/to/nexus"
    }
  }
}
```

**Exposed tools**: `nexus_research`, `nexus_memory_search`, `nexus_export_evidence_pack`, `nexus_start_evidence_job`, `nexus_job_status`, `nexus_cancel_job`, `nexus_status`, `nexus_read`, `nexus_glob`, `nexus_grep`, `nexus_analyze`, `nexus_bash`

### CEREBRO API

REST + WebSocket API for programmatic access.

```bash
# Start with Docker
docker compose --profile api up -d

# Or standalone
uvicorn core.api.cerebro.app:create_app --factory --host 0.0.0.0 --port 8000
```

- REST endpoints at `http://localhost:8000`
- WebSocket streaming at `ws://localhost:8000/ws/stream`
- OpenAPI docs at `http://localhost:8000/docs`

### Interactive REPL

Full-featured terminal interface with command history, streaming output, and all orchestration capabilities.

```bash
nexus
```

```
nexus7> Analyze this project and suggest improvements
[HiveMind activates: Analysis -> Debate -> Architecture -> Execution]
```

**Commands**: `/swarm <mode> <task>`, `/spawn <role>`, `/learn <path>`, `/rag query <text>`, `/doctor`, `/status`, `/budget`, and more. Run `/help` for the full list.

---

## Supported Providers

| Provider | Driver | Models | SDK |
|----------|--------|--------|-----|
| **Anthropic** | `AnthropicSDKDriver` | claude-opus-4-6, claude-sonnet-4-6 | `anthropic` |
| **Google** | `GoogleGenAISDKDriver` | gemini-3.1-pro-preview, gemini-3-flash-preview | `google-genai` |
| **OpenAI** | `OpenAISDKDriver` | gpt-5.4, gpt-5-mini, gpt-5-nano | `openai` |
| **DeepSeek** | `DeepSeekSDKDriver` | deepseek-chat, deepseek-reasoner | OpenAI-compatible |
| **Moonshot Kimi** | `KimiSDKDriver` | kimi-k2-thinking, kimi-k2-thinking-turbo | OpenAI-compatible |
| **MiniMax** | `MiniMaxSDKDriver` | MiniMax-M2.5, MiniMax-M2.5-HighSpeed | OpenAI-compatible |
| **Ollama** | `OllamaDriver` | Any local model | Local inference |

Model defaults are managed by `core/provider_registry.json` and updated automatically. Set API keys via environment variables (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, etc.) or `.env` file.

Driver mode is configurable: `auto` (SDK when key is available, CLI fallback), `sdk`, or `cli`. Set via `NEXUS_DRIVER_MODE`.

---

## Installation

### From PyPI

```bash
pip install nexus-swarm-os
```

### From Source

```bash
git clone https://github.com/yannabadie/NEXUS.git
cd NEXUS && git checkout NX-CG

# Core only (lightweight, ~20MB)
pip install -e .

# With SDK drivers
pip install -e ".[sdk]"

# With everything (SDK + dense RAG + API + MCP + OTel + dev tools)
pip install -e ".[all]"
```

### Optional Extras

| Extra | What it adds |
|-------|-------------|
| `sdk` | Anthropic, Google, OpenAI SDKs |
| `dense` | LanceDB + sentence-transformers for dense retrieval |
| `ingest` | IBM Docling for PDF/DOCX/PPTX/XLSX ingestion |
| `api` | FastAPI + uvicorn + WebSocket for CEREBRO |
| `mcp` | MCP server protocol |
| `db` | SQLModel + Redis for persistence and event bus |
| `otel` | OpenTelemetry instrumentation |
| `dev` | pytest, ruff, mypy, httpx |
| `all` | Everything above |

---

## Quick Start

### 1. Research CLI (no API keys needed)

```bash
pip install -e .
nexus-research "How does memory indexing work?" --mode mock --path core/memory_pkg/
```

### 2. Interactive REPL

```bash
# Set at least one provider key
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=AI...

nexus
```

### 3. MCP Server

```bash
pip install -e ".[mcp]"
nexus-mcp
```

### 4. CEREBRO API

```bash
pip install -e ".[api]"
uvicorn core.api.cerebro.app:create_app --factory --port 8000
```

---

## Docker

```bash
# Full stack (NEXUS + Redis)
docker compose up -d

# With CEREBRO API
docker compose --profile api up -d

# With observability (OpenTelemetry + Jaeger)
docker compose --profile observability up -d

# Everything
docker compose --profile api --profile observability up -d
```

Set provider API keys in a `.env` file or pass them directly:

```bash
ANTHROPIC_API_KEY=sk-ant-... GOOGLE_API_KEY=AI... docker compose up -d
```

**Services**:
| Service | Port | Description |
|---------|------|-------------|
| `redis` | 6379 | Event bus + state store |
| `nexus` | -- | Backend orchestrator (headless) |
| `cerebro` | 8000 | REST + WebSocket API (profile: `api`) |
| `otel-collector` | 4317/4318 | OTLP gRPC/HTTP (profile: `observability`) |
| `jaeger` | 16686 | Tracing UI (profile: `observability`) |

---

## Security

NEXUS ships with a layered security stack, all active by default:

| Layer | Component | Purpose |
|-------|-----------|---------|
| Input | **InputGuard** | Prompt injection detection, input sanitization |
| Output | **OutputGuard** | Response filtering, dialogue act classification |
| Filesystem | **PathGuardian** | Path traversal prevention, workspace sandboxing |
| Adversarial | **ShadowRedTeam** | Automated red-team testing of agent outputs |
| Access | **RBAC** | Role-based access control with policy enforcement |
| Audit | **AuditLogger** | Immutable action log for compliance |
| Integrity | **IntegrityMonitor** | Critical file hash verification |
| Network | **SSRF Blocklist** | OWASP-compliant URL filtering for `web_fetch` |
| RAG | **Spotlighting** | Data-marking defense against RAG context injection |

Execution runs in Docker sandbox by default. Host execution is opt-in via `NEXUS_FF_HOST_EXECUTION_ALLOWED=true`.

---

## Configuration

NEXUS loads configuration from (in order): `pyproject.toml` -> `.env` -> environment variables -> defaults.

Key environment variables:

```bash
# Provider API keys
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
KIMI_API_KEY=...
MINIMAX_API_KEY=...

# Driver mode (auto | sdk | cli)
NEXUS_DRIVER_MODE=auto

# Feature flags (NEXUS_FF_<FLAG>=true|false)
NEXUS_FF_SANDBOX_ENABLED=true
NEXUS_FF_STREAMING_ENABLED=true
NEXUS_FF_PROMPT_CACHING=true
NEXUS_FF_OTEL_ENABLED=false

# Budget cap (daily USD limit, 0 to disable)
BUDGET_LIMIT_USD=50.0

# Routing policy (balanced | cost_optimized | quality_optimized)
ROUTING_POLICY=balanced
```

Full flag reference in `core/config.py`.

---

## Testing

```bash
# Run all tests
pytest tests/

# With coverage
pytest tests/ --cov=core --cov-fail-under=60

# Specific test file
pytest tests/test_research_cli.py -v

# Skip slow/integration tests
pytest tests/ -m "not slow and not integration"
```

Current test counts, pass/fail/skip breakdown, and coverage are published per CI run in the `evidence-ledger` artifact from CI on `NX-CG`. Use the ledger rather than hardcoded counts for exact numbers.

---

## Project Structure

```
nexus/
  core/
    orchestration_v7.py          # FSM orchestrator
    drivers/                     # 7 provider drivers + failover + cache
    intelligence/
      hive_mind/                 # 7-phase cognitive pipeline
      swarm/                     # 6 collaboration modes
      evolution/                 # Agent spawning and mutation
    execution_pkg/               # Tool execution + routing
    security_pkg/security/       # InputGuard, OutputGuard, PathGuardian, RBAC
    memory_pkg/memory/           # RAG (BM25, TF-IDF, LanceDB, hybrid)
    synapse/                     # Message protocol + reliability
    infrastructure/              # Bootstrap, sessions, circuit breaker
    observability/               # Telemetry, OTel, audit logging
    interface_pkg/               # REPL, MCP server, HITL
    api/cerebro/                 # REST + WebSocket API
    metagraph/                   # AST-based codebase intelligence
    fsm/                         # State machine (12 states)
  interface/ui/cerebro/          # React dashboard (CEREBRO UI)
  tests/                         # Test suite
  prompts/                       # System prompts
  workspace/                     # Runtime data (agents, logs, sessions)
  nexus7.py                      # Entry point
  nexus_research.py              # Research CLI entry point
```

---

## Contributing

1. Read [MISSION.md](MISSION.md) for the project vision
2. Follow code conventions in [CLAUDE.md](CLAUDE.md)
3. All PRs require tests (`pytest tests/ --tb=short` must pass)
4. Use `ruff check core/ tests/` and `ruff format core/ tests/` before committing
5. Commit format: `type(scope): subject` (see `.claude/skills/commit-format.md`)

---

## License

MIT -- see [LICENSE](LICENSE) for details.
