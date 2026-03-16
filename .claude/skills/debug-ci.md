---
name: debug-ci
description: NEXUS GitHub Actions CI troubleshooting guide. Use when CI fails or when investigating test failures.
---

# NEXUS CI Debugging Guide

## Quick Diagnosis

```bash
# 1. Check latest CI status
gh run list --branch NX-CG --limit 5

# 2. View failed run
gh run view <run-id>

# 3. Get failure logs
gh run view <run-id> --log-failed | grep -A 20 "ERROR\|FAILED"

# 4. Re-run failed jobs (if transient)
gh run rerun <run-id>
```

## CI Pipeline Structure (.github/workflows/ci.yml)

### 3 Blocking Gates

1. **unit-tests** (Python 3.11, 3.12, 3.13)
   - All test files in `tests/`
   - Coverage threshold: 40%
   - Timeout: 60s per test
   - Ignores: `benchmark_professional.py`

2. **lint-type-check**
   - Ruff lint + format check
   - Python syntax compilation
   - Mypy type check (core modules only)

3. **security-scan**
   - Bandit security scan
   - KERNEL integrity check

### Optional Jobs

- **integration** - Manual trigger only (requires API keys)
- **torture** - Nightly stress tests (3 AM UTC)

## Common Failure Patterns

### 1. Import Errors

**Symptom**:
```
ModuleNotFoundError: No module named 'email_validator'
ImportError: cannot import name 'GeminiDriverV7'
```

**Causes**:
- Missing dependency in requirements.txt
- Import path changed (refactoring)
- Module renamed/moved

**Fix**:
```bash
# Check dependencies
pip install -e ".[dev]"

# Verify imports locally
python -c "import module_name"

# Update requirements.txt if needed
echo "package>=version" >> requirements.txt
```

### 2. AttributeError in Tests

**Symptom**:
```
AttributeError: 'OrchestratorV7' object has no attribute '_transition_to'
AttributeError: 'OrchestratorV7' object has no attribute 'agent_invoker'
```

**Causes**:
- Method extracted to module (P5.1 refactoring)
- Initialization order broken
- Missing delegation wrapper

**Fix**:
```python
# Add delegation wrapper
def _transition_to(self, new_state):
    """Delegates to StateHandler for backward compatibility."""
    return self.state_handler.transition_to(new_state)
```

### 3. Test Failures (Assertions)

**Symptom**:
```
FAILED tests/test_file.py::test_name - assert False
AssertionError: Expected 'success', got 'error'
```

**Causes**:
- Test expectations outdated
- Code behavior changed
- Mock setup incorrect

**Debug**:
```bash
# Run locally with verbose output
pytest tests/test_file.py::test_name -vv -s

# Add debug print in test
def test_name():
    print(f"DEBUG: result = {result}")
    assert result == expected
```

### 4. Ruff Lint Errors

**Symptom**:
```
core/file.py:27:1: I001 Import block is un-sorted
core/file.py:28:26: F401 `typing.Optional` imported but unused
core/file.py:123:18: UP006 Use `list` instead of `List`
```

**Fix**:
```bash
# Auto-fix most issues
ruff check core/ tests/ --fix

# Format code
ruff format core/ tests/

# Check specific file
ruff check core/file.py
```

### 5. Coverage Below Threshold

**Symptom**:
```
FAILED: coverage < 40% (actual: 38%)
```

**Fix**:
- Add tests for untested code
- Remove dead code
- Adjust threshold temporarily (not recommended)

```bash
# Check coverage locally
pytest tests/ --cov=core --cov-report=term-missing

# See what's not covered
pytest tests/ --cov=core --cov-report=html
open htmlcov/index.html
```

### 6. Timeout Errors

**Symptom**:
```
FAILED: Test timeout after 60s
```

**Causes**:
- Infinite loop
- Blocking I/O without timeout
- Heavy computation

**Fix**:
```python
# Mark slow tests
@pytest.mark.slow
def test_heavy_computation():
    # ...

# Or increase timeout for specific test
@pytest.mark.timeout(120)
def test_needs_more_time():
    # ...
```

## Environment Variables (CI)

```yaml
PYTHONPATH: ${{ github.workspace }}
SKIP_LLM_TESTS: 1              # Skip tests requiring API keys
NEXUS_TELEMETRY: 0             # Disable telemetry in CI
```

## Reproducing CI Failures Locally

**Match CI environment**:
```bash
# Use same Python version
pyenv install 3.13
pyenv local 3.13

# Install exact dependencies
pip install -r requirements.txt

# Set CI env vars
export PYTHONPATH=.
export SKIP_LLM_TESTS=1
export NEXUS_TELEMETRY=0

# Run tests like CI does
pytest tests/ \
  --tb=short -q \
  --timeout=60 \
  --ignore=tests/benchmark_professional.py \
  --cov=core \
  --cov-fail-under=40
```

## CI-Specific Issues

### GitHub Actions Cache Issues

**Symptom**: Tests pass locally but fail in CI

**Possible causes**:
- Stale pip cache
- Different dependency versions

**Fix**: Clear cache manually
```bash
# In workflow file, bump cache key
cache: 'pip-v2'  # was 'pip-v1'
```

### Workspace Directory Issues

**Symptom**: FileNotFoundError for workspace/

**Cause**: CI doesn't create workspace dirs automatically

**Fix**: In workflow
```yaml
- name: Create workspace directories
  run: |
    mkdir -p workspace/.nexus workspace/logs workspace/memory
```

## Verification Protocol

**CRITICAL: Always verify CI passes after fix**

```bash
# 1. Fix issue locally
# 2. Run tests locally
pytest tests/

# 3. Commit and push
git add .
git commit -m "fix(ci): description"
git push origin NX-CG

# 4. Wait for CI
sleep 20

# 5. VERIFY status
gh run list --branch NX-CG --limit 1

# 6. If failed, get logs and repeat
gh run view $(gh run list --branch NX-CG --limit 1 --json databaseId -q '.[0].databaseId') --log-failed
```

**NEVER claim "CI fixed" without verification** [OK]

## Debugging Checklist

Before pushing a "fix":
- [ ] Tests pass locally
- [ ] Ruff lint passes
- [ ] Python syntax valid (`python -m py_compile`)
- [ ] Dependencies updated (requirements.txt + pyproject.toml)
- [ ] Environment matches CI (Python version, env vars)

After pushing:
- [ ] Wait for CI to start (10-20s)
- [ ] Check run status
- [ ] If failed, download logs
- [ ] Identify root cause
- [ ] Fix and repeat

## Pro Tips

1. **Run CI locally first** - Use `act` or Docker
2. **Check recent changes** - What was different in last passing run?
3. **Read full stack trace** - Don't just grep for ERROR
4. **Test matrix failures** - If only Python 3.11 fails, version-specific issue
5. **Compare with main branch** - Does it pass there?

## Emergency: Disable Failing Tests Temporarily

**Only as last resort**:
```python
@pytest.mark.skip(reason="Known issue #123 - fix in progress")
def test_failing():
    # ...
```

**Remember to**:
- File GitHub issue
- Link issue in skip reason
- Fix ASAP (don't leave skipped tests)

## Resources

- CI logs: `gh run view <id> --log`
- Workflow file: `.github/workflows/ci.yml`
- Requirements: `requirements.txt` + `pyproject.toml`
- Test config: `pyproject.toml` [tool.pytest]
- Coverage config: `pyproject.toml` [tool.coverage]

**Remember**: CI failures are INFORMATION, not setbacks. They catch bugs before production [OK]
