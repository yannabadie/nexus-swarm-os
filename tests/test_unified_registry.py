"""
Tests for V8.4.0 UnifiedAgentRegistry

Tests the centralized agent management system that replaces
hardcoded if/else chains throughout the codebase.
"""

from pathlib import Path

from core.foundation.agents.unified_registry import (
    AgentCapability,
    AgentDescriptor,
    AgentProvider,
    UnifiedAgentRegistry,
    get_registry,
    reset_registry,
)


class TestAgentDescriptor:
    """Test AgentDescriptor dataclass"""

    def test_create_builtin_agent(self):
        """Should create a builtin agent descriptor"""
        agent = AgentDescriptor(
            id="gemini",
            provider=AgentProvider.GEMINI,
            display_name="Gemini",
            capabilities=[AgentCapability.RESEARCH],
        )
        assert agent.id == "gemini"
        assert agent.provider == AgentProvider.GEMINI
        assert agent.is_builtin is True
        assert agent.is_available is True

    def test_create_spawned_agent(self):
        """Should create a spawned agent descriptor"""
        agent = AgentDescriptor(
            id="security_expert",
            provider=AgentProvider.SPAWNED,
            display_name="Security Expert",
            capabilities=[AgentCapability.ANALYSIS],
            config_path=Path("workspace/agents/security_expert.yaml"),
        )
        assert agent.is_builtin is False
        assert agent.config_path is not None

    def test_dylan_scores_default_empty(self):
        """DyLAN scores should default to empty dict"""
        agent = AgentDescriptor(
            id="test",
            provider=AgentProvider.GEMINI,
            display_name="Test",
        )
        assert agent.dylan_scores == {}


class TestUnifiedAgentRegistry:
    """Test UnifiedAgentRegistry class"""

    def test_builtins_pre_registered(self):
        """Gemini and Claude should be pre-registered"""
        registry = UnifiedAgentRegistry()

        gemini = registry.get("gemini")
        claude = registry.get("claude")

        assert gemini is not None
        assert gemini.id == "gemini"
        assert gemini.provider == AgentProvider.GEMINI

        assert claude is not None
        assert claude.id == "claude"
        assert claude.provider == AgentProvider.CLAUDE

    def test_case_insensitive_lookup(self):
        """Should handle case variations via aliases"""
        registry = UnifiedAgentRegistry()

        # All these should resolve to same agent
        assert registry.get("gemini").id == "gemini"
        assert registry.get("Gemini").id == "gemini"
        assert registry.get("GEMINI").id == "gemini"

        assert registry.get("claude").id == "claude"
        assert registry.get("Claude").id == "claude"
        assert registry.get("CLAUDE").id == "claude"

    def test_get_nonexistent_returns_none(self):
        """Should return None for unknown agents"""
        registry = UnifiedAgentRegistry()
        assert registry.get("unknown_agent") is None

    def test_get_display_name(self):
        """Should return human-readable display names"""
        registry = UnifiedAgentRegistry()

        assert registry.get_display_name("gemini") == "Gemini"
        assert registry.get_display_name("claude") == "Claude"
        # Unknown agents get titlecased ID
        assert registry.get_display_name("unknown_agent") == "Unknown_Agent"

    def test_get_alternate_builtins(self):
        """Should return the other builtin agent"""
        registry = UnifiedAgentRegistry()

        assert registry.get_alternate("gemini") == "claude"
        assert registry.get_alternate("Gemini") == "claude"
        assert registry.get_alternate("claude") == "gemini"
        assert registry.get_alternate("Claude") == "gemini"

    def test_get_alternate_spawned_returns_none(self):
        """Spawned agents don't have a default alternate"""
        registry = UnifiedAgentRegistry()
        registry.register(
            AgentDescriptor(
                id="expert",
                provider=AgentProvider.SPAWNED,
                display_name="Expert",
            )
        )

        assert registry.get_alternate("expert") is None

    def test_is_gemini(self):
        """Should correctly identify Gemini provider"""
        registry = UnifiedAgentRegistry()

        assert registry.is_gemini("gemini") is True
        assert registry.is_gemini("Gemini") is True
        assert registry.is_gemini("claude") is False
        assert registry.is_gemini("unknown") is False

    def test_is_claude(self):
        """Should correctly identify Claude provider"""
        registry = UnifiedAgentRegistry()

        assert registry.is_claude("claude") is True
        assert registry.is_claude("Claude") is True
        assert registry.is_claude("gemini") is False
        assert registry.is_claude("unknown") is False

    def test_is_builtin(self):
        """Should identify builtin vs spawned agents"""
        registry = UnifiedAgentRegistry()

        assert registry.is_builtin("gemini") is True
        assert registry.is_builtin("claude") is True

        registry.register(
            AgentDescriptor(
                id="spawned_agent",
                provider=AgentProvider.SPAWNED,
                display_name="Spawned",
            )
        )
        assert registry.is_builtin("spawned_agent") is False

    def test_register_spawned_agent(self):
        """Should register custom spawned agents"""
        registry = UnifiedAgentRegistry()

        spawned = AgentDescriptor(
            id="security_expert",
            provider=AgentProvider.SPAWNED,
            display_name="Security Expert",
            capabilities=[AgentCapability.ANALYSIS, AgentCapability.CODING],
        )
        registry.register(spawned)

        agent = registry.get("security_expert")
        assert agent is not None
        assert agent.display_name == "Security Expert"
        assert agent.is_builtin is False

        # Should also be accessible via display name alias
        assert registry.get("Security Expert") is not None

    def test_unregister_agent(self):
        """Should remove agents from registry"""
        registry = UnifiedAgentRegistry()

        registry.register(
            AgentDescriptor(
                id="temp_agent",
                provider=AgentProvider.SPAWNED,
                display_name="Temp",
            )
        )

        assert registry.get("temp_agent") is not None
        assert registry.unregister("temp_agent") is True
        assert registry.get("temp_agent") is None
        assert registry.unregister("temp_agent") is False  # Already removed

    def test_list_available(self):
        """Should list all available agents"""
        registry = UnifiedAgentRegistry()

        available = registry.list_available()
        assert len(available) == 2  # Gemini + Claude

        # Add unavailable agent
        registry.register(
            AgentDescriptor(
                id="offline",
                provider=AgentProvider.OLLAMA,
                display_name="Offline",
                is_available=False,
            )
        )

        available = registry.list_available()
        assert len(available) == 2  # Still only 2

    def test_list_builtins(self):
        """Should list only builtin agents"""
        registry = UnifiedAgentRegistry()

        registry.register(
            AgentDescriptor(
                id="spawned",
                provider=AgentProvider.SPAWNED,
                display_name="Spawned",
            )
        )

        builtins = registry.list_builtins()
        assert len(builtins) == 2
        assert all(a.is_builtin for a in builtins)

    def test_list_spawned(self):
        """Should list only spawned agents"""
        registry = UnifiedAgentRegistry()

        assert len(registry.list_spawned()) == 0

        registry.register(
            AgentDescriptor(
                id="spawned1",
                provider=AgentProvider.SPAWNED,
                display_name="Spawned 1",
            )
        )
        registry.register(
            AgentDescriptor(
                id="spawned2",
                provider=AgentProvider.SPAWNED,
                display_name="Spawned 2",
            )
        )

        spawned = registry.list_spawned()
        assert len(spawned) == 2

    def test_contains(self):
        """Should support 'in' operator"""
        registry = UnifiedAgentRegistry()

        assert "gemini" in registry
        assert "claude" in registry
        assert "unknown" not in registry

    def test_len(self):
        """Should return number of registered agents"""
        registry = UnifiedAgentRegistry()

        assert len(registry) == 2  # Gemini + Claude

        registry.register(
            AgentDescriptor(
                id="new",
                provider=AgentProvider.SPAWNED,
                display_name="New",
            )
        )
        assert len(registry) == 3


class TestDriverRegistration:
    """Test driver registration and retrieval"""

    def test_register_and_get_driver(self):
        """Should register and retrieve drivers"""
        registry = UnifiedAgentRegistry()

        # Create mock driver
        class MockDriver:
            async def invoke(self, prompt: str, **kwargs) -> str:
                return f"Response to: {prompt}"

        driver = MockDriver()
        registry.register_driver("gemini", driver)

        retrieved = registry.get_driver("gemini")
        assert retrieved is driver

    def test_get_driver_nonexistent(self):
        """Should return None for unregistered drivers"""
        registry = UnifiedAgentRegistry()
        assert registry.get_driver("gemini") is None

    def test_driver_removed_on_unregister(self):
        """Driver should be removed when agent is unregistered"""
        registry = UnifiedAgentRegistry()

        class MockDriver:
            async def invoke(self, prompt: str, **kwargs) -> str:
                return ""

        registry.register(
            AgentDescriptor(
                id="temp",
                provider=AgentProvider.SPAWNED,
                display_name="Temp",
            )
        )
        registry.register_driver("temp", MockDriver())

        assert registry.get_driver("temp") is not None
        registry.unregister("temp")
        assert registry.get_driver("temp") is None


class TestCapabilitySelection:
    """Test capability-based agent selection"""

    def test_select_for_capability_basic(self):
        """Should select agent with matching capability"""
        registry = UnifiedAgentRegistry()

        # Claude has CODING capability by default
        best = registry.select_for_capability(AgentCapability.CODING)
        assert best is not None
        assert AgentCapability.CODING in best.capabilities

    def test_select_for_capability_with_dylan_scores(self):
        """Should prefer higher DyLAN scores"""
        registry = UnifiedAgentRegistry()

        # Give Claude high coding score, Gemini low
        registry.update_dylan_score("claude", "coding", 0.9)
        registry.update_dylan_score("gemini", "coding", 0.3)

        # Add coding to gemini capabilities for this test
        gemini = registry.get("gemini")
        gemini.capabilities.append(AgentCapability.CODING)

        best = registry.select_for_capability(AgentCapability.CODING)
        assert best.id == "claude"

    def test_select_for_capability_with_exclusion(self):
        """Should exclude specified agents"""
        registry = UnifiedAgentRegistry()

        # Add RESEARCH to Claude for this test
        claude = registry.get("claude")
        claude.capabilities.append(AgentCapability.RESEARCH)

        # Exclude Gemini
        best = registry.select_for_capability(AgentCapability.RESEARCH, exclude=["gemini"])
        assert best.id == "claude"

    def test_select_for_capability_no_match(self):
        """Should return None if no agent matches"""
        registry = UnifiedAgentRegistry()

        # No agents have a fictional capability
        # Use a capability that no default agent has
        registry.get("gemini").capabilities = []
        registry.get("claude").capabilities = []

        best = registry.select_for_capability(AgentCapability.CREATIVE)
        assert best is None

    def test_update_dylan_score(self):
        """Should update DyLAN scores"""
        registry = UnifiedAgentRegistry()

        assert registry.update_dylan_score("gemini", "research", 0.85) is True

        gemini = registry.get("gemini")
        assert gemini.dylan_scores["research"] == 0.85

    def test_update_dylan_score_clamped(self):
        """Should clamp scores to 0.0-1.0"""
        registry = UnifiedAgentRegistry()

        registry.update_dylan_score("gemini", "test", 1.5)
        assert registry.get("gemini").dylan_scores["test"] == 1.0

        registry.update_dylan_score("gemini", "test", -0.5)
        assert registry.get("gemini").dylan_scores["test"] == 0.0

    def test_update_dylan_score_nonexistent(self):
        """Should return False for nonexistent agent"""
        registry = UnifiedAgentRegistry()
        assert registry.update_dylan_score("unknown", "test", 0.5) is False


class TestGlobalSingleton:
    """Test global registry singleton"""

    def test_get_registry_returns_singleton(self):
        """get_registry should return same instance"""
        reset_registry()

        r1 = get_registry()
        r2 = get_registry()

        assert r1 is r2

    def test_reset_registry(self):
        """reset_registry should create new instance"""
        r1 = get_registry()
        reset_registry()
        r2 = get_registry()

        assert r1 is not r2

    def test_singleton_persists_changes(self):
        """Changes to singleton should persist"""
        reset_registry()

        registry = get_registry()
        registry.register(
            AgentDescriptor(
                id="persistent",
                provider=AgentProvider.SPAWNED,
                display_name="Persistent",
            )
        )

        # Get again and verify
        registry2 = get_registry()
        assert registry2.get("persistent") is not None


class TestAgentProvider:
    """Test AgentProvider enum"""

    def test_provider_values(self):
        """Each provider should have correct value"""
        assert AgentProvider.GEMINI.value == "gemini"
        assert AgentProvider.CLAUDE.value == "claude"
        assert AgentProvider.OPENAI.value == "openai"
        assert AgentProvider.DEEPSEEK.value == "deepseek"
        assert AgentProvider.KIMI.value == "kimi"
        assert AgentProvider.MINIMAX.value == "minimax"
        assert AgentProvider.OLLAMA.value == "ollama"
        assert AgentProvider.SPAWNED.value == "spawned"

    def test_provider_count(self):
        """Should have 8 providers (7 backends + spawned)"""
        assert len(list(AgentProvider)) == 8


class TestAgentCapability:
    """Test AgentCapability enum"""

    def test_capability_values(self):
        """Each capability should have correct value"""
        assert AgentCapability.CODING.value == "coding"
        assert AgentCapability.RESEARCH.value == "research"
        assert AgentCapability.CREATIVE.value == "creative"
        assert AgentCapability.ANALYSIS.value == "analysis"
        assert AgentCapability.GENERAL.value == "general"

    def test_capability_count(self):
        """Should have 5 capabilities"""
        assert len(list(AgentCapability)) == 5
