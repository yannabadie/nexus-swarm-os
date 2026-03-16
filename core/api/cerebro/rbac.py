"""
NEXUS V12.2 IRONCLAD - Role-Based Access Control

Provides permission enforcement for CEREBRO API endpoints.

Usage:
    from core.api.cerebro.rbac import require_permission, Permission

    @router.get("/files")
    async def list_files(
        user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ)),
    ):
        ...

Roles:
    - OWNER: Full control (all permissions)
    - ADMIN: Manage users, settings, full workspace access
    - MEMBER: Standard access (read/write files, run workflows)
    - VIEWER: Read-only access

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import logging
from enum import Enum
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from .deps import AuthenticatedUser, require_auth

logger = logging.getLogger(__name__)


# =============================================================================
# Permissions
# =============================================================================


class Permission(str, Enum):
    """Granular permissions for NEXUS operations."""

    # Files
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"

    # Workspace
    WORKSPACE_CREATE = "workspace:create"
    WORKSPACE_DELETE = "workspace:delete"
    WORKSPACE_SETTINGS = "workspace:settings"

    # Users
    USER_INVITE = "user:invite"
    USER_REMOVE = "user:remove"
    USER_CHANGE_ROLE = "user:change_role"

    # Workflow
    WORKFLOW_START = "workflow:start"
    WORKFLOW_STOP = "workflow:stop"

    # Admin
    AUDIT_VIEW = "audit:view"
    SETTINGS_MANAGE = "settings:manage"


# =============================================================================
# Role -> Permission Mapping
# =============================================================================

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    # OWNER: Full control
    "owner": set(Permission),
    # ADMIN: Everything except billing/ownership
    "admin": {
        Permission.FILE_READ,
        Permission.FILE_WRITE,
        Permission.FILE_DELETE,
        Permission.WORKSPACE_CREATE,
        Permission.WORKSPACE_DELETE,
        Permission.WORKSPACE_SETTINGS,
        Permission.USER_INVITE,
        Permission.USER_REMOVE,
        Permission.WORKFLOW_START,
        Permission.WORKFLOW_STOP,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE,
    },
    # MEMBER: Standard access
    "member": {
        Permission.FILE_READ,
        Permission.FILE_WRITE,
        Permission.WORKFLOW_START,
        Permission.WORKFLOW_STOP,
    },
    # VIEWER: Read-only
    "viewer": {
        Permission.FILE_READ,
    },
}


# =============================================================================
# Permission Checking
# =============================================================================


def get_user_role(user_id: UUID, tenant_id: UUID) -> str | None:
    """
    Get user's role from database.

    Args:
        user_id: User UUID
        tenant_id: Tenant UUID

    Returns:
        Role string or None if user not found
    """
    try:
        from sqlmodel import select

        from core.infrastructure.db import User, get_session

        with get_session() as session:
            statement = select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.is_active)
            user = session.exec(statement).first()

            if user:
                return user.role.value if hasattr(user.role, "value") else str(user.role)

        return None

    except Exception as e:
        logger.warning(f"[RBAC] Failed to get user role: {e}")
        return None


def has_permission(role: str, permission: Permission) -> bool:
    """
    Check if a role has a specific permission.

    Args:
        role: User role string
        permission: Permission to check

    Returns:
        True if role has permission
    """
    role_perms = ROLE_PERMISSIONS.get(role.lower(), set())
    return permission in role_perms


async def log_permission_denial(
    user: AuthenticatedUser,
    permission: Permission,
    resource_type: str,
    resource_id: str | None = None,
    request: Request | None = None,
) -> None:
    """
    Log a permission denial to audit log.

    Args:
        user: Authenticated user
        permission: Permission that was denied
        resource_type: Type of resource
        resource_id: Optional resource identifier
        request: Optional FastAPI request
    """
    try:
        from core.observability.audit import AuditLogger

        await AuditLogger.log_permission_denied(
            tenant_id=UUID(user.tenant_id),
            user_id=UUID(user.user_id),
            permission=permission.value,
            resource_type=resource_type,
            resource_id=resource_id,
            request=request,
        )
    except Exception as e:
        logger.warning(f"[RBAC] Failed to log permission denial: {e}")


# =============================================================================
# FastAPI Dependencies
# =============================================================================


def require_permission(permission: Permission, resource_type: str = "api"):
    """
    FastAPI dependency for permission checking.

    Usage:
        @router.get("/files")
        async def list_files(
            user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ)),
        ):
            ...

    Args:
        permission: Required permission
        resource_type: Type of resource being accessed (for audit)

    Returns:
        Dependency function
    """

    async def check_permission(
        request: Request,
        user: AuthenticatedUser = Depends(require_auth),
    ) -> AuthenticatedUser:
        """
        Check if authenticated user has required permission.

        Args:
            request: FastAPI request
            user: Authenticated user from require_auth

        Returns:
            AuthenticatedUser if authorized

        Raises:
            HTTPException 403 if permission denied
        """
        # Get role from JWT token (set during login)
        role = getattr(user, "role", None)

        # If role not in token, try to get from database
        if not role:
            try:
                role = get_user_role(UUID(user.user_id), UUID(user.tenant_id))
            except Exception as e:
                logger.error("[RBAC] Failed to get user role: %s", e, exc_info=True)
                role = None

        # Default to viewer if no role found (most restrictive)
        if not role:
            role = "viewer"
            logger.warning(f"[RBAC] No role found for user {user.user_id}, defaulting to 'viewer'")

        # Check permission
        if not has_permission(role, permission):
            logger.warning(f"[RBAC] Permission denied: user={user.user_id} role={role} permission={permission.value}")

            # Log to audit
            await log_permission_denial(
                user=user,
                permission=permission,
                resource_type=resource_type,
                resource_id=str(request.url),
                request=request,
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )

        return user

    return check_permission


def require_role(role: str):
    """
    FastAPI dependency for role checking.

    Less granular than require_permission, but useful for
    simple role-based access.

    Usage:
        @router.get("/admin")
        async def admin_panel(
            user: AuthenticatedUser = Depends(require_role("admin")),
        ):
            ...

    Args:
        role: Required role (owner, admin, member, viewer)

    Returns:
        Dependency function
    """
    # Map role to minimum required role
    role_hierarchy = ["viewer", "member", "admin", "owner"]

    async def check_role(
        user: AuthenticatedUser = Depends(require_auth),
    ) -> AuthenticatedUser:
        """Check if user has at least the required role."""
        user_role = getattr(user, "role", None)

        if not user_role:
            try:
                user_role = get_user_role(UUID(user.user_id), UUID(user.tenant_id))
            except Exception:
                user_role = None

        if not user_role:
            user_role = "viewer"

        # Check role hierarchy
        try:
            user_level = role_hierarchy.index(user_role.lower())
            required_level = role_hierarchy.index(role.lower())

            if user_level < required_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role '{role}' or higher required",
                )

            return user

        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Invalid role: {user_role}",
            ) from err

    return check_role
