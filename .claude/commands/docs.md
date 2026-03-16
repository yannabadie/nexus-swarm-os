---
description: "Documentation generation and maintenance - update READMEs, fix versions, audit docs"
allowed-tools: "Bash,Glob,Read,Grep,Write,Edit,TodoWrite"
---

# /docs Command - Documentation Agent

Invoke the documentation agent to generate, update, or audit documentation.

## Usage
- `/docs audit` - Audit all docs for gaps and version mismatches
- `/docs generate core/swarm` - Generate README for module
- `/docs update CHANGELOG` - Update changelog with recent changes
- `/docs fix-versions` - Fix version references (V8.x -> V12.4)
- `/docs "Add docstrings to MemoryService"` - Add specific documentation

## Arguments
`$ARGUMENTS` - The documentation task (audit, generate, update, fix-versions, or description)

## Current State

**Version**: V12.4 "COGNITIVE BOOST"

**Known Gaps**:
- `core/governance/` - No README
- `core/prompts/` - No README
- `core/ui/` - No README
- `CHANGELOG.md` - Missing V10-V12 entries
- Module READMEs - Some have V8.0/V9.x references

**Known Issues**:
- Windows paths in auto-generated docs
- `SESSION_CONTINUITY.md` location mismatch
- References to removed `doc_generator/`

## Documentation Standards

**Module README Template**:
```markdown
# {Module Name}

## Overview
## Architecture
## Usage
## API Reference
## Configuration
## See Also
```

**Docstring Style**: Google-style

**Version Reference**: Always use "V12.4" for current version

## Workflow

Based on doc-writer agent:

### For `audit`:
1. Glob all *.md files
2. Check for version mismatches (V8.x, V9.x, V10.x)
3. Identify missing module READMEs
4. Check for broken file references
5. Report gaps with priorities

### For `generate <path>`:
1. Scan target module
2. Read public APIs
3. Generate README from template
4. Add docstrings if missing

### For `update <file>`:
1. Read current file
2. Check for outdated content
3. Update with accurate information
4. Validate references exist

### For `fix-versions`:
1. Find all version mismatches
2. Update to V12.4
3. Remove Windows paths
4. Validate changes

## Task: $ARGUMENTS

Begin documentation work based on the specified task.

Report:
- Files updated (list with change summary)
- Version fixes (old -> new)
- Gaps identified
- Quality score
