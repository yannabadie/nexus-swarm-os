from pathlib import Path
from unittest.mock import MagicMock, patch

from core.interface_pkg.interface.repl import InteractiveNexusV7


def test_global_integration(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace_test_global"
    workspace_path.mkdir()
    (workspace_path / ".nexus").mkdir()
    (workspace_path / "memory").mkdir()

    gemini_info = {"model": "gemini-mock"}
    claude_info = {"model": "claude-mock"}

    with (
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_gemini"),
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_claude"),
        patch("core.interface_pkg.interface.repl.load_config") as mock_config_loader,
        patch("core.intelligence.evolution.lineage.load_lineage") as mock_load_lineage,
        patch("core.intelligence.evolution.lineage.get_current_parent") as mock_get_parent,
        patch.object(
            InteractiveNexusV7,
            "_calculate_nexus_root",
            return_value=workspace_path,
        ),
    ):
        mock_config = MagicMock()
        mock_config.workspace_path = workspace_path
        mock_config.log_level = "INFO"
        mock_config.agent_metrics_enabled = False
        mock_config.swarm_enabled = True
        mock_config.swarm_auto_route = True
        mock_config.validation_use_tiered = True
        mock_config.validation_tier_default = 1
        mock_config.red_team_mandatory = False
        mock_config.max_children_concurrent = 5
        mock_config.max_generations_per_day = 100
        mock_config.budget_limit_usd = 50.0
        mock_config_loader.return_value = mock_config

        mock_load_lineage.return_value = {"history": []}
        mock_get_parent.return_value = {"id": "PARENT_V1", "generation": 1, "asi_proximity_score": 0.5}

        repl = InteractiveNexusV7(workspace_path, gemini_info, claude_info)
        repl.nexus_root = workspace_path / "NEXUS_ROOT"
        repl.nexus_root.mkdir()

        repl.spawn_agent("Python Refactoring Expert")

        agent_dir = workspace_path / "agents" / "python_refactoring_expert"
        assert agent_dir.exists()
        assert (agent_dir / "BIRTH_CERTIFICATE.json").exists()

        mock_swarm_result = {
            "mode": "LEAD_SUPPORT",
            "state": "completed",
            "output": "Optimization complete.",
            "analysis": {"complexity": "COMPLEX", "primary_domain": "CODING"},
        }
        repl.orchestrator.process_with_swarm = MagicMock(return_value=mock_swarm_result)

        repl.run_swarm_task("Refactor core/orchestration_v7.py")
        repl.orchestrator.process_with_swarm.assert_called_once()

        auto_memory = getattr(repl.orchestrator, "auto_memory", None)
        assert auto_memory is not None

        auto_memory.record_success(
            task_type="CODING",
            task_description="Refactor core",
            swarm_mode="LEAD_SUPPORT",
            lead_agent="claude",
            duration_seconds=5.0,
            score=1.0,
        )

        success_file = auto_memory.successes_file
        assert success_file.exists(), f"Expected successes file at {success_file}"
        content = success_file.read_text(encoding="utf-8")
        assert "Refactor core" in content
        assert "LEAD_SUPPORT" in content
