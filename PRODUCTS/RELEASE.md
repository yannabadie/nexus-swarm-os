# Release Candidate Guide

## Prerequisites
- Python 3.11+ installed.
- Optional (companion server): `python -m pip install mcp`.
- CI evidence for the current candidate is published in the `evidence-ledger` artifact from `NEXUS CI` on `NX-CG`.

## Flagship Quickstart (Research CLI)
```bash
python -m pip install -r requirements.txt
python nexus_research.py "How does ProjectMemory index files?" --mode mock --path core/memory_pkg/memory/project_memory.py
```

Expected outputs (under `WORKSPACE_PATH`, default `./workspace/research/<timestamp>`):
- `report.md`, `sources.json`, `trace.jsonl`, `reasoning_graph.mmd`, `metrics.json`, `manifest.sha256`.

Demo script:
```bash
powershell -ExecutionPolicy Bypass -File scripts/demo_flagship.ps1
```

## Companion Quickstart (MCP Server)
```bash
python -m pip install mcp
nexus-mcp
```

Demo script (spawns server and calls MCP tools):
```bash
powershell -ExecutionPolicy Bypass -File scripts/demo_companion.ps1
```

## Tests
```bash
python -m pytest tests/test_research_cli.py -v
python -m pytest tests/test_mcp_companion.py -v
```

## Notes
- `NEXUS_ROOT` controls the indexing base for research and MCP tools.
- MCP evidence pack output is restricted to `WORKSPACE_PATH` for safety.
- Release readiness should be read from the per-run `evidence-ledger.json` artifact, not from hardcoded counts in repository docs.
