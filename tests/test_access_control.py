"""
Tests for V12.4 Access Control Manager.

Validates:
- Role to_dict
- AgentAccess to_dict
- AccessCheckResult to_dict
- AccessStats to_dict
- Role management (define, remove, permissions)
- Agent management (register, unregister, roles)
- Access checks (basic, role-based, extra grants, denials, admin)
- Effective permissions
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.security_pkg.security.access_control import (
    ADMIN_ROLE,
    AccessCheckResult,
    AccessControlManager,
    AccessStats,
    AgentAccess,
    Role,
    get_access_controller,
    reset_access_controller,
)

# =============================================================================
# Role Tests
# =============================================================================


class TestRole:
    """Test Role dataclass."""

    def test_basic(self):
        r = Role(name="analyst")
        assert r.name == "analyst"
        assert r.permissions == set()

    def test_with_permissions(self):
        r = Role(name="executor", permissions={"read", "write"})
        assert "read" in r.permissions
        assert "write" in r.permissions

    def test_to_dict(self):
        r = Role(name="analyst", permissions={"read", "search"}, description="Read-only")
        d = r.to_dict()
        assert d["name"] == "analyst"
        assert "read" in d["permissions"]
        assert d["description"] == "Read-only"


# =============================================================================
# AgentAccess Tests
# =============================================================================


class TestAgentAccess:
    """Test AgentAccess dataclass."""

    def test_basic(self):
        a = AgentAccess(agent_id="claude")
        assert a.agent_id == "claude"
        assert a.roles == set()

    def test_auto_timestamp(self):
        a = AgentAccess(agent_id="claude")
        assert a.created_at > 0

    def test_to_dict(self):
        a = AgentAccess(agent_id="claude", roles={"analyst"})
        d = a.to_dict()
        assert d["agent_id"] == "claude"
        assert "analyst" in d["roles"]


# =============================================================================
# AccessCheckResult Tests
# =============================================================================


class TestAccessCheckResult:
    """Test AccessCheckResult dataclass."""

    def test_allowed(self):
        r = AccessCheckResult(allowed=True, permission="read")
        assert r.allowed is True

    def test_denied(self):
        r = AccessCheckResult(allowed=False, reason="No permission")
        assert r.allowed is False

    def test_to_dict(self):
        r = AccessCheckResult(allowed=True, agent_id="claude", permission="read")
        d = r.to_dict()
        assert d["allowed"] is True
        assert d["agent_id"] == "claude"


# =============================================================================
# AccessStats Tests
# =============================================================================


class TestAccessStats:
    """Test AccessStats dataclass."""

    def test_to_dict(self):
        s = AccessStats(total_roles=2, total_agents=5, total_checks=100, total_allowed=80, total_denied=20)
        d = s.to_dict()
        assert d["total_roles"] == 2
        assert d["total_allowed"] == 80


# =============================================================================
# Role Management Tests
# =============================================================================


class TestRoleManagement:
    """Test role CRUD operations."""

    def test_define_role(self):
        ac = AccessControlManager()
        role = ac.define_role("analyst", permissions={"read", "search"})
        assert role.name == "analyst"
        assert ac.role_count == 1

    def test_define_role_update(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        ac.define_role("analyst", permissions={"read", "write"})
        role = ac.get_role("analyst")
        assert "write" in role.permissions

    def test_remove_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        assert ac.remove_role("analyst") is True
        assert ac.role_count == 0

    def test_remove_role_not_found(self):
        ac = AccessControlManager()
        assert ac.remove_role("missing") is False

    def test_remove_role_cascades_to_agents(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        ac.assign_role("claude", "analyst")
        ac.remove_role("analyst")
        agent = ac.get_agent("claude")
        assert "analyst" not in agent.roles

    def test_get_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        assert ac.get_role("analyst") is not None

    def test_get_role_not_found(self):
        ac = AccessControlManager()
        assert ac.get_role("missing") is None

    def test_list_roles(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        ac.define_role("executor")
        assert len(ac.list_roles()) == 2

    def test_add_permission_to_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        assert ac.add_permission_to_role("analyst", "search") is True
        assert "search" in ac.get_role("analyst").permissions

    def test_add_permission_role_not_found(self):
        ac = AccessControlManager()
        assert ac.add_permission_to_role("missing", "read") is False

    def test_remove_permission_from_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read", "search"})
        assert ac.remove_permission_from_role("analyst", "search") is True
        assert "search" not in ac.get_role("analyst").permissions

    def test_remove_permission_role_not_found(self):
        ac = AccessControlManager()
        assert ac.remove_permission_from_role("missing", "read") is False


# =============================================================================
# Agent Management Tests
# =============================================================================


class TestAgentManagement:
    """Test agent CRUD operations."""

    def test_register_agent(self):
        ac = AccessControlManager()
        agent = ac.register_agent("claude")
        assert agent.agent_id == "claude"
        assert ac.agent_count == 1

    def test_register_agent_idempotent(self):
        ac = AccessControlManager()
        a1 = ac.register_agent("claude")
        a2 = ac.register_agent("claude")
        assert a1 is a2
        assert ac.agent_count == 1

    def test_unregister_agent(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.unregister_agent("claude") is True
        assert ac.agent_count == 0

    def test_unregister_agent_not_found(self):
        ac = AccessControlManager()
        assert ac.unregister_agent("missing") is False

    def test_assign_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        assert ac.assign_role("claude", "analyst") is True
        agent = ac.get_agent("claude")
        assert "analyst" in agent.roles

    def test_assign_role_auto_registers(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        ac.assign_role("claude", "analyst")
        assert ac.agent_count == 1

    def test_assign_role_not_defined(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.assign_role("claude", "nonexistent") is False

    def test_revoke_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        ac.assign_role("claude", "analyst")
        assert ac.revoke_role("claude", "analyst") is True
        assert "analyst" not in ac.get_agent("claude").roles

    def test_revoke_role_not_assigned(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.revoke_role("claude", "analyst") is False

    def test_revoke_role_agent_not_found(self):
        ac = AccessControlManager()
        assert ac.revoke_role("missing", "analyst") is False

    def test_grant_permission(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.grant_permission("claude", "special_read") is True
        assert "special_read" in ac.get_agent("claude").extra_permissions

    def test_deny_permission(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.deny_permission("claude", "write") is True
        assert "write" in ac.get_agent("claude").denied_permissions


# =============================================================================
# Access Check Tests
# =============================================================================


class TestAccessChecks:
    """Test access checking."""

    def test_unregistered_agent_denied(self):
        ac = AccessControlManager()
        assert ac.is_allowed("unknown", "read") is False

    def test_no_permissions_denied(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.is_allowed("claude", "read") is False

    def test_role_permission_allowed(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read", "search"})
        ac.assign_role("claude", "analyst")
        assert ac.is_allowed("claude", "read") is True
        assert ac.is_allowed("claude", "search") is True
        assert ac.is_allowed("claude", "write") is False

    def test_extra_grant_allowed(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        ac.grant_permission("claude", "special")
        assert ac.is_allowed("claude", "special") is True

    def test_deny_overrides_role(self):
        ac = AccessControlManager()
        ac.define_role("executor", permissions={"read", "write", "execute"})
        ac.assign_role("claude", "executor")
        ac.deny_permission("claude", "execute")
        assert ac.is_allowed("claude", "read") is True
        assert ac.is_allowed("claude", "execute") is False

    def test_deny_overrides_extra_grant(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        ac.grant_permission("claude", "write")
        ac.deny_permission("claude", "write")
        assert ac.is_allowed("claude", "write") is False

    def test_admin_bypasses_all(self):
        ac = AccessControlManager()
        ac.define_role(ADMIN_ROLE)
        ac.assign_role("claude", ADMIN_ROLE)
        assert ac.is_allowed("claude", "anything") is True
        assert ac.is_allowed("claude", "super_secret") is True

    def test_admin_still_respects_deny(self):
        ac = AccessControlManager()
        ac.define_role(ADMIN_ROLE)
        ac.assign_role("claude", ADMIN_ROLE)
        ac.deny_permission("claude", "forbidden")
        assert ac.is_allowed("claude", "forbidden") is False

    def test_check_result_details(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        ac.assign_role("claude", "analyst")
        result = ac.check("claude", "read")
        assert result.allowed is True
        assert result.matched_role == "analyst"
        assert "Role" in result.reason

    def test_check_result_denied_details(self):
        ac = AccessControlManager()
        result = ac.check("unknown", "read")
        assert result.allowed is False
        assert "not registered" in result.reason

    def test_multiple_roles(self):
        ac = AccessControlManager()
        ac.define_role("reader", permissions={"read"})
        ac.define_role("writer", permissions={"write"})
        ac.assign_role("claude", "reader")
        ac.assign_role("claude", "writer")
        assert ac.is_allowed("claude", "read") is True
        assert ac.is_allowed("claude", "write") is True


# =============================================================================
# Effective Permissions Tests
# =============================================================================


class TestEffectivePermissions:
    """Test effective permissions calculation."""

    def test_empty(self):
        ac = AccessControlManager()
        ac.register_agent("claude")
        assert ac.get_effective_permissions("claude") == set()

    def test_from_role(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read", "search"})
        ac.assign_role("claude", "analyst")
        perms = ac.get_effective_permissions("claude")
        assert perms == {"read", "search"}

    def test_with_extras(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        ac.assign_role("claude", "analyst")
        ac.grant_permission("claude", "special")
        perms = ac.get_effective_permissions("claude")
        assert perms == {"read", "special"}

    def test_minus_denied(self):
        ac = AccessControlManager()
        ac.define_role("executor", permissions={"read", "write", "execute"})
        ac.assign_role("claude", "executor")
        ac.deny_permission("claude", "execute")
        perms = ac.get_effective_permissions("claude")
        assert perms == {"read", "write"}

    def test_admin_gets_wildcard(self):
        ac = AccessControlManager()
        ac.define_role(ADMIN_ROLE)
        ac.assign_role("claude", ADMIN_ROLE)
        perms = ac.get_effective_permissions("claude")
        assert "*" in perms

    def test_unknown_agent(self):
        ac = AccessControlManager()
        assert ac.get_effective_permissions("unknown") == set()


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test access control statistics."""

    def test_initial_stats(self):
        ac = AccessControlManager()
        stats = ac.get_stats()
        assert stats.total_checks == 0
        assert stats.total_allowed == 0

    def test_stats_after_checks(self):
        ac = AccessControlManager()
        ac.define_role("analyst", permissions={"read"})
        ac.assign_role("claude", "analyst")
        ac.is_allowed("claude", "read")  # Allowed
        ac.is_allowed("claude", "write")  # Denied
        ac.is_allowed("unknown", "read")  # Denied
        stats = ac.get_stats()
        assert stats.total_checks == 3
        assert stats.total_allowed == 1
        assert stats.total_denied == 2

    def test_stats_to_dict(self):
        ac = AccessControlManager()
        d = ac.get_stats().to_dict()
        assert "total_roles" in d
        assert "total_checks" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_role_count(self):
        ac = AccessControlManager()
        ac.define_role("a")
        ac.define_role("b")
        assert ac.role_count == 2

    def test_agent_count(self):
        ac = AccessControlManager()
        ac.register_agent("a")
        ac.register_agent("b")
        assert ac.agent_count == 2

    def test_clear(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        ac.register_agent("claude")
        ac.clear()
        assert ac.role_count == 0
        assert ac.agent_count == 0

    def test_to_dict(self):
        ac = AccessControlManager()
        ac.define_role("analyst")
        ac.register_agent("claude")
        d = ac.to_dict()
        assert d["role_count"] == 1
        assert d["agent_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global access controller."""

    def test_get(self):
        reset_access_controller()
        ac = get_access_controller()
        assert isinstance(ac, AccessControlManager)

    def test_singleton(self):
        reset_access_controller()
        a1 = get_access_controller()
        a2 = get_access_controller()
        assert a1 is a2

    def test_reset(self):
        reset_access_controller()
        a1 = get_access_controller()
        reset_access_controller()
        a2 = get_access_controller()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_security_package(self):
        from core.security_pkg.security import (
            AccessCheckResult,
            AccessControlManager,
            AccessStats,
            AgentAccess,
            Role,
            get_access_controller,
            reset_access_controller,
        )

        assert all(
            [
                AccessControlManager,
                Role,
                AgentAccess,
                AccessCheckResult,
                AccessStats,
                get_access_controller,
                reset_access_controller,
            ]
        )

    def test_from_module(self):
        from core.security_pkg.security.access_control import (
            ADMIN_ROLE,
            DEFAULT_ROLE,
        )

        assert ADMIN_ROLE == "admin"
        assert DEFAULT_ROLE == "default"
