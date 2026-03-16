"""
Tests for BudgetService (V9.1 Service Layer)

These tests verify the BudgetService extracted from repl.py works correctly.
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestBudgetService:
    """Test BudgetService functionality."""

    @pytest.fixture
    def mock_console(self):
        """Create a mock console."""
        console = MagicMock()
        console.print = MagicMock()
        console.print_error = MagicMock()
        console.console = MagicMock()
        console.console.print = MagicMock()
        return console

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            yield workspace

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.budget_limit_usd = 10.0
        config.budget_warning_threshold = 0.8
        config.budget_critical_threshold = 0.9
        return config

    @pytest.fixture
    def budget_service(self, temp_workspace, mock_console, mock_config):
        """Create a BudgetService instance."""
        from core.observability.telemetry.service import BudgetService

        return BudgetService(workspace_path=temp_workspace, console=mock_console, config=mock_config)

    @pytest.fixture
    def workspace_with_budget(self, temp_workspace):
        """Create workspace with budget tracking data."""
        budget_file = temp_workspace / ".nexus" / "budget_state.json"
        budget_file.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "spent_today_usd": 2.5,
            "limit_usd": 10.0,
            "api_calls_today": 15,
            "last_reset": datetime.now(UTC).strftime("%Y-%m-%d"),
        }

        budget_file.write_text(json.dumps(state), encoding="utf-8")
        return temp_workspace

    # ==================== status() tests ====================

    def test_status_returns_stats(self, budget_service, mock_console):
        """Test status returns budget statistics."""
        result = budget_service.status()

        assert result.success is True
        assert result.data is not None
        # Console should have been called with status display
        assert mock_console.console.print.called

    def test_status_shows_warning_level(self, workspace_with_budget, mock_console, mock_config):
        """Test status shows correct warning level."""
        from core.observability.telemetry.service import BudgetService

        service = BudgetService(workspace_path=workspace_with_budget, console=mock_console, config=mock_config)

        result = service.status()
        assert result.success is True

    # ==================== reset() tests ====================

    def test_reset_cancelled_by_user(self, budget_service, mock_console):
        """Test reset cancelled when user says no."""
        with patch("builtins.input", return_value="no"):
            result = budget_service.reset(confirmed=False)

        assert result.success is False
        assert result.message == "Cancelled by user"

    def test_reset_confirmed_by_flag(self, budget_service, mock_console):
        """Test reset with confirmed=True skips prompt."""
        result = budget_service.reset(confirmed=True)

        assert result.success is True
        assert result.message == "Budget reset"
        mock_console.print.assert_any_call("\n[green]Budget counter reset successfully.[/green]")

    def test_reset_confirmed_by_input(self, budget_service, mock_console):
        """Test reset confirmed via user input."""
        with patch("builtins.input", return_value="yes"):
            result = budget_service.reset(confirmed=False)

        assert result.success is True

    def test_reset_keyboard_interrupt(self, budget_service, mock_console):
        """Test reset handles KeyboardInterrupt."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = budget_service.reset(confirmed=False)

        assert result.success is False
        assert result.message == "Cancelled by user"

    # ==================== add_credit() tests ====================

    def test_add_credit_positive(self, budget_service, mock_console):
        """Test adding positive credit."""
        result = budget_service.add_credit(5.0)

        assert result.success is True
        assert result.data is not None
        assert "new_limit" in result.data
        mock_console.print.assert_any_call("\n[green]Added $5.00 to daily budget.[/green]")

    def test_add_credit_zero(self, budget_service, mock_console):
        """Test adding zero credit fails."""
        result = budget_service.add_credit(0)

        assert result.success is False
        assert "positive" in result.error
        mock_console.print_error.assert_called_with("Amount must be positive")

    def test_add_credit_negative(self, budget_service, mock_console):
        """Test adding negative credit fails."""
        result = budget_service.add_credit(-5.0)

        assert result.success is False
        assert "positive" in result.error

    # ==================== history() tests ====================

    def test_history_no_data(self, budget_service, mock_console):
        """Test history with no API calls."""
        result = budget_service.history()

        assert result.success is True
        assert result.data["count"] == 0
        mock_console.print.assert_any_call("[dim]No API calls recorded in the last 24 hours.[/dim]\n")

    def test_history_with_data(self, temp_workspace, mock_console, mock_config):
        """Test history with API call data."""
        from core.observability.telemetry.service import BudgetService

        # Create telemetry file with API calls
        telemetry_file = temp_workspace / "telemetry.jsonl"
        events = [
            {
                "type": "api_call",
                "session_id": "test",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "provider": "anthropic",
                    "model": "claude-3",
                    "tokens_in": 100,
                    "tokens_out": 200,
                    "success": True,
                },
            }
        ]
        with open(telemetry_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        service = BudgetService(workspace_path=temp_workspace, console=mock_console, config=mock_config)

        result = service.history()

        assert result.success is True
        assert result.data["count"] == 1


class TestGetBudgetService:
    """Test _get_budget_service helper function."""

    def test_get_service_from_extras(self):
        """Test getting service from context extras."""
        from core.observability.telemetry.service import _get_budget_service

        mock_service = MagicMock()
        mock_context = MagicMock()
        mock_context.extras = {"budget_service": mock_service}

        result = _get_budget_service(mock_context)
        assert result is mock_service

    def test_get_service_creates_new(self):
        """Test creating new service when not in extras."""
        from core.observability.telemetry.service import BudgetService, _get_budget_service

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_context = MagicMock()
            mock_context.extras = {"workspace_path": Path(tmpdir)}
            mock_context.console = MagicMock()
            mock_context.config = MagicMock()

            result = _get_budget_service(mock_context)
            assert isinstance(result, BudgetService)
