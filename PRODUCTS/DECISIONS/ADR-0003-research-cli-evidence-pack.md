# ADR-0003: Flagship Research CLI Evidence Pack

Date: 2026-01-21
Status: Accepted

## Context
The portfolio selection requires a flagship product that serves research and developer audiences with fast time-to-value, local-first operation, and reproducible evidence packs. The core already includes ProjectMemory and security constraints that favor additive integration over core refactors.

## Decision
Implement a standalone Research CLI (`nexus_research.py`) that indexes local files via ProjectMemory and emits a reproducible evidence pack (report, sources, trace, reasoning graph, manifest). Provide mock/local modes (default mock), configurable backends, and optional path scoping. Keep the entry point additive to avoid changes to `nexus7.py`.

## Consequences
- New CLI is usable without external keys or network access.
- Evidence pack artifacts are standardized for demos and audits.
- Tests and demo scripts validate the flow without altering core orchestration.
