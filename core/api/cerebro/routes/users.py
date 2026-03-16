"""
NEXUS V12.2 IRONCLAD - User Management API

Provides user management endpoints for CEREBRO UI:
- GET /api/users : List users in tenant
- POST /api/users/invite : Invite a new user
- DELETE /api/users/{user_id} : Remove a user
- PATCH /api/users/{user_id}/role : Change user role

Security:
- All endpoints require authentication
- RBAC enforcement (USER_INVITE, USER_REMOVE, USER_CHANGE_ROLE permissions)
- Audit logging for all operations

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..deps import AuthenticatedUser
from ..rbac import Permission, require_permission

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================


class UserResponse(BaseModel):
    """User information response."""

    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    last_login: datetime | None = None


class UserListResponse(BaseModel):
    """List of users response."""

    users: list[UserResponse]
    total: int


class InviteUserRequest(BaseModel):
    """Request to invite a new user."""

    username: str
    email: EmailStr
    role: str = "member"  # Default role
    password: str | None = None  # Optional, will generate if not provided


class ChangeRoleRequest(BaseModel):
    """Request to change user role."""

    role: str


# =============================================================================
# Helper Functions
# =============================================================================


def _get_users(tenant_id: UUID) -> list[dict]:
    """Get all users for a tenant (sync, for thread pool)."""
    from sqlmodel import select

    from core.infrastructure.db import User, get_session

    with get_session() as session:
        statement = select(User).where(User.tenant_id == tenant_id)
        users = session.exec(statement).all()

        return [
            {
                "id": str(u.id),
                "username": u.username,
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                "is_active": u.is_active,
                "created_at": u.created_at,
                "last_login": u.last_login,
            }
            for u in users
        ]


def _create_user(
    tenant_id: UUID,
    username: str,
    email: str,
    password: str,
    role: str,
) -> dict:
    """Create a new user (sync, for thread pool)."""
    from sqlmodel import select

    from core.infrastructure.db import User, UserRole, get_session
    from core.security_pkg.security.password import hash_password

    with get_session() as session:
        # Check if username already exists in tenant
        statement = select(User).where(
            User.tenant_id == tenant_id,
            User.username == username,
        )
        if session.exec(statement).first():
            raise ValueError(f"Username '{username}' already exists")

        # Check if email already exists in tenant
        statement = select(User).where(
            User.tenant_id == tenant_id,
            User.email == email,
        )
        if session.exec(statement).first():
            raise ValueError(f"Email '{email}' already exists")

        # Validate role
        try:
            user_role = UserRole(role)
        except ValueError:
            raise ValueError(f"Invalid role: {role}") from None

        # Create user
        user = User(
            tenant_id=tenant_id,
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=user_role,
            is_active=True,
        )

        session.add(user)
        session.commit()
        session.refresh(user)

        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "is_active": user.is_active,
            "created_at": user.created_at,
        }


def _delete_user(tenant_id: UUID, user_id: UUID) -> bool:
    """Delete a user (sync, for thread pool)."""
    from sqlmodel import select

    from core.infrastructure.db import User, get_session

    with get_session() as session:
        statement = select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
        )
        user = session.exec(statement).first()

        if not user:
            return False

        session.delete(user)
        session.commit()
        return True


def _change_role(tenant_id: UUID, user_id: UUID, new_role: str) -> dict | None:
    """Change user role (sync, for thread pool)."""
    from sqlmodel import select

    from core.infrastructure.db import User, UserRole, get_session

    with get_session() as session:
        statement = select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
        )
        user = session.exec(statement).first()

        if not user:
            return None

        # Validate role
        try:
            user.role = UserRole(new_role)
        except ValueError:
            raise ValueError(f"Invalid role: {new_role}") from None

        session.add(user)
        session.commit()
        session.refresh(user)

        return {
            "id": str(user.id),
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        }


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=UserListResponse)
async def list_users(
    user: AuthenticatedUser = Depends(require_permission(Permission.USER_INVITE, "user")),
) -> UserListResponse:
    """
    List all users in the tenant.

    Requires USER_INVITE permission (admin+).

    Returns:
        List of users with their roles and status
    """
    import asyncio

    users = await asyncio.to_thread(_get_users, UUID(user.tenant_id))

    return UserListResponse(
        users=[UserResponse(**u) for u in users],
        total=len(users),
    )


@router.post("/invite", response_model=UserResponse)
async def invite_user(
    body: InviteUserRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.USER_INVITE, "user")),
) -> UserResponse:
    """
    Invite a new user to the tenant.

    Requires USER_INVITE permission (admin+).

    Args:
        body: InviteUserRequest with username, email, role

    Returns:
        Created user info

    Raises:
        400: Username or email already exists
        403: Permission denied
    """
    import asyncio
    import secrets

    # Generate password if not provided
    password = body.password or secrets.token_urlsafe(12)

    try:
        result = await asyncio.to_thread(
            _create_user,
            UUID(user.tenant_id),
            body.username,
            body.email,
            password,
            body.role,
        )

        # Audit log
        try:
            from core.observability.audit import AuditAction, AuditLogger

            await AuditLogger.log(
                tenant_id=UUID(user.tenant_id),
                user_id=UUID(user.user_id),
                action=AuditAction.USER_CREATE,
                resource_type="user",
                resource_id=result["id"],
            )
        except Exception as e:
            logger.warning(f"[USERS] Audit log failed: {e}")

        logger.info(f"[USERS] User invited: {body.username} by {user.user_id}")

        return UserResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{user_id}")
async def remove_user(
    user_id: str,
    user: AuthenticatedUser = Depends(require_permission(Permission.USER_REMOVE, "user")),
) -> dict:
    """
    Remove a user from the tenant.

    Requires USER_REMOVE permission (admin+).

    Args:
        user_id: UUID of user to remove

    Returns:
        {"status": "deleted"}

    Raises:
        404: User not found
        403: Permission denied
    """
    import asyncio

    # Prevent self-deletion
    if user_id == user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    try:
        target_uuid = UUID(user_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID") from err

    deleted = await asyncio.to_thread(
        _delete_user,
        UUID(user.tenant_id),
        target_uuid,
    )

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Audit log
    try:
        from core.observability.audit import AuditAction, AuditLogger

        await AuditLogger.log(
            tenant_id=UUID(user.tenant_id),
            user_id=UUID(user.user_id),
            action=AuditAction.USER_DELETE,
            resource_type="user",
            resource_id=user_id,
        )
    except Exception as e:
        logger.warning(f"[USERS] Audit log failed: {e}")

    logger.info(f"[USERS] User removed: {user_id} by {user.user_id}")

    return {"status": "deleted", "user_id": user_id}


@router.patch("/{user_id}/role")
async def change_role(
    user_id: str,
    body: ChangeRoleRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.USER_CHANGE_ROLE, "user")),
) -> dict:
    """
    Change a user's role.

    Requires USER_CHANGE_ROLE permission (owner only).

    Args:
        user_id: UUID of user to update
        body: ChangeRoleRequest with new role

    Returns:
        Updated user info

    Raises:
        404: User not found
        400: Invalid role
        403: Permission denied
    """
    import asyncio

    try:
        target_uuid = UUID(user_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID") from err

    try:
        result = await asyncio.to_thread(
            _change_role,
            UUID(user.tenant_id),
            target_uuid,
            body.role,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Audit log
    try:
        from core.observability.audit import AuditAction, AuditLogger

        await AuditLogger.log(
            tenant_id=UUID(user.tenant_id),
            user_id=UUID(user.user_id),
            action=AuditAction.USER_ROLE_CHANGE,
            resource_type="user",
            resource_id=user_id,
            details={"new_role": body.role},
        )
    except Exception as e:
        logger.warning(f"[USERS] Audit log failed: {e}")

    logger.info(f"[USERS] Role changed: {user_id} -> {body.role} by {user.user_id}")

    return {"status": "updated", **result}
