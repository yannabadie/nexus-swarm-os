# Architecture Overview

NEXUS is organized around a core orchestration engine, a memory layer, and integration surfaces (CLI, MCP, UI). The repository is designed for additive extensions rather than large rewrites.

## Core Runtime
- `nexus7.py` is the primary CLI entrypoint that runs the orchestration loop.
- `core/` hosts the orchestrator (FSM + Hive Mind/Swarm), execution tools, and security layers.
- `core/config.py` is the single source of truth for configuration loaded from `.env`.

## Memory and Retrieval
- `core/memory/` contains ProjectMemory (RAG) and pluggable backends.
- Memory backends choose Dense > BM25S > TF-IDF depending on availability.
- Indexed artifacts are stored under `.nexus/` in the project root.

## Products and Integrations
- Flagship: `nexus_research.py` generates evidence packs from local files.
- Companion: `core/mcp/server.py` exposes MCP tools for research, memory search, and evidence pack export.
- UI: `interface/ui/cerebro/` is a React + TypeScript front end.

## Data and Workspace
- Runtime outputs live under `WORKSPACE_PATH` (default `./workspace`).
- Evidence packs include report, sources, trace, graph, metrics, and manifest files.

## Extension Points
- Add new tools via `core/execution/` and register them through the ToolManager.
- Add new MCP tools in `core/mcp/server.py` (stdio transport).
- Add product docs under `PRODUCTS/` and update ADRs in `PRODUCTS/DECISIONS/`.
