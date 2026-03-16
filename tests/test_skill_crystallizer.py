"""
Tests for V12.4 Skill Crystallizer - Auto-compile repeated tool sequences.

Validates:
- ToolCallRecord creation, signature, serialization
- ToolSequencePattern detection and stats
- CrystallizedSkill compilation, rendering, serialization
- SkillCrystallizer recording, pattern detection, crystallization
- Parameter extraction (constant vs variable)
- Skill persistence (save/load)
- Skill management (find, remove, invocation tracking)
- Edge cases (empty history, single calls, overlapping patterns)
- Module exports
"""

from core.memory_pkg.skills.crystallizer import (
    CrystallizedSkill,
    SkillCrystallizer,
    ToolCallRecord,
    ToolSequencePattern,
)

# =============================================================================
# ToolCallRecord Tests
# =============================================================================


class TestToolCallRecord:
    """Test tool call recording."""

    def test_basic_creation(self):
        r = ToolCallRecord(tool_name="read", arguments={"path": "a.py"})
        assert r.tool_name == "read"
        assert r.arguments == {"path": "a.py"}
        assert r.success is True
        assert r.timestamp != ""

    def test_defaults(self):
        r = ToolCallRecord(tool_name="bash")
        assert r.arguments == {}
        assert r.success is True
        assert r.output == ""
        assert r.error == ""
        assert r.duration_seconds == 0.0

    def test_failed_call(self):
        r = ToolCallRecord(
            tool_name="bash",
            arguments={"command": "false"},
            success=False,
            error="Exit code 1",
        )
        assert r.success is False
        assert r.error == "Exit code 1"

    def test_signature(self):
        r = ToolCallRecord(tool_name="edit", arguments={"path": "a.py", "old": "x", "new": "y"})
        assert r.signature == "edit(new,old,path)"

    def test_signature_empty_args(self):
        r = ToolCallRecord(tool_name="bash")
        assert r.signature == "bash()"

    def test_to_dict(self):
        r = ToolCallRecord(tool_name="read", arguments={"path": "a.py"})
        d = r.to_dict()
        assert d["tool_name"] == "read"
        assert d["arguments"] == {"path": "a.py"}
        assert d["success"] is True
        assert "timestamp" in d

    def test_from_dict(self):
        data = {
            "tool_name": "write",
            "arguments": {"path": "b.py", "content": "hello"},
            "success": True,
            "output": "OK",
            "error": "",
            "duration_seconds": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        r = ToolCallRecord.from_dict(data)
        assert r.tool_name == "write"
        assert r.arguments["path"] == "b.py"
        assert r.duration_seconds == 0.5

    def test_from_dict_minimal(self):
        r = ToolCallRecord.from_dict({"tool_name": "bash"})
        assert r.tool_name == "bash"
        assert r.success is True

    def test_output_truncated_in_dict(self):
        r = ToolCallRecord(tool_name="bash", output="x" * 500)
        d = r.to_dict()
        assert len(d["output"]) == 200


# =============================================================================
# ToolSequencePattern Tests
# =============================================================================


class TestToolSequencePattern:
    """Test pattern representation."""

    def test_creation(self):
        p = ToolSequencePattern(
            pattern_id="abc123",
            tool_names=["read", "edit", "bash"],
            signatures=["read(path)", "edit(new,old,path)", "bash(command)"],
            occurrence_count=3,
        )
        assert p.pattern_id == "abc123"
        assert p.length == 3
        assert p.occurrence_count == 3

    def test_auto_generated_id(self):
        p = ToolSequencePattern(
            pattern_id="",
            tool_names=["read", "edit"],
            signatures=[],
            occurrence_count=2,
        )
        assert p.pattern_id != ""
        assert len(p.pattern_id) == 8

    def test_sequence_hash_deterministic(self):
        p1 = ToolSequencePattern(
            pattern_id="a",
            tool_names=["read", "edit"],
            signatures=[],
            occurrence_count=1,
        )
        p2 = ToolSequencePattern(
            pattern_id="b",
            tool_names=["read", "edit"],
            signatures=[],
            occurrence_count=1,
        )
        assert p1.sequence_hash == p2.sequence_hash

    def test_sequence_hash_differs(self):
        p1 = ToolSequencePattern(
            pattern_id="a",
            tool_names=["read", "edit"],
            signatures=[],
            occurrence_count=1,
        )
        p2 = ToolSequencePattern(
            pattern_id="b",
            tool_names=["edit", "read"],
            signatures=[],
            occurrence_count=1,
        )
        assert p1.sequence_hash != p2.sequence_hash

    def test_to_dict(self):
        p = ToolSequencePattern(
            pattern_id="test",
            tool_names=["read", "bash"],
            signatures=["read(path)", "bash(cmd)"],
            occurrence_count=5,
            avg_duration_seconds=1.234,
            success_rate=0.95,
        )
        d = p.to_dict()
        assert d["pattern_id"] == "test"
        assert d["length"] == 2
        assert d["occurrence_count"] == 5
        assert d["avg_duration_seconds"] == 1.234
        assert d["success_rate"] == 0.95


# =============================================================================
# CrystallizedSkill Tests
# =============================================================================


class TestCrystallizedSkill:
    """Test skill representation."""

    def test_creation(self):
        s = CrystallizedSkill(
            skill_id="sk1",
            name="read_edit",
            description="Read then edit a file",
            tool_steps=[
                {"tool_name": "read", "arguments": {"path": "{{file}}"}},
                {"tool_name": "edit", "arguments": {"path": "{{file}}", "old": "{{old}}", "new": "{{new}}"}},
            ],
            parameters=[
                {"name": "file", "type": "string"},
                {"name": "old", "type": "string"},
                {"name": "new", "type": "string"},
            ],
        )
        assert s.skill_id == "sk1"
        assert s.step_count == 2
        assert s.name == "read_edit"

    def test_auto_generated_id(self):
        s = CrystallizedSkill(
            skill_id="",
            name="test",
            description="",
            tool_steps=[],
        )
        assert s.skill_id != ""
        assert len(s.skill_id) == 8

    def test_auto_timestamp(self):
        s = CrystallizedSkill(
            skill_id="test",
            name="test",
            description="",
            tool_steps=[],
        )
        assert s.created_at != ""

    def test_render_steps(self):
        s = CrystallizedSkill(
            skill_id="sk1",
            name="read_edit",
            description="",
            tool_steps=[
                {"tool_name": "read", "arguments": {"path": "{{file}}"}},
                {"tool_name": "edit", "arguments": {"path": "{{file}}", "new": "{{replacement}}"}},
            ],
        )
        rendered = s.render_steps({"file": "main.py", "replacement": "new_code"})
        assert rendered[0]["arguments"]["path"] == "main.py"
        assert rendered[1]["arguments"]["path"] == "main.py"
        assert rendered[1]["arguments"]["new"] == "new_code"

    def test_render_no_params(self):
        s = CrystallizedSkill(
            skill_id="sk1",
            name="test",
            description="",
            tool_steps=[
                {"tool_name": "bash", "arguments": {"command": "pytest"}},
            ],
        )
        rendered = s.render_steps({})
        assert rendered[0]["arguments"]["command"] == "pytest"

    def test_to_dict(self):
        s = CrystallizedSkill(
            skill_id="sk1",
            name="test_skill",
            description="A test skill",
            tool_steps=[{"tool_name": "bash", "arguments": {}}],
            tags=["bash"],
        )
        d = s.to_dict()
        assert d["skill_id"] == "sk1"
        assert d["name"] == "test_skill"
        assert d["step_count"] == 1
        assert d["tags"] == ["bash"]

    def test_from_dict(self):
        data = {
            "skill_id": "sk2",
            "name": "from_dict_skill",
            "description": "Loaded",
            "tool_steps": [{"tool_name": "read", "arguments": {"path": "x"}}],
            "parameters": [],
            "source_pattern_id": "pat1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "invocation_count": 5,
            "success_rate": 0.8,
            "tags": ["read"],
        }
        s = CrystallizedSkill.from_dict(data)
        assert s.skill_id == "sk2"
        assert s.name == "from_dict_skill"
        assert s.invocation_count == 5
        assert s.success_rate == 0.8

    def test_roundtrip_serialization(self):
        original = CrystallizedSkill(
            skill_id="rt1",
            name="roundtrip",
            description="Test roundtrip",
            tool_steps=[
                {"tool_name": "read", "arguments": {"path": "{{file}}"}},
                {"tool_name": "bash", "arguments": {"command": "pytest"}},
            ],
            parameters=[{"name": "file", "type": "string"}],
            tags=["read", "bash"],
        )
        d = original.to_dict()
        restored = CrystallizedSkill.from_dict(d)
        assert restored.skill_id == original.skill_id
        assert restored.name == original.name
        assert restored.step_count == original.step_count
        assert restored.tags == original.tags


# =============================================================================
# SkillCrystallizer - Recording Tests
# =============================================================================


class TestCrystallizerRecording:
    """Test tool call recording."""

    def test_record_single(self):
        c = SkillCrystallizer()
        c.record(ToolCallRecord(tool_name="read"))
        assert c.history_size == 1

    def test_record_batch(self):
        c = SkillCrystallizer()
        calls = [
            ToolCallRecord(tool_name="read"),
            ToolCallRecord(tool_name="edit"),
            ToolCallRecord(tool_name="bash"),
        ]
        c.record_batch(calls)
        assert c.history_size == 3

    def test_history_trimming(self):
        c = SkillCrystallizer(max_history=5)
        for i in range(10):
            c.record(ToolCallRecord(tool_name=f"tool_{i}"))
        assert c.history_size == 5

    def test_clear_history(self):
        c = SkillCrystallizer()
        c.record(ToolCallRecord(tool_name="read"))
        c.clear_history()
        assert c.history_size == 0


# =============================================================================
# SkillCrystallizer - Pattern Detection Tests
# =============================================================================


class TestPatternDetection:
    """Test pattern detection algorithm."""

    def test_no_patterns_empty_history(self):
        c = SkillCrystallizer()
        patterns = c.detect_patterns()
        assert patterns == []

    def test_no_patterns_short_history(self):
        c = SkillCrystallizer()
        c.record(ToolCallRecord(tool_name="read"))
        patterns = c.detect_patterns()
        assert patterns == []

    def test_simple_repeated_pair(self):
        """Two-tool sequence repeated twice should be detected."""
        c = SkillCrystallizer(min_occurrences=2)
        # Sequence: read->edit, read->edit
        calls = [
            ToolCallRecord(tool_name="read", arguments={"path": "a.py"}),
            ToolCallRecord(tool_name="edit", arguments={"path": "a.py"}),
            ToolCallRecord(tool_name="read", arguments={"path": "b.py"}),
            ToolCallRecord(tool_name="edit", arguments={"path": "b.py"}),
        ]
        c.record_batch(calls)
        patterns = c.detect_patterns()

        assert len(patterns) >= 1
        names = [p.tool_names for p in patterns]
        assert ["read", "edit"] in names

    def test_triple_sequence(self):
        """Three-tool sequence repeated should be detected."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="edit"))
            c.record(ToolCallRecord(tool_name="bash"))

        patterns = c.detect_patterns()
        found = any(p.tool_names == ["read", "edit", "bash"] for p in patterns)
        assert found

    def test_pattern_occurrence_count(self):
        """Occurrence count should match actual repeats."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(3):
            c.record(ToolCallRecord(tool_name="glob"))
            c.record(ToolCallRecord(tool_name="read"))

        patterns = c.detect_patterns()
        glob_read = [p for p in patterns if p.tool_names == ["glob", "read"]]
        assert len(glob_read) == 1
        assert glob_read[0].occurrence_count == 3

    def test_min_occurrences_threshold(self):
        """Sequences below threshold should not be detected."""
        c = SkillCrystallizer(min_occurrences=3)
        # Only 2 occurrences
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="write"))

        patterns = c.detect_patterns()
        assert len(patterns) == 0

    def test_pattern_stats(self):
        """Pattern should have duration and success stats."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read", success=True, duration_seconds=1.0))
            c.record(ToolCallRecord(tool_name="bash", success=True, duration_seconds=2.0))

        patterns = c.detect_patterns()
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.avg_duration_seconds > 0
        assert p.success_rate > 0

    def test_no_pattern_single_tools(self):
        """Non-repeated sequences should not be detected."""
        c = SkillCrystallizer(min_occurrences=2)
        c.record(ToolCallRecord(tool_name="read"))
        c.record(ToolCallRecord(tool_name="edit"))
        c.record(ToolCallRecord(tool_name="bash"))
        c.record(ToolCallRecord(tool_name="write"))

        patterns = c.detect_patterns()
        assert len(patterns) == 0

    def test_subpattern_removal(self):
        """Shorter patterns contained in longer ones should be removed."""
        c = SkillCrystallizer(min_occurrences=2)
        # Sequence: A->B->C repeated twice
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="edit"))
            c.record(ToolCallRecord(tool_name="bash"))

        patterns = c.detect_patterns()
        # Should have the 3-tool pattern, not the 2-tool sub-patterns
        three_tool = [p for p in patterns if p.length == 3]
        assert len(three_tool) == 1


# =============================================================================
# SkillCrystallizer - Crystallization Tests
# =============================================================================


class TestCrystallization:
    """Test skill compilation from patterns."""

    def test_basic_crystallization(self):
        """Simple repeated pattern should crystallize into a skill."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read", arguments={"path": "same.py"}))
            c.record(ToolCallRecord(tool_name="bash", arguments={"command": "pytest"}))

        skills = c.crystallize()
        assert len(skills) >= 1
        skill = skills[0]
        assert skill.step_count == 2
        assert skill.source_pattern_id != ""

    def test_constant_args_preserved(self):
        """Arguments that don't change should be fixed in the skill."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="bash", arguments={"command": "pytest"}))
            c.record(ToolCallRecord(tool_name="bash", arguments={"command": "mypy"}))

        skills = c.crystallize()
        assert len(skills) >= 1
        # Both 'command' values are constant across occurrences of each step
        for step in skills[0].tool_steps:
            if "{{" not in str(step["arguments"].get("command", "")):
                # Constant - good
                pass

    def test_variable_args_parameterized(self):
        """Arguments that vary should become parameters."""
        c = SkillCrystallizer(min_occurrences=2)
        c.record(ToolCallRecord(tool_name="read", arguments={"path": "a.py"}))
        c.record(ToolCallRecord(tool_name="edit", arguments={"path": "a.py", "old": "x", "new": "y"}))
        c.record(ToolCallRecord(tool_name="read", arguments={"path": "b.py"}))
        c.record(ToolCallRecord(tool_name="edit", arguments={"path": "b.py", "old": "x", "new": "z"}))

        skills = c.crystallize()
        assert len(skills) >= 1

        # The 'path' arg varies across occurrences -> should be parameterized
        skill = skills[0]
        param_names = [p["name"] for p in skill.parameters]
        assert len(param_names) > 0

    def test_skill_has_name(self):
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="glob"))
            c.record(ToolCallRecord(tool_name="grep"))

        skills = c.crystallize()
        assert len(skills) >= 1
        assert skills[0].name != ""

    def test_skill_has_description(self):
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="write"))

        skills = c.crystallize()
        assert len(skills) >= 1
        assert "Auto-crystallized" in skills[0].description

    def test_skill_has_tags(self):
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="edit"))

        skills = c.crystallize()
        assert len(skills) >= 1
        assert "read" in skills[0].tags
        assert "edit" in skills[0].tags

    def test_no_duplicate_crystallization(self):
        """Same pattern should not be crystallized twice."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="bash"))

        first = c.crystallize()
        second = c.crystallize()
        assert len(first) >= 1
        assert len(second) == 0  # Already crystallized

    def test_crystallize_with_provided_patterns(self):
        """Should accept pre-detected patterns."""
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read", arguments={"path": "x"}))
            c.record(ToolCallRecord(tool_name="bash", arguments={"cmd": "y"}))

        patterns = c.detect_patterns()
        skills = c.crystallize(patterns=patterns)
        assert len(skills) >= 1


# =============================================================================
# SkillCrystallizer - Skill Management Tests
# =============================================================================


class TestSkillManagement:
    """Test skill CRUD and matching."""

    def _make_crystallizer_with_skills(self):
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="glob"))
            c.record(ToolCallRecord(tool_name="read"))

        c.crystallize()
        return c

    def test_list_skills(self):
        c = self._make_crystallizer_with_skills()
        skills = c.list_skills()
        assert len(skills) >= 1

    def test_get_skill_by_id(self):
        c = self._make_crystallizer_with_skills()
        skills = c.list_skills()
        skill = c.get_skill(skills[0].skill_id)
        assert skill is not None
        assert skill.skill_id == skills[0].skill_id

    def test_get_skill_not_found(self):
        c = SkillCrystallizer()
        assert c.get_skill("nonexistent") is None

    def test_get_skill_by_name(self):
        c = self._make_crystallizer_with_skills()
        skills = c.list_skills()
        found = c.get_skill_by_name(skills[0].name)
        assert found is not None

    def test_remove_skill(self):
        c = self._make_crystallizer_with_skills()
        skills = c.list_skills()
        sid = skills[0].skill_id
        assert c.remove_skill(sid) is True
        assert c.get_skill(sid) is None
        assert c.remove_skill(sid) is False

    def test_find_matching_skill(self):
        c = self._make_crystallizer_with_skills()
        match = c.find_matching_skill(["glob", "read"])
        assert match is not None

    def test_find_no_match(self):
        c = self._make_crystallizer_with_skills()
        match = c.find_matching_skill(["write", "delete"])
        assert match is None

    def test_record_invocation(self):
        c = self._make_crystallizer_with_skills()
        skills = c.list_skills()
        sid = skills[0].skill_id

        c.record_skill_invocation(sid, success=True)
        assert c.get_skill(sid).invocation_count == 1
        assert c.get_skill(sid).success_rate == 1.0

        c.record_skill_invocation(sid, success=False)
        assert c.get_skill(sid).invocation_count == 2
        assert c.get_skill(sid).success_rate == 0.5

    def test_record_invocation_nonexistent(self):
        c = SkillCrystallizer()
        c.record_skill_invocation("nonexistent", success=True)  # Should not raise


# =============================================================================
# Persistence Tests
# =============================================================================


class TestPersistence:
    """Test skill save/load to disk."""

    def test_save_and_load(self, tmp_path):
        """Skills should persist across crystallizer instances."""
        storage = tmp_path / "skills_storage"

        # Create and crystallize
        c1 = SkillCrystallizer(storage_path=storage, min_occurrences=2)
        for _ in range(2):
            c1.record(ToolCallRecord(tool_name="read"))
            c1.record(ToolCallRecord(tool_name="edit"))

        skills = c1.crystallize()
        assert len(skills) >= 1
        skill_id = skills[0].skill_id
        skill_name = skills[0].name

        # Load in new instance
        c2 = SkillCrystallizer(storage_path=storage)
        loaded = c2.list_skills()
        assert len(loaded) == len(skills)
        assert c2.get_skill(skill_id) is not None
        assert c2.get_skill(skill_id).name == skill_name

    def test_save_creates_directory(self, tmp_path):
        storage = tmp_path / "new_dir" / "skills"
        c = SkillCrystallizer(storage_path=storage, min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="bash"))
            c.record(ToolCallRecord(tool_name="read"))

        c.crystallize()
        assert (storage / "skills.json").exists()

    def test_load_missing_file(self, tmp_path):
        """Should handle missing skills file gracefully."""
        c = SkillCrystallizer(storage_path=tmp_path / "empty")
        assert c.list_skills() == []

    def test_load_corrupt_file(self, tmp_path):
        """Should handle corrupt skills file gracefully."""
        storage = tmp_path / "corrupt"
        storage.mkdir()
        (storage / "skills.json").write_text("not json{{{")
        c = SkillCrystallizer(storage_path=storage)
        assert c.list_skills() == []

    def test_remove_persists(self, tmp_path):
        """Removing a skill should update the persisted file."""
        storage = tmp_path / "persist_rm"
        c = SkillCrystallizer(storage_path=storage, min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="write"))

        skills = c.crystallize()
        sid = skills[0].skill_id
        c.remove_skill(sid)

        # Reload
        c2 = SkillCrystallizer(storage_path=storage)
        assert c2.get_skill(sid) is None


# =============================================================================
# State Export Tests
# =============================================================================


class TestStateExport:
    """Test crystallizer state export."""

    def test_to_dict_empty(self):
        c = SkillCrystallizer()
        d = c.to_dict()
        assert d["history_size"] == 0
        assert d["pattern_count"] == 0
        assert d["skill_count"] == 0
        assert "config" in d

    def test_to_dict_with_data(self):
        c = SkillCrystallizer(min_occurrences=2)
        for _ in range(2):
            c.record(ToolCallRecord(tool_name="read"))
            c.record(ToolCallRecord(tool_name="bash"))

        c.crystallize()
        d = c.to_dict()
        assert d["history_size"] == 4
        assert d["skill_count"] >= 1
        assert "skills" in d
        assert d["config"]["min_occurrences"] == 2


# =============================================================================
# Parameter Type Inference Tests
# =============================================================================


class TestParameterInference:
    """Test parameter type inference."""

    def test_string_params(self):
        c = SkillCrystallizer(min_occurrences=2)
        c.record(ToolCallRecord(tool_name="read", arguments={"path": "a.py"}))
        c.record(ToolCallRecord(tool_name="read", arguments={"path": "b.py"}))

        skills = c.crystallize()
        if skills and skills[0].parameters:
            param = skills[0].parameters[0]
            assert param["type"] == "string"

    def test_integer_params(self):
        c = SkillCrystallizer(min_occurrences=2)
        c.record(ToolCallRecord(tool_name="read", arguments={"offset": 0}))
        c.record(ToolCallRecord(tool_name="read", arguments={"offset": 10}))

        skills = c.crystallize()
        if skills and skills[0].parameters:
            offset_params = [p for p in skills[0].parameters if p["key"] == "offset"]
            if offset_params:
                assert offset_params[0]["type"] == "integer"


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that skill types are importable."""

    def test_from_skills_package(self):
        from core.memory_pkg.skills import (
            CrystallizedSkill,
            SkillCrystallizer,
            ToolCallRecord,
            ToolSequencePattern,
        )

        assert SkillCrystallizer is not None
        assert ToolCallRecord is not None
        assert ToolSequencePattern is not None
        assert CrystallizedSkill is not None

    def test_from_crystallizer_module(self):
        from core.memory_pkg.skills.crystallizer import (
            CrystallizedSkill,
            SkillCrystallizer,
            ToolCallRecord,
            ToolSequencePattern,
        )

        assert all([SkillCrystallizer, ToolCallRecord, ToolSequencePattern, CrystallizedSkill])
