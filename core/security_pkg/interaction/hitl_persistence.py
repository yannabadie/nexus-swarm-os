"""
NEXUS V12.2 IRONCLAD - HITL Persistence Service

Persists Human-in-the-Loop requests to database for:
- Server restart survival
- WebSocket disconnect recovery
- Async handling (mobile notifications, email, etc.)

The HITLRequest model is defined in core/audit/models.py.

Usage:
    from core.security_pkg.interaction.hitl_persistence import HITLPersistence

    # Create a request
    request = await HITLPersistence.create_request(
        tenant_id=user.tenant_id,
        workspace_id="default",
        request_type="confirm",
        prompt="Delete all files?",
    )

    # Answer a request
    await HITLPersistence.answer_request(request.id, "yes")

    # Get pending requests
    pending = await HITLPersistence.get_pending(tenant_id, workspace_id)

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlmodel import select

logger = logging.getLogger(__name__)


# =============================================================================
# Sync DB Operations (run in thread pool)
# =============================================================================


def _insert_hitl_request(
    tenant_id: UUID,
    workspace_id: str,
    request_type: str,
    prompt: str,
    options: list | None = None,
    context_data: dict | None = None,
    ttl_hours: int = 24,
) -> dict:
    """
    Insert a new HITL request.

    Called from thread pool via asyncio.to_thread().
    """
    from core.infrastructure.db import get_session
    from core.observability.audit.models import HITLRequest

    request = HITLRequest(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        request_type=request_type,
        prompt=prompt,
        options=json.dumps(options) if options else None,
        context_data=json.dumps(context_data) if context_data else None,
        expires_at=(datetime.now(UTC) + timedelta(hours=ttl_hours)).replace(tzinfo=None),
    )

    with get_session() as session:
        session.add(request)
        session.commit()
        session.refresh(request)

        return {
            "id": request.id,
            "tenant_id": request.tenant_id,
            "workspace_id": request.workspace_id,
            "request_type": request.request_type,
            "prompt": request.prompt,
            "options": json.loads(request.options) if request.options else None,
            "status": request.status,
            "created_at": request.created_at,
            "expires_at": request.expires_at,
        }


def _get_pending_requests(tenant_id: UUID, workspace_id: str | None = None) -> list[dict]:
    """
    Get all pending requests for a tenant/workspace.

    Called from thread pool via asyncio.to_thread().
    """
    from core.infrastructure.db import get_session
    from core.observability.audit.models import HITLRequest, HITLRequestStatus

    with get_session() as session:
        statement = select(HITLRequest).where(
            HITLRequest.tenant_id == tenant_id,
            HITLRequest.status == HITLRequestStatus.PENDING.value,
            HITLRequest.expires_at > datetime.now(UTC).replace(tzinfo=None),
        )

        if workspace_id:
            statement = statement.where(HITLRequest.workspace_id == workspace_id)

        statement = statement.order_by(HITLRequest.created_at.desc())

        results = []
        for req in session.exec(statement).all():
            results.append(
                {
                    "id": req.id,
                    "request_id": str(req.id),  # Alias for frontend compatibility
                    "tenant_id": req.tenant_id,
                    "workspace_id": req.workspace_id,
                    "request_type": req.request_type,
                    "prompt": req.prompt,
                    "options": json.loads(req.options) if req.options else None,
                    "status": req.status,
                    "created_at": req.created_at,
                    "expires_at": req.expires_at,
                }
            )

        return results


def _answer_request(request_id: UUID, answer: str) -> dict | None:
    """
    Answer a pending request.

    Called from thread pool via asyncio.to_thread().
    """
    from core.infrastructure.db import get_session
    from core.observability.audit.models import HITLRequest, HITLRequestStatus

    with get_session() as session:
        statement = select(HITLRequest).where(HITLRequest.id == request_id)
        request = session.exec(statement).first()

        if not request:
            return None

        if request.status != HITLRequestStatus.PENDING.value:
            return None  # Already answered or expired

        request.status = HITLRequestStatus.ANSWERED.value
        request.answer = answer
        request.answered_at = datetime.now(UTC).replace(tzinfo=None)

        session.add(request)
        session.commit()
        session.refresh(request)

        return {
            "id": request.id,
            "request_type": request.request_type,
            "prompt": request.prompt,
            "answer": request.answer,
            "status": request.status,
            "answered_at": request.answered_at,
            "context_data": json.loads(request.context_data) if request.context_data else None,
        }


def _cancel_request(request_id: UUID) -> bool:
    """
    Cancel a pending request.

    Called from thread pool via asyncio.to_thread().
    """
    from core.infrastructure.db import get_session
    from core.observability.audit.models import HITLRequest, HITLRequestStatus

    with get_session() as session:
        statement = select(HITLRequest).where(HITLRequest.id == request_id)
        request = session.exec(statement).first()

        if not request:
            return False

        if request.status != HITLRequestStatus.PENDING.value:
            return False

        request.status = HITLRequestStatus.CANCELLED.value
        session.add(request)
        session.commit()

        return True


def _cleanup_expired() -> int:
    """
    Mark expired requests.

    Called from thread pool via asyncio.to_thread().
    """
    from sqlalchemy import update

    from core.infrastructure.db import get_engine
    from core.observability.audit.models import HITLRequest, HITLRequestStatus

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            update(HITLRequest)
            .where(
                HITLRequest.status == HITLRequestStatus.PENDING.value,
                HITLRequest.expires_at < datetime.now(UTC).replace(tzinfo=None),
            )
            .values(status=HITLRequestStatus.EXPIRED.value)
        )
        conn.commit()
        return result.rowcount


def _get_request_by_id(request_id: UUID) -> dict | None:
    """
    Get a single request by ID.

    Called from thread pool via asyncio.to_thread().
    """
    from core.infrastructure.db import get_session
    from core.observability.audit.models import HITLRequest

    with get_session() as session:
        statement = select(HITLRequest).where(HITLRequest.id == request_id)
        request = session.exec(statement).first()

        if not request:
            return None

        return {
            "id": request.id,
            "request_id": str(request.id),
            "tenant_id": request.tenant_id,
            "workspace_id": request.workspace_id,
            "request_type": request.request_type,
            "prompt": request.prompt,
            "options": json.loads(request.options) if request.options else None,
            "status": request.status,
            "answer": request.answer,
            "context_data": json.loads(request.context_data) if request.context_data else None,
            "created_at": request.created_at,
            "answered_at": request.answered_at,
            "expires_at": request.expires_at,
        }


# =============================================================================
# Async HITL Persistence Service
# =============================================================================


class HITLPersistence:
    """
    HITL Persistence Service for async database operations.

    All methods are static for easy access without instantiation.
    """

    DEFAULT_TTL_HOURS = 24

    @staticmethod
    async def create_request(
        tenant_id: UUID,
        workspace_id: str,
        request_type: str,
        prompt: str,
        options: list | None = None,
        context_data: dict | None = None,
        ttl_hours: int = 24,
    ) -> dict:
        """
        Create a new HITL request.

        Args:
            tenant_id: Tenant UUID
            workspace_id: Workspace identifier
            request_type: "ask", "confirm", or "choose"
            prompt: Question to show user
            options: List of choices (for "choose" type)
            context_data: Workflow context for resuming
            ttl_hours: Time to live in hours (default 24)

        Returns:
            Dict with created request info
        """
        result = await asyncio.to_thread(
            _insert_hitl_request,
            tenant_id,
            workspace_id,
            request_type,
            prompt,
            options,
            context_data,
            ttl_hours,
        )

        logger.info(f"[HITL] Created request: {result['id']} type={request_type}")
        return result

    @staticmethod
    async def get_pending(
        tenant_id: UUID,
        workspace_id: str | None = None,
    ) -> list[dict]:
        """
        Get all pending requests for a tenant/workspace.

        Args:
            tenant_id: Tenant UUID
            workspace_id: Optional workspace filter

        Returns:
            List of pending request dicts
        """
        return await asyncio.to_thread(_get_pending_requests, tenant_id, workspace_id)

    @staticmethod
    async def answer_request(
        request_id: UUID,
        answer: str,
    ) -> dict | None:
        """
        Answer a pending request.

        Args:
            request_id: Request UUID
            answer: User's answer

        Returns:
            Updated request dict, or None if not found/already answered
        """
        result = await asyncio.to_thread(_answer_request, request_id, answer)

        if result:
            logger.info(f"[HITL] Answered request: {request_id}")
        else:
            logger.warning(f"[HITL] Could not answer request: {request_id}")

        return result

    @staticmethod
    async def cancel_request(request_id: UUID) -> bool:
        """
        Cancel a pending request.

        Args:
            request_id: Request UUID

        Returns:
            True if cancelled, False if not found/already answered
        """
        result = await asyncio.to_thread(_cancel_request, request_id)

        if result:
            logger.info(f"[HITL] Cancelled request: {request_id}")

        return result

    @staticmethod
    async def get_request(request_id: UUID) -> dict | None:
        """
        Get a single request by ID.

        Args:
            request_id: Request UUID

        Returns:
            Request dict or None if not found
        """
        return await asyncio.to_thread(_get_request_by_id, request_id)

    @staticmethod
    async def cleanup_expired() -> int:
        """
        Mark expired requests as expired.

        Should be called periodically (e.g., every hour).

        Returns:
            Number of requests marked as expired
        """
        count = await asyncio.to_thread(_cleanup_expired)
        if count > 0:
            logger.info(f"[HITL] Cleaned up {count} expired requests")
        return count
