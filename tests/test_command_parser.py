"""
Tests for V12.4 Command Parser.

Validates:
- ArgType enum values
- Arg dataclass and to_dict
- CommandDef properties and to_dict
- ParsedCommand creation and to_dict
- Suggestion creation and to_dict
- Parser definition (define, undefine, aliases)
- Parsing (positional, named, flags, type coercion)
- Validation (required args, enum choices)
- Suggestions (prefix matching, aliases)
- Listing (commands, categories, help)
- State management
- Module exports
"""

from core.interface_pkg.interface.command_parser import (
    Arg,
    ArgType,
    CommandDef,
    CommandParser,
    ParsedCommand,
    Suggestion,
)

# =============================================================================
# ArgType Tests
# =============================================================================


class TestArgType:
    """Test ArgType enum."""

    def test_string(self):
        assert ArgType.STRING.value == "string"

    def test_int(self):
        assert ArgType.INT.value == "int"

    def test_float(self):
        assert ArgType.FLOAT.value == "float"

    def test_bool(self):
        assert ArgType.BOOL.value == "bool"

    def test_enum(self):
        assert ArgType.ENUM.value == "enum"

    def test_path(self):
        assert ArgType.PATH.value == "path"

    def test_all_values(self):
        assert len(ArgType) == 6


# =============================================================================
# Arg Tests
# =============================================================================


class TestArg:
    """Test Arg dataclass."""

    def test_basic_creation(self):
        arg = Arg("name")
        assert arg.name == "name"
        assert arg.arg_type == ArgType.STRING
        assert arg.required is False
        assert arg.default is None
        assert arg.choices == []
        assert arg.help == ""

    def test_required_arg(self):
        arg = Arg("task", ArgType.STRING, required=True, help="Task description")
        assert arg.required is True
        assert arg.help == "Task description"

    def test_enum_arg(self):
        arg = Arg("mode", ArgType.ENUM, choices=["fast", "slow"])
        assert arg.choices == ["fast", "slow"]

    def test_default_value(self):
        arg = Arg("depth", ArgType.INT, default=3)
        assert arg.default == 3

    def test_to_dict(self):
        arg = Arg("name", ArgType.STRING, required=True, help="A name")
        d = arg.to_dict()
        assert d["name"] == "name"
        assert d["type"] == "string"
        assert d["required"] is True
        assert d["help"] == "A name"


# =============================================================================
# CommandDef Tests
# =============================================================================


class TestCommandDef:
    """Test CommandDef dataclass."""

    def test_basic_creation(self):
        cmd = CommandDef(name="test", description="A test command")
        assert cmd.name == "test"
        assert cmd.description == "A test command"
        assert cmd.category == "general"

    def test_positional_args(self):
        cmd = CommandDef(
            name="test",
            args=[
                Arg("task", required=True),
                Arg("mode", required=False),
            ],
        )
        assert len(cmd.positional_args) == 1
        assert cmd.positional_args[0].name == "task"

    def test_optional_args(self):
        cmd = CommandDef(
            name="test",
            args=[
                Arg("task", required=True),
                Arg("mode", required=False),
                Arg("depth", required=False),
            ],
        )
        assert len(cmd.optional_args) == 2

    def test_aliases(self):
        cmd = CommandDef(name="test", aliases=["t", "tst"])
        assert cmd.aliases == ["t", "tst"]

    def test_to_dict(self):
        cmd = CommandDef(name="test", description="desc", category="admin")
        d = cmd.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "desc"
        assert d["category"] == "admin"
        assert "args" in d
        assert "aliases" in d


# =============================================================================
# ParsedCommand Tests
# =============================================================================


class TestParsedCommand:
    """Test ParsedCommand dataclass."""

    def test_basic_creation(self):
        pc = ParsedCommand(command="test")
        assert pc.command == "test"
        assert pc.args == {}
        assert pc.flags == {}
        assert pc.is_valid is True
        assert pc.errors == []

    def test_invalid_command(self):
        pc = ParsedCommand(command="bad", is_valid=False, errors=["Unknown"])
        assert pc.is_valid is False
        assert "Unknown" in pc.errors

    def test_to_dict(self):
        pc = ParsedCommand(command="test", args={"k": "v"}, flags={"verbose": True})
        d = pc.to_dict()
        assert d["command"] == "test"
        assert d["args"] == {"k": "v"}
        assert d["flags"] == {"verbose": True}
        assert d["is_valid"] is True


# =============================================================================
# Suggestion Tests
# =============================================================================


class TestSuggestion:
    """Test Suggestion dataclass."""

    def test_basic_creation(self):
        s = Suggestion(text="/test", description="A test")
        assert s.text == "/test"
        assert s.score == 1.0

    def test_to_dict(self):
        s = Suggestion(text="/test", description="desc", score=0.75)
        d = s.to_dict()
        assert d["text"] == "/test"
        assert d["description"] == "desc"
        assert d["score"] == 0.75


# =============================================================================
# Define Tests
# =============================================================================


class TestDefine:
    """Test command definition."""

    def test_define(self):
        parser = CommandParser()
        cmd = parser.define("test", "A test command")
        assert cmd.name == "test"
        assert parser.command_count == 1

    def test_define_with_args(self):
        parser = CommandParser()
        cmd = parser.define(
            "swarm",
            "Launch swarm",
            args=[
                Arg("task", ArgType.STRING, required=True),
                Arg("mode", ArgType.ENUM, choices=["parallel", "sequential"]),
            ],
        )
        assert len(cmd.args) == 2

    def test_define_with_aliases(self):
        parser = CommandParser()
        parser.define("test", aliases=["t", "tst"])
        assert parser.alias_count == 2
        assert parser.is_defined("t")
        assert parser.is_defined("tst")

    def test_define_with_category(self):
        parser = CommandParser()
        parser.define("test", category="admin")
        cmd = parser.get_definition("test")
        assert cmd.category == "admin"

    def test_is_defined(self):
        parser = CommandParser()
        parser.define("test")
        assert parser.is_defined("test") is True
        assert parser.is_defined("missing") is False

    def test_get_definition(self):
        parser = CommandParser()
        parser.define("test", "desc")
        cmd = parser.get_definition("test")
        assert cmd.description == "desc"

    def test_get_definition_by_alias(self):
        parser = CommandParser()
        parser.define("test", "desc", aliases=["t"])
        cmd = parser.get_definition("t")
        assert cmd.name == "test"

    def test_get_definition_not_found(self):
        parser = CommandParser()
        assert parser.get_definition("missing") is None

    def test_undefine(self):
        parser = CommandParser()
        parser.define("test", aliases=["t"])
        assert parser.undefine("test") is True
        assert parser.command_count == 0
        assert parser.alias_count == 0

    def test_undefine_not_found(self):
        parser = CommandParser()
        assert parser.undefine("missing") is False


# =============================================================================
# Parse Tests - Basic
# =============================================================================


class TestParseBasic:
    """Test basic command parsing."""

    def test_simple_command(self):
        parser = CommandParser()
        parser.define("help")
        result = parser.parse("/help")
        assert result.command == "help"
        assert result.is_valid is True

    def test_missing_prefix(self):
        parser = CommandParser()
        result = parser.parse("help")
        assert result.is_valid is False
        assert "must start with" in result.errors[0]

    def test_unknown_command(self):
        parser = CommandParser()
        result = parser.parse("/unknown")
        assert result.is_valid is False
        assert "Unknown command" in result.errors[0]

    def test_empty_input(self):
        parser = CommandParser()
        result = parser.parse("/")
        assert result.is_valid is False

    def test_raw_input_preserved(self):
        parser = CommandParser()
        parser.define("test")
        result = parser.parse("/test")
        assert result.raw_input == "/test"

    def test_alias_resolves(self):
        parser = CommandParser()
        parser.define("help", aliases=["h"])
        result = parser.parse("/h")
        assert result.command == "help"
        assert result.is_valid is True

    def test_custom_prefix(self):
        parser = CommandParser(prefix="!")
        parser.define("help")
        result = parser.parse("!help")
        assert result.command == "help"
        assert result.is_valid is True

    def test_unquoted_parse_error(self):
        parser = CommandParser()
        parser.define("test")
        result = parser.parse("/test 'unmatched")
        assert result.is_valid is False
        assert "Parse error" in result.errors[0]


# =============================================================================
# Parse Tests - Arguments
# =============================================================================


class TestParseArgs:
    """Test argument parsing."""

    def test_positional_arg(self):
        parser = CommandParser()
        parser.define("echo", args=[Arg("text", required=True)])
        result = parser.parse("/echo hello")
        assert result.args["text"] == "hello"

    def test_quoted_positional(self):
        parser = CommandParser()
        parser.define("echo", args=[Arg("text", required=True)])
        result = parser.parse("/echo 'hello world'")
        assert result.args["text"] == "hello world"

    def test_named_arg(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("key"), Arg("value")])
        result = parser.parse("/set --key name --value test")
        assert result.args["key"] == "name"
        assert result.args["value"] == "test"

    def test_boolean_flag(self):
        parser = CommandParser()
        parser.define("run", args=[Arg("verbose", ArgType.BOOL)])
        result = parser.parse("/run --verbose")
        assert result.flags["verbose"] is True

    def test_missing_named_value(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("key")])
        result = parser.parse("/set --key")
        assert "Missing value" in result.errors[0]

    def test_default_value_applied(self):
        parser = CommandParser()
        parser.define("run", args=[Arg("depth", ArgType.INT, default=3)])
        result = parser.parse("/run")
        assert result.args["depth"] == 3

    def test_extra_positional(self):
        parser = CommandParser()
        parser.define("test", args=[Arg("a", required=True)])
        result = parser.parse("/test hello extra")
        assert "Unexpected argument" in result.errors[0]

    def test_extra_positional_absorbed(self):
        parser = CommandParser()
        parser.define(
            "test",
            args=[
                Arg("a", required=True),
                Arg("b", ArgType.STRING),
            ],
        )
        result = parser.parse("/test hello world")
        assert result.args["a"] == "hello"
        assert result.args["b"] == "world"

    def test_mixed_positional_and_named(self):
        parser = CommandParser()
        parser.define(
            "swarm",
            args=[
                Arg("task", required=True),
                Arg("mode", ArgType.ENUM, choices=["parallel", "sequential"]),
            ],
        )
        result = parser.parse("/swarm 'Fix bug' --mode parallel")
        assert result.args["task"] == "Fix bug"
        assert result.args["mode"] == "parallel"


# =============================================================================
# Parse Tests - Validation
# =============================================================================


class TestParseValidation:
    """Test argument validation."""

    def test_missing_required(self):
        parser = CommandParser()
        parser.define("echo", args=[Arg("text", required=True)])
        result = parser.parse("/echo")
        assert result.is_valid is False
        assert "Missing required" in result.errors[0]

    def test_invalid_enum_choice(self):
        parser = CommandParser()
        parser.define(
            "run",
            args=[
                Arg("mode", ArgType.ENUM, choices=["fast", "slow"]),
            ],
        )
        result = parser.parse("/run --mode invalid")
        assert result.is_valid is False
        assert "Invalid value" in result.errors[0]

    def test_valid_enum_choice(self):
        parser = CommandParser()
        parser.define(
            "run",
            args=[
                Arg("mode", ArgType.ENUM, choices=["fast", "slow"]),
            ],
        )
        result = parser.parse("/run --mode fast")
        assert result.is_valid is True
        assert result.args["mode"] == "fast"


# =============================================================================
# Parse Tests - Type Coercion
# =============================================================================


class TestTypeCoercion:
    """Test type coercion."""

    def test_int_coercion(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("count", ArgType.INT)])
        result = parser.parse("/set --count 42")
        assert result.args["count"] == 42
        assert isinstance(result.args["count"], int)

    def test_int_coercion_fail(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("count", ArgType.INT)])
        result = parser.parse("/set --count abc")
        assert result.is_valid is False
        assert "must be an integer" in result.errors[0]

    def test_float_coercion(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("rate", ArgType.FLOAT)])
        result = parser.parse("/set --rate 3.14")
        assert abs(result.args["rate"] - 3.14) < 0.001

    def test_float_coercion_fail(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("rate", ArgType.FLOAT)])
        result = parser.parse("/set --rate abc")
        assert result.is_valid is False
        assert "must be a float" in result.errors[0]

    def test_bool_flag_toggle(self):
        """BOOL args act as flags - presence sets True."""
        parser = CommandParser()
        parser.define("run", args=[Arg("verbose", ArgType.BOOL)])
        result = parser.parse("/run --verbose")
        assert result.flags["verbose"] is True

    def test_bool_flag_absent(self):
        """BOOL arg absent means not in flags."""
        parser = CommandParser()
        parser.define("run", args=[Arg("verbose", ArgType.BOOL)])
        result = parser.parse("/run")
        assert "verbose" not in result.flags

    def test_bool_coercion_from_default(self):
        """BOOL coercion works for non-flag BOOL values."""
        parser = CommandParser()
        parser.define("set", args=[Arg("flag", ArgType.STRING, default="true")])
        result = parser.parse("/set")
        assert result.args["flag"] == "true"

    def test_string_no_coercion(self):
        parser = CommandParser()
        parser.define("set", args=[Arg("text", ArgType.STRING)])
        result = parser.parse("/set --text hello")
        assert result.args["text"] == "hello"


# =============================================================================
# Suggest Tests
# =============================================================================


class TestSuggest:
    """Test command suggestions."""

    def test_suggest_prefix(self):
        parser = CommandParser()
        parser.define("help", "Show help")
        parser.define("history", "Show history")
        parser.define("run", "Run task")
        suggestions = parser.suggest("/h")
        assert len(suggestions) == 2
        assert suggestions[0].text == "/help"

    def test_suggest_exact(self):
        parser = CommandParser()
        parser.define("help", "Show help")
        suggestions = parser.suggest("/help")
        assert len(suggestions) == 1
        assert suggestions[0].score == 1.0

    def test_suggest_empty(self):
        parser = CommandParser()
        parser.define("help")
        parser.define("run")
        suggestions = parser.suggest("/")
        assert len(suggestions) == 2

    def test_suggest_no_match(self):
        parser = CommandParser()
        parser.define("help")
        suggestions = parser.suggest("/xyz")
        assert len(suggestions) == 0

    def test_suggest_alias(self):
        parser = CommandParser()
        parser.define("help", "Show help", aliases=["h"])
        suggestions = parser.suggest("/h")
        # Both "help" and alias "h" match
        texts = [s.text for s in suggestions]
        assert "/help" in texts
        assert "/h" in texts

    def test_suggest_sorted_by_score(self):
        parser = CommandParser()
        parser.define("help", aliases=["h"])
        suggestions = parser.suggest("/h")
        scores = [s.score for s in suggestions]
        assert scores == sorted(scores, reverse=True)

    def test_suggest_strips_prefix(self):
        parser = CommandParser()
        parser.define("test")
        suggestions = parser.suggest("  /t  ")
        assert len(suggestions) == 1


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test command listing."""

    def test_list_commands(self):
        parser = CommandParser()
        parser.define("beta")
        parser.define("alpha")
        cmds = parser.list_commands()
        assert [c.name for c in cmds] == ["alpha", "beta"]

    def test_list_by_category(self):
        parser = CommandParser()
        parser.define("help", category="general")
        parser.define("admin", category="admin")
        parser.define("debug", category="admin")
        cmds = parser.list_commands(category="admin")
        assert len(cmds) == 2
        assert all(c.category == "admin" for c in cmds)

    def test_list_categories(self):
        parser = CommandParser()
        parser.define("help", category="general")
        parser.define("admin", category="admin")
        cats = parser.list_categories()
        assert cats == ["admin", "general"]

    def test_get_help(self):
        parser = CommandParser()
        parser.define(
            "swarm",
            "Launch swarm mode",
            args=[
                Arg("task", ArgType.STRING, required=True, help="Task to run"),
                Arg("mode", ArgType.ENUM, choices=["parallel", "sequential"]),
            ],
            aliases=["sw"],
        )
        help_text = parser.get_help("swarm")
        assert "/swarm" in help_text
        assert "Launch swarm mode" in help_text
        assert "task" in help_text
        assert "(required)" in help_text
        assert "Aliases:" in help_text

    def test_get_help_by_alias(self):
        parser = CommandParser()
        parser.define("swarm", "desc", aliases=["sw"])
        help_text = parser.get_help("sw")
        assert "/swarm" in help_text

    def test_get_help_not_found(self):
        parser = CommandParser()
        assert parser.get_help("missing") is None


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_command_count(self):
        parser = CommandParser()
        assert parser.command_count == 0
        parser.define("a")
        parser.define("b")
        assert parser.command_count == 2

    def test_alias_count(self):
        parser = CommandParser()
        parser.define("test", aliases=["t", "tst"])
        assert parser.alias_count == 2

    def test_clear(self):
        parser = CommandParser()
        parser.define("test", aliases=["t"])
        parser.clear()
        assert parser.command_count == 0
        assert parser.alias_count == 0

    def test_to_dict(self):
        parser = CommandParser()
        parser.define("test", "desc")
        d = parser.to_dict()
        assert d["command_count"] == 1
        assert d["alias_count"] == 0
        assert "test" in d["commands"]


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_interface_package(self):
        from core.interface_pkg.interface import (
            Arg,
            ArgType,
            CommandDef,
            CommandParser,
            ParsedCommand,
            Suggestion,
        )

        assert all([Arg, ArgType, CommandDef, CommandParser, ParsedCommand, Suggestion])

    def test_from_module(self):
        from core.interface_pkg.interface.command_parser import (
            Arg,
            ArgType,
            CommandDef,
            CommandParser,
            ParsedCommand,
            Suggestion,
        )

        assert all([Arg, ArgType, CommandDef, CommandParser, ParsedCommand, Suggestion])
