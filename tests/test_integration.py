"""
Integration Tests - NEXUS V7.8.1

Tests integration between:
- AutoBootstrap + Commands (REPL)
- HybridSwarmEngine pipeline
- Full orchestration pipeline

V7.8.1: GoT (Graph of Thought) tests removed - Phase 14c cleanup
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.infrastructure.bootstrap import AutoBootstrap

# V7.8.1: GoT imports removed (Phase 14c cleanup)
from core.intelligence.swarm import HybridSwarmEngine
from core.interface_pkg.interface.commands import SLASH_COMMANDS, is_slash_command, parse_command

# ============================================================================
# AutoBootstrap + Commands Integration
# ============================================================================


class TestBootstrapCommandIntegration:
    """Test AutoBootstrap integration with commands system."""

    def test_bootstrap_command_registered(self):
        """Bootstrap command should be in SLASH_COMMANDS."""
        assert any("/bootstrap" in cmd for cmd in SLASH_COMMANDS)

    def test_bootstrap_command_description(self):
        """Bootstrap command should have proper description."""
        for cmd, desc in SLASH_COMMANDS.items():
            if "/bootstrap" in cmd:
                assert "NEXUS.md" in desc or "project" in desc.lower()
                break

    def test_parse_bootstrap_command(self):
        """Should parse /bootstrap command correctly."""
        cmd, args = parse_command("/bootstrap")
        assert cmd == "/bootstrap"
        assert args == ""

    def test_parse_bootstrap_with_path(self):
        """Should parse /bootstrap with path argument."""
        cmd, args = parse_command("/bootstrap /path/to/project")
        assert cmd == "/bootstrap"
        assert args == "/path/to/project"

    def test_is_slash_command_bootstrap(self):
        """Bootstrap should be detected as slash command."""
        assert is_slash_command("/bootstrap")
        assert is_slash_command("/bootstrap ./project")


class TestBootstrapEndToEnd:
    """End-to-end tests for AutoBootstrap."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project structure."""
        base = Path(tempfile.mkdtemp())

        # Create Python project structure
        (base / "src").mkdir()
        (base / "tests").mkdir()
        (base / "docs").mkdir()

        # Python files
        (base / "src" / "__init__.py").write_text("")
        (base / "src" / "main.py").write_text("""
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}
""")

        # Config files
        (base / "pyproject.toml").write_text("""
[project]
name = "test-project"
version = "0.1.0"

[tool.pytest]
testpaths = ["tests"]

[build-system]
requires = ["setuptools"]
""")

        (base / "requirements.txt").write_text("""
fastapi>=0.100.0
uvicorn>=0.22.0
pytest>=7.0.0
""")

        # Test file
        (base / "tests" / "test_main.py").write_text("""
def test_placeholder():
    assert True
""")

        yield base

        # Cleanup
        shutil.rmtree(base, ignore_errors=True)

    def test_full_bootstrap_workflow(self, temp_project):
        """Test complete bootstrap workflow."""
        # 1. Create bootstrap
        bootstrap = AutoBootstrap(temp_project)

        # 2. Analyze project
        analysis = bootstrap.analyze()

        # 3. Verify analysis results
        assert "Python" in analysis.languages
        assert "FastAPI" in analysis.frameworks
        assert analysis.has_tests
        assert analysis.project_name != "Unknown Project"

        # 4. Generate NEXUS.md
        nexus_md = bootstrap.generate_nexus_md(analysis)

        # 5. Verify content
        assert "Python" in nexus_md
        assert "FastAPI" in nexus_md
        assert "pytest" in nexus_md.lower() or "tests" in nexus_md.lower()

        # 6. Save and verify file
        bootstrap.save(nexus_md)
        assert (temp_project / "NEXUS.md").exists()

        # 7. Verify file content matches (normalize line endings)
        saved_content = (temp_project / "NEXUS.md").read_text(encoding="utf-8")
        # Normalize line endings for cross-platform comparison
        assert saved_content.replace("\r\n", "\n") == nexus_md.replace("\r\n", "\n")


# ============================================================================
# Full Pipeline Integration (V7.8.1: GoT tests removed - Phase 14c cleanup)
# ============================================================================


class TestFullPipelineIntegration:
    """Test full NEXUS pipeline integration."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        base = Path(tempfile.mkdtemp())

        (base / "workspace").mkdir()
        (base / "_IO_BUFFER").mkdir()

        yield base

        shutil.rmtree(base, ignore_errors=True)

    # V7.8.1: test_swarm_engine_reset_clears_got removed (GoT removed in Phase 14c)
    # V7.8.1: test_swarm_stats_include_got removed (GoT removed in Phase 14c)

    def test_process_task_basic_flow(self):
        """Test basic task processing flow."""

        def mock_invoke(agent_id, task_type, context):
            return {"content": "Task completed", "status": "success"}

        engine = HybridSwarmEngine(invoke_agent=mock_invoke)

        result = engine.process_task("Simple task")

        assert result is not None
        assert result.status.value in ["completed", "failed"]
        assert result.final_output is not None


# ============================================================================
# Module Import Tests
# ============================================================================


class TestModuleImports:
    """Test that all modules can be imported correctly."""

    def test_import_bootstrap(self):
        """AutoBootstrap should be importable."""
        from core.infrastructure.bootstrap import AutoBootstrap

        assert AutoBootstrap is not None

    # V7.8.1: test_import_reasoning removed (GoT removed in Phase 14c)

    def test_import_swarm(self):
        """SwarmEngine should be importable."""
        from core.intelligence.swarm import HybridSwarmEngine

        assert HybridSwarmEngine is not None

    def test_import_security(self):
        """Security modules should be importable."""
        from core.security_pkg.security import MutationValidator, PathGuardian

        assert PathGuardian is not None
        assert MutationValidator is not None

    def test_import_commands(self):
        """Commands should be importable."""
        from core.interface_pkg.interface.commands import SLASH_COMMANDS, get_help_message

        assert SLASH_COMMANDS is not None
        assert callable(get_help_message)


# ============================================================================
# Cross-Module Integration
# ============================================================================


class TestCrossModuleIntegration:
    """Test integration between different modules."""

    def test_bootstrap_creates_valid_nexus_md(self):
        """Bootstrap should create valid NEXUS.md for swarm consumption."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            (project / "main.py").write_text("print('hello')")

            bootstrap = AutoBootstrap(project)
            analysis = bootstrap.analyze()
            nexus_md = bootstrap.generate_nexus_md(analysis)

            # Should be valid markdown
            assert nexus_md.startswith("#")
            assert len(nexus_md) > 100

    # V7.8.1: test_got_integrates_with_task_analysis removed (GoT removed in Phase 14c)
    # V7.8.1: test_swarm_phase_includes_decomposing removed (GoT removed in Phase 14c)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
