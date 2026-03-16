# Codebase Map

## Overview
NEXUS is a multi-agent orchestration system (Gemini + Claude) with a CLI REPL, FastAPI control plane (CEREBRO), and a React dashboard. It includes HiveMind (7-phase pipeline), Swarm (6 collaboration modes), memory/RAG, security hardening, and MCP integration.

## Entry Points
- `nexus7.py`: primary CLI REPL entry point (bootstrap, interactive loop).
- `core/api/cerebro/app.py`: FastAPI app factory for REST + WebSocket control plane.
- `core/mcp/server.py`: MCP server exposing NEXUS tools over stdio JSON-RPC.
- `interface/ui/cerebro/`: React 19 + TypeScript dashboard (Vite, Tailwind).

## Core Modules (core/)
- Orchestration: `core/orchestration_v7.py`, `core/orchestration/` (FSM handlers, context builder, agent invoker, sync bridge).
- HiveMind: `core/hive_mind/` (7-phase pipeline, debate, saga checkpoints, SwarmBridge).
- Swarm: `core/swarm/` (mode negotiation, executors, fallback chains, DyLAN metrics).
- Execution: `core/execution/` (tool registry, handlers, security validation, dynamic tools).
- Drivers: `core/drivers/` (Gemini/Claude CLI + async drivers, session management).
- Memory: `core/memory/` (SuccessMemory, AutoMemory, ProjectMemory, backends, ingest). 
- Security: `core/security/` + `core/governance/` (guards, execution policy, red team).
- Telemetry/Logging: `core/telemetry/`, `core/logging/` (JSONL logs, budgets, metrics).

## Support Modules
- Context and multi-tenancy: `core/context/`, `core/db/`, `core/api/`.
- Bootstrap and spinoffs: `core/bootstrap/` (project deployment, agent discovery).
- Agent registry: `core/agents/` (unified registry, spawn service, DyLAN stats).
- Workspace/session isolation: `core/workspace/`, `core/session/`.
- Interaction: `core/interaction/`, notifications in `core/notifications/`.
- Events: `core/events/` (Redis event bus for UI).
- Workflow registry: `core/workflow/` (Redis-backed workflow storage, locks).
- Synapse protocol: `core/synapse/` (agent message schemas, auto-repair).

## UI (interface/ui/cerebro)
React 19 dashboard with Vite build, Vitest unit tests, Playwright E2E, and Zustand state stores. WebSocket and REST API integrations target `core/api/cerebro`.

## Tests
`tests/` contains extensive pytest suites, with subfolders for API, audit, FSM, interaction, workflow, torture, and versioned test suites (v10, v11).

## Scripts and Tools
- `scripts/doc_engine.py`: documentation sync, architecture map generation.
- `scripts/init_db.py`: DB bootstrap (SQLModel).
- `scripts/migrate_v9_to_v10.py`: migration utility.
- `tools/`: doc generator tooling.

## Docs, Audit, and Prompts
- `docs/`: architecture, security, API references, workflows.
- `audit/`: audits and issue inventories.
- `prompts/`: shared/system prompts and prompt loader.
- `memory-bank/`: project context templates (mostly placeholders).

## Extension Points
- Tooling: add handlers in `core/execution/handlers/` or dynamic tools via `core/execution/dynamic_tools.py`.
- API: add routes under `core/api/cerebro/routes/`.
- MCP: extend tools in `core/mcp/server.py` and registry in `core/mcp/registry.py`.
- UI: add components in `interface/ui/cerebro/src/components/` and stores in `interface/ui/cerebro/src/stores/`.
- Prompts: add or edit prompt templates under `prompts/` and `prompts/_shared/`.
