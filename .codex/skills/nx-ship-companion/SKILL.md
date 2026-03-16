---
name: nx-ship-companion
description: Build the companion product MVP (prefer MCP server or lightweight integration), add tests, demo script, and write PRODUCTS/30_COMPANION.md. Use after flagship scope is set.
---

# Nx Ship Companion

## Overview
Deliver a smaller companion product that targets a different audience or JTBD.

## Workflow
1. Confirm companion scope (MCP server, SDK, or integration) and target audience.
2. Implement minimal entry point and ensure it works in mock/offline mode.
3. Add smoke + unit tests for the companion.
4. Add demo script under `scripts/demo_companion.*`.
5. Document usage in `PRODUCTS/30_COMPANION.md`.
6. Append to `PRODUCTS/PROGRESS_LOG.md` and add ADRs for major decisions.

## Output Checklist
- Companion product runnable with a demo command.
- `scripts/demo_companion.*` runnable.
- Tests added and recorded in `PRODUCTS/03_BASELINE.md`.
- `PRODUCTS/30_COMPANION.md` updated with commands and outputs.
