# Session Module

## Synopsis
The Session module provides session isolation for parallel task execution to prevent context bleeding between agents. It implements V9.7.1 HOME environment spoofing (replacing V9.7 CWD isolation) to isolate Gemini CLI session storage while keeping CWD at project root, preventing "ghost file" issues. Critical for SwarmEngine parallel execution and multi-agent orchestration.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `home_isolator.py` | HOME environment spoofing for session isolation with security fixes (V11 F24-F29) | `HomeIsolator` |
| `workspace_manager.py` | Workspace management with HOME isolation delegation | `SessionWorkspaceManager`, `get_workspace_manager()`, `reset_workspace_manager()` |
| `__init__.py` | Module initialization with public exports | All classes and functions from submodules |

## Key Interfaces

### SessionWorkspaceManager

**`SessionWorkspaceManager`**
- Manages isolated environments for session isolation
- V9.7.1: Delegates to HomeIsolator for HOME spoofing
- Thread-safe with RLock for concurrent SwarmEngine access
- V10 PRISM: Tenant-scoped via ServiceFactory when context active

**Key Methods:**
- `get_or_create_workspace(session_id: str, session_type: str = "swarm") -> Path`: Get/create isolated workspace (legacy V9.7 CWD isolation)
- `get_isolated_env(session_id: str, session_type: str = "swarm") -> Dict[str, str]`: **V9.7.1** - Get isolated environment with HOME spoofing
- `cleanup_workspace(session_id: str, session_type: str = "swarm") -> bool`: Cleanup isolated workspace
- `cleanup_isolated_env(session_id: str, session_type: str = "swarm") -> bool`: **V9.7.1** - Cleanup isolated HOME directory
- `get_default_workspace() -> Path`: Get base workspace (for FSM single-threaded mode)
- `list_active_workspaces() -> Dict[str, Path]`: List all active workspaces
- `get_stats() -> Dict[str, int]`: Get statistics (active_count, total_size_mb)

**Session Types:**
- `"fsm"`: FSM single-threaded mode (no isolation needed)
- `"hive"`: HiveMind per-task isolation
- `"swarm"`: SwarmEngine parallel isolation (default)
- `"agent"`: Spawned agent isolation

### HomeIsolator (V9.7.1 Core Component)

**`HomeIsolator`**
- Creates isolated HOME environments for subprocess session isolation
- **Key Insight**: Gemini CLI uses `os.homedir()` which respects `$HOME` / `%USERPROFILE%`
- Different HOME per agent = isolated session storage
- CWD stays at project root = file operations work correctly

**Security Features (V11 Fixes F24-F29):**
- **F24**: Workspace-unique prefixes to mitigate hash collisions (enabled by default in V12.4)
- **F26**: Reference counting for safe cleanup (prevents cleanup while in use)
- **F27**: Session ID sanitization to prevent path traversal (CWE-22)
- **F28**: Cross-platform app data isolation (APPDATA, XDG)
- **F29**: Disk quota monitoring and enforcement

**Key Methods:**
- `get_isolated_env(session_id: str) -> Dict[str, str]`: Get environment with isolated HOME
- `acquire_env(session_id: str) -> Dict[str, str]`: **F26** - Acquire with reference counting
- `release_env(session_id: str) -> int`: **F26** - Release reference (returns remaining count)
- `get_ref_count(session_id: str) -> int`: **F26** - Check current reference count
- `cleanup_home(session_id: str, force: bool = False) -> bool`: Cleanup HOME directory (respects refs unless force=True)
- `cleanup_old_homes(max_age_hours: float = 24.0) -> int`: Cleanup old homes by age
- `check_disk_quota(quota_mb: float = 500.0, warn_threshold: float = 0.8) -> Dict`: **F29** - Monitor disk usage
- `enforce_quota(quota_mb: float = 500.0) -> int`: **F29** - Auto-cleanup oldest sessions to enforce quota
- `get_stats() -> Dict`: Get statistics (active_count, total_size_mb)

**Cross-Platform HOME Isolation:**
- **Linux/macOS**: Sets `$HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`
- **Windows**: Sets `%USERPROFILE%`, `%HOMEDRIVE%`, `%HOMEPATH%`, `%HOME%`, `%APPDATA%`, `%LOCALAPPDATA%`

### Global Access Functions

**`get_workspace_manager(base_workspace: Optional[Path] = None) -> SessionWorkspaceManager`**
- Get workspace manager for current tenant context
- V10: Returns tenant-scoped manager via ServiceFactory
- V11 F30: Thread-safe singleton initialization with double-check locking
- Legacy: Global singleton

**`reset_workspace_manager() -> None`**
- Reset global singleton (for testing)
- V10: Also clears ServiceFactory tenant cache

## Dependencies & Integration

### Internal Dependencies
- `pathlib` - Path handling
- `threading` - RLock for thread safety
- `shutil` - Directory cleanup
- `os`, `sys` - Environment and platform detection
- `core.context` (V10) - Tenant context
- `core.factory` (V10) - Service factory

### Integration Points
- **SwarmEngine**: Uses isolated environments for parallel agent execution
- **HiveMind**: Uses per-task isolation to prevent context bleeding
- **ExecutionEngine**: Wraps subprocess calls with isolated environments
- **V10 PRISM**: Tenant-scoped workspace managers

### Directory Structure

```
workspace/
+-- .sessions/                    # Legacy V9.7 CWD isolation (deprecated)
|   +-- swarm_task_001_lead/
+-- .session_homes/               # V9.7.1 HOME spoofing
    +-- nx123456_swarm_task_001_lead/    # Isolated HOME (with workspace prefix)
    |   +-- .gemini/              # Gemini CLI session storage
    |   +-- AppData/              # Windows app data isolation
    |   +-- .config/              # XDG config (Linux)
    |   +-- .local/share/         # XDG data (Linux)
    |   +-- .cache/               # XDG cache (Linux)
    +-- nx123456_swarm_task_002_support/
```

### Usage Examples

```python
from core.session import SessionWorkspaceManager, HomeIsolator
import subprocess

# Create workspace manager
manager = SessionWorkspaceManager(Path("workspace"))

# V9.7.1: Get isolated environment (not workspace!)
isolated_env = manager.get_isolated_env("task_001_lead", "swarm")

# Pass to Gemini subprocess (CWD stays at project root!)
proc = subprocess.Popen(
    ["gemini", "chat", "--model", "gemini-3-pro-preview"],
    env=isolated_env,
    cwd=workspace_path  # CWD is NOT changed!
)

# Cleanup after task completion
manager.cleanup_isolated_env("task_001_lead", "swarm")

# V11 F26: Reference counting for safe cleanup
home_isolator = HomeIsolator(Path("workspace"))

# Acquire environment (increments ref count)
env = home_isolator.acquire_env("task_001_lead")
subprocess.Popen(cmd, env=env, cwd=workspace_path)

# Release environment (decrements ref count)
home_isolator.release_env("task_001_lead")

# Cleanup only succeeds if ref count is 0
home_isolator.cleanup_home("task_001_lead")  # Safe: respects ref count

# V11 F29: Disk quota enforcement
quota_check = home_isolator.check_disk_quota(quota_mb=500.0)
if quota_check["status"] == "exceeded":
    cleaned = home_isolator.enforce_quota(quota_mb=500.0)
    print(f"Cleaned {cleaned} sessions to enforce quota")
```

## Design Notes

### V9.7 to V9.7.1 Evolution

**Problem (V9.7 CWD Isolation):**
- Changed subprocess CWD to isolated workspace
- Gemini CLI sandboxes file operations to CWD
- Result: "Ghost files" written to isolated dir instead of project root

**Solution (V9.7.1 HOME Spoofing):**
- Keep CWD at project root (file operations work correctly)
- Change HOME env var (session storage is isolated)
- Gemini CLI session storage: `~/.gemini/tmp/<hash(cwd)>/chats/`
- Different HOME = Different session storage = Isolation without ghost files

### Security Fixes (V11)

- **F24**: Workspace-unique prefixes prevent hash collisions in multi-workspace deployments
- **F26**: Reference counting prevents cleanup while sessions are active
- **F27**: Session ID sanitization prevents path traversal attacks (CWE-22)
- **F28**: Cross-platform app data isolation (Windows APPDATA, Linux XDG)
- **F29**: Disk quota monitoring prevents disk exhaustion in production
- **F30**: Thread-safe singleton initialization (double-check locking)

### Thread Safety

- All methods protected by `RLock` (reentrant lock)
- Safe for concurrent access from multiple SwarmEngine executors
- V11 F30: Double-check locking pattern for singleton initialization

### V10 PRISM Integration

- Tenant-scoped workspace managers via ServiceFactory
- Automatic tenant context detection
- Graceful fallback to global singleton if no context active

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `session_efficiency_scorecard.py` | Per-session performance tracking with task completion rates, time-to-first-result, tool success rates, agent switch counts, and overall session quality scoring | `get_session_scorecard`, `SessionEfficiencyScorecard` |
| `session_analytics.py` | Per-session analytics tracking phase timings (duration, tokens, cost), agent action success rates, session-level aggregates, and cross-session pattern detection | `get_session_analytics`, `SessionAnalytics` |
| `state_recovery.py` | Session state capture and recovery with automatic snapshots, manual savepoints, and rollback capability for fault-tolerant session management | `get_recovery_manager`, `StateRecoveryManager` |
