# Audit Tests

## Synopsis

System integrity audit tests validating isolation physics, workspace boundaries, environment variable protection, and concurrent execution safety. Ensures NEXUS maintains strict isolation between sessions, workspaces, and tenants.

## Architecture

```mermaid
classDiagram
    class TestAuditLoggerUnit {
        +setup_db(self, tmp_path)
        +test_audit_log_model_fields(self)
        +test_audit_log_defaults(self)
        +test_audit_action_enum(self)
    }
    class TestAuditLoggerAsync {
        +setup_db(self, tmp_path)
        +test_log_creates_entry(self)
        +test_log_with_details(self)
        +test_log_permission_denied(self)
        +test_concurrent_logging(self)
    }
    class TestAuditLoggerQueries {
        +setup_db(self, tmp_path)
        +test_query_logs_for_tenant(self)
        +test_query_logs_with_action_filter(self)
    }
    class TestAuditLogImmutability {
        +setup_db(self, tmp_path)
        +test_no_update_method(self)
        +test_no_delete_method(self)
    }
    class IsolationPhysicsProof {
        +workspace
        +results
        +proof_dir
        -__init__(self, workspace: Path)
        +test_home_isolation(self) dict
        +test_cwd_preservation(self) dict
        +test_env_leak_prevention(self) dict
        +test_concurrent_isolation(self) dict
        +test_cleanup_works(self) dict
        +run_all(self) dict
        +cleanup(self)
    }
```

## Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_isolation_physics.py` | Workspace isolation, CWD preservation, env leak prevention | Home isolation, concurrent isolation, cleanup verification |

## Test Coverage

### Isolation Physics Tests

**IsolationPhysicsProof** - Comprehensive isolation verification
- `test_home_isolation()` - HOME environment variable isolation per workspace
- `test_cwd_preservation()` - Current working directory (CWD) preservation
- `test_env_leak_prevention()` - Environment variable leak prevention
- `test_concurrent_isolation()` - Concurrent session isolation (no cross-contamination)
- `test_cleanup_works()` - Workspace cleanup verification

**Validation Approach**:
- Creates multiple isolated workspaces
- Verifies HOME is set to workspace path
- Ensures CWD is preserved across operations
- Tests concurrent operations for race conditions
- Validates cleanup removes all workspace data

## Running Tests

```bash
# All audit tests
python -m pytest tests/audit/ -v

# Isolation physics only
python -m pytest tests/audit/test_isolation_physics.py -v

# Run isolation proof manually
python tests/audit/test_isolation_physics.py
```

## Dependencies

- `pytest` - Test framework
- `pathlib` - Path operations
- `tempfile` - Temporary directories
- `concurrent.futures` - Concurrent execution

## Critical Guarantees

These tests verify NEXUS maintains:
1. **Workspace Isolation** - Each workspace has independent HOME
2. **CWD Preservation** - Operations don't change working directory
3. **Env Protection** - Environment variables don't leak between sessions
4. **Concurrent Safety** - Multiple sessions don't interfere
5. **Clean Teardown** - Workspaces are fully removed on cleanup

## Related Modules

- [core/workspace/](../../core/workspace/) - Workspace management
- [core/session/](../../core/session/) - Session management
- [KERNEL.py](../../KERNEL.py) - Security boundaries