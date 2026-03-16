---
name: nx-ship-flagship
description: Build the flagship product MVP (CLI/API/UI), add tests, demo script, and write PRODUCTS/20_FLAGSHIP.md. Use once a flagship is selected.
---

# Nx Ship Flagship

## Overview
Implement the flagship product with a reproducible demo, tests, and user-facing docs.

## Workflow
1. Confirm flagship definition and scope (MVP, offline/mock mode, evidence pack outputs).
2. Implement minimal entry point (CLI or API) without breaking `nexus7.py`.
3. Add smoke + unit tests for new functionality.
4. Add demo script under `scripts/demo_flagship.*`.
5. Document usage in `PRODUCTS/20_FLAGSHIP.md` (quickstart, config, outputs).
6. Append to `PRODUCTS/PROGRESS_LOG.md` and add ADRs for major decisions.

## Output Checklist
- Flagship code merged with mock/offline mode.
- `scripts/demo_flagship.*` runnable.
- Tests added and recorded in `PRODUCTS/03_BASELINE.md`.
- `PRODUCTS/20_FLAGSHIP.md` updated with commands and artifacts.
