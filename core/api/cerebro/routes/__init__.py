"""
CEREBRO API routes package.

Routes:
- health: Health check endpoints (/health, /health/ready)
- stream: WebSocket streaming endpoint (/ws/stream)
- state: State snapshot for F5 recovery (/api/state/snapshot)
- interactions: Human-in-the-loop (/api/interactions/{id}/reply)
- workflow: Task execution control (/api/workflow/start)
- files: Secure file access (/api/files/content)
- auth: Authentication (/api/auth/login, /api/auth/me)
- memory: RAG memory management (/api/memory/*)
- timeline: Causality timeline (/api/timeline/{task_id})
- settings: Runtime/provider settings (/api/settings/providers)
"""

from . import auth, files, health, interactions, memory, settings, state, stream, timeline, workflow

__all__ = ["health", "stream", "state", "interactions", "workflow", "files", "auth", "memory", "timeline", "settings"]
