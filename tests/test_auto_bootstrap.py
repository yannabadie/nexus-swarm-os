"""
Tests for AutoBootstrap - NEXUS V7

Tests automatic NEXUS.md generation for new projects.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.infrastructure.bootstrap.auto_bootstrap import AutoBootstrap, ProjectAnalysis, bootstrap_project

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    project = Path(tempfile.mkdtemp()) / "test_project"
    project.mkdir(parents=True)
    yield project
    shutil.rmtree(project.parent, ignore_errors=True)


@pytest.fixture
def python_project(temp_project):
    """Create a Python project structure."""
    # Create structure
    (temp_project / "src").mkdir()
    (temp_project / "tests").mkdir()
    (temp_project / "docs").mkdir()

    # Create Python files
    (temp_project / "src" / "__init__.py").write_text("")
    (temp_project / "src" / "main.py").write_text("""
from fastapi import FastAPI
import asyncio

app = FastAPI()

def calculate_total(items):
    return sum(items)
""")

    (temp_project / "tests" / "test_main.py").write_text("""
import pytest

def test_calculate():
    assert True
""")

    # Create config files
    (temp_project / "requirements.txt").write_text("""
fastapi>=0.100.0
pytest>=7.0.0
""")

    (temp_project / "pyproject.toml").write_text("""
[project]
name = "test_project"
version = "1.0.0"

[tool.pytest]
testpaths = ["tests"]

[tool.black]
line-length = 100
""")

    (temp_project / "README.md").write_text("# Test Project")

    # Create GitHub Actions
    (temp_project / ".github" / "workflows").mkdir(parents=True)
    (temp_project / ".github" / "workflows" / "ci.yml").write_text("name: CI")

    return temp_project


@pytest.fixture
def node_project(temp_project):
    """Create a Node.js project structure."""
    # Create structure
    (temp_project / "src").mkdir()
    (temp_project / "__tests__").mkdir()

    # Create package.json
    (temp_project / "package.json").write_text(
        json.dumps(
            {
                "name": "test-node-project",
                "version": "1.0.0",
                "scripts": {
                    "start": "node src/index.js",
                    "test": "jest",
                    "build": "webpack --mode production",
                    "lint": "eslint src/",
                },
                "dependencies": {"express": "^4.18.0", "react": "^18.0.0"},
            },
            indent=2,
        )
    )

    # Create JS files
    (temp_project / "src" / "index.js").write_text("""
const express = require('express');
const app = express();

app.get('/', (req, res) => res.send('Hello'));
""")

    (temp_project / "tsconfig.json").write_text("{}")
    (temp_project / ".eslintrc.json").write_text("{}")

    return temp_project


@pytest.fixture
def makefile_project(temp_project):
    """Create a project with Makefile."""
    (temp_project / "src").mkdir()

    (temp_project / "Makefile").write_text("""
.PHONY: all test build clean

all: build

test:
\tpytest tests/

build:
\tpython -m build

clean:
\trm -rf dist/

deploy:
\t./scripts/deploy.sh
""")

    (temp_project / "src" / "main.py").write_text("print('hello')")

    return temp_project


# ============================================================================
# ProjectAnalysis Tests
# ============================================================================


class TestProjectAnalysis:
    """Test ProjectAnalysis dataclass."""

    def test_default_values(self):
        """Analysis should have sensible defaults."""
        analysis = ProjectAnalysis()

        assert analysis.languages == []
        assert analysis.frameworks == []
        assert analysis.databases == []
        assert analysis.tools == []
        assert analysis.directories == []
        assert analysis.key_files == []
        assert analysis.commands == {}
        assert analysis.indentation == "unknown"
        assert analysis.naming_style == "unknown"
        assert not analysis.has_tests
        assert not analysis.has_docs
        assert not analysis.has_ci
        assert analysis.project_name == "Unknown Project"

    def test_analysis_date_set(self):
        """Analysis date should be auto-set."""
        analysis = ProjectAnalysis()
        assert analysis.analysis_date is not None
        assert len(analysis.analysis_date) > 0


# ============================================================================
# AutoBootstrap Initialization Tests
# ============================================================================


class TestAutoBootstrapInit:
    """Test AutoBootstrap initialization."""

    def test_init_with_path(self, temp_project):
        """AutoBootstrap should accept project path."""
        bootstrap = AutoBootstrap(temp_project)
        assert bootstrap.project_path == temp_project.resolve()
        assert bootstrap.analysis is None

    def test_needs_bootstrap_no_nexus_md(self, temp_project):
        """Should need bootstrap when no NEXUS.md exists."""
        bootstrap = AutoBootstrap(temp_project)
        assert bootstrap.needs_bootstrap()

    def test_needs_bootstrap_with_nexus_md(self, temp_project):
        """Should not need bootstrap when NEXUS.md exists."""
        (temp_project / "NEXUS.md").write_text("# Existing")

        bootstrap = AutoBootstrap(temp_project)
        assert not bootstrap.needs_bootstrap()


# ============================================================================
# Language Detection Tests
# ============================================================================


class TestLanguageDetection:
    """Test programming language detection."""

    def test_detect_python(self, python_project):
        """Should detect Python from .py files."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "Python" in analysis.languages

    def test_detect_javascript(self, node_project):
        """Should detect JavaScript from package.json."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()

        assert "JavaScript" in analysis.languages

    def test_detect_typescript(self, node_project):
        """Should detect TypeScript from tsconfig.json."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()

        assert "TypeScript" in analysis.languages


# ============================================================================
# Framework Detection Tests
# ============================================================================


class TestFrameworkDetection:
    """Test framework detection."""

    def test_detect_fastapi(self, python_project):
        """Should detect FastAPI from imports."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "FastAPI" in analysis.frameworks

    def test_detect_express(self, node_project):
        """Should detect Express from require."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()

        assert "Express" in analysis.frameworks

    def test_detect_react(self, node_project):
        """Should detect React from dependencies."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()

        assert "React" in analysis.frameworks


# ============================================================================
# Tool Detection Tests
# ============================================================================


class TestToolDetection:
    """Test development tool detection."""

    def test_detect_pytest(self, python_project):
        """Should detect pytest from imports."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "pytest" in analysis.tools

    def test_detect_black(self, python_project):
        """Should detect Black from pyproject.toml."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "Black" in analysis.tools

    def test_detect_github_actions(self, python_project):
        """Should detect GitHub Actions from .github/workflows."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "GitHub Actions" in analysis.tools

    def test_detect_eslint(self, node_project):
        """Should detect ESLint from .eslintrc."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()

        assert "ESLint" in analysis.tools


# ============================================================================
# Command Discovery Tests
# ============================================================================


class TestCommandDiscovery:
    """Test command discovery."""

    def test_discover_npm_scripts(self, node_project):
        """Should discover npm scripts from package.json."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()

        assert "npm run start" in analysis.commands
        assert "npm run test" in analysis.commands
        assert "npm run build" in analysis.commands

    def test_discover_makefile_targets(self, makefile_project):
        """Should discover Makefile targets."""
        bootstrap = AutoBootstrap(makefile_project)
        analysis = bootstrap.analyze()

        assert "make test" in analysis.commands
        assert "make build" in analysis.commands
        assert "make deploy" in analysis.commands

    def test_discover_pip_install(self, python_project):
        """Should discover pip install when requirements.txt exists."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "pip install -r requirements.txt" in analysis.commands


# ============================================================================
# Structure Analysis Tests
# ============================================================================


class TestStructureAnalysis:
    """Test project structure analysis."""

    def test_find_directories(self, python_project):
        """Should find significant directories."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "src" in analysis.directories
        assert "tests" in analysis.directories
        assert "docs" in analysis.directories

    def test_find_key_files(self, python_project):
        """Should find key configuration files."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert "requirements.txt" in analysis.key_files
        assert "pyproject.toml" in analysis.key_files
        assert "README.md" in analysis.key_files

    def test_has_tests(self, python_project):
        """Should detect test directory."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert analysis.has_tests

    def test_has_docs(self, python_project):
        """Should detect docs directory."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert analysis.has_docs

    def test_has_ci(self, python_project):
        """Should detect CI configuration."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()

        assert analysis.has_ci


# ============================================================================
# NEXUS.md Generation Tests
# ============================================================================


class TestNexusMdGeneration:
    """Test NEXUS.md content generation."""

    def test_generate_includes_project_name(self, python_project):
        """Generated NEXUS.md should include project name."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()
        content = bootstrap.generate_nexus_md(analysis)

        assert "test_project" in content

    def test_generate_includes_tech_stack(self, python_project):
        """Generated NEXUS.md should include tech stack."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()
        content = bootstrap.generate_nexus_md(analysis)

        assert "Tech Stack" in content
        assert "Python" in content
        assert "FastAPI" in content

    def test_generate_includes_commands(self, node_project):
        """Generated NEXUS.md should include commands."""
        bootstrap = AutoBootstrap(node_project)
        analysis = bootstrap.analyze()
        content = bootstrap.generate_nexus_md(analysis)

        assert "Key Commands" in content
        assert "npm run" in content

    def test_generate_includes_structure(self, python_project):
        """Generated NEXUS.md should include project structure."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()
        content = bootstrap.generate_nexus_md(analysis)

        assert "Project Structure" in content
        assert "src/" in content

    def test_generate_includes_conventions(self, python_project):
        """Generated NEXUS.md should include conventions."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()
        content = bootstrap.generate_nexus_md(analysis)

        assert "Code Conventions" in content
        assert "Indentation" in content

    def test_generate_includes_do_not(self, python_project):
        """Generated NEXUS.md should include DO NOT section."""
        bootstrap = AutoBootstrap(python_project)
        analysis = bootstrap.analyze()
        content = bootstrap.generate_nexus_md(analysis)

        assert "DO NOT" in content


# ============================================================================
# Save Tests
# ============================================================================


class TestSave:
    """Test NEXUS.md saving."""

    def test_save_creates_file(self, python_project):
        """Save should create NEXUS.md file."""
        bootstrap = AutoBootstrap(python_project)
        bootstrap.analyze()

        saved_path = bootstrap.save()

        assert saved_path.exists()
        assert saved_path.name == "NEXUS.md"
        assert "test_project" in saved_path.read_text()

    def test_save_custom_path(self, python_project):
        """Save should support custom path."""
        bootstrap = AutoBootstrap(python_project)
        bootstrap.analyze()

        custom_path = python_project / "custom" / "NEXUS.md"
        custom_path.parent.mkdir(parents=True)

        saved_path = bootstrap.save(path=custom_path)

        assert saved_path == custom_path
        assert saved_path.exists()


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestBootstrapProject:
    """Test bootstrap_project convenience function."""

    def test_bootstrap_new_project(self, python_project):
        """Should bootstrap project without NEXUS.md."""
        result = bootstrap_project(python_project)

        assert result is not None
        assert result.exists()
        assert result.name == "NEXUS.md"

    def test_skip_existing_nexus_md(self, python_project):
        """Should skip project with existing NEXUS.md."""
        (python_project / "NEXUS.md").write_text("# Existing")

        result = bootstrap_project(python_project)

        assert result is None

    def test_force_regenerate(self, python_project):
        """Should regenerate with force=True."""
        (python_project / "NEXUS.md").write_text("# Old")

        result = bootstrap_project(python_project, force=True)

        assert result is not None
        content = result.read_text()
        assert "Auto-generated" in content


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_project(self, temp_project):
        """Should handle empty project directory."""
        bootstrap = AutoBootstrap(temp_project)
        analysis = bootstrap.analyze()

        assert analysis.languages == []
        assert analysis.frameworks == []
        assert analysis.project_name == "test_project"

    def test_generate_without_analysis(self, temp_project):
        """Should raise error if generate called before analyze."""
        bootstrap = AutoBootstrap(temp_project)

        with pytest.raises(ValueError, match="No analysis available"):
            bootstrap.generate_nexus_md()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
