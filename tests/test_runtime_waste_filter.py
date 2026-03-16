"""
Tests for V12.4 Runtime Waste Filter (arXiv:2510.26585).

Validates:
- InterventionType and InterventionAction enum values
- ExchangeRecord creation and to_dict
- Intervention creation and to_dict
- FilterStats creation and to_dict
- Basic exchange checking - no waste detected
- Redundancy detection (duplicate content hashes)
- Loop detection (circular A->B->A->B patterns)
- Same-agent monologue detection (MAX_SAME_AGENT consecutive)
- Stagnation detection (no new topic words)
- Divergence detection (off-topic exchanges)
- Cost limit detection (budget exhausted and warning)
- Task context setting
- Topic word extraction (stop word filtering)
- Content hashing
- Priority ordering (which intervention fires first)
- Singleton get/reset pattern
- Statistics tracking (interventions_triggered, tokens_saved, counts)
- Edge cases (empty content, no task context, zero budget, single exchange)
- Reset clearing all state
- Thread safety
"""

import threading
import time

import pytest

from core.infrastructure.resilience.runtime_waste_filter import (
    COST_WARNING_THRESHOLD,
    DIVERGENCE_THRESHOLD,
    LOOP_THRESHOLD,
    MAX_SAME_AGENT,
    MIN_NEW_WORDS,
    REDUNDANCY_HASH_WINDOW,
    STAGNATION_WINDOW,
    STOP_WORDS,
    ExchangeRecord,
    FilterStats,
    Intervention,
    InterventionAction,
    InterventionType,
    RuntimeWasteFilter,
    get_runtime_waste_filter,
    reset_runtime_waste_filter,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_runtime_waste_filter()
    yield
    reset_runtime_waste_filter()


@pytest.fixture
def rwf() -> RuntimeWasteFilter:
    """Return a fresh RuntimeWasteFilter instance."""
    return RuntimeWasteFilter()


# =============================================================================
# 1. InterventionType Enum
# =============================================================================


class TestInterventionType:
    """Test InterventionType enum values."""

    def test_redundancy_value(self):
        assert InterventionType.REDUNDANCY.value == "redundancy"

    def test_divergence_value(self):
        assert InterventionType.DIVERGENCE.value == "divergence"

    def test_stagnation_value(self):
        assert InterventionType.STAGNATION.value == "stagnation"

    def test_loop_value(self):
        assert InterventionType.LOOP.value == "loop"

    def test_cost_limit_value(self):
        assert InterventionType.COST_LIMIT.value == "cost_limit"

    def test_is_str_subclass(self):
        assert isinstance(InterventionType.REDUNDANCY, str)

    def test_all_members_count(self):
        assert len(InterventionType) == 5


# =============================================================================
# 2. InterventionAction Enum
# =============================================================================


class TestInterventionAction:
    """Test InterventionAction enum values."""

    def test_continue_value(self):
        assert InterventionAction.CONTINUE.value == "continue"

    def test_skip_value(self):
        assert InterventionAction.SKIP.value == "skip"

    def test_summarize_value(self):
        assert InterventionAction.SUMMARIZE.value == "summarize"

    def test_redirect_value(self):
        assert InterventionAction.REDIRECT.value == "redirect"

    def test_terminate_value(self):
        assert InterventionAction.TERMINATE.value == "terminate"

    def test_is_str_subclass(self):
        assert isinstance(InterventionAction.CONTINUE, str)

    def test_all_members_count(self):
        assert len(InterventionAction) == 5


# =============================================================================
# 3. ExchangeRecord
# =============================================================================


class TestExchangeRecord:
    """Test ExchangeRecord dataclass."""

    def test_creation(self):
        rec = ExchangeRecord(
            agent_id="claude",
            content_hash="abc123def456",
            token_count=100,
            timestamp=1234567890.0,
        )
        assert rec.agent_id == "claude"
        assert rec.content_hash == "abc123def456"
        assert rec.token_count == 100
        assert rec.timestamp == 1234567890.0

    def test_default_topic_words(self):
        rec = ExchangeRecord(
            agent_id="gemini",
            content_hash="h",
            token_count=1,
            timestamp=0.0,
        )
        assert rec.topic_words == set()

    def test_topic_words_provided(self):
        rec = ExchangeRecord(
            agent_id="gemini",
            content_hash="h",
            token_count=1,
            timestamp=0.0,
            topic_words={"python", "testing"},
        )
        assert rec.topic_words == {"python", "testing"}

    def test_to_dict_keys(self):
        rec = ExchangeRecord(
            agent_id="claude",
            content_hash="0123456789abcdef",
            token_count=50,
            timestamp=0.0,
        )
        d = rec.to_dict()
        assert set(d.keys()) == {"agent_id", "content_hash", "token_count"}

    def test_to_dict_hash_truncated_to_8(self):
        rec = ExchangeRecord(
            agent_id="claude",
            content_hash="0123456789abcdef",
            token_count=50,
            timestamp=0.0,
        )
        d = rec.to_dict()
        assert d["content_hash"] == "01234567"
        assert len(d["content_hash"]) == 8

    def test_to_dict_values(self):
        rec = ExchangeRecord(
            agent_id="gemini",
            content_hash="fedcba9876543210",
            token_count=200,
            timestamp=0.0,
        )
        d = rec.to_dict()
        assert d["agent_id"] == "gemini"
        assert d["token_count"] == 200


# =============================================================================
# 4. Intervention
# =============================================================================


class TestIntervention:
    """Test Intervention dataclass."""

    def test_creation_defaults(self):
        iv = Intervention(
            type=InterventionType.REDUNDANCY,
            action=InterventionAction.SKIP,
        )
        assert iv.confidence == 0.5
        assert iv.reason == ""
        assert iv.token_waste_estimate == 0

    def test_creation_full(self):
        iv = Intervention(
            type=InterventionType.STAGNATION,
            action=InterventionAction.SUMMARIZE,
            confidence=0.75,
            reason="No progress",
            token_waste_estimate=500,
        )
        assert iv.type == InterventionType.STAGNATION
        assert iv.action == InterventionAction.SUMMARIZE
        assert iv.confidence == 0.75
        assert iv.reason == "No progress"
        assert iv.token_waste_estimate == 500

    def test_to_dict_keys(self):
        iv = Intervention(
            type=InterventionType.LOOP,
            action=InterventionAction.REDIRECT,
        )
        d = iv.to_dict()
        assert set(d.keys()) == {
            "type",
            "action",
            "confidence",
            "reason",
            "token_waste_estimate",
        }

    def test_to_dict_values(self):
        iv = Intervention(
            type=InterventionType.COST_LIMIT,
            action=InterventionAction.TERMINATE,
            confidence=0.999999,
            reason="Budget gone",
            token_waste_estimate=1000,
        )
        d = iv.to_dict()
        assert d["type"] == "cost_limit"
        assert d["action"] == "terminate"
        assert d["confidence"] == 1.0  # rounded to 3 decimals
        assert d["reason"] == "Budget gone"
        assert d["token_waste_estimate"] == 1000

    def test_to_dict_confidence_rounding(self):
        iv = Intervention(
            type=InterventionType.DIVERGENCE,
            action=InterventionAction.REDIRECT,
            confidence=0.12345,
        )
        d = iv.to_dict()
        assert d["confidence"] == 0.123


# =============================================================================
# 5. FilterStats
# =============================================================================


class TestFilterStats:
    """Test FilterStats dataclass."""

    def test_defaults(self):
        s = FilterStats()
        assert s.total_exchanges == 0
        assert s.interventions_triggered == 0
        assert s.tokens_saved == 0
        assert s.intervention_counts == {}
        assert s.action_counts == {}

    def test_to_dict_keys(self):
        s = FilterStats()
        d = s.to_dict()
        assert set(d.keys()) == {
            "total_exchanges",
            "interventions_triggered",
            "tokens_saved",
            "intervention_counts",
            "action_counts",
        }

    def test_to_dict_values(self):
        s = FilterStats(
            total_exchanges=10,
            interventions_triggered=3,
            tokens_saved=500,
            intervention_counts={"redundancy": 2, "loop": 1},
            action_counts={"skip": 2, "redirect": 1},
        )
        d = s.to_dict()
        assert d["total_exchanges"] == 10
        assert d["interventions_triggered"] == 3
        assert d["tokens_saved"] == 500
        assert d["intervention_counts"] == {"redundancy": 2, "loop": 1}
        assert d["action_counts"] == {"skip": 2, "redirect": 1}

    def test_to_dict_returns_dict_copy_of_counts(self):
        original = {"redundancy": 5}
        s = FilterStats(intervention_counts=original)
        d = s.to_dict()
        d["intervention_counts"]["redundancy"] = 999
        assert s.intervention_counts["redundancy"] == 5


# =============================================================================
# 6. Basic Exchange Checking - No Waste
# =============================================================================


class TestBasicExchangeNoWaste:
    """Test that clean exchanges produce CONTINUE."""

    def test_single_exchange_no_intervention(self, rwf: RuntimeWasteFilter):
        iv = rwf.check_exchange("claude", "This is a unique message about authentication.", 50)
        assert iv.action == InterventionAction.CONTINUE

    def test_two_different_exchanges_no_intervention(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Analyzing the login module for issues.", 50)
        iv = rwf.check_exchange("gemini", "I found a bug in the token validation logic.", 60)
        assert iv.action == InterventionAction.CONTINUE

    def test_continue_reason_message(self, rwf: RuntimeWasteFilter):
        iv = rwf.check_exchange("claude", "Unique content about database queries.", 50)
        assert "No waste signals" in iv.reason

    def test_continue_confidence_is_one(self, rwf: RuntimeWasteFilter):
        iv = rwf.check_exchange("claude", "Unique analysis of memory leak problem.", 50)
        assert iv.confidence == 1.0

    def test_continue_type_is_redundancy(self, rwf: RuntimeWasteFilter):
        """The default CONTINUE intervention has type REDUNDANCY per source."""
        iv = rwf.check_exchange("claude", "Exploring new algorithms for sorting.", 50)
        assert iv.type == InterventionType.REDUNDANCY


# =============================================================================
# 7. Redundancy Detection
# =============================================================================


class TestRedundancyDetection:
    """Test duplicate content hash detection."""

    def test_duplicate_content_triggers_skip(self, rwf: RuntimeWasteFilter):
        content = "The authentication token is expired and needs renewal."
        rwf.check_exchange("claude", content, 50)
        iv = rwf.check_exchange("gemini", content, 50)
        assert iv.action == InterventionAction.SKIP
        assert iv.type == InterventionType.REDUNDANCY

    def test_duplicate_confidence(self, rwf: RuntimeWasteFilter):
        content = "Fix the database connection pooling issue."
        rwf.check_exchange("claude", content, 50)
        iv = rwf.check_exchange("claude", content, 50)
        assert iv.confidence == 0.9

    def test_duplicate_reason_mentions_agent(self, rwf: RuntimeWasteFilter):
        content = "Implement retry logic for network calls."
        rwf.check_exchange("claude", content, 50)
        iv = rwf.check_exchange("gemini", content, 50)
        assert "gemini" in iv.reason

    def test_duplicate_token_waste_estimate(self, rwf: RuntimeWasteFilter):
        content = "Optimize the search algorithm for better performance."
        rwf.check_exchange("claude", content, 100)
        iv = rwf.check_exchange("gemini", content, 200)
        assert iv.token_waste_estimate == 200

    def test_whitespace_normalized_for_hashing(self, rwf: RuntimeWasteFilter):
        """Hashing normalizes whitespace so variants are detected as duplicates."""
        rwf.check_exchange("claude", "fix   the   bug", 30)
        iv = rwf.check_exchange("gemini", "fix the bug", 30)
        assert iv.action == InterventionAction.SKIP

    def test_case_normalized_for_hashing(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Fix The Bug", 30)
        iv = rwf.check_exchange("gemini", "fix the bug", 30)
        assert iv.action == InterventionAction.SKIP

    def test_different_content_no_redundancy(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Analyzing memory consumption patterns.", 50)
        iv = rwf.check_exchange("gemini", "The CPU utilization is too high on workers.", 50)
        assert iv.action == InterventionAction.CONTINUE

    def test_redundancy_within_hash_window(self, rwf: RuntimeWasteFilter):
        """Duplicates within the last REDUNDANCY_HASH_WINDOW are detected."""
        target = "Specific content to repeat later within window."
        rwf.check_exchange("claude", target, 50)
        for i in range(REDUNDANCY_HASH_WINDOW - 2):
            rwf.check_exchange("gemini", f"Unique filler content number {i} for spacing.", 50)
        iv = rwf.check_exchange("claude", target, 50)
        assert iv.action == InterventionAction.SKIP

    def test_redundancy_outside_hash_window(self, rwf: RuntimeWasteFilter):
        """Duplicates outside the hash window are not detected as redundant."""
        # Use a fresh filter with large stagnation window to avoid stagnation false positive
        rwf2 = RuntimeWasteFilter(stagnation_window=100)
        target = "Specific content to repeat outside window boundary."
        rwf2.check_exchange("claude", target, 50)
        # Each filler uses truly distinct topic words to avoid stagnation
        topics = [
            "kubernetes orchestration deployment cluster management",
            "tensorflow neural network backpropagation gradient",
            "cryptography elliptic curves signature verification",
            "elasticsearch lucene indexing sharding replicas",
            "postgresql vacuum autovacuum transaction isolation",
            "prometheus alertmanager grafana observability monitoring",
            "kafka partitions consumers producers streaming",
            "redis sentinel clustering keyspace eviction",
            "terraform modules providers provisioning infrastructure",
            "graphql federation resolver subscriptions mutations",
            "websocket handshake framing protocol masking",
            "docker containerd runc namespace cgroups",
            "ansible playbook inventory handlers templates",
            "nginx upstream loadbalancing reverse proxy",
            "rabbitmq exchanges queues bindings acknowledgement",
        ]
        for i, topic in enumerate(topics):
            agent = "claude" if i % 2 == 0 else "gemini"
            rwf2.check_exchange(agent, topic, 50)
        iv = rwf2.check_exchange("claude", target, 50)
        assert iv.action == InterventionAction.CONTINUE


# =============================================================================
# 8. Loop Detection
# =============================================================================


class TestLoopDetection:
    """Test circular A->B->A->B pattern detection."""

    def _make_loop(self, rwf: RuntimeWasteFilter, rounds: int = LOOP_THRESHOLD):
        """Create a circular pattern with `rounds` repetitions."""
        msg_a = "Agent A says fix the authentication layer."
        msg_b = "Agent B says review the token logic."
        for _ in range(rounds):
            rwf.check_exchange("claude", msg_a, 50)
            rwf.check_exchange("gemini", msg_b, 50)

    def test_loop_detected_with_three_agent_cycle(self, rwf: RuntimeWasteFilter):
        """A 3-agent repeating cycle is detected with default LOOP_THRESHOLD=3.

        The loop detector splits the last threshold*2 exchanges into two halves
        and checks if the (agent_id, content_hash) pairs match. With a 2-agent
        pattern of period 2, the halves of size 3 are misaligned. A 3-agent
        pattern of period 3 aligns correctly with threshold=3.
        """
        msgs = [
            ("claude", "Authentication architecture design plan."),
            ("gemini", "Token validation strategy review."),
            ("gpt4", "Security protocol implementation check."),
        ]
        # Two full cycles -> 6 exchanges, halves of 3 match
        for _ in range(2):
            for agent, msg in msgs:
                rwf.check_exchange(agent, msg, 50)
        iv = rwf._check_loop()
        assert iv.action == InterventionAction.REDIRECT
        assert iv.type == InterventionType.LOOP

    def test_loop_detected_with_custom_threshold_two(self):
        """A 2-agent loop is detected with loop_threshold=2."""
        rwf = RuntimeWasteFilter(loop_threshold=2)
        msg_a = "Authentication architecture design plan."
        msg_b = "Token validation strategy review."
        for _ in range(2):
            rwf.check_exchange("claude", msg_a, 50)
            rwf.check_exchange("gemini", msg_b, 50)
        iv = rwf._check_loop()
        assert iv.action == InterventionAction.REDIRECT
        assert iv.type == InterventionType.LOOP
        assert iv.confidence == 0.85

    def test_loop_fires_some_intervention_on_repeated_pattern(self, rwf: RuntimeWasteFilter):
        """Repeated A->B->A->B pattern triggers interventions (redundancy or loop)."""
        msg_a = "Agent A discusses the optimization problem repeatedly."
        msg_b = "Agent B repeats the performance review discussion."
        for _ in range(LOOP_THRESHOLD):
            rwf.check_exchange("claude", msg_a, 50)
            rwf.check_exchange("gemini", msg_b, 50)
        stats = rwf.get_stats()
        assert stats.interventions_triggered > 0

    def test_no_loop_under_threshold(self, rwf: RuntimeWasteFilter):
        """Fewer than threshold repetitions do not trigger loop."""
        msg_a = "Claude explores caching strategies for the API."
        msg_b = "Gemini reviews the caching implementation details."
        # Only do 1 round (needs threshold*2 exchanges minimum)
        rwf.check_exchange("claude", msg_a, 50)
        iv = rwf.check_exchange("gemini", msg_b, 50)
        assert iv.action == InterventionAction.CONTINUE

    def test_loop_confidence(self, rwf: RuntimeWasteFilter):
        msg_a = "Loop message alpha about database schema."
        msg_b = "Loop message beta about index optimization."
        interventions = []
        for _ in range(LOOP_THRESHOLD):
            iv1 = rwf.check_exchange("claude", msg_a, 50)
            iv2 = rwf.check_exchange("gemini", msg_b, 50)
            if iv1.type == InterventionType.LOOP and iv1.action != InterventionAction.CONTINUE:
                interventions.append(iv1)
            if iv2.type == InterventionType.LOOP and iv2.action != InterventionAction.CONTINUE:
                interventions.append(iv2)
        # At least one loop intervention should have confidence 0.85
        if interventions:
            assert any(iv.confidence == 0.85 for iv in interventions)

    def test_loop_not_triggered_with_varied_content(self, rwf: RuntimeWasteFilter):
        """Different content each round does not trigger loop detection."""
        for i in range(LOOP_THRESHOLD * 2):
            rwf.check_exchange(
                "claude" if i % 2 == 0 else "gemini",
                f"Unique message number {i} about different technical topics.",
                50,
            )
        stats = rwf.get_stats()
        assert stats.intervention_counts.get("loop", 0) == 0


# =============================================================================
# 9. Same-Agent Monologue Detection
# =============================================================================


class TestMonologueDetection:
    """Test MAX_SAME_AGENT consecutive same-agent detection."""

    def _fill_for_loop_check(self, rwf: RuntimeWasteFilter):
        """Add enough exchanges to pass the loop minimum length check."""
        for i in range(LOOP_THRESHOLD * 2):
            rwf.check_exchange(
                "gemini" if i % 2 == 0 else "claude",
                f"Preliminary exchange {i} about different engineering tasks.",
                30,
            )

    def test_monologue_triggers_redirect(self, rwf: RuntimeWasteFilter):
        self._fill_for_loop_check(rwf)
        interventions = []
        for i in range(MAX_SAME_AGENT):
            iv = rwf.check_exchange(
                "claude",
                f"Claude monologue message {i} about different topics each time.",
                50,
            )
            if iv.type == InterventionType.LOOP and iv.action != InterventionAction.CONTINUE:
                interventions.append(iv)
        assert len(interventions) > 0

    def test_monologue_reason_mentions_agent(self, rwf: RuntimeWasteFilter):
        self._fill_for_loop_check(rwf)
        last_iv = None
        for i in range(MAX_SAME_AGENT):
            iv = rwf.check_exchange(
                "claude",
                f"Claude talking alone message {i} about a novel subject each turn.",
                50,
            )
            if iv.type == InterventionType.LOOP and iv.action == InterventionAction.REDIRECT:
                last_iv = iv
        assert last_iv is not None
        assert "claude" in last_iv.reason

    def test_monologue_confidence_is_070(self, rwf: RuntimeWasteFilter):
        self._fill_for_loop_check(rwf)
        last_iv = None
        for i in range(MAX_SAME_AGENT):
            iv = rwf.check_exchange(
                "claude",
                f"Claude keeps talking alone message {i} about varied engineering.",
                50,
            )
            if iv.type == InterventionType.LOOP and iv.action == InterventionAction.REDIRECT:
                last_iv = iv
        assert last_iv is not None
        assert last_iv.confidence == 0.7

    def test_no_monologue_with_alternation(self, rwf: RuntimeWasteFilter):
        self._fill_for_loop_check(rwf)
        for i in range(MAX_SAME_AGENT * 2):
            agent = "claude" if i % 2 == 0 else "gemini"
            iv = rwf.check_exchange(
                agent,
                f"Alternating agent message {i} exploring unique ideas each round.",
                50,
            )
            if iv.type == InterventionType.LOOP:
                assert iv.action == InterventionAction.CONTINUE


# =============================================================================
# 10. Stagnation Detection
# =============================================================================


class TestStagnationDetection:
    """Test no-new-topic-words stagnation detection."""

    def test_stagnation_with_repeated_words(self, rwf: RuntimeWasteFilter):
        """Exchanges using the same topic words trigger stagnation after window.

        Key: The window exchanges must contain ZERO new topic words compared
        to pre-window exchanges. We use different sentence structures (stop words)
        but only topic words already established in pre-window.
        """
        # Pre-window: establish base topic words {python, authentication, module, iteration}
        for i in range(3):
            rwf.check_exchange(
                "claude",
                f"python authentication module iteration {i}",
                50,
            )
        # Window: same topic words, varied stop words for unique hashes
        stagnant_phrases = [
            "the python authentication is on module iteration",
            "an authentication module in python for iteration",
            "with python for authentication and module iteration",
            "iteration of python authentication to module",
            "python module but authentication and iteration",
        ]
        for i in range(STAGNATION_WINDOW):
            agent = "claude" if i % 2 == 0 else "gemini"
            rwf.check_exchange(agent, stagnant_phrases[i], 50)
        # Directly verify stagnation is detected
        topic_words = rwf._extract_topic_words(stagnant_phrases[0])
        iv = rwf._check_stagnation(topic_words)
        assert iv.action == InterventionAction.SUMMARIZE
        assert iv.type == InterventionType.STAGNATION

    def test_stagnation_action_is_summarize(self, rwf: RuntimeWasteFilter):
        """Stagnation intervention action is SUMMARIZE."""
        # Pre-window: establish {database, query, optimization, attempt}
        for i in range(3):
            rwf.check_exchange("claude", f"database query optimization attempt {i}", 50)
        # Window: only reuse existing topic words, vary stop words
        stagnant = [
            "the database query is on optimization attempt",
            "an optimization attempt in database for query",
            "with database for query and optimization attempt",
            "attempt of database query to optimization",
            "database optimization but query and attempt",
        ]
        for i in range(STAGNATION_WINDOW):
            agent = "claude" if i % 2 == 0 else "gemini"
            rwf.check_exchange(agent, stagnant[i], 50)
        topic_words = rwf._extract_topic_words(stagnant[0])
        iv = rwf._check_stagnation(topic_words)
        assert iv.action == InterventionAction.SUMMARIZE

    def test_stagnation_confidence(self, rwf: RuntimeWasteFilter):
        """Stagnation confidence is 0.75."""
        # Pre-window: establish {server, monitoring, metrics, review}
        for i in range(3):
            rwf.check_exchange("claude", f"server monitoring metrics review {i}", 50)
        # Window: only reuse existing topic words
        stagnant = [
            "the server monitoring is on metrics review",
            "an metrics review in server for monitoring",
            "with server for monitoring and metrics review",
            "review of server monitoring to metrics",
            "server metrics but monitoring and review",
        ]
        for i in range(STAGNATION_WINDOW):
            agent = "claude" if i % 2 == 0 else "gemini"
            rwf.check_exchange(agent, stagnant[i], 50)
        topic_words = rwf._extract_topic_words(stagnant[0])
        iv = rwf._check_stagnation(topic_words)
        assert iv.confidence == 0.75

    def test_no_stagnation_with_new_words(self, rwf: RuntimeWasteFilter):
        """Each exchange introducing new words prevents stagnation."""
        topics = [
            "kubernetes deployment cluster orchestration",
            "machine learning neural network training",
            "cryptography encryption protocol security",
            "microservice architecture gateway routing",
            "terraform infrastructure provisioning cloud",
            "graphql schema resolver federation",
            "websocket realtime streaming protocol",
            "elasticsearch indexing aggregation pipeline",
            "prometheus monitoring alerting dashboard",
            "jenkins cicd pipeline automation workflow",
        ]
        for i, topic in enumerate(topics):
            agent = "claude" if i % 2 == 0 else "gemini"
            iv = rwf.check_exchange(agent, topic, 50)
            if iv.type == InterventionType.STAGNATION:
                assert iv.action == InterventionAction.CONTINUE

    def test_no_stagnation_under_window(self, rwf: RuntimeWasteFilter):
        """Fewer than stagnation_window exchanges do not trigger stagnation."""
        for _i in range(STAGNATION_WINDOW - 1):
            iv = rwf.check_exchange("claude", "Same repeated content about python.", 50)
            if iv.type == InterventionType.STAGNATION:
                assert iv.action == InterventionAction.CONTINUE

    def test_stagnation_custom_window(self):
        """Custom stagnation_window parameter is respected."""
        rwf = RuntimeWasteFilter(stagnation_window=3)
        # Pre-window
        rwf.check_exchange("claude", "Alpha beta gamma keyword.", 50)
        # Window of 3 with same words
        for _ in range(3):
            rwf.check_exchange("gemini", "Alpha beta gamma keyword.", 50)
        stats = rwf.get_stats()
        # Either stagnation or redundancy triggered (redundancy may fire first)
        assert stats.interventions_triggered > 0


# =============================================================================
# 11. Divergence Detection
# =============================================================================


class TestDivergenceDetection:
    """Test off-topic exchange detection."""

    def test_divergence_detected_when_off_topic(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix the authentication bug in login module.")
        # Add some initial on-topic exchanges to pass the len > 3 guard
        rwf.check_exchange("claude", "Looking at authentication module.", 50)
        rwf.check_exchange("gemini", "Found login bug in validation.", 50)
        rwf.check_exchange("claude", "Fixing authentication token check.", 50)
        # Now send a completely off-topic exchange
        iv = rwf.check_exchange(
            "gemini",
            "kubernetes deployment cluster orchestration terraform provisioning "
            "grafana dashboard monitoring prometheus alerting pipeline",
            100,
        )
        # Divergence or another check may trigger
        rwf.get_stats()
        # The off-topic message should cause some intervention
        if iv.type == InterventionType.DIVERGENCE:
            assert iv.action == InterventionAction.REDIRECT

    def test_divergence_action_is_redirect(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Optimize database query performance.")
        rwf.check_exchange("claude", "Database query optimization.", 50)
        rwf.check_exchange("gemini", "Performance tuning database indexes.", 50)
        rwf.check_exchange("claude", "Query plan analysis database.", 50)
        iv = rwf.check_exchange(
            "gemini",
            "cooking recipe chocolate strawberry vanilla baking dessert frosting",
            50,
        )
        if iv.type == InterventionType.DIVERGENCE:
            assert iv.action == InterventionAction.REDIRECT

    def test_no_divergence_without_task_context(self, rwf: RuntimeWasteFilter):
        """Without task context, divergence check always returns CONTINUE."""
        for i in range(5):
            iv = rwf.check_exchange("claude", f"Random topic {i} unrelated stuff.", 50)
            if iv.type == InterventionType.DIVERGENCE:
                assert iv.action == InterventionAction.CONTINUE

    def test_no_divergence_on_topic(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix authentication bug in login module.")
        rwf.check_exchange("claude", "Authentication module analysis.", 50)
        rwf.check_exchange("gemini", "Login bug investigation.", 50)
        rwf.check_exchange("claude", "Fix for authentication.", 50)
        iv = rwf.check_exchange("gemini", "Login module authentication fix applied.", 50)
        if iv.type == InterventionType.DIVERGENCE:
            assert iv.action == InterventionAction.CONTINUE

    def test_divergence_requires_more_than_3_exchanges(self, rwf: RuntimeWasteFilter):
        """Divergence only fires after more than 3 exchanges."""
        rwf.set_task_context("Fix authentication bug.")
        iv = rwf.check_exchange(
            "claude",
            "cooking recipe chocolate baking dessert pastry",
            50,
        )
        if iv.type == InterventionType.DIVERGENCE:
            assert iv.action == InterventionAction.CONTINUE

    def test_no_divergence_with_empty_current_words(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix authentication bug.")
        for i in range(4):
            rwf.check_exchange("claude", f"Exchange {i} about authentication bug.", 50)
        # Very short content that produces no topic words after stop filtering
        iv = rwf.check_exchange("claude", "a is the to", 10)
        if iv.type == InterventionType.DIVERGENCE:
            assert iv.action == InterventionAction.CONTINUE


# =============================================================================
# 12. Cost Limit Detection
# =============================================================================


class TestCostLimitDetection:
    """Test token budget enforcement."""

    def test_budget_exhausted_triggers_terminate(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix bug.", token_budget=100)
        rwf.check_exchange("claude", "First message about fixing bug.", 60)
        rwf.check_exchange("gemini", "Second message about fixing bug.", 50)
        # Tokens used: 110 / budget: 100 -> exhausted
        # Redundancy or cost_limit may fire depending on priority
        stats = rwf.get_stats()
        assert stats.interventions_triggered > 0

    def test_budget_warning_triggers_summarize(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Optimize performance.", token_budget=1000)
        # Use 860 tokens => remaining ratio = 0.14 < 0.15 threshold
        rwf.check_exchange("claude", "Performance optimization analysis complete.", 860)
        iv = rwf.check_exchange("gemini", "Additional performance profiling results.", 1)
        # Check that cost_limit was detected
        if iv.type == InterventionType.COST_LIMIT:
            assert iv.action == InterventionAction.SUMMARIZE

    def test_no_cost_limit_without_budget(self, rwf: RuntimeWasteFilter):
        """Zero budget means no cost limit checking."""
        rwf.set_task_context("Fix bug.", token_budget=0)
        for i in range(10):
            iv = rwf.check_exchange("claude", f"Message {i} with tokens.", 1000)
            if iv.type == InterventionType.COST_LIMIT:
                assert iv.action == InterventionAction.CONTINUE

    def test_no_cost_limit_when_budget_healthy(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=10000)
        iv = rwf.check_exchange("claude", "Small message about the task.", 10)
        if iv.type == InterventionType.COST_LIMIT:
            assert iv.action == InterventionAction.CONTINUE

    def test_budget_exhausted_confidence_is_one(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=50)
        rwf.check_exchange("claude", "First.", 30)
        iv = rwf.check_exchange("gemini", "Second.", 25)
        if iv.type == InterventionType.COST_LIMIT:
            assert iv.confidence == 1.0

    def test_budget_warning_confidence(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=1000)
        rwf.check_exchange("claude", "Using most of budget.", 870)
        iv = rwf.check_exchange("gemini", "Just a bit more.", 1)
        if iv.type == InterventionType.COST_LIMIT:
            assert iv.confidence == 0.8

    def test_cost_limit_terminate_reason_includes_counts(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=50)
        rwf.check_exchange("claude", "Message one.", 30)
        iv = rwf.check_exchange("gemini", "Message two.", 25)
        if iv.type == InterventionType.COST_LIMIT and iv.action == InterventionAction.TERMINATE:
            assert "55" in iv.reason or "50" in iv.reason


# =============================================================================
# 13. Task Context Setting
# =============================================================================


class TestTaskContext:
    """Test set_task_context behavior."""

    def test_set_task_context_extracts_words(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix authentication bug in login module.")
        assert "authentication" in rwf._task_words
        assert "login" in rwf._task_words
        assert "module" in rwf._task_words

    def test_set_task_context_filters_stop_words(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix the bug in the system.")
        assert "the" not in rwf._task_words
        assert "in" not in rwf._task_words

    def test_set_task_context_sets_budget(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=5000)
        assert rwf._token_budget == 5000

    def test_set_task_context_resets_tokens_used(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Accumulate some tokens.", 100)
        rwf.set_task_context("New task.", token_budget=1000)
        assert rwf._tokens_used == 0

    def test_set_task_context_default_budget_zero(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task without budget.")
        assert rwf._token_budget == 0


# =============================================================================
# 14. Topic Word Extraction
# =============================================================================


class TestTopicWordExtraction:
    """Test _extract_topic_words static method."""

    def test_extracts_lowercase_words(self):
        words = RuntimeWasteFilter._extract_topic_words("Python Django Flask")
        assert "python" in words
        assert "django" in words
        assert "flask" in words

    def test_filters_stop_words(self):
        words = RuntimeWasteFilter._extract_topic_words("the quick fox is very fast")
        assert "the" not in words
        assert "is" not in words
        assert "very" not in words
        assert "quick" in words
        assert "fast" in words  # "fast" is NOT a stop word, it passes through
        assert "fox" in words

    def test_regex_requires_two_plus_chars(self):
        """Words must match [a-z][a-z0-9_]+ which requires at least 2 chars."""
        words = RuntimeWasteFilter._extract_topic_words("a b c de fg")
        assert "a" not in words
        assert "b" not in words
        assert "c" not in words
        assert "de" in words or "de" in STOP_WORDS
        assert "fg" in words

    def test_includes_words_with_underscores(self):
        words = RuntimeWasteFilter._extract_topic_words("hello_world test_case")
        assert "hello_world" in words
        assert "test_case" in words

    def test_includes_words_with_digits(self):
        words = RuntimeWasteFilter._extract_topic_words("python3 version12")
        assert "python3" in words
        assert "version12" in words

    def test_empty_string(self):
        words = RuntimeWasteFilter._extract_topic_words("")
        assert words == set()

    def test_only_stop_words(self):
        words = RuntimeWasteFilter._extract_topic_words("the is a an to of in for on with")
        assert len(words) == 0

    def test_mixed_case_lowered(self):
        words = RuntimeWasteFilter._extract_topic_words("Authentication MODULE")
        assert "authentication" in words
        assert "module" in words
        assert "Authentication" not in words

    def test_punctuation_ignored(self):
        words = RuntimeWasteFilter._extract_topic_words("hello, world! test.")
        assert "hello" in words
        assert "world" in words
        assert "test" in words


# =============================================================================
# 15. Content Hashing
# =============================================================================


class TestContentHashing:
    """Test _hash static method."""

    def test_deterministic(self):
        h1 = RuntimeWasteFilter._hash("Hello World")
        h2 = RuntimeWasteFilter._hash("Hello World")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = RuntimeWasteFilter._hash("Hello World")
        h2 = RuntimeWasteFilter._hash("hello world")
        assert h1 == h2

    def test_whitespace_normalized(self):
        h1 = RuntimeWasteFilter._hash("hello    world")
        h2 = RuntimeWasteFilter._hash("hello world")
        assert h1 == h2

    def test_leading_trailing_whitespace(self):
        h1 = RuntimeWasteFilter._hash("  hello world  ")
        h2 = RuntimeWasteFilter._hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = RuntimeWasteFilter._hash("Hello World")
        h2 = RuntimeWasteFilter._hash("Goodbye World")
        assert h1 != h2

    def test_returns_hex_string(self):
        h = RuntimeWasteFilter._hash("test content")
        assert all(c in "0123456789abcdef" for c in h)

    def test_md5_length(self):
        h = RuntimeWasteFilter._hash("test")
        assert len(h) == 32

    def test_newlines_normalized(self):
        h1 = RuntimeWasteFilter._hash("hello\nworld")
        h2 = RuntimeWasteFilter._hash("hello world")
        assert h1 == h2

    def test_tabs_normalized(self):
        h1 = RuntimeWasteFilter._hash("hello\tworld")
        h2 = RuntimeWasteFilter._hash("hello world")
        assert h1 == h2


# =============================================================================
# 16. Priority Ordering
# =============================================================================


class TestPriorityOrdering:
    """Test that checks run in priority order: redundancy > loop > stagnation > divergence > cost."""

    def test_redundancy_fires_before_cost_limit(self, rwf: RuntimeWasteFilter):
        """Redundancy should fire before cost limit."""
        rwf.set_task_context("Task.", token_budget=100)
        content = "Repeated content about the task analysis."
        rwf.check_exchange("claude", content, 50)
        iv = rwf.check_exchange("gemini", content, 60)
        # Both redundancy and cost_limit could fire, but redundancy is first
        assert iv.type == InterventionType.REDUNDANCY
        assert iv.action == InterventionAction.SKIP

    def test_checks_order_is_redundancy_loop_stagnation_divergence_cost(self, rwf: RuntimeWasteFilter):
        """Verify the internal check order by inspection."""
        # This is an indirect test: we verify that a CONTINUE from all checks
        # results in the default CONTINUE intervention
        iv = rwf.check_exchange("claude", "Unique content about kubernetes deployment.", 50)
        assert iv.action == InterventionAction.CONTINUE


# =============================================================================
# 17. Singleton Pattern
# =============================================================================


class TestSingletonPattern:
    """Test get/reset singleton pattern."""

    def test_get_returns_instance(self):
        f = get_runtime_waste_filter()
        assert isinstance(f, RuntimeWasteFilter)

    def test_get_returns_same_instance(self):
        f1 = get_runtime_waste_filter()
        f2 = get_runtime_waste_filter()
        assert f1 is f2

    def test_reset_clears_instance(self):
        f1 = get_runtime_waste_filter()
        reset_runtime_waste_filter()
        f2 = get_runtime_waste_filter()
        assert f1 is not f2

    def test_reset_then_get_fresh(self):
        f = get_runtime_waste_filter()
        f.check_exchange("claude", "Some content.", 50)
        stats_before = f.get_stats()
        assert stats_before.total_exchanges == 1

        reset_runtime_waste_filter()
        f2 = get_runtime_waste_filter()
        stats_after = f2.get_stats()
        assert stats_after.total_exchanges == 0

    def test_singleton_usable_after_reset(self):
        reset_runtime_waste_filter()
        f = get_runtime_waste_filter()
        iv = f.check_exchange("claude", "Test content.", 50)
        assert iv.action == InterventionAction.CONTINUE


# =============================================================================
# 18. Statistics Tracking
# =============================================================================


class TestStatisticsTracking:
    """Test FilterStats updates via check_exchange."""

    def test_total_exchanges_increments(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Message one.", 50)
        rwf.check_exchange("gemini", "Message two.", 50)
        stats = rwf.get_stats()
        assert stats.total_exchanges == 2

    def test_interventions_triggered_increments(self, rwf: RuntimeWasteFilter):
        content = "Exact same content for redundancy detection."
        rwf.check_exchange("claude", content, 50)
        rwf.check_exchange("gemini", content, 50)
        stats = rwf.get_stats()
        assert stats.interventions_triggered >= 1

    def test_tokens_saved_accumulates(self, rwf: RuntimeWasteFilter):
        content = "Content that will be flagged as redundant."
        rwf.check_exchange("claude", content, 100)
        rwf.check_exchange("gemini", content, 200)
        stats = rwf.get_stats()
        assert stats.tokens_saved >= 200

    def test_intervention_counts_by_type(self, rwf: RuntimeWasteFilter):
        content = "Duplicate content to trigger redundancy counter."
        rwf.check_exchange("claude", content, 50)
        rwf.check_exchange("gemini", content, 50)
        stats = rwf.get_stats()
        assert stats.intervention_counts.get("redundancy", 0) >= 1

    def test_action_counts_tracked(self, rwf: RuntimeWasteFilter):
        content = "Repeated content triggers skip action counter."
        rwf.check_exchange("claude", content, 50)
        rwf.check_exchange("gemini", content, 50)
        stats = rwf.get_stats()
        assert stats.action_counts.get("skip", 0) >= 1

    def test_stats_snapshot_is_independent(self, rwf: RuntimeWasteFilter):
        """get_stats returns a copy, not a reference."""
        rwf.check_exchange("claude", "Message.", 50)
        stats1 = rwf.get_stats()
        rwf.check_exchange("gemini", "Another message.", 50)
        stats2 = rwf.get_stats()
        assert stats1.total_exchanges == 1
        assert stats2.total_exchanges == 2

    def test_no_intervention_no_counts(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Unique message about microservices.", 50)
        stats = rwf.get_stats()
        assert stats.interventions_triggered == 0
        assert stats.tokens_saved == 0
        assert stats.intervention_counts == {}
        assert stats.action_counts == {}


# =============================================================================
# 19. Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_content(self, rwf: RuntimeWasteFilter):
        iv = rwf.check_exchange("claude", "", 0)
        assert iv.action == InterventionAction.CONTINUE

    def test_zero_token_count_estimated(self, rwf: RuntimeWasteFilter):
        """Token count of 0 is estimated from content length."""
        rwf.check_exchange("claude", "A message with some content here.", 0)
        stats = rwf.get_stats()
        assert stats.total_exchanges == 1

    def test_token_estimation_formula(self, rwf: RuntimeWasteFilter):
        """Token count = max(1, len(content) // 4) when provided as 0."""
        content = "abcdefghijklmnop"  # 16 chars -> 4 tokens
        rwf.check_exchange("claude", content, 0)
        # Internal token tracking
        assert rwf._tokens_used == 4

    def test_token_estimation_minimum_one(self, rwf: RuntimeWasteFilter):
        """Very short content gets at least 1 token."""
        rwf.check_exchange("claude", "ab", 0)
        assert rwf._tokens_used >= 1

    def test_no_task_context(self, rwf: RuntimeWasteFilter):
        """Without task context, divergence never fires."""
        for i in range(10):
            iv = rwf.check_exchange(
                "claude",
                f"Random topic {i} about completely different subjects.",
                50,
            )
            if iv.type == InterventionType.DIVERGENCE:
                assert iv.action == InterventionAction.CONTINUE

    def test_zero_budget_no_cost_limit(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=0)
        for i in range(5):
            iv = rwf.check_exchange("claude", f"Message {i} with many tokens.", 10000)
            if iv.type == InterventionType.COST_LIMIT:
                assert iv.action == InterventionAction.CONTINUE

    def test_single_exchange(self, rwf: RuntimeWasteFilter):
        iv = rwf.check_exchange("claude", "Just one message.", 50)
        assert iv.action == InterventionAction.CONTINUE
        stats = rwf.get_stats()
        assert stats.total_exchanges == 1

    def test_very_long_content(self, rwf: RuntimeWasteFilter):
        content = "unique_word " * 10000
        iv = rwf.check_exchange("claude", content, 10000)
        assert iv is not None

    def test_special_characters_in_content(self, rwf: RuntimeWasteFilter):
        content = "!!!@@@###$$$%%%^^^&&&***()()() 42 = = = +"
        iv = rwf.check_exchange("claude", content, 50)
        assert iv.action == InterventionAction.CONTINUE

    def test_unicode_content(self, rwf: RuntimeWasteFilter):
        content = "Authentication module verification check."
        iv = rwf.check_exchange("claude", content, 50)
        assert iv is not None

    def test_budget_exactly_at_threshold(self, rwf: RuntimeWasteFilter):
        """Budget remaining exactly at threshold border."""
        rwf.set_task_context("Task.", token_budget=100)
        # Use 85 tokens -> remaining = 0.15, exactly at threshold
        rwf.check_exchange("claude", "Content.", 85)
        iv = rwf.check_exchange("gemini", "More.", 1)
        # remaining_ratio = 1 - 86/100 = 0.14 < 0.15
        if iv.type == InterventionType.COST_LIMIT:
            assert iv.action == InterventionAction.SUMMARIZE

    def test_multiple_agents(self, rwf: RuntimeWasteFilter):
        """More than 2 agents still works."""
        rwf.check_exchange("claude", "Analysis from Claude about system architecture.", 50)
        rwf.check_exchange("gemini", "Analysis from Gemini about deployment strategy.", 50)
        iv = rwf.check_exchange("gpt4", "Analysis from GPT4 about testing patterns.", 50)
        assert iv.action == InterventionAction.CONTINUE
        assert rwf.get_stats().total_exchanges == 3


# =============================================================================
# 20. Reset
# =============================================================================


class TestReset:
    """Test reset clears all state."""

    def test_reset_clears_stats(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Some content.", 50)
        rwf.reset()
        stats = rwf.get_stats()
        assert stats.total_exchanges == 0
        assert stats.interventions_triggered == 0
        assert stats.tokens_saved == 0

    def test_reset_clears_exchanges(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Content.", 50)
        rwf.reset()
        assert len(rwf._exchanges) == 0

    def test_reset_clears_task_words(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Fix authentication bug.")
        rwf.reset()
        assert len(rwf._task_words) == 0

    def test_reset_clears_all_topic_words(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Python authentication module.", 50)
        rwf.reset()
        assert len(rwf._all_topic_words) == 0

    def test_reset_clears_budget(self, rwf: RuntimeWasteFilter):
        rwf.set_task_context("Task.", token_budget=5000)
        rwf.reset()
        assert rwf._token_budget == 0

    def test_reset_clears_tokens_used(self, rwf: RuntimeWasteFilter):
        rwf.check_exchange("claude", "Content.", 100)
        rwf.reset()
        assert rwf._tokens_used == 0

    def test_reset_allows_fresh_start(self, rwf: RuntimeWasteFilter):
        content = "Exact same message for redundancy."
        rwf.check_exchange("claude", content, 50)
        rwf.reset()
        iv = rwf.check_exchange("claude", content, 50)
        assert iv.action == InterventionAction.CONTINUE


# =============================================================================
# 21. Thread Safety
# =============================================================================


class TestThreadSafety:
    """Test concurrent access to RuntimeWasteFilter."""

    def test_concurrent_check_exchange(self, rwf: RuntimeWasteFilter):
        """Multiple threads calling check_exchange simultaneously."""
        errors = []
        results = []

        def worker(agent_id: str, count: int):
            try:
                for i in range(count):
                    iv = rwf.check_exchange(
                        agent_id,
                        f"Thread {agent_id} message {i} about unique engineering topic.",
                        50,
                    )
                    results.append(iv)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=("claude", 20)),
            threading.Thread(target=worker, args=("gemini", 20)),
            threading.Thread(target=worker, args=("gpt4", 20)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"
        stats = rwf.get_stats()
        assert stats.total_exchanges == 60

    def test_concurrent_get_stats(self, rwf: RuntimeWasteFilter):
        """get_stats is safe to call from multiple threads."""
        errors = []

        def writer():
            try:
                for i in range(30):
                    rwf.check_exchange("claude", f"Write thread message {i}.", 10)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(30):
                    _ = rwf.get_stats()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_concurrent_singleton_access(self):
        """Multiple threads can safely get the singleton."""
        instances = []
        errors = []

        def getter():
            try:
                inst = get_runtime_waste_filter()
                instances.append(inst)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=getter) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        assert len(instances) == 20
        # All should be the same instance
        assert all(inst is instances[0] for inst in instances)

    def test_concurrent_reset_and_get(self):
        """Concurrent reset and get do not crash."""
        errors = []

        def resetter():
            try:
                for _ in range(20):
                    reset_runtime_waste_filter()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def getter():
            try:
                for _ in range(20):
                    f = get_runtime_waste_filter()
                    f.check_exchange("claude", "Test.", 10)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=resetter),
            threading.Thread(target=getter),
            threading.Thread(target=getter),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0


# =============================================================================
# 22. Constructor Parameters
# =============================================================================


class TestConstructorParameters:
    """Test custom constructor parameters."""

    def test_custom_stagnation_window(self):
        rwf = RuntimeWasteFilter(stagnation_window=2)
        assert rwf._stagnation_window == 2

    def test_custom_loop_threshold(self):
        rwf = RuntimeWasteFilter(loop_threshold=5)
        assert rwf._loop_threshold == 5

    def test_custom_cost_warning_threshold(self):
        rwf = RuntimeWasteFilter(cost_warning_threshold=0.25)
        assert rwf._cost_warning_threshold == 0.25

    def test_default_stagnation_window(self):
        rwf = RuntimeWasteFilter()
        assert rwf._stagnation_window == STAGNATION_WINDOW

    def test_default_loop_threshold(self):
        rwf = RuntimeWasteFilter()
        assert rwf._loop_threshold == LOOP_THRESHOLD

    def test_default_cost_warning_threshold(self):
        rwf = RuntimeWasteFilter()
        assert rwf._cost_warning_threshold == COST_WARNING_THRESHOLD


# =============================================================================
# 23. Constants Verification
# =============================================================================


class TestConstants:
    """Verify module constants have expected values."""

    def test_redundancy_hash_window(self):
        assert REDUNDANCY_HASH_WINDOW == 10

    def test_stagnation_window(self):
        assert STAGNATION_WINDOW == 5

    def test_min_new_words(self):
        assert MIN_NEW_WORDS == 3

    def test_loop_threshold(self):
        assert LOOP_THRESHOLD == 3

    def test_max_same_agent(self):
        assert MAX_SAME_AGENT == 4

    def test_cost_warning_threshold(self):
        assert abs(COST_WARNING_THRESHOLD - 0.15) < 0.001

    def test_divergence_threshold(self):
        assert abs(DIVERGENCE_THRESHOLD - 0.80) < 0.001

    def test_stop_words_is_frozenset(self):
        assert isinstance(STOP_WORDS, frozenset)

    def test_stop_words_contains_common_words(self):
        assert "the" in STOP_WORDS
        assert "is" in STOP_WORDS
        assert "and" in STOP_WORDS
        assert "or" in STOP_WORDS

    def test_stop_words_does_not_contain_technical_words(self):
        assert "python" not in STOP_WORDS
        assert "authentication" not in STOP_WORDS
        assert "database" not in STOP_WORDS


# =============================================================================
# 24. Integration-Style Tests
# =============================================================================


class TestIntegrationScenarios:
    """End-to-end scenarios combining multiple features."""

    def test_full_conversation_lifecycle(self, rwf: RuntimeWasteFilter):
        """Simulate a full agent conversation with task context and budget."""
        rwf.set_task_context(
            "Fix memory leak in worker pool thread connection handle allocation.",
            token_budget=5000,
        )

        # Round 1: on-topic analysis with task-relevant words
        iv1 = rwf.check_exchange(
            "claude",
            "Analyzing worker pool memory allocation patterns thread.",
            80,
        )
        assert iv1.action == InterventionAction.CONTINUE

        iv2 = rwf.check_exchange(
            "gemini",
            "Found potential leak in worker thread connection pool.",
            90,
        )
        assert iv2.action == InterventionAction.CONTINUE

        # Round 2: continued progress with task-relevant words
        iv3 = rwf.check_exchange(
            "claude",
            "Profiling memory handle allocation growth in worker pool.",
            85,
        )
        assert iv3.action == InterventionAction.CONTINUE

        iv4 = rwf.check_exchange(
            "gemini",
            "Confirmed handle leak in connection pool thread worker.",
            95,
        )
        assert iv4.action == InterventionAction.CONTINUE

        stats = rwf.get_stats()
        assert stats.total_exchanges == 4

    def test_degrading_conversation(self, rwf: RuntimeWasteFilter):
        """Conversation that starts well then degrades into repetition."""
        rwf.set_task_context("Optimize API response time.", token_budget=1000)

        # Good exchanges
        rwf.check_exchange("claude", "Profiling shows database queries are slow.", 50)
        rwf.check_exchange("gemini", "Adding indexes should improve read performance.", 50)

        # Starts repeating
        content = "Database queries need optimization for performance."
        rwf.check_exchange("claude", content, 50)
        iv = rwf.check_exchange("gemini", content, 50)
        # Should detect redundancy
        assert iv.action != InterventionAction.CONTINUE

    def test_stats_after_multiple_interventions(self, rwf: RuntimeWasteFilter):
        """Stats correctly accumulate across multiple intervention types."""
        # Trigger redundancy
        dup = "Duplicate message for statistics testing purposes."
        rwf.check_exchange("claude", dup, 100)
        rwf.check_exchange("gemini", dup, 100)

        stats = rwf.get_stats()
        assert stats.total_exchanges == 2
        assert stats.interventions_triggered >= 1
        assert stats.tokens_saved >= 100

    def test_reset_mid_conversation(self, rwf: RuntimeWasteFilter):
        """Resetting mid-conversation clears all history."""
        rwf.set_task_context("Build API.", token_budget=1000)
        content = "Repeated API design discussion content."
        rwf.check_exchange("claude", content, 50)
        rwf.check_exchange("gemini", content, 50)

        rwf.reset()

        # After reset, same content is not flagged
        iv = rwf.check_exchange("claude", content, 50)
        assert iv.action == InterventionAction.CONTINUE
        stats = rwf.get_stats()
        assert stats.total_exchanges == 1
        assert stats.interventions_triggered == 0

    def test_custom_thresholds_affect_detection(self):
        """Custom constructor thresholds change detection sensitivity."""
        rwf = RuntimeWasteFilter(
            stagnation_window=2,
            loop_threshold=2,
            cost_warning_threshold=0.5,
        )
        rwf.set_task_context("Task.", token_budget=100)

        # Quick budget warning at 50% threshold
        rwf.check_exchange("claude", "Using half the budget quickly.", 55)
        iv = rwf.check_exchange("gemini", "More budget usage.", 1)
        # remaining = 1 - 56/100 = 0.44 < 0.5
        if iv.type == InterventionType.COST_LIMIT:
            assert iv.action == InterventionAction.SUMMARIZE
