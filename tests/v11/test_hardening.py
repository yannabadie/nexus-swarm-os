"""
V11.3 HARDENING: Security Tests.

Tests for security hardening features:
1. JWT_SECRET from environment
2. CORS explicit origins
3. No hardcoded secrets

Author: Claude (NEXUS V11.3 HARDENING)
Date: 2025-12-15
"""

import os
from unittest.mock import patch

import pytest


class TestJWTSecurity:
    """Test suite for JWT secret handling."""

    def test_jwt_secret_from_env(self):
        """Verify JWT_SECRET is loaded from environment."""
        # Set environment variable
        test_secret = "test-secret-12345"
        with patch.dict(os.environ, {"NEXUS_JWT_SECRET": test_secret}):
            # Need to reload module to pick up new env
            import importlib

            from core.api.cerebro import middleware

            importlib.reload(middleware)

            assert test_secret == middleware.JWT_SECRET

    def test_jwt_secret_fallback_warning(self):
        """Verify fallback secret is used with warning when env not set."""
        # Clear the env var
        env = os.environ.copy()
        env.pop("NEXUS_JWT_SECRET", None)

        with patch.dict(os.environ, env, clear=True):
            import importlib

            from core.api.cerebro import middleware

            importlib.reload(middleware)

            # Should have fallback secret
            assert middleware.JWT_SECRET is not None
            assert "dev" in middleware.JWT_SECRET.lower() or "insecure" in middleware.JWT_SECRET.lower()

    def test_jwt_secret_not_hardcoded(self):
        """Verify no hardcoded production secrets in code."""
        # Read the source file
        import inspect

        from core.api.cerebro import middleware

        source = inspect.getsource(middleware)

        # Should not contain the old hardcoded secret
        assert "nexus-cerebro-dev-secret" not in source


class TestCORSSecurity:
    """Test suite for CORS configuration."""

    def test_cors_origins_from_env(self):
        """Verify CORS origins loaded from environment."""
        test_origins = "http://localhost:3000,https://example.com"

        with patch.dict(os.environ, {"NEXUS_CORS_ORIGINS": test_origins}):
            import importlib

            from core.api.cerebro import app

            importlib.reload(app)

            assert "http://localhost:3000" in app.CORS_ORIGINS
            assert "https://example.com" in app.CORS_ORIGINS

    def test_cors_default_localhost(self):
        """Verify default CORS allows localhost."""
        env = os.environ.copy()
        env.pop("NEXUS_CORS_ORIGINS", None)

        with patch.dict(os.environ, env, clear=True):
            import importlib

            from core.api.cerebro import app

            importlib.reload(app)

            # Should default to localhost
            assert "http://localhost:3000" in app.CORS_ORIGINS

    def test_cors_not_wildcard(self):
        """Verify CORS does not use wildcard origin."""
        import importlib

        from core.api.cerebro import app

        importlib.reload(app)

        # Should not contain wildcard
        assert "*" not in app.CORS_ORIGINS


class TestEnvExample:
    """Test suite for .env.example documentation."""

    def test_env_example_has_jwt_secret(self):
        """Verify .env.example documents JWT_SECRET."""
        from pathlib import Path

        env_example = Path("C:/Code/NEXUS/NEXUS-N7A/.env.example")
        if env_example.exists():
            content = env_example.read_text()
            assert "NEXUS_JWT_SECRET" in content

    def test_env_example_has_cors_origins(self):
        """Verify .env.example documents CORS_ORIGINS."""
        from pathlib import Path

        env_example = Path("C:/Code/NEXUS/NEXUS-N7A/.env.example")
        if env_example.exists():
            content = env_example.read_text()
            assert "NEXUS_CORS_ORIGINS" in content


# =============================================================================
# Run standalone
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
