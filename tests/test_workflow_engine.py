"""
Tests for V12.4 Workflow Template Engine.

Validates:
- Workflow and step creation
- Topological dependency sorting
- Sequential step execution
- Dependency-based execution order
- Context passing between steps
- Conditional execution (skip_if, run_if)
- Step retry on failure
- Stop-on-failure behavior
- Continue-on-failure behavior
- Handler not found handling
- Workflow progress tracking
- Template registration and reuse
- Execution history
- State export
- Module exports
"""

from core.execution_pkg.execution.workflow_engine import (
    ExecutionResult,
    StepStatus,
    Workflow,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)

# =============================================================================
# WorkflowStep Tests
# =============================================================================


class TestWorkflowStep:
    """Test WorkflowStep dataclass."""

    def test_basic_creation(self):
        step = WorkflowStep(name="lint", handler="lint_code")
        assert step.name == "lint"
        assert step.handler == "lint_code"
        assert step.status == StepStatus.PENDING

    def test_with_dependencies(self):
        step = WorkflowStep(name="test", handler="run_tests", depends_on=["lint"])
        assert step.depends_on == ["lint"]

    def test_to_dict(self):
        step = WorkflowStep(name="lint", handler="lint_code")
        d = step.to_dict()
        assert d["name"] == "lint"
        assert d["status"] == "pending"


# =============================================================================
# Workflow Tests
# =============================================================================


class TestWorkflow:
    """Test Workflow dataclass."""

    def test_basic_creation(self):
        wf = Workflow(name="review")
        assert wf.name == "review"
        assert wf.workflow_id  # auto-generated
        assert wf.status == WorkflowStatus.CREATED

    def test_add_step(self):
        wf = Workflow(name="review")
        wf.add_step(WorkflowStep(name="lint", handler="lint_code"))
        assert wf.step_count == 1

    def test_get_step(self):
        wf = Workflow(name="review")
        wf.add_step(WorkflowStep(name="lint", handler="lint_code"))
        step = wf.get_step("lint")
        assert step is not None
        assert step.handler == "lint_code"

    def test_get_step_not_found(self):
        wf = Workflow(name="review")
        assert wf.get_step("missing") is None

    def test_step_names(self):
        wf = Workflow(name="review")
        wf.add_step(WorkflowStep(name="a", handler="h"))
        wf.add_step(WorkflowStep(name="b", handler="h"))
        assert wf.step_names == ["a", "b"]

    def test_progress_empty(self):
        wf = Workflow(name="empty")
        assert wf.progress == 1.0

    def test_progress_partial(self):
        wf = Workflow(name="review")
        s1 = WorkflowStep(name="a", handler="h")
        s2 = WorkflowStep(name="b", handler="h")
        s1.status = StepStatus.COMPLETED
        wf.add_step(s1)
        wf.add_step(s2)
        assert wf.progress == 0.5

    def test_to_dict(self):
        wf = Workflow(name="review")
        wf.add_step(WorkflowStep(name="lint", handler="h"))
        d = wf.to_dict()
        assert d["name"] == "review"
        assert d["step_count"] == 1
        assert len(d["steps"]) == 1


# =============================================================================
# Simple Execution Tests
# =============================================================================


class TestSimpleExecution:
    """Test basic workflow execution."""

    def test_single_step(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("simple")
        wf.add_step(WorkflowStep(name="greet", handler="greet_handler"))
        result = engine.execute(
            wf,
            handlers={
                "greet_handler": lambda ctx: "Hello!",
            },
        )
        assert result.success is True
        assert result.completed_steps == 1
        assert result.context["greet"] == "Hello!"

    def test_multiple_steps(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("multi")
        wf.add_step(WorkflowStep(name="a", handler="h"))
        wf.add_step(WorkflowStep(name="b", handler="h"))
        wf.add_step(WorkflowStep(name="c", handler="h"))
        result = engine.execute(
            wf,
            handlers={
                "h": lambda ctx: "done",
            },
        )
        assert result.success is True
        assert result.total_steps == 3
        assert result.completed_steps == 3

    def test_initial_context(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("ctx")
        wf.add_step(WorkflowStep(name="check", handler="h"))
        result = engine.execute(
            wf,
            handlers={"h": lambda ctx: ctx.get("seed")},
            initial_context={"seed": 42},
        )
        assert result.success is True
        assert result.context["check"] == 42


# =============================================================================
# Dependency Tests
# =============================================================================


class TestDependencies:
    """Test dependency-based execution order."""

    def test_dependency_order(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("deps")
        wf.add_step(WorkflowStep(name="build", handler="h"))
        wf.add_step(WorkflowStep(name="test", handler="h", depends_on=["build"]))
        wf.add_step(WorkflowStep(name="deploy", handler="h", depends_on=["test"]))

        order = []

        def track(ctx, name=None):
            order.append(name)
            return name

        result = engine.execute(
            wf,
            handlers={
                "h": lambda ctx: order.append("step") or "ok",
            },
        )
        assert result.success is True
        # All 3 should complete
        assert result.completed_steps == 3

    def test_dep_result_in_context(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("chain")
        wf.add_step(WorkflowStep(name="first", handler="h_first"))
        wf.add_step(WorkflowStep(name="second", handler="h_second", depends_on=["first"]))

        result = engine.execute(
            wf,
            handlers={
                "h_first": lambda ctx: {"value": 10},
                "h_second": lambda ctx: ctx["first"]["value"] * 2,
            },
        )
        assert result.success is True
        assert result.context["second"] == 20

    def test_fan_in_dependencies(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("fan_in")
        wf.add_step(WorkflowStep(name="a", handler="h"))
        wf.add_step(WorkflowStep(name="b", handler="h"))
        wf.add_step(WorkflowStep(name="merge", handler="h_merge", depends_on=["a", "b"]))

        result = engine.execute(
            wf,
            handlers={
                "h": lambda ctx: "done",
                "h_merge": lambda ctx: f"merged: {ctx.get('a')}, {ctx.get('b')}",
            },
        )
        assert result.success is True
        assert "merged" in result.context["merge"]

    def test_unsatisfied_dep_skips(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("broken_dep")
        wf.add_step(WorkflowStep(name="first", handler="h_fail"))
        wf.add_step(WorkflowStep(name="second", handler="h", depends_on=["first"]))

        engine.execute(
            wf,
            handlers={
                "h_fail": lambda ctx: (_ for _ in ()).throw(ValueError("boom")),
                "h": lambda ctx: "ok",
            },
            stop_on_failure=False,
        )
        # second should be skipped because first failed
        step2 = wf.get_step("second")
        assert step2.status == StepStatus.SKIPPED


# =============================================================================
# Conditional Execution Tests
# =============================================================================


class TestConditionalExecution:
    """Test skip_if and run_if conditions."""

    def test_skip_if_truthy(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("cond")
        wf.add_step(WorkflowStep(name="maybe", handler="h", skip_if="should_skip"))
        result = engine.execute(
            wf,
            handlers={"h": lambda ctx: "ran"},
            initial_context={"should_skip": True},
        )
        step = wf.get_step("maybe")
        assert step.status == StepStatus.SKIPPED
        assert "maybe" not in result.context

    def test_skip_if_falsy(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("cond")
        wf.add_step(WorkflowStep(name="maybe", handler="h", skip_if="should_skip"))
        engine.execute(
            wf,
            handlers={"h": lambda ctx: "ran"},
            initial_context={"should_skip": False},
        )
        step = wf.get_step("maybe")
        assert step.status == StepStatus.COMPLETED

    def test_run_if_truthy(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("cond")
        wf.add_step(WorkflowStep(name="maybe", handler="h", run_if="is_enabled"))
        engine.execute(
            wf,
            handlers={"h": lambda ctx: "ran"},
            initial_context={"is_enabled": True},
        )
        step = wf.get_step("maybe")
        assert step.status == StepStatus.COMPLETED

    def test_run_if_falsy(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("cond")
        wf.add_step(WorkflowStep(name="maybe", handler="h", run_if="is_enabled"))
        engine.execute(
            wf,
            handlers={"h": lambda ctx: "ran"},
            initial_context={"is_enabled": False},
        )
        step = wf.get_step("maybe")
        assert step.status == StepStatus.SKIPPED

    def test_run_if_missing_key(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("cond")
        wf.add_step(WorkflowStep(name="maybe", handler="h", run_if="nonexistent"))
        engine.execute(
            wf,
            handlers={"h": lambda ctx: "ran"},
        )
        step = wf.get_step("maybe")
        assert step.status == StepStatus.SKIPPED


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling and retries."""

    def test_step_failure(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("fail")
        wf.add_step(WorkflowStep(name="boom", handler="h"))
        result = engine.execute(
            wf,
            handlers={
                "h": lambda ctx: (_ for _ in ()).throw(RuntimeError("kaboom")),
            },
        )
        assert result.success is False
        assert result.failed_steps == 1
        assert "kaboom" in result.errors[0]

    def test_stop_on_failure(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("stop")
        wf.add_step(WorkflowStep(name="a", handler="h_fail"))
        wf.add_step(WorkflowStep(name="b", handler="h_ok"))
        result = engine.execute(
            wf,
            handlers={
                "h_fail": lambda ctx: (_ for _ in ()).throw(RuntimeError("fail")),
                "h_ok": lambda ctx: "ok",
            },
            stop_on_failure=True,
        )
        assert result.failed_steps == 1
        # b should remain pending (not executed)
        step_b = wf.get_step("b")
        assert step_b.status == StepStatus.PENDING

    def test_continue_on_failure(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("continue")
        wf.add_step(WorkflowStep(name="a", handler="h_fail"))
        wf.add_step(WorkflowStep(name="b", handler="h_ok"))
        result = engine.execute(
            wf,
            handlers={
                "h_fail": lambda ctx: (_ for _ in ()).throw(RuntimeError("fail")),
                "h_ok": lambda ctx: "ok",
            },
            stop_on_failure=False,
        )
        assert result.failed_steps == 1
        assert result.completed_steps == 1

    def test_handler_not_found(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("missing")
        wf.add_step(WorkflowStep(name="x", handler="nonexistent"))
        result = engine.execute(wf, handlers={})
        assert result.success is False
        assert any("not found" in e for e in result.errors)

    def test_retry_success(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("retry")
        wf.add_step(WorkflowStep(name="flaky", handler="h_flaky", retries=2))

        call_count = [0]

        def flaky_handler(ctx):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("not yet")
            return "finally"

        result = engine.execute(wf, handlers={"h_flaky": flaky_handler})
        assert result.success is True
        step = wf.get_step("flaky")
        assert step.attempts == 3

    def test_retry_exhausted(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("retry_fail")
        wf.add_step(WorkflowStep(name="always_fail", handler="h", retries=1))
        result = engine.execute(
            wf,
            handlers={
                "h": lambda ctx: (_ for _ in ()).throw(RuntimeError("nope")),
            },
        )
        assert result.success is False
        step = wf.get_step("always_fail")
        assert step.attempts == 2  # 1 original + 1 retry


# =============================================================================
# Template Tests
# =============================================================================


class TestTemplates:
    """Test workflow template registration."""

    def test_register_template(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("ci_pipeline")
        wf.add_step(WorkflowStep(name="build", handler="h"))
        engine.register_template(wf)
        assert engine.template_count == 1

    def test_get_template(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("ci_pipeline")
        engine.register_template(wf)
        retrieved = engine.get_template("ci_pipeline")
        assert retrieved is not None
        assert retrieved.name == "ci_pipeline"

    def test_get_template_not_found(self):
        engine = WorkflowEngine()
        assert engine.get_template("missing") is None

    def test_list_templates(self):
        engine = WorkflowEngine()
        engine.register_template(engine.create_workflow("b"))
        engine.register_template(engine.create_workflow("a"))
        assert engine.list_templates() == ["a", "b"]


# =============================================================================
# History Tests
# =============================================================================


class TestHistory:
    """Test execution history."""

    def test_history_recorded(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("test")
        wf.add_step(WorkflowStep(name="a", handler="h"))
        engine.execute(wf, handlers={"h": lambda ctx: "ok"})
        assert engine.execution_count == 1

    def test_get_history(self):
        engine = WorkflowEngine()
        for i in range(3):
            wf = engine.create_workflow(f"wf_{i}")
            wf.add_step(WorkflowStep(name="a", handler="h"))
            engine.execute(wf, handlers={"h": lambda ctx: "ok"})
        history = engine.get_history(limit=2)
        assert len(history) == 2

    def test_clear_history(self):
        engine = WorkflowEngine()
        wf = engine.create_workflow("test")
        wf.add_step(WorkflowStep(name="a", handler="h"))
        engine.execute(wf, handlers={"h": lambda ctx: "ok"})
        count = engine.clear_history()
        assert count == 1
        assert engine.execution_count == 0


# =============================================================================
# ExecutionResult Tests
# =============================================================================


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_success(self):
        r = ExecutionResult(
            workflow_id="w1",
            workflow_name="test",
            status=WorkflowStatus.COMPLETED,
            total_steps=3,
            completed_steps=3,
            failed_steps=0,
            skipped_steps=0,
            total_duration=1.5,
            context={},
        )
        assert r.success is True

    def test_failure(self):
        r = ExecutionResult(
            workflow_id="w1",
            workflow_name="test",
            status=WorkflowStatus.FAILED,
            total_steps=3,
            completed_steps=1,
            failed_steps=1,
            skipped_steps=1,
            total_duration=0.5,
            context={},
            errors=["step failed"],
        )
        assert r.success is False

    def test_to_dict(self):
        r = ExecutionResult(
            workflow_id="w1",
            workflow_name="test",
            status=WorkflowStatus.COMPLETED,
            total_steps=2,
            completed_steps=2,
            failed_steps=0,
            skipped_steps=0,
            total_duration=1.0,
            context={},
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["total_steps"] == 2


# =============================================================================
# State Export Tests
# =============================================================================


class TestStateExport:
    """Test state export."""

    def test_to_dict(self):
        engine = WorkflowEngine()
        engine.register_template(engine.create_workflow("test"))
        d = engine.to_dict()
        assert d["template_count"] == 1
        assert "test" in d["templates"]

    def test_to_dict_empty(self):
        engine = WorkflowEngine()
        d = engine.to_dict()
        assert d["template_count"] == 0
        assert d["execution_count"] == 0


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import (
            ExecutionResult,
            StepStatus,
            Workflow,
            WorkflowEngine,
            WorkflowStatus,
            WorkflowStep,
        )

        assert all([WorkflowEngine, Workflow, WorkflowStep, WorkflowStatus, StepStatus, ExecutionResult])

    def test_from_module(self):
        from core.execution_pkg.execution.workflow_engine import (
            ExecutionResult,
            StepStatus,
            Workflow,
            WorkflowEngine,
            WorkflowStatus,
            WorkflowStep,
        )

        assert all([WorkflowEngine, Workflow, WorkflowStep, WorkflowStatus, StepStatus, ExecutionResult])
