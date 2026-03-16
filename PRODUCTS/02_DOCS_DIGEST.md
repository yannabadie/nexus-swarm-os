# Docs Digest

## Root Docs and Global References
- `README.md`: product overview, quick start, test commands, contribution notes.
- `MISSION.md`: core vision and immutable collaboration principles.
- `ROADMAP.md`: versioned roadmap and current status (V12.4).
- `ARCHITECTURE_MAP.md`: C4-style architecture maps and component flow details.
- `INVARIANTS.md`: immutable rules tied to `KERNEL.py`.
- `KERNEL.py` + `KERNEL_HASH.txt`: alignment constants and integrity checks.
- `requirements.txt`, `requirements_v7.txt`: Python dependency sets.
- `docker-compose.yml`: Redis service for CEREBRO events/workflow.

## Module READMEs (Core)
- `core/README.md`: core architecture overview, layers, entry points.
- `core/bootstrap/README.md`: project bootstrap, agent discovery, spinoff support.
- `core/interface/README.md`: REPL, slash commands, CLI flow.
- `core/interface/commands/README.md`: command registry and handlers.
- `core/workspace/README.md`: workspace lifecycle and isolation.
- `core/interaction/README.md`: interaction provider abstraction and HITL.
- `core/agents/README.md`: unified agent registry, spawning service, DyLAN tracking.
- `core/async_primitives/README.md`: cancellation, blackboard, event bus, task manager.
- `core/fsm/README.md`: FSM states, transitions, health monitoring.
- `core/hive_mind/README.md`: 7-phase pipeline and breakpoints.
- `core/hive_mind/phases/README.md`: per-phase responsibilities.
- `core/swarm/README.md`: mode negotiation and execution engine.
- `core/swarm/executors/README.md`: implementations for 6 swarm modes.
- `core/execution/README.md`: tool registry, handlers, validation.
- `core/execution/handlers/README.md`: tool handler categories and APIs.
- `core/drivers/README.md`: driver protocol and provider adapters.
- `core/synapse/README.md`: agent message schemas, auto-repair protocol rules.
- `core/routing/README.md`: model routing decisions and DyLAN integration.
- `core/memory/README.md`: memory layers, backends, and RAG.
- `core/memory/backends/README.md`: TF-IDF, BM25, dense, hybrid backends.
- `core/memory/ingestors/README.md`: multi-format ingestion pipeline.
- `core/security/README.md`: defense-in-depth security stack.
- `core/governance/README.md`: sandbox policy and red team validation.
- `core/telemetry/README.md`: budget tracking and telemetry export.
- `core/logging/README.md`: structured logging and driver logs.
- `core/notifications/README.md`: email/REPL/file alerts.
- `core/api/README.md`: rate limiting and concurrency control.
- `core/api/cerebro/README.md`: FastAPI control plane overview.
- `core/api/cerebro/routes/README.md`: REST/WS routes and RBAC patterns.
- `core/db/README.md`: SQLModel data model and tenancy.
- `core/events/README.md`: Redis event bus for UI.
- `core/workflow/README.md`: Redis workflow registry, distributed locks, TTL cleanup.
- `core/session/README.md`: HOME isolation and workspace management.
- `core/orchestration/README.md`: orchestration components extracted from OrchestratorV7.
- `core/prompts/README.md`: prompt loader and includes.
- `core/adapters/README.md`: analysis type adapters.
- `core/audit/README.md`: audit log and HITL persistence.
- `core/meta/README.md`: CLI/tool introspection.
- `core/reasoning/README.md`: placeholders for GoT/ToT.
- `core/mcp/README.md`: MCP client/server integration.
- `core/evolution/README.md`: evolution pipeline, validators.
- `core/evolution/phases/README.md`: brainstorm/create/promote phases.
- `core/utils/README.md`: JSON extraction, atomic store, async helpers.
- `core/ui/README.md`: Rich-based console output.
- `core/context/README.md`: tenant context via contextvars.
- `core/resilience/README.md`: circuit breakers and system health.

## Module READMEs (Tests)
- `tests/README.md`: test suite overview and run commands.
- `tests/api/README.md`: RBAC tests.
- `tests/audit/README.md`: isolation and audit validation.
- `tests/fsm/README.md`: hibernate + stagnation predictor tests.
- `tests/interaction/README.md`: HITL persistence tests.
- `tests/fixtures/README.md`: mocks and fixtures.
- `tests/proofs/README.md`: proof-style smoke tests.
- `tests/workflow/README.md`: Redis workflow registry and locks.
- `tests/torture/README.md`: chaos/resilience tests.
- `tests/torture/scenarios/README.md`: scenario catalog.
- `tests/v10/README.md`: PRISM isolation suite.
- `tests/v11/README.md`: SENTINEL security suite.

## Module READMEs (Docs, Tools, Prompts, UI)
- `docs/README.md`: documentation index with architecture/security/API references.
- `docs/workflows/README.md`: backend/frontend/system workflows.
- `docs/archive/README.md`: archived legacy artifacts.
- `tools/README.md`: tooling overview (doc generator).
- `scripts/README.md`: maintenance scripts and usage.
- `prompts/README.md`: prompt directory structure and usage.
- `interface/ui/cerebro/README.md`: React dashboard stack, commands, tests.

## Audit and Memory Bank
- `audit/AUDIT_SUMMARY.md`: issue counts by category and location.
- `audit/README_QUALITY_SCORES.md`: README quality assessment.
- `audit/ARCHITECTURE_DISCOVERY.md`: architecture scan and entrypoint classification.
- `memory-bank/*.md`: placeholder project context templates (activeContext, productContext, etc.).

## Notable Non-README References
- `docs/TEST_PROTOCOL.md`: pytest markers and recommended runs.
- `docs/guides/INSTALLATION.md`: installation steps and CLI verification.
- `docs/MCP_SERVER_IMPLEMENTATION_GUIDE.md`: MCP integration guidance.
- `docs/SECURITY.md`: security overview.
