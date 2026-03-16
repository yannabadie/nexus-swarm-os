"""
V12.2 IRONCLAD - Audit Logger Tests

Tests:
- Append-only behavior (no UPDATE/DELETE)
- Async-safe operations
- Required fields validation
- Query functions

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.infrastructure.db.engine import init_db, reset_engine


class TestAuditLoggerUnit:
    """Unit tests for AuditLogger (no async)."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    def test_audit_log_model_fields(self):
        """Test AuditLog model has required fields."""
        from core.observability.audit.models import AuditLog

        log = AuditLog(
            tenant_id=uuid4(),
            user_id=uuid4(),
            action="file:read",
            resource_type="file",
            resource_id="/test/file.txt",
            status="success",
        )

        assert log.action == "file:read"
        assert log.resource_type == "file"
        assert log.status == "success"
        assert log.timestamp is not None

    def test_audit_log_defaults(self):
        """Test AuditLog default values."""
        from core.observability.audit.models import AuditLog

        log = AuditLog(
            tenant_id=uuid4(),
            user_id=uuid4(),
            action="test",
            resource_type="test",
        )

        assert log.status == "success"
        assert log.timestamp is not None
        assert log.details is None

    def test_audit_action_enum(self):
        """Test AuditAction enum values."""
        from core.observability.audit.models import AuditAction

        assert AuditAction.FILE_READ == "file:read"
        assert AuditAction.FILE_WRITE == "file:write"
        assert AuditAction.AUTH_LOGIN == "auth:login"
        assert AuditAction.AUTH_LOGOUT == "auth:logout"
        assert AuditAction.PERMISSION_DENIED == "permission:denied"


class TestAuditLoggerAsync:
    """Async tests for AuditLogger."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_log_creates_entry(self):
        """Test AuditLogger.log creates a database entry."""
        from core.observability.audit import AuditAction, AuditLogger

        tenant_id = uuid4()
        user_id = uuid4()

        result = await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=AuditAction.FILE_READ,
            resource_type="file",
            resource_id="/test.txt",
        )

        assert result is not None
        assert result["action"] == "file:read"
        assert result["resource_type"] == "file"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_log_with_details(self):
        """Test AuditLogger.log with additional details."""
        from core.observability.audit import AuditAction, AuditLogger

        result = await AuditLogger.log(
            tenant_id=uuid4(),
            user_id=uuid4(),
            action=AuditAction.FILE_WRITE,
            resource_type="file",
            resource_id="/new.txt",
            details={"bytes_written": 1024},
        )

        assert result is not None
        assert result["action"] == "file:write"
        assert result["resource_id"] == "/new.txt"

    @pytest.mark.asyncio
    async def test_log_permission_denied(self):
        """Test logging permission denied events."""
        from core.observability.audit import AuditAction, AuditLogger

        result = await AuditLogger.log(
            tenant_id=uuid4(),
            user_id=uuid4(),
            action=AuditAction.PERMISSION_DENIED,
            resource_type="file",
            resource_id="/secret.txt",
            status="denied",
            details={"required_permission": "file:write"},
        )

        assert result is not None
        assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_concurrent_logging(self):
        """Test multiple concurrent log operations."""
        from core.observability.audit import AuditAction, AuditLogger

        tenant_id = uuid4()
        user_id = uuid4()

        async def log_one(i: int):
            return await AuditLogger.log(
                tenant_id=tenant_id,
                user_id=user_id,
                action=AuditAction.FILE_READ,
                resource_type="file",
                resource_id=f"/file_{i}.txt",
            )

        results = await asyncio.gather(*[log_one(i) for i in range(10)])

        assert len(results) == 10
        assert all(r is not None for r in results)


class TestAuditLoggerQueries:
    """Tests for audit log query functions."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_query_logs_for_tenant(self):
        """Test querying logs by tenant."""
        from core.observability.audit import AuditAction, AuditLogger

        tenant_id = uuid4()
        other_tenant = uuid4()

        await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=uuid4(),
            action=AuditAction.FILE_READ,
            resource_type="file",
        )

        await AuditLogger.log(
            tenant_id=other_tenant,
            user_id=uuid4(),
            action=AuditAction.FILE_READ,
            resource_type="file",
        )

        logs = await AuditLogger.query(tenant_id=tenant_id, limit=100)

        assert len(logs) == 1
        assert logs[0]["tenant_id"] == tenant_id

    @pytest.mark.asyncio
    async def test_query_logs_with_action_filter(self):
        """Test filtering logs by action type."""
        from core.observability.audit import AuditAction, AuditLogger

        tenant_id = uuid4()
        user_id = uuid4()

        await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=AuditAction.FILE_READ,
            resource_type="file",
        )

        await AuditLogger.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=AuditAction.FILE_WRITE,
            resource_type="file",
        )

        logs = await AuditLogger.query(
            tenant_id=tenant_id,
            action=AuditAction.FILE_READ,
            limit=100,
        )

        assert len(logs) == 1
        assert logs[0]["action"] == "file:read"


class TestAuditLogImmutability:
    """Tests verifying audit logs are append-only (immutable)."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_no_update_method(self):
        """Verify AuditLogger has no update method."""
        from core.observability.audit import AuditLogger

        assert not hasattr(AuditLogger, "update")
        assert not hasattr(AuditLogger, "update_log")
        assert not hasattr(AuditLogger, "modify")

    @pytest.mark.asyncio
    async def test_no_delete_method(self):
        """Verify AuditLogger has no delete method."""
        from core.observability.audit import AuditLogger

        assert not hasattr(AuditLogger, "delete")
        assert not hasattr(AuditLogger, "delete_log")
        assert not hasattr(AuditLogger, "remove")
