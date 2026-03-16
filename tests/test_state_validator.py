"""
Tests for V12.4 FSM State Validator.

Validates:
- ValidationResult to_dict
- ValidatorStats to_dict
- Transition matrix (define, add, remove, get)
- Invariants (add, remove, check)
- Validation (valid, invalid, strict, lenient, invariants)
- can_transition, is_terminal, get_reachable
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.fsm.state_validator import (
    StateValidator,
    ValidationResult,
    ValidatorStats,
    get_state_validator,
    reset_state_validator,
)

# =============================================================================
# ValidationResult Tests
# =============================================================================


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_valid(self):
        r = ValidationResult(valid=True, from_state="idle", to_state="running")
        assert r.valid is True

    def test_invalid(self):
        r = ValidationResult(valid=False, error="Bad transition")
        assert r.valid is False

    def test_to_dict(self):
        r = ValidationResult(valid=True, from_state="a", to_state="b", warnings=["w1"])
        d = r.to_dict()
        assert d["valid"] is True
        assert d["warnings"] == ["w1"]


# =============================================================================
# ValidatorStats Tests
# =============================================================================


class TestValidatorStats:
    """Test ValidatorStats dataclass."""

    def test_to_dict(self):
        s = ValidatorStats(
            defined_states=5,
            total_transitions_defined=10,
            total_invariants=2,
            total_validations=100,
            total_valid=90,
            total_invalid=10,
        )
        d = s.to_dict()
        assert d["defined_states"] == 5
        assert d["total_valid"] == 90


# =============================================================================
# Transition Matrix Tests
# =============================================================================


class TestTransitionMatrix:
    """Test transition matrix management."""

    def test_define_transition(self):
        v = StateValidator()
        v.define_transition("idle", {"running", "error"})
        assert v.get_valid_targets("idle") == {"running", "error"}

    def test_define_transitions_bulk(self):
        v = StateValidator()
        v.define_transitions(
            {
                "idle": {"running"},
                "running": {"idle", "error"},
            }
        )
        assert v.state_count == 2

    def test_add_transition(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        v.add_transition("idle", "error")
        assert "error" in v.get_valid_targets("idle")

    def test_add_transition_new_state(self):
        v = StateValidator()
        v.add_transition("new", "target")
        assert v.get_valid_targets("new") == {"target"}

    def test_remove_transition(self):
        v = StateValidator()
        v.define_transition("idle", {"running", "error"})
        assert v.remove_transition("idle", "error") is True
        assert "error" not in v.get_valid_targets("idle")

    def test_remove_transition_not_found(self):
        v = StateValidator()
        assert v.remove_transition("missing", "target") is False

    def test_get_valid_targets_empty(self):
        v = StateValidator()
        assert v.get_valid_targets("unknown") == set()

    def test_get_all_states(self):
        v = StateValidator()
        v.define_transitions(
            {
                "idle": {"running"},
                "running": {"done"},
            }
        )
        states = v.get_all_states()
        assert states == {"idle", "running", "done"}


# =============================================================================
# Invariant Tests
# =============================================================================


class TestInvariants:
    """Test invariant management."""

    def test_add_invariant(self):
        v = StateValidator()
        v.add_invariant(
            "no_empty_tasks",
            "running",
            lambda ctx: len(ctx.get("tasks", [])) > 0,
            description="Running state must have tasks",
        )
        violations = v.check_invariants("running", {"tasks": []})
        assert len(violations) == 1
        assert "no_empty_tasks" in violations[0]

    def test_invariant_passes(self):
        v = StateValidator()
        v.add_invariant(
            "has_tasks",
            "running",
            lambda ctx: len(ctx.get("tasks", [])) > 0,
        )
        violations = v.check_invariants("running", {"tasks": ["t1"]})
        assert len(violations) == 0

    def test_invariant_error_handled(self):
        v = StateValidator()
        v.add_invariant(
            "bad_check",
            "running",
            lambda ctx: ctx["missing_key"],  # Will raise KeyError
        )
        violations = v.check_invariants("running", {})
        assert len(violations) == 1
        assert "error" in violations[0].lower()

    def test_remove_invariant(self):
        v = StateValidator()
        v.add_invariant("test_inv", "running", lambda ctx: True)
        assert v.remove_invariant("test_inv") is True
        assert v.check_invariants("running", {}) == []

    def test_remove_invariant_not_found(self):
        v = StateValidator()
        assert v.remove_invariant("missing") is False

    def test_no_invariants_for_state(self):
        v = StateValidator()
        assert v.check_invariants("unknown", {}) == []


# =============================================================================
# Validation Tests
# =============================================================================


class TestValidation:
    """Test transition validation."""

    def test_valid_transition(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        result = v.validate("idle", "running")
        assert result.valid is True
        assert result.from_state == "idle"
        assert result.to_state == "running"

    def test_invalid_transition(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        result = v.validate("idle", "error")
        assert result.valid is False
        assert "Invalid transition" in result.error

    def test_strict_undefined_state(self):
        v = StateValidator(strict=True)
        v.define_transition("idle", {"running"})
        result = v.validate("unknown", "running")
        assert result.valid is False
        assert "No transitions defined" in result.error

    def test_lenient_undefined_state(self):
        v = StateValidator(strict=False)
        v.define_transition("idle", {"running"})
        result = v.validate("unknown", "running")
        assert result.valid is True
        assert len(result.warnings) > 0

    def test_validate_with_invariant_pass(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        v.add_invariant("has_tasks", "running", lambda ctx: ctx.get("tasks"))
        result = v.validate("idle", "running", context={"tasks": ["t1"]})
        assert result.valid is True

    def test_validate_with_invariant_fail_strict(self):
        v = StateValidator(strict=True)
        v.define_transition("idle", {"running"})
        v.add_invariant("has_tasks", "running", lambda ctx: ctx.get("tasks"))
        result = v.validate("idle", "running", context={"tasks": []})
        assert result.valid is False
        assert "Invariant" in result.error

    def test_validate_with_invariant_fail_lenient(self):
        v = StateValidator(strict=False)
        v.define_transition("idle", {"running"})
        v.add_invariant("has_tasks", "running", lambda ctx: ctx.get("tasks"))
        result = v.validate("idle", "running", context={"tasks": []})
        assert result.valid is True
        assert len(result.warnings) > 0

    def test_validate_no_context_skips_invariants(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        v.add_invariant("check", "running", lambda ctx: False)  # Would fail
        result = v.validate("idle", "running")  # No context
        assert result.valid is True


# =============================================================================
# Quick Check Tests
# =============================================================================


class TestQuickChecks:
    """Test quick state checks."""

    def test_can_transition(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        assert v.can_transition("idle", "running") is True
        assert v.can_transition("idle", "error") is False

    def test_can_transition_undefined_strict(self):
        v = StateValidator(strict=True)
        assert v.can_transition("unknown", "any") is False

    def test_can_transition_undefined_lenient(self):
        v = StateValidator(strict=False)
        assert v.can_transition("unknown", "any") is True

    def test_is_terminal(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        v.define_transition("done", set())
        assert v.is_terminal("done") is True
        assert v.is_terminal("idle") is False

    def test_is_terminal_undefined(self):
        v = StateValidator()
        assert v.is_terminal("unknown") is True

    def test_get_reachable(self):
        v = StateValidator()
        v.define_transitions(
            {
                "idle": {"running"},
                "running": {"done", "error"},
                "error": {"idle"},
            }
        )
        reachable = v.get_reachable("idle")
        assert reachable == {"running", "done", "error", "idle"}

    def test_get_reachable_no_targets(self):
        v = StateValidator()
        v.define_transition("end", set())
        assert v.get_reachable("end") == set()


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test validator statistics."""

    def test_initial_stats(self):
        v = StateValidator()
        stats = v.get_stats()
        assert stats.total_validations == 0

    def test_stats_after_validations(self):
        v = StateValidator()
        v.define_transition("idle", {"running"})
        v.validate("idle", "running")
        v.validate("idle", "error")
        stats = v.get_stats()
        assert stats.total_validations == 2
        assert stats.total_valid == 1
        assert stats.total_invalid == 1

    def test_stats_to_dict(self):
        v = StateValidator()
        d = v.get_stats().to_dict()
        assert "defined_states" in d
        assert "total_validations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_state_count(self):
        v = StateValidator()
        v.define_transition("a", {"b"})
        v.define_transition("b", {"c"})
        assert v.state_count == 2

    def test_strict_property(self):
        v = StateValidator(strict=False)
        assert v.strict is False

    def test_clear(self):
        v = StateValidator()
        v.define_transition("a", {"b"})
        v.add_invariant("test", "b", lambda ctx: True)
        v.validate("a", "b")
        v.clear()
        assert v.state_count == 0
        assert v.get_stats().total_validations == 0

    def test_to_dict(self):
        v = StateValidator()
        v.define_transition("a", {"b"})
        d = v.to_dict()
        assert d["state_count"] == 1
        assert d["strict"] is True
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global state validator."""

    def test_get(self):
        reset_state_validator()
        v = get_state_validator()
        assert isinstance(v, StateValidator)

    def test_singleton(self):
        reset_state_validator()
        v1 = get_state_validator()
        v2 = get_state_validator()
        assert v1 is v2

    def test_reset(self):
        reset_state_validator()
        v1 = get_state_validator()
        reset_state_validator()
        v2 = get_state_validator()
        assert v1 is not v2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_fsm_package(self):
        from core.fsm import (
            StateValidationResult,
            StateValidator,
            ValidatorStats,
            get_state_validator,
            reset_state_validator,
        )

        assert all(
            [
                StateValidator,
                StateValidationResult,
                ValidatorStats,
                get_state_validator,
                reset_state_validator,
            ]
        )

    def test_from_module(self):
        from core.fsm.state_validator import (
            MAX_STATES,
        )

        assert MAX_STATES == 500
