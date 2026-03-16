# Claude Code Setup Guide for NEXUS

**Status**: [OK] Partially configured - Skills created, hooks exist, settings functional

## Current Configuration

### [OK] Existing Files

- `.claude/settings.json` - Permission rules + basic hooks
- `.claude/settings.local.json` - Local overrides
- `.claude/hooks/session_start.py` - SessionStart hook
- `.claude/hooks/post_test.py` - PostToolUse hook for pytest
- `.claude/skills/` - **NEW**: 4 essential skills created
- `.claude/rules/` - Empty (ready for custom rules)

### [OK] Skills Created (Use via natural language)

| Skill | Invocation | Purpose |
|-------|------------|---------|
| `test-strategy.md` | "write tests for..." | Testing patterns, fixtures, coverage |
| `commit-format.md` | "create a commit..." | Commit conventions, git workflow |
| `swarm-modes.md` | "which collaboration mode..." | Swarm Engine mode selection |
| `debug-ci.md` | "CI is failing..." | GitHub Actions troubleshooting |

**Skills are invoked automatically** when Claude detects relevant keywords in your prompts.

## [OK] Completed Optimizations

### 1. CLAUDE.md Optimization
**Status**: [OK] DONE
- **Before**: 769 lines (too verbose)
- **After**: 270 lines (optimized)
- **Reduction**: 65% (-499 lines)
- **Method**: Moved detailed patterns to skills, removed redundant explanations, kept only essentials

**What was removed**:
- Verbose vision/concept explanations -> Condensed to core purpose
- Detailed testing patterns -> Already in test-strategy.md skill
- Commit format examples -> Already in commit-format.md skill
- Swarm mode details -> Already in swarm-modes.md skill
- Code style conventions -> Claude already knows Python best practices

**What was kept**:
- Project purpose & mission
- Critical rules (verification, testing, security)
- Tech stack essentials
- Key commands
- Architecture map (condensed)
- Anti-patterns

## Recommended Enhancements

### 1. Enhanced Hooks (Manual Setup Required)

**Due to JSON schema constraints**, hooks must be configured manually. Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash.*git push.*origin (NX|main)",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'branch=$(git branch --show-current); if [[ \"$branch\" == \"NX\" || \"$branch\" == \"main\" ]]; then echo \"ERROR: Cannot push directly to protected branch\"; exit 2; fi'"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit.*\\.py$",
        "hooks": [
          {
            "type": "command",
            "command": "ruff format $CLAUDE_FILE_PATH"
          }
        ]
      },
      {
        "matcher": "Write.*\\.py$",
        "hooks": [
          {
            "type": "command",
            "command": "python -m py_compile $CLAUDE_FILE_PATH"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo '💡 Remember: Always verify claims with actual outputs (gh run list, pytest)'"
          }
        ]
      }
    ]
  }
}
```

**Exit codes**:
- `0` = Success (continue)
- `2` = Blocking error (PreToolUse only)
- Other = Warning (logs but continues)

### 2. ~~Trim CLAUDE.md~~ [OK] COMPLETED

**Previous**: 769 lines
**Current**: 270 lines [OK]
**Status**: Optimized (under 300-line target)

**Result**: Improved instruction clarity and reduced cognitive load. All essential information preserved, verbose explanations removed or condensed.

### 3. Create Rules (Optional)

**Rules** (`rules/*.md`) are like skills but always active.

**Example**: `.claude/rules/verification-protocol.md`
```markdown
# Verification Protocol

When claiming something is "fixed" or "complete":

1. Execute verification command
2. Check actual output
3. Document evidence
4. NEVER claim success without proof

Examples:
- "CI fixed" -> Run `gh run list` and verify "success"
- "Tests pass" -> Run `pytest` and verify 0 failures
```

Rules are **always enforced**, unlike skills which activate contextually.

## Usage Examples

### Using Skills

```
# Test writing (auto-invokes test-strategy.md)
User: "Write tests for the GuardPipeline module"
Claude: [Applies test-strategy patterns automatically]

# Committing (auto-invokes commit-format.md)
User: "Commit these changes"
Claude: [Uses NEXUS commit format with co-author]

# Swarm mode selection (auto-invokes swarm-modes.md)
User: "Design the API schema collaboratively"
Claude: [Suggests PING_PONG mode based on skill]

# CI debugging (auto-invokes debug-ci.md)
User: "The GitHub Actions are failing"
Claude: [Uses debug-ci checklist automatically]
```

### Verifying Configuration

```bash
# Check settings are valid
cat .claude/settings.json | jq .

# List available skills
ls .claude/skills/

# Test SessionStart hook
# (Triggers automatically when starting Claude Code)
```

## Project-Specific Best Practices

### NEXUS Testing

**Always run tests before pushing**:
```bash
# Quick validation
pytest tests/ --tb=short

# With coverage
pytest tests/ --cov=core --cov-fail-under=40

# Syntax check
find core -name "*.py" -exec python -m py_compile {} \;
```

### NEXUS Git Workflow

**Branch strategy**:
- `NX-CG` - Active development (use this)
- `NX` - Main branch (protected)
- `main` - Legacy (rarely used)

**Never**:
- [NO] Push directly to `NX` or `main`
- [NO] Force push
- [NO] Skip hooks (`--no-verify`)

### NEXUS Verification Protocol

**After every fix**:
```bash
git push origin NX-CG
sleep 15
gh run list --branch NX-CG --limit 1
# If failed:
gh run view <run-id> --log-failed
```

## MCP Servers (Already Configured)

NEXUS has MCP servers configured in `.mcp.json`:
- **Notion** - Documentation access
- **Hugging Face** - Model/dataset search

**Enable if needed**:
```bash
# Check MCP status
cat .mcp.json

# Enable all project MCP servers
# (Add to .claude/settings.json)
"enableAllProjectMcpServers": true
```

## Troubleshooting

### Skills not activating

**Check**:
1. File exists: `ls .claude/skills/test-strategy.md`
2. YAML frontmatter valid (name, description)
3. Keywords in description match your prompt

### Hooks not running

**Check**:
1. Matcher regex correct
2. Exit code appropriate (0=success, 2=block)
3. Command syntax valid
4. File permissions (`chmod +x .claude/hooks/*.py`)

### Performance issues

**If Claude is slow**:
1. CLAUDE.md too long (trim to < 300 lines)
2. Too many active hooks
3. Skills too verbose (keep focused)

## Next Steps

1. **Immediate**: Use the 4 skills created (automatic)
2. **Optional**: Add enhanced hooks (manual JSON edit)
3. **Recommended**: Trim CLAUDE.md (from 500 -> 300 lines)
4. **Advanced**: Create custom rules for NEXUS-specific patterns

## Resources

- Skills documentation: Each skill has usage examples
- Claude Code docs: https://code.claude.com/docs
- NEXUS best practices: `docs/CLAUDE_CODE_RULES_RECOMMENDATIONS.md`

**Remember**: The goal is to make NEXUS development **faster and safer** through intelligent automation [OK]
