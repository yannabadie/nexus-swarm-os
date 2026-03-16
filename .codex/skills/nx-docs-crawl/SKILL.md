---
name: nx-docs-crawl
description: Crawl README and doc files to refresh PRODUCTS/02_DOCS_DIGEST.md and PRODUCTS/01_CODEBASE_MAP.md. Use when docs changed, new modules were added, or a proof-of-reading digest is required.
---

# Nx Docs Crawl

## Overview
Scan repository documentation and update the docs digest and codebase map summaries.

## Workflow
1. List all README files and key root docs.
2. Read each README and the required root documents (README, MISSION, ROADMAP, ARCHITECTURE_MAP, INVARIANTS, KERNEL, requirements*, docker-compose).
3. Update `PRODUCTS/02_DOCS_DIGEST.md` with one-line summaries per README, grouped by area.
4. Update `PRODUCTS/01_CODEBASE_MAP.md` if new entry points or extension points are found.
5. Add a short note to `PRODUCTS/PROGRESS_LOG.md` describing the refresh.

## Commands
```bash
rg --files -g "README.md"
```

## Output Checklist
- `PRODUCTS/02_DOCS_DIGEST.md` updated with grouped summaries and notable non-README docs.
- `PRODUCTS/01_CODEBASE_MAP.md` updated if structure or entry points changed.
- `PRODUCTS/PROGRESS_LOG.md` appended with refresh note.
