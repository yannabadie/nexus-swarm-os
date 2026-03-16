"""
NEXUS V12.2 IRONCLAD - Audit Module

Provides append-only audit logging for compliance and security.

Quick Start:
    from core.observability.audit import AuditLogger, AuditAction, AuditStatus

    # Log a file read
    await AuditLogger.log_file(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action=AuditAction.FILE_READ,
        file_path="/path/to/file.py",
        success=True,
        request=request,
    )

    # Query recent denials
    denials = await AuditLogger.query(
        tenant_id=user.tenant_id,
        status=AuditStatus.DENIED,
        limit=50,
    )

Components:
    - AuditLog: SQLModel for audit entries (append-only)
    - HITLRequest: SQLModel for Human-in-the-Loop persistence
    - AuditLogger: Async-safe logging interface

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

from .audit_logger import AuditLogger
from .models import (
    AuditAction,
    # Audit
    AuditLog,
    AuditStatus,
    # HITL
    HITLRequest,
    HITLRequestStatus,
    HITLRequestType,
)

__all__ = [
    # Audit
    "AuditLog",
    "AuditAction",
    "AuditStatus",
    "AuditLogger",
    # HITL
    "HITLRequest",
    "HITLRequestStatus",
    "HITLRequestType",
]
