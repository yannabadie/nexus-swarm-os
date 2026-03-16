# ADR-0002: Baseline Test Alignment for Current Interfaces

Date: 2026-01-20
Status: Accepted

## Context
Baseline pytest failed due to tests expecting legacy interfaces and behavior (tutorial step count, DebateResult fields, swarm invoke signature, and project memory no-match assumptions). The runtime code reflects newer interfaces (V8.3+/V12.4) and semantic retrieval behavior.

## Decision
Update tests to align with current interfaces and behavior, without changing production code. Adjusted DX expectations, DebateResult construction, swarm invoke mocks to accept session isolation args, and project memory no-match assertion to use a high min_score threshold.

## Consequences
- Baseline pytest passes with current runtime behavior.
- Tests are less brittle to version string changes and updated data models.
- No changes to runtime logic; deprecation warnings remain for future cleanup.
