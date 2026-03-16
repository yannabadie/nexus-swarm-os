"""
NEXUS V12.2 IRONCLAD - Audit Logger

Append-only audit logger with async support.

Design:
- Thread-safe: Uses asyncio.to_thread() for DB operations
- Append-only: Only INSERT operations, never UPDATE/DELETE
- Fast: Non-blocking async interface
- Reliable: Catches and logs errors, never fails requests

Usage:
    from core.observability.audit import AuditLogger, AuditAction, AuditStatus

    # In an async route handler
    await AuditLogger.log(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action=AuditAction.FILE_READ,
        resource_type="file",
        resource_id="/path/to/file.py",
        status=AuditStatus.SUCCESS,
        request=request,  # Optional: extracts IP and user-agent
    )

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlmodel import select

from .models import AuditAction, AuditLog, AuditStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Sync DB Operations (run in thread pool)
# =============================================================================


def _insert_audit_log(entry: AuditLog) -> dict:
    """
    Sync insert of audit log entry.

    Called from thread pool via asyncio.to_thread().
    Returns dict to avoid detached session issues.
    """
    from core.infrastructure.db import get_session

    with get_session() as session:
        session.add(entry)
        session.commit()
        session.refresh(entry)
        # Return dict to avoid detachment
        return {
            "id": entry.id,
            "tenant_id": entry.tenant_id,
            "user_id": entry.user_id,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "status": entry.status,
            "timestamp": entry.timestamp,
        }


def _query_audit_logs(
    tenant_id: UUID,
    filters: dict,
    limit: int,
    offset: int,
) -> list[dict]:
    """
    Sync query of audit logs with filters.

    Called from thread pool via asyncio.to_thread().
    Returns dicts to avoid detached session issues.
    """
    from core.infrastructure.db import get_session

    with get_session() as session:
        statement = select(AuditLog).where(AuditLog.tenant_id == tenant_id)

        if filters.get("user_id"):
            statement = statement.where(AuditLog.user_id == filters["user_id"])

        if filters.get("action"):
            statement = statement.where(AuditLog.action == filters["action"])

        if filters.get("status"):
            statement = statement.where(AuditLog.status == filters["status"])

        if filters.get("resource_type"):
            statement = statement.where(AuditLog.resource_type == filters["resource_type"])

        if filters.get("since"):
            statement = statement.where(AuditLog.timestamp >= filters["since"])

        if filters.get("until"):
            statement = statement.where(AuditLog.timestamp <= filters["until"])

        # Order by most recent first
        statement = statement.order_by(AuditLog.timestamp.desc())

        # Pagination
        statement = statement.offset(offset).limit(limit)

        # Convert to dicts to avoid detached session issues
        results = []
        for log in session.exec(statement).all():
            results.append(
                {
                    "id": log.id,
                    "tenant_id": log.tenant_id,
                    "user_id": log.user_id,
                    "action": log.action,
                    "resource_type": log.resource_type,
                    "resource_id": log.resource_id,
                    "status": log.status,
                    "details": log.details,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "timestamp": log.timestamp,
                }
            )
        return results


def _count_audit_logs(tenant_id: UUID, filters: dict) -> int:
    """
    Sync count of audit logs with filters.

    Called from thread pool via asyncio.to_thread().
    """
    from sqlalchemy import func

    from core.infrastructure.db import get_session

    with get_session() as session:
        statement = select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id)

        if filters.get("user_id"):
            statement = statement.where(AuditLog.user_id == filters["user_id"])

        if filters.get("action"):
            statement = statement.where(AuditLog.action == filters["action"])

        if filters.get("status"):
            statement = statement.where(AuditLog.status == filters["status"])

        return session.exec(statement).one()


def _cleanup_old_logs(retention_days: int) -> int:
    """
    Sync cleanup of logs older than retention period.

    Called from thread pool via asyncio.to_thread().
    """
    from sqlalchemy import delete

    from core.infrastructure.db import get_engine

    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).replace(tzinfo=None)

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(delete(AuditLog).where(AuditLog.timestamp < cutoff))
        conn.commit()
        return result.rowcount


# =============================================================================
# Async Audit Logger
# =============================================================================


class AuditLogger:
    """
    Append-only audit logger with async support.

    All methods are static for easy access without instantiation.
    """

    @staticmethod
    async def log(
        tenant_id: UUID,
        user_id: UUID,
        action: str | AuditAction,
        resource_type: str,
        resource_id: str | None = None,
        status: str | AuditStatus = AuditStatus.SUCCESS,
        details: dict | None = None,
        request: Any | None = None,  # FastAPI Request
    ) -> dict | None:
        """
        Log an audit event (append-only).

        Args:
            tenant_id: Tenant UUID
            user_id: User UUID who performed the action
            action: Action type (e.g., AuditAction.FILE_READ)
            resource_type: Type of resource (e.g., "file", "user")
            resource_id: Optional resource identifier
            status: Result status (success, denied, error)
            details: Optional dict with additional context
            request: Optional FastAPI Request for IP/user-agent

        Returns:
            Dict with created AuditLog entry info, or None on error
        """
        try:
            # Normalize enums to strings
            action_str = action.value if isinstance(action, AuditAction) else str(action)
            status_str = status.value if isinstance(status, AuditStatus) else str(status)

            # Extract request metadata
            ip_address = None
            user_agent = None
            if request:
                try:
                    ip_address = getattr(request.client, "host", None) if hasattr(request, "client") else None
                    user_agent = request.headers.get("user-agent") if hasattr(request, "headers") else None
                except Exception:
                    pass

            # Create entry
            entry = AuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action_str,
                resource_type=resource_type,
                resource_id=resource_id,
                status=status_str,
                details=json.dumps(details) if details else None,
                ip_address=ip_address,
                user_agent=user_agent[:500] if user_agent else None,
            )

            # Insert in thread pool (non-blocking)
            result = await asyncio.to_thread(_insert_audit_log, entry)
            logger.debug(f"[AUDIT] Logged: {action_str} on {resource_type}")
            return result

        except Exception as e:
            # Never fail the request due to audit logging
            logger.error(f"[AUDIT] Failed to log: {e}")
            return None

    @staticmethod
    async def log_auth(
        tenant_id: UUID,
        user_id: UUID,
        action: AuditAction,
        success: bool,
        request: Any | None = None,
        details: dict | None = None,
    ) -> dict | None:
        """
        Convenience method for authentication audit events.

        Args:
            tenant_id: Tenant UUID
            user_id: User UUID
            action: Auth action (AUTH_LOGIN, AUTH_LOGOUT, etc.)
            success: Whether auth succeeded
            request: Optional FastAPI Request
            details: Optional additional details
        """
        return await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type="auth",
            status=AuditStatus.SUCCESS if success else AuditStatus.DENIED,
            request=request,
            details=details,
        )

    @staticmethod
    async def log_file(
        tenant_id: UUID,
        user_id: UUID,
        action: AuditAction,
        file_path: str,
        success: bool,
        request: Any | None = None,
        details: dict | None = None,
    ) -> dict | None:
        """
        Convenience method for file audit events.

        Args:
            tenant_id: Tenant UUID
            user_id: User UUID
            action: File action (FILE_READ, FILE_WRITE, FILE_DELETE)
            file_path: Path to the file
            success: Whether operation succeeded
            request: Optional FastAPI Request
            details: Optional additional details
        """
        return await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type="file",
            resource_id=file_path,
            status=AuditStatus.SUCCESS if success else AuditStatus.ERROR,
            request=request,
            details=details,
        )

    @staticmethod
    async def log_permission_denied(
        tenant_id: UUID,
        user_id: UUID,
        permission: str,
        resource_type: str,
        resource_id: str | None = None,
        request: Any | None = None,
    ) -> dict | None:
        """
        Log a permission denial event.

        Args:
            tenant_id: Tenant UUID
            user_id: User UUID
            permission: Permission that was denied
            resource_type: Type of resource
            resource_id: Optional resource identifier
            request: Optional FastAPI Request
        """
        return await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=AuditAction.PERMISSION_DENIED,
            resource_type=resource_type,
            resource_id=resource_id,
            status=AuditStatus.DENIED,
            request=request,
            details={"permission": permission},
        )

    @staticmethod
    async def query(
        tenant_id: UUID,
        user_id: UUID | None = None,
        action: str | AuditAction | None = None,
        status: str | AuditStatus | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Query audit logs with filters.

        Args:
            tenant_id: Tenant UUID (required)
            user_id: Filter by user
            action: Filter by action type
            status: Filter by status
            resource_type: Filter by resource type
            since: Filter by timestamp >= since
            until: Filter by timestamp <= until
            limit: Max results (default 100)
            offset: Pagination offset

        Returns:
            List of dicts representing matching AuditLog entries
        """
        filters = {}

        if user_id:
            filters["user_id"] = user_id
        if action:
            filters["action"] = action.value if isinstance(action, AuditAction) else action
        if status:
            filters["status"] = status.value if isinstance(status, AuditStatus) else status
        if resource_type:
            filters["resource_type"] = resource_type
        if since:
            filters["since"] = since
        if until:
            filters["until"] = until

        return await asyncio.to_thread(_query_audit_logs, tenant_id, filters, limit, offset)

    @staticmethod
    async def count(
        tenant_id: UUID,
        user_id: UUID | None = None,
        action: str | AuditAction | None = None,
        status: str | AuditStatus | None = None,
    ) -> int:
        """
        Count audit logs matching filters.

        Args:
            tenant_id: Tenant UUID (required)
            user_id: Filter by user
            action: Filter by action type
            status: Filter by status

        Returns:
            Count of matching entries
        """
        filters = {}

        if user_id:
            filters["user_id"] = user_id
        if action:
            filters["action"] = action.value if isinstance(action, AuditAction) else action
        if status:
            filters["status"] = status.value if isinstance(status, AuditStatus) else status

        return await asyncio.to_thread(_count_audit_logs, tenant_id, filters)

    @staticmethod
    async def cleanup(retention_days: int = 90) -> int:
        """
        Remove audit logs older than retention period.

        Default: 90 days retention.

        Args:
            retention_days: Number of days to keep

        Returns:
            Count of deleted entries
        """
        try:
            count = await asyncio.to_thread(_cleanup_old_logs, retention_days)
            logger.info(f"[AUDIT] Cleaned up {count} logs older than {retention_days} days")
            return count
        except Exception as e:
            logger.error(f"[AUDIT] Cleanup failed: {e}")
            return 0
