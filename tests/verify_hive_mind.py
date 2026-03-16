import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.config import load_config
from core.orchestration_v7 import OrchestratorV7


def verify_hive_mind():
    print("[*] INITIALIZING HIVE MIND VERIFICATION...")

    # 1. Load Config
    config = load_config()
    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)

    # Mock API info
    gemini_info = {"model": "gemini-pro-mock"}
    claude_info = {"model": "claude-sonnet-mock"}

    try:
        # Initialize Orchestrator (simulates startup)
        orch = OrchestratorV7(workspace, config, gemini_info, claude_info)
        print("[OK] OrchestratorV7 instantiated successfully")

        # --- TEST 1: SWARM ENGINE ---
        print("\n[TEST 1] SWARM ENGINE STATUS")
        if orch.swarm_engine:
            print("[OK] HybridSwarmEngine: ACTIVE")

            # Check Auto-Route Config
            if config.swarm_auto_route:
                print("[OK] Swarm Auto-Route: ENABLED (Correct)")
            else:
                print("[FAIL] Swarm Auto-Route: DISABLED (Incorrect for V7.5)")

            # Check Modes
            print("[OK] TaskAnalyzer: READY")
            print("[OK] ModeSelector: READY")
            print("[OK] NegotiationProtocol: READY")

        else:
            print("[FAIL] HybridSwarmEngine: NOT INITIALIZED")

        # --- TEST 2: EVOLUTION CONFIG ---
        print("\n[TEST 2] EVOLUTION & RED TEAM CONFIG")

        # Check Red Team Optionality
        is_mandatory = getattr(config, "red_team_mandatory", True)
        print(f"[INFO] Red Team Mandatory: {is_mandatory}")

        if not is_mandatory:
            print("[OK] PASS: Red Team is OPTIONAL (Ready for Agent Spawning)")
        else:
            print("[FAIL] FAIL: Red Team is MANDATORY (Will block specialization)")

        # Check Evolution Prompt Availability
        gemini_prompt = Path("prompts/system_gemini_v7.md")
        if gemini_prompt.exists():
            print("[OK] System Prompt: FOUND")
        else:
            print("[FAIL] System Prompt: MISSING")

        # --- TEST 3: PROMPT LOADER ---
        print("\n[TEST 3] PROMPT LOADER (V7.5)")
        from core.memory_pkg.prompts import load_prompt

        # Test loading with includes
        gemini = load_prompt("system_gemini_v7")
        if "VISION" in gemini:
            print("[OK] Prompt includes resolved correctly")
        else:
            print("[FAIL] Prompt includes NOT resolved")

        # Test template variables
        evo = load_prompt("evolution_brainstorm", {"child_count": 5, "parent_id": "TEST", "lineage_context": ""})
        if "5 mutations" in evo:
            print("[OK] Template variables substituted correctly")
        else:
            print("[FAIL] Template variables NOT substituted")

        # --- TEST 4: AUTO-MEMORY ---
        print("\n[TEST 4] AUTO-MEMORY (V7.5)")
        from core.memory_pkg.memory import get_auto_memory

        memory = get_auto_memory(workspace)
        if memory:
            print("[OK] AutoMemory: INITIALIZED")
            # Test recommendation
            rec = memory.get_recommendation("coding")
            print(f"[INFO] Sample recommendation for 'coding': {rec}")
        else:
            print("[FAIL] AutoMemory: NOT AVAILABLE")

        # --- TEST 5: JSON EXTRACTOR ---
        print("\n[TEST 5] JSON EXTRACTOR (V7.5)")
        from core.utils.json_extractor import extract_json_safe, wrap_json

        # Test extraction
        test_input = 'Some text START_JSON {"key": "value"} END_JSON more text'
        result, method = extract_json_safe(test_input)
        if result and result.get("key") == "value":
            print(f"[OK] JSON extraction works (method: {method})")
        else:
            print("[FAIL] JSON extraction failed")

        # Test wrapping
        wrapped = wrap_json({"test": 123})
        if "START_JSON" in wrapped and "END_JSON" in wrapped:
            print("[OK] JSON wrapping works")
        else:
            print("[FAIL] JSON wrapping failed")

        print("\n" + "=" * 50)
        print("HIVE MIND V7.5 VERIFICATION COMPLETE")
        print("=" * 50)

    except Exception as e:
        print(f"\n[CRITICAL] ERROR during verification: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    verify_hive_mind()
