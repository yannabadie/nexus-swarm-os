# Scripts

## Synopsis

Utility scripts for NEXUS maintenance, documentation generation, database initialization, and version migrations. These scripts are developer tools for maintaining system integrity and consistency.

## Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `doc_engine.py` | Documentation synchronization and architecture map generation | `python scripts/doc_engine.py --check` |
| `init_db.py` | Database initialization and schema creation | `python scripts/init_db.py` |
| `migrate_v9_to_v10.py` | V9 to V10 migration (PRISM multi-tenancy) | `python scripts/migrate_v9_to_v10.py` |

## doc_engine.py

**NEXUS Documentation Engine V2.2** - Unified documentation synchronization system.

### Modes

- `--check` - Read-only audit (CI-safe, exit code 1 if issues)
- `--sync` - Update version patterns in docs (dry-run by default)
- `--gen-map` - Generate ARCHITECTURE_MAP_GENERATED.md
- `--audit` - Check module READMEs exist and are up-to-date
- `--full` - All of the above
- `--apply` - Actually write changes (use with other modes)

### Features

- Version synchronization from .env (NEXUS_VERSION, NEXUS_CODENAME)
- Architecture map generation with 10 ZOOM sections
- Dynamic extraction of commands, dataclasses, enums
- Test coverage statistics
- Torture protocol test scanning
- Anti-hallucination validation

### Usage

```bash
# CI: Verify consistency
python scripts/doc_engine.py --check

# Show what would change
python scripts/doc_engine.py --sync

# Actually update files
python scripts/doc_engine.py --sync --apply

# Generate architecture map
python scripts/doc_engine.py --gen-map --apply

# Everything
python scripts/doc_engine.py --full --apply
```

### Safety

- Idempotent (same result if run multiple times)
- Minimal changes (only version patterns, never content)
- Dry-run by default (--apply to actually write)
- All changes logged with before/after

## init_db.py

Database initialization script for NEXUS multi-tenant database.

### Purpose

- Creates database schema (tables, indexes, constraints)
- Initializes default tenant/workspace
- Sets up audit log tables
- Creates HITL request tables
- Initializes hibernation state tables
- Creates workflow registry tables

### Usage

```bash
# Initialize database
python scripts/init_db.py

# Initialize with custom database URL
DATABASE_URL=sqlite:///custom.db python scripts/init_db.py
```

### Tables Created

- `tenants` - Tenant accounts
- `workspaces` - Workspace isolation
- `audit_logs` - Audit trail (immutable)
- `hitl_requests` - Human-in-the-loop requests
- `hibernation_states` - Session hibernation
- `workflow_registry` - Distributed workflow tracking

## migrate_v9_to_v10.py

Migration script from NEXUS V9 (single-tenant) to V10 (PRISM multi-tenant).

### Purpose

- Migrates V9 workspace data to V10 PRISM structure
- Creates default tenant/workspace for existing data
- Updates file paths to tenant-aware structure
- Migrates memory storage to isolated paths
- Updates database schema

### Usage

```bash
# Dry run (show what would change)
python scripts/migrate_v9_to_v10.py --dry-run

# Actually migrate
python scripts/migrate_v9_to_v10.py

# Migrate with custom tenant/workspace IDs
python scripts/migrate_v9_to_v10.py --tenant-id custom_tenant --workspace-id custom_ws
```

### Migration Steps

1. Backup existing workspace
2. Create default tenant/workspace
3. Migrate memory storage paths
4. Update database records
5. Verify migration integrity

### Rollback

Create backup before migration:
```bash
cp -r workspace workspace_backup_v9
python scripts/migrate_v9_to_v10.py
```

## Running Scripts

```bash
# From NEXUS root directory
python scripts/doc_engine.py --check
python scripts/init_db.py
python scripts/migrate_v9_to_v10.py --dry-run
```

## Dependencies

- **doc_engine.py**: Standard library only (ast, json, pathlib, re)
- **init_db.py**: sqlalchemy, core.db.models
- **migrate_v9_to_v10.py**: sqlalchemy, pathlib, shutil

## Related

- [docs/architecture/](../docs/architecture/) - Architecture documentation
- [core/db/models.py](../core/db/models.py) - Database models
- [.env](.env) - Version configuration