"""
Tests for V12.4 Multi-Tenant Memory Isolation (OPERATION PRISM).

Validates:
- Tenant storage isolation (each tenant gets own directory)
- Default tenant fallback for single-tenant deployments
- Tenant registration and listing
- Tenant deletion with storage cleanup
- Cross-tenant data isolation (critical security property)
- Tenant ID sanitization
- Registry persistence
"""

import json

import pytest

from core.memory_pkg.memory.namespace_manager import RAGNamespaceManager
from core.memory_pkg.memory.tenant_memory import DEFAULT_TENANT, TenantMemoryService


@pytest.fixture
def service(tmp_path):
    """Create a TenantMemoryService with temp storage."""
    return TenantMemoryService(nexus_root=tmp_path)


class TestTenantInitialization:
    """Test service initialization."""

    def test_creates_tenants_directory(self, tmp_path):
        """Should create .nexus/tenants/ on init."""
        TenantMemoryService(nexus_root=tmp_path)
        assert (tmp_path / ".nexus" / "tenants").exists()

    def test_empty_registry_on_fresh_start(self, service):
        """Should start with empty tenant registry."""
        assert service.tenant_count == 0

    def test_loads_existing_registry(self, tmp_path):
        """Should load existing registry from disk."""
        registry_path = tmp_path / ".nexus" / "tenants" / "tenant_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "tenants": {"existing_tenant": {"created_at": "2026-01-01", "status": "active"}},
                }
            )
        )

        service = TenantMemoryService(nexus_root=tmp_path)
        assert service.tenant_exists("existing_tenant")


class TestGetTenantManager:
    """Test tenant manager creation and retrieval."""

    def test_returns_rag_namespace_manager(self, service):
        """Should return a RAGNamespaceManager instance."""
        manager = service.get_tenant_manager("tenant_a")
        assert isinstance(manager, RAGNamespaceManager)

    def test_creates_tenant_directory(self, service, tmp_path):
        """Should create isolated storage directory for tenant."""
        service.get_tenant_manager("tenant_a")
        tenant_dir = tmp_path / ".nexus" / "tenants" / "tenant_a"
        assert tenant_dir.exists()

    def test_default_tenant_on_none(self, service, tmp_path):
        """Should use default tenant when None passed."""
        service.get_tenant_manager(None)
        default_dir = tmp_path / ".nexus" / "tenants" / DEFAULT_TENANT
        assert default_dir.exists()

    def test_default_tenant_on_empty_string(self, service, tmp_path):
        """Should use default tenant for empty string."""
        service.get_tenant_manager("")
        default_dir = tmp_path / ".nexus" / "tenants" / DEFAULT_TENANT
        assert default_dir.exists()

    def test_caches_manager_instances(self, service):
        """Same tenant ID should return same manager instance."""
        m1 = service.get_tenant_manager("tenant_a")
        m2 = service.get_tenant_manager("tenant_a")
        assert m1 is m2

    def test_different_tenants_different_managers(self, service):
        """Different tenant IDs should return different managers."""
        m1 = service.get_tenant_manager("tenant_a")
        m2 = service.get_tenant_manager("tenant_b")
        assert m1 is not m2

    def test_registers_tenant(self, service):
        """Getting a manager should register the tenant."""
        assert not service.tenant_exists("new_tenant")
        service.get_tenant_manager("new_tenant")
        assert service.tenant_exists("new_tenant")
        assert service.tenant_count == 1


class TestTenantIsolation:
    """Test cross-tenant data isolation (CRITICAL)."""

    def test_separate_storage_paths(self, service, tmp_path):
        """Each tenant must have a distinct storage path."""
        m_a = service.get_tenant_manager("tenant_a")
        m_b = service.get_tenant_manager("tenant_b")

        # Storage directories should be different
        assert m_a.storage_dir != m_b.storage_dir
        assert "tenant_a" in str(m_a.storage_dir)
        assert "tenant_b" in str(m_b.storage_dir)

    def test_separate_config_files(self, service, tmp_path):
        """Each tenant should have its own rag_config.json path."""
        m_a = service.get_tenant_manager("tenant_a")
        m_b = service.get_tenant_manager("tenant_b")

        # Config paths must be different (isolated)
        assert m_a.config_path != m_b.config_path
        # Both paths should be under their respective tenant dirs
        assert "tenant_a" in str(m_a.config_path)
        assert "tenant_b" in str(m_b.config_path)

    def test_agent_rags_isolated(self, service):
        """Agent RAGs in one tenant should not appear in another."""
        m_a = service.get_tenant_manager("tenant_a")
        m_b = service.get_tenant_manager("tenant_b")

        # Create agent RAG in tenant A
        m_a.create_agent_rag("security_expert", metadata={"source": "tenant_a"})

        # Tenant B should not see it
        namespaces_b = m_b.list_namespaces()
        ns_names = [ns.name for ns in namespaces_b]
        assert "security_expert" not in ns_names

    def test_project_rags_isolated(self, service):
        """Project RAG data in one tenant should not leak to another."""
        m_a = service.get_tenant_manager("tenant_a")
        m_b = service.get_tenant_manager("tenant_b")

        project_a = m_a.get_project_rag()
        project_b = m_b.get_project_rag()

        # Different storage paths
        assert project_a.storage_path != project_b.storage_path


class TestTenantListing:
    """Test tenant enumeration."""

    def test_list_empty(self, service):
        """Should return empty list when no tenants."""
        assert service.list_tenants() == []

    def test_list_multiple_tenants(self, service):
        """Should list all registered tenants."""
        service.get_tenant_manager("alpha")
        service.get_tenant_manager("beta")
        service.get_tenant_manager("gamma")

        tenants = service.list_tenants()
        tenant_ids = [t["tenant_id"] for t in tenants]
        assert "alpha" in tenant_ids
        assert "beta" in tenant_ids
        assert "gamma" in tenant_ids
        assert len(tenants) == 3

    def test_tenant_info_has_metadata(self, service):
        """Tenant info should include created_at and status."""
        service.get_tenant_manager("test_tenant")
        tenants = service.list_tenants()
        info = tenants[0]

        assert info["tenant_id"] == "test_tenant"
        assert info["status"] == "active"
        assert "created_at" in info
        assert "storage_path" in info

    def test_get_tenant_info(self, service):
        """Should return detailed info for specific tenant."""
        service.get_tenant_manager("info_test")
        info = service.get_tenant_info("info_test")

        assert info is not None
        assert info["tenant_id"] == "info_test"

    def test_get_tenant_info_nonexistent(self, service):
        """Should return None for unknown tenant."""
        info = service.get_tenant_info("nonexistent")
        assert info is None


class TestTenantDeletion:
    """Test tenant data deletion."""

    def test_delete_tenant_removes_storage(self, service, tmp_path):
        """Should remove tenant directory on delete."""
        service.get_tenant_manager("doomed_tenant")
        tenant_dir = tmp_path / ".nexus" / "tenants" / "doomed_tenant"
        assert tenant_dir.exists()

        result = service.delete_tenant("doomed_tenant")
        assert result is True
        assert not tenant_dir.exists()

    def test_delete_removes_from_registry(self, service):
        """Should remove tenant from registry."""
        service.get_tenant_manager("delete_me")
        assert service.tenant_exists("delete_me")

        service.delete_tenant("delete_me")
        assert not service.tenant_exists("delete_me")

    def test_delete_removes_from_cache(self, service):
        """Should clear cached manager on delete."""
        m1 = service.get_tenant_manager("cached_tenant")
        service.delete_tenant("cached_tenant")

        # New manager should be a fresh instance
        m2 = service.get_tenant_manager("cached_tenant")
        assert m1 is not m2

    def test_delete_nonexistent_returns_false(self, service):
        """Should return False for nonexistent tenant."""
        result = service.delete_tenant("ghost")
        assert result is False

    def test_cannot_delete_default_tenant(self, service):
        """Should refuse to delete the default tenant."""
        service.get_tenant_manager(None)  # Creates default
        result = service.delete_tenant(DEFAULT_TENANT)
        assert result is False
        assert service.tenant_exists(DEFAULT_TENANT)


class TestTenantIdSanitization:
    """Test tenant ID sanitization for security."""

    def test_lowercase(self, service):
        """Should lowercase tenant IDs."""
        service.get_tenant_manager("UPPER_CASE")
        assert service.tenant_exists("upper_case")

    def test_special_chars_replaced(self, service):
        """Should replace special characters with underscores."""
        service.get_tenant_manager("tenant/with\\special.chars!")
        # Verify it was sanitized (check directory exists with sanitized name)
        tenants = service.list_tenants()
        assert len(tenants) == 1
        # No slashes or dots in the ID
        assert "/" not in tenants[0]["tenant_id"]
        assert "\\" not in tenants[0]["tenant_id"]

    def test_max_length(self, service):
        """Should truncate long tenant IDs."""
        long_id = "a" * 200
        service.get_tenant_manager(long_id)
        tenants = service.list_tenants()
        assert len(tenants[0]["tenant_id"]) <= 64

    def test_path_traversal_prevented(self, service, tmp_path):
        """Must prevent path traversal attacks."""
        service.get_tenant_manager("../../etc/passwd")
        tenants = service.list_tenants()
        # Should be sanitized, not a path traversal
        tenant_id = tenants[0]["tenant_id"]
        assert ".." not in tenant_id
        # Storage should be under tenants dir
        assert tenants[0]["storage_path"].startswith(str(tmp_path / ".nexus" / "tenants"))


class TestRegistryPersistence:
    """Test that tenant registry survives restarts."""

    def test_registry_persists_across_instances(self, tmp_path):
        """Registry should survive service restart."""
        # Create tenants in first instance
        s1 = TenantMemoryService(nexus_root=tmp_path)
        s1.get_tenant_manager("persistent_tenant")
        assert s1.tenant_count == 1

        # New instance should see the tenant
        s2 = TenantMemoryService(nexus_root=tmp_path)
        assert s2.tenant_exists("persistent_tenant")
        assert s2.tenant_count == 1

    def test_delete_persists_across_instances(self, tmp_path):
        """Deletion should persist across restarts."""
        s1 = TenantMemoryService(nexus_root=tmp_path)
        s1.get_tenant_manager("temp_tenant")
        s1.delete_tenant("temp_tenant")

        s2 = TenantMemoryService(nexus_root=tmp_path)
        assert not s2.tenant_exists("temp_tenant")


class TestModuleExports:
    """Test module-level exports."""

    def test_importable_from_memory_package(self):
        """Should be importable from core.memory_pkg.memory."""
        from core.memory_pkg.memory import DEFAULT_TENANT, TenantMemoryService

        assert TenantMemoryService is not None
        assert DEFAULT_TENANT == "_default"
