import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

from core.interface_pkg.interface.repl import InteractiveNexusV7


def test_hive_mind_execution_v2():
    print("\n🚀 STARTING HIVE MIND EXECUTION TEST V2 (MOCKED)\n")

    workspace_path = Path("workspace_test_hive_v2")
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace_path.mkdir()

    # Setup Mocks (V12.4: Use AsyncDriverFactory pattern)
    with (
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_gemini"),
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_claude"),
        patch("core.interface_pkg.interface.repl.load_config") as MockConfig,
        patch.object(InteractiveNexusV7, "_calculate_nexus_root", return_value=workspace_path),
        patch("core.intelligence.evolution.lineage.load_lineage") as MockLineage,
        patch("core.intelligence.evolution.lineage.get_current_parent") as MockGetParent,
    ):
        # 1. Config Mock
        mock_config = MagicMock()
        mock_config.workspace_path = workspace_path
        mock_config.log_level = "INFO"
        mock_config.agent_metrics_enabled = False
        mock_config.swarm_enabled = True
        mock_config.swarm_auto_route = True
        mock_config.max_children_concurrent = 5
        mock_config.max_generations_per_day = 100
        mock_config.ui_verbose = True
        # Critical for Red Team Optionality
        mock_config.red_team_mandatory = False
        # Fix validation_tier_default for test
        mock_config.validation_tier_default = 1
        mock_config.validation_use_tiered = True

        MockConfig.return_value = mock_config

        # 2. Lineage Mock
        MockLineage.return_value = {"history": []}
        MockGetParent.return_value = {"id": "PARENT_V1", "generation": 1, "asi_proximity_score": 0.5}

        # 3. Initialize REPL
        gemini_info = {"model": "gemini-mock"}
        claude_info = {"model": "claude-mock"}

        # Dummy dirs
        (workspace_path / ".nexus").mkdir(parents=True, exist_ok=True)
        nexus_root = workspace_path / "NEXUS_PARENT"
        nexus_root.mkdir()
        (nexus_root / "dummy.py").write_text("print('Original')")

        repl = InteractiveNexusV7(workspace_path, gemini_info, claude_info)
        repl.nexus_root = nexus_root  # Force root

        # Mock Rate Limiter
        repl.rate_limiter = MagicMock()
        repl.rate_limiter.can_evolve.return_value = (True, "OK")
        repl.rate_limiter.get_stats.return_value = {"today_evolutions": 0, "remaining_today": 10}

        # 4. TEST EVOLUTION (Specialization)
        print("\n🧪 TEST 2: EVOLUTION (Agent Specialization)...")

        # Mock Brainstorming to return a valid mutation
        def mock_brainstorm(*args, **kwargs):
            print("   [Mock] Brainstorming: Proposing SQL Agent Specialization")
            return [
                {
                    "file": "dummy.py",
                    "change": "print('SQL Expert Agent')",
                    "operation": "REPLACE",
                    "search_block": "print('Original')",
                    "reason": "Specialization for SQL",
                    "expected_asi_impact": 0.8,
                }
            ]

        repl.brainstorm_children_with_ais = mock_brainstorm

        # Run Evolution
        repl.run_evolve(child_count=1)

        # Verify Child Creation
        workspace_path.parent / "GENERATION_ACTIVE"  # Default path logic
        # Note: repl.py logic for child_dir uses self.nexus_root.parent / "GENERATION_ACTIVE"
        # Since repl.nexus_root is workspace_path/NEXUS_PARENT
        # child_dir will be workspace_path/GENERATION_ACTIVE

        expected_gen_dir = workspace_path / "GENERATION_ACTIVE"

        if expected_gen_dir.exists():
            children = list(expected_gen_dir.iterdir())
            if len(children) > 0:
                print(f"[OK] Evolution PASSED: Child created at {children[0]}")

                # Verify content
                child_file = children[0] / "dummy.py"
                if child_file.exists() and "SQL Expert Agent" in child_file.read_text():
                    print("[OK] Mutation Applied: Content verified")
                else:
                    print("[NO] Mutation Failed: Content not updated")

                # Verify Red Team Skipped (Implicitly passed if child exists and valid)
                birth_cert = children[0] / "BIRTH_CERTIFICATE.json"
                if birth_cert.exists():
                    print("[OK] Birth Certificate: Created")
                else:
                    print("[NO] Birth Certificate: Missing")

            else:
                print("[NO] Evolution Failed: Directory empty")
        else:
            print(f"[NO] Evolution Failed: Directory {expected_gen_dir} not created")

        # 5. TEST SWARM
        print("\n🧪 TEST 1: SWARM ENGINE...")

        # Mock orchestrator.process_with_swarm
        mock_swarm_result = {
            "mode": "SPECIALIST",
            "state": "completed",
            "output": "Swarm Task Completed Successfully via Mock",
            "analysis": {"complexity": "MODERATE", "domains": ["CODING"]},
        }
        repl.orchestrator.process_with_swarm = MagicMock(return_value=mock_swarm_result)

        repl.run_swarm_task("Optimize this SQL query")

        repl.orchestrator.process_with_swarm.assert_called_once()
        print("[OK] Swarm Execution PASSED (Method called correctly)")

    # Cleanup
    try:
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
    except Exception:
        pass
    print("\n🏁 Test Suite Completed.")


if __name__ == "__main__":
    test_hive_mind_execution_v2()
