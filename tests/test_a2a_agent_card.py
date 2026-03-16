"""
Tests for V12.4 A2A Agent Card (Agent-to-Agent Protocol v0.3).

Validates:
- agent_card.json schema compliance with A2A v0.3 spec
- All required fields present
- Skill definitions complete
- Cerebro endpoint serves the card correctly
- Fallback behavior when card file is missing
"""

import json
from pathlib import Path

import pytest

# =============================================================================
# Agent Card JSON Schema Tests
# =============================================================================

AGENT_CARD_PATH = Path(__file__).parent.parent / "agent_card.json"


class TestAgentCardFile:
    """Test the static agent_card.json file."""

    def test_file_exists(self):
        """agent_card.json should exist at project root."""
        assert AGENT_CARD_PATH.exists(), f"Missing: {AGENT_CARD_PATH}"

    def test_valid_json(self):
        """File should be valid JSON."""
        data = json.loads(AGENT_CARD_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @pytest.fixture
    def card(self) -> dict:
        """Load agent card data."""
        return json.loads(AGENT_CARD_PATH.read_text(encoding="utf-8"))

    def test_protocol_version(self, card):
        """Should declare A2A protocol version 0.3.0."""
        assert card["protocolVersion"] == "0.3.0"

    def test_required_identity_fields(self, card):
        """Required identity fields must be present."""
        assert card["name"] == "NEXUS"
        assert len(card["description"]) > 20
        assert card["url"].startswith("http")
        assert card["version"] == "12.4.0"

    def test_capabilities_present(self, card):
        """Capabilities object must be present."""
        caps = card["capabilities"]
        assert isinstance(caps, dict)
        assert caps["streaming"] is True
        assert "stateTransitionHistory" in caps

    def test_capabilities_extensions(self, card):
        """Should declare NEXUS-specific extensions."""
        extensions = card["capabilities"].get("extensions", [])
        ext_uris = [e["uri"] for e in extensions]
        assert "urn:nexus:swarm-engine" in ext_uris
        assert "urn:nexus:evolution" in ext_uris
        assert "urn:nexus:mcp" in ext_uris

    def test_default_modes(self, card):
        """Default input/output modes must be declared."""
        assert "text/plain" in card["defaultInputModes"]
        assert "application/json" in card["defaultInputModes"]
        assert "text/plain" in card["defaultOutputModes"]
        assert "application/json" in card["defaultOutputModes"]

    def test_skills_present(self, card):
        """At least one skill must be defined."""
        assert len(card["skills"]) >= 1

    def test_skills_have_required_fields(self, card):
        """Every skill must have id, name, description, and tags."""
        for skill in card["skills"]:
            assert "id" in skill, f"Skill missing 'id': {skill.get('name', '?')}"
            assert "name" in skill, f"Skill missing 'name': {skill.get('id', '?')}"
            assert "description" in skill, f"Skill missing 'description': {skill['id']}"
            assert "tags" in skill, f"Skill missing 'tags': {skill['id']}"
            assert len(skill["tags"]) >= 1, f"Skill has no tags: {skill['id']}"

    def test_core_skills_defined(self, card):
        """Core NEXUS skills must be represented."""
        skill_ids = [s["id"] for s in card["skills"]]
        assert "collaborative-problem-solving" in skill_ids
        assert "agent-spawning" in skill_ids
        assert "code-execution" in skill_ids
        assert "rag-memory" in skill_ids

    def test_provider_info(self, card):
        """Provider organization should be set."""
        provider = card.get("provider")
        assert provider is not None
        assert "organization" in provider
        assert "url" in provider

    def test_security_schemes(self, card):
        """Should define authentication schemes."""
        schemes = card.get("securitySchemes", {})
        assert "bearer" in schemes or "apiKey" in schemes

    def test_additional_interfaces(self, card):
        """Should declare WebSocket interface."""
        interfaces = card.get("additionalInterfaces", [])
        transports = [i["transport"] for i in interfaces]
        assert "websocket" in transports

    def test_documentation_url(self, card):
        """Should provide documentation URL."""
        assert card.get("documentationUrl") is not None


class TestSkillDetails:
    """Test individual skill definitions for completeness."""

    @pytest.fixture
    def card(self) -> dict:
        return json.loads(AGENT_CARD_PATH.read_text(encoding="utf-8"))

    def _get_skill(self, card, skill_id: str) -> dict:
        for skill in card["skills"]:
            if skill["id"] == skill_id:
                return skill
        pytest.fail(f"Skill {skill_id} not found")

    def test_collab_skill_has_swarm_tags(self, card):
        """Collaboration skill should reference swarm modes."""
        skill = self._get_skill(card, "collaborative-problem-solving")
        assert "swarm" in skill["tags"]
        assert "orchestration" in skill["tags"]

    def test_collab_skill_has_examples(self, card):
        """Collaboration skill should have usage examples."""
        skill = self._get_skill(card, "collaborative-problem-solving")
        assert len(skill.get("examples", [])) >= 1

    def test_spawning_skill_tags(self, card):
        """Agent spawning skill should have evolution tags."""
        skill = self._get_skill(card, "agent-spawning")
        assert "evolution" in skill["tags"]
        assert "spawning" in skill["tags"]

    def test_code_execution_tags(self, card):
        """Code execution skill should mention sandbox."""
        skill = self._get_skill(card, "code-execution")
        assert "sandbox" in skill["tags"]

    def test_rag_memory_tags(self, card):
        """RAG memory skill should mention retrieval."""
        skill = self._get_skill(card, "rag-memory")
        assert "rag" in skill["tags"]
        assert "retrieval" in skill["tags"]


# =============================================================================
# A2A Route Tests
# =============================================================================


class TestA2ARoute:
    """Test the Cerebro A2A endpoint."""

    def test_route_module_loads(self):
        """A2A route module should import cleanly."""
        from core.api.cerebro.routes.a2a import router

        assert router is not None

    def test_load_agent_card_function(self):
        """_load_agent_card should return valid card data."""
        import core.api.cerebro.routes.a2a as a2a_module
        from core.api.cerebro.routes.a2a import _load_agent_card

        # Reset cache for test
        a2a_module._agent_card_cache = None

        card = _load_agent_card()
        assert isinstance(card, dict)
        assert card["name"] == "NEXUS"
        assert card["protocolVersion"] == "0.3.0"

        # Reset cache after test
        a2a_module._agent_card_cache = None

    def test_card_caching(self):
        """Agent card should be cached after first load."""
        import core.api.cerebro.routes.a2a as a2a_module

        # Reset cache
        a2a_module._agent_card_cache = None

        card1 = a2a_module._load_agent_card()
        card2 = a2a_module._load_agent_card()

        # Should be the same object (cached)
        assert card1 is card2

        # Reset cache after test
        a2a_module._agent_card_cache = None

    @pytest.mark.asyncio
    async def test_endpoint_returns_card(self):
        """GET /.well-known/agent.json should return the card."""
        import core.api.cerebro.routes.a2a as a2a_module
        from core.api.cerebro.routes.a2a import get_agent_card

        a2a_module._agent_card_cache = None

        response = await get_agent_card()
        assert response.status_code == 200
        assert response.media_type == "application/json"

        body = json.loads(response.body.decode())
        assert body["name"] == "NEXUS"

        a2a_module._agent_card_cache = None

    @pytest.mark.asyncio
    async def test_endpoint_cache_headers(self):
        """Response should include cache headers."""
        import core.api.cerebro.routes.a2a as a2a_module
        from core.api.cerebro.routes.a2a import get_agent_card

        a2a_module._agent_card_cache = None

        response = await get_agent_card()
        assert "Cache-Control" in response.headers
        assert "max-age" in response.headers["Cache-Control"]

        a2a_module._agent_card_cache = None


class TestA2AAppIntegration:
    """Test A2A route integration with Cerebro app."""

    def test_a2a_router_registered(self):
        """A2A router should be registered in the Cerebro app."""
        from core.api.cerebro.app import create_cerebro_app

        app = create_cerebro_app()

        routes = [route.path for route in app.routes]
        assert "/.well-known/agent.json" in routes
