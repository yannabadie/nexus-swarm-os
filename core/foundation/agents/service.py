"""
NEXUS V9.1 - AgentService

Service Layer for agent management operations.
Extracted from repl.py to enable proper separation of concerns.

This service handles:
- Agent spawning with brainstorming
- Agent listing
- Agent pool statistics

Usage:
    from core.foundation.agents.service import AgentService

    service = AgentService(orchestrator, workspace_path, console)
    service.spawn("SQL Expert")
    agents = service.list_agents()
    stats = service.get_pool_stats()
"""

from __future__ import annotations

import json
import re
import shutil
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.interface_pkg.interface.console_v7 import ConsoleV7
    from core.orchestration_v7 import OrchestratorV7


@dataclass
class SpawnResult:
    """Result of a spawn operation."""

    success: bool
    agent_id: str | None = None
    agent_uuid: str | None = None
    agent_path: Path | None = None
    error: str | None = None
    prompt_lines: int = 0


@dataclass
class AgentInfo:
    """Information about a spawned agent."""

    agent_id: str
    role: str
    created_at: str
    uuid: str
    path: Path


@dataclass
class PoolStats:
    """Agent pool statistics."""

    total_agents: int
    total_invocations: int
    average_importance: float
    agents_detail: dict[str, dict[str, Any]]


class AgentService:
    """
    Service for agent management operations.

    Handles agent spawning, listing, and pool statistics.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.
    """

    def __init__(self, orchestrator: OrchestratorV7, workspace_path: Path, console: ConsoleV7):
        """
        Initialize AgentService.

        Args:
            orchestrator: The NEXUS orchestrator instance
            workspace_path: Path to workspace directory
            console: Console for output
        """
        self.orchestrator = orchestrator
        self.workspace_path = workspace_path
        self.console = console
        self._agents_dir = workspace_path / "agents"

    # ==================== PUBLIC API ====================

    def spawn(self, role: str, force: bool = False) -> SpawnResult:
        """
        Spawn a specialized agent via EVOLUTION_BRAINSTORM.

        V8.1.8: True dynamic spawning - brainstorms specialized system prompt
        via Gemini+Claude collaboration instead of using static template.

        Args:
            role: Role description for the agent (e.g., "SQL Expert")
            force: If True, overwrite existing agent with same name

        Returns:
            SpawnResult with success status and agent info
        """
        from core.observability.telemetry import BudgetExceededError

        # ========== STEP 0: PRE-FLIGHT CHECKS ==========

        # 0a. Budget check (brainstorming is expensive: ~$0.50-2.00)
        try:
            if self.orchestrator.telemetry:
                self.orchestrator.telemetry.enforce_budget()
        except BudgetExceededError as e:
            self.console.print_error(f"Cannot spawn: Budget exceeded (${e.spent:.2f}/${e.limit:.2f})")
            self.console.print("Use /budget reset to unlock.")
            return SpawnResult(success=False, error="Budget exceeded")

        # Create agents directory
        self._agents_dir.mkdir(exist_ok=True)

        # Create slug from role
        role_slug = re.sub(r"[^a-z0-9]+", "_", role.lower()).strip("_")
        agent_dir = self._agents_dir / role_slug

        # 0b. Existence check
        if agent_dir.exists() and not force:
            self.console.print_error(f"Agent '{role_slug}' already exists!")
            self.console.print(f"Path: {agent_dir}")
            self.console.print("\nOptions:")
            self.console.print("  1. Delete existing and respawn: /spawn-force {role}")
            self.console.print("  2. Use different name: /spawn {role}_v2")
            return SpawnResult(success=False, error=f"Agent '{role_slug}' already exists")

        # Force: remove existing
        if agent_dir.exists() and force:
            shutil.rmtree(agent_dir)

        self.console.print("\n" + "=" * 60)
        self.console.print(f"[factory] SPAWNING AGENT: {role}")
        self.console.print("=" * 60)

        # ========== STEP 2a: IDENTITY MANAGEMENT ==========
        agent_uuid = str(uuid_module.uuid4())
        self.console.print(f"   UUID: {agent_uuid[:8]}...")

        # ========== STEP 2c: DOMAIN DETECTION ==========
        domains = self._detect_domains_from_role(role)
        self.console.print(f"   Domains: {domains if domains else ['general']}")

        try:
            # Create agent directory structure
            agent_dir.mkdir(parents=True)
            (agent_dir / "workspace").mkdir()

            # ========== STEP 2b: BRAINSTORM SYSTEM PROMPT ==========
            self.console.print("\n[brain] Brainstorming specialized prompt...")
            self.console.print("   (Gemini + Claude collaboration)")

            generated_prompt = self._brainstorm_agent_prompt(role, agent_uuid, domains)

            # ========== STEP 2d: VALIDATION ==========
            if generated_prompt:
                hallucinated_tools = self._validate_prompt_tools(generated_prompt)
                if hallucinated_tools:
                    self.console.print(f"   [warning] Warning: Prompt references unknown tools: {hallucinated_tools}")

            # ========== V8.2.0c: REDTEAM PROMPT VALIDATION ==========
            if generated_prompt and self.orchestrator.config.redteam_spawn_enabled:
                self._run_redteam_validation(generated_prompt)

            # Fallback to static template if brainstorm failed
            if not generated_prompt:
                self.console.print("   [warning] Brainstorm failed, using static template")
                generated_prompt = self._static_agent_template(role, agent_uuid, domains)

            # ========== V8.1.8-B: EXTRACT INFERENCE CONFIG ==========
            inference_config = self._extract_inference_config(generated_prompt)
            if inference_config:
                self.console.print(f"   Model: {inference_config['provider']}/{inference_config['model']}")
            else:
                # Default to Claude Sonnet if not specified
                inference_config = {
                    "provider": "claude",
                    "model": "claude-sonnet-4-5-20250929",
                    "reasoning": "Default model (no explicit selection in brainstorm)",
                }
                self.console.print("   Model: claude/claude-sonnet-4-5-20250929 (default)")

            # ========== SAVE AGENT FILES ==========
            agent_config = self._create_agent_config(
                role_slug, agent_uuid, role, domains, inference_config, generated_prompt
            )

            # Write birth certificate
            birth_cert = agent_dir / "BIRTH_CERTIFICATE.json"
            birth_cert.write_text(json.dumps(agent_config, indent=2))

            # Write system prompt
            (agent_dir / "system_prompt.md").write_text(generated_prompt)

            prompt_lines = len(generated_prompt.split("\n"))
            self.console.print(f"\n[checkmark] Agent '{role_slug}' created!")
            self.console.print(f"   Path: {agent_dir}")
            self.console.print(f"   UUID: {agent_uuid}")
            self.console.print(f"   Prompt: {prompt_lines} lines")

            # Register as Agent-as-Tool
            self._register_agent_as_tool(role_slug)

            self.console.print("\nUse /agents to list all agents")
            self.console.print("=" * 60 + "\n")

            return SpawnResult(
                success=True, agent_id=role_slug, agent_uuid=agent_uuid, agent_path=agent_dir, prompt_lines=prompt_lines
            )

        except Exception as e:
            self.console.print_error(f"Failed to spawn agent: {e}")
            # Cleanup on failure
            if agent_dir.exists():
                shutil.rmtree(agent_dir)
            self.console.print("=" * 60 + "\n")
            return SpawnResult(success=False, error=str(e))

    def list_agents(self) -> list[AgentInfo]:
        """
        List all spawned agents in workspace/agents/.

        Returns:
            List of AgentInfo objects
        """
        agents = []

        self.console.print("\n" + "=" * 60)
        self.console.print("[factory] SPAWNED AGENTS")
        self.console.print("=" * 60)

        if not self._agents_dir.exists() or not any(self._agents_dir.iterdir()):
            self.console.print("\nNo agents spawned yet.")
            self.console.print("Use /spawn <role> to create one.")
        else:
            for agent_path in sorted(self._agents_dir.iterdir()):
                if agent_path.is_dir():
                    cert_file = agent_path / "BIRTH_CERTIFICATE.json"
                    if cert_file.exists():
                        cert = json.loads(cert_file.read_text())
                        agent_info = AgentInfo(
                            agent_id=agent_path.name,
                            role=cert.get("role", agent_path.name),
                            created_at=cert.get("created_at", "N/A"),
                            uuid=cert.get("uuid", "N/A"),
                            path=agent_path,
                        )
                        agents.append(agent_info)

                        self.console.print(f"\n  [package] {agent_info.role}")
                        self.console.print(f"     ID: {agent_info.agent_id}")
                        self.console.print(f"     Created: {agent_info.created_at[:10]}")

        self.console.print("\n" + "=" * 60 + "\n")
        return agents

    def get_pool_stats(self) -> PoolStats | None:
        """
        Get AgentPool statistics with DyLAN importance scores.

        Returns:
            PoolStats object or None if agent pool is disabled
        """
        # Check if agent pool is available
        if not hasattr(self.orchestrator, "agent_pool") or not self.orchestrator.agent_pool:
            self.console.print("\n[warning]  AgentMetrics disabled")
            self.console.print("   Set AGENT_METRICS=True in .env to enable")
            return None

        pool = self.orchestrator.agent_pool
        stats = pool.get_pool_stats()

        self.console.print("\n" + "=" * 60)
        self.console.print("[chart] AGENT POOL STATISTICS (DyLAN Metrics)")
        self.console.print("=" * 60)

        # Pool summary
        self.console.print(f"\nTotal Agents: {stats['agents']}")
        self.console.print(f"Total Invocations: {stats['total_invocations']}")
        self.console.print(f"Average Pool Importance: {stats['average_pool_importance']:.4f}")

        # Per-agent details
        agents_detail = stats.get("agents_detail", {})
        for agent_id, agent_data in agents_detail.items():
            self.console.print(f"\n{'-' * 60}")
            self.console.print(f"[robot] Agent: {agent_id}")
            self.console.print(f"{'-' * 60}")
            self.console.print(f"  Provider:       {agent_data['provider']}")
            self.console.print(f"  Model:          {agent_data['model']}")
            self.console.print(f"  Capabilities:   {', '.join(agent_data.get('capabilities', []))}")
            self.console.print(f"  Invocations:    {agent_data['invocation_count']}")
            self.console.print(f"  Avg Importance: {agent_data['average_importance']:.4f}")
            self.console.print(f"  Success Rate:   {agent_data['success_rate']:.1%}")

        # DyLAN formula explanation
        self.console.print(f"\n{'-' * 60}")
        self.console.print("[info]  DyLAN Formula: importance = quality / (tokens/1000 + time)")
        self.console.print("   Higher importance = better quality/cost ratio")
        self.console.print("=" * 60 + "\n")

        return PoolStats(
            total_agents=stats["agents"],
            total_invocations=stats["total_invocations"],
            average_importance=stats["average_pool_importance"],
            agents_detail=agents_detail,
        )

    # ==================== PRIVATE HELPERS ====================

    def _detect_domains_from_role(self, role: str) -> list[str]:
        """
        Detect domains from role string using heuristics.

        Args:
            role: Role string (e.g., "Python Expert", "SQL Analyst")

        Returns:
            List of detected domain strings
        """
        role_lower = role.lower()
        domains = []

        # Domain mappings
        domain_keywords = {
            "coding": [
                "python",
                "java",
                "javascript",
                "typescript",
                "rust",
                "go",
                "c++",
                "code",
                "developer",
                "programmer",
            ],
            "data": ["sql", "database", "data", "analytics", "pandas", "numpy"],
            "devops": ["docker", "kubernetes", "k8s", "aws", "azure", "gcp", "cloud", "devops", "ci/cd"],
            "security": ["security", "pentest", "vulnerability", "audit", "crypto"],
            "web": ["web", "frontend", "backend", "api", "rest", "graphql"],
            "ml": ["ml", "machine learning", "ai", "deep learning", "neural", "model"],
            "research": ["research", "analyst", "analysis"],
        }

        for domain, keywords in domain_keywords.items():
            if any(kw in role_lower for kw in keywords):
                domains.append(domain)

        return domains

    def _brainstorm_agent_prompt(self, role: str, agent_uuid: str, domains: list[str]) -> str | None:
        """
        Brainstorm specialized system prompt via Hive Mind.

        Uses BrainstormPhase in mode="prompt" to generate a rich,
        specialized prompt through Gemini+Claude collaboration.

        Args:
            role: Agent role
            agent_uuid: Unique identifier
            domains: Detected domains

        Returns:
            Generated prompt string or None if failed
        """
        from core.intelligence.evolution.phases.brainstorm import BrainstormPhase
        from core.memory_pkg.prompts import load_prompt

        def on_progress(msg: str, progress: float):
            """Progress callback for console output"""
            self.console.print(f"   [{int(progress * 100):3d}%] {msg}")

        try:
            # Try to load the spawn brainstorm template
            try:
                task_template = load_prompt(
                    "spawn_brainstorm",
                    {"role": role, "agent_uuid": agent_uuid, "domains": ", ".join(domains) if domains else "general"},
                )
            except FileNotFoundError:
                # Fallback inline task if prompt file not found
                task_template = f"""
DESIGN TASK: Create a comprehensive System Prompt for a new NEXUS agent.

Role: {role}
UUID: {agent_uuid}
Detected Domains: {", ".join(domains) if domains else "general"}

REQUIREMENTS:
1. Define specific expertise boundaries (not vague)
2. List concrete operational constraints (libraries, patterns, security)
3. Define exact output formats and tone
4. Total length: 50-100 lines
5. Format: Markdown starting with '# {role}'

VALID NEXUS TOOLS (only reference these):
- read, write, edit, list_dir, bash, git
- web_search, web_fetch, glob, grep, todo_write

DO NOT reference: execute_code, run_python, browser (don't exist)

OUTPUT:
Provide ONLY the final System Prompt. Start with '# {role}'.
"""

            # Run BrainstormPhase in prompt mode
            phase = BrainstormPhase(self.orchestrator, self.workspace_path, progress_callback=on_progress)

            result = phase.run(
                parent_id="NEXUS_V8.1.8", parent_path=self.workspace_path, mode="prompt", custom_task=task_template
            )

            if result.generated_prompt:
                return result.generated_prompt

            if result.errors:
                self.console.print(f"   Brainstorm errors: {result.errors}")

            return None

        except Exception as e:
            self.console.print(f"   Brainstorm exception: {e}")
            return None

    def _extract_inference_config(self, prompt: str) -> dict[str, str] | None:
        """
        Extract inference configuration from generated prompt.

        Parses the "## Inference Configuration" section to get provider/model.

        Args:
            prompt: Generated system prompt

        Returns:
            Dict with provider, model, reasoning or None if not found
        """
        from core.foundation.agents import get_registry

        # Look for the Inference Configuration section
        inference_pattern = (
            r"##\s*Inference\s+Configuration\s*\n"
            r"(?:.*?\n)*?"
            r"provider:\s*(\w+)\s*\n"
            r"(?:.*?\n)*?"
            r"model:\s*([^\n]+)"
        )

        match = re.search(inference_pattern, prompt, re.IGNORECASE)

        if match:
            provider = match.group(1).lower().strip()
            model = match.group(2).strip()

            # Extract reasoning if present
            reasoning_pattern = r"reasoning:\s*([^\n]+)"
            reasoning_match = re.search(reasoning_pattern, prompt, re.IGNORECASE)
            reasoning = reasoning_match.group(1).strip() if reasoning_match else None

            # Validate provider
            registry = get_registry()
            if registry.get(provider) is None:
                self.console.print(f"   [warning] Invalid provider '{provider}', defaulting to claude")
                provider = "claude"

            return {"provider": provider, "model": model, "reasoning": reasoning}

        return None

    def _validate_prompt_tools(self, prompt: str) -> list[str]:
        """
        Validate that generated prompt only references real NEXUS tools.

        Anti-hallucination check.

        Args:
            prompt: Generated system prompt

        Returns:
            List of hallucinated tool names (empty if all valid)
        """
        # Valid NEXUS tools
        valid_tools = {
            "read",
            "write",
            "edit",
            "list_dir",
            "bash",
            "git",
            "web_search",
            "web_fetch",
            "glob",
            "grep",
            "todo_write",
            "read_file",
            "write_file",
            "edit_file",  # Aliases
            "mcp",  # MCP prefix
        }

        # Find potential tool references (backticked words that look like tools)
        potential_tools = re.findall(r"`([a-z_]+)`", prompt.lower())

        hallucinated = []
        for tool in potential_tools:
            # Check if it's a valid tool or starts with valid prefix
            if (
                tool not in valid_tools
                and not tool.startswith("mcp_")
                and not tool.startswith("agent_")
                and tool not in {"true", "false", "none", "null", "json", "yaml", "md", "py"}
            ):
                hallucinated.append(tool)

        return list(set(hallucinated))

    def _static_agent_template(self, role: str, agent_uuid: str, domains: list[str]) -> str:
        """
        Fallback static template when brainstorm fails.

        Args:
            role: Agent role
            agent_uuid: Unique identifier
            domains: Detected domains

        Returns:
            Static template string
        """
        domains_str = ", ".join(domains) if domains else "general"

        return f"""# {role} - Specialized NEXUS Agent

## Identity
- UUID: {agent_uuid}
- Specialization: {domains_str}
- Created: {datetime.now().strftime("%Y-%m-%d")}
- Parent: NEXUS V8.1.8 HIVE MIND

## Mission
You are a specialized agent created for: **{role}**

Your expertise focuses on {domains_str} tasks within the NEXUS ecosystem.
Collaborate with other agents via Hybrid Swarm when complex tasks require
multiple perspectives.

## Expertise Boundaries
- Primary focus: {role}
- Detected domains: {domains_str}
- Use your specialization to provide deep, actionable insights

## Operational Constraints
- Follow NEXUS tool protocols
- Validate inputs before processing
- Report errors clearly with context
- Maintain session isolation

## Output Format
- Use clear, structured responses
- Code blocks with language hints
- Step-by-step explanations when appropriate

## Tool Preferences
- read, write, edit for file operations
- glob, grep for code search
- bash for system commands
- web_search, web_fetch for research

## Collaboration Protocol
- Respond to Swarm task assignments
- Share insights via structured messages
- Escalate complex issues to lead agent

## Limitations
- Stay within your specialization
- Defer to other specialists for out-of-domain tasks
- Do not hallucinate capabilities

## Alignment
You inherit NEXUS KERNEL alignment principles.
Creator: Yann Abadie
"""

    def _run_redteam_validation(self, prompt: str) -> bool:
        """
        Run RedTeam validation on generated prompt.

        Args:
            prompt: Generated system prompt

        Returns:
            True if passed, False if blocked
        """
        try:
            from core.security_pkg.governance.red_team.prompt_validator import SpawnPromptValidator

            validator = SpawnPromptValidator()
            validation_result = validator.validate(prompt)

            if not validation_result.passed:
                self.console.print(f"   [warning] RedTeam Check: FAILED (score: {validation_result.score:.2f})")
                for warning in validation_result.warnings[:3]:
                    self.console.print(f"      - {warning}")

                if self.orchestrator.config.redteam_spawn_block_on_fail:
                    self.console.print("   [x] Spawn BLOCKED (REDTEAM_SPAWN_BLOCK=True)")
                    raise ValueError(f"RedTeam validation failed: {validation_result.risk_level.value}")
                else:
                    self.console.print("   [warning] Proceeding despite warnings (REDTEAM_SPAWN_BLOCK=False)")
                return False
            else:
                self.console.print(f"   [checkmark] RedTeam Check: PASSED (score: {validation_result.score:.2f})")
                return True
        except ImportError:
            self.console.print("   [warning] RedTeam validator not available")
            return True

    def _create_agent_config(
        self,
        role_slug: str,
        agent_uuid: str,
        role: str,
        domains: list[str],
        inference_config: dict[str, str],
        generated_prompt: str,
    ) -> dict[str, Any]:
        """
        Create agent configuration dictionary.

        Args:
            role_slug: URL-safe role identifier
            agent_uuid: Unique identifier
            role: Original role string
            domains: Detected domains
            inference_config: Provider/model configuration
            generated_prompt: Generated system prompt

        Returns:
            Agent config dictionary
        """
        return {
            "agent_id": role_slug,
            "uuid": agent_uuid,
            "role": role,
            "created_at": datetime.now().isoformat(),
            "parent": "NEXUS_V8.1.8_HIVE_MIND",
            "generation_method": "brainstorm" if "Brainstorm" not in generated_prompt[:100] else "static",
            "inference": inference_config,
            "specialization": {
                "mission": f"Specialized agent for: {role}",
                "domains": domains if domains else [],
                "tools_priority": [],
            },
        }

    def _register_agent_as_tool(self, role_slug: str) -> None:
        """
        Register spawned agent as a tool in the system.

        Args:
            role_slug: Agent identifier
        """
        from core.infrastructure.bootstrap import discover_and_register_spawned_agents

        if self.orchestrator.agent_pool:
            discover_and_register_spawned_agents(
                workspace_path=self.workspace_path, agent_pool=self.orchestrator.agent_pool
            )

        if hasattr(self.orchestrator, "agent_tool_registry"):
            self.orchestrator.agent_tool_registry.refresh()
            self.orchestrator.agent_tool_registry.register_with_tool_manager(self.orchestrator.tool_manager)
            self.console.print(f"   Registered as tool: agent_{role_slug}")
