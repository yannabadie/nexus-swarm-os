---
description: "Code review - analyze changes for quality, security, and standards compliance"
allowed-tools: "Bash,Glob,Read,Grep,WebSearch"
---

# /review Command - Code Review

Perform comprehensive code review of recent changes or specific files.

## Usage
- `/review` - Review uncommitted changes
- `/review HEAD~5` - Review last 5 commits
- `/review core/swarm/` - Review specific directory
- `/review file.py` - Review specific file
- `/review --security` - Security-focused review

## Arguments
`$ARGUMENTS` - Optional: commit range, file/directory path, or flags

## Review Dimensions

### 1. Code Quality
- PEP 8 compliance
- Type hints completeness
- Docstring quality
- Code complexity (cognitive load)
- DRY violations

### 2. Security (OWASP Top 10)
- Input validation
- Authentication/authorization
- Data exposure
- Injection vulnerabilities
- Dependencies (CVEs)

### 3. NEXUS Standards
- FSM state usage (valid transitions)
- Message format compliance
- Tool handler patterns
- Error handling patterns
- Test coverage

### 4. Performance
- Algorithmic complexity
- Async patterns (sync-in-async issues)
- Memory usage
- Database queries

## Review Commands

```bash
# Uncommitted changes
git diff

# Staged changes
git diff --staged

# Last N commits
git log -N --oneline
git diff HEAD~N

# Specific file history
git log --oneline -10 -- <file>
```

## Output Format

For each finding:
```
[SEVERITY] CATEGORY - Description
  Location: file.py:line
  Issue: What's wrong
  Recommendation: How to fix
```

Severity levels:
- `[CRITICAL]` - Security vulnerability, data loss risk
- `[HIGH]` - Bug, significant standards violation
- `[MEDIUM]` - Code smell, minor violation
- `[LOW]` - Suggestion, nitpick

## NEXUS-Specific Checks

| Pattern | Check | Location |
|---------|-------|----------|
| FSM transitions | Valid state changes | `core/fsm/states.py` |
| Message formats | Pydantic validation | `core/synapse/` |
| Tool handlers | Standard interface | `core/execution/handlers/` |
| Security guards | Proper validation | `core/security/` |
| Async patterns | No sync-in-async | `core/orchestration/` |

## Task: $ARGUMENTS

If `$ARGUMENTS` is empty, review uncommitted changes: `git diff`

If `$ARGUMENTS` contains:
- A path: review that file/directory
- A commit range: review those commits
- `--security`: focus on security issues

Provide structured review output with:
1. Summary (files reviewed, total findings by severity)
2. Critical/High findings (detailed)
3. Medium/Low findings (summarized)
4. Recommendations
