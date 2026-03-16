"""
NEXUS V12.4 COGNITIVE BOOST - A2A Agent Card Endpoint

Serves the A2A v0.3 Agent Card at /.well-known/agent.json for
agent-to-agent protocol discoverability.

The Agent Card is loaded from agent_card.json at the project root
and enriched with runtime information (available agents, version).

Spec: https://a2a-protocol.org/v0.3.0/specification/
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache the agent card in memory after first load
_agent_card_cache: dict[str, Any] | None = None


def _load_agent_card() -> dict[str, Any]:
    """Load and cache the agent card from disk."""
    global _agent_card_cache

    if _agent_card_cache is not None:
        return _agent_card_cache

    # Search upward from this file to find agent_card.json at project root
    card_path = Path(__file__).resolve().parents[4] / "agent_card.json"

    if not card_path.exists():
        logger.warning(f"agent_card.json not found at {card_path}")
        return {
            "protocolVersion": "0.3.0",
            "name": "NEXUS",
            "description": "Multi-Agent Collaborative Intelligence Orchestrator",
            "url": "http://localhost:8080",
            "version": "12.4.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }

    try:
        card_data = json.loads(card_path.read_text(encoding="utf-8"))
        _agent_card_cache = card_data
        logger.info("A2A Agent Card loaded successfully")
        return card_data
    except Exception as e:
        logger.error(f"Failed to load agent_card.json: {e}")
        return {"error": f"Failed to load agent card: {e}"}


@router.get(
    "/agent.json",
    response_class=JSONResponse,
    summary="A2A Agent Card",
    description="Returns the NEXUS Agent Card per A2A Protocol v0.3.0 specification.",
)
async def get_agent_card() -> JSONResponse:
    """Serve the A2A Agent Card for protocol discoverability."""
    card = _load_agent_card()
    return JSONResponse(
        content=card,
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )
