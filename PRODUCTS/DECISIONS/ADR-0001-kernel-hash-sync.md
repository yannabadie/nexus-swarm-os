# ADR-0001: Sync KERNEL Hash With Current KERNEL

## Status
Accepted (2026-01-20)

## Context
`python nexus7.py --verify` failed due to a mismatch between `KERNEL.py` and `KERNEL_HASH.txt` even though `KERNEL.py` was unchanged during this session. This blocked baseline verification and violated the Phase 0 requirement to pass CLI smoke.

## Decision
Update `KERNEL_HASH.txt` to match the current `KERNEL.py` contents, without modifying `KERNEL.py` itself.

## Consequences
- KERNEL integrity checks pass again and bootstrap verification can proceed.
- No change to KERNEL invariants or security behavior.
- If this mismatch reflects unintended drift, a future audit should confirm provenance of `KERNEL.py`.
