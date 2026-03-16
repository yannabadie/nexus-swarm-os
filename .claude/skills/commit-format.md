---
name: commit-format
description: NEXUS commit message conventions and git workflow. Use when creating commits or managing branches.
---

# NEXUS Commit Format & Git Workflow

## Commit Message Structure

```
type(scope): subject

[optional body]

[optional footer]

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

## Commit Types

| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat(P5.1-Phase3): extract ResultHandler from orchestrator` |
| `fix` | Bug fix | `fix(ci): add email-validator dependency` |
| `refactor` | Code restructuring | `refactor(memory): simplify RAG query logic` |
| `test` | Test additions/changes | `test(V12.4): add tests for StateHandler (22 tests)` |
| `docs` | Documentation | `docs(P5.1): finalize session document` |
| `chore` | Maintenance | `chore: update dependencies` |
| `perf` | Performance improvement | `perf(rag): optimize vector search with HNSW` |
| `style` | Code style (formatting) | `style: run ruff format on core/` |

## Scopes

**Common scopes**:
- `P5.1`, `P5.2` - Epic/Phase identifiers
- `V12.4`, `V8.3` - Version identifiers
- `ci` - CI/CD changes
- `tests` - Test-related changes
- Module names: `memory`, `orchestration`, `drivers`, `swarm`, etc.

## Subject Line Rules

1. **Limit to 70 characters** (enforced)
2. **Use imperative mood** ("add", not "added" or "adds")
3. **Don't end with period**
4. **Be specific but concise**

**Examples**:
```
[OK] feat(P5.1-Phase1): extract GuardPipeline from orchestrator (145 LOC, 15 tests)
[OK] fix(init): correct agent_invoker initialization order
[OK] docs: add verification rule + Claude Code best practices research

[NO] feat: did some stuff (too vague)
[NO] Fixed the bug in orchestration_v7.py that was causing issues. (too long, past tense)
```

## Body (Optional)

**Use body for**:
- Explaining **why** (not what - that's in the code)
- Listing multiple changes
- Describing impact/breaking changes

**Format**:
```
feat(P5.1-Phase3): extract ResultHandler from orchestrator (206 LOC, 22 tests)

ResultHandler encapsulates:
- Result creation (make_result)
- Pydantic message validation
- Tool result formatting
- Auto-Memory recording on task completion

API compatibility maintained via delegation wrapper: _make_result() delegates to result_handler.make_result()
```

## Footer

**Co-Authored-By** (mandatory for AI commits):
```
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Issue references**:
```
Fixes #142
Closes #143
Related to #144
```

**Breaking changes**:
```
BREAKING CHANGE: Removed deprecated CLI driver imports
```

## Real NEXUS Examples

**Feature commits**:
```
feat(V12.4): add RuntimeWasteFilter and ExperienceDistiller (294 tests)

feat(P5.1-Phase4): extract StateHandler from OrchestratorV7 (1177->1097 lines)

feat(V8.3.1): add SwarmBridge delegation to HiveMind phases
```

**Fix commits**:
```
fix(tests): update driver mocks for V12.4 AsyncDriverFactory

fix(ci): add email-validator dependency for pydantic EmailStr

fix(init): correct agent_invoker initialization order
```

**Test commits**:
```
test(V12.4): add tests for FSM handlers, Phase retry/architecture (363 tests)

test(V12.4): add tests for NegotiationProtocol, SwarmEngine, Orchestrator (332 tests)
```

**Documentation commits**:
```
docs(P5.1): mark orchestrator decomposition complete (5/7 phases)

docs: add verification rule + Claude Code best practices research
```

## Git Workflow (NEXUS Branches)

### Main Branches

- **`NX`** - Main development branch (protected)
- **`NX-CG`** - Current work branch (Claude + Gemini collaboration)
- **`main`** - Legacy (rarely used)

### Workflow

```bash
# 1. Start from NX-CG
git checkout NX-CG
git pull origin NX-CG

# 2. Make changes
# ... edit files ...

# 3. Stage specific files (avoid git add -A)
git add core/orchestration_v7.py tests/test_orchestration.py

# 4. Commit with format
git commit -m "feat(P5.1-Phase5): cleanup delegation wrappers

Removed 5 delegation wrappers after P5.1 extraction:
- _validate_input_guard
- _handle_trivial_input
- _format_tool_result
- _create_context
- _detect_mutations

SwarmEngine now uses agent_invoker.invoke_for_swarm() directly.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 5. Push
git push origin NX-CG

# 6. VERIFY CI passes
gh run list --limit 1
```

### Protected Branch Rules

**NEVER**:
- [NO] Force push to `NX` or `main`
- [NO] Push directly to `NX` (use PR)
- [NO] Skip hooks with `--no-verify`

**ALWAYS**:
- [OK] Work on `NX-CG` or feature branches
- [OK] Run tests before pushing
- [OK] Verify CI passes after push

## Multi-File Commits

**When changing multiple related files**:
```
feat(P5.1-Phase3): extract ResultHandler from orchestrator (206 LOC, 22 tests)

Created:
- core/orchestration/result_handler.py (206 lines)
- tests/test_result_handler.py (22 tests)

Modified:
- core/orchestration_v7.py (1177->1097 lines)
- core/orchestration/__init__.py (exports updated)

API compatibility maintained via _make_result() delegation wrapper.
```

## Amending Commits

**Use `--amend` ONLY for**:
- Fixing typos in last commit message
- Adding forgotten files to last commit
- **NEVER amend pushed commits**

```bash
# Fix typo in last commit message
git commit --amend -m "new message"

# Add forgotten file to last commit
git add forgotten_file.py
git commit --amend --no-edit
```

## Using HEREDOC for Long Messages

**For messages with multiple lines**:
```bash
git commit -m "$(cat <<'EOF'
feat(P5.1-Phase3): extract ResultHandler from orchestrator

Created ResultHandler to encapsulate result creation, validation,
and Auto-Memory recording.

Changes:
- Created core/orchestration/result_handler.py (206 LOC)
- Added 22 comprehensive tests
- Maintained API compatibility via delegation

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

## Verification Protocol

**CRITICAL: After every push**:
```bash
# 1. Push
git push origin NX-CG

# 2. Wait 10-20s for CI to start
sleep 15

# 3. Check CI status
gh run list --branch NX-CG --limit 1

# 4. If failed, get logs
gh run view <run-id> --log-failed | grep ERROR

# 5. Fix, commit, push, REPEAT verification
```

**NEVER say "pushed successfully" without verifying CI passes** [OK]

## Pro Tips

- **Atomic commits** - One logical change per commit
- **Commit early, commit often** - Don't wait for "perfect"
- **Use conventional commits** - Enables auto-changelog
- **Reference issues** - Links commits to tasks
- **Write for future you** - You'll forget in 2 weeks

## Common Pitfalls

[NO] **Too vague**: `git commit -m "fixes"`
[NO] **Too long**: Subject > 70 chars
[NO] **Past tense**: "Fixed bug" (use "Fix bug")
[NO] **Mixing concerns**: Multiple unrelated changes
[NO] **No co-author**: Forgot AI attribution

[OK] **Good commit**: Clear, concise, imperative, scoped, co-authored
