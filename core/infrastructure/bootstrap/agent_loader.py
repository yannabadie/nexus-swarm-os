"""
Spawned Agent Loader - NEXUS V7.5 HIVE MIND

Discovers and loads spawned agents from workspace/agents/ at startup.
Integrates them into the AgentPool for use by Hybrid Swarm Engine.

Usage:
    from core.infrastructure.bootstrap.agent_loader import SpawnedAgentLoader

    loader = SpawnedAgentLoader(workspace_path)
    agents = loader.discover_spawned_agents()

    for profile in agents:
        agent_pool.register(profile)
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Import AgentProfile from agent_metrics
from core.intelligence.swarm.agent_metrics import AgentProfile

if TYPE_CHECKING:
    from core.intelligence.swarm.agent_metrics import AgentPool

logger = logging.getLogger(__name__)


@dataclass
class InferenceConfig:
    """V8.1.8-B: Model inference configuration for spawned agent."""

    provider: str  # "gemini" or "claude"
    model: str  # e.g., "gemini-2.5-flash", "claude-sonnet-4-5-20250929"
    reasoning: str | None = None  # Why this model was chosen


@dataclass
class SpawnedAgentConfig:
    """Configuration loaded from BIRTH_CERTIFICATE.json"""

    agent_id: str
    role: str
    created_at: str
    parent: str
    mission: str
    domains: list[str]
    tools_priority: list[str]
    workspace_path: Path
    system_prompt_path: Path | None = None
    # V8.1.8: Unique identifier for agent tracking
    uuid: str | None = None
    # V8.1.8-B: Model inference configuration
    inference: InferenceConfig | None = None


class SpawnedAgentLoader:
    """
    Discovers and loads spawned agents from workspace/agents/.

    Each spawned agent directory must contain:
    - BIRTH_CERTIFICATE.json (required)
    - system_prompt.md (optional, for specialized prompts)
    - workspace/ (agent's working directory)
    """

    PROVIDER_SPAWNED = "spawned"

    def __init__(self, workspace_path: Path):
        """
        Initialize loader with workspace path.

        Args:
            workspace_path: Path to NEXUS workspace (contains agents/)
        """
        self.workspace_path = Path(workspace_path)
        self.agents_dir = self.workspace_path / "agents"

    def discover_spawned_agents(self) -> list[AgentProfile]:
        """
        Scan workspace/agents/ and create AgentProfile for each spawned agent.

        Returns:
            List of AgentProfile objects ready for registration in AgentPool
        """
        agents = []

        if not self.agents_dir.exists():
            logger.debug(f"No agents directory at {self.agents_dir}")
            return agents

        for agent_dir in self.agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue

            try:
                profile = self._load_agent_from_dir(agent_dir)
                if profile:
                    agents.append(profile)
                    logger.info(f"Discovered spawned agent: {profile.agent_id}")
            except Exception as e:
                logger.warning(f"Failed to load agent from {agent_dir}: {e}")

        logger.info(f"Discovered {len(agents)} spawned agents")
        return agents

    def _load_agent_from_dir(self, agent_dir: Path) -> AgentProfile | None:
        """
        Load a single agent from its directory.

        Args:
            agent_dir: Path to agent directory (workspace/agents/<agent_id>/)

        Returns:
            AgentProfile or None if invalid
        """
        cert_file = agent_dir / "BIRTH_CERTIFICATE.json"

        if not cert_file.exists():
            logger.debug(f"No BIRTH_CERTIFICATE.json in {agent_dir}")
            return None

        try:
            cert_data = json.loads(cert_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in {cert_file}: {e}")
            return None

        # Extract config from certificate
        config = self._parse_birth_certificate(cert_data, agent_dir)
        if not config:
            return None

        # Create AgentProfile
        profile = AgentProfile(
            agent_id=config.agent_id,
            provider=self.PROVIDER_SPAWNED,
            model=f"spawned_{config.agent_id}",
            capabilities=config.domains if config.domains else ["general"],
            is_active=True,
            uuid=config.uuid,  # V8.2.0: Propagate UUID from BIRTH_CERTIFICATE
        )

        return profile

    def _parse_birth_certificate(self, cert_data: dict[str, Any], agent_dir: Path) -> SpawnedAgentConfig | None:
        """
        Parse BIRTH_CERTIFICATE.json into SpawnedAgentConfig.

        Handles both flat and nested certificate formats.
        """
        # Handle nested format (birth_certificate wrapper)
        if "birth_certificate" in cert_data:
            cert_data = cert_data["birth_certificate"]

        agent_id = cert_data.get("agent_id")
        if not agent_id:
            logger.warning(f"Missing agent_id in {agent_dir}")
            return None

        # Extract specialization info
        specialization = cert_data.get("specialization", {})

        # Check for system prompt
        system_prompt_path = agent_dir / "system_prompt.md"
        if not system_prompt_path.exists():
            system_prompt_path = None

        # V8.1.8-B: Parse inference configuration
        inference_data = cert_data.get("inference")
        inference_config = None
        if inference_data and isinstance(inference_data, dict):
            inference_config = InferenceConfig(
                provider=inference_data.get("provider", "claude"),
                model=inference_data.get("model", "claude-sonnet-4-5-20250929"),
                reasoning=inference_data.get("reasoning"),
            )

        return SpawnedAgentConfig(
            agent_id=agent_id,
            role=cert_data.get("role", agent_id),
            created_at=cert_data.get("created_at", ""),
            parent=cert_data.get("parent", "NEXUS_V7.5"),
            mission=specialization.get("mission", f"Specialized agent: {agent_id}"),
            domains=specialization.get("domains", []),
            tools_priority=specialization.get("tools_priority", []),
            workspace_path=agent_dir,
            system_prompt_path=system_prompt_path,
            # V8.1.8: Extract UUID if present
            uuid=cert_data.get("uuid"),
            # V8.1.8-B: Model inference configuration
            inference=inference_config,
        )

    def load_agent_config(self, agent_id: str) -> SpawnedAgentConfig | None:
        """
        Load configuration for a specific agent by ID.

        Used by invocation adapter to get agent details.

        Args:
            agent_id: Agent identifier

        Returns:
            SpawnedAgentConfig or None if not found
        """
        agent_dir = self.agents_dir / agent_id

        if not agent_dir.exists():
            return None

        cert_file = agent_dir / "BIRTH_CERTIFICATE.json"
        if not cert_file.exists():
            return None

        try:
            cert_data = json.loads(cert_file.read_text(encoding="utf-8"))
            return self._parse_birth_certificate(cert_data, agent_dir)
        except Exception as e:
            logger.warning(f"Failed to load config for {agent_id}: {e}")
            return None

    def load_system_prompt(self, agent_id: str) -> str | None:
        """
        Load the specialized system prompt for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            System prompt content or None if not found
        """
        prompt_file = self.agents_dir / agent_id / "system_prompt.md"

        if not prompt_file.exists():
            return None

        try:
            return prompt_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to load system prompt for {agent_id}: {e}")
            return None

    def get_agent_workspace(self, agent_id: str) -> Path | None:
        """
        Get the workspace directory for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Path to agent's workspace or None
        """
        workspace = self.agents_dir / agent_id / "workspace"

        if workspace.exists():
            return workspace

        return None


def discover_and_register_spawned_agents(workspace_path: Path, agent_pool: "AgentPool") -> int:
    """
    Convenience function to discover and register all spawned agents.

    Args:
        workspace_path: Path to NEXUS workspace
        agent_pool: AgentPool to register agents into

    Returns:
        Number of agents registered
    """
    loader = SpawnedAgentLoader(workspace_path)
    agents = loader.discover_spawned_agents()

    for profile in agents:
        agent_pool.register(profile)

    return len(agents)
