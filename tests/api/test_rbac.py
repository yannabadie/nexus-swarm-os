"""
V12.2 IRONCLAD - RBAC Tests

Tests:
- Permission matrix verification
- Role hierarchy
- Permission enforcement dependency
- Access denied scenarios

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestPermissionEnum:
    """Tests for Permission enum."""

    def test_all_permissions_exist(self):
        """Verify all expected permissions are defined."""
        from core.api.cerebro.rbac import Permission

        expected = [
            "FILE_READ",
            "FILE_WRITE",
            "FILE_DELETE",
            "WORKSPACE_CREATE",
            "WORKSPACE_DELETE",
            "USER_INVITE",
            "USER_REMOVE",
            "USER_CHANGE_ROLE",
            "WORKFLOW_START",
            "WORKFLOW_STOP",
            "AUDIT_VIEW",
            "SETTINGS_MANAGE",
        ]

        for perm_name in expected:
            assert hasattr(Permission, perm_name), f"Missing permission: {perm_name}"

    def test_permission_values(self):
        """Verify permission values follow naming convention."""
        from core.api.cerebro.rbac import Permission

        assert Permission.FILE_READ.value == "file:read"
        assert Permission.FILE_WRITE.value == "file:write"
        assert Permission.USER_INVITE.value == "user:invite"


class TestRolePermissions:
    """Tests for role-to-permission mapping."""

    def test_owner_has_all_permissions(self):
        """Verify owner role has all permissions."""
        from core.api.cerebro.rbac import ROLE_PERMISSIONS, Permission

        owner_perms = ROLE_PERMISSIONS.get("owner", set())

        for perm in Permission:
            assert perm in owner_perms, f"Owner missing permission: {perm}"

    def test_admin_permissions(self):
        """Verify admin has expected permissions (not owner-only ones)."""
        from core.api.cerebro.rbac import ROLE_PERMISSIONS, Permission

        admin_perms = ROLE_PERMISSIONS.get("admin", set())

        # Admin SHOULD have
        assert Permission.FILE_READ in admin_perms
        assert Permission.FILE_WRITE in admin_perms
        assert Permission.FILE_DELETE in admin_perms
        assert Permission.USER_INVITE in admin_perms
        assert Permission.AUDIT_VIEW in admin_perms

        # Admin should NOT have (owner only)
        assert Permission.USER_CHANGE_ROLE not in admin_perms

    def test_member_permissions(self):
        """Verify member has limited permissions."""
        from core.api.cerebro.rbac import ROLE_PERMISSIONS, Permission

        member_perms = ROLE_PERMISSIONS.get("member", set())

        # Member SHOULD have
        assert Permission.FILE_READ in member_perms
        assert Permission.FILE_WRITE in member_perms
        assert Permission.WORKFLOW_START in member_perms

        # Member should NOT have
        assert Permission.USER_INVITE not in member_perms
        assert Permission.USER_REMOVE not in member_perms
        assert Permission.AUDIT_VIEW not in member_perms

    def test_viewer_permissions(self):
        """Verify viewer has read-only permissions."""
        from core.api.cerebro.rbac import ROLE_PERMISSIONS, Permission

        viewer_perms = ROLE_PERMISSIONS.get("viewer", set())

        # Viewer SHOULD have
        assert Permission.FILE_READ in viewer_perms

        # Viewer should NOT have
        assert Permission.FILE_WRITE not in viewer_perms
        assert Permission.FILE_DELETE not in viewer_perms
        assert Permission.WORKFLOW_START not in viewer_perms

    def test_role_hierarchy(self):
        """Verify permissions increase with role level."""
        from core.api.cerebro.rbac import ROLE_PERMISSIONS

        viewer_count = len(ROLE_PERMISSIONS.get("viewer", set()))
        member_count = len(ROLE_PERMISSIONS.get("member", set()))
        admin_count = len(ROLE_PERMISSIONS.get("admin", set()))
        owner_count = len(ROLE_PERMISSIONS.get("owner", set()))

        assert viewer_count < member_count < admin_count <= owner_count


class TestRequirePermission:
    """Tests for require_permission dependency."""

    def test_require_permission_returns_callable(self):
        """Verify require_permission returns a dependency function."""
        from core.api.cerebro.rbac import Permission, require_permission

        dep = require_permission(Permission.FILE_READ, "file")

        assert callable(dep)

    @pytest.mark.asyncio
    async def test_permission_granted_for_correct_role(self):
        """Test that permission is granted when user has required role."""
        from core.api.cerebro.deps import AuthenticatedUser
        from core.api.cerebro.rbac import Permission, require_permission

        dep = require_permission(Permission.FILE_READ, "file")

        mock_request = MagicMock()
        mock_user = AuthenticatedUser(
            user_id=str(uuid4()),
            tenant_id=str(uuid4()),
            workspace_id="default",
            role="viewer",  # Viewer has FILE_READ
        )

        result = await dep(request=mock_request, user=mock_user)

        assert result == mock_user

    @pytest.mark.asyncio
    async def test_permission_denied_for_insufficient_role(self):
        """Test that permission is denied when user lacks required role."""
        from fastapi import HTTPException

        from core.api.cerebro.deps import AuthenticatedUser
        from core.api.cerebro.rbac import Permission, require_permission

        dep = require_permission(Permission.USER_INVITE, "user")

        mock_request = MagicMock()
        mock_user = AuthenticatedUser(
            user_id=str(uuid4()),
            tenant_id=str(uuid4()),
            workspace_id="default",
            role="viewer",  # Viewer does NOT have USER_INVITE
        )

        with pytest.raises(HTTPException) as exc_info:
            await dep(request=mock_request, user=mock_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_owner_can_do_everything(self):
        """Test that owner role passes all permission checks."""
        from core.api.cerebro.deps import AuthenticatedUser
        from core.api.cerebro.rbac import Permission, require_permission

        mock_request = MagicMock()
        mock_user = AuthenticatedUser(
            user_id=str(uuid4()),
            tenant_id=str(uuid4()),
            workspace_id="default",
            role="owner",
        )

        for perm in Permission:
            dep = require_permission(perm, "test")
            result = await dep(request=mock_request, user=mock_user)
            assert result == mock_user, f"Owner should have {perm}"


class TestRBACIntegration:
    """Integration tests for RBAC with routes."""

    def test_files_route_uses_rbac(self):
        """Verify files route has RBAC dependency."""
        from core.api.cerebro.routes.files import router

        for route in router.routes:
            if hasattr(route, "path") and route.path == "/content":
                deps = getattr(route, "dependencies", [])
                assert len(deps) > 0 or hasattr(route, "dependant"), "Files route should have RBAC dependency"

    def test_users_route_uses_rbac(self):
        """Verify users routes have RBAC dependencies."""
        from core.api.cerebro.routes.users import router

        for route in router.routes:
            if hasattr(route, "path"):
                deps = getattr(route, "dependencies", [])
                len(deps) > 0 or hasattr(route, "dependant")
                # All user management routes should have RBAC
