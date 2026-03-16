"""
Context Audit Trail - Track all context activations for compliance.

V12.4 COGNITIVE BOOST

Provides an append-only audit log for all context changes:
- Context activations (tenant/user/workspace entry)
- Context deactivations (exit)
- Access violations (unauthorized attempts)

Usage:
    from core.infrastructure.context.audit_trail import get_audit_trail

    trail = get_audit_trail()
    trail.record_activation(tenant_id="t1", user_id="u1", context_id="ctx_123")
    trail.record_deactivation(context_id="ctx_123")

    # Query
    entries = trail.query_by_tenant("t1")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_ENTRIES = 50000
DEFAULT_RETENTION = 86400.0  # 24 hours in seconds


# =============================================================================
# Types
# =============================================================================


@dataclass
class AuditEntry:
    """A single audit log entry."""

    context_id: str
    action: str  # "activation", "deactivation", "violation"
    tenant_id: str = ""
    user_id: str = ""
    workspace_id: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "action": self.action,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass
class AuditStats:
    """Audit trail statistics."""

    total_entries: int
    activations: int
    deactivations: int
    violations: int
    unique_tenants: int
    unique_users: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "activations": self.activations,
            "deactivations": self.deactivations,
            "violations": self.violations,
            "unique_tenants": self.unique_tenants,
            "unique_users": self.unique_users,
        }


# =============================================================================
# Audit Trail
# =============================================================================


class ContextAuditTrail:
    """
    Append-only audit log for context changes.

    Features:
    - Record activations, deactivations, and violations
    - Query by tenant, user, action, context_id, and time range
    - Bounded history with auto-eviction
    - Thread-safe
    """

    def __init__(self, *, max_entries: int = MAX_ENTRIES):
        self._max_entries = max_entries
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_activation(
        self,
        context_id: str,
        *,
        tenant_id: str = "",
        user_id: str = "",
        workspace_id: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Record a context activation."""
        entry = AuditEntry(
            context_id=context_id,
            action="activation",
            tenant_id=tenant_id,
            user_id=user_id,
            workspace_id=workspace_id,
            reason=reason,
            metadata=metadata or {},
        )
        self._append(entry)
        return entry

    def record_deactivation(
        self,
        context_id: str,
        *,
        tenant_id: str = "",
        user_id: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Record a context deactivation."""
        entry = AuditEntry(
            context_id=context_id,
            action="deactivation",
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
            metadata=metadata or {},
        )
        self._append(entry)
        return entry

    def record_violation(
        self,
        context_id: str,
        *,
        tenant_id: str = "",
        user_id: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Record an access violation attempt."""
        entry = AuditEntry(
            context_id=context_id,
            action="violation",
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
            metadata=metadata or {},
        )
        self._append(entry)
        _logger.warning(f"Context violation: ctx={context_id} tenant={tenant_id} user={user_id} reason={reason}")
        return entry

    def _append(self, entry: AuditEntry) -> None:
        """Append entry, evicting oldest if at capacity."""
        with self._lock:
            self._entries.append(entry)
            while len(self._entries) > self._max_entries:
                self._entries.pop(0)

    # =========================================================================
    # Queries
    # =========================================================================

    def query_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditEntry]:
        """Get entries for a specific tenant."""
        return self._filter(lambda e: e.tenant_id == tenant_id, limit)

    def query_by_user(self, user_id: str, *, limit: int = 100) -> list[AuditEntry]:
        """Get entries for a specific user."""
        return self._filter(lambda e: e.user_id == user_id, limit)

    def query_by_action(self, action: str, *, limit: int = 100) -> list[AuditEntry]:
        """Get entries for a specific action type."""
        return self._filter(lambda e: e.action == action, limit)

    def query_by_context(self, context_id: str, *, limit: int = 100) -> list[AuditEntry]:
        """Get entries for a specific context ID."""
        return self._filter(lambda e: e.context_id == context_id, limit)

    def query_by_time_range(self, start: float, end: float, *, limit: int = 100) -> list[AuditEntry]:
        """Get entries within a time range (monotonic timestamps)."""
        return self._filter(lambda e: start <= e.timestamp <= end, limit)

    def get_violations(self, *, limit: int = 100) -> list[AuditEntry]:
        """Get all violation entries."""
        return self.query_by_action("violation", limit=limit)

    def get_recent(self, limit: int = 50) -> list[AuditEntry]:
        """Get most recent entries."""
        return list(reversed(self._entries[-limit:]))

    def _filter(self, predicate, limit: int) -> list[AuditEntry]:
        """Filter entries with predicate, most recent first."""
        results = []
        for entry in reversed(self._entries):
            if predicate(entry):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> AuditStats:
        """Get audit trail statistics."""
        activations = sum(1 for e in self._entries if e.action == "activation")
        deactivations = sum(1 for e in self._entries if e.action == "deactivation")
        violations = sum(1 for e in self._entries if e.action == "violation")
        tenants = {e.tenant_id for e in self._entries if e.tenant_id}
        users = {e.user_id for e in self._entries if e.user_id}
        return AuditStats(
            total_entries=len(self._entries),
            activations=activations,
            deactivations=deactivations,
            violations=violations,
            unique_tenants=len(tenants),
            unique_users=len(users),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def size(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """Clear all audit entries."""
        with self._lock:
            self._entries.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_entries": self._max_entries,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_trail: ContextAuditTrail | None = None
_trail_lock = threading.Lock()


def get_audit_trail() -> ContextAuditTrail:
    """Get or create the global audit trail."""
    global _trail
    if _trail is None:
        with _trail_lock:
            if _trail is None:
                _trail = ContextAuditTrail()
    return _trail


def reset_audit_trail() -> None:
    """Reset the global audit trail (for testing)."""
    global _trail
    _trail = None
