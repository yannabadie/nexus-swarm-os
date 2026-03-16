"""
Tests for Phase 16: Developer Experience (DX)

Tests:
- /budget command functionality
- Categorized help structure
- Interactive tutorial
- Quickstart guide
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# =============================================================================
# COMMAND CATEGORIES TESTS (Phase 16b)
# =============================================================================


class TestCommandCategories:
    """Test categorized command structure."""

    def test_command_categories_exist(self):
        """Verify COMMAND_CATEGORIES structure."""
        from core.interface_pkg.interface.commands import COMMAND_CATEGORIES

        assert isinstance(COMMAND_CATEGORIES, dict)
        assert len(COMMAND_CATEGORIES) == 6  # V7.8: Added Memory category

        expected_categories = [
            "Collaboration",
            "Evolution",
            "Monitoring",
            "Workspace",
            "Memory",  # V7.8 Phase 10c
            "System",
        ]

        for expected in expected_categories:
            found = any(expected in cat for cat in COMMAND_CATEGORIES)
            assert found, f"Category '{expected}' not found"

    def test_budget_commands_in_monitoring(self):
        """Verify /budget commands are in Monitoring category."""
        from core.interface_pkg.interface.commands import COMMAND_CATEGORIES

        monitoring = COMMAND_CATEGORIES.get("📊 Monitoring", {})

        assert "/budget" in monitoring
        assert "/budget reset" in monitoring
        assert "/budget add <amount>" in monitoring
        assert "/budget history" in monitoring

    def test_tutorial_commands_in_system(self):
        """Verify tutorial commands are in System category."""
        from core.interface_pkg.interface.commands import COMMAND_CATEGORIES

        system = COMMAND_CATEGORIES.get("⚙️ System", {})

        assert "/tutorial" in system
        assert "/quickstart" in system
        assert "/chat" in system

    def test_slash_commands_backwards_compat(self):
        """Verify flat SLASH_COMMANDS is populated."""
        from core.interface_pkg.interface.commands import COMMAND_CATEGORIES, SLASH_COMMANDS

        # Should contain all commands from all categories
        total_commands = sum(len(cmds) for cmds in COMMAND_CATEGORIES.values())
        assert len(SLASH_COMMANDS) == total_commands

    def test_get_help_message_formatted(self):
        """Verify help message is well-formatted."""
        from core.interface_pkg.interface.commands import get_help_message

        help_text = get_help_message()

        assert "NEXUS V" in help_text
        assert "Collaboration" in help_text
        assert "Evolution" in help_text
        assert "Monitoring" in help_text
        assert "/tutorial" in help_text

    def test_get_category_for_command(self):
        """Test command-to-category lookup."""
        from core.interface_pkg.interface.commands import get_category_for_command

        assert "Monitoring" in get_category_for_command("/budget")
        assert "Monitoring" in get_category_for_command("/telemetry")
        assert "System" in get_category_for_command("/help")
        assert get_category_for_command("/nonexistent") == "Unknown"


# =============================================================================
# TUTORIAL TESTS (Phase 16c)
# =============================================================================


class TestInteractiveTutorial:
    """Test interactive tutorial functionality."""

    def test_tutorial_steps_defined(self):
        """Verify tutorial steps are properly defined."""
        from core.interface_pkg.interface.tutorial import TUTORIAL_STEPS, TutorialStep

        assert len(TUTORIAL_STEPS) == 6

        for step in TUTORIAL_STEPS:
            assert isinstance(step, TutorialStep)
            assert step.title
            assert step.explanation

    def test_tutorial_step_structure(self):
        """Verify TutorialStep dataclass."""
        from core.interface_pkg.interface.tutorial import TutorialStep

        step = TutorialStep(
            title="Test Step", explanation="Test explanation", suggested_command="/test", tip="Test tip"
        )

        assert step.title == "Test Step"
        assert step.explanation == "Test explanation"
        assert step.suggested_command == "/test"
        assert step.tip == "Test tip"

    def test_tutorial_format_step(self):
        """Verify step formatting."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial, TutorialStep

        tutorial = InteractiveTutorial()
        step = TutorialStep(
            title="Test", explanation="Explanation here", suggested_command="/test", tip="A helpful tip"
        )

        formatted = tutorial.format_step(step, 0)

        assert "TUTORIAL (1/" in formatted
        assert "Test" in formatted
        assert "Explanation here" in formatted
        assert "/test" in formatted
        assert "A helpful tip" in formatted

    def test_tutorial_get_step(self):
        """Test get_step method."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()

        assert tutorial.get_step(0) is not None
        assert tutorial.get_step(4) is not None
        assert tutorial.get_step(5) is not None
        assert tutorial.get_step(6) is None  # Out of bounds
        assert tutorial.get_step(-1) is None  # Negative

    def test_quickstart_content(self):
        """Verify quickstart guide content."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()
        quickstart = tutorial.get_quick_start()

        assert "QUICK START" in quickstart
        assert "/swarm" in quickstart
        assert "/budget" in quickstart
        assert "/spawn" in quickstart
        assert "/help" in quickstart

    def test_tutorial_run_complete(self):
        """Test tutorial run completing all steps."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()
        output = []

        # Mock input to press Enter for each step
        mock_input = MagicMock(return_value="")

        result = tutorial.run(print_fn=output.append, input_fn=mock_input)

        assert result is True
        assert mock_input.call_count == len(tutorial.steps)

    def test_tutorial_run_quit(self):
        """Test tutorial run with quit."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()
        output = []

        # Quit on first step
        mock_input = MagicMock(return_value="q")

        result = tutorial.run(print_fn=output.append, input_fn=mock_input)

        assert result is False
        assert mock_input.call_count == 1

    def test_tutorial_run_skip(self):
        """Test tutorial run with skip."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()
        output = []

        # Skip all steps then complete
        call_count = 0

        total_steps = len(tutorial.steps)

        def mock_input(prompt):
            nonlocal call_count
            call_count += 1
            return "s" if call_count < total_steps else ""

        result = tutorial.run(print_fn=output.append, input_fn=mock_input)

        assert result is True


# =============================================================================
# BUDGET COMMAND TESTS (Phase 16a)
# =============================================================================


class TestBudgetCommand:
    """Test /budget command functionality."""

    @pytest.fixture
    def mock_tracker(self):
        """Create mock BudgetTracker."""
        tracker = MagicMock()
        tracker.get_stats.return_value = {
            "spent_today_usd": 5.25,
            "limit_usd": 50.0,
            "remaining_usd": 44.75,
            "percentage_used": 10.5,
            "api_calls_today": 15,
            "reset_date": date.today().isoformat(),
        }
        tracker.get_warning_level.return_value = None
        tracker.get_remaining.return_value = 44.75
        tracker.limit_usd = 50.0
        return tracker

    def test_budget_stats_structure(self):
        """Verify BudgetTracker.get_stats() structure."""
        import tempfile

        from core.observability.telemetry import BudgetTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = BudgetTracker(workspace_path=Path(tmpdir))
            stats = tracker.get_stats()

            assert "spent_today_usd" in stats
            assert "limit_usd" in stats
            assert "remaining_usd" in stats
            assert "percentage_used" in stats
            assert "api_calls_today" in stats
            assert "reset_date" in stats

    def test_budget_warning_levels(self):
        """Test warning level thresholds."""
        import tempfile

        from core.observability.telemetry import BudgetTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = BudgetTracker(workspace_path=Path(tmpdir))
            # Manually set limit for testing (default is 50.0)
            tracker.limit_usd = 100.0

            # Under 80% - no warning
            tracker._state.spent_today_usd = 50.0
            assert tracker.get_warning_level() is None

            # At 80% - warning
            tracker._state.spent_today_usd = 80.0
            assert tracker.get_warning_level() == "warning"

            # At 90% - critical
            tracker._state.spent_today_usd = 95.0
            assert tracker.get_warning_level() == "critical"

    def test_budget_reset_clears_counters(self):
        """Test reset_daily clears counters."""
        import tempfile

        from core.observability.telemetry import BudgetTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = BudgetTracker(workspace_path=Path(tmpdir))
            tracker._state.spent_today_usd = 25.0
            tracker._state.api_calls_today = 50

            tracker.reset_daily()

            assert tracker._state.spent_today_usd == 0.0
            assert tracker._state.api_calls_today == 0

    def test_budget_add_credit(self):
        """Test add_credit increases limit."""
        import tempfile

        from core.observability.telemetry import BudgetTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = BudgetTracker(workspace_path=Path(tmpdir))
            original_limit = tracker.limit_usd

            tracker.add_credit(25.0)

            assert tracker.limit_usd == original_limit + 25.0

    def test_parse_command_budget(self):
        """Test parsing /budget commands."""
        from core.interface_pkg.interface.commands import parse_command

        cmd, args = parse_command("/budget")
        assert cmd == "/budget"
        assert args == ""

        cmd, args = parse_command("/budget reset")
        assert cmd == "/budget"
        assert args == "reset"

        cmd, args = parse_command("/budget add 10")
        assert cmd == "/budget"
        assert args == "add 10"


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestPhase16Integration:
    """Integration tests for Phase 16 components."""

    def test_commands_tutorial_consistency(self):
        """Verify tutorial references valid commands."""
        from core.interface_pkg.interface.commands import SLASH_COMMANDS
        from core.interface_pkg.interface.tutorial import TUTORIAL_STEPS

        for step in TUTORIAL_STEPS:
            if step.suggested_command:
                # Extract base command
                cmd = step.suggested_command.split()[0]
                if cmd.startswith("/"):
                    # Find in SLASH_COMMANDS (may have args in key)
                    found = any(cmd in key for key in SLASH_COMMANDS)
                    assert found, f"Tutorial references unknown command: {cmd}"

    def test_help_references_all_categories(self):
        """Verify help message includes all categories."""
        from core.interface_pkg.interface.commands import COMMAND_CATEGORIES, get_help_message

        help_text = get_help_message()

        for category in COMMAND_CATEGORIES:
            # Category name (without emoji) should appear
            cat_name = category.split(" ", 1)[-1] if " " in category else category
            assert cat_name in help_text, f"Category '{cat_name}' missing from help"
