# NEXUS V12.4 "COGNITIVE BOOST" - Quick Start

Get NEXUS running in 3 minutes. Pick your path:

---

## Path A: Research (zero API keys)

The fastest way to see NEXUS work. Uses mock mode with local sparse retrieval.

```bash
pip install -e "."
nexus-research --mode mock "What is the NEXUS architecture?" --limit 3
```

Output: `workspace/research/` with report.md, sources.json, reasoning graph.

---

## Path B: MCP Server (Claude Desktop / IDE)

Expose NEXUS tools to Claude Desktop or any MCP-compatible IDE.

```bash
pip install -e ".[mcp]"
nexus-mcp
```

Add to Claude Desktop config (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "nexus": {
      "command": "nexus-mcp"
    }
  }
}
```

---

## Path C: CEREBRO API (web dashboard)

REST API + WebSocket streaming for the CEREBRO frontend.

```bash
pip install -e ".[api]"
uvicorn core.api.cerebro.app:create_cerebro_app --factory --port 8080
curl http://localhost:8080/health
```

Frontend (optional):
```bash
cd interface/ui/cerebro && npm install && npm run dev
```

---

## Path D: Full AI Mode (Claude + Gemini)

Interactive REPL with real LLM calls.

```bash
pip install -e ".[all]"
export ANTHROPIC_API_KEY=sk-...
export GOOGLE_API_KEY=AIza...
python nexus7.py
```

---

## Install Extras Reference

| Extra | What it adds | Size |
|-------|-------------|------|
| (base) | Core + sparse RAG | ~20MB |
| `dense` | LanceDB + sentence-transformers | ~500MB |
| `ingest` | Document ingestion (docling) | ~200MB |
| `db` | SQLModel + Redis | ~10MB |
| `api` | FastAPI + CEREBRO stack | ~15MB |
| `sdk` | Anthropic + Google GenAI SDKs | ~20MB |
| `mcp` | MCP server protocol | ~5MB |
| `otel` | OpenTelemetry observability | ~10MB |
| `dev` | pytest + ruff + mypy | ~30MB |
| `all` | Everything above | ~800MB |

Combine extras: `pip install -e ".[api,sdk,dev]"`

---

## Smoke Test

Verify your install works:
```bash
python scripts/smoke_test.py
```

---

## Key Files

| File | Purpose |
|------|---------|
| `nexus7.py` | Main REPL entry point |
| `nexus_research.py` | Standalone research tool |
| `core/config.py` | All configuration + feature flags |
| `CLAUDE.md` | Full developer guide |
| `docs/INDEX.md` | Module documentation index |

---

**Need help?** See [CLAUDE.md](CLAUDE.md) for the full developer guide.
