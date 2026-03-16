"""
AutoBootstrap - Automatic NEXUS.md Generation

When NEXUS is deployed to a new project without NEXUS.md:
1. Analyze project structure (glob, grep, read key files)
2. Detect tech stack and framework
3. Find key commands (package.json, Makefile, pyproject.toml)
4. Generate initial NEXUS.md

The generated NEXUS.md starts generalist and can be refined as NEXUS works.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ProjectAnalysis:
    """Results of project analysis."""

    # Tech stack detection
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    # Project structure
    directories: list[str] = field(default_factory=list)
    key_files: list[str] = field(default_factory=list)

    # Commands discovered
    commands: dict[str, str] = field(default_factory=dict)

    # Conventions observed
    indentation: str = "unknown"
    naming_style: str = "unknown"
    has_tests: bool = False
    has_docs: bool = False
    has_ci: bool = False

    # Metadata
    project_name: str = "Unknown Project"
    analysis_date: str = field(default_factory=lambda: datetime.now().isoformat())


class AutoBootstrap:
    """
    Automatically analyze a project and generate NEXUS.md.

    Usage:
        bootstrap = AutoBootstrap(project_path)
        analysis = bootstrap.analyze()
        nexus_md = bootstrap.generate_nexus_md(analysis)
        bootstrap.save(nexus_md)
    """

    # Tech stack detection patterns
    LANGUAGE_PATTERNS = {
        "Python": ["*.py", "requirements*.txt", "pyproject.toml", "setup.py", "Pipfile"],
        "JavaScript": ["*.js", "package.json", "*.mjs"],
        "TypeScript": ["*.ts", "*.tsx", "tsconfig.json"],
        "Go": ["*.go", "go.mod", "go.sum"],
        "Rust": ["*.rs", "Cargo.toml"],
        "Java": ["*.java", "pom.xml", "build.gradle"],
        "C#": ["*.cs", "*.csproj", "*.sln"],
        "Ruby": ["*.rb", "Gemfile", "Rakefile"],
        "PHP": ["*.php", "composer.json"],
    }

    FRAMEWORK_PATTERNS = {
        # Python
        "FastAPI": ["from fastapi", "import fastapi"],
        "Django": ["from django", "import django", "DJANGO_SETTINGS"],
        "Flask": ["from flask", "import flask"],
        "PyTorch": ["import torch", "from torch"],
        "TensorFlow": ["import tensorflow", "from tensorflow"],
        # JavaScript/TypeScript
        "React": ["from 'react'", 'from "react"', "@types/react"],
        "Next.js": ["from 'next'", "next.config"],
        "Vue": ["from 'vue'", "@vue/"],
        "Express": ["from 'express'", "require('express')"],
        "NestJS": ["@nestjs/", "from '@nestjs"],
        # Other
        "Spring": ["org.springframework"],
        "Rails": ["Rails.application", "ActionController"],
    }

    DATABASE_PATTERNS = {
        "PostgreSQL": ["psycopg", "postgresql://", "postgres://", "pg_"],
        "MySQL": ["mysql://", "pymysql", "mysql-connector"],
        "MongoDB": ["mongodb://", "pymongo", "mongoose"],
        "SQLite": ["sqlite://", "sqlite3"],
        "Redis": ["redis://", "import redis", "from redis"],
        "Elasticsearch": ["elasticsearch", "from elasticsearch"],
    }

    TOOL_PATTERNS = {
        "Docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
        "Kubernetes": ["*.yaml", "kubectl", "k8s/"],
        "GitHub Actions": [".github/workflows/"],
        "GitLab CI": [".gitlab-ci.yml"],
        "pytest": ["pytest.ini", "conftest.py", "[tool.pytest]"],
        "Jest": ["jest.config*", "@types/jest"],
        "ESLint": [".eslintrc*", "eslint.config*"],
        "Prettier": [".prettierrc*", "prettier.config*"],
        "Black": ["[tool.black]"],
        "Ruff": ["[tool.ruff]", "ruff.toml"],
    }

    def __init__(self, project_path: Path):
        """
        Initialize AutoBootstrap.

        Args:
            project_path: Root path of the project to analyze
        """
        self.project_path = Path(project_path).resolve()
        self.analysis: ProjectAnalysis | None = None

    def analyze(self) -> ProjectAnalysis:
        """
        Perform full project analysis.

        Returns:
            ProjectAnalysis with detected stack, structure, commands
        """
        analysis = ProjectAnalysis()
        analysis.project_name = self.project_path.name

        # Analyze structure
        analysis.directories = self._analyze_directories()
        analysis.key_files = self._find_key_files()

        # Detect tech stack
        analysis.languages = self._detect_languages()
        analysis.frameworks = self._detect_frameworks()
        analysis.databases = self._detect_databases()
        analysis.tools = self._detect_tools()

        # Find commands
        analysis.commands = self._discover_commands()

        # Observe conventions
        analysis.indentation = self._detect_indentation()
        analysis.naming_style = self._detect_naming_style()
        analysis.has_tests = self._has_tests()
        analysis.has_docs = self._has_docs()
        analysis.has_ci = self._has_ci()

        self.analysis = analysis
        return analysis

    def _analyze_directories(self) -> list[str]:
        """Find significant directories."""
        significant_dirs = []
        ignored = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            ".tox",
            ".pytest_cache",
            "dist",
            "build",
            ".next",
            "target",
        }

        try:
            for item in self.project_path.iterdir():
                if item.is_dir() and item.name not in ignored and not item.name.startswith("."):
                    significant_dirs.append(item.name)
        except PermissionError:
            pass

        return sorted(significant_dirs)[:20]  # Limit to 20

    def _find_key_files(self) -> list[str]:
        """Find configuration and key files."""
        key_patterns = [
            "README*",
            "LICENSE*",
            "CHANGELOG*",
            "package.json",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "Makefile",
            "Dockerfile",
            "docker-compose*",
            "requirements*.txt",
            "Pipfile",
            "Cargo.toml",
            "go.mod",
            "tsconfig.json",
            ".env.example",
            "*.config.js",
            "*.config.ts",
        ]

        found = []
        for pattern in key_patterns:
            for match in self.project_path.glob(pattern):
                if match.is_file():
                    found.append(match.name)

        return sorted(set(found))[:30]  # Limit and dedupe

    def _detect_languages(self) -> list[str]:
        """Detect programming languages used."""
        detected = []

        for lang, patterns in self.LANGUAGE_PATTERNS.items():
            for pattern in patterns:
                if pattern.startswith("*"):
                    # File extension pattern
                    matches = list(self.project_path.rglob(pattern))
                    # Exclude common ignored directories
                    matches = [
                        m
                        for m in matches
                        if not any(p in str(m) for p in ["node_modules", "__pycache__", ".git", "venv"])
                    ]
                    if matches:
                        detected.append(lang)
                        break
                else:
                    # Specific file pattern
                    if (self.project_path / pattern).exists():
                        detected.append(lang)
                        break

        return detected

    def _detect_frameworks(self) -> list[str]:
        """Detect frameworks by searching file contents."""
        detected = []

        # Directories/files to exclude (contain detection patterns, not actual usage)
        # Note: Be careful with patterns - they must be specific enough to not
        # match legitimate project directories (e.g., "test_" would match "test_project")
        exclude_patterns = [
            "node_modules",
            "__pycache__",
            ".git",
            "venv",
            "auto_bootstrap.py",  # This file contains detection patterns!
        ]

        # Additional file-specific patterns (match filename, not full path)
        exclude_filenames = [
            "test_auto_bootstrap.py",
            "test_integration.py",
        ]

        # Directories to exclude (using Path parts for cross-platform compatibility)
        exclude_dirs = ["bootstrap", "tests"]

        # Read key files for framework patterns
        files_to_check = []

        # Python files (exclude bootstrap module to avoid false positives)
        for py_file in list(self.project_path.rglob("*.py"))[:50]:
            # Check path patterns (string matching)
            if any(p in str(py_file) for p in exclude_patterns):
                continue
            # Check specific filenames
            if py_file.name in exclude_filenames:
                continue
            # Check directory parts (cross-platform)
            if any(d in py_file.parts for d in exclude_dirs):
                continue
            files_to_check.append(py_file)

        # JavaScript/TypeScript files
        for pattern in ["*.js", "*.ts", "*.jsx", "*.tsx"]:
            for js_file in list(self.project_path.rglob(pattern))[:30]:
                if not any(p in str(js_file) for p in ["node_modules", "__pycache__", ".git"]):
                    files_to_check.append(js_file)

        # Package files
        for name in ["package.json", "requirements.txt", "pyproject.toml", "Cargo.toml"]:
            pkg_file = self.project_path / name
            if pkg_file.exists():
                files_to_check.append(pkg_file)

        # Check patterns
        content_cache: dict[Path, str] = {}

        for framework, patterns in self.FRAMEWORK_PATTERNS.items():
            for file_path in files_to_check:
                try:
                    if file_path not in content_cache:
                        content_cache[file_path] = file_path.read_text(encoding="utf-8", errors="ignore")

                    content = content_cache[file_path]
                    if any(pattern in content for pattern in patterns):
                        if framework not in detected:
                            detected.append(framework)
                        break
                except (PermissionError, OSError):
                    continue

        # Also check package.json dependencies for common frameworks
        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "react" in deps and "React" not in detected:
                    detected.append("React")
                if "vue" in deps and "Vue" not in detected:
                    detected.append("Vue")
                if "express" in deps and "Express" not in detected:
                    detected.append("Express")
                if "@nestjs/core" in deps and "NestJS" not in detected:
                    detected.append("NestJS")
                if "next" in deps and "Next.js" not in detected:
                    detected.append("Next.js")
            except (json.JSONDecodeError, OSError):
                pass

        return detected

    def _detect_databases(self) -> list[str]:
        """Detect databases from connection strings and imports."""
        detected = []

        # Exclude bootstrap module (contains detection patterns)
        exclude_patterns = [
            "node_modules",
            "__pycache__",
            ".git",
            "venv",
            "auto_bootstrap.py",
            "core/bootstrap",
            "test_auto_bootstrap",
        ]

        # Check common config files
        config_files = ["*.py", ".env*", "*.json", "*.yaml", "*.yml", "*.toml"]

        files_to_check = []
        for pattern in config_files:
            for f in list(self.project_path.rglob(pattern))[:30]:
                if not any(p in str(f) for p in exclude_patterns):
                    files_to_check.append(f)

        for db, patterns in self.DATABASE_PATTERNS.items():
            for file_path in files_to_check:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if any(pattern.lower() in content.lower() for pattern in patterns):
                        if db not in detected:
                            detected.append(db)
                        break
                except (PermissionError, OSError):
                    continue

        return detected

    def _detect_tools(self) -> list[str]:
        """Detect development tools."""
        detected = []

        for tool, patterns in self.TOOL_PATTERNS.items():
            found = False
            for pattern in patterns:
                if found:
                    break

                if "/" in pattern:
                    # Directory pattern
                    if (self.project_path / pattern.rstrip("/")).exists():
                        detected.append(tool)
                        found = True
                elif pattern.startswith("["):
                    # TOML section pattern - check pyproject.toml
                    toml_file = self.project_path / "pyproject.toml"
                    if toml_file.exists():
                        try:
                            content = toml_file.read_text(encoding="utf-8")
                            if pattern in content:
                                detected.append(tool)
                                found = True
                        except (PermissionError, OSError):
                            pass
                elif "*" in pattern:
                    # Glob pattern with wildcard
                    matches = list(self.project_path.glob(pattern))
                    if matches:
                        detected.append(tool)
                        found = True
                else:
                    # Exact file pattern
                    if (self.project_path / pattern).exists():
                        detected.append(tool)
                        found = True

        # Special detection: pytest via test file imports
        if "pytest" not in detected:
            test_dirs = ["tests", "test"]
            for test_dir in test_dirs:
                test_path = self.project_path / test_dir
                if test_path.exists():
                    # Check for pytest imports in test files
                    for test_file in list(test_path.rglob("test_*.py"))[:10]:
                        try:
                            content = test_file.read_text(encoding="utf-8", errors="ignore")
                            if "import pytest" in content or "from pytest" in content:
                                detected.append("pytest")
                                break
                        except (PermissionError, OSError):
                            continue
                    if "pytest" in detected:
                        break

        return detected

    def _discover_commands(self) -> dict[str, str]:
        """Discover available commands from package files."""
        commands = {}

        # package.json scripts
        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                for name, cmd in scripts.items():
                    commands[f"npm run {name}"] = cmd[:100]  # Truncate long commands
            except (json.JSONDecodeError, OSError):
                pass

        # Makefile targets
        makefile = self.project_path / "Makefile"
        if makefile.exists():
            try:
                content = makefile.read_text(encoding="utf-8")
                # Find targets (lines starting with word followed by :)
                for match in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:", content, re.MULTILINE):
                    target = match.group(1)
                    if target not in ["PHONY", "all", "default"]:
                        commands[f"make {target}"] = f"Makefile target: {target}"
            except (OSError, UnicodeDecodeError):
                pass

        # pyproject.toml scripts
        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                # Simple TOML parsing for scripts section
                if "[project.scripts]" in content or "[tool.poetry.scripts]" in content:
                    commands["python -m <module>"] = "Entry points defined in pyproject.toml"

                # pytest
                if "pytest" in content.lower():
                    commands["pytest"] = "Run tests with pytest"
            except (OSError, UnicodeDecodeError):
                pass

        # Common commands based on detected files
        if (self.project_path / "requirements.txt").exists():
            commands["pip install -r requirements.txt"] = "Install Python dependencies"

        if (self.project_path / "package.json").exists():
            commands["npm install"] = "Install Node.js dependencies"

        return commands

    def _detect_indentation(self) -> str:
        """Detect common indentation style."""
        # Check a few Python/JS files
        spaces_2 = 0
        spaces_4 = 0
        tabs = 0

        for pattern in ["*.py", "*.js", "*.ts"]:
            for f in list(self.project_path.rglob(pattern))[:10]:
                if any(p in str(f) for p in ["node_modules", "__pycache__", ".git"]):
                    continue
                try:
                    lines = f.read_text(encoding="utf-8").split("\n")[:100]
                    for line in lines:
                        if line.startswith("    ") and not line.startswith("     "):
                            spaces_4 += 1
                        elif line.startswith("  ") and not line.startswith("   "):
                            spaces_2 += 1
                        elif line.startswith("\t"):
                            tabs += 1
                except (OSError, UnicodeDecodeError):
                    continue

        if spaces_4 > spaces_2 and spaces_4 > tabs:
            return "4 spaces"
        elif spaces_2 > spaces_4 and spaces_2 > tabs:
            return "2 spaces"
        elif tabs > 0:
            return "tabs"
        return "unknown"

    def _detect_naming_style(self) -> str:
        """Detect naming conventions."""
        # Check Python files for snake_case vs camelCase
        snake_count = 0
        camel_count = 0

        for f in list(self.project_path.rglob("*.py"))[:20]:
            if any(p in str(f) for p in ["node_modules", "__pycache__", ".git", "venv"]):
                continue
            try:
                content = f.read_text(encoding="utf-8")
                snake_count += len(re.findall(r"\bdef [a-z]+_[a-z]", content))
                camel_count += len(re.findall(r"\bdef [a-z]+[A-Z]", content))
            except (OSError, UnicodeDecodeError):
                continue

        if snake_count > camel_count:
            return "snake_case"
        elif camel_count > snake_count:
            return "camelCase"
        return "mixed"

    def _has_tests(self) -> bool:
        """Check if project has tests."""
        test_indicators = ["tests/", "test/", "spec/", "__tests__/", "*_test.py", "test_*.py", "*.test.js", "*.spec.ts"]

        for indicator in test_indicators:
            if "/" in indicator:
                if (self.project_path / indicator.rstrip("/")).exists():
                    return True
            else:
                if list(self.project_path.rglob(indicator)):
                    return True
        return False

    def _has_docs(self) -> bool:
        """Check if project has documentation."""
        doc_indicators = ["docs/", "documentation/", "doc/", "README.md", "CONTRIBUTING.md"]
        return any((self.project_path / ind.rstrip("/")).exists() for ind in doc_indicators)

    def _has_ci(self) -> bool:
        """Check if project has CI/CD configuration."""
        ci_paths = [
            ".github/workflows",
            ".gitlab-ci.yml",
            ".travis.yml",
            "Jenkinsfile",
            ".circleci/config.yml",
            "azure-pipelines.yml",
        ]
        return any((self.project_path / p).exists() for p in ci_paths)

    def generate_nexus_md(self, analysis: ProjectAnalysis | None = None) -> str:
        """
        Generate NEXUS.md content from analysis.

        Args:
            analysis: ProjectAnalysis (uses self.analysis if not provided)

        Returns:
            NEXUS.md content as string
        """
        if analysis is None:
            analysis = self.analysis
        if analysis is None:
            raise ValueError("No analysis available. Run analyze() first.")

        lines = [
            f"# {analysis.project_name}",
            "",
        ]

        # Extract project description from README if available
        description = self._extract_project_description()
        if description:
            lines.append(f"> {description}")
            lines.append("")

        lines.extend(
            [
                f"> Auto-generated by NEXUS AutoBootstrap ({analysis.analysis_date[:10]})",
                "",
                "---",
                "",
            ]
        )

        # Tech Stack - Enhanced
        lines.append("## Tech Stack")
        lines.append("")

        if analysis.languages:
            for lang in analysis.languages:
                version = self._detect_language_version(lang)
                if version:
                    lines.append(f"- **{lang}**: {version}")
                else:
                    lines.append(f"- **{lang}**")

        if analysis.frameworks:
            lines.append("")
            lines.append("**Frameworks:**")
            for fw in analysis.frameworks:
                lines.append(f"- {fw}")

        if analysis.databases:
            lines.append("")
            lines.append("**Data Storage:**")
            for db in analysis.databases:
                lines.append(f"- {db}")

        if analysis.tools:
            lines.append("")
            lines.append("**Development Tools:**")
            for tool in analysis.tools:
                lines.append(f"- {tool}")

        lines.append("")

        # Project Structure - Enhanced with descriptions
        lines.append("## Project Structure")
        lines.append("")
        lines.append("```")
        lines.append(f"{analysis.project_name}/")

        # Add descriptions for common directory names
        dir_descriptions = {
            "src": "Source code",
            "lib": "Libraries",
            "core": "Core modules",
            "api": "API endpoints",
            "app": "Application code",
            "tests": "Test suite",
            "test": "Test suite",
            "docs": "Documentation",
            "config": "Configuration",
            "scripts": "Utility scripts",
            "utils": "Utilities",
            "helpers": "Helper functions",
            "models": "Data models",
            "views": "View layer",
            "controllers": "Controllers",
            "services": "Business logic",
            "middleware": "Middleware",
            "static": "Static assets",
            "public": "Public files",
            "templates": "Templates",
            "migrations": "DB migrations",
            "fixtures": "Test fixtures",
            "bin": "Executables",
            "dist": "Distribution",
            "build": "Build output",
        }

        for dir_name in analysis.directories[:15]:
            desc = dir_descriptions.get(dir_name.lower(), "")
            if desc:
                lines.append(f"+-- {dir_name}/          # {desc}")
            else:
                lines.append(f"+-- {dir_name}/")

        # Add key files with context
        for file_name in analysis.key_files[:8]:
            lines.append(f"+-- {file_name}")

        lines.append("```")
        lines.append("")

        # Entry Points - NEW SECTION
        entry_points = self._detect_entry_points()
        if entry_points:
            lines.append("## Entry Points")
            lines.append("")
            for entry, desc in entry_points.items():
                lines.append(f"- `{entry}` - {desc}")
            lines.append("")

        # Commands - Enhanced
        if analysis.commands:
            lines.append("## Key Commands")
            lines.append("")

            # Group by type
            install_cmds = {k: v for k, v in analysis.commands.items() if "install" in k.lower()}
            test_cmds = {k: v for k, v in analysis.commands.items() if "test" in k.lower() or "pytest" in k.lower()}
            build_cmds = {k: v for k, v in analysis.commands.items() if "build" in k.lower() or "make" in k.lower()}
            other_cmds = {
                k: v
                for k, v in analysis.commands.items()
                if k not in install_cmds and k not in test_cmds and k not in build_cmds
            }

            if install_cmds:
                lines.append("### Setup")
                lines.append("```bash")
                for cmd in list(install_cmds.keys())[:3]:
                    lines.append(cmd)
                lines.append("```")
                lines.append("")

            if test_cmds:
                lines.append("### Testing")
                lines.append("```bash")
                for cmd in list(test_cmds.keys())[:3]:
                    lines.append(cmd)
                lines.append("```")
                lines.append("")

            if build_cmds:
                lines.append("### Build")
                lines.append("```bash")
                for cmd in list(build_cmds.keys())[:3]:
                    lines.append(cmd)
                lines.append("```")
                lines.append("")

            if other_cmds:
                lines.append("### Other")
                for cmd, desc in list(other_cmds.items())[:5]:
                    lines.append(f"- `{cmd}` - {desc[:60]}")
                lines.append("")

        # Conventions - Enhanced
        lines.append("## Code Conventions")
        lines.append("")
        lines.append(f"- **Indentation:** {analysis.indentation}")
        lines.append(f"- **Naming:** {analysis.naming_style}")

        if analysis.has_tests:
            test_framework = self._detect_test_framework()
            lines.append(f"- **Testing:** {test_framework}")
        else:
            lines.append("- **Testing:** No tests detected")

        if analysis.has_docs:
            lines.append("- **Documentation:** Present")
        if analysis.has_ci:
            ci_type = self._detect_ci_type()
            lines.append(f"- **CI/CD:** {ci_type}")

        lines.append("")

        # DO NOT section - Enhanced with actual detection
        lines.append("## DO NOT")
        lines.append("")

        # Always include these
        lines.append("### Security")
        lines.append("- **DO NOT** commit `.env` files or API keys")
        lines.append("- **DO NOT** commit `credentials.json` or secrets")
        lines.append("- **DO NOT** log sensitive data (passwords, tokens)")
        lines.append("")

        # Detect protected files
        protected = self._detect_protected_files()
        if protected:
            lines.append("### Protected Files")
            for pfile, reason in protected.items():
                lines.append(f"- **DO NOT** modify `{pfile}` - {reason}")
            lines.append("")

        # Framework-specific rules
        fw_rules = self._get_framework_rules(analysis.frameworks)
        if fw_rules:
            lines.append("### Framework Rules")
            for rule in fw_rules:
                lines.append(f"- **DO NOT** {rule}")
            lines.append("")

        # Architecture Notes - NEW SECTION
        arch_notes = self._detect_architecture_patterns()
        if arch_notes:
            lines.append("## Architecture Notes")
            lines.append("")
            for note in arch_notes:
                lines.append(f"- {note}")
            lines.append("")

        # Important Files - NEW SECTION
        important = self._detect_important_files()
        if important:
            lines.append("## Important Files")
            lines.append("")
            for ifile, desc in important.items():
                lines.append(f"- `{ifile}` - {desc}")
            lines.append("")

        # Notes
        lines.append("---")
        lines.append("")
        lines.append("*This NEXUS.md was auto-generated. Customize as needed:*")
        lines.append("- Add project-specific conventions")
        lines.append("- Document architecture decisions")
        lines.append("- Add team coding standards")
        lines.append("- Update DO NOT section with project-specific rules")
        lines.append("")

        return "\n".join(lines)

    def _extract_project_description(self) -> str | None:
        """Extract project description from README or package files."""
        # Try README
        for readme in ["README.md", "README.rst", "README.txt", "README"]:
            readme_path = self.project_path / readme
            if readme_path.exists():
                try:
                    content = readme_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")
                    # Skip title, find first paragraph
                    in_description = False
                    for line in lines:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("="):
                            if in_description:
                                break
                            continue
                        if line.startswith(">") or line.startswith("!"):
                            continue
                        if len(line) > 20:
                            # Found description
                            return line[:150] + ("..." if len(line) > 150 else "")
                except (OSError, UnicodeDecodeError):
                    pass

        # Try package.json description
        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                if "description" in data and data["description"]:
                    return data["description"][:150]
            except (json.JSONDecodeError, OSError):
                pass

        # Try pyproject.toml
        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                match = re.search(r'description\s*=\s*"([^"]+)"', content)
                if match:
                    return match.group(1)[:150]
            except (OSError, UnicodeDecodeError):
                pass

        return None

    def _detect_language_version(self, language: str) -> str | None:
        """Detect language version from config files."""
        if language == "Python":
            # Check pyproject.toml
            pyproject = self.project_path / "pyproject.toml"
            if pyproject.exists():
                try:
                    content = pyproject.read_text(encoding="utf-8")
                    match = re.search(r'python\s*[>=<]+\s*"?(\d+\.\d+)', content, re.IGNORECASE)
                    if match:
                        return f"{match.group(1)}+"
                except (OSError, UnicodeDecodeError):
                    pass
            # Check .python-version
            pv = self.project_path / ".python-version"
            if pv.exists():
                try:
                    return pv.read_text().strip()
                except (OSError, UnicodeDecodeError):
                    pass

        elif language == "JavaScript" or language == "TypeScript":
            # Check package.json engines
            pkg_json = self.project_path / "package.json"
            if pkg_json.exists():
                try:
                    data = json.loads(pkg_json.read_text(encoding="utf-8"))
                    engines = data.get("engines", {})
                    if "node" in engines:
                        return f"Node {engines['node']}"
                except (json.JSONDecodeError, OSError):
                    pass

        return None

    def _detect_entry_points(self) -> dict[str, str]:
        """Detect main entry points for the project."""
        entry_points = {}

        # Python entry points
        for name in ["main.py", "app.py", "__main__.py", "run.py", "server.py", "cli.py"]:
            if (self.project_path / name).exists():
                entry_points[f"python {name}"] = "Main entry point"
            elif (self.project_path / "src" / name).exists():
                entry_points[f"python src/{name}"] = "Main entry point"

        # Check pyproject.toml for scripts
        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "[project.scripts]" in content or "[tool.poetry.scripts]" in content:
                    # Extract script names
                    matches = re.findall(r"(\w+)\s*=", content[content.find("scripts") :])
                    for script in matches[:3]:
                        if script and not script.startswith("_"):
                            entry_points[script] = "CLI command"
            except (OSError, UnicodeDecodeError):
                pass

        # package.json main/bin
        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                if "main" in data:
                    entry_points[f"node {data['main']}"] = "Main module"
                if "bin" in data:
                    if isinstance(data["bin"], str):
                        entry_points["npx <package>"] = "Binary entry"
                    elif isinstance(data["bin"], dict):
                        for cmd in list(data["bin"].keys())[:3]:
                            entry_points[cmd] = "CLI command"
            except (json.JSONDecodeError, OSError):
                pass

        return entry_points

    def _detect_test_framework(self) -> str:
        """Detect which test framework is used."""
        if (self.project_path / "pytest.ini").exists():
            return "pytest"
        if (self.project_path / "conftest.py").exists():
            return "pytest"

        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "[tool.pytest" in content:
                    return "pytest"
            except (OSError, UnicodeDecodeError):
                pass

        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "jest" in deps:
                    return "Jest"
                if "mocha" in deps:
                    return "Mocha"
                if "vitest" in deps:
                    return "Vitest"
            except (json.JSONDecodeError, OSError):
                pass

        return "Tests present"

    def _detect_ci_type(self) -> str:
        """Detect CI/CD system."""
        if (self.project_path / ".github" / "workflows").exists():
            return "GitHub Actions"
        if (self.project_path / ".gitlab-ci.yml").exists():
            return "GitLab CI"
        if (self.project_path / ".travis.yml").exists():
            return "Travis CI"
        if (self.project_path / "Jenkinsfile").exists():
            return "Jenkins"
        if (self.project_path / ".circleci").exists():
            return "CircleCI"
        if (self.project_path / "azure-pipelines.yml").exists():
            return "Azure Pipelines"
        return "CI configured"

    def _detect_protected_files(self) -> dict[str, str]:
        """Detect files that should not be modified."""
        protected = {}

        # Lock files
        lock_files = [
            ("package-lock.json", "Generated by npm"),
            ("yarn.lock", "Generated by yarn"),
            ("pnpm-lock.yaml", "Generated by pnpm"),
            ("Pipfile.lock", "Generated by pipenv"),
            ("poetry.lock", "Generated by poetry"),
            ("Cargo.lock", "Generated by cargo"),
            ("go.sum", "Generated by go modules"),
        ]

        for lock_file, reason in lock_files:
            if (self.project_path / lock_file).exists():
                protected[lock_file] = reason

        # Config files that are usually generated or critical
        if (self.project_path / ".git").exists():
            protected[".git/"] = "Git internal data"

        # Detect migration files
        if (self.project_path / "migrations").exists() or (self.project_path / "alembic").exists():
            protected["migrations/"] = "DB migrations - use migration tools"

        return protected

    def _get_framework_rules(self, frameworks: list[str]) -> list[str]:
        """Get framework-specific DO NOT rules."""
        rules = []

        framework_rules = {
            "Django": [
                "modify `settings.py` without testing",
                "run migrations without backup",
            ],
            "FastAPI": [
                "modify OpenAPI schema manually",
            ],
            "React": [
                "mutate state directly (use setState/hooks)",
            ],
            "Next.js": [
                "modify `.next/` directory",
            ],
            "Express": [
                "expose internal errors to clients",
            ],
        }

        for fw in frameworks:
            if fw in framework_rules:
                rules.extend(framework_rules[fw])

        return rules[:5]  # Limit to 5 rules

    def _detect_architecture_patterns(self) -> list[str]:
        """Detect architectural patterns from project structure."""
        patterns = []

        dirs = set(self.analysis.directories if self.analysis else [])

        # MVC
        if {"models", "views", "controllers"} & dirs:
            patterns.append("MVC pattern detected (models/views/controllers)")

        # API-focused
        if {"api", "endpoints", "routes"} & dirs:
            patterns.append("API-focused architecture (endpoints/routes)")

        # Layered
        if {"services", "repositories"} & dirs:
            patterns.append("Layered architecture (services/repositories)")

        # Monorepo
        if {"packages", "apps", "libs"} & dirs:
            patterns.append("Monorepo structure (packages/apps)")

        # Microservices hint
        if (self.project_path / "docker-compose.yml").exists():
            patterns.append("Docker Compose for multi-container setup")

        # Event-driven
        if {"events", "handlers", "listeners"} & dirs:
            patterns.append("Event-driven components detected")

        return patterns[:5]

    def _detect_important_files(self) -> dict[str, str]:
        """Detect important configuration files."""
        important = {}

        important_files = [
            (".env.example", "Environment template"),
            ("docker-compose.yml", "Docker services definition"),
            ("Dockerfile", "Container build instructions"),
            ("nginx.conf", "Nginx configuration"),
            ("tsconfig.json", "TypeScript configuration"),
            ("webpack.config.js", "Webpack bundler config"),
            ("vite.config.js", "Vite bundler config"),
            (".eslintrc.js", "ESLint rules"),
            (".prettierrc", "Prettier formatting"),
            ("pyproject.toml", "Python project config"),
            ("setup.py", "Python package setup"),
        ]

        for fname, desc in important_files:
            # Check root and common subdirs
            for prefix in ["", "config/", ".config/"]:
                fpath = self.project_path / prefix / fname
                if fpath.exists():
                    important[prefix + fname] = desc
                    break

        return dict(list(important.items())[:8])

    def save(self, content: str | None = None, path: Path | None = None) -> Path:
        """
        Save NEXUS.md to project.

        Args:
            content: NEXUS.md content (generates if not provided)
            path: Save path (defaults to project_path/NEXUS.md)

        Returns:
            Path where file was saved
        """
        if content is None:
            content = self.generate_nexus_md()

        save_path = path or (self.project_path / "NEXUS.md")
        save_path.write_text(content, encoding="utf-8")

        return save_path

    def needs_bootstrap(self) -> bool:
        """
        Check if project needs NEXUS.md generation.

        Returns:
            True if no NEXUS.md exists
        """
        nexus_md = self.project_path / "NEXUS.md"
        return not nexus_md.exists()


def bootstrap_project(project_path: Path, force: bool = False) -> Path | None:
    """
    Convenience function to bootstrap a project.

    Args:
        project_path: Project root path
        force: Generate even if NEXUS.md exists

    Returns:
        Path to generated NEXUS.md, or None if skipped
    """
    bootstrap = AutoBootstrap(project_path)

    if not force and not bootstrap.needs_bootstrap():
        return None

    analysis = bootstrap.analyze()
    content = bootstrap.generate_nexus_md(analysis)
    return bootstrap.save(content)
