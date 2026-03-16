"""
NEXUS V8.0 - Agent Registry

Anti-duplication registry with semantic similarity search.
Prevents spawning duplicate agents by checking if similar agents already exist.

Usage:
    registry = AgentRegistry(workspace_path)

    # Check before spawning
    similar = registry.find_similar(["pdf_parsing", "ocr"])
    if similar:
        use(similar)
    else:
        spawn_new()

    # Register new agent
    registry.register_spawn(new_agent)
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RegisteredAgent:
    """An agent registered in the registry."""

    agent_id: str
    role: str
    capabilities: list[str]
    mission: str
    created_at: str
    last_used: str
    use_count: int = 0
    success_rate: float = 1.0
    is_active: bool = True
    source: str = "spawned"  # "spawned", "builtin", "merged"


class AgentRegistry:
    """
    Registry of agents with similarity search to prevent duplicates.

    Thread-safe for concurrent access.
    """

    REGISTRY_FILE = "agent_registry.json"
    SIMILARITY_THRESHOLD = 0.8  # 80% capability overlap = similar

    def __init__(self, workspace_path: Path):
        """
        Initialize registry.

        Args:
            workspace_path: Path to NEXUS workspace
        """
        self.workspace_path = Path(workspace_path)
        self.registry_path = self.workspace_path / ".nexus" / self.REGISTRY_FILE
        self._lock = threading.Lock()
        self._agents: dict[str, RegisteredAgent] = {}
        self._load_registry()

    def _load_registry(self):
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                data = json.loads(self.registry_path.read_text(encoding="utf-8"))
                for agent_id, agent_data in data.get("agents", {}).items():
                    self._agents[agent_id] = RegisteredAgent(**agent_data)
                logger.info(f"Loaded {len(self._agents)} agents from registry")
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}")
                self._agents = {}
        else:
            self._agents = {}
            # Register builtin agents
            self._register_builtin_agents()

    def _save_registry(self):
        """Save registry to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "8.0",
            "updated_at": datetime.now().isoformat(),
            "agents": {agent_id: asdict(agent) for agent_id, agent in self._agents.items()},
        }
        self.registry_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _register_builtin_agents(self):
        """Register builtin agents (Gemini, Claude)."""
        builtins = [
            RegisteredAgent(
                agent_id="gemini",
                role="general",
                capabilities=["coding", "research", "analysis", "creative", "web"],
                mission="General-purpose AI assistant (Google)",
                created_at=datetime.now().isoformat(),
                last_used=datetime.now().isoformat(),
                source="builtin",
            ),
            RegisteredAgent(
                agent_id="claude",
                role="general",
                capabilities=["coding", "research", "analysis", "creative", "security"],
                mission="General-purpose AI assistant (Anthropic)",
                created_at=datetime.now().isoformat(),
                last_used=datetime.now().isoformat(),
                source="builtin",
            ),
        ]
        for agent in builtins:
            self._agents[agent.agent_id] = agent

    def find_similar(self, required_capabilities: list[str], threshold: float = None) -> RegisteredAgent | None:
        """
        Find an existing agent with similar capabilities.

        Args:
            required_capabilities: Capabilities needed
            threshold: Similarity threshold (default: 0.8)

        Returns:
            RegisteredAgent if found, None otherwise
        """
        threshold = threshold or self.SIMILARITY_THRESHOLD

        with self._lock:
            best_match = None
            best_score = 0.0

            required_set = set(c.lower() for c in required_capabilities)

            for agent in self._agents.values():
                if not agent.is_active:
                    continue

                agent_caps = set(c.lower() for c in agent.capabilities)
                similarity = self._jaccard_similarity(required_set, agent_caps)

                if similarity >= threshold and similarity > best_score:
                    best_match = agent
                    best_score = similarity

            if best_match:
                logger.info(f"Found similar agent: {best_match.agent_id} (similarity: {best_score:.2f})")

            return best_match

    def _jaccard_similarity(self, set1: set[str], set2: set[str]) -> float:
        """Calculate Jaccard similarity between two sets."""
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union

    def register_spawn(self, agent_id: str, role: str, capabilities: list[str], mission: str) -> bool:
        """
        Register a newly spawned agent.

        Args:
            agent_id: Unique agent identifier
            role: Agent's role
            capabilities: List of capabilities
            mission: Agent's mission statement

        Returns:
            True if registered, False if duplicate detected
        """
        with self._lock:
            # Check for exact duplicate
            if agent_id in self._agents:
                logger.warning(f"Agent {agent_id} already exists in registry")
                return False

            # Check for similar agent
            similar = self.find_similar(capabilities)
            if similar and similar.agent_id != agent_id:
                logger.warning(
                    f"Similar agent exists: {similar.agent_id}. Consider using existing agent instead of spawning."
                )
                # Still allow registration, but log warning

            # Register
            agent = RegisteredAgent(
                agent_id=agent_id,
                role=role,
                capabilities=capabilities,
                mission=mission,
                created_at=datetime.now().isoformat(),
                last_used=datetime.now().isoformat(),
                use_count=0,
                source="spawned",
            )
            self._agents[agent_id] = agent
            self._save_registry()

            logger.info(f"Registered new agent: {agent_id}")
            return True

    def record_usage(self, agent_id: str, success: bool = True):
        """
        Record that an agent was used.

        Args:
            agent_id: Agent identifier
            success: Whether the usage was successful
        """
        with self._lock:
            if agent_id not in self._agents:
                return

            agent = self._agents[agent_id]
            agent.last_used = datetime.now().isoformat()
            agent.use_count += 1

            # Update success rate (rolling average)
            old_rate = agent.success_rate
            agent.success_rate = (old_rate * (agent.use_count - 1) + (1.0 if success else 0.0)) / agent.use_count

            self._save_registry()

    def deactivate_agent(self, agent_id: str, reason: str = ""):
        """
        Deactivate an agent (soft delete).

        Args:
            agent_id: Agent to deactivate
            reason: Reason for deactivation
        """
        with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].is_active = False
                self._save_registry()
                logger.info(f"Deactivated agent {agent_id}: {reason}")

    def merge_agents(self, source_id: str, target_id: str, new_capabilities: list[str] = None) -> bool:
        """
        Merge source agent into target agent.

        Args:
            source_id: Agent to merge from (will be deactivated)
            target_id: Agent to merge into
            new_capabilities: Additional capabilities to add

        Returns:
            True if merged successfully
        """
        with self._lock:
            if source_id not in self._agents or target_id not in self._agents:
                return False

            source = self._agents[source_id]
            target = self._agents[target_id]

            # Merge capabilities
            merged_caps = set(target.capabilities)
            merged_caps.update(source.capabilities)
            if new_capabilities:
                merged_caps.update(new_capabilities)

            target.capabilities = list(merged_caps)

            # Deactivate source
            source.is_active = False

            self._save_registry()
            logger.info(f"Merged {source_id} into {target_id}")
            return True

    def get_agent(self, agent_id: str) -> RegisteredAgent | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)

    def get_active_agents(self) -> list[RegisteredAgent]:
        """Get all active agents."""
        return [a for a in self._agents.values() if a.is_active]

    def get_spawned_agents(self) -> list[RegisteredAgent]:
        """Get all spawned (non-builtin) agents."""
        return [a for a in self._agents.values() if a.is_active and a.source == "spawned"]

    def get_agents_by_capability(self, capability: str) -> list[RegisteredAgent]:
        """Get agents that have a specific capability."""
        capability_lower = capability.lower()
        return [
            a for a in self._agents.values() if a.is_active and capability_lower in [c.lower() for c in a.capabilities]
        ]

    def get_stats(self) -> dict:
        """Get registry statistics."""
        active = [a for a in self._agents.values() if a.is_active]
        spawned = [a for a in active if a.source == "spawned"]

        return {
            "total_agents": len(self._agents),
            "active_agents": len(active),
            "spawned_agents": len(spawned),
            "builtin_agents": len(active) - len(spawned),
            "total_capabilities": len(set(c.lower() for a in active for c in a.capabilities)),
        }
