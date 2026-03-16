"""
Runtime settings routes for CEREBRO.

Exposes the provider/runtime plan that the UI can render without leaking
secrets. This is the backend contract for the future provider settings flow.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core.config import Config
from core.version import NEXUS_CANONICAL_BRANCH, NEXUS_CODENAME, NEXUS_VERSION

from ..deps import AuthenticatedUser, require_auth

router = APIRouter()


@router.get("/providers")
async def get_provider_settings(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return the provider/runtime configuration snapshot for the authenticated workspace."""
    config = Config()
    return {
        "version": NEXUS_VERSION,
        "codename": NEXUS_CODENAME,
        "canonical_branch": NEXUS_CANONICAL_BRANCH,
        "driver_mode": config.driver_mode,
        "provider_snapshot": config.provider_snapshot,
        "security": {
            "sandbox_enabled": config.features.sandbox_enabled,
            "host_execution_allowed": config.features.host_execution_allowed,
        },
        "user_path": [
            "Select driver mode and preferred defaults.",
            "Connect provider API keys for SDK execution.",
            "Run runtime verification before enabling a provider in production.",
            "Review sandbox posture before enabling host execution.",
        ],
    }
