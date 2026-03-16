# ADR-0004: MCP Server Companion for Research + Evidence Packs

Date: 2026-01-21
Status: Accepted

## Context
The companion product must serve a different audience (integration/automation) while reusing existing NEXUS capabilities. MCP support already exists, but tooling lacks research and evidence pack endpoints aligned with the flagship.

## Decision
Extend `core.mcp.server` with MCP tools for `nexus_research`, `nexus_memory_search`, and `nexus_export_evidence_pack`, backed by ProjectMemory and the flagship evidence pack generator. Add safety checks to keep indexing under `NEXUS_ROOT` and outputs under `WORKSPACE_PATH`.

## Consequences
- External MCP clients can run research and export evidence packs without direct repo access.
- Companion remains additive and compatible with existing MCP tooling.
- New tests validate helper functions without requiring the MCP SDK.
