---
name: nx-market-refresh-2026
description: Research the 2025-2026 market landscape (local-first AI, MCP, evidence packs, eval harnesses) and update PRODUCTS/04_LANDSCAPE_2026.md with cited sources. Use when preparing portfolio or differentiation work.
---

# Nx Market Refresh 2026

## Overview
Produce a concise market landscape with citations to inform product selection and differentiation.

## Workflow
1. Define the focus areas: local-first AI, MCP ecosystem, research/evidence tooling, eval harnesses, and compliance/audit tooling.
2. Collect sources with URLs and dates (press releases, docs, standards, major vendor updates).
3. Summarize trends, competitive landscape, and gaps relevant to NEXUS.
4. Write `PRODUCTS/04_LANDSCAPE_2026.md` with citations and implications.
5. Append a note to `PRODUCTS/PROGRESS_LOG.md`.

## Commands (examples)
```bash
# PowerShell: fetch a source and save a snippet
Invoke-WebRequest https://modelcontextprotocol.io/ -UseBasicParsing | Select-Object -First 20
```

```bash
# Verify MCP docs or vendor updates
Invoke-WebRequest https://docs.anthropic.com/ -UseBasicParsing | Select-Object -First 20
```

## Output Checklist
- `PRODUCTS/04_LANDSCAPE_2026.md` with:
  - Trend summary
  - Competitive map
  - Differentiation opportunities
  - Risks and assumptions
  - At least 6 cited sources (URL + access date)
- `PRODUCTS/PROGRESS_LOG.md` appended with market refresh note.
