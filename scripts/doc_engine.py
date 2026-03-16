#!/usr/bin/env python3
"""
NEXUS Documentation Engine V2.0

Unified documentation synchronization system.
Single source of truth: pyproject.toml via core.version

Modes:
    --check      : Read-only audit (CI-safe, returns exit code 1 if issues)
    --sync       : Update version patterns in docs (requires --apply to write)
    --gen-map    : Generate ARCHITECTURE_MAP_GENERATED.md
    --audit      : Check module READMEs exist and are up-to-date
    --full       : All of the above

Safety:
    - Idempotent (same result if run multiple times)
    - Minimal changes (only version patterns, never content)
    - Dry-run by default (--apply to actually write)
    - All changes logged with before/after

Usage:
    python scripts/doc_engine.py --check              # CI: verify consistency
    python scripts/doc_engine.py --sync               # Show what would change
    python scripts/doc_engine.py --sync --apply       # Actually update files
    python scripts/doc_engine.py --gen-map --apply    # Generate architecture map
    python scripts/doc_engine.py --full --apply       # Everything

Exit Codes:
    0: Success (or dry-run complete)
    1: Issues found (--check mode)
    2: Error during execution

V2.0 Changes:
    - Complete architecture map with 10 ZOOM sections
    - Dynamic extraction of commands, dataclasses, enums
    - Test coverage statistics
    - Command categories
    - Dataclass field details
    - Anti-hallucination validation

Recent Changes:
    - Added ZOOM: Async Primitives section
    - Added ZOOM: Blind Spot Remediations section
    - Enhanced FSM extraction (async handlers detection)
    - Added SagaManager, HealthStateMachine, StagnationPredictor coverage
    - Added async_primitives module scanning
    - Updated anti-hallucination with current runtime structures

Regression Coverage Changes:
    - Added Torture Protocol test scanning
    - Added torture test statistics to architecture map
    - Added torture scenario categories extraction
"""

import os
import re
import sys
import ast
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any
from collections import defaultdict

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.version import NEXUS_CODENAME, NEXUS_VERSION


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class Issue:
    """Documentation issue found during check."""

    severity: str  # ERROR, WARNING, INFO
    file: str
    message: str
    current: str = ""
    expected: str = ""

    def __str__(self):
        result = f"[{self.severity}] {self.file}: {self.message}"
        if self.current and self.expected:
            result += f"\n  Current:  {self.current}\n  Expected: {self.expected}"
        return result


@dataclass
class Change:
    """A change to be applied to a file."""

    file: str
    pattern: str
    old_value: str
    new_value: str
    line_number: int = 0

    def __str__(self):
        return f"{self.file}:{self.line_number} | '{self.old_value}' -> '{self.new_value}'"


@dataclass
class ClassInfo:
    """Information about a Python class."""

    name: str
    file_path: str
    line_number: int
    bases: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    methods: List[str] = field(default_factory=list)
    fields: List[Tuple[str, str]] = field(default_factory=list)  # (name, type)
    is_dataclass: bool = False
    is_enum: bool = False


@dataclass
class FunctionInfo:
    """Information about a Python function."""

    name: str
    file_path: str
    line_number: int
    is_async: bool = False
    docstring: Optional[str] = None


@dataclass
class ModuleInfo:
    """Information about a Python module."""

    path: str
    classes: List[ClassInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    lines_of_code: int = 0


@dataclass
class ComponentInfo:
    """Information about a logical component (directory)."""

    name: str
    path: str
    modules: List[ModuleInfo] = field(default_factory=list)
    total_loc: int = 0
    total_classes: int = 0
    total_functions: int = 0


@dataclass
class CommandInfo:
    """Information about a slash command."""

    name: str
    category: str
    description: str = ""


@dataclass
class DataclassInfo:
    """Information about a dataclass with fields."""

    name: str
    file_path: str
    fields: List[Tuple[str, str, str]] = field(default_factory=list)  # (name, type, default)
    docstring: Optional[str] = None


# =============================================================================
# DOCUMENTATION ENGINE
# =============================================================================


class DocEngine:
    """
    Unified documentation synchronization engine.

    Design Principles:
    1. Single Source of Truth: pyproject.toml via core.version
    2. Minimal Changes: Only version patterns, never content
    3. Idempotent: Same result if run multiple times
    4. Fail-Safe: Pattern not found = WARNING, not ERROR
    5. Visible: All changes logged with before/after
    """

    # Files to synchronize
    SYNC_FILES = {
        "README.md": [
            (r'NEXUS V[\d.]+\s*"[^"]*"', 'NEXUS V{version} "{codename}"'),
            (r"Version-[\d.]+-blue", "Version-{version}-blue"),
            (r"## V[\d.]+ Features", "## V{major_minor} Features"),
            (r"NEXUS V[\d.]+ HIVE MIND", "NEXUS V{major_minor} {codename}"),
            (r"## Architecture \(V[\d.]+\)", "## Architecture (V{major_minor})"),
        ],
        "CLAUDE.md": [
            (r"\*\*Version\*\*: [\d.]+", "**Version**: {version}"),
            (r"# NEXUS V[\d.]+", "# NEXUS V{major_minor}"),
        ],
    }

    def __init__(self, project_root: Path):
        self.root = project_root
        self.version = NEXUS_VERSION
        self.codename = NEXUS_CODENAME
        self.major_minor = ".".join(self.version.split(".")[:2])
        self.issues: List[Issue] = []
        self.changes: List[Change] = []

    def _relative_posix(self, path: Path) -> str:
        """Return a deterministic repo-relative path using POSIX separators."""
        return path.relative_to(self.root).as_posix()

    def _format_pattern(self, pattern: str) -> str:
        """Format a pattern with version variables."""
        return pattern.format(version=self.version, codename=self.codename, major_minor=self.major_minor)

    # =========================================================================
    # MODE: CHECK
    # =========================================================================

    def check(self) -> List[Issue]:
        """Check documentation consistency (read-only)."""
        self.issues = []
        print(f"\n{'=' * 60}")
        print(f"NEXUS Documentation Check")
        print(f"Source of Truth: pyproject.toml -> NEXUS_VERSION={self.version}")
        print(f"{'=' * 60}\n")

        for filename, patterns in self.SYNC_FILES.items():
            file_path = self.root / filename
            if not file_path.exists():
                self.issues.append(Issue(severity="ERROR", file=filename, message="File not found"))
                continue
            content = file_path.read_text(encoding="utf-8")
            for pattern, replacement in patterns:
                expected = self._format_pattern(replacement)
                match = re.search(pattern, content)
                if match:
                    current = match.group(0)
                    expected_pattern = self._format_pattern(replacement)
                    expected_regex = re.escape(expected_pattern)
                    if not re.match(expected_regex.replace(r"\{", "{").replace(r"\}", "}"), current):
                        self.issues.append(
                            Issue(
                                severity="ERROR",
                                file=filename,
                                message=f"Version mismatch for pattern '{pattern}'",
                                current=current,
                                expected=expected_pattern,
                            )
                        )
                else:
                    self.issues.append(
                        Issue(severity="WARNING", file=filename, message=f"Pattern not found: '{pattern}'")
                    )

        self._check_module_readmes()
        self._print_check_results()
        return self.issues

    def _check_module_readmes(self):
        """Check that each core/* module has a README."""
        core_path = self.root / "core"
        if not core_path.exists():
            return
        for module_dir in sorted(core_path.iterdir(), key=lambda candidate: candidate.name):
            if not module_dir.is_dir() or module_dir.name.startswith("_"):
                continue
            readme_path = module_dir / "README.md"
            if not readme_path.exists():
                self.issues.append(
                    Issue(severity="WARNING", file=f"core/{module_dir.name}/README.md", message="Missing README.md")
                )
            else:
                content = readme_path.read_text(encoding="utf-8")
                if "V7." in content and "V8" not in content:
                    self.issues.append(
                        Issue(
                            severity="WARNING",
                            file=f"core/{module_dir.name}/README.md",
                            message="May be outdated (references V7 but not V8)",
                        )
                    )

    def _print_check_results(self):
        """Print check results."""
        errors = [i for i in self.issues if i.severity == "ERROR"]
        warnings = [i for i in self.issues if i.severity == "WARNING"]
        if errors:
            print("[ERRORS]")
            for issue in errors:
                print(f"  {issue}")
            print()
        if warnings:
            print("[WARNINGS]")
            for issue in warnings:
                print(f"  {issue}")
            print()
        if not errors and not warnings:
            print(f"[OK] All documentation is in sync with version {self.version}")
        else:
            print(f"\nSummary: {len(errors)} errors, {len(warnings)} warnings")

    # =========================================================================
    # MODE: SYNC
    # =========================================================================

    def sync(self, apply: bool = False) -> List[Change]:
        """Synchronize version patterns in documentation files."""
        self.changes = []
        print(f"\n{'=' * 60}")
        print(f"NEXUS Documentation Sync {'(DRY RUN)' if not apply else '(APPLYING)'}")
        print(f'Target Version: {self.version} "{self.codename}"')
        print(f"{'=' * 60}\n")

        for filename, patterns in self.SYNC_FILES.items():
            file_path = self.root / filename
            if not file_path.exists():
                print(f"[SKIP] {filename}: File not found")
                continue
            content = file_path.read_text(encoding="utf-8")
            new_content = content
            file_changes = []

            for pattern, replacement in patterns:
                expected = self._format_pattern(replacement)

                def replacer(match, exp=expected, cont=content, fc=file_changes):
                    old_value = match.group(0)
                    if old_value != exp:
                        line_num = cont[: match.start()].count("\n") + 1
                        fc.append(
                            Change(
                                file=filename, pattern=pattern, old_value=old_value, new_value=exp, line_number=line_num
                            )
                        )
                    return exp

                new_content = re.sub(pattern, replacer, new_content)

            if file_changes:
                print(f"[CHANGES] {filename}:")
                for change in file_changes:
                    print(f"  Line {change.line_number}: '{change.old_value}' -> '{change.new_value}'")
                self.changes.extend(file_changes)
                if apply:
                    file_path.write_text(new_content, encoding="utf-8")
                    print(f"  -> Written!")
            else:
                print(f"[OK] {filename}: Already in sync")

        print(f"\nTotal changes: {len(self.changes)}")
        if not apply and self.changes:
            print("(Use --apply to write changes)")
        return self.changes

    # =========================================================================
    # MODE: GENERATE MAP
    # =========================================================================

    def generate_map(self, output_path: Optional[Path] = None, apply: bool = False) -> str:
        """Generate architecture map document."""
        if output_path is None:
            output_path = self.root / "docs" / "ARCHITECTURE_MAP_GENERATED.md"

        print(f"\n{'=' * 60}")
        print(f"NEXUS Architecture Map Generator V2")
        print(f"{'=' * 60}\n")

        scanner = CodebaseScanner(self.root)
        components = scanner.scan()

        extractor = StructureExtractor(self.root)
        structures = extractor.extract()

        generator = MapGeneratorV2(
            version=self.version, codename=self.codename, components=components, structures=structures, root=self.root
        )
        content = generator.generate()

        if apply:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            print(f"[OK] Generated: {output_path}")
            print(f"     {len(content):,} bytes, {content.count(chr(10))} lines")
        else:
            print(f"[DRY RUN] Would generate: {output_path}")
            print(f"          {len(content):,} bytes, {content.count(chr(10))} lines")
            print("(Use --apply to write)")
        return content

    # =========================================================================
    # MODE: AUDIT
    # =========================================================================

    def audit(self) -> Dict[str, str]:
        """Audit module READMEs for existence and currency."""
        print(f"\n{'=' * 60}")
        print(f"NEXUS Module README Audit")
        print(f"{'=' * 60}\n")

        results = {}
        core_path = self.root / "core"

        for module_dir in sorted(core_path.iterdir(), key=lambda candidate: candidate.name):
            if not module_dir.is_dir() or module_dir.name.startswith("_"):
                continue
            readme_path = module_dir / "README.md"
            module_name = module_dir.name

            if not readme_path.exists():
                results[module_name] = "MISSING"
                print(f"[MISSING] core/{module_name}/README.md")
            else:
                content = readme_path.read_text(encoding="utf-8")
                has_v8 = "V8" in content or "v8" in content
                has_v7_only = ("V7" in content or "v7" in content) and not has_v8
                if has_v7_only:
                    results[module_name] = "OUTDATED"
                    print(f"[OUTDATED] core/{module_name}/README.md (V7 references, no V8)")
                else:
                    results[module_name] = "OK"
                    print(f"[OK] core/{module_name}/README.md")

        ok_count = sum(1 for v in results.values() if v == "OK")
        missing_count = sum(1 for v in results.values() if v == "MISSING")
        outdated_count = sum(1 for v in results.values() if v == "OUTDATED")
        print(f"\nSummary: {ok_count} OK, {missing_count} missing, {outdated_count} outdated")
        return results

    # =========================================================================
    # MODE: FULL
    # =========================================================================

    def full(self, apply: bool = False) -> bool:
        """Run all modes: check, sync, gen-map, audit."""
        print(f"\n{'#' * 60}")
        print(f"# NEXUS Documentation Engine V2 - FULL RUN")
        print(f'# Version: {self.version} "{self.codename}"')
        print(f"# Apply: {apply}")
        print(f"{'#' * 60}")

        issues = self.check()
        has_errors = any(i.severity == "ERROR" for i in issues)
        changes = self.sync(apply=apply)
        self.generate_map(apply=apply)
        audit_results = self.audit()

        print(f"\n{'=' * 60}")
        print("FINAL SUMMARY")
        print(f"{'=' * 60}")
        print(f"  Check:  {len(issues)} issues ({sum(1 for i in issues if i.severity == 'ERROR')} errors)")
        print(f"  Sync:   {len(changes)} changes {'applied' if apply else '(dry run)'}")
        print(f"  Audit:  {sum(1 for v in audit_results.values() if v != 'OK')} modules need attention")
        return not has_errors


# =============================================================================
# CODEBASE SCANNER
# =============================================================================


class CodebaseScanner:
    """Scans the codebase and extracts structural information."""

    def __init__(self, root: Path):
        self.root = root

    def scan(self) -> List[ComponentInfo]:
        """Scan core/ directory and return component information."""
        components = []
        core_path = self.root / "core"
        if not core_path.exists():
            return components

        for component_dir in sorted(core_path.iterdir(), key=lambda candidate: candidate.name):
            if not component_dir.is_dir() or component_dir.name.startswith("_"):
                continue
            component = self._scan_component(component_dir)
            components.append(component)
        return components

    def _scan_component(self, path: Path) -> ComponentInfo:
        """Scan a single component directory."""
        component = ComponentInfo(name=path.name, path=path.relative_to(self.root).as_posix())
        for py_file in sorted(path.rglob("*.py"), key=lambda candidate: candidate.as_posix()):
            if py_file.name.startswith("_"):
                continue
            module = self._scan_module(py_file)
            component.modules.append(module)
            component.total_loc += module.lines_of_code
            component.total_classes += len(module.classes)
            component.total_functions += len(module.functions)
        return component

    def _scan_module(self, path: Path) -> ModuleInfo:
        """Scan a single Python module."""
        module = ModuleInfo(path=path.relative_to(self.root).as_posix())
        try:
            content = path.read_text(encoding="utf-8")
            module.lines_of_code = len(content.splitlines())
            tree = ast.parse(content)
            analyzer = CodeAnalyzer(str(path))
            analyzer.visit(tree)
            module.classes = analyzer.classes
            module.functions = analyzer.functions
        except Exception:
            pass
        return module


class CodeAnalyzer(ast.NodeVisitor):
    """AST visitor to extract code structure."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.classes: List[ClassInfo] = []
        self.functions: List[FunctionInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = [self._get_name(b) for b in node.bases]
        is_dataclass = any(self._get_name(d) == "dataclass" for d in node.decorator_list)
        is_enum = "Enum" in bases or "IntEnum" in bases or "StrEnum" in bases
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

        # Extract fields for dataclasses
        fields = []
        if is_dataclass:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    field_type = self._get_annotation(item.annotation) if item.annotation else "Any"
                    fields.append((field_name, field_type))

        class_info = ClassInfo(
            name=node.name,
            file_path=self.file_path,
            line_number=node.lineno,
            bases=bases,
            docstring=ast.get_docstring(node),
            methods=methods,
            fields=fields,
            is_dataclass=is_dataclass,
            is_enum=is_enum,
        )
        self.classes.append(class_info)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not hasattr(self, "_in_class"):
            self.functions.append(
                FunctionInfo(
                    name=node.name,
                    file_path=self.file_path,
                    line_number=node.lineno,
                    is_async=False,
                    docstring=ast.get_docstring(node),
                )
            )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if not hasattr(self, "_in_class"):
            self.functions.append(
                FunctionInfo(
                    name=node.name,
                    file_path=self.file_path,
                    line_number=node.lineno,
                    is_async=True,
                    docstring=ast.get_docstring(node),
                )
            )
        self.generic_visit(node)

    def _get_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        return ""

    def _get_annotation(self, node) -> str:
        """Get type annotation as string."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Subscript):
            base = self._get_annotation(node.value)
            if isinstance(node.slice, ast.Tuple):
                args = ", ".join(self._get_annotation(e) for e in node.slice.elts)
            else:
                args = self._get_annotation(node.slice)
            return f"{base}[{args}]"
        elif isinstance(node, ast.Attribute):
            return f"{self._get_annotation(node.value)}.{node.attr}"
        return "Any"


# =============================================================================
# STRUCTURE EXTRACTOR
# =============================================================================


class StructureExtractor:
    """Extracts high-level structures from the codebase."""

    def __init__(self, root: Path):
        self.root = root

    def _relative_posix(self, path: Path) -> str:
        """Return a deterministic repo-relative path using POSIX separators."""
        return path.relative_to(self.root).as_posix()

    def extract(self) -> Dict:
        """Extract all structures."""
        return {
            "fsm_states": self._extract_enum_values(self.root / "core" / "fsm" / "states.py", "OrchestratorState"),
            "hive_states": self._extract_enum_values(
                self.root / "core" / "intelligence" / "hive_mind" / "types.py", "HiveMindState"
            ),
            "hive_phases": self._extract_enum_values(
                self.root / "core" / "intelligence" / "hive_mind" / "types.py", "HivePhase"
            ),
            "swarm_modes": self._extract_enum_values(
                self.root / "core" / "intelligence" / "swarm" / "collaboration_modes.py", "CollaborationMode"
            ),
            "health_states": self._extract_enum_values(
                self.root / "core" / "fsm" / "health_state_machine.py", "HealthState"
            ),
            "prediction_levels": self._extract_enum_values(
                self.root / "core" / "fsm" / "stagnation_predictor.py", "PredictionLevel"
            ),
            "commands": self._extract_commands_detailed(),
            "enums": self._extract_all_enums(),
            "dataclasses": self._extract_all_dataclasses_detailed(),
            "test_stats": self._get_test_stats(),
            "model_routing": self._extract_model_routing(),
            "fallback_chains": self._extract_fallback_chains(),
            "mode_characteristics": self._extract_mode_characteristics(),
            "async_primitives": self._extract_async_primitives(),
            "async_handlers": self._extract_async_handlers(),
            "saga_phases": self._extract_saga_phases(),
            "recovery_strategies": self._extract_recovery_strategies(),
            "torture_tests": self._extract_torture_tests(),
        }

    def _extract_enum_values(self, file_path: Path, enum_name: str) -> List[str]:
        """Extract values from an enum class."""
        if not file_path.exists():
            return []
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == enum_name:
                    values = []
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    values.append(target.id)
                    return values
        except Exception:
            pass
        return []

    def _extract_commands_detailed(self) -> Dict[str, List[CommandInfo]]:
        """Extract slash commands with categories."""
        categories = {
            "Collaboration": [],
            "Evolution": [],
            "Monitoring": [],
            "Workspace": [],
            "Memory": [],
            "System": [],
        }

        # Command -> Category mapping
        cmd_categories = {
            "swarm": ("Collaboration", "Route task through Hybrid Swarm Engine"),
            "swarm-status": ("Collaboration", "Show current mode + DyLAN metrics"),
            "swarm-fsm": ("Collaboration", "Debug: route via FSM states"),
            "pool-stats": ("Collaboration", "Show agent pool scores"),
            "spawn": ("Evolution", "Create specialized agent"),
            "agents": ("Evolution", "List all spawned agents"),
            "evolve": ("Evolution", "Create child generations"),
            "evolve-status": ("Evolution", "Show evolution stats"),
            "review": ("Evolution", "Review pending children"),
            "specialize": ("Evolution", "Create NEXUS spinoff"),
            "status": ("Monitoring", "Orchestrator state"),
            "telemetry": ("Monitoring", "7-day report"),
            "budget": ("Monitoring", "Budget status"),
            "doctor": ("Monitoring", "Run diagnostics"),
            "workspace": ("Workspace", "Current workspace info"),
            "bootstrap": ("Workspace", "Generate NEXUS.md"),
            "ws": ("Workspace", "Workspace file commands"),
            "learn": ("Memory", "Index into RAG"),
            "forget": ("Memory", "Remove from RAG"),
            "memory-status": ("Memory", "Index statistics"),
            "rag": ("Memory", "RAG commands"),
            "clear": ("System", "Clear terminal"),
            "reset": ("System", "Reset to IDLE"),
            "mode": ("System", "Change mode"),
            "chat": ("System", "Chat-only (no tools)"),
            "help": ("System", "Help message"),
            "tutorial": ("System", "Interactive guide"),
            "quickstart": ("System", "Quick start"),
            "exit": ("System", "Exit NEXUS"),
            "quit": ("System", "Exit NEXUS"),
            "export-telemetry": ("Monitoring", "Export session telemetry"),
        }

        commands_dir = self.root / "core" / "interface_pkg" / "interface" / "commands"
        if not commands_dir.exists():
            return categories

        for py_file in sorted(commands_dir.glob("*.py"), key=lambda candidate: candidate.as_posix()):
            if py_file.name in {"__init__.py", "registry.py"}:
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
            except Exception:
                continue

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if "Command" not in {self._get_base_name(base) for base in node.bases}:
                    continue

                command_name = self._extract_command_property_string(node, "name")
                if not command_name or not command_name.startswith("/"):
                    continue

                command_desc = self._extract_command_property_string(node, "description") or ""
                command_slug = command_name.lstrip("/")
                category, fallback_desc = cmd_categories.get(command_slug, ("System", ""))
                categories[category].append(
                    CommandInfo(
                        name=command_slug,
                        category=category,
                        description=command_desc or fallback_desc,
                    )
                )

        for category in categories:
            unique: dict[str, CommandInfo] = {}
            for cmd in categories[category]:
                unique[cmd.name] = cmd
            categories[category] = [unique[name] for name in sorted(unique)]

        return categories

    def _extract_command_property_string(self, class_node: ast.ClassDef, property_name: str) -> str | None:
        """Extract a literal string returned by a command property method."""
        for item in class_node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != property_name:
                continue
            for stmt in item.body:
                if isinstance(stmt, ast.Return):
                    value = stmt.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        return value.value
        return None

    def _extract_all_enums(self) -> List[Tuple[str, str]]:
        """Extract all enum names with their files."""
        enums = []
        for py_file in sorted((self.root / "core").rglob("*.py"), key=lambda candidate: candidate.as_posix()):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        bases = [self._get_base_name(b) for b in node.bases]
                        if any(b in ("Enum", "IntEnum", "StrEnum") for b in bases):
                            rel_path = self._relative_posix(py_file)
                            enums.append((node.name, rel_path))
            except Exception:
                pass
        return sorted(set(enums), key=lambda item: (item[0], item[1]))

    def _extract_all_dataclasses_detailed(self) -> List[DataclassInfo]:
        """Extract all dataclasses with their fields."""
        dataclasses = []
        for py_file in sorted((self.root / "core").rglob("*.py"), key=lambda candidate: candidate.as_posix()):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        for decorator in node.decorator_list:
                            if self._get_base_name(decorator) == "dataclass":
                                fields = []
                                for item in node.body:
                                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                                        field_name = item.target.id
                                        field_type = self._get_annotation(item.annotation) if item.annotation else "Any"
                                        default = ""
                                        if item.value:
                                            if isinstance(item.value, ast.Constant):
                                                default = repr(item.value.value)
                                            elif isinstance(item.value, ast.Call):
                                                default = "..."
                                        fields.append((field_name, field_type, default))

                                rel_path = self._relative_posix(py_file)
                                dataclasses.append(
                                    DataclassInfo(
                                        name=node.name,
                                        file_path=rel_path,
                                        fields=fields,
                                        docstring=ast.get_docstring(node),
                                    )
                                )
                                break
            except Exception:
                pass
        return sorted(dataclasses, key=lambda item: (item.name, item.file_path))

    def _get_test_stats(self) -> Dict[str, int]:
        """Get test statistics."""
        stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
        tests_dir = self.root / "tests"
        if tests_dir.exists():
            # Count test files and functions
            for py_file in sorted(tests_dir.rglob("test_*.py"), key=lambda candidate: candidate.as_posix()):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    # Count test functions
                    test_count = len(re.findall(r"def test_", content))
                    stats["total"] += test_count
                except Exception:
                    pass
        return stats

    def _extract_model_routing(self) -> Dict[str, Dict[str, str]]:
        """
        Extract model routing configuration dynamically from ModelRouter.

        V2.1: Dynamic extraction - adapts automatically to routing changes.
        """
        routing = {
            "claude": {"model": "", "opus_tasks": [], "sonnet_tasks": []},
            "gemini": {"model": "", "pro_tasks": [], "flash_tasks": []},
        }

        try:
            # Try to import and instantiate ModelRouter
            from core.execution_pkg.routing.model_router import ModelRouter, TaskType

            router = ModelRouter()

            routing["claude"]["model"] = router.opus_model
            routing["claude"]["sonnet_model"] = router.sonnet_model
            routing["claude"]["opus_tasks"] = sorted(t.value for t in router.opus_tasks)
            routing["claude"]["sonnet_tasks"] = sorted(t.value for t in router.sonnet_tasks)

            routing["gemini"]["model"] = router.gemini_pro_model
            routing["gemini"]["flash_model"] = router.gemini_flash_model
            routing["gemini"]["pro_tasks"] = sorted(t.value for t in router.gemini_pro_tasks)
            routing["gemini"]["flash_tasks"] = sorted(t.value for t in router.gemini_flash_tasks)

        except Exception:
            # Fallback to static values if import fails
            routing["claude"]["opus_tasks"] = ["brainstorm", "redteam", "architect", "evolution"]
            routing["claude"]["sonnet_tasks"] = ["tool", "validation", "simple", "format"]
            routing["gemini"]["pro_tasks"] = ["reasoning", "research", "analysis"]
            routing["gemini"]["flash_tasks"] = ["simple", "format", "validation"]

        return routing

    def _extract_fallback_chains(self) -> Dict[str, Optional[str]]:
        """
        Extract fallback chains dynamically from CollaborationMode.fallback_mode.

        V2.1: Dynamic extraction - adapts automatically to mode changes.
        """
        fallbacks = {}

        try:
            # Try to import CollaborationMode and extract from fallback_mode property
            from core.intelligence.swarm.collaboration_modes import CollaborationMode

            for mode in CollaborationMode:
                fallback = mode.fallback_mode
                fallbacks[mode.value.upper()] = fallback.value.upper() if fallback else None

        except Exception:
            # Fallback to static values if import fails
            fallbacks = {
                "PARALLEL": "SEQUENTIAL",
                "SEQUENTIAL": "SPECIALIST",
                "LEAD_SUPPORT": "SPECIALIST",
                "PING_PONG": "SEQUENTIAL",
                "RED_BLUE": "LEAD_SUPPORT",
                "SPECIALIST": None,
            }

        return fallbacks

    def _extract_mode_characteristics(self) -> Dict[str, Dict]:
        """
        Extract mode characteristics dynamically from MODE_CHARACTERISTICS.

        V2.1: Dynamic extraction - adapts automatically to new modes.
        """
        characteristics = {}

        try:
            from core.intelligence.swarm.collaboration_modes import MODE_CHARACTERISTICS

            for mode, char in MODE_CHARACTERISTICS.items():
                characteristics[mode.value] = {
                    "description": char.description,
                    "when_to_use": char.when_to_use,
                    "complexity_affinity": char.complexity_affinity,
                    "parallelism_benefit": char.parallelism_benefit,
                    "adversarial": char.adversarial,
                    "typical_rounds": char.typical_rounds,
                }

        except Exception:
            characteristics = {
                "parallel": {
                    "description": "Both agents work simultaneously on independent subtasks",
                },
                "sequential": {
                    "description": "First agent outputs, second agent refines or continues",
                },
                "lead_support": {
                    "description": "Lead agent drives, support agent reviews and assists",
                },
                "ping_pong": {
                    "description": "Rapid alternation until convergence",
                },
                "specialist": {
                    "description": "Single expert handles the task while the other stays idle",
                },
                "red_blue": {
                    "description": "Adversarial propose/attack/defend review loop",
                },
            }

        return characteristics

    def _get_base_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            return self._get_base_name(node.func)
        return ""

    def _get_annotation(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Subscript):
            base = self._get_annotation(node.value)
            if isinstance(node.slice, ast.Tuple):
                args = ", ".join(self._get_annotation(e) for e in node.slice.elts)
            else:
                args = self._get_annotation(node.slice)
            return f"{base}[{args}]"
        elif isinstance(node, ast.Attribute):
            return f"{self._get_annotation(node.value)}.{node.attr}"
        return "Any"

    # =========================================================================
    # Async/runtime extractors
    # =========================================================================

    def _extract_async_primitives(self) -> Dict[str, List[str]]:
        """Extract async primitives from core/foundation/async_primitives/."""
        primitives = {"classes": [], "files": []}
        async_path = self.root / "core" / "foundation" / "async_primitives"
        if not async_path.exists():
            return primitives

        for py_file in sorted(async_path.glob("*.py"), key=lambda candidate: candidate.as_posix()):
            if py_file.name.startswith("_"):
                continue
            primitives["files"].append(py_file.name)
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        primitives["classes"].append(node.name)
            except Exception:
                pass
        return primitives

    def _extract_async_handlers(self) -> List[str]:
        """Extract async handler methods from fsm_handlers.py."""
        handlers = []
        handler_file = self.root / "core" / "execution_pkg" / "orchestration" / "fsm_handlers.py"
        if not handler_file.exists():
            return handlers

        try:
            content = handler_file.read_text(encoding="utf-8")
            # Find async def handle_*_async methods
            pattern = r"async\s+def\s+(handle_\w+_async)"
            handlers = re.findall(pattern, content)
        except Exception:
            pass
        return handlers

    def _extract_saga_phases(self) -> List[str]:
        """Extract PHASE_ORDER from saga_manager.py."""
        phases = []
        saga_file = self.root / "core" / "intelligence" / "hive_mind" / "saga_manager.py"
        if not saga_file.exists():
            return phases

        try:
            content = saga_file.read_text(encoding="utf-8")
            # Find PHASE_ORDER list
            match = re.search(r"PHASE_ORDER\s*=\s*\[(.*?)\]", content, re.DOTALL)
            if match:
                phase_str = match.group(1)
                phases = re.findall(r'"(\w+)"', phase_str)
        except Exception:
            pass
        return phases

    def _extract_recovery_strategies(self) -> List[str]:
        """Extract recovery strategies from health_state_machine.py."""
        strategies = []
        health_file = self.root / "core" / "fsm" / "health_state_machine.py"
        if not health_file.exists():
            return strategies

        try:
            content = health_file.read_text(encoding="utf-8")
            # Find strategy registrations
            pattern = r'RecoveryStrategy\s*\(\s*name\s*=\s*"(\w+)"'
            strategies = re.findall(pattern, content)
        except Exception:
            pass
        return strategies

    def _extract_torture_tests(self) -> Dict[str, Any]:
        """Extract Torture Protocol V8 test statistics."""
        torture_stats = {"total_tests": 0, "categories": {}, "files": [], "markers": []}

        torture_dir = self.root / "tests" / "torture"
        if not torture_dir.exists():
            return torture_stats

        # Extract category stats from scenario files
        scenarios_dir = torture_dir / "scenarios"
        category_map = {
            "saga_crash.py": ("Saga Crash Recovery", "CR"),
            "saga_concurrency.py": ("Saga Concurrency", "CC"),
            "context_edge.py": ("Context Edge Cases", "CE"),
            "compensation.py": ("Compensation Failures", "CF"),
            "hive_integration.py": ("HiveMind Integration", "HM"),
        }

        for filename, (category_name, prefix) in category_map.items():
            file_path = scenarios_dir / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    # Count test functions
                    test_count = len(re.findall(rf"def test_{prefix.lower()}\d+", content))
                    torture_stats["categories"][category_name] = test_count
                    torture_stats["total_tests"] += test_count
                    torture_stats["files"].append(filename)
                except Exception:
                    pass

        # Extract markers from base.py or torture_v8.py
        torture_v8 = self.root / "tests" / "torture_v8.py"
        if torture_v8.exists():
            try:
                content = torture_v8.read_text(encoding="utf-8")
                markers = re.findall(r"@pytest\.mark\.(\w+)", content)
                torture_stats["markers"] = list(set(m for m in markers if m.startswith("torture")))
            except Exception:
                pass

        return torture_stats


# =============================================================================
# MAP GENERATOR - enhanced with async primitives and torture protocol coverage
# =============================================================================


class MapGeneratorV2:
    """Generates the complete architecture map document V2."""

    def __init__(self, version: str, codename: str, components: List[ComponentInfo], structures: Dict, root: Path):
        self.version = version
        self.codename = codename
        self.components = components
        self.structures = structures
        self.root = root

    def generate(self) -> str:
        """Generate the complete architecture map."""
        sections = [
            self._generate_header(),
            self._generate_toc(),
            self._generate_overview(),
            self._generate_component_summary(),
            self._generate_orchestration_zoom(),
            self._generate_llm_drivers_zoom(),
            self._generate_swarm_zoom(),
            self._generate_hive_mind_zoom(),
            self._generate_async_primitives_zoom(),
            self._generate_blind_spot_remediations_zoom(),
            self._generate_evolution_zoom(),
            self._generate_memory_zoom(),
            self._generate_security_zoom(),
            self._generate_functional_inventory(),
            self._generate_key_dataclasses(),
            self._generate_statistics(),
            self._generate_torture_protocol_zoom(),
            self._generate_anti_hallucination(),
            self._generate_footer(),
        ]
        return "\n".join(sections)

    def _generate_header(self) -> str:
        return f"""# NEXUS V{self.version} Architecture Map

**Generation Mode**: Deterministic output from the checked-out codebase
**Generator**: `scripts/doc_engine.py` V2
**Codename**: "{self.codename}"

---

> This document is automatically generated by scanning the codebase.
> It provides a complete, verified view of the NEXUS architecture.

---
"""

    def _generate_toc(self) -> str:
        return """## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [ZOOM: Orchestration Core](#2-zoom-orchestration-core)
3. [ZOOM: LLM Drivers & Routing](#3-zoom-llm-drivers--routing)
4. [ZOOM: Swarm Engine](#4-zoom-swarm-engine)
5. [ZOOM: Hive Mind Pipeline](#5-zoom-hive-mind-pipeline)
6. [ZOOM: Async Primitives](#6-zoom-async-primitives)
7. [ZOOM: Blind Spot Remediations](#7-zoom-blind-spot-remediations)
8. [ZOOM: Evolution & Spawning](#8-zoom-evolution--spawning)
9. [ZOOM: Memory Systems](#9-zoom-memory-systems)
10. [ZOOM: Security & Governance](#10-zoom-security--governance)
11. [Functional Inventory](#11-functional-inventory)
12. [Key Dataclasses](#12-key-dataclasses)
13. [Statistics](#13-statistics)
14. [Torture Protocol](#14-torture-protocol)
15. [Anti-Hallucination Reference](#15-anti-hallucination-reference)

---
"""

    def _generate_overview(self) -> str:
        commands = self.structures.get("commands", {})
        total_commands = sum(len(cmds) for cmds in commands.values())
        return f"""## 1. HIGH-LEVEL OVERVIEW

```mermaid
graph TD
    subgraph Entry["Entry Layer"]
        USER[User Input]
        REPL[REPL<br/>{total_commands} commands]
    end

    subgraph Core["Orchestration Core"]
        ORCH[OrchestratorV7<br/>11 FSM states]
        SWARM[Swarm Engine<br/>6 modes]
        HIVE[Hive Mind<br/>7 phases]
    end

    subgraph LLM["LLM Drivers"]
        GEMINI[Gemini Driver<br/>Persistent Session]
        CLAUDE[Claude Driver<br/>Hybrid XML]
    end

    subgraph Support["Support Systems"]
        MEM[Memory<br/>RAG + Success]
        SEC[Security<br/>Execution Policy + Guards]
        EVOL[Evolution<br/>Spawn + Validate]
        TEL[Telemetry<br/>Budget Tracking]
    end

    USER --> REPL
    REPL --> ORCH
    ORCH -->|"MODERATE+"| HIVE
    ORCH -->|"SIMPLE"| SWARM
    HIVE -->|"delegate"| SWARM
    SWARM --> GEMINI
    SWARM --> CLAUDE
    SEC -.->|"validates"| ORCH
    MEM -.->|"boosts"| SWARM
    TEL -.->|"limits"| LLM
    EVOL -.->|"spawns"| SWARM
```

### Architecture Summary

| Layer | Components | Purpose |
|-------|------------|---------|
| **Entry** | REPL, Commands | User interaction |
| **Orchestration** | FSM, Router | State management, task routing |
| **Collaboration** | Swarm, Hive Mind | Multi-agent coordination |
| **LLM** | Gemini, Claude | Model execution |
| **Support** | Memory, Security, Evolution, Telemetry | Cross-cutting concerns |

"""

    def _generate_component_summary(self) -> str:
        lines = [
            "### Component Summary",
            "",
            "| Component | Files | LOC | Classes | Functions |",
            "|-----------|-------|-----|---------|-----------|",
        ]

        for comp in sorted(self.components, key=lambda c: -c.total_loc):
            lines.append(
                f"| {comp.name} | {len(comp.modules)} | {comp.total_loc:,} | {comp.total_classes} | {comp.total_functions} |"
            )

        return "\n".join(lines) + "\n"

    def _generate_orchestration_zoom(self) -> str:
        states = self.structures.get("fsm_states", [])
        states_list = "\n".join(f"| `{s}` | - |" for s in states)

        return f"""## 2. ZOOM: Orchestration Core

### FSM State Diagram

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE --> BRAINSTORMING: user_input
    IDLE --> SWARM_ANALYZING: /swarm or auto-route

    BRAINSTORMING --> EXECUTING_TOOL: tool_call
    BRAINSTORMING --> WAITING_USER: task_done

    EXECUTING_TOOL --> VALIDATING_CFL: tool_result
    VALIDATING_CFL --> BRAINSTORMING: continue
    VALIDATING_CFL --> WAITING_USER: done

    SWARM_ANALYZING --> SWARM_NEGOTIATING: analysis_done
    SWARM_NEGOTIATING --> SWARM_EXECUTING: mode_agreed
    SWARM_EXECUTING --> VALIDATING_CFL: execution_done

    WAITING_USER --> IDLE: new_input

    BRAINSTORMING --> ERROR: exception
    ERROR --> IDLE: /reset
    ERROR --> PANIC: fatal
```

### Decision Points

```mermaid
graph TD
    INPUT[User Input] --> GUARD{{Input + Runtime<br/>Guards}}
    GUARD -->|PASS| ANALYZE{{Task<br/>Complexity?}}
    GUARD -->|BLOCK| REJECT[Reject]

    ANALYZE -->|TRIVIAL| FAST[Fast Path<br/>Direct Response]
    ANALYZE -->|SIMPLE| SWARM[Swarm Engine]
    ANALYZE -->|MODERATE+| GATE{{Hive Mind<br/>Enabled?}}

    GATE -->|Yes| HIVE[Hive Mind Pipeline]
    GATE -->|No| SWARM

    HIVE --> DELEGATE[Swarm Execution]
```

### Orchestrator States ({len(states)} total)

| State | Description |
|-------|-------------|
{states_list}

**Source**: `core/fsm/states.py`

"""

    def _generate_llm_drivers_zoom(self) -> str:
        routing = self.structures.get("model_routing", {})

        # Build dynamic routing table from extracted data
        claude_routing = routing.get("claude", {})
        gemini_routing = routing.get("gemini", {})

        opus_tasks = claude_routing.get("opus_tasks", [])
        sonnet_tasks = claude_routing.get("sonnet_tasks", [])
        pro_tasks = gemini_routing.get("pro_tasks", [])
        flash_tasks = gemini_routing.get("flash_tasks", [])

        # Build routing table rows dynamically
        routing_rows = []
        for task in opus_tasks:
            routing_rows.append(f"| {task.upper()} | Claude Opus 4.6 | Complex reasoning, creativity |")
        for task in sonnet_tasks:
            routing_rows.append(f"| {task.upper()} | Claude Sonnet 4.6 | Speed, tool use |")
        for task in pro_tasks:
            if task not in opus_tasks:  # Avoid duplicates
                routing_rows.append(f"| {task.upper()} | Gemini 3.1 Pro Preview | Large context, analysis |")
        for task in flash_tasks:
            if task not in sonnet_tasks and task not in pro_tasks:
                routing_rows.append(f"| {task.upper()} | Gemini 3 Flash Preview | Quick responses |")
        routing_table = "\n".join(routing_rows) if routing_rows else "| DEFAULT | Claude Sonnet | Default routing |"

        return f"""## 3. ZOOM: LLM Drivers & Routing

### Model Selection

```mermaid
graph TD
    subgraph Routing["Model Router"]
        TASK[TaskType] --> ROUTER{{{{Model<br/>Router}}}}
        ROUTER -->|BRAINSTORM| OPUS[Claude Opus 4.6]
        ROUTER -->|REASONING| SONNET[Claude Sonnet 4.6]
        ROUTER -->|TOOL| SONNET
        ROUTER -->|SIMPLE| HAIKU[Claude Haiku 4.5]
        ROUTER -->|RESEARCH| PRO[Gemini 3.1 Pro Preview]
        ROUTER -->|FAST| FLASH[Gemini 3 Flash Preview]
    end

    subgraph Drivers["LLM Drivers"]
        OPUS --> CLAUDE_DRV[Claude Driver<br/>Hybrid XML + Tools]
        SONNET --> CLAUDE_DRV
        HAIKU --> CLAUDE_DRV
        PRO --> GEMINI_DRV[Gemini Driver<br/>JSON Protocol]
        FLASH --> GEMINI_DRV
    end

    subgraph Session["Session Management"]
        GEMINI_DRV --> SESS[Session Manager<br/>UUID Isolation]
        CLAUDE_DRV --> SESS
        SESS --> PERSIST[(Session State)]
    end
```

### Model Routing Table (Dynamic)

| Task Type | Model | Reasoning |
|-----------|-------|-----------|
{routing_table}

**Claude Tasks**: Opus -> {", ".join(opus_tasks) if opus_tasks else "N/A"} | Sonnet -> {", ".join(sonnet_tasks) if sonnet_tasks else "N/A"}
**Gemini Tasks**: Pro -> {", ".join(pro_tasks) if pro_tasks else "N/A"} | Flash -> {", ".join(flash_tasks) if flash_tasks else "N/A"}

### Spawned Agent Provider Selection

```mermaid
graph TD
    SPAWN["#47;spawn role"] --> BIRTH[BIRTH_CERTIFICATE.json]
    BIRTH --> INF{{{{inference.provider}}}}
    INF -->|gemini| GEMINI_DRV[Gemini Driver]
    INF -->|claude| CLAUDE_DRV[Claude Driver]

    subgraph Selection["V8.1.8-B Selection Logic"]
        DOMAIN[Domain Analysis] --> MATCH{{{{Best Match?}}}}
        MATCH -->|Code/Tools| CLAUDE_DRV
        MATCH -->|Research| GEMINI_DRV
        MATCH -->|Creative| CLAUDE_DRV
    end
```

**Source**: `core/execution_pkg/routing/model_router.py`, `core/drivers/`

"""

    def _generate_swarm_zoom(self) -> str:
        modes = self.structures.get("swarm_modes", [])
        fallbacks = self.structures.get("fallback_chains", {})
        characteristics = self.structures.get("mode_characteristics", {})

        # Build dynamic fallback chain for Mermaid diagram
        fallback_mermaid = []
        mode_abbrev = {
            "PARALLEL": "M1",
            "SEQUENTIAL": "M2",
            "LEAD_SUPPORT": "M3",
            "PING_PONG": "M4",
            "SPECIALIST": "M5",
            "RED_BLUE": "M6",
        }
        for mode, fallback in fallbacks.items():
            if fallback:
                src = mode_abbrev.get(mode, mode[:2])
                dst = mode_abbrev.get(fallback, fallback[:2])
                fallback_mermaid.append(f"        {src} -.->|fail| {dst}")
        fallback_diagram = "\n".join(fallback_mermaid)

        # Build dynamic mode descriptions from characteristics
        mode_table_rows = []
        for mode in modes:
            mode_lower = mode.lower()
            mode_upper = mode.upper() if mode != mode.upper() else mode
            char = characteristics.get(mode_lower, {})
            desc = char.get("description", "")
            fallback = fallbacks.get(mode_upper, fallbacks.get(mode, "None"))
            fallback_str = fallback if fallback else "None (terminal)"
            mode_table_rows.append(f"| `{mode_upper}` | {desc} | {fallback_str} |")
        mode_table = "\n".join(mode_table_rows)

        fallback_table = "\n".join(
            f"| `{m}` | `{fallbacks.get(m, 'None')}` |"
            for m in [mode.upper() if mode != mode.upper() else mode for mode in modes]
        )

        return f"""## 4. ZOOM: Swarm Engine

### Task Analysis & Mode Selection

```mermaid
graph TD
    subgraph Analysis["Task Analysis"]
        TASK[Task] --> ANALYZER[TaskAnalyzer]
        ANALYZER --> COMPLEXITY{{{{Complexity}}}}
        COMPLEXITY -->|TRIVIAL| SKIP[Skip Swarm]
        COMPLEXITY -->|SIMPLE+| SELECT[ModeSelector]
    end

    subgraph Selection["Mode Selection"]
        SELECT --> DYLAN[DyLAN Scores]
        SELECT --> MEMORY[SuccessMemory<br/>+0-30% boost]
        DYLAN --> PROPOSE[Proposed Mode]
        MEMORY --> PROPOSE
    end

    subgraph Negotiation["Negotiation Protocol"]
        PROPOSE --> NEG{{{{Negotiate?}}}}
        NEG -->|Yes| DEBATE[Max 4 turns]
        NEG -->|No| EXEC
        DEBATE --> AGREED[Agreed Mode]
        AGREED --> EXEC[Execute]
    end

    subgraph Modes["{len(modes)} Collaboration Modes"]
        EXEC --> M1[PARALLEL<br/>Independent work]
        EXEC --> M2[SEQUENTIAL<br/>Pipeline]
        EXEC --> M3[LEAD_SUPPORT<br/>80/20 split]
        EXEC --> M4[PING_PONG<br/>Rapid alternation]
        EXEC --> M5[SPECIALIST<br/>Single expert]
        EXEC --> M6[RED_BLUE<br/>Adversarial]
    end

    subgraph Fallback["Fallback Chain"]
{fallback_diagram}
    end
```

### Collaboration Modes ({len(modes)})

| Mode | Description | Fallback |
|------|-------------|----------|
{mode_table}

### Fallback Chain

| Mode | Fallback To |
|------|-------------|
{fallback_table}

**Source**: `core/intelligence/swarm/collaboration_modes.py`, `core/intelligence/swarm/mode_executors.py`

"""

    def _generate_hive_mind_zoom(self) -> str:
        states = self.structures.get("hive_states", [])
        phases = self.structures.get("hive_phases", [])

        # Group states by phase
        phase_states = defaultdict(list)
        for state in states:
            if "ANALYZING" in state:
                phase_states["Phase 1: Analysis"].append(state)
            elif "DEBAT" in state or "CONSENSUS" in state:
                phase_states["Phase 2: Debate"].append(state)
            elif "ARCHITECT" in state or "REGISTRY" in state or "SPAWN" in state:
                phase_states["Phase 3: Architecture"].append(state)
            elif "EXECUT" in state or "MONITOR" in state:
                phase_states["Phase 4: Execution"].append(state)
            elif "DIAGNOS" in state:
                phase_states["Phase 5: Diagnosis"].append(state)
            elif "RETRY" in state:
                phase_states["Phase 6: Retry"].append(state)
            elif "REFLECT" in state or "RETENTION" in state or "CONSOLIDAT" in state:
                phase_states["Phase 7: Consolidation"].append(state)
            elif "SUCCESS" in state or "FAILED" in state or "ESCALATE" in state:
                phase_states["Terminal"].append(state)
            else:
                phase_states["Other"].append(state)

        phase_table = ""
        for phase, phase_state_list in phase_states.items():
            if phase_state_list:
                phase_table += f"| {phase} | {', '.join(f'`{s}`' for s in phase_state_list)} |\n"

        return f"""## 5. ZOOM: Hive Mind Pipeline

### 7-Phase Pipeline

```mermaid
graph TD
    subgraph Phase1["Phase 1: Analysis"]
        P1A[HIVE_ANALYZING_GEMINI] --> P1B[HIVE_ANALYZING_CLAUDE]
        P1B --> P1C[HIVE_COMPARING_ANALYSES]
        P1C --> P1D{{Agreement<br/>> 85%?}}
    end

    subgraph Phase2["Phase 2: Debate"]
        P1D -->|No| P2A[HIVE_DEBATING<br/>3-10 turns]
        P1D -->|Yes| P3A
        P2A --> P2B[HIVE_CHECKING_CONSENSUS]
        P2B --> BP1[BREAKPOINT:<br/>AFTER_DEBATE]
    end

    subgraph Phase3["Phase 3: Architecture"]
        BP1 --> P3A[HIVE_ARCHITECTING]
        P3A --> P3B[HIVE_CHECKING_REGISTRY]
        P3B --> P3C{{Spawn<br/>Needed?}}
        P3C -->|Yes| BP2[BREAKPOINT:<br/>BEFORE_SPAWN]
        P3C -->|No| P4A
        BP2 --> P3D[HIVE_SPAWNING]
        P3D --> P4A
    end

    subgraph Phase4["Phase 4: Execution"]
        P4A[HIVE_EXECUTING] --> P4B[HIVE_MONITORING]
        P4B --> P4C{{Success?}}
    end

    subgraph Phase5["Phase 5: Diagnosis"]
        P4C -->|No| P5A[HIVE_DIAGNOSING]
        P5A --> BP3[BREAKPOINT:<br/>AFTER_DIAGNOSIS]
    end

    subgraph Phase6["Phase 6: Retry"]
        BP3 --> P6A{{Retry?<br/>max 3}}
        P6A -->|Yes| P3A
        P6A -->|No| FAIL[HIVE_FAILED]
    end

    subgraph Phase7["Phase 7: Consolidation"]
        P4C -->|Yes| P7A[HIVE_REFLECTING]
        P7A --> P7B[HIVE_DECIDING_RETENTION]
        P7B --> BP4[BREAKPOINT:<br/>CONSOLIDATION]
        BP4 --> P7C[HIVE_CONSOLIDATING]
        P7C --> SUCCESS[HIVE_SUCCESS]
    end
```

### HiveMind States ({len(states)} total)

| Phase | States |
|-------|--------|
{phase_table}

### User Breakpoints

| Breakpoint | Location | Purpose |
|------------|----------|---------|
| `AFTER_DEBATE` | After Phase 2 | Review debate consensus |
| `BEFORE_SPAWN` | Before spawning | Approve agent creation |
| `AFTER_DIAGNOSIS` | After failure analysis | Review fix strategy |
| `CONSOLIDATION` | Before knowledge archival | Review learnings |

**Source**: `core/intelligence/hive_mind/types.py`, `core/intelligence/hive_mind/phases/`

"""

    def _generate_async_primitives_zoom(self) -> str:
        """Generate Async Primitives section."""
        primitives = self.structures.get("async_primitives", {})
        classes = primitives.get("classes", [])
        files = primitives.get("files", [])
        async_handlers = self.structures.get("async_handlers", [])

        classes_list = ", ".join(f"`{c}`" for c in classes) if classes else "None found"
        files_list = ", ".join(f"`{f}`" for f in files) if files else "None found"
        handlers_list = (
            "\n".join(f"| `{h}()` | Non-blocking handler |" for h in async_handlers)
            if async_handlers
            else "| None | - |"
        )

        return f"""## 6. ZOOM: Async Primitives

### Overview

The current runtime exposes a complete async infrastructure for non-blocking operations.

```mermaid
graph TD
    subgraph Primitives["core/foundation/async_primitives/"]
        CT[CancellationToken<br/>Hierarchical cancellation]
        PH[AsyncProcessHandle<br/>Subprocess tracking]
        RW[AsyncRWLock<br/>Reader-Writer lock]
        BB[AsyncBlackboard<br/>Shared state + TTL]
    end

    subgraph Usage["Integration Points"]
        DRIVERS[Async Drivers] --> CT
        DRIVERS --> PH
        HIVE[Hive Mind] --> BB
        FSM[FSM Handlers] --> RW
    end

    subgraph Control["Cancellation Flow"]
        USER[Ctrl+C] --> FACTORY[AsyncDriverFactory]
        FACTORY --> |cancel_all| CT
        CT --> |propagate| PH
        PH --> |terminate| PROC[Subprocess]
    end
```

### Async Primitive Classes

| Class | Purpose |
|-------|---------|
| `CancellationToken` | Hierarchical cancellation with callbacks |
| `CancellationTokenSource` | Creates and controls tokens |
| `AsyncProcessHandle` | Track subprocess by UUID |
| `ProcessHandleRegistry` | Global registry for cancel_by_uuid |
| `AsyncRWLock` | Multiple readers OR single writer |
| `AsyncBlackboard` | Thread-safe shared state with TTL |

**Files**: {files_list}
**Classes**: {classes_list}

### Async Handlers (FSMHandlers)

| Handler | Purpose |
|---------|---------|
{handlers_list}

**Source**: `core/foundation/async_primitives/`, `core/execution_pkg/orchestration/fsm_handlers.py`

"""

    def _generate_blind_spot_remediations_zoom(self) -> str:
        """Generate Blind Spot Remediations section."""
        health_states = self.structures.get("health_states", [])
        prediction_levels = self.structures.get("prediction_levels", [])
        saga_phases = self.structures.get("saga_phases", [])
        recovery_strategies = self.structures.get("recovery_strategies", [])

        health_table = "\n".join(f"| `{s}` |" for s in health_states) if health_states else "| None |"
        prediction_table = "\n".join(f"| `{p}` |" for p in prediction_levels) if prediction_levels else "| None |"
        saga_table = " -> ".join(saga_phases) if saga_phases else "Not found"
        recovery_table = "\n".join(f"| `{s}` |" for s in recovery_strategies) if recovery_strategies else "| None |"

        return f"""## 7. ZOOM: Blind Spot Remediations

### Overview

The current runtime addresses architectural blind spots with dedicated modules.

```mermaid
graph TD
    subgraph P0["P0: NexusJSONEncoder"]
        JSON[Serialization] --> DT[datetime -> isoformat]
        JSON --> EN[Enum -> value]
        JSON --> UUID[UUID -> str]
    end

    subgraph P2["P2: SagaManager"]
        SAGA[SagaManager] --> CP[Checkpoint Phase]
        SAGA --> RB[Rollback + Context Truncation]
        SAGA --> GD[Phase Guards]
    end

    subgraph P3["P3: Async Handlers"]
        ASYNC[FSMHandlers] --> BRA[handle_brainstorming_async]
        ASYNC --> CFL[handle_validating_cfl_async]
        ASYNC --> FP[handle_fast_path_async]
    end

    subgraph P4["P4: HealthStateMachine"]
        HEALTH[HealthFSM] --> STATES[5 States]
        HEALTH --> RECOV[Recovery Strategies]
        STATES --> HEALTHY
        STATES --> DEGRADED
        STATES --> CRITICAL
        STATES --> RECOVERING
        STATES --> PANIC
    end

    subgraph P5["P5: StagnationPredictor"]
        STAG[Predictor] --> IND[Leading Indicators]
        STAG --> TRAJ[Trajectory Analysis]
        STAG --> ACT[Prediction Levels]
    end
```

### HealthStateMachine States

| State |
|-------|
{health_table}

**Transitions**: HEALTHY -> DEGRADED (1 error) -> CRITICAL (3 errors) -> RECOVERING/PANIC

### Recovery Strategies

| Strategy |
|----------|
{recovery_table}

### SagaManager Phase Order

```
{saga_table}
```

**Features**:
- Atomic checkpoints via `AtomicJsonStore`
- Context truncation on rollback (`messages[:checkpoint_index]`)
- Phase guards before each transition

### StagnationPredictor Levels

| Level |
|-------|
{prediction_table}

**Thresholds**: CONTINUE (<0.4) -> MONITOR (0.4-0.6) -> NUDGE (0.6-0.8) -> INTERVENE (>0.8)

### Implementation Summary

| Phase | Module | Lines |
|-------|--------|-------|
| P0 | `core/utils/serialization.py` | ~240 |
| P1 | `core/intelligence/hive_mind/async_adapter.py` | +80 |
| P2 | `core/intelligence/hive_mind/saga_manager.py` | ~640 |
| P3 | `core/execution_pkg/orchestration/fsm_handlers.py` | +290 |
| P4 | `core/fsm/health_state_machine.py` | ~549 |
| P5 | `core/fsm/stagnation_predictor.py` | ~476 |

**Source**: `core/intelligence/hive_mind/saga_manager.py`, `core/fsm/health_state_machine.py`, `core/fsm/stagnation_predictor.py`

"""

    def _generate_evolution_zoom(self) -> str:
        return """## 8. ZOOM: Evolution & Spawning

### /spawn Flow

```mermaid
graph TD
    subgraph Spawn["/spawn Flow - V8.1.8"]
        CMD["#47;spawn SQL Expert"] --> BUDGET{{Budget<br/>OK?}}
        BUDGET -->|No| REJECT[Reject]
        BUDGET -->|Yes| UUID[Generate UUID]
        UUID --> DOMAIN[Detect Domains]
        DOMAIN --> BRAIN[BrainstormPhase<br/>Gemini + Claude]
        BRAIN --> PROMPT[Generated Prompt]
        PROMPT --> MODEL[V8.1.8-B:<br/>Select Model]
        MODEL --> CERT[BIRTH_CERTIFICATE.json]
        CERT --> POOL[Register AgentPool]
    end

    subgraph Validation["5-Tier Validation"]
        CHILD[Child NEXUS] --> T1[Tier 1: Syntax]
        T1 --> T2[Tier 2: Smoke Test]
        T2 --> T3[Tier 3: Benchmark]
        T3 --> T4[Tier 4: Red Team]
        T4 --> T5[Tier 5: Live Eval]
        T5 --> PROMOTE{{Auto-Promote?}}
    end

    subgraph Promotion["Promotion Criteria"]
        PROMOTE -->|+3% perf| AUTO[Auto-Promote]
        PROMOTE -->|Manual| REVIEW[Human Review]
        AUTO --> LINEAGE[Update LINEAGE.json]
        REVIEW --> LINEAGE
    end
```

### BIRTH_CERTIFICATE.json Structure

```json
{
  "uuid": "agent-uuid-here",
  "role": "SQL Expert",
  "created_at": "2025-12-09T...",
  "parent_version": "8.3.2",
  "inference": {
    "provider": "claude",
    "model": "claude-sonnet-4-5"
  },
  "domains": ["database", "sql", "optimization"],
  "prompt_hash": "sha256:..."
}
```

### Evolution Commands

| Command | Description |
|---------|-------------|
| `/spawn <role>` | Create specialized agent |
| `/agents` | List all spawned agents |
| `/evolve [count]` | Create child generations |
| `/evolve-status` | Show evolution stats |
| `/review` | Review pending children |
| `/specialize <mission>` | Create NEXUS spinoff |

**Source**: `core/intelligence/evolution/`, `core/infrastructure/bootstrap/agent_loader.py`

"""

    def _generate_memory_zoom(self) -> str:
        return """## 9. ZOOM: Memory Systems

### Memory Architecture

```mermaid
graph TD
    subgraph ProjectMemory["Project Memory"]
        LEARN["#47;learn <path>"] --> INDEX[Index Files]
        INDEX --> STORE["NEXUS_ROOT/.nexus/project_knowledge.json"]
        INDEX --> BACKEND{{Backend Selection}}
        BACKEND --> AUTO[auto]
        BACKEND --> DENSE[dense -> lancedb/]
        BACKEND --> BM25[bm25]
        BACKEND --> TFIDF[tfidf]
        QUERY["#47;rag query <text>"] --> SEARCH[retrieve()]
        SEARCH --> CHUNKS[Top-K Chunks]
    end

    subgraph Success["SuccessMemoryV2"]
        TASK_DONE[Task Complete] --> RECORD[record_success]
        RECORD --> ENTRY[SuccessEntry<br/>mode, agents, duration]
        ENTRY --> VIRTUAL["success_memory://task_id chunks"]
        VIRTUAL --> STORE

        NEW_TASK[New Task] --> SIMILAR[search_similar]
        SIMILAR --> BOOST[Mode Boost<br/>0-30%]
    end

    subgraph Auto["Auto Memory"]
        SUCCESS[Success] --> AUTO_REC[record_success]
        FAILURE[Failure] --> AUTO_FAIL[record_failure]
        AUTO_REC --> JSONL[(workspace/memory/*.jsonl)]
        AUTO_FAIL --> JSONL

        SUGGEST[suggest_mode] --> JSONL
        SUGGEST --> BEST[Best Mode for Type]
    end

    subgraph Integration["Memory Integration"]
        BOOST --> SELECTOR[ModeSelector]
        BEST --> SELECTOR
        CHUNKS --> CONTEXT[Context Builder]
    end
```

### Memory Commands

| Command | Description |
|---------|-------------|
| `/learn [path]` | Index files into RAG |
| `/forget [path]` | Remove from RAG index |
| `/memory-status` | Show index statistics |
| `/rag <init|clear|query <text>>` | RAG maintenance and retrieval commands |

### Storage Paths

| Path | Purpose |
|------|---------|
| `NEXUS_ROOT/.nexus/project_knowledge.json` | ProjectMemory JSON index |
| `NEXUS_ROOT/.nexus/lancedb/` | Optional dense retrieval storage |
| `workspace/memory/` | AutoMemory and compatibility artifacts |

### RAG Backends

| Backend | Description | When Used |
|---------|-------------|-----------|
| **auto** | Select Dense, then BM25, then TF-IDF | Default selector |
| **dense** | Semantic search with MiniLM + LanceDB | Optional best-quality path |
| **bm25** | Sparse lexical retrieval | Fallback when dense is unavailable |
| **tfidf** | Built-in term-based retrieval | Lowest-dependency fallback |
| **hybrid** | Dense + BM25 implementation | Exists, but not selected by default today |

**Source**: `core/memory_pkg/memory/`

"""

    def _generate_security_zoom(self) -> str:
        return """## 10. ZOOM: Security & Governance

### Security Architecture

```mermaid
graph TD
    subgraph Policy["Runtime Policy"]
        INPUT[User Input] --> CHECK{{Execution<br/>Policy}}
        CHECK -->|PASS| PROCESS[Continue]
        CHECK -->|FAIL| REJECT[Reject + Log]
    end

    subgraph Sandbox["Sandbox Policy"]
        PROCESS --> SANDBOX[SandboxPolicy]
        SANDBOX --> ALLOW{{Allowed?}}
        ALLOW -->|Yes| TOOL[Tool Execution]
        ALLOW -->|No| BLOCK[Block + Alert]

        TOOL --> VALIDATE[Output Validation]
        VALIDATE --> SANITIZE[Sanitize Response]
    end

    subgraph Governance["Governance"]
        GOV_CHECK[Governance Rules] --> BUDGET{{Budget<br/>OK?}}
        BUDGET -->|No| THROTTLE[Throttle]
        BUDGET -->|Yes| CONTINUE[Continue]

        CONTINUE --> AUDIT[Audit Log]
    end
```

### Runtime Policy

The default distributed runtime is governed by execution policy, tool capability
checks, sandbox controls, and integrity monitoring.

Legacy KERNEL/INVARIANTS artifacts still exist for backward compatibility and
historical review, but they are **not** the default runtime authority on NX-CG.

### SandboxPolicy

| Policy | Description |
|--------|-------------|
| **File Access** | Restricted to workspace/ |
| **Network** | Controlled external access |
| **Execution** | Sandboxed command execution |
| **Budget** | Token/cost limits |

### Defense-in-Depth

| Layer | Protection |
|-------|------------|
| 1. Policy | Execution and capability validation |
| 2. Sandbox | Operation restrictions |
| 3. Governance | Budget/rate limits |
| 4. Audit | Full operation logging |

**Source**: `core/security_pkg/`, `core/execution_pkg/execution/`

"""

    def _generate_functional_inventory(self) -> str:
        commands = self.structures.get("commands", {})

        cmd_sections = []
        for category, cmd_list in commands.items():
            if cmd_list:
                cmd_sections.append(f"\n#### {category}\n")
                cmd_sections.append("| Command | Description |")
                cmd_sections.append("|---------|-------------|")
                for cmd in cmd_list:
                    desc = cmd.description or "-"
                    cmd_sections.append(f"| `/{cmd.name}` | {desc} |")

        total_cmds = sum(len(cmds) for cmds in commands.values())

        return f"""## 11. FUNCTIONAL INVENTORY

### Slash Commands ({total_cmds} total)

{"\n".join(cmd_sections)}

"""

    def _generate_key_dataclasses(self) -> str:
        dataclasses = self.structures.get("dataclasses", [])

        # Select key dataclasses
        key_names = [
            "TaskAnalysis",
            "ModeProposal",
            "AgentProfile",
            "InferenceConfig",
            "SuccessEntry",
            "HiveMindResult",
            "DebateResult",
            "ExecutionPlan",
            "FailureDiagnosis",
            "SwarmDelegationResult",
            "ToolResult",
        ]

        key_dc = [dc for dc in dataclasses if dc.name in key_names]

        dc_table = ""
        for dc in key_dc:
            fields_str = ", ".join(f[0] for f in dc.fields[:5])
            if len(dc.fields) > 5:
                fields_str += f" (+{len(dc.fields) - 5} more)"
            dc_table += f"| `{dc.name}` | {fields_str} | `{dc.file_path}` |\n"

        enums = self.structures.get("enums", [])
        enum_list = ", ".join(f"`{e[0]}`" for e in enums[:25])
        if len(enums) > 25:
            enum_list += f" (+{len(enums) - 25} more)"

        return f"""## 12. KEY DATACLASSES

### Core Dataclasses

| Dataclass | Key Fields | Source |
|-----------|------------|--------|
{dc_table}

### All Enums ({len(enums)} total)

{enum_list}

### All Dataclasses ({len(dataclasses)} total)

{", ".join(f"`{dc.name}`" for dc in dataclasses[:30])}{"..." if len(dataclasses) > 30 else ""}

"""

    def _generate_statistics(self) -> str:
        total_files = sum(len(c.modules) for c in self.components)
        total_loc = sum(c.total_loc for c in self.components)
        total_classes = sum(c.total_classes for c in self.components)
        total_functions = sum(c.total_functions for c in self.components)
        total_dataclasses = len(self.structures.get("dataclasses", []))
        total_enums = len(self.structures.get("enums", []))
        test_stats = self.structures.get("test_stats", {})

        # LOC chart
        loc_chart = []
        max_loc = max((c.total_loc for c in self.components), default=1)
        for comp in sorted(self.components, key=lambda c: -c.total_loc)[:15]:
            bar_len = int((comp.total_loc / max_loc) * 30)
            bar = "#" * bar_len
            loc_chart.append(f"{comp.name:<15} | {bar} {comp.total_loc:,}")

        return (
            f"""## 13. STATISTICS

### Codebase Metrics

| Metric | Value |
|--------|-------|
| **Total Components** | {len(self.components)} |
| **Total Python Files** | {total_files} |
| **Total Lines of Code** | {total_loc:,} |
| **Total Classes** | {total_classes} |
| **Total Functions** | {total_functions:,} |
| **Total Dataclasses** | {total_dataclasses} |
| **Total Enums** | {total_enums} |

### Test Coverage

| Metric | Value |
|--------|-------|
| **Test Functions** | {test_stats.get("total", "N/A")} |

### Lines of Code by Component

```
{chr(10).join(loc_chart)}
```

### Component Distribution

| Component | % of Codebase |
|-----------|---------------|
"""
            + "\n".join(
                f"| {comp.name} | {comp.total_loc / total_loc * 100:.1f}% |"
                for comp in sorted(self.components, key=lambda c: -c.total_loc)[:10]
            )
            + "\n"
        )

    def _generate_torture_protocol_zoom(self) -> str:
        """Generate Torture Protocol section."""
        torture = self.structures.get("torture_tests", {})
        total_tests = torture.get("total_tests", 0)
        categories = torture.get("categories", {})
        markers = torture.get("markers", [])

        if total_tests == 0:
            return """## 14. TORTURE PROTOCOL

> Torture Protocol tests not found. Run `pytest tests/torture_v8.py -m torture` to verify.

"""

        category_table = (
            "\n".join(f"| {cat} | {count} |" for cat, count in sorted(categories.items()))
            if categories
            else "| N/A | 0 |"
        )

        markers_list = ", ".join(f"`@pytest.mark.{m}`" for m in markers) if markers else "None"

        return f"""## 14. TORTURE PROTOCOL

### Overview

Torture Protocol V8 provides comprehensive stress testing for SagaManager + HiveMind integration.

```mermaid
graph TD
    subgraph TortureProtocol["Torture Protocol V8"]
        ENTRY[torture_v8.py] --> METRICS[MetricsCollector]
        ENTRY --> CHAOS[ChaosInjectors]

        subgraph Categories["5 Test Categories"]
            CR[Saga Crash<br/>15 tests]
            CC[Concurrency<br/>12 tests]
            CE[Context Edge<br/>10 tests]
            CF[Compensation<br/>8 tests]
            HM[HiveMind<br/>30 tests]
        end

        CHAOS --> CR
        CHAOS --> CC
        CHAOS --> CE
        CHAOS --> CF
        CHAOS --> HM

        METRICS --> REPORT[Report]
    end
```

### Test Categories ({total_tests} total)

| Category | Tests |
|----------|-------|
{category_table}

### Target Metrics

| Metric | Target |
|--------|--------|
| Success Rate | >95% |
| Recovery Rate | >90% |
| Panic Rate | <1% |
| Hot-Swap Effectiveness | >80% |

### Chaos Injectors

| Injector | Purpose |
|----------|---------|
| `CrashInjector` | Simulate crashes at checkpoints, persist, fsync |
| `RaceInjector` | Introduce race conditions via delays |
| `CorruptionInjector` | Corrupt saga files in various ways |
| `TimeoutInjector` | Inject timeouts into operations |

### pytest Markers

{markers_list}

### Execution

```bash
# Run all torture tests
pytest tests/torture_v8.py -m torture -v --tb=short

# Run by category
pytest tests/torture_v8.py -m torture_saga -v   # Saga tests
pytest tests/torture_v8.py -m torture_hive -v   # HiveMind tests
pytest tests/torture_v8.py -m torture_slow -v   # Slow tests
```

**Source**: `tests/torture_v8.py`, `tests/torture/`

"""

    def _generate_anti_hallucination(self) -> str:
        fsm_states = self.structures.get("fsm_states", [])
        hive_states = self.structures.get("hive_states", [])
        swarm_modes = self.structures.get("swarm_modes", [])

        return f"""## 15. ANTI-HALLUCINATION REFERENCE

### Verified Structures

This section provides **verified** structures for AI agents to reference, preventing hallucination.

#### OrchestratorState (VERIFIED)

```python
# core/fsm/states.py
class OrchestratorState(Enum):
{chr(10).join(f'    {s} = "{s}"' for s in fsm_states)}
```

#### HiveMindState (VERIFIED - {len(hive_states)} states)

```python
# core/intelligence/hive_mind/types.py - First 15 states
{chr(10).join(f"    {s}" for s in hive_states[:15])}
    # ... +{len(hive_states) - 15} more
```

#### CollaborationMode (VERIFIED)

```python
# core/intelligence/swarm/collaboration_modes.py
class CollaborationMode(Enum):
{chr(10).join(f'    {m} = "{m.lower()}"' for m in swarm_modes)}
```

### Common Hallucination Traps

| Wrong | Correct |
|-------|---------|
| `TaskAnalysis.reasoning` | Use `ModeProposal.reasoning` |
| `ModeProposal.recommended_mode` | Use `.mode` |
| `HiveMindState.HIVE_COMPLETE` | Use `HIVE_SUCCESS` |
| `invoke(task_type=)` | Use `invoke(session_uuid=)` |

### Reference Documents

| Document | Purpose |
|----------|---------|
| `docs/DATACLASS_FIELDS.md` | Exact field definitions |
| `docs/DRIVER_INTERNALS.md` | LLM driver implementation |
| `docs/ASYNC_MAP.md` | Async vs sync functions |

"""

    def _generate_footer(self) -> str:
        return f"""---

## Regeneration

To regenerate this document after code changes:

```bash
python scripts/doc_engine.py --gen-map --apply
```

Or run the full documentation sync:

```bash
python scripts/doc_engine.py --full --apply
```

---

*Generated by NEXUS Documentation Engine V2*
*Source: `scripts/doc_engine.py`*
*Version: {self.version} "{self.codename}"*
"""


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="NEXUS Documentation Engine V2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--check", action="store_true", help="Check documentation consistency (read-only)")
    parser.add_argument("--sync", action="store_true", help="Synchronize version patterns")
    parser.add_argument("--gen-map", action="store_true", help="Generate architecture map")
    parser.add_argument("--audit", action="store_true", help="Audit module READMEs")
    parser.add_argument("--full", action="store_true", help="Run all modes")
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default is dry-run)")
    parser.add_argument("--output", type=str, help="Output path for architecture map")

    args = parser.parse_args()

    if not any([args.check, args.sync, args.gen_map, args.audit, args.full]):
        args.check = True

    project_root = Path(__file__).parent.parent
    engine = DocEngine(project_root)

    exit_code = 0

    try:
        if args.full:
            success = engine.full(apply=args.apply)
            exit_code = 0 if success else 1
        else:
            if args.check:
                issues = engine.check()
                if any(i.severity == "ERROR" for i in issues):
                    exit_code = 1
            if args.sync:
                engine.sync(apply=args.apply)
            if args.gen_map:
                output = Path(args.output) if args.output else None
                engine.generate_map(output_path=output, apply=args.apply)
            if args.audit:
                engine.audit()

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
