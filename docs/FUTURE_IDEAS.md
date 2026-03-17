# NEXUS — Future Ideas Backlog

Ideas extracted from deleted documentation files during the 2026-03-17 doc cleanup.
Not yet implemented. Ordered by theme.

---

## 1. MCP Server Integration

- Add MCP servers: **GitHub** (issue/PR workflows), **Slack** (notifications), **PostgreSQL** (schema awareness for CEREBRO)
- `nexus-evidence` MCP server: 2 tools (`review_pr`, `get_evidence`) for Claude Desktop + VS Code — not yet built (full spec in `docs/plans/2026-02-26-nexus-evidence-pack-design.md`)

---

## 2. CEREBRO UI & Product

- `MemoryPanel` UI component: drag-and-drop ingestion, namespace selector, coverage stats
- Agent performance dashboard: task completion rate, token usage, error frequency per agent
- Cost tracking per collaboration mode (spend analytics)
- HITL (Human-in-the-Loop) interface: approval workflow UI, not just CLI prompts
- Agent retirement/archival: archive underperforming agents to `workspace/agents/archive/`

---

## 3. Memory System Enhancements

- `RAGNamespaceManager`: per-agent scoped RAG namespaces stored under `.nexus/agent_rags/{agent_name}/`
- `UniversalIngestor` via Docling: supports PDF, DOCX, PPTX, XLSX, images (PNG/JPEG/TIFF), audio (WAV/MP3) — `ingestors/` dir exists but is empty
- API endpoint `POST /api/memory/ingest` with multipart file upload + namespace routing

---

## 4. Intelligence Quality

- **SLM inter-phase compression**: after each HiveMind phase, route output through local Llama-3/4 8B (Ollama driver) before passing to next frontier model — 70-85% inter-phase token reduction. `semantic_compressor.py` exists but SLM routing not wired.
- **Structured Outputs migration** (Epic 1.2): replace `json_parser.py` (339 LOC, fragile regex) with Anthropic/Google native structured output APIs — eliminates JSON parsing errors entirely
- **StagnationPredictor → FSM**: wire the `INTERVENE` signal from `StagnationPredictor` directly into the FSM orchestrator's decision branch (currently the signal is computed but not consumed by the FSM)
- **A/B testing**: HybridBackend vs DenseBackend on real tasks to validate the claimed +15% recall improvement
- **Domain strength matrix**: add OPENAI, DEEPSEEK, KIMI, MINIMAX, OLLAMA rows to `AGENT_DOMAIN_STRENGTHS` in `task_analyzer.py` (currently only Gemini/Claude are scored)
- **EMA weight adaptation**: make `AGENT_DOMAIN_STRENGTHS` learnable over time using Exponential Moving Average — V13 work
- **ML DialogueAct classifier**: replace the current rules-based DialogueAct classification in OutputGuard with a lightweight ML classifier

---

## 5. Product Launch & Monetization

- `nexus_swarm/` public SDK module: `from nexus_swarm import Orchestrator` with 5-line quickstart — not built
- `nexus-evidence` standalone package: dual-agent PR review CLI + MCP server — not built (spec: `docs/plans/`)
- PyPI publication of `nexus-swarm-os` package
- GitHub-ready README with differentiators vs CrewAI / LangGraph / AutoGen
- `examples/` directory: quickstart, cross-model verification, multi-provider failover
- Benchmark harness: reproducible single-model vs multi-model comparison (code review, security, reasoning, cost)
- CEREBRO Cloud deployment with pricing tiers (Free / Pro / Team / Enterprise)

---

## 6. Observability & Verification

- Cache metrics in OTel spans: add `cache_creation_tokens` / `cache_read_tokens` as span attributes — may not be wired to OTel yet
- Verify `NEXUS_FF_PROMPT_CACHING` feature flag exists
- Single-provider mode degradation: verify PARALLEL → SPECIALIST graceful degradation in `hybrid_swarm_engine.py`
- Swarm Engine tool definitions cached (extend prompt caching beyond HiveMind phases)

---

## 7. Code Quality (see also `docs/quality/CODE_QUALITY_REVIEW_2026-02-24.md`)

- **142 print statements** → replace with `logger.info()` (automatable)
- **51 missing return type annotations** on public methods
- **106 global singletons** → refactor to Dependency Injection via `ServiceFactory`
- **21 God Objects** >500 lines: top priority `TrueHiveMind` (1201 LOC), `IndependentAnalysisPhase` (815 LOC)

---

## 8. Auth & API (from V12.0 plan, unverified)

- JWT refresh: "refresh 5 min before expiry" pattern — verify if implemented in CEREBRO
- RBAC multi-user support (admin/user roles) — verify if beyond single-admin
- Rate limiting: 100 req/min per user as CEREBRO API middleware
