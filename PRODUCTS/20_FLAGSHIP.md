# Flagship: Research CLI + Evidence Pack

## Overview
The flagship delivers a local-first evidence workflow that turns a question into a grounded evidence pack built from on-disk project files. It runs in mock/local mode by default, requires no external API keys, and now produces a deterministic verification layer on top of retrieval: decomposed subqueries, aggregated evidence, verified claims with supporting/opposing source IDs, contradiction heuristics, confidence scoring, and a provenance graph over retrieved sources.

## Quickstart (Mock Mode)
```bash
python -m pip install -r requirements.txt
python nexus_research.py "How does ProjectMemory index files?" --mode mock --path core/memory_pkg/memory/project_memory.py
```

Alternate invocation:
```bash
python -m nexus_research "How does ProjectMemory index files?" --mode mock --path docs/README.md
```

Outputs land under `WORKSPACE_PATH` (default `./workspace/research/<timestamp>`), unless you pass `--output`.

## Evidence Pack Outputs
- `report.md`: question, research plan, answer bullets, verified claims, findings, contradictions, source table, and confidence score.
- `sources.json`: structured sources with file paths, line ranges, excerpts, query coverage, verification scores, source IDs, subqueries, retrieval summary, and synthesis payload.
- `trace.jsonl`: step-by-step trace (`start`, `index`, `plan`, `retrieve`, `synthesize`, `write_outputs`).
- `reasoning_graph.mmd`: Mermaid graph linking question -> verified claims -> sources, with dashed edges for opposing evidence.
- `metrics.json`: duration, counts, claim breakdown, contradiction count, unique files, and confidence metrics.
- `manifest.sha256`: SHA-256 checksums for the pack files.

## Configuration Notes
- `--mode` supports `mock` or `local`.
- `--backend` accepts `tfidf`, `bm25`, `dense`, `hybrid`, or `auto` (mock defaults to `tfidf`).
- `--path` can be repeated to target specific files or directories.
- `NEXUS_ROOT` controls the project root; `WORKSPACE_PATH` controls output base.

## Demo Script
```bash
powershell -ExecutionPolicy Bypass -File scripts/demo_flagship.ps1
```

## Tests
```bash
python -m pytest tests/test_research_cli.py -v
```

## Comparative Evaluation

NEXUS now ships a deterministic swarm evaluation harness for repeatable baseline comparison:

```bash
python scripts/run_swarm_eval_harness.py --output-root artifacts/swarm-eval
```

It compares:
- `single_agent`
- `deterministic_pipeline`
- `swarm`

Artifacts:
- `report.json`
- `report.md`

The harness is local-first and reproducible. It exercises the real `HybridSwarmEngine`
with a deterministic dual-agent simulator so the repo can publish comparative evidence
without needing live provider access for every run.

## Live Provider Evidence

NEXUS also ships a fixed-task provider canary runner:

```bash
python scripts/run_provider_canaries.py --output artifacts/provider-canaries.json
```

It is intentionally separate from structural smoke:
- structural smoke proves wiring
- provider canaries prove live execution when secrets are configured
