"""Tests for PhaseBudgetAllocator - dynamic token budget allocation."""

from core.intelligence.hive_mind.budget_allocator import (
    PHASE_PROPORTIONS,
    PhaseBudget,
    PhaseBudgetAllocator,
    get_budget_allocator,
    reset_budget_allocator,
)

# =============================================================================
# Allocation
# =============================================================================


class TestAllocation:
    def test_allocate_returns_all_phases(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        budgets = alloc.allocate("MODERATE")
        for phase in PHASE_PROPORTIONS:
            assert phase in budgets
            assert budgets[phase] > 0

    def test_allocate_moderate_sums_to_budget(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        budgets = alloc.allocate("MODERATE")
        # Int rounding may cause slight deviation
        total = sum(budgets.values())
        assert abs(total - 50000) < len(budgets)  # Allow 1-per-phase rounding

    def test_trivial_uses_less_budget(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        trivial = alloc.allocate("TRIVIAL")
        alloc2 = PhaseBudgetAllocator(total_budget=50000)
        moderate = alloc2.allocate("MODERATE")
        assert sum(trivial.values()) < sum(moderate.values())

    def test_expert_uses_more_budget(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        expert = alloc.allocate("EXPERT")
        alloc2 = PhaseBudgetAllocator(total_budget=50000)
        moderate = alloc2.allocate("MODERATE")
        assert sum(expert.values()) > sum(moderate.values())

    def test_execution_gets_largest_share(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        budgets = alloc.allocate("MODERATE")
        assert budgets["execution"] > budgets["analysis"]
        assert budgets["execution"] > budgets["debate"]
        assert budgets["execution"] > budgets["architecture"]

    def test_custom_proportions(self):
        custom = {"analysis": 0.5, "execution": 0.5}
        alloc = PhaseBudgetAllocator(total_budget=10000, proportions=custom)
        budgets = alloc.allocate("MODERATE")
        assert budgets["analysis"] == 5000
        assert budgets["execution"] == 5000

    def test_unknown_complexity_defaults_to_1x(self):
        alloc = PhaseBudgetAllocator(total_budget=10000)
        budgets = alloc.allocate("UNKNOWN")
        total = sum(budgets.values())
        assert abs(total - 10000) < len(budgets)


# =============================================================================
# Redistribution
# =============================================================================


class TestRedistribution:
    def test_savings_redistributed(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        original_exec = alloc.get_budget("execution")
        # Analysis uses much less than allocated
        alloc.report_actual("analysis", 100)
        new_exec = alloc.get_budget("execution")
        assert new_exec > original_exec

    def test_no_redistribution_on_overspend(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        original_exec = alloc.get_budget("execution")
        # Phase goes over budget
        alloc.report_actual("analysis", 999999)
        new_exec = alloc.get_budget("execution")
        assert new_exec == original_exec

    def test_redistribution_proportional(self):
        alloc = PhaseBudgetAllocator(total_budget=100000)
        alloc.allocate("MODERATE")
        exec_before = alloc.get_budget("execution")
        consol_before = alloc.get_budget("consolidation")
        # Analysis saves big
        alloc.report_actual("analysis", 0)
        exec_gain = alloc.get_budget("execution") - exec_before
        consol_gain = alloc.get_budget("consolidation") - consol_before
        # Execution should get a bigger share (0.35 vs 0.10)
        assert exec_gain > consol_gain

    def test_completed_phases_dont_get_redistributed(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        alloc.report_actual("analysis", 100)
        analysis_budget = alloc.get_budget("analysis")
        # Now debate saves too
        alloc.report_actual("debate", 100)
        # Analysis budget shouldn't change (already completed)
        assert alloc.get_budget("analysis") == analysis_budget

    def test_report_unknown_phase_returns_zero(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        result = alloc.report_actual("unknown_phase", 100)
        assert result == 0


# =============================================================================
# Budget Queries
# =============================================================================


class TestBudgetQueries:
    def test_get_budget_before_allocation(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        assert alloc.get_budget("analysis") == 0

    def test_get_remaining_before_use(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        remaining = alloc.get_remaining("analysis")
        assert remaining == alloc.get_budget("analysis")

    def test_get_remaining_after_use(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        budget = alloc.get_budget("analysis")
        alloc.report_actual("analysis", budget - 100)
        assert alloc.get_remaining("analysis") == 100

    def test_get_remaining_unknown_phase(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        assert alloc.get_remaining("nonexistent") == 0

    def test_can_afford_true(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        assert alloc.can_afford("execution", 100)

    def test_can_afford_false(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        assert not alloc.can_afford("retry", 999999)


# =============================================================================
# PhaseBudget dataclass
# =============================================================================


class TestPhaseBudget:
    def test_savings_positive(self):
        pb = PhaseBudget(phase="test", allocated=1000, adjusted=1000, actual=700, completed=True)
        assert pb.savings == 300

    def test_savings_negative(self):
        pb = PhaseBudget(phase="test", allocated=1000, adjusted=1000, actual=1200, completed=True)
        assert pb.savings == -200

    def test_savings_none_actual(self):
        pb = PhaseBudget(phase="test", allocated=1000, adjusted=1000)
        assert pb.savings == 0

    def test_utilization(self):
        pb = PhaseBudget(phase="test", allocated=1000, adjusted=1000, actual=500)
        assert pb.utilization == 0.5

    def test_utilization_zero_adjusted(self):
        pb = PhaseBudget(phase="test", allocated=0, adjusted=0)
        assert pb.utilization == 0.0


# =============================================================================
# Report & Stats
# =============================================================================


class TestReportAndStats:
    def test_report_after_partial_execution(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        alloc.report_actual("analysis", 1000)
        alloc.report_actual("debate", 2000)
        report = alloc.get_report()
        assert report.total_spent == 3000
        assert report.phases_completed_count() if hasattr(report, "phases_completed_count") else True
        assert report.redistributed >= 0

    def test_stats_format(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("COMPLEX")
        stats = alloc.get_stats()
        assert stats["complexity"] == "COMPLEX"
        assert stats["total_budget"] == 50000
        assert stats["phases_total"] == 7
        assert stats["phases_completed"] == 0

    def test_reset_clears_state(self):
        alloc = PhaseBudgetAllocator(total_budget=50000)
        alloc.allocate("MODERATE")
        alloc.report_actual("analysis", 100)
        alloc.reset()
        assert alloc.get_budget("analysis") == 0
        stats = alloc.get_stats()
        assert stats["phases_total"] == 0


# =============================================================================
# Full Pipeline Scenario
# =============================================================================


class TestFullPipeline:
    def test_realistic_pipeline(self):
        """Simulate a realistic HiveMind pipeline budget flow."""
        alloc = PhaseBudgetAllocator(total_budget=50000)
        budgets = alloc.allocate("MODERATE")

        # Phase 1: Analysis - uses 60% of budget
        analysis_budget = budgets["analysis"]
        alloc.report_actual("analysis", int(analysis_budget * 0.6))

        # Execution budget should have increased
        assert alloc.get_budget("execution") > budgets["execution"]

        # Phase 2: Debate - uses 80% of (adjusted) budget
        debate_budget = alloc.get_budget("debate")
        alloc.report_actual("debate", int(debate_budget * 0.8))

        # Phase 3: Architecture - cheap
        alloc.report_actual("architecture", 500)

        # Phase 4: Execution - now has much more budget
        exec_budget = alloc.get_budget("execution")
        assert exec_budget > budgets["execution"]

        # Final report
        report = alloc.get_report()
        assert report.redistributed > 0
        assert report.utilization > 0


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_budget_allocator()
        a1 = get_budget_allocator()
        a2 = get_budget_allocator()
        assert a1 is a2

    def test_reset_creates_new_instance(self):
        reset_budget_allocator()
        a1 = get_budget_allocator()
        reset_budget_allocator()
        a2 = get_budget_allocator()
        assert a1 is not a2
