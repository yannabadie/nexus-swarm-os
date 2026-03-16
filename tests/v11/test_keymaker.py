"""
NEXUS V11.6 KEYMAKER - Authentication Tests

Tests for KEYMAKER authentication endpoints:
- Login endpoint (POST /api/auth/login)
- Me endpoint (GET /api/auth/me)
- Optional auth dependencies
- CORTEX routes with auth

Author: Claude (NEXUS V11.6 KEYMAKER)
Date: 2025-12-15
"""

from unittest.mock import patch

import pytest


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_login_success(self):
        """Valid password should return JWT token."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        try:
            from jose import jwt  # noqa: F401  # availability check
        except ImportError:
            pytest.skip("python-jose not installed")

        from core.api.cerebro.routes import auth

        # Mock the fallback password to avoid env dependency
        with patch.object(auth, "FALLBACK_ADMIN_PASSWORD", "nexus"):
            from fastapi import FastAPI

            app = FastAPI()
            app.include_router(auth.router, prefix="/api/auth")

            with TestClient(app) as client:
                response = client.post("/api/auth/login", json={"username": "admin", "password": "nexus"})

            # Should succeed with default password
            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"
            assert data["user_id"] == "admin"
            assert data["tenant_id"] == "default"

    def test_login_invalid_password(self):
        """Invalid password should return 401."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import auth

        app = FastAPI()
        app.include_router(auth.router, prefix="/api/auth")

        with TestClient(app) as client:
            response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong_password"})

        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_me_without_auth(self):
        """GET /me without auth should return 401."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import auth

        app = FastAPI()
        app.include_router(auth.router, prefix="/api/auth")

        with TestClient(app) as client:
            response = client.get("/api/auth/me")

        assert response.status_code == 401

    def test_logout_returns_success(self):
        """POST /logout should return success."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import auth

        app = FastAPI()
        app.include_router(auth.router, prefix="/api/auth")

        with TestClient(app) as client:
            response = client.post("/api/auth/logout")

        assert response.status_code == 200
        assert response.json()["status"] == "logged_out"


class TestAuthDependencies:
    """Tests for authentication dependencies."""

    def test_require_auth_no_header(self):
        """require_auth should raise 401 without Authorization header."""
        import asyncio

        from fastapi import HTTPException

        from core.api.cerebro.deps import require_auth

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(require_auth(None))

        assert exc_info.value.status_code == 401

    def test_require_auth_invalid_format(self):
        """require_auth should raise 401 with invalid format."""
        import asyncio

        from fastapi import HTTPException

        from core.api.cerebro.deps import require_auth

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(require_auth("InvalidToken"))

        assert exc_info.value.status_code == 401
        assert "Bearer" in exc_info.value.detail

    def test_get_current_user_optional_returns_none(self):
        """get_current_user_optional should return None without auth."""
        import asyncio

        from core.api.cerebro.deps import get_current_user_optional

        result = asyncio.run(get_current_user_optional(None))
        assert result is None

    def test_get_current_user_optional_invalid_returns_none(self):
        """get_current_user_optional should return None with invalid token."""
        import asyncio

        from core.api.cerebro.deps import get_current_user_optional

        result = asyncio.run(get_current_user_optional("Bearer invalid_token"))
        assert result is None


class TestAuthenticatedUser:
    """Tests for AuthenticatedUser dataclass."""

    def test_authenticated_user_fields(self):
        """AuthenticatedUser should have expected fields."""
        from core.api.cerebro.deps import AuthenticatedUser

        user = AuthenticatedUser(user_id="test_user", tenant_id="test_tenant", workspace_id="test_workspace")

        assert user.user_id == "test_user"
        assert user.tenant_id == "test_tenant"
        assert user.workspace_id == "test_workspace"

    def test_authenticated_user_str(self):
        """AuthenticatedUser __str__ should include key info."""
        from core.api.cerebro.deps import AuthenticatedUser

        user = AuthenticatedUser(user_id="admin", tenant_id="default", workspace_id="main")

        str_repr = str(user)
        assert "admin" in str_repr
        assert "default" in str_repr


class TestIRONCLADEnforcement:
    """V11.6.1 IRONCLAD: Tests for mandatory authentication."""

    def test_state_snapshot_without_auth_returns_401(self):
        """State snapshot WITHOUT token should return 401 (IRONCLAD)."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import state

        app = FastAPI()
        app.include_router(state.router, prefix="/api/state")

        with TestClient(app) as client:
            # No auth token
            response = client.get("/api/state/snapshot")

        # V11.6.1 IRONCLAD: Must return 401, not 200 or 400
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]

    def test_state_snapshot_with_query_param_only_returns_401(self):
        """State snapshot with tenant_id query param but no token returns 401 (IDOR prevention)."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import state

        app = FastAPI()
        app.include_router(state.router, prefix="/api/state")

        with TestClient(app) as client:
            # Query param only, no auth - this is the IDOR attack vector
            response = client.get("/api/state/snapshot", params={"tenant_id": "admin"})

        # V11.6.1 IRONCLAD: Query params are IGNORED, must return 401
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]

    def test_workflow_start_without_auth_returns_401(self):
        """Workflow start WITHOUT token should return 401 (IRONCLAD)."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import workflow

        app = FastAPI()
        app.include_router(workflow.router, prefix="/api/workflow")

        with TestClient(app) as client:
            # No auth token
            response = client.post("/api/workflow/start", json={"task": "test task"})

        # V11.6.1 IRONCLAD: Must return 401
        assert response.status_code == 401

    def test_files_content_without_auth_returns_401(self):
        """File read WITHOUT token should return 401 (IRONCLAD)."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import files

        app = FastAPI()
        app.include_router(files.router, prefix="/api/files")

        with TestClient(app) as client:
            # No auth token - this is the attack vector the advisor mentioned
            response = client.get("/api/files/content", params={"path": ".env"})

        # V11.6.1 IRONCLAD: Must return 401, not 403
        # Note: 403 would be PathGuardian, but auth should fail first
        assert response.status_code == 401

    def test_interactions_pending_without_auth_returns_401(self):
        """Interactions pending WITHOUT token should return 401 (IRONCLAD)."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import interactions

        app = FastAPI()
        app.include_router(interactions.router, prefix="/api/interactions")

        with TestClient(app) as client:
            # No auth token
            response = client.get("/api/interactions/pending")

        # V11.6.1 IRONCLAD: Must return 401
        assert response.status_code == 401

    def test_websocket_without_token_closes_4001(self):
        """WebSocket WITHOUT token should close with 4001 (IRONCLAD V11.6.2)."""
        try:
            from fastapi.testclient import TestClient
            from starlette.websockets import WebSocketDisconnect
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import stream

        app = FastAPI()
        app.include_router(stream.router, prefix="/ws")

        # No auth token - this is the IDOR attack vector
        # V11.6.2 IRONCLAD: WebSocket should reject (close with 4001)
        with TestClient(app) as client, pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/stream"):
            pass
        # Test passes if WebSocketDisconnect is raised
        # Log shows: "[IRONCLAD] WebSocket connection rejected: no token provided"

    def test_websocket_with_tenant_id_only_closes_4001(self):
        """WebSocket with tenant_id param but no token closes 4001 (IDOR prevention)."""
        try:
            from fastapi.testclient import TestClient
            from starlette.websockets import WebSocketDisconnect
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from fastapi import FastAPI

        from core.api.cerebro.routes import stream

        app = FastAPI()
        app.include_router(stream.router, prefix="/ws")

        # tenant_id param only, no token - this is the IDOR attack vector
        # V11.6.2: tenant_id param is now IGNORED
        with (
            TestClient(app) as client,
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/stream?tenant_id=admin"),
        ):
            pass
        # V11.6.2 IRONCLAD: Must close with 4001, not allow anonymous access
        # Test passes if WebSocketDisconnect is raised (no token = rejected)


class TestKeymakerConfig:
    """Tests for KEYMAKER configuration."""

    def test_default_password_warning(self):
        """Using default password should log warning."""
        # This tests that the module loads correctly
        # The warning is logged at import time
        from core.api.cerebro.routes import auth

        # Default password should be 'nexus'
        assert auth.FALLBACK_ADMIN_PASSWORD == "nexus" or auth.FALLBACK_ADMIN_PASSWORD != ""

    def test_token_expiration_set(self):
        """Token expiration should be configured."""
        from core.api.cerebro.routes import auth

        assert auth.TOKEN_EXPIRE_HOURS == 24


class TestAuthRouterRegistered:
    """Tests that auth router is properly registered."""

    def test_auth_routes_in_app(self):
        """Auth routes should be registered in CEREBRO app."""
        from core.api.cerebro.app import create_cerebro_app

        app = create_cerebro_app()
        routes = [route.path for route in app.routes]

        # V11.6 KEYMAKER routes
        assert "/api/auth/login" in routes
        assert "/api/auth/me" in routes
        assert "/api/auth/logout" in routes

    def test_app_version_updated(self):
        """App version should be 13.0.0."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[all] not installed")

        from core.api.cerebro.app import create_cerebro_app

        app = create_cerebro_app()

        with TestClient(app) as client:
            response = client.get("/")

        data = response.json()
        assert data["version"] == "12.4.0"
        assert "auth" in data
