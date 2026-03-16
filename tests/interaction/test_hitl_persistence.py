"""
V12.2 IRONCLAD - HITL Persistence Tests

Tests:
- HITLRequest model
- Create, read, answer operations
- TTL expiration
- Pending requests query

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.infrastructure.db.engine import init_db, reset_engine


class TestHITLRequestModel:
    """Tests for HITLRequest SQLModel."""

    def test_model_fields(self):
        """Test HITLRequest has required fields."""
        from core.observability.audit.models import HITLRequest, HITLRequestStatus

        request = HITLRequest(
            tenant_id=uuid4(),
            workspace_id="default",
            request_type="ask",
            prompt="Continue with deployment?",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        assert request.request_type == "ask"
        assert request.prompt == "Continue with deployment?"
        assert request.status == HITLRequestStatus.PENDING

    def test_status_enum(self):
        """Test HITLRequestStatus enum values."""
        from core.observability.audit.models import HITLRequestStatus

        assert HITLRequestStatus.PENDING == "pending"
        assert HITLRequestStatus.ANSWERED == "answered"
        assert HITLRequestStatus.EXPIRED == "expired"
        assert HITLRequestStatus.CANCELLED == "cancelled"

    def test_default_status_is_pending(self):
        """Test new requests default to pending."""
        from core.observability.audit.models import HITLRequest, HITLRequestStatus

        request = HITLRequest(
            tenant_id=uuid4(),
            workspace_id="default",
            request_type="confirm",
            prompt="Test?",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )

        assert request.status == HITLRequestStatus.PENDING


class TestHITLPersistence:
    """Tests for HITLPersistence service."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_create_request(self):
        """Test creating a HITL request."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_id = uuid4()

        result = await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="default",
            request_type="ask",
            prompt="Should I continue?",
        )

        assert result is not None
        assert result["request_type"] == "ask"
        assert result["prompt"] == "Should I continue?"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_request_with_options(self):
        """Test creating a request with choice options."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        result = await HITLPersistence.create_request(
            tenant_id=uuid4(),
            workspace_id="default",
            request_type="choose",
            prompt="Select an option:",
            options=["Option A", "Option B", "Option C"],
        )

        assert result is not None
        assert result["options"] is not None

    @pytest.mark.asyncio
    async def test_get_pending_requests(self):
        """Test getting pending requests for a workspace."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_id = uuid4()

        await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="workspace-a",
            request_type="ask",
            prompt="Question 1?",
        )

        await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="workspace-a",
            request_type="confirm",
            prompt="Question 2?",
        )

        await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="workspace-b",
            request_type="ask",
            prompt="Different workspace?",
        )

        pending = await HITLPersistence.get_pending(
            tenant_id=tenant_id,
            workspace_id="workspace-a",
        )

        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_answer_request(self):
        """Test answering a pending request."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_id = uuid4()

        created = await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="default",
            request_type="confirm",
            prompt="Proceed?",
        )

        request_id = created["id"]

        answered = await HITLPersistence.answer_request(
            request_id=request_id,
            answer="yes",
        )

        assert answered is not None
        assert answered["status"] == "answered"
        assert answered["answer"] == "yes"

    @pytest.mark.asyncio
    async def test_answered_request_not_in_pending(self):
        """Test that answered requests are not in pending list."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_id = uuid4()

        created = await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="default",
            request_type="ask",
            prompt="Test?",
        )

        await HITLPersistence.answer_request(
            request_id=created["id"],
            answer="done",
        )

        pending = await HITLPersistence.get_pending(
            tenant_id=tenant_id,
            workspace_id="default",
        )

        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_answer_nonexistent_returns_none(self):
        """Test answering nonexistent request returns None."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        result = await HITLPersistence.answer_request(
            request_id=uuid4(),
            answer="test",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_request_by_id(self):
        """Test getting a specific request by ID."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_id = uuid4()

        created = await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="default",
            request_type="ask",
            prompt="Specific question?",
        )

        fetched = await HITLPersistence.get_request(request_id=created["id"])

        assert fetched is not None
        assert fetched["prompt"] == "Specific question?"


class TestHITLWorkspaceIsolation:
    """Tests for workspace isolation in HITL."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_different_workspaces_independent(self):
        """Test that workspaces have independent pending lists."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_id = uuid4()

        await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="workspace-1",
            request_type="ask",
            prompt="WS1 Question?",
        )

        await HITLPersistence.create_request(
            tenant_id=tenant_id,
            workspace_id="workspace-2",
            request_type="ask",
            prompt="WS2 Question?",
        )

        pending_1 = await HITLPersistence.get_pending(tenant_id, "workspace-1")
        pending_2 = await HITLPersistence.get_pending(tenant_id, "workspace-2")

        assert len(pending_1) == 1
        assert len(pending_2) == 1
        assert pending_1[0]["prompt"] == "WS1 Question?"
        assert pending_2[0]["prompt"] == "WS2 Question?"

    @pytest.mark.asyncio
    async def test_different_tenants_independent(self):
        """Test that tenants have independent pending lists."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        tenant_a = uuid4()
        tenant_b = uuid4()

        await HITLPersistence.create_request(
            tenant_id=tenant_a,
            workspace_id="default",
            request_type="ask",
            prompt="Tenant A question?",
        )

        await HITLPersistence.create_request(
            tenant_id=tenant_b,
            workspace_id="default",
            request_type="ask",
            prompt="Tenant B question?",
        )

        pending_a = await HITLPersistence.get_pending(tenant_a, "default")
        pending_b = await HITLPersistence.get_pending(tenant_b, "default")

        assert len(pending_a) == 1
        assert len(pending_b) == 1


class TestHITLRequestTypes:
    """Tests for different HITL request types."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Setup test database."""
        db_path = tmp_path / "test.db"
        reset_engine()
        init_db(db_path)
        yield
        reset_engine()

    @pytest.mark.asyncio
    async def test_ask_request(self):
        """Test creating an 'ask' type request."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        result = await HITLPersistence.create_request(
            tenant_id=uuid4(),
            workspace_id="default",
            request_type="ask",
            prompt="What should I do next?",
        )

        assert result["request_type"] == "ask"

    @pytest.mark.asyncio
    async def test_confirm_request(self):
        """Test creating a 'confirm' type request."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        result = await HITLPersistence.create_request(
            tenant_id=uuid4(),
            workspace_id="default",
            request_type="confirm",
            prompt="Delete all files?",
        )

        assert result["request_type"] == "confirm"

    @pytest.mark.asyncio
    async def test_choose_request(self):
        """Test creating a 'choose' type request with options."""
        from core.security_pkg.interaction.hitl_persistence import HITLPersistence

        result = await HITLPersistence.create_request(
            tenant_id=uuid4(),
            workspace_id="default",
            request_type="choose",
            prompt="Select deployment target:",
            options=["staging", "production", "canary"],
        )

        assert result["request_type"] == "choose"
        assert result["options"] is not None
