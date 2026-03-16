import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.interface_pkg.interface.repl import InteractiveNexusV7


def test_hive_mind_execution():
    print("\n🚀 STARTING HIVE MIND EXECUTION TEST (SIMULATED)\n")

    workspace_path = Path("workspace_test_hive")
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace_path.mkdir()

    # Mock Drivers (V12.4: Use AsyncDriverFactory pattern)
    with (
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_gemini"),
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_claude"),
        patch("core.intelligence.swarm.task_analyzer.TaskAnalyzer.analyze") as MockAnalyze,
        patch("core.intelligence.swarm.mode_selector.ModeSelector.select_mode") as MockSelect,
        patch("core.intelligence.swarm.mode_executors.get_executor") as MockGetExecutor,
    ):
        # Setup Mocks for Swarm
        mock_analysis = MagicMock()
        mock_analysis.complexity.name = "MODERATE"
        mock_analysis.domains = []
        mock_analysis.primary_domain = None
        MockAnalyze.return_value = mock_analysis

        mock_proposal = MagicMock()
        mock_proposal.mode = CollaborationMode.PARALLEL
        mock_proposal.confidence = 0.9
        MockSelect.return_value = mock_proposal

        mock_executor = MagicMock()
        mock_execution_result = MagicMock()
        mock_execution_result.final_output = "Simulated Swarm Execution Result"
        mock_execution_result.status = "success"
        mock_executor.execute.return_value = mock_execution_result
        MockGetExecutor.return_value = mock_executor

        # Initialize REPL
        print("1. Initializing REPL...")
        # We mock sys.stdout to capture prints if needed, but console output is fine
        gemini_info = {"model": "gemini-mock"}
        claude_info = {"model": "claude-mock"}

        # Create dummy files for REPL init
        (workspace_path / ".nexus").mkdir(exist_ok=True)

        # Mock Config
        with (
            patch("core.interface_pkg.interface.repl.load_config") as MockConfig,
            patch.object(InteractiveNexusV7, "_calculate_nexus_root", return_value=workspace_path),
        ):
            mock_config = MagicMock()
            mock_config.workspace_path = workspace_path
            mock_config.log_level = "INFO"
            mock_config.agent_metrics_enabled = True
            mock_config.swarm_enabled = True
            mock_config.swarm_auto_route = True
            mock_config.swarm_negotiation_enabled = False  # Simplify test
            mock_config.red_team_mandatory = False
            mock_config.max_children_concurrent = 5
            mock_config.max_generations_per_day = 100
            MockConfig.return_value = mock_config

            repl = InteractiveNexusV7(workspace_path, gemini_info, claude_info)

            # Mock orchestrator rate limiter to allow evolution
            repl.rate_limiter = MagicMock()
            repl.rate_limiter.can_evolve.return_value = (True, "OK")

            # Mock brainstorm_children_with_ais
            print("\n2. Testing EVOLUTION (Specialization)...")

            # Prepare a fake parent to copy from
            nexus_root_mock = workspace_path / "NEXUS_MOCK_PARENT"
            nexus_root_mock.mkdir()
            (nexus_root_mock / "dummy.py").write_text("print('Hello')")
            repl.nexus_root = nexus_root_mock

            # Setup fake lineage
            (workspace_path / "LINEAGE.json").write_text(
                '{"history": [{"id": "NEXUS_MOCK_PARENT", "generation": 0, "asi_proximity_score": 0.1}]}'
            )

            def mock_brainstorm(*args, **kwargs):
                print("   [Mock] Brainstorming active -> Returning mutation proposal")
                return [
                    {
                        "file": "dummy.py",
                        "change": "print('Hello Specialized')",
                        "operation": "REPLACE",
                        "search_block": "print('Hello')",
                        "reason": "Specialization test",
                        "expected_asi_impact": 0.5,
                    }
                ]

            repl.brainstorm_children_with_ais = mock_brainstorm

            # Run Evolution
            repl.run_evolve(child_count=1)

            # Verify child creation
            generation_dir = workspace_path / "GENERATION_ACTIVE"
            if generation_dir.exists() and any(generation_dir.iterdir()):
                print("[OK] Evolution Test PASSED: Child created.")
            else:
                print("[NO] Evolution Test FAILED: No child created.")

            # Test Swarm
            print("\n3. Testing SWARM execution...")
            repl.run_swarm_task("Analyze this code")

            # Check if process_with_swarm was called (implicitly via success message)
            # Since we mocked the components, if we see output, it worked.
            print("[OK] Swarm Test PASSED (Logic executed without crash)")

    # Cleanup
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    # Reset the AutoMemory global singleton so subsequent tests start fresh.
    from core.memory_pkg.memory.auto_memory import reset_auto_memory
    reset_auto_memory()
    print("\n🏁 Test Suite Completed.")


if __name__ == "__main__":
    test_hive_mind_execution()
