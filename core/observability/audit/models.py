"""
NEXUS V12.2 IRONCLAD - Audit Models

Defines SQLModel tables for:
- AuditLog: Immutable audit trail for compliance
- HITLRequest: Human-in-the-Loop persistence

Design Principles:
- Append-only: No UPDATE/DELETE operations on AuditLog
- Indexed: Fast queries by tenant_id, user_id, action, timestamp
- Immutable: SQLModel frozen config prevents modifications

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

# =============================================================================
# Enums
# =============================================================================


class AuditAction(str, Enum):
    """Audit action categories."""

    # Authentication
    AUTH_LOGIN = "auth:login"
    AUTH_LOGOUT = "auth:logout"
    AUTH_REFRESH = "auth:refresh"
    AUTH_FAILED = "auth:failed"

    # Files
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"

    # Workflow
    WORKFLOW_START = "workflow:start"
    WORKFLOW_STOP = "workflow:stop"
    WORKFLOW_COMPLETE = "workflow:complete"

    # Users
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_ROLE_CHANGE = "user:role_change"

    # Permissions
    PERMISSION_DENIED = "permission:denied"
    PERMISSION_GRANTED = "permission:granted"

    # System
    SYSTEM_ERROR = "system:error"
    SYSTEM_CONFIG = "system:config"


class AuditStatus(str, Enum):
    """Audit event status."""

    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


class HITLRequestStatus(str, Enum):
    """Human-in-the-Loop request status."""

    PENDING = "pending"
    ANSWERED = "answered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class HITLRequestType(str, Enum):
    """Human-in-the-Loop request types."""

    ASK = "ask"  # Free-form question
    CONFIRM = "confirm"  # Yes/No confirmation
    CHOOSE = "choose"  # Multiple choice


# =============================================================================
# AuditLog Model
# =============================================================================


class AuditLog(SQLModel, table=True):
    """
    Immutable audit trail for compliance.

    Design: Append-only (no UPDATE/DELETE operations)

    All sensitive operations should create an AuditLog entry:
    - Authentication events
    - File access
    - Workflow execution
    - User management
    - Permission checks

    Example:
        await AuditLogger.log(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action=AuditAction.FILE_READ,
            resource_type="file",
            resource_id="/path/to/file.py",
            status=AuditStatus.SUCCESS,
        )
    """

    __tablename__ = "audit_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    user_id: UUID = Field(index=True)

    # Action details
    action: str = Field(index=True)  # e.g., "file:read", "user:login"
    resource_type: str  # e.g., "file", "user", "workflow"
    resource_id: str | None = Field(default=None, max_length=500)  # e.g., file path, user UUID

    # Result
    status: str = Field(default="success")  # "success", "denied", "error"
    details: str | None = Field(default=None, max_length=2000)  # JSON string for additional context

    # Request metadata
    ip_address: str | None = Field(default=None, max_length=45)  # IPv6 max length
    user_agent: str | None = Field(default=None, max_length=500)

    # Timestamp
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None), index=True)

    def __repr__(self) -> str:
        return f"AuditLog({self.action}, user={self.user_id}, status={self.status})"


# =============================================================================
# HITLRequest Model
# =============================================================================


class HITLRequest(SQLModel, table=True):
    """
    Human-in-the-Loop request for async handling.

    Persists HITL requests to database so they survive:
    - Server restarts
    - WebSocket disconnects
    - Browser refreshes

    Requests have a TTL (default 24h) after which they expire.

    Example:
        request = await HITLPersistence.create_request(
            tenant_id=user.tenant_id,
            workspace_id="default",
            request_type=HITLRequestType.CONFIRM,
            prompt="Delete all files?",
        )
    """

    __tablename__ = "hitl_requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    workspace_id: str = Field(index=True, max_length=100)

    # Request details
    request_type: str  # "ask", "confirm", "choose"
    prompt: str = Field(max_length=2000)
    options: str | None = Field(default=None, max_length=2000)  # JSON array for choices

    # Context (for resuming workflow)
    context_data: str | None = Field(default=None, max_length=10000)  # JSON workflow context

    # State
    status: str = Field(default="pending", index=True)  # pending, answered, expired, cancelled
    answer: str | None = Field(default=None, max_length=2000)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    answered_at: datetime | None = Field(default=None)
    expires_at: datetime = Field(default_factory=lambda: (datetime.now(UTC) + timedelta(hours=24)).replace(tzinfo=None))

    def is_expired(self) -> bool:
        """Check if request has expired."""
        return datetime.now(UTC).replace(tzinfo=None) > self.expires_at

    def is_pending(self) -> bool:
        """Check if request is still pending."""
        return self.status == HITLRequestStatus.PENDING.value and not self.is_expired()

    def __repr__(self) -> str:
        return f"HITLRequest({self.request_type}, status={self.status})"
