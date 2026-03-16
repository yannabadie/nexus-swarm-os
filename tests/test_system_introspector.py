"""
Tests for V12.4 System Introspector.

Validates:
- ComponentInfo to_dict
- SystemSnapshot to_dict
- IntrospectorStats to_dict
- Registration (register, unregister)
- Status updates
- Capability management
- Queries (by ID, category, status, capability)
- Snapshot generation
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.meta.system_introspector import (
    CATEGORIES,
    MAX_COMPONENTS,
    ComponentInfo,
    IntrospectorStats,
    SystemIntrospector,
    SystemSnapshot,
    get_introspector,
    reset_introspector,
)

# =============================================================================
# ComponentInfo Tests
# =============================================================================


class TestComponentInfo:
    """Test ComponentInfo dataclass."""

    def test_basic(self):
        c = ComponentInfo(component_id="swarm", category="orchestration")
        assert c.component_id == "swarm"
        assert c.status == "active"

    def test_to_dict(self):
        c = ComponentInfo(
            component_id="swarm",
            category="orchestration",
            version="12.4",
            capabilities=["parallel", "sequential"],
        )
        d = c.to_dict()
        assert d["version"] == "12.4"
        assert len(d["capabilities"]) == 2


# =============================================================================
# SystemSnapshot Tests
# =============================================================================


class TestSystemSnapshot:
    """Test SystemSnapshot dataclass."""

    def test_to_dict(self):
        s = SystemSnapshot(
            total_components=5,
            active_components=3,
            degraded_components=1,
            inactive_components=1,
            categories={"orchestration": 2, "memory": 3},
            total_capabilities=10,
        )
        d = s.to_dict()
        assert d["active_components"] == 3
        assert d["categories"]["memory"] == 3


# =============================================================================
# IntrospectorStats Tests
# =============================================================================


class TestIntrospectorStats:
    """Test IntrospectorStats dataclass."""

    def test_to_dict(self):
        s = IntrospectorStats(total_registered=5, total_queries=20, total_capability_lookups=8)
        d = s.to_dict()
        assert d["total_queries"] == 20


# =============================================================================
# Registration Tests
# =============================================================================


class TestRegistration:
    """Test component registration."""

    def test_register(self):
        i = SystemIntrospector()
        assert i.register_component("swarm", category="orchestration") is True
        assert i.component_count == 1

    def test_register_duplicate(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        assert i.register_component("swarm") is False

    def test_register_with_capabilities(self):
        i = SystemIntrospector()
        i.register_component("swarm", capabilities=["parallel", "sequential"])
        comp = i.get_component("swarm")
        assert comp.capabilities == ["parallel", "sequential"]

    def test_register_with_metadata(self):
        i = SystemIntrospector()
        i.register_component("swarm", metadata={"author": "claude"})
        comp = i.get_component("swarm")
        assert comp.metadata["author"] == "claude"

    def test_unregister(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        assert i.unregister_component("swarm") is True
        assert i.component_count == 0

    def test_unregister_not_found(self):
        i = SystemIntrospector()
        assert i.unregister_component("missing") is False

    def test_is_registered(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        assert i.is_registered("swarm") is True
        assert i.is_registered("missing") is False


# =============================================================================
# Status Tests
# =============================================================================


class TestStatus:
    """Test status updates."""

    def test_update_status(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        assert i.update_status("swarm", "degraded") is True
        comp = i.get_component("swarm")
        assert comp.status == "degraded"

    def test_update_status_not_found(self):
        i = SystemIntrospector()
        assert i.update_status("missing", "active") is False


# =============================================================================
# Capability Tests
# =============================================================================


class TestCapabilities:
    """Test capability management."""

    def test_add_capability(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        assert i.add_capability("swarm", "parallel") is True
        comp = i.get_component("swarm")
        assert "parallel" in comp.capabilities

    def test_add_capability_not_found(self):
        i = SystemIntrospector()
        assert i.add_capability("missing", "parallel") is False

    def test_add_duplicate_capability(self):
        i = SystemIntrospector()
        i.register_component("swarm", capabilities=["parallel"])
        i.add_capability("swarm", "parallel")
        comp = i.get_component("swarm")
        assert comp.capabilities.count("parallel") == 1

    def test_remove_capability(self):
        i = SystemIntrospector()
        i.register_component("swarm", capabilities=["parallel", "sequential"])
        assert i.remove_capability("swarm", "parallel") is True
        comp = i.get_component("swarm")
        assert "parallel" not in comp.capabilities

    def test_remove_capability_not_found(self):
        i = SystemIntrospector()
        assert i.remove_capability("missing", "parallel") is False

    def test_remove_nonexistent_capability(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        assert i.remove_capability("swarm", "nonexistent") is False


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_component(self):
        i = SystemIntrospector()
        i.register_component("swarm", version="12.4")
        comp = i.get_component("swarm")
        assert comp is not None
        assert comp.version == "12.4"

    def test_get_component_not_found(self):
        i = SystemIntrospector()
        assert i.get_component("missing") is None

    def test_list_components(self):
        i = SystemIntrospector()
        i.register_component("b_comp")
        i.register_component("a_comp")
        assert i.list_components() == ["a_comp", "b_comp"]

    def test_list_components_by_category(self):
        i = SystemIntrospector()
        i.register_component("swarm", category="orchestration")
        i.register_component("memory", category="memory")
        i.register_component("hive", category="orchestration")
        result = i.list_components(category="orchestration")
        assert len(result) == 2

    def test_list_components_by_status(self):
        i = SystemIntrospector()
        i.register_component("active_comp")
        i.register_component("degraded_comp")
        i.update_status("degraded_comp", "degraded")
        result = i.list_components(status="active")
        assert result == ["active_comp"]

    def test_find_by_capability(self):
        i = SystemIntrospector()
        i.register_component("swarm", capabilities=["parallel", "sequential"])
        i.register_component("hive", capabilities=["analysis", "parallel"])
        i.register_component("memory", capabilities=["rag", "search"])
        results = i.find_by_capability("parallel")
        assert len(results) == 2

    def test_find_by_capability_excludes_inactive(self):
        i = SystemIntrospector()
        i.register_component("swarm", capabilities=["parallel"])
        i.register_component("old_swarm", capabilities=["parallel"])
        i.update_status("old_swarm", "inactive")
        results = i.find_by_capability("parallel")
        assert len(results) == 1

    def test_list_all_capabilities(self):
        i = SystemIntrospector()
        i.register_component("a", capabilities=["cap1", "cap2"])
        i.register_component("b", capabilities=["cap2", "cap3"])
        caps = i.list_all_capabilities()
        assert caps == ["cap1", "cap2", "cap3"]

    def test_get_by_category(self):
        i = SystemIntrospector()
        i.register_component("swarm", category="orchestration")
        i.register_component("memory", category="memory")
        results = i.get_by_category("orchestration")
        assert len(results) == 1
        assert results[0].component_id == "swarm"


# =============================================================================
# Snapshot Tests
# =============================================================================


class TestSnapshot:
    """Test system snapshot generation."""

    def test_empty_snapshot(self):
        i = SystemIntrospector()
        snap = i.get_snapshot()
        assert snap.total_components == 0

    def test_snapshot_with_components(self):
        i = SystemIntrospector()
        i.register_component("swarm", category="orchestration", capabilities=["parallel"])
        i.register_component("memory", category="memory", capabilities=["rag"])
        i.register_component("old", category="other")
        i.update_status("old", "inactive")
        snap = i.get_snapshot()
        assert snap.total_components == 3
        assert snap.active_components == 2
        assert snap.inactive_components == 1
        assert snap.total_capabilities == 2
        assert snap.categories["orchestration"] == 1

    def test_snapshot_to_dict(self):
        i = SystemIntrospector()
        d = i.get_snapshot().to_dict()
        assert "total_components" in d
        assert "categories" in d


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test introspector statistics."""

    def test_initial_stats(self):
        i = SystemIntrospector()
        stats = i.get_stats()
        assert stats.total_registered == 0
        assert stats.total_queries == 0

    def test_stats_track_queries(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        i.get_component("swarm")
        i.list_components()
        stats = i.get_stats()
        assert stats.total_queries == 2

    def test_stats_track_capability_lookups(self):
        i = SystemIntrospector()
        i.register_component("swarm", capabilities=["parallel"])
        i.find_by_capability("parallel")
        stats = i.get_stats()
        assert stats.total_capability_lookups == 1

    def test_stats_to_dict(self):
        i = SystemIntrospector()
        d = i.get_stats().to_dict()
        assert "total_queries" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_component_count(self):
        i = SystemIntrospector()
        i.register_component("a")
        i.register_component("b")
        assert i.component_count == 2

    def test_clear(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        i.get_component("swarm")
        i.clear()
        assert i.component_count == 0
        assert i.get_stats().total_queries == 0

    def test_to_dict(self):
        i = SystemIntrospector()
        i.register_component("swarm")
        d = i.to_dict()
        assert d["component_count"] == 1
        assert "snapshot" in d
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global introspector."""

    def test_get(self):
        reset_introspector()
        intro = get_introspector()
        assert isinstance(intro, SystemIntrospector)

    def test_singleton(self):
        reset_introspector()
        i1 = get_introspector()
        i2 = get_introspector()
        assert i1 is i2

    def test_reset(self):
        reset_introspector()
        i1 = get_introspector()
        reset_introspector()
        i2 = get_introspector()
        assert i1 is not i2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_meta_package(self):
        from core.meta import (
            ComponentInfo,
            IntrospectorStats,
            SystemIntrospector,
            SystemSnapshot,
            get_introspector,
            reset_introspector,
        )

        assert all(
            [
                SystemIntrospector,
                ComponentInfo,
                SystemSnapshot,
                IntrospectorStats,
                get_introspector,
                reset_introspector,
            ]
        )

    def test_constants(self):
        assert MAX_COMPONENTS == 1000
        assert "orchestration" in CATEGORIES
