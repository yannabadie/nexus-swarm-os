# NEXUS Evidence Pack - Design Document

**Date**: 2026-02-26
**Author**: Yann Abadie + Claude Opus 4.6
**Status**: Approved
**Branch**: To be created (`nexus-evidence`)

---

## Problem

Agents are in production (~57% of teams), but the #1 pain is **quality and observability** (~32% cite quality as a blocker, ~89% consider observability "table stakes"). Teams need to prove, debug, measure, and control agent outputs. No tool currently sells **verifiable evidence** as its core product.

## Solution

**NEXUS Evidence Pack** = a standalone Python package (`nexus-evidence`) that transforms a PR diff into a **verifiable evidence pack** using dual-agent analysis (Claude + Gemini).

Distributed via:
- **CLI**: `nexus-evidence review` for CI/CD pipelines
- **MCP Server**: 2 tools for Claude Desktop + VS Code interactive use

## Market Positioning

- **Not a framework** (saturated: LangGraph, CrewAI, Agent Framework, Agents SDK)
- **Evidence + governance + MCP distribution** = complement to existing stacks
- **Differentiator**: Dual-agent cross-check (two LLMs converging = measurable confidence)

## Trajectory

**Option 1 (chosen): Wedge OSS first, enterprise later**

1. Evidence Pack (OSS wedge) - 6 weeks
2. Research Studio in parallel (R&D that feeds the wedge)
3. Evidence Gateway once adoption proven (policy/audit/caps)

---

## Evidence Pack Format (Contract)

Each pack is a directory `evidence-pack-{timestamp}/` containing 6 artefacts:

| File | Format | Content |
|------|--------|---------|
| `report.md` | Markdown | Structured analysis: summary, risks, recommendations, confidence score |
| `sources.json` | JSON | List of sources consulted (files, URLs) with excerpts |
| `trace.jsonl` | JSON Lines | Each reasoning step: agent, prompt, response, duration, cost |
| `reasoning_graph.mmd` | Mermaid | Decision graph: nodes = steps, edges = dependencies |
| `metrics.json` | JSON | Tokens, total cost, duration, models used, confidence |
| `manifest.sha256` | Text | SHA-256 hash of each artefact for verifiability |

Mock mode produces identical format with realistic simulated data (zero API keys).

---

## PR Review Workflow (5 Steps)

```
1. COLLECT    2a. ANALYZE_CLAUDE   3. CROSS-CHECK    4. SYNTHESIZE    5. PACKAGE
PR diff +   -> Claude: risks,    -> Compare two     -> Score,         -> Evidence
context       quality, tests       analyses,          graph,           Pack +
            -> Gemini: risks,      resolve            confidence       PR comment
2b.           architecture,       divergences
ANALYZE_GEM   performance
```

### Step 1 - COLLECT
Extract PR diff, identify touched files, load context (imports, existing tests, dependencies).
Mock: pre-generated synthetic diff.

### Step 2a/2b - DUAL ANALYZE (parallel)
Claude and Gemini receive the same context but differentiated prompts:
- **Claude**: code quality, edge cases, test suggestions
- **Gemini**: architecture, performance, security patterns

Mock: two pre-scripted responses with different perspectives.

### Step 3 - CROSS-CHECK
Compare both analyses. Identify agreements (high confidence) and divergences (need attention).
If divergence > threshold, one reconciliation round (PING_PONG from NEXUS Swarm Engine).

### Step 4 - SYNTHESIZE
Consolidate results into typed structures. Calculate global confidence score. Generate Mermaid reasoning graph.

### Step 5 - PACKAGE
Write 6 artefacts. Calculate SHA-256 manifest. Optionally format a PR-ready comment (GitHub/GitLab markdown).

---

## Package Structure

```
nexus-evidence/
  pyproject.toml
  README.md
  src/nexus_evidence/
    __init__.py
    cli.py                  # Click/Typer CLI
    mcp_server.py           # MCP server (2 tools)
    core/
      collector.py          # Step 1: PR diff + context
      analyzer.py           # Step 2: Dual-agent analysis
      crosscheck.py         # Step 3: Cross-check
      synthesizer.py        # Step 4: Scoring + graph
      packager.py           # Step 5: Artefacts + manifest
    drivers/
      claude.py             # Claude SDK (simplified from NEXUS)
      gemini.py             # Gemini SDK (simplified from NEXUS)
      mock.py               # Mock driver (zero keys)
    models/
      evidence.py           # Pydantic: EvidencePack, Report, etc.
      config.py             # Config: keys, modes, budgets
    formats/
      markdown.py           # report.md generator
      mermaid.py            # reasoning_graph.mmd generator
      pr_comment.py         # PR comment formatter
  tests/
    test_collector.py
    test_analyzer.py
    test_crosscheck.py
    test_packager.py
    test_mock_mode.py
  examples/
    claude_desktop_config.json
    vscode_mcp_settings.json
```

## MCP Interface

**Tools exposed:**
- `review_pr(repo_path, branch?, base_branch?, question?)` -> Evidence Pack path
- `get_evidence(pack_id)` -> Pack contents

**Clients:** Claude Desktop + VS Code (both targeted)

## CLI Interface

```bash
# Mock mode (zero keys, instant demo)
nexus-evidence review ./my-repo --mode mock

# Live mode
nexus-evidence review ./my-repo --branch feature-x --base main

# With question
nexus-evidence review ./my-repo -q "Is the error handling sufficient?"
```

## Dependencies

**From NEXUS (simplified extraction):**
- Claude/Gemini drivers (~200 LOC each, vs ~800 in NEXUS)
- Budget tracking (token counter only)
- Pydantic models

**New:**
- `click` or `typer` (CLI)
- `mcp` (MCP server protocol)
- `anthropic` + `google-genai` (optional extras)

## Pricing (Future)

| Tier | Price | Features |
|------|-------|----------|
| Community (MIT) | Free | CLI + MCP, mock + live, 6 artefacts |
| Pro | 20-40 EUR/dev/month | PR comment templates, export bundles, support |
| Team | 200-600 EUR/team/month | Signed artefacts, policies, retention |

## Success Criteria (6 weeks)

1. `nexus-evidence review --mode mock` produces valid Evidence Pack in <5s
2. MCP server installable in Claude Desktop AND VS Code
3. 1 real PR reviewed with live dual-agent analysis
4. Published on PyPI + MCP registry
5. 90-second demo video
6. 5-10 external installs

## Risks

| Risk | Mitigation |
|------|------------|
| MCP registry still in preview | Also distribute via pip + manual config |
| Dual-agent adds cost | Budget tracker + mock mode for demos |
| Package extraction takes too long | Start with mock mode only, add live drivers later |
| No adoption in 4 weeks | Pivot to "Governance addon" for existing frameworks |

---

## Roadmap (6 weeks)

- **S1**: Package scaffold + Evidence Pack models + mock driver + smoke tests
- **S2**: Collector + Packager (mock pipeline end-to-end)
- **S3**: MCP server (2 tools) + Claude Desktop/VS Code config
- **S4**: Live drivers (Claude + Gemini) + dual-agent analysis
- **S5**: Cross-check + PR comment formatter + OTel export (optional)
- **S6**: PyPI release + MCP registry + demo video + README polish
