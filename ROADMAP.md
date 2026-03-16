# NEXUS V12.4 "COGNITIVE BOOST" - Roadmap

**Version**: 12.4.0 | **Status**: Active
**Maintainer**: Yann Abadie | **Branch**: NX-CG
**Current Status**: Use CI evidence ledger for current status.

---

## Scope

This roadmap is a strategic planning document, not a release-status dashboard.
Do not use it for current pass/fail counts, coverage, provider health, or
release readiness. Those signals belong to CI artifacts and reproducible
evaluation outputs.

Canonical truth surfaces:
- `pyproject.toml` + `core/version.py` for version and canonical branch
- CI evidence ledger for test, coverage, build, smoke, and artifact status
- `core/provider_registry.json` for provider defaults and replacements
- ADRs under `PRODUCTS/DECISIONS/` for architecture decisions

Historical release narratives:
- `docs/releases/`
- `PRODUCTS/03_BASELINE.md`
- `PRODUCTS/PROGRESS_LOG.md`

---

## Immediate Priorities

### 1. Branch Integrity

Objective:
Keep `NX-CG` green and reproducible on every push.

Required outcomes:
- No failing required GitHub Actions jobs
- Evidence ledger generated even when upstream jobs fail
- Deterministic generated docs across Windows and Linux
- Wheel build and install smoke kept operational

### 2. Truth Consolidation

Objective:
Remove duplicate or drifting public status surfaces.

Required outcomes:
- One canonical version source
- `.env.example` aligned with `core/provider_registry.json`
- Public docs stop publishing unsourced quality or maturity claims
- PR text and templates require linked evidence for public claims

### 3. Provider Compatibility

Objective:
Make provider maintenance boring instead of reactive.

Required outcomes:
- Registry refresh works against current official provider endpoints
- Deprecated model IDs map to supported replacements
- Routine CI proves wiring only
- Scheduled or pre-release canaries prove live provider execution

### 4. Runtime UX

Objective:
Make terminal and headless execution behavior explicit and observable.

Required outcomes:
- Headless mode validates a real task path, not only boot semantics
- Interactive runtime surfaces orchestration mode, agent activity, and state
- Output modes stay deterministic enough for CI and automation

### 5. Security and Governance

Objective:
Ship neutral runtime policy instead of doctrine-heavy governance messaging.

Required outcomes:
- Default runtime authority is execution policy, sandboxing, and capability checks
- Legacy KERNEL/INVARIANTS artifacts are not presented as default product governance
- High-risk execution surfaces remain deny-by-default
- Repo hygiene blocks committed local state and absolute local paths

---

## World-Class Exit Criteria

NEXUS should not be described as world-class until all of the following are true:

- Required CI is green on the canonical branch
- Public claims are backed by current artifacts
- Provider compatibility evidence is separated into structural smoke vs live canaries
- Documentation generation is deterministic
- Evaluation data shows when multi-agent orchestration helps, hurts, and costs more
- Security posture is described in terms of real boundaries, not branding language

---

## Frozen Claims

The following claims are frozen until backed by current, linked evidence:

- "all passing"
- "production-ready"
- "world-class"
- exact coverage percentages outside CI artifacts
- provider compatibility as an end-to-end claim on routine CI alone
- retrieval or collaboration uplift numbers without published evaluation artifacts

---

## Next Review

Review this roadmap when one of these changes:
- canonical branch strategy
- evidence ledger schema
- provider registry schema
- major runtime surface (`nexus7.py`, CEREBRO API/UI, MCP server)
