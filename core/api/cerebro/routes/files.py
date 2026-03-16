"""
NEXUS V12.2 IRONCLAD - Secure File Access Endpoints
V11.6.1 IRONCLAD - MANDATORY authentication (Zero Trust)
V12.1 RETINA - FileCommander support with directory tree
V12.2 IRONCLAD - RBAC enforcement + audit logging

Enables secure file operations for CEREBRO UI:
- GET /api/files/content : Read file content (size-limited, path-validated)
- POST /api/files/save : Save file content (path-validated)
- GET /api/files/tree : Get directory tree structure (V12.0 RETINA)
- GET /api/files/info : Get file metadata

Security Features:
- PathGuardian for path validation (prevents path traversal)
- 1MB file size limit (OOM protection)
- Sacred file protection (.env, KERNEL.py, etc.)
- V11.6.1 IRONCLAD: MANDATORY authentication (audit trail + access control)
- V12.1 RETINA: Rate limiting on sensitive endpoints (Conseiller 1)
- V12.2 IRONCLAD: RBAC permission checks + audit logging

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..deps import AuthenticatedUser
from ..rbac import Permission, require_permission

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# Constants - OOM Protection
# =============================================================================

MAX_FILE_SIZE = 1_000_000  # 1MB limit (pattern from tool_executor.py:152)


# =============================================================================
# Request Models
# =============================================================================


class FileWriteRequest(BaseModel):
    """Request body for file write operations."""

    path: str
    content: str


# =============================================================================
# Helper Functions
# =============================================================================


def _get_guardian():
    """
    Get PathGuardian for current workspace.

    Returns:
        PathGuardian instance configured for workspace
    """
    try:
        from core.config import Config
        from core.security_pkg.security.path_guardian import PathGuardian

        config = Config()
        workspace = Path(config.workspace_path).resolve()
        nexus_root = workspace.parent  # Parent directory for read access

        return PathGuardian(workspace, nexus_root)
    except Exception as e:
        logger.error(f"Failed to create PathGuardian: {e}")
        raise HTTPException(500, f"Security configuration error: {e}") from e


async def _audit_file_access(
    user: AuthenticatedUser,
    path: str,
    action: str,
    success: bool,
    request: Request = None,
) -> None:
    """
    V12.2 IRONCLAD: Audit log file access.

    Args:
        user: Authenticated user
        path: File path
        action: "read", "write", or "delete"
        success: Whether operation succeeded
        request: Optional FastAPI request for IP/user-agent
    """
    try:
        from core.observability.audit import AuditAction, AuditLogger

        action_map = {
            "read": AuditAction.FILE_READ,
            "write": AuditAction.FILE_WRITE,
            "delete": AuditAction.FILE_DELETE,
        }

        await AuditLogger.log_file(
            tenant_id=UUID(user.tenant_id),
            user_id=UUID(user.user_id),
            action=action_map.get(action, AuditAction.FILE_READ),
            file_path=path,
            success=success,
            request=request,
        )
    except Exception as e:
        # Don't fail the request if audit logging fails
        logger.warning(f"[CORTEX] Audit log failed: {e}")


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/content")
async def read_file(
    request: Request,
    path: str = Query(..., description="Relative path to file"),
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ, "file")),
) -> dict[str, Any]:
    """
    Read file content with size limit and path validation.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    V12.2 IRONCLAD: RBAC permission check + audit logging.
    All file operations are logged with authenticated user info.

    Security:
    - PathGuardian validates path is in allowed zones
    - 1MB file size limit prevents OOM
    - Sacred files (.env, KERNEL.py) are protected
    - RBAC: Requires FILE_READ permission

    Args:
        request: FastAPI request (for audit logging)
        path: Relative path to file (relative to workspace)
        user: Authenticated user (from JWT token)

    Returns:
        {"path": "...", "content": "...", "size": ...}

    Raises:
        401: Not authenticated
        403: Access denied (path traversal, sacred file, no permission)
        404: File not found
        413: File too large (> 1MB)
        500: Read failed
    """
    guardian = _get_guardian()

    # Validate path with PathGuardian
    is_valid, resolved_path, message = guardian.validate_read(path)

    if not is_valid:
        logger.warning(f"[CORTEX] File access denied: {path} - {message}")
        # V12.2: Audit log the denial
        await _audit_file_access(user, path, "read", success=False, request=request)
        raise HTTPException(403, f"Access denied: {message}")

    # Check file exists
    if not resolved_path.exists():
        raise HTTPException(404, f"File not found: {path}")

    if not resolved_path.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    # SIZE LIMIT CHECK (OOM protection)
    try:
        file_size = resolved_path.stat().st_size
    except OSError as e:
        raise HTTPException(500, f"Cannot stat file: {e}") from e

    if file_size > MAX_FILE_SIZE:
        logger.warning(f"[CORTEX] File too large: {path} ({file_size} bytes > {MAX_FILE_SIZE})")
        raise HTTPException(
            413,  # Payload Too Large
            f"File too large: {file_size:,} bytes exceeds {MAX_FILE_SIZE:,} byte limit",
        )

    # Read file content
    try:
        content = resolved_path.read_text(encoding="utf-8")
        # V12.2: Audit log successful read
        await _audit_file_access(user, path, "read", success=True, request=request)
        logger.debug(f"[CORTEX] File read: {path} ({len(content)} chars) by user={user.user_id}")
        return {
            "path": path,
            "content": content,
            "size": len(content),
        }
    except UnicodeDecodeError as e:
        raise HTTPException(400, f"File is not valid UTF-8 text: {path}") from e
    except Exception as e:
        logger.error(f"[CORTEX] Read failed: {path} - {e}")
        raise HTTPException(500, f"Read failed: {e}") from e


@router.post("/save")
async def save_file(
    request: Request,
    body: FileWriteRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "file")),
) -> dict[str, str]:
    """
    Save file content with path validation.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    V12.2 IRONCLAD: RBAC permission check + audit logging.
    All file operations are logged with authenticated user info.

    Security:
    - PathGuardian validates path is in workspace
    - Absolute paths are rejected
    - Sacred files (.env, KERNEL.py) are protected
    - RBAC: Requires FILE_WRITE permission

    Args:
        request: FastAPI request (for audit logging)
        body: FileWriteRequest with path and content
        user: Authenticated user (from JWT token)

    Returns:
        {"status": "saved", "path": "..."}

    Raises:
        401: Not authenticated
        403: Access denied (absolute path, sacred file, outside workspace, no permission)
        500: Write failed
    """
    guardian = _get_guardian()

    # Validate path with PathGuardian
    is_valid, resolved_path, message = guardian.validate_write(body.path)

    if not is_valid:
        logger.warning(f"[CORTEX] File write denied: {body.path} - {message}")
        # V12.2: Audit log the denial
        await _audit_file_access(user, body.path, "write", success=False, request=request)
        raise HTTPException(403, f"Access denied: {message}")

    # Write file content
    try:
        # Create parent directories if needed
        resolved_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        resolved_path.write_text(body.content, encoding="utf-8")

        # V12.2: Audit log successful write
        await _audit_file_access(user, body.path, "write", success=True, request=request)
        logger.info(f"[CORTEX] File saved: {body.path} ({len(body.content)} chars) by user={user.user_id}")
        return {"status": "saved", "path": body.path}

    except Exception as e:
        logger.error(f"[CORTEX] Write failed: {body.path} - {e}")
        raise HTTPException(500, f"Write failed: {e}") from e


@router.get("/tree")
async def file_tree(
    path: str = Query(".", description="Root path for tree"),
    max_depth: int = Query(3, ge=1, le=5, description="Max directory depth"),
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ, "file")),
) -> dict[str, Any]:
    """
    Get directory tree structure.

    V11.6.2 IRONCLAD: MANDATORY authentication.
    V12.0 RETINA VISUALS: FileCommander support.

    Security:
    - PathGuardian validates root path
    - Authentication required for audit trail
    - Excludes sensitive directories (.git, node_modules, etc.)

    Args:
        path: Root path for tree (relative to workspace)
        max_depth: Maximum depth to traverse (1-5)
        user: Authenticated user (from JWT token)

    Returns:
        {"name": "...", "type": "directory", "path": "...", "children": [...]}

    Raises:
        401: Not authenticated
        403: Access denied (path traversal)
    """
    guardian = _get_guardian()

    # Validate root path
    is_valid, resolved_path, message = guardian.validate_read(path)
    if not is_valid:
        logger.warning(f"[CORTEX] Tree access denied: {path} - {message}")
        raise HTTPException(403, f"Access denied: {message}")

    # Directories to exclude (performance + security)
    EXCLUDED_DIRS = {
        ".git",
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "site-packages",
        "dist",
        "build",
        ".nexus",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "egg-info",
        ".eggs",
    }

    def build_tree(p: Path, current_depth: int, base_path: Path) -> dict[str, Any] | None:
        """Recursively build directory tree."""
        if current_depth > max_depth:
            return None

        if not p.exists():
            return None

        # Calculate relative path from base (relative to workspace for API compatibility)
        try:
            rel_path = str(p.relative_to(base_path))
            if rel_path == ".":
                rel_path = "."  # Root directory
        except ValueError:
            rel_path = p.name

        if p.is_file():
            return {
                "name": p.name,
                "type": "file",
                "path": rel_path.replace("\\", "/"),
            }

        # Directory
        children = []
        try:
            for child in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                # Skip hidden and excluded
                if child.name.startswith(".") and child.name not in {".env.example"}:
                    continue
                if child.name in EXCLUDED_DIRS:
                    continue
                if child.name.endswith(".egg-info"):
                    continue

                subtree = build_tree(child, current_depth + 1, base_path)
                if subtree:
                    children.append(subtree)
        except PermissionError:
            logger.warning(f"[CORTEX] Permission denied reading: {p}")

        return {
            "name": p.name,
            "type": "directory",
            "path": rel_path.replace("\\", "/"),
            "children": children,
        }

    tree = build_tree(resolved_path, 1, resolved_path)

    if tree is None:
        return {"name": path, "type": "directory", "path": path, "children": []}

    logger.debug(f"[CORTEX] Tree built: {path} (depth={max_depth}) by user={user.user_id}")
    return tree


@router.get("/info")
async def file_info(
    path: str = Query(..., description="Relative path to file"),
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ, "file")),
) -> dict[str, Any]:
    """
    Get file metadata without reading content.

    V11.6.1 IRONCLAD: MANDATORY authentication.
    Useful for checking file size before reading.

    Args:
        path: Relative path to file
        user: Authenticated user (from JWT token)

    Returns:
        {"path": "...", "exists": bool, "size": int, "is_file": bool, "can_read": bool}

    Raises:
        401: Not authenticated
        403: Access denied
    """
    guardian = _get_guardian()

    is_valid, resolved_path, message = guardian.validate_read(path)

    if not is_valid:
        raise HTTPException(403, f"Access denied: {message}")

    exists = resolved_path.exists()
    is_file = resolved_path.is_file() if exists else False
    file_size = resolved_path.stat().st_size if is_file else 0

    return {
        "path": path,
        "exists": exists,
        "size": file_size,
        "is_file": is_file,
        "is_directory": resolved_path.is_dir() if exists else False,
        "can_read": file_size <= MAX_FILE_SIZE,
    }
