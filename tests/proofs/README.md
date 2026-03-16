# Smoke Checks (Legacy `tests/proofs/` Path)

## Synopsis

Fast smoke checks for critical behavior after significant refactorings. The directory name is retained for compatibility, but these scripts are not formal proofs.

## Test Files

| File | Purpose | Validation |
|------|---------|------------|
| `verify_headless_mode.py` | Headless mode non-blocking verification | InteractionProvider factory, HeadlessProvider.confirm() returns immediately, ask() returns immediately |

## verify_headless_mode.py

Smoke validation that NEXUS V9.8 DETOX removed blocking calls from headless interaction providers.

**Tests**:
1. **InteractionProvider Factory** - Returns HeadlessProvider when `NEXUS_INTERACTION_MODE=headless`
2. **confirm() Non-Blocking** - Returns immediately with default value (<0.1s)
3. **ask() Non-Blocking** - Returns immediately with default value (<0.1s)

**Expected Output**: All tests pass without blocking or timeout

**Run**:
```bash
python tests/proofs/verify_headless_mode.py
```

## Purpose

Smoke checks are:
- **Fast** - Run in seconds, not minutes
- **Focused** - Test one feature thoroughly
- **Executable** - Can run standalone without pytest
- **Demonstrative** - Demonstrate a specific regression check or fix

## When to Add Smoke Checks

Add a smoke check when:
- Major refactoring needs validation
- Critical bug fix needs verification
- Feature requires demonstration
- Quick smoke test needed

## Related

- [tests/verify_stability.py](../verify_stability.py) - System stability verification
- [tests/verify_hive_mind.py](../verify_hive_mind.py) - HiveMind verification
- [core/interaction/](../../core/interaction/) - Interaction providers
