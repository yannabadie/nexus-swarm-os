"""
NEXUS V12.4 COGNITIVE BOOST - Tenant Memory Isolation

Multi-tenant memory isolation for SaaS deployments (OPERATION PRISM).
Each tenant gets a fully isolated RAGNamespaceManager with separate
storage, preventing cross-tenant data leakage.

Architecture:
    .nexus/
    +-- tenants/
    |   +-- tenant_abc/
    |   |   +-- project_knowledge.json
    |   |   +-- lancedb/
    |   |   +-- agent_rags/
    |   |   +-- rag_config.json
    |   +-- tenant_xyz/
    |   |   +-- ...
    |   +-- _default/             # Single-tenant fallback
    |       +-- ...
    +-- tenant_registry.json      # Tenant metadata

Usage:
    service = TenantMemoryService(nexus_root)

    # Get tenant-scoped namespace manager
    manager = service.get_tenant_manager("tenant_abc")
    project_rag = manager.get_project_rag()

    # List all tenants
    tenants = service.list_tenants()

    # Cleanup tenant data
    service.delete_tenant("tenant_abc")
"""

import json
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .namespace_manager import RAGNamespaceManager

logger = logging.getLogger(__name__)

# Default tenant for single-tenant deployments
DEFAULT_TENANT = "_default"

# Registry filename
TENANT_REGISTRY_FILE = "tenant_registry.json"


class TenantMemoryService:
    """
    Multi-tenant memory isolation service.

    Maps tenant IDs to isolated RAGNamespaceManager instances,
    each with its own storage directory. Ensures no cross-tenant
    data access is possible.
    """

    def __init__(
        self,
        nexus_root: Path,
        embedding_engine: Any | None = None,
    ):
        """
        Initialize the tenant memory service.

        Args:
            nexus_root: Root directory of NEXUS installation
            embedding_engine: Optional shared EmbeddingEngine (compute-only, no data)
        """
        self._nexus_root = Path(nexus_root)
        self._tenants_dir = self._nexus_root / ".nexus" / "tenants"
        self._registry_path = self._tenants_dir / TENANT_REGISTRY_FILE
        self._embedding_engine = embedding_engine

        # Cache: tenant_id -> RAGNamespaceManager
        self._managers: dict[str, RAGNamespaceManager] = {}

        # Ensure base directory exists
        self._tenants_dir.mkdir(parents=True, exist_ok=True)

        # Load registry
        self._registry = self._load_registry()

    # =========================================================================
    # Public API
    # =========================================================================

    def get_tenant_manager(
        self,
        tenant_id: str | None = None,
    ) -> RAGNamespaceManager:
        """
        Get the RAGNamespaceManager for a specific tenant.

        Creates the tenant's storage directory and manager on first access.

        Args:
            tenant_id: Tenant identifier (uses DEFAULT_TENANT if None)

        Returns:
            Isolated RAGNamespaceManager for the tenant
        """
        tenant_id = self._resolve_tenant(tenant_id)

        if tenant_id in self._managers:
            return self._managers[tenant_id]

        # Create tenant directory
        tenant_dir = self._tenants_dir / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)

        # Create isolated RAGNamespaceManager rooted at tenant directory
        manager = RAGNamespaceManager(
            nexus_root=tenant_dir,
            embedding_engine=self._embedding_engine,
        )

        # Register tenant if new
        if tenant_id not in self._registry.get("tenants", {}):
            self._registry.setdefault("tenants", {})[tenant_id] = {
                "created_at": datetime.now(UTC).isoformat(),
                "status": "active",
            }
            self._save_registry()

        self._managers[tenant_id] = manager
        logger.info(f"Tenant memory initialized: {tenant_id}")
        return manager

    def list_tenants(self) -> list[dict[str, Any]]:
        """
        List all registered tenants with their metadata.

        Returns:
            List of tenant info dicts with id, created_at, status, stats
        """
        result = []
        for tenant_id, meta in self._registry.get("tenants", {}).items():
            info = {
                "tenant_id": tenant_id,
                "created_at": meta.get("created_at", ""),
                "status": meta.get("status", "active"),
                "storage_path": str(self._tenants_dir / tenant_id),
            }

            # Add stats if manager is loaded
            if tenant_id in self._managers:
                try:
                    stats = self._managers[tenant_id].get_stats()
                    info["stats"] = stats
                except Exception:
                    info["stats"] = None
            else:
                info["stats"] = None

            result.append(info)

        return result

    def get_tenant_info(self, tenant_id: str) -> dict[str, Any] | None:
        """
        Get detailed info about a specific tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Tenant info dict, or None if not found
        """
        tenant_id = self._sanitize_tenant_id(tenant_id)
        meta = self._registry.get("tenants", {}).get(tenant_id)
        if meta is None:
            return None

        info = {
            "tenant_id": tenant_id,
            "created_at": meta.get("created_at", ""),
            "status": meta.get("status", "active"),
            "storage_path": str(self._tenants_dir / tenant_id),
        }

        # Load stats
        manager = self.get_tenant_manager(tenant_id)
        try:
            info["stats"] = manager.get_stats()
        except Exception:
            info["stats"] = None

        return info

    def delete_tenant(self, tenant_id: str) -> bool:
        """
        Delete a tenant's memory data.

        Removes all storage and cache for the tenant.
        Does NOT delete the _default tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if deleted, False if not found or protected
        """
        tenant_id = self._sanitize_tenant_id(tenant_id)

        if tenant_id == DEFAULT_TENANT:
            logger.warning("Cannot delete default tenant")
            return False

        tenant_dir = self._tenants_dir / tenant_id
        if not tenant_dir.exists():
            return False

        # Remove from cache
        self._managers.pop(tenant_id, None)

        # Remove from registry
        if tenant_id in self._registry.get("tenants", {}):
            del self._registry["tenants"][tenant_id]
            self._save_registry()

        # Delete storage
        try:
            shutil.rmtree(tenant_dir)
            logger.info(f"Tenant data deleted: {tenant_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete tenant {tenant_id}: {e}")
            return False

    def tenant_exists(self, tenant_id: str) -> bool:
        """Check if a tenant exists in the registry."""
        tenant_id = self._sanitize_tenant_id(tenant_id)
        return tenant_id in self._registry.get("tenants", {})

    @property
    def tenant_count(self) -> int:
        """Number of registered tenants."""
        return len(self._registry.get("tenants", {}))

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _resolve_tenant(self, tenant_id: str | None) -> str:
        """Resolve and sanitize tenant ID, defaulting to _default."""
        if tenant_id is None or tenant_id.strip() == "":
            return DEFAULT_TENANT
        return self._sanitize_tenant_id(tenant_id)

    def _sanitize_tenant_id(self, tenant_id: str) -> str:
        """Sanitize tenant ID for filesystem safety."""
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", tenant_id)
        return sanitized.lower()[:64]  # Max 64 chars

    def _load_registry(self) -> dict[str, Any]:
        """Load tenant registry from disk."""
        if self._registry_path.exists():
            try:
                return json.loads(self._registry_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load tenant registry: {e}")
        return {"tenants": {}, "created_at": datetime.now(UTC).isoformat()}

    def _save_registry(self):
        """Save tenant registry to disk."""
        try:
            self._registry_path.write_text(
                json.dumps(self._registry, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save tenant registry: {e}")


__all__ = ["TenantMemoryService", "DEFAULT_TENANT"]
