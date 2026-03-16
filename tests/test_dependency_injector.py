"""
Tests for V12.4 Dependency Injector.

Validates:
- Capability registration/unregistration
- Availability toggling
- Agent requirement declaration
- Validation (ready/missing/unavailable)
- Conflict detection (exclusive resources)
- Dependency manifest generation
- Listing capabilities and agents
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.orchestration.dependency_injector import (
    AgentRequirements,
    Capability,
    Conflict,
    DependencyInjector,
    DependencyManifest,
    ValidationResult,
    get_injector,
    reset_injector,
)

# =============================================================================
# Capability Tests
# =============================================================================


class TestCapability:
    """Test Capability dataclass."""

    def test_basic_creation(self):
        cap = Capability(name="web_search", provider="tools.web")
        assert cap.name == "web_search"
        assert cap.provider == "tools.web"
        assert cap.exclusive is False
        assert cap.available is True

    def test_exclusive(self):
        cap = Capability(name="code_exec", exclusive=True)
        assert cap.exclusive is True

    def test_to_dict(self):
        cap = Capability(
            name="web_search",
            provider="tools.web",
            description="Search the web",
            exclusive=False,
        )
        d = cap.to_dict()
        assert d["name"] == "web_search"
        assert d["provider"] == "tools.web"
        assert d["exclusive"] is False


# =============================================================================
# Register Tests
# =============================================================================


class TestRegister:
    """Test capability registration."""

    def test_register(self):
        di = DependencyInjector()
        cap = di.register("web_search", provider="tools.web")
        assert cap.name == "web_search"
        assert di.capability_count == 1

    def test_register_multiple(self):
        di = DependencyInjector()
        di.register("web_search")
        di.register("code_exec")
        di.register("file_read")
        assert di.capability_count == 3

    def test_register_with_metadata(self):
        di = DependencyInjector()
        cap = di.register("web_search", metadata={"rate_limit": 100})
        assert cap.metadata["rate_limit"] == 100

    def test_register_exclusive(self):
        di = DependencyInjector()
        cap = di.register("gpu", exclusive=True)
        assert cap.exclusive is True

    def test_unregister(self):
        di = DependencyInjector()
        di.register("web_search")
        assert di.unregister("web_search") is True
        assert di.capability_count == 0

    def test_unregister_nonexistent(self):
        di = DependencyInjector()
        assert di.unregister("missing") is False

    def test_is_registered(self):
        di = DependencyInjector()
        di.register("web_search")
        assert di.is_registered("web_search") is True
        assert di.is_registered("missing") is False

    def test_get_capability(self):
        di = DependencyInjector()
        di.register("web_search", provider="tools.web")
        cap = di.get_capability("web_search")
        assert cap is not None
        assert cap.provider == "tools.web"

    def test_get_capability_not_found(self):
        di = DependencyInjector()
        assert di.get_capability("missing") is None


# =============================================================================
# Availability Tests
# =============================================================================


class TestAvailability:
    """Test capability availability."""

    def test_default_available(self):
        di = DependencyInjector()
        di.register("web_search")
        assert di.is_available("web_search") is True

    def test_set_unavailable(self):
        di = DependencyInjector()
        di.register("web_search")
        assert di.set_available("web_search", False) is True
        assert di.is_available("web_search") is False

    def test_set_available_again(self):
        di = DependencyInjector()
        di.register("web_search")
        di.set_available("web_search", False)
        di.set_available("web_search", True)
        assert di.is_available("web_search") is True

    def test_set_available_nonexistent(self):
        di = DependencyInjector()
        assert di.set_available("missing", True) is False

    def test_is_available_not_registered(self):
        di = DependencyInjector()
        assert di.is_available("missing") is False


# =============================================================================
# Requirements Tests
# =============================================================================


class TestRequirements:
    """Test agent requirement declaration."""

    def test_require_basic(self):
        di = DependencyInjector()
        reqs = di.require("claude", ["web_search", "code_exec"])
        assert reqs.agent_id == "claude"
        assert reqs.required == {"web_search", "code_exec"}

    def test_require_optional(self):
        di = DependencyInjector()
        reqs = di.require("claude", ["web_search"], optional=["gpu"])
        assert reqs.optional == {"gpu"}

    def test_require_additive(self):
        di = DependencyInjector()
        di.require("claude", ["web_search"])
        di.require("claude", ["code_exec"])
        reqs = di.get_requirements("claude")
        assert reqs.required == {"web_search", "code_exec"}

    def test_get_requirements(self):
        di = DependencyInjector()
        di.require("claude", ["web_search"])
        reqs = di.get_requirements("claude")
        assert reqs is not None
        assert reqs.agent_id == "claude"

    def test_get_requirements_not_found(self):
        di = DependencyInjector()
        assert di.get_requirements("missing") is None

    def test_requirements_to_dict(self):
        di = DependencyInjector()
        reqs = di.require("claude", ["b", "a"], optional=["c"])
        d = reqs.to_dict()
        assert d["agent_id"] == "claude"
        assert d["required"] == ["a", "b"]  # sorted
        assert d["optional"] == ["c"]


# =============================================================================
# Validation Tests
# =============================================================================


class TestValidation:
    """Test agent readiness validation."""

    def test_validate_ready(self):
        di = DependencyInjector()
        di.register("web_search")
        di.register("code_exec")
        di.require("claude", ["web_search", "code_exec"])
        result = di.validate("claude")
        assert result.ready is True
        assert sorted(result.satisfied) == ["code_exec", "web_search"]
        assert result.missing == []

    def test_validate_missing(self):
        di = DependencyInjector()
        di.register("web_search")
        di.require("claude", ["web_search", "gpu_compute"])
        result = di.validate("claude")
        assert result.ready is False
        assert result.missing == ["gpu_compute"]

    def test_validate_unavailable(self):
        di = DependencyInjector()
        di.register("web_search")
        di.set_available("web_search", False)
        di.require("claude", ["web_search"])
        result = di.validate("claude")
        assert result.ready is False
        assert result.unavailable == ["web_search"]

    def test_validate_no_requirements(self):
        di = DependencyInjector()
        result = di.validate("claude")
        assert result.ready is True  # No requirements = ready

    def test_validate_optional_satisfied(self):
        di = DependencyInjector()
        di.register("web_search")
        di.register("gpu")
        di.require("claude", ["web_search"], optional=["gpu"])
        result = di.validate("claude")
        assert result.ready is True
        assert result.optional_satisfied == ["gpu"]

    def test_validate_optional_missing(self):
        di = DependencyInjector()
        di.register("web_search")
        di.require("claude", ["web_search"], optional=["gpu"])
        result = di.validate("claude")
        assert result.ready is True  # Still ready (optional missing is OK)
        assert result.optional_missing == ["gpu"]

    def test_validate_to_dict(self):
        di = DependencyInjector()
        di.register("web_search")
        di.require("claude", ["web_search"])
        result = di.validate("claude")
        d = result.to_dict()
        assert d["agent_id"] == "claude"
        assert d["ready"] is True

    def test_validate_all(self):
        di = DependencyInjector()
        di.register("web_search")
        di.require("claude", ["web_search"])
        di.require("gemini", ["web_search"])
        results = di.validate_all()
        assert len(results) == 2
        assert all(r.ready for r in results)

    def test_validate_all_mixed(self):
        di = DependencyInjector()
        di.register("web_search")
        di.require("claude", ["web_search"])
        di.require("gemini", ["gpu"])  # Not registered
        results = di.validate_all()
        claude_result = next(r for r in results if r.agent_id == "claude")
        gemini_result = next(r for r in results if r.agent_id == "gemini")
        assert claude_result.ready is True
        assert gemini_result.ready is False


# =============================================================================
# Conflict Detection Tests
# =============================================================================


class TestConflictDetection:
    """Test conflict detection."""

    def test_no_conflicts(self):
        di = DependencyInjector()
        di.register("web_search")  # Not exclusive
        di.require("claude", ["web_search"])
        di.require("gemini", ["web_search"])
        conflicts = di.detect_conflicts()
        assert conflicts == []

    def test_exclusive_conflict(self):
        di = DependencyInjector()
        di.register("gpu", exclusive=True)
        di.require("claude", ["gpu"])
        di.require("gemini", ["gpu"])
        conflicts = di.detect_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].capability == "gpu"
        assert sorted(conflicts[0].agents) == ["claude", "gemini"]

    def test_no_conflict_single_user(self):
        di = DependencyInjector()
        di.register("gpu", exclusive=True)
        di.require("claude", ["gpu"])
        conflicts = di.detect_conflicts()
        assert conflicts == []

    def test_conflict_subset_agents(self):
        di = DependencyInjector()
        di.register("gpu", exclusive=True)
        di.require("claude", ["gpu"])
        di.require("gemini", ["gpu"])
        di.require("ollama", [])
        # Only check claude and ollama
        conflicts = di.detect_conflicts(["claude", "ollama"])
        assert conflicts == []

    def test_conflict_to_dict(self):
        di = DependencyInjector()
        di.register("gpu", exclusive=True)
        di.require("claude", ["gpu"])
        di.require("gemini", ["gpu"])
        conflicts = di.detect_conflicts()
        d = conflicts[0].to_dict()
        assert d["capability"] == "gpu"
        assert "agents" in d
        assert "reason" in d

    def test_multiple_conflicts(self):
        di = DependencyInjector()
        di.register("gpu", exclusive=True)
        di.register("serial_port", exclusive=True)
        di.require("agent_a", ["gpu", "serial_port"])
        di.require("agent_b", ["gpu", "serial_port"])
        conflicts = di.detect_conflicts()
        assert len(conflicts) == 2


# =============================================================================
# Manifest Tests
# =============================================================================


class TestManifest:
    """Test dependency manifest generation."""

    def test_full_manifest(self):
        di = DependencyInjector()
        di.register("web_search", provider="tools.web")
        di.register("code_exec", provider="tools.bash")
        di.require("claude", ["web_search", "code_exec"], optional=["gpu"])
        manifest = di.get_manifest("claude")
        assert manifest is not None
        assert manifest.agent_id == "claude"
        assert sorted(manifest.required_capabilities) == ["code_exec", "web_search"]
        assert manifest.optional_capabilities == ["gpu"]
        assert manifest.resolved == {
            "code_exec": "tools.bash",
            "web_search": "tools.web",
        }
        assert manifest.unresolved == []

    def test_manifest_with_unresolved(self):
        di = DependencyInjector()
        di.register("web_search", provider="tools.web")
        di.require("claude", ["web_search", "gpu"])
        manifest = di.get_manifest("claude")
        assert manifest.unresolved == ["gpu"]
        assert "web_search" in manifest.resolved

    def test_manifest_not_found(self):
        di = DependencyInjector()
        assert di.get_manifest("missing") is None

    def test_manifest_to_dict(self):
        di = DependencyInjector()
        di.register("web_search", provider="tools.web")
        di.require("claude", ["web_search"])
        manifest = di.get_manifest("claude")
        d = manifest.to_dict()
        assert d["agent_id"] == "claude"
        assert "resolved" in d
        assert "unresolved" in d


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test listing capabilities and agents."""

    def test_list_capabilities(self):
        di = DependencyInjector()
        di.register("c_cap")
        di.register("a_cap")
        di.register("b_cap")
        caps = di.list_capabilities()
        assert [c.name for c in caps] == ["a_cap", "b_cap", "c_cap"]

    def test_list_capabilities_available_only(self):
        di = DependencyInjector()
        di.register("available")
        di.register("unavailable")
        di.set_available("unavailable", False)
        caps = di.list_capabilities(available_only=True)
        assert len(caps) == 1
        assert caps[0].name == "available"

    def test_list_agents(self):
        di = DependencyInjector()
        di.require("gemini", ["a"])
        di.require("claude", ["b"])
        assert di.list_agents() == ["claude", "gemini"]


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        di = DependencyInjector()
        assert di.capability_count == 0
        assert di.agent_count == 0
        di.register("cap1")
        di.require("agent1", ["cap1"])
        assert di.capability_count == 1
        assert di.agent_count == 1

    def test_clear(self):
        di = DependencyInjector()
        di.register("cap1")
        di.require("agent1", ["cap1"])
        di.clear()
        assert di.capability_count == 0
        assert di.agent_count == 0

    def test_to_dict(self):
        di = DependencyInjector()
        di.register("web_search", provider="tools.web")
        di.require("claude", ["web_search"])
        d = di.to_dict()
        assert d["capability_count"] == 1
        assert d["agent_count"] == 1
        assert "web_search" in d["capabilities"]
        assert "claude" in d["agents"]


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global injector."""

    def test_get_injector(self):
        reset_injector()
        di = get_injector()
        assert isinstance(di, DependencyInjector)

    def test_singleton(self):
        reset_injector()
        d1 = get_injector()
        d2 = get_injector()
        assert d1 is d2

    def test_reset(self):
        reset_injector()
        d1 = get_injector()
        reset_injector()
        d2 = get_injector()
        assert d1 is not d2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_orchestration_package(self):
        from core.execution_pkg.orchestration import (
            AgentRequirements,
            Capability,
            Conflict,
            DependencyInjector,
            DependencyManifest,
            DependencyValidationResult,
            get_injector,
            reset_injector,
        )

        assert all(
            [
                DependencyInjector,
                Capability,
                AgentRequirements,
                DependencyValidationResult,
                Conflict,
                DependencyManifest,
                get_injector,
                reset_injector,
            ]
        )

    def test_from_module(self):
        from core.execution_pkg.orchestration.dependency_injector import (
            Capability,
            DependencyInjector,
        )

        assert all(
            [
                DependencyInjector,
                Capability,
                AgentRequirements,
                ValidationResult,
                Conflict,
                DependencyManifest,
            ]
        )
