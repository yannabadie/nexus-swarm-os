"""Tests for EvolveR Principle Library - self-distilled lessons with dynamic scoring."""

import pytest

from core.intelligence.hive_mind.principle_library import (
    Principle,
    PrincipleLibrary,
    get_principle_library,
    reset_principle_library,
)

# =============================================================================
# Principle Scoring
# =============================================================================


class TestPrincipleScoring:
    def test_new_principle_score_is_neutral(self):
        p = Principle(id="1", text="test", tags=[], source_task="", created_at="")
        assert p.score == pytest.approx(0.5)

    def test_one_success_raises_score(self):
        p = Principle(id="1", text="test", tags=[], source_task="", created_at="")
        p.record_usage(success=True)
        assert p.score == pytest.approx(2 / 3)

    def test_one_failure_lowers_score(self):
        p = Principle(id="1", text="test", tags=[], source_task="", created_at="")
        p.record_usage(success=False)
        assert p.score == pytest.approx(1 / 3)

    def test_many_successes_converge_to_one(self):
        p = Principle(id="1", text="test", tags=[], source_task="", created_at="")
        for _ in range(100):
            p.record_usage(success=True)
        assert p.score > 0.95

    def test_mixed_results(self):
        p = Principle(id="1", text="test", tags=[], source_task="", created_at="")
        p.record_usage(success=True)
        p.record_usage(success=True)
        p.record_usage(success=False)
        # (2+1) / (3+2) = 0.6
        assert p.score == pytest.approx(0.6)

    def test_record_usage_updates_last_used(self):
        p = Principle(id="1", text="test", tags=[], source_task="", created_at="")
        assert p.last_used is None
        p.record_usage(success=True)
        assert p.last_used is not None


# =============================================================================
# Principle Serialization
# =============================================================================


class TestSerialization:
    def test_to_dict(self):
        p = Principle(id="abc", text="Test", tags=["a"], source_task="task1", created_at="2025-01-01")
        d = p.to_dict()
        assert d["id"] == "abc"
        assert d["text"] == "Test"
        assert d["score"] == 0.5

    def test_from_dict(self):
        data = {
            "id": "abc",
            "text": "Test",
            "tags": ["a", "b"],
            "source_task": "task1",
            "created_at": "2025-01-01",
            "usage_count": 5,
            "success_count": 3,
        }
        p = Principle.from_dict(data)
        assert p.id == "abc"
        assert p.usage_count == 5
        assert p.success_count == 3

    def test_roundtrip(self):
        p = Principle(id="x", text="Test", tags=["t"], source_task="s", created_at="now")
        p.record_usage(True)
        d = p.to_dict()
        p2 = Principle.from_dict(d)
        assert p2.usage_count == 1
        assert p2.success_count == 1


# =============================================================================
# Library - Add & Retrieve
# =============================================================================


class TestLibraryAddRetrieve:
    def test_add_principle(self):
        lib = PrincipleLibrary()
        p = lib.add_principle("Test principle", tags=["coding"], source_task="task1")
        assert p.id != ""
        assert p.text == "Test principle"

    def test_add_deduplicates(self):
        lib = PrincipleLibrary()
        p1 = lib.add_principle("Always verify file paths before writing to disk safely and correctly", tags=["coding"])
        p2 = lib.add_principle(
            "Always verify file paths before writing to disk safely and correctly please", tags=["io"]
        )
        assert p1.id == p2.id
        # Tags should be merged
        assert "coding" in p1.tags
        assert "io" in p1.tags

    def test_retrieve_by_tags(self):
        lib = PrincipleLibrary()
        lib.add_principle("Code carefully", tags=["coding"])
        lib.add_principle("Research first", tags=["research"])
        lib.add_principle("Test everything", tags=["coding", "testing"])

        results = lib.retrieve(tags=["coding"])
        assert len(results) == 2
        texts = {r.text for r in results}
        assert "Code carefully" in texts
        assert "Test everything" in texts

    def test_retrieve_empty_tags_returns_all(self):
        lib = PrincipleLibrary()
        lib.add_principle("P1", tags=["a"])
        lib.add_principle("P2", tags=["b"])
        results = lib.retrieve(tags=None, top_k=10)
        assert len(results) == 2

    def test_retrieve_top_k(self):
        lib = PrincipleLibrary()
        for i in range(10):
            lib.add_principle(f"Principle {i}", tags=["common"])
        results = lib.retrieve(tags=["common"], top_k=3)
        assert len(results) == 3

    def test_retrieve_min_score(self):
        lib = PrincipleLibrary()
        p1 = lib.add_principle("Good principle", tags=["a"])
        p2 = lib.add_principle("Bad principle that is different text", tags=["a"])
        # Make p2 low-scoring
        p2.record_usage(False)
        p2.record_usage(False)
        p2.record_usage(False)

        results = lib.retrieve(tags=["a"], min_score=0.4)
        assert len(results) == 1
        assert results[0].id == p1.id

    def test_retrieve_sorted_by_score(self):
        lib = PrincipleLibrary()
        lib.add_principle("Principle A with unique start text", tags=["common"])
        p2 = lib.add_principle("Principle B also unique initial text", tags=["common"])
        # Make p2 higher scoring
        p2.record_usage(True)
        p2.record_usage(True)

        results = lib.retrieve(tags=["common"], top_k=2)
        assert results[0].id == p2.id


# =============================================================================
# Library - Usage Recording
# =============================================================================


class TestUsageRecording:
    def test_record_usage_success(self):
        lib = PrincipleLibrary()
        p = lib.add_principle("Test", tags=["a"])
        assert lib.record_usage(p.id, success=True)
        assert p.usage_count == 1
        assert p.success_count == 1

    def test_record_usage_failure(self):
        lib = PrincipleLibrary()
        p = lib.add_principle("Test", tags=["a"])
        assert lib.record_usage(p.id, success=False)
        assert p.usage_count == 1
        assert p.success_count == 0

    def test_record_usage_unknown_id(self):
        lib = PrincipleLibrary()
        assert not lib.record_usage("nonexistent", success=True)


# =============================================================================
# Library - Prompt Formatting
# =============================================================================


class TestPromptFormatting:
    def test_format_empty(self):
        lib = PrincipleLibrary()
        assert lib.format_for_prompt(tags=["anything"]) == ""

    def test_format_with_principles(self):
        lib = PrincipleLibrary()
        lib.add_principle("Always test first", tags=["coding"])
        result = lib.format_for_prompt(tags=["coding"])
        assert "LEARNED PRINCIPLES" in result
        assert "Always test first" in result
        assert "reliable" in result

    def test_format_respects_min_score(self):
        lib = PrincipleLibrary()
        p = lib.add_principle("Bad principle with unique text", tags=["coding"])
        # Lower score below 0.3 threshold
        for _ in range(10):
            p.record_usage(False)
        result = lib.format_for_prompt(tags=["coding"])
        assert result == ""


# =============================================================================
# Library - Eviction & Capacity
# =============================================================================


class TestEviction:
    def test_evicts_at_capacity(self):
        lib = PrincipleLibrary(max_principles=5)
        principles = []
        for i in range(6):
            p = lib.add_principle(f"Principle {i} with unique text content here", tags=["a"])
            principles.append(p)
        assert len(lib.get_all()) == 5

    def test_evicts_lowest_scoring(self):
        lib = PrincipleLibrary(max_principles=3)
        lib.add_principle("Good principle unique AAA text", tags=["a"])
        p2 = lib.add_principle("Bad principle unique BBB text", tags=["a"])
        p3 = lib.add_principle("Great principle unique CCC text", tags=["a"])

        # Make p2 low-scoring
        p2.record_usage(False)
        p2.record_usage(False)

        # Make p3 high-scoring
        p3.record_usage(True)
        p3.record_usage(True)

        # Adding p4 should evict p2 (lowest score)
        lib.add_principle("New principle unique DDD text", tags=["a"])

        remaining_ids = {p.id for p in lib.get_all()}
        assert p2.id not in remaining_ids
        assert p3.id in remaining_ids


# =============================================================================
# Library - Persistence
# =============================================================================


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        persist = tmp_path / "principles.json"
        lib = PrincipleLibrary(persist_path=persist)
        lib.add_principle("Test principle", tags=["coding"], source_task="task1")
        lib.save()

        # Load into new instance
        lib2 = PrincipleLibrary(persist_path=persist)
        assert len(lib2.get_all()) == 1
        assert lib2.get_all()[0].text == "Test principle"

    def test_load_nonexistent_file(self, tmp_path):
        persist = tmp_path / "nonexistent.json"
        lib = PrincipleLibrary(persist_path=persist)
        assert len(lib.get_all()) == 0


# =============================================================================
# Library - Stats & Lifecycle
# =============================================================================


class TestStatsAndLifecycle:
    def test_stats_empty(self):
        lib = PrincipleLibrary()
        stats = lib.get_stats()
        assert stats["total_principles"] == 0

    def test_stats_with_data(self):
        lib = PrincipleLibrary()
        p = lib.add_principle("Test", tags=["coding"])
        p.record_usage(True)
        p.record_usage(True)  # Need 2 successes for score >= 0.7: (2+1)/(2+2) = 0.75
        stats = lib.get_stats()
        assert stats["total_principles"] == 1
        assert stats["total_usages"] == 2
        assert stats["high_confidence"] == 1  # score 0.75 >= 0.7

    def test_reset(self):
        lib = PrincipleLibrary()
        lib.add_principle("Test", tags=["a"])
        lib.reset()
        assert len(lib.get_all()) == 0

    def test_get_principle_by_id(self):
        lib = PrincipleLibrary()
        p = lib.add_principle("Test", tags=["a"])
        assert lib.get_principle(p.id) is p
        assert lib.get_principle("nonexistent") is None


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_principle_library()
        l1 = get_principle_library()
        l2 = get_principle_library()
        assert l1 is l2

    def test_reset_creates_new_instance(self):
        reset_principle_library()
        l1 = get_principle_library()
        reset_principle_library()
        l2 = get_principle_library()
        assert l1 is not l2
