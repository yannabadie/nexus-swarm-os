---
name: nx-baseline-verify
description: Run baseline installs, tests, and CLI/UI smoke checks, then update PRODUCTS/03_BASELINE.md with results. Use before product work or after significant changes.
---

# Nx Baseline Verify

## Overview
Establish a reproducible baseline by installing dependencies, running key tests, and verifying CLI/UI startup.

## Workflow
1. Install Python deps.
2. Install UI deps (Cerebro) and capture npm audit summary.
3. Run pytest suite (full or segmented if timeouts occur).
4. Run CLI bootstrap verification.
5. Update `PRODUCTS/03_BASELINE.md` and append to `PRODUCTS/PROGRESS_LOG.md`.
6. If baseline fails, apply minimal hotfixes and record an ADR.

## Commands
```bash
python -m pip install -r requirements.txt
```

```bash
cd interface/ui/cerebro
npm install
```

```bash
python -m pytest tests/ -v
```

```bash
python nexus7.py --verify
```

## Output Checklist
- `PRODUCTS/03_BASELINE.md` updated with command outputs and failures.
- `PRODUCTS/PROGRESS_LOG.md` appended with baseline summary.
- `PRODUCTS/DECISIONS/ADR-*.md` added if hotfixes were required.
