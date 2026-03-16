"""
Simple smoke tests for NEXUS V7

Run with: python -m pytest tests/

Note: Legacy driver tests removed (test_imports, test_claude_parser)
after deletion of core/drivers/legacy/ in Sprint 1 consolidation.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config():
    """Test config loads"""
    from core.config import load_config

    config = load_config()
    assert config.gemini_cli_path
    assert config.claude_cli_path
    assert config.max_stalemate_count > 0


def test_stagnation_detector():
    """Test stagnation detection"""
    from core.fsm.stagnation_detector import StagnationDetector

    detector = StagnationDetector(similarity_threshold=0.8, window_size=3)

    # Add highly similar messages (same with minor variation)
    detector.add_message("I will read auth.py to find the bug")
    detector.add_message("I will read auth.py to find the bug")
    detector.add_message("I will read auth.py to find the bug")

    # Should detect stagnation (identical messages)
    assert detector.is_stagnant()


if __name__ == "__main__":
    # Run tests manually
    test_config()
    print("[OK] Config OK")

    test_stagnation_detector()
    print("[OK] Stagnation Detector OK")

    print("\n[OK] All tests passed!")
