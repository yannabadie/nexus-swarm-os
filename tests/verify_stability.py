import sys
from pathlib import Path

# Add path to find core modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.orchestration_v7 import OrchestratorV7


def mock_cli_info():
    return {"available": True, "model": "mock-model", "context_window": 100000, "version": "1.0"}


class MockDriver:
    def __init__(self, name):
        self.name = name
        self.call_count = 0

    def invoke(self, context: str):
        self.call_count += 1
        print(f"\n[{self.name} Driver invoked]")

        # Verify Context Content
        if "PLAN STRATÉGIQUE" in context:
            print("  [OK] Context contains PLAN STRATÉGIQUE")
        else:
            print("  [FAIL] Context MISSING PLAN STRATÉGIQUE")

        if "CAPABILITIES" in context:
            print("  [OK] Context contains CAPABILITIES")
        else:
            print("  [FAIL] Context MISSING CAPABILITIES")

        # Simulate responses based on state/content
        # Simple turn simulation
        if "Create a file" in context and self.call_count == 1:
            # Gemini planning
            return {
                "sender": "Gemini",
                "action_type": "DELEGATE",
                "content": "I will delegate file creation to Claude.",
                "next_agent": "Claude",
                "status": "CONTINUE",
                "strategic_plan_update": [
                    {"step_id": 1, "description": "Create file", "status": "IN_PROGRESS", "assigned_agent": "Claude"}
                ],
            }
        elif "Create a file" in context and self.name == "Claude":
            # Claude executing
            return {
                "sender": "Claude",
                "action_type": "TOOL_USE",
                "content": "Creating file.",
                "tool_use": {
                    "tool_name": "write",
                    "arguments": {"file_path": "stability_test.txt", "content": "Step 1"},
                },
                "status": "CONTINUE",
            }
        elif "TOOL RESULT" in context:
            # Validation
            return {
                "sender": self.name,
                "action_type": "TALK",
                "content": "File created successfully.",
                "status": "FINISHED",
            }

        return {"sender": self.name, "action_type": "TALK", "content": "Generic response", "status": "FINISHED"}


def test_stability_and_context():
    print("Testing NEXUS V7 Logic, Stability and Context Injection...")

    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    (workspace / ".nexus").mkdir(exist_ok=True)
    (workspace / "_IO_BUFFER").mkdir(exist_ok=True)

    config = Config()
    config.ui_verbose = True

    gemini_info = mock_cli_info()
    claude_info = mock_cli_info()

    # Create orchestrator directly (not REPL) to avoid interactive session issues
    orchestrator = OrchestratorV7(workspace, config, gemini_info, claude_info)

    # Mock drivers
    orchestrator.drivers["Gemini"] = MockDriver("Gemini")
    orchestrator.drivers["Claude"] = MockDriver("Claude")

    # --- Turn 1 ---
    print("\n--- Turn 1: Define Objective ---")
    user_input = "Create a file named stability_test.txt"

    # IDLE -> BRAINSTORMING
    result = orchestrator.process_turn(user_input)
    print(f"State: {result['state']}")

    # Run loop
    max_iterations = 5
    iterations = 0
    while result["state"] != "IDLE" and iterations < max_iterations:
        result = orchestrator.process_turn()
        print(f"State: {result['state']}")
        iterations += 1

    if result["state"] == "IDLE":
        print("SUCCESS: Turn 1 completed.")
    else:
        print("FAILED: Turn 1 did not complete.")


if __name__ == "__main__":
    test_stability_and_context()
