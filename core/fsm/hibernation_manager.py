"""
NEXUS V12.3 SCALE-OUT - Hibernation Manager

Manages FSM state persistence during HIBERNATE state.

When WebSocket disconnects during an active workflow:
1. Save current state to database (+ Redis if enabled)
2. Transition to HIBERNATE
3. On reconnect, restore state and resume

Storage:
- SQLite: Primary storage (always used)
- Redis: Optional cache for multi-instance (opt-in via USE_REDIS_HIBERNATION)

V12.3: Added Redis cache layer for multi-instance deployments.

Author: Claude (NEXUS V12.2 IRONCLAD, V12.3 SCALE-OUT)
Date: 2025-12-16
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel, select

logger = logging.getLogger(__name__)


# =============================================================================
# V12.3 SCALE-OUT: Redis Cache Layer (Optional)
# =============================================================================


class RedisHibernationCache:
    """
    Optional Redis cache for hibernation state.

    Provides fast lookups across multiple instances.
    SQLite remains authoritative - Redis is cache only.

    Key Schema:
        hibernation:{tenant_id}:{workspace_id} -> JSON state
    """

    KEY_PREFIX = "hibernation"
    DEFAULT_TTL = 86400  # 24 hours

    _instance: Optional["RedisHibernationCache"] = None
    _redis: Any | None = None
    _enabled: bool = False

    @classmethod
    async def get_instance(cls) -> "RedisHibernationCache":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance._init()
        return cls._instance

    async def _init(self) -> None:
        """Initialize Redis connection if configured."""
        try:
            from core.config import Config

            config = Config()

            if not getattr(config, "use_redis_hibernation", False):
                logger.debug("[HIBERNATE] Redis cache disabled (USE_REDIS_HIBERNATION=false)")
                return

            redis_url = getattr(config, "redis_url", "redis://localhost:6379")

            import redis.asyncio as redis_async

            self._redis = redis_async.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            self._enabled = True
            logger.info(f"[HIBERNATE] Redis cache enabled at {redis_url}")

        except ImportError:
            logger.debug("[HIBERNATE] redis package not installed, cache disabled")
        except Exception as e:
            logger.warning(f"[HIBERNATE] Redis connection failed: {e}, cache disabled")

    def _key(self, tenant_id: UUID, workspace_id: str) -> str:
        """Generate Redis key."""
        return f"{self.KEY_PREFIX}:{tenant_id}:{workspace_id}"

    async def set(
        self,
        tenant_id: UUID,
        workspace_id: str,
        state: dict,
        ttl_hours: int = 24,
    ) -> bool:
        """Cache hibernation state in Redis."""
        if not self._enabled or not self._redis:
            return False

        try:
            key = self._key(tenant_id, workspace_id)
            # Convert UUID to string for JSON serialization
            state_copy = dict(state)
            if "tenant_id" in state_copy and isinstance(state_copy["tenant_id"], UUID):
                state_copy["tenant_id"] = str(state_copy["tenant_id"])
            if "id" in state_copy and isinstance(state_copy["id"], UUID):
                state_copy["id"] = str(state_copy["id"])

            await self._redis.setex(
                key,
                ttl_hours * 3600,
                json.dumps(state_copy, default=str),
            )
            logger.debug(f"[HIBERNATE] Cached in Redis: {key}")
            return True
        except Exception as e:
            logger.warning(f"[HIBERNATE] Redis cache set failed: {e}")
            return False

    async def get(
        self,
        tenant_id: UUID,
        workspace_id: str,
    ) -> dict | None:
        """Get hibernation state from Redis cache."""
        if not self._enabled or not self._redis:
            return None

        try:
            key = self._key(tenant_id, workspace_id)
            data = await self._redis.get(key)
            if data:
                logger.debug(f"[HIBERNATE] Cache hit: {key}")
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"[HIBERNATE] Redis cache get failed: {e}")
            return None

    async def delete(
        self,
        tenant_id: UUID,
        workspace_id: str,
    ) -> bool:
        """Delete hibernation state from Redis cache."""
        if not self._enabled or not self._redis:
            return False

        try:
            key = self._key(tenant_id, workspace_id)
            await self._redis.delete(key)
            logger.debug(f"[HIBERNATE] Cache deleted: {key}")
            return True
        except Exception as e:
            logger.warning(f"[HIBERNATE] Redis cache delete failed: {e}")
            return False


# =============================================================================
# Hibernation State Model
# =============================================================================


class HibernationState(SQLModel, table=True):
    """
    Persisted FSM state for HIBERNATE recovery.

    Stores:
    - Previous FSM state
    - Workflow context
    - Expiration time
    """

    __tablename__ = "hibernation_states"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    workspace_id: str = Field(index=True, max_length=100)

    # FSM State
    previous_state: str  # OrchestratorState name
    fsm_context: str | None = Field(default=None, max_length=50000)  # JSON

    # Agent context
    active_agent: str | None = None  # "gemini" or "claude"
    turn_count: int = 0
    message_history: str | None = Field(default=None, max_length=100000)  # JSON

    # Timestamps
    entered_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    expires_at: datetime = Field(default_factory=lambda: (datetime.now(UTC) + timedelta(hours=24)).replace(tzinfo=None))

    # Status
    is_active: bool = Field(default=True, index=True)

    def is_expired(self) -> bool:
        """Check if hibernation has expired."""
        return datetime.now(UTC).replace(tzinfo=None) > self.expires_at


# =============================================================================
# Sync DB Operations (run in thread pool)
# =============================================================================


def _save_hibernation(
    tenant_id: UUID,
    workspace_id: str,
    previous_state: str,
    fsm_context: dict | None = None,
    active_agent: str | None = None,
    turn_count: int = 0,
    message_history: list | None = None,
    ttl_hours: int = 24,
) -> dict:
    """Save hibernation state to database."""
    from core.infrastructure.db import get_session

    # Deactivate any existing hibernation for this tenant/workspace
    with get_session() as session:
        statement = select(HibernationState).where(
            HibernationState.tenant_id == tenant_id,
            HibernationState.workspace_id == workspace_id,
            HibernationState.is_active,
        )
        existing = session.exec(statement).first()
        if existing:
            existing.is_active = False
            session.add(existing)

        # Create new hibernation state
        state = HibernationState(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            previous_state=previous_state,
            fsm_context=json.dumps(fsm_context) if fsm_context else None,
            active_agent=active_agent,
            turn_count=turn_count,
            message_history=json.dumps(message_history) if message_history else None,
            expires_at=(datetime.now(UTC) + timedelta(hours=ttl_hours)).replace(tzinfo=None),
        )

        session.add(state)
        session.commit()
        session.refresh(state)

        return {
            "id": state.id,
            "tenant_id": state.tenant_id,
            "workspace_id": state.workspace_id,
            "previous_state": state.previous_state,
            "entered_at": state.entered_at,
            "expires_at": state.expires_at,
        }


def _get_active_hibernation(tenant_id: UUID, workspace_id: str) -> dict | None:
    """Get active hibernation state for tenant/workspace."""
    from core.infrastructure.db import get_session

    with get_session() as session:
        statement = select(HibernationState).where(
            HibernationState.tenant_id == tenant_id,
            HibernationState.workspace_id == workspace_id,
            HibernationState.is_active,
            HibernationState.expires_at > datetime.now(UTC).replace(tzinfo=None),
        )
        state = session.exec(statement).first()

        if not state:
            return None

        return {
            "id": state.id,
            "tenant_id": state.tenant_id,
            "workspace_id": state.workspace_id,
            "previous_state": state.previous_state,
            "fsm_context": json.loads(state.fsm_context) if state.fsm_context else None,
            "active_agent": state.active_agent,
            "turn_count": state.turn_count,
            "message_history": json.loads(state.message_history) if state.message_history else None,
            "entered_at": state.entered_at,
            "expires_at": state.expires_at,
        }


def _exit_hibernation(tenant_id: UUID, workspace_id: str) -> dict | None:
    """Deactivate hibernation and return stored state."""
    from core.infrastructure.db import get_session

    with get_session() as session:
        statement = select(HibernationState).where(
            HibernationState.tenant_id == tenant_id,
            HibernationState.workspace_id == workspace_id,
            HibernationState.is_active,
        )
        state = session.exec(statement).first()

        if not state:
            return None

        # Check if expired
        if state.is_expired():
            state.is_active = False
            session.add(state)
            session.commit()
            return None

        # Deactivate and return
        state.is_active = False
        session.add(state)
        session.commit()

        return {
            "id": state.id,
            "previous_state": state.previous_state,
            "fsm_context": json.loads(state.fsm_context) if state.fsm_context else None,
            "active_agent": state.active_agent,
            "turn_count": state.turn_count,
            "message_history": json.loads(state.message_history) if state.message_history else None,
            "entered_at": state.entered_at,
        }


def _cleanup_expired() -> int:
    """Mark expired hibernations as inactive."""
    from sqlalchemy import update

    from core.infrastructure.db import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            update(HibernationState)
            .where(
                HibernationState.is_active,
                HibernationState.expires_at < datetime.now(UTC).replace(tzinfo=None),
            )
            .values(is_active=False)
        )
        conn.commit()
        return result.rowcount


# =============================================================================
# Async Hibernation Manager
# =============================================================================


class HibernationManager:
    """
    Manages FSM state persistence during HIBERNATE.

    All methods are static for easy access.

    Usage:
        # Enter hibernation (on WS disconnect)
        await HibernationManager.enter_hibernate(
            tenant_id=user.tenant_id,
            workspace_id="default",
            previous_state=OrchestratorState.BRAINSTORMING,
            fsm_context={"task": "...", "plan": "..."},
        )

        # Check for hibernation (on WS connect)
        state = await HibernationManager.get_hibernation(tenant_id, workspace_id)
        if state:
            # Resume from hibernation
            restored = await HibernationManager.exit_hibernate(tenant_id, workspace_id)
    """

    DEFAULT_TTL_HOURS = 24

    @staticmethod
    async def enter_hibernate(
        tenant_id: UUID,
        workspace_id: str,
        previous_state: str,
        fsm_context: dict | None = None,
        active_agent: str | None = None,
        turn_count: int = 0,
        message_history: list | None = None,
        ttl_hours: int = 24,
    ) -> dict:
        """
        Save state and enter hibernation.

        Args:
            tenant_id: Tenant UUID
            workspace_id: Workspace identifier
            previous_state: FSM state name before hibernation
            fsm_context: Workflow context to preserve
            active_agent: Currently active agent
            turn_count: Current turn count
            message_history: Recent messages
            ttl_hours: Time to live in hours

        Returns:
            Dict with hibernation info
        """
        # Save to SQLite (authoritative storage)
        result = await asyncio.to_thread(
            _save_hibernation,
            tenant_id,
            workspace_id,
            previous_state,
            fsm_context,
            active_agent,
            turn_count,
            message_history,
            ttl_hours,
        )

        # V12.3: Also cache in Redis if enabled (write-through)
        try:
            cache = await RedisHibernationCache.get_instance()
            await cache.set(tenant_id, workspace_id, result, ttl_hours)
        except Exception as e:
            logger.debug(f"[HIBERNATE] Redis cache update failed: {e}")

        logger.info(
            f"[HIBERNATE] Entered hibernation: tenant={tenant_id} "
            f"workspace={workspace_id} previous_state={previous_state}"
        )

        return result

    @staticmethod
    async def get_hibernation(
        tenant_id: UUID,
        workspace_id: str,
    ) -> dict | None:
        """
        Check if there's an active hibernation for tenant/workspace.

        V12.3: Checks Redis cache first for speed, falls back to SQLite.

        Args:
            tenant_id: Tenant UUID
            workspace_id: Workspace identifier

        Returns:
            Hibernation state dict or None
        """
        # V12.3: Try Redis cache first (fast path for multi-instance)
        try:
            cache = await RedisHibernationCache.get_instance()
            cached = await cache.get(tenant_id, workspace_id)
            if cached:
                return cached
        except Exception as e:
            logger.debug(f"[HIBERNATE] Redis cache check failed: {e}")

        # Fall back to SQLite (authoritative)
        return await asyncio.to_thread(_get_active_hibernation, tenant_id, workspace_id)

    @staticmethod
    async def exit_hibernate(
        tenant_id: UUID,
        workspace_id: str,
    ) -> dict | None:
        """
        Exit hibernation and restore state.

        Args:
            tenant_id: Tenant UUID
            workspace_id: Workspace identifier

        Returns:
            Restored state dict or None if no active hibernation
        """
        result = await asyncio.to_thread(_exit_hibernation, tenant_id, workspace_id)

        if result:
            logger.info(
                f"[HIBERNATE] Exited hibernation: tenant={tenant_id} "
                f"workspace={workspace_id} previous_state={result['previous_state']}"
            )
        else:
            logger.debug(f"[HIBERNATE] No active hibernation: tenant={tenant_id} workspace={workspace_id}")

        return result

    @staticmethod
    async def cleanup_expired() -> int:
        """
        Mark expired hibernations as inactive.

        Should be called periodically (e.g., hourly).

        Returns:
            Number of hibernations cleaned up
        """
        count = await asyncio.to_thread(_cleanup_expired)
        if count > 0:
            logger.info(f"[HIBERNATE] Cleaned up {count} expired hibernations")
        return count
