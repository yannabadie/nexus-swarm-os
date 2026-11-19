"""
Tests for the JUnit parsing in scripts/generate_evidence_ledger.py.

The ledger is the project's CI evidence, so it has to report the real test counts for both shapes of JUnit file:
``<testsuite>`` as the root element, and ``<testsuites>`` wrapping one or more ``<testsuite>`` elements (what
current pytest writes). Reading the attributes of a ``<testsuites>`` root, which carries none, silently reported
"0 tests" for a run of thousands.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_evidence_ledger.py"

SUITE = '<testsuite name="pytest" errors="1" failures="2" skipped="3" tests="20" time="12.5"></testsuite>'
EXPECTED_SINGLE = {"tests": 20, "failures": 2, "errors": 1, "skipped": 3, "passed": 14, "duration_seconds": 12.5}


@pytest.fixture(scope="module")
def ledger():
    spec = importlib.util.spec_from_file_location("generate_evidence_ledger", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pytest-junit.xml"
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>{body}', encoding="utf-8")
    return path


def test_testsuite_root(ledger, tmp_path):
    assert ledger._parse_junit(_write(tmp_path, SUITE)) == EXPECTED_SINGLE


def test_testsuites_root_wrapping_one_suite(ledger, tmp_path):
    path = _write(tmp_path, f'<testsuites name="pytest tests">{SUITE}</testsuites>')
    assert ledger._parse_junit(path) == EXPECTED_SINGLE


def test_testsuites_root_with_several_suites_is_summed(ledger, tmp_path):
    first = '<testsuite name="a" errors="0" failures="1" skipped="2" tests="10" time="1.5"></testsuite>'
    second = '<testsuite name="b" errors="1" failures="0" skipped="2" tests="5" time="2.0"></testsuite>'
    result = ledger._parse_junit(_write(tmp_path, f"<testsuites>{first}{second}</testsuites>"))
    assert result == {"tests": 15, "failures": 1, "errors": 1, "skipped": 4, "passed": 9, "duration_seconds": 3.5}


def test_testsuites_root_carrying_its_own_totals_is_used_as_is(ledger, tmp_path):
    """Some producers aggregate on the root; counting its children as well would double the totals."""
    body = f'<testsuites tests="20" failures="2" errors="1" skipped="3" time="12.5">{SUITE}</testsuites>'
    assert ledger._parse_junit(_write(tmp_path, body)) == EXPECTED_SINGLE


def test_missing_file_reports_zero_tests(ledger, tmp_path):
    expected = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "passed": 0, "duration_seconds": None}
    assert ledger._parse_junit(None) == expected
    assert ledger._parse_junit(tmp_path / "does-not-exist.xml") == expected
