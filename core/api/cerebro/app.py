"""
CEREBRO FastAPI application factory.

Creates the API surface used by NEXUS for:
- Redis connection lifecycle management
- Tenant context middleware
- WebSocket streaming
- Workflow, memory, files, and settings APIs
- Authentication, RBAC, and rate limiting

Usage:
    uvicorn core.api.cerebro.app:create_cerebro_app --factory --port 8080
"""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    raise ImportError("CEREBRO API requires FastAPI. Install with: pip install nexus-swarm-os[api]") from None


from core.observability.events.redis_bus import get_redis_bus
from core.version import NEXUS_CODENAME, NEXUS_VERSION

logger = logging.getLogger(__name__)

# V11.3 HARDENING: CORS origins from environment (comma-separated)
# Example: NEXUS_CORS_ORIGINS=http://localhost:3000,https://nexus.example.com
_cors_env = os.environ.get("NEXUS_CORS_ORIGINS", "http://localhost:3000")
CORS_ORIGINS: list[str] = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

if not CORS_ORIGINS:
    CORS_ORIGINS = ["http://localhost:3000"]
    logger.warning("NEXUS_CORS_ORIGINS not set, defaulting to localhost:3000")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan: startup and shutdown events.

    Startup:
    - Connect to Redis
    - V12.0: Register main event loop for in-memory pub/sub

    Shutdown:
    - Disconnect from Redis
    """
    import asyncio

    # Startup
    logger.info("CEREBRO API: Starting up...")
    bus = get_redis_bus()

    # V12.0: Register main event loop for thread-safe in-memory pub/sub
    main_loop = asyncio.get_running_loop()
    bus.set_main_loop(main_loop)

    connected = await bus.connect()
    if connected:
        logger.info("CEREBRO API: Redis connected")
    else:
        logger.warning("CEREBRO API: Redis not available, running in degraded mode")

    yield  # Application runs here

    # Shutdown
    logger.info("CEREBRO API: Shutting down...")
    await bus.disconnect()
    logger.info("CEREBRO API: Redis disconnected")


def create_cerebro_app() -> FastAPI:
    """
    Create the CEREBRO FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="NEXUS CEREBRO API",
        description=f"Real-time event streaming API for NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME}",
        version=NEXUS_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # V11.3 HARDENING: CORS with explicit origins (not wildcard)
    # Note: allow_credentials=True requires explicit origins, not ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-ID"],
    )

    # Tenant context middleware (HTTP only, not WebSocket)
    from .middleware import TenantContextMiddleware

    app.add_middleware(TenantContextMiddleware)

    # V12.1 RETINA: Rate limiting middleware (Conseiller 1 feedback)
    from .rate_limit import setup_rate_limiting

    setup_rate_limiting(app)

    # Include routers
    from .routes import health, stream

    # Core routers (V10)
    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(stream.router, prefix="/ws", tags=["websocket"])

    # V11.5 CORTEX routers
    from .routes import files, interactions, state, workflow

    app.include_router(state.router, prefix="/api/state", tags=["state"])
    app.include_router(interactions.router, prefix="/api/interactions", tags=["interactions"])
    app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
    app.include_router(files.router, prefix="/api/files", tags=["files"])

    # V11.6 KEYMAKER routers
    from .routes import auth

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

    # V12.2 IRONCLAD routers
    from .routes import users

    app.include_router(users.router, prefix="/api/users", tags=["users"])

    # V13.0 MEMORIA UNIVERSALIS routers
    from .routes import memory

    app.include_router(memory.router, prefix="/api/memory", tags=["memory"])

    # V12.4 P2.1: Causality Timeline (observability)
    from .routes import timeline

    app.include_router(timeline.router, prefix="/api/timeline", tags=["timeline"])

    from .routes import settings

    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])

    # V12.4 A2A Protocol: Agent Card endpoint
    from .routes import a2a

    app.include_router(a2a.router, prefix="/.well-known", tags=["a2a"])

    # Root endpoint
    @app.get("/", tags=["root"])
    async def root():
        """Root endpoint with API info."""
        return {
            "service": "NEXUS CEREBRO API",
            "version": NEXUS_VERSION,
            "codename": NEXUS_CODENAME,
            "docs": "/docs",
            "health": "/health",
            "websocket": "/ws/stream",
            # V11.5 CORTEX endpoints
            "state": "/api/state/snapshot",
            "interactions": "/api/interactions/pending",
            "workflow": "/api/workflow/start",
            "files": "/api/files/content",
            # V11.6 KEYMAKER endpoints
            "auth": "/api/auth/login",
            "auth_refresh": "/api/auth/refresh",
            # V12.2 IRONCLAD endpoints
            "users": "/api/users",
            "users_invite": "/api/users/invite",
            # V13.0 MEMORIA UNIVERSALIS endpoints
            "memory": "/api/memory/stats",
            "memory_namespaces": "/api/memory/namespaces",
            "memory_ingest": "/api/memory/ingest",
            # V12.4 P2.1: Causality Timeline
            "timeline": "/api/timeline/{task_id}",
            "timeline_summary": "/api/timeline/{task_id}/summary",
            "settings_providers": "/api/settings/providers",
            # V12.4 A2A Protocol
            "agent_card": "/.well-known/agent.json",
        }

    return app


# For uvicorn direct usage
app = create_cerebro_app()
