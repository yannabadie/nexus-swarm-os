"""
Comprehensive tests for core/security/integrity_monitor.py

Test coverage:
1. Constructor (5 tests)
2. compute_hash (10 tests)
3. compute_all_hashes (10 tests)
4. verify_integrity - No Baseline (5 tests)
5. verify_integrity - Files Match (10 tests)
6. verify_integrity - Modifications Detected (15 tests)
7. check_watched_files (10 tests)
8. save_baseline (10 tests)
9. load_baseline (10 tests)
10. get_status_report (10 tests)
11. Round-trip Tests (10 tests)
12. Edge Cases (5 tests)

Total: 100+ tests
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from core.security_pkg.security.integrity_monitor import IntegrityMonitor

# ============================================================================
# 1. Constructor Tests (~5 tests)
# ============================================================================


def test_constructor_stores_project_root_as_path(tmp_path):
    """Constructor stores project_root as Path object"""
    monitor = IntegrityMonitor(tmp_path)
    assert monitor.project_root == tmp_path
    assert isinstance(monitor.project_root, Path)


def test_constructor_accepts_string_path(tmp_path):
    """Constructor converts string path to Path object"""
    monitor = IntegrityMonitor(str(tmp_path))
    assert monitor.project_root == tmp_path
    assert isinstance(monitor.project_root, Path)


def test_constructor_initializes_empty_hashes(tmp_path):
    """Constructor initializes empty hashes dict"""
    monitor = IntegrityMonitor(tmp_path)
    assert monitor.hashes == {}
    assert isinstance(monitor.hashes, dict)


def test_constructor_initializes_empty_baseline(tmp_path):
    """Constructor initializes empty baseline dict"""
    monitor = IntegrityMonitor(tmp_path)
    assert monitor.baseline == {}
    assert isinstance(monitor.baseline, dict)


def test_constructor_baseline_loaded_defaults_false(tmp_path):
    """Constructor sets baseline_loaded to False"""
    monitor = IntegrityMonitor(tmp_path)
    assert monitor.baseline_loaded is False


# ============================================================================
# 2. compute_hash Tests (~10 tests)
# ============================================================================


def test_compute_hash_returns_sha256_for_existing_file(tmp_path):
    """compute_hash returns SHA-256 hex string for existing file"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    assert hash_value is not None
    assert isinstance(hash_value, str)
    assert len(hash_value) == 64  # SHA-256 hex length

    # Verify it's a valid hex string
    int(hash_value, 16)


def test_compute_hash_returns_none_for_nonexistent_file(tmp_path):
    """compute_hash returns None for non-existent file"""
    nonexistent = tmp_path / "nonexistent.txt"

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(nonexistent)

    assert hash_value is None


def test_compute_hash_same_file_same_hash(tmp_path):
    """Same file content produces same hash"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Test content", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash1 = monitor.compute_hash(test_file)
    hash2 = monitor.compute_hash(test_file)

    assert hash1 == hash2


def test_compute_hash_modified_file_different_hash(tmp_path):
    """Modified file produces different hash"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Original content", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash1 = monitor.compute_hash(test_file)

    test_file.write_text("Modified content", encoding="utf-8")
    hash2 = monitor.compute_hash(test_file)

    assert hash1 != hash2


def test_compute_hash_empty_file_consistent(tmp_path):
    """Empty file has consistent hash"""
    test_file = tmp_path / "empty.txt"
    test_file.write_text("", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    # SHA-256 of empty string
    expected = hashlib.sha256(b"").hexdigest()
    assert hash_value == expected


def test_compute_hash_binary_file(tmp_path):
    """compute_hash works with binary files"""
    test_file = tmp_path / "binary.dat"
    test_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    assert hash_value is not None
    assert len(hash_value) == 64


def test_compute_hash_large_file(tmp_path):
    """compute_hash handles large files with chunked reading"""
    test_file = tmp_path / "large.dat"
    # Create 1MB file
    large_content = b"X" * (1024 * 1024)
    test_file.write_bytes(large_content)

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    # Verify against direct hash
    expected = hashlib.sha256(large_content).hexdigest()
    assert hash_value == expected


def test_compute_hash_unicode_content(tmp_path):
    """compute_hash handles unicode content correctly"""
    test_file = tmp_path / "unicode.txt"
    test_file.write_text("Hello 世界 🌍", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    assert hash_value is not None
    assert len(hash_value) == 64


def test_compute_hash_different_content_different_hash(tmp_path):
    """Different content produces different hashes"""
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("Content A", encoding="utf-8")
    file2.write_text("Content B", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash1 = monitor.compute_hash(file1)
    hash2 = monitor.compute_hash(file2)

    assert hash1 != hash2


def test_compute_hash_multiline_file(tmp_path):
    """compute_hash handles multiline files correctly"""
    test_file = tmp_path / "multiline.txt"
    content = "Line 1\nLine 2\nLine 3\n"
    test_file.write_text(content, encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    # Read back what was actually written (handles platform line endings)
    actual_content = test_file.read_bytes()
    expected = hashlib.sha256(actual_content).hexdigest()
    assert hash_value == expected


# ============================================================================
# 3. compute_all_hashes Tests (~10 tests)
# ============================================================================


def test_compute_all_hashes_returns_dict(tmp_path):
    """compute_all_hashes returns dictionary"""
    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    assert isinstance(hashes, dict)


def test_compute_all_hashes_includes_protected_files(tmp_path):
    """compute_all_hashes hashes all existing protected files"""
    # Create some protected files
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    assert "KERNEL.py" in hashes
    assert "MISSION.md" in hashes


def test_compute_all_hashes_includes_watched_files(tmp_path):
    """compute_all_hashes includes watched files"""
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    assert "CLAUDE.md" in hashes


def test_compute_all_hashes_skips_nonexistent_files(tmp_path):
    """compute_all_hashes skips files that don't exist"""
    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    # Most files won't exist in empty tmp_path
    # Should not include keys for non-existent files
    for rel_path in IntegrityMonitor.PROTECTED_FILES:
        if rel_path not in hashes:
            # Verify the file doesn't exist
            assert not (tmp_path / rel_path).exists()


def test_compute_all_hashes_updates_self_hashes(tmp_path):
    """compute_all_hashes updates self.hashes"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    returned_hashes = monitor.compute_all_hashes()

    assert monitor.hashes == returned_hashes
    assert "KERNEL.py" in monitor.hashes


def test_compute_all_hashes_parent_directory_fallback(tmp_path):
    """compute_all_hashes checks parent directory if file not in project_root"""
    # Create KERNEL.py in parent directory
    (tmp_path.parent / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    # Should find KERNEL.py in parent
    assert "KERNEL.py" in hashes

    # Cleanup
    (tmp_path.parent / "KERNEL.py").unlink()


def test_compute_all_hashes_handles_nested_paths(tmp_path):
    """compute_all_hashes handles nested directory paths"""
    nested_dir = tmp_path / "core" / "governance" / "red_team"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "alignment_tests.py").write_text("# Tests", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    assert "core/governance/red_team/alignment_tests.py" in hashes


def test_compute_all_hashes_clears_previous_hashes(tmp_path):
    """compute_all_hashes clears previous hash data"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.hashes = {"old_file.txt": "old_hash"}

    hashes = monitor.compute_all_hashes()

    assert "old_file.txt" not in hashes
    assert "KERNEL.py" in hashes


def test_compute_all_hashes_handles_all_file_types(tmp_path):
    """compute_all_hashes handles both .py and .md files"""
    (tmp_path / "KERNEL.py").write_text("# Python", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Markdown", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    assert "KERNEL.py" in hashes
    assert "MISSION.md" in hashes
    assert hashes["KERNEL.py"] != hashes["MISSION.md"]


def test_compute_all_hashes_returns_relative_paths(tmp_path):
    """compute_all_hashes uses relative paths as keys"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hashes = monitor.compute_all_hashes()

    # Keys should be relative paths, not absolute
    for key in hashes:
        assert not Path(key).is_absolute()


# ============================================================================
# 4. verify_integrity - No Baseline Tests (~5 tests)
# ============================================================================


def test_verify_integrity_no_baseline_returns_true_empty_list(tmp_path):
    """verify_integrity returns (True, []) on first run with no baseline"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_no_baseline_sets_baseline_loaded(tmp_path):
    """verify_integrity sets baseline_loaded = True on first run"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    assert monitor.baseline_loaded is False

    monitor.verify_integrity()

    assert monitor.baseline_loaded is True


def test_verify_integrity_no_baseline_uses_current_as_baseline(tmp_path):
    """verify_integrity uses current hashes as baseline on first run"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()

    # Baseline should now contain current file hashes
    assert "KERNEL.py" in monitor.baseline
    assert len(monitor.baseline) > 0


def test_verify_integrity_loads_baseline_from_default_location(tmp_path):
    """verify_integrity loads baseline from default location if exists"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    # Create baseline file
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "INTEGRITY_BASELINE.json"
    monitor.save_baseline(baseline_path)

    # Create new monitor (no baseline loaded)
    monitor2 = IntegrityMonitor(tmp_path)
    assert monitor2.baseline_loaded is False

    # verify_integrity should auto-load baseline
    monitor2.verify_integrity()

    assert monitor2.baseline_loaded is True
    assert "KERNEL.py" in monitor2.baseline


def test_verify_integrity_no_baseline_empty_project(tmp_path):
    """verify_integrity handles empty project with no files"""
    monitor = IntegrityMonitor(tmp_path)
    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []
    assert monitor.baseline == {}


# ============================================================================
# 5. verify_integrity - Files Match Tests (~10 tests)
# ============================================================================


def test_verify_integrity_files_match_returns_true_empty_list(tmp_path):
    """verify_integrity returns (True, []) when all files match baseline"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_files_match_with_loaded_baseline(tmp_path):
    """verify_integrity works with explicitly loaded baseline"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)

    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_only_checks_protected_files(tmp_path):
    """verify_integrity only checks PROTECTED_FILES, not watched files"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Modify watched file (should not affect verify_integrity)
    (tmp_path / "CLAUDE.md").write_text("# Modified Claude", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    # Should still be valid because only protected files matter
    assert is_valid is True
    assert modified == []


def test_verify_integrity_multiple_protected_files_all_match(tmp_path):
    """verify_integrity handles multiple protected files all matching"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")
    (tmp_path / "INVARIANTS.md").write_text("# Invariants", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_files_match_after_baseline_reload(tmp_path):
    """verify_integrity works after saving and reloading baseline"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    # New monitor, load baseline
    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)

    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_ignores_new_files(tmp_path):
    """verify_integrity does not report new files added after baseline"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Add new protected file
    (tmp_path / "MISSION.md").write_text("# New Mission", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    # New files are OK (not modifications)
    assert is_valid is True
    assert modified == []


def test_verify_integrity_files_match_nested_paths(tmp_path):
    """verify_integrity handles nested protected files correctly"""
    nested_dir = tmp_path / "core" / "governance" / "red_team"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "alignment_tests.py").write_text("# Tests", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_baseline_persists_across_checks(tmp_path):
    """verify_integrity maintains baseline across multiple checks"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Multiple checks should all use same baseline
    is_valid1, _ = monitor.verify_integrity()
    is_valid2, _ = monitor.verify_integrity()
    is_valid3, _ = monitor.verify_integrity()

    assert is_valid1 is True
    assert is_valid2 is True
    assert is_valid3 is True


def test_verify_integrity_empty_baseline_empty_current(tmp_path):
    """verify_integrity handles case where no protected files exist"""
    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline (empty)

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_verify_integrity_files_match_after_compute_all_hashes(tmp_path):
    """verify_integrity works correctly after explicit compute_all_hashes call"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.compute_all_hashes()
    monitor.baseline = monitor.hashes.copy()
    monitor.baseline_loaded = True

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


# ============================================================================
# 6. verify_integrity - Modifications Detected Tests (~15 tests)
# ============================================================================


def test_verify_integrity_detects_modified_kernel(tmp_path):
    """verify_integrity detects modified KERNEL.py"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Modify KERNEL.py
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified


def test_verify_integrity_detects_modified_mission(tmp_path):
    """verify_integrity detects modified MISSION.md"""
    (tmp_path / "MISSION.md").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "MISSION.md").write_text("# Modified", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "MISSION.md" in modified


def test_verify_integrity_detects_multiple_modifications(tmp_path):
    """verify_integrity lists all modified protected files"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")
    (tmp_path / "INVARIANTS.md").write_text("# Invariants", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Modify all three
    (tmp_path / "KERNEL.py").write_text("# Modified Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Modified Mission", encoding="utf-8")
    (tmp_path / "INVARIANTS.md").write_text("# Modified Invariants", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert len(modified) == 3
    assert "KERNEL.py" in modified
    assert "MISSION.md" in modified
    assert "INVARIANTS.md" in modified


def test_verify_integrity_detects_deleted_file(tmp_path):
    """verify_integrity detects deleted protected file"""
    kernel_file = tmp_path / "KERNEL.py"
    kernel_file.write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Delete file
    kernel_file.unlink()

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py (DELETED)" in modified


def test_verify_integrity_deleted_file_format(tmp_path):
    """verify_integrity formats deleted files with (DELETED) suffix"""
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "MISSION.md").unlink()

    is_valid, modified = monitor.verify_integrity()

    assert "MISSION.md (DELETED)" in modified
    assert "MISSION.md" not in modified  # Should use (DELETED) format


def test_verify_integrity_does_not_report_new_files(tmp_path):
    """verify_integrity ignores new files (only cares about modifications)"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Add new file
    (tmp_path / "MISSION.md").write_text("# New", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    # Should be valid, new files are OK
    assert is_valid is True
    assert modified == []


def test_verify_integrity_watched_file_modified_still_valid(tmp_path):
    """verify_integrity ignores watched file modifications (use check_watched_files)"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Modify watched file
    (tmp_path / "CLAUDE.md").write_text("# Modified", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    # verify_integrity only checks protected files
    assert is_valid is True
    assert modified == []


def test_verify_integrity_minor_content_change_detected(tmp_path):
    """verify_integrity detects even minor content changes"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Add single character
    (tmp_path / "KERNEL.py").write_text("# Kernel ", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified


def test_verify_integrity_whitespace_change_detected(tmp_path):
    """verify_integrity detects whitespace-only changes"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Add newline
    (tmp_path / "KERNEL.py").write_text("# Kernel\n", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified


def test_verify_integrity_nested_file_modification(tmp_path):
    """verify_integrity detects modifications in nested protected files"""
    nested_dir = tmp_path / "core" / "governance" / "red_team"
    nested_dir.mkdir(parents=True, exist_ok=True)
    test_file = nested_dir / "alignment_tests.py"
    test_file.write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    test_file.write_text("# Modified", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "core/governance/red_team/alignment_tests.py" in modified


def test_verify_integrity_mixed_changes(tmp_path):
    """verify_integrity handles mixed scenario: some modified, some deleted, some new"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Modify one, delete one, add one
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")
    (tmp_path / "MISSION.md").unlink()
    (tmp_path / "INVARIANTS.md").write_text("# New", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified
    assert "MISSION.md (DELETED)" in modified
    assert "INVARIANTS.md" not in modified  # New files not reported


def test_verify_integrity_recomputes_hashes_each_time(tmp_path):
    """verify_integrity recomputes current hashes on each call"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # First check - no changes
    is_valid1, modified1 = monitor.verify_integrity()
    assert is_valid1 is True

    # Modify file
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    # Second check - should detect change
    is_valid2, modified2 = monitor.verify_integrity()
    assert is_valid2 is False
    assert "KERNEL.py" in modified2


def test_verify_integrity_encoding_changes_detected(tmp_path):
    """verify_integrity detects content changes regardless of encoding"""
    (tmp_path / "KERNEL.py").write_text("Hello", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Different content
    (tmp_path / "KERNEL.py").write_text("Goodbye", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified


def test_verify_integrity_binary_modification_detected(tmp_path):
    """verify_integrity detects binary file modifications"""
    # Note: KERNEL.py is a protected file, but we'll test the concept
    kernel_txt = tmp_path / "KERNEL_HASH.txt"
    kernel_txt.write_bytes(b"\x00\x01\x02")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    kernel_txt.write_bytes(b"\x00\x01\x03")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL_HASH.txt" in modified


def test_verify_integrity_partial_modification(tmp_path):
    """verify_integrity detects when some files modified but others unchanged"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Modify only KERNEL.py
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified
    assert "MISSION.md" not in modified


# ============================================================================
# 7. check_watched_files Tests (~10 tests)
# ============================================================================


def test_check_watched_files_returns_list(tmp_path):
    """check_watched_files returns a list"""
    monitor = IntegrityMonitor(tmp_path)
    result = monitor.check_watched_files()

    assert isinstance(result, list)


def test_check_watched_files_no_baseline_returns_empty(tmp_path):
    """check_watched_files returns empty list when no baseline loaded"""
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    result = monitor.check_watched_files()

    assert result == []


def test_check_watched_files_files_match_returns_empty(tmp_path):
    """check_watched_files returns empty when watched files unchanged"""
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    result = monitor.check_watched_files()

    assert result == []


def test_check_watched_files_detects_claude_md_modification(tmp_path):
    """check_watched_files detects CLAUDE.md modification"""
    (tmp_path / "CLAUDE.md").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "CLAUDE.md").write_text("# Modified", encoding="utf-8")

    result = monitor.check_watched_files()

    assert "CLAUDE.md" in result


def test_check_watched_files_detects_system_prompt_modification(tmp_path):
    """check_watched_files detects system prompt file modification"""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    prompt_file = prompts_dir / "system_gemini_v7.md"
    prompt_file.write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    prompt_file.write_text("# Modified", encoding="utf-8")

    result = monitor.check_watched_files()

    assert "prompts/system_gemini_v7.md" in result


def test_check_watched_files_multiple_modifications(tmp_path):
    """check_watched_files lists multiple modified watched files"""
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / "system_gemini_v7.md").write_text("# Gemini", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "CLAUDE.md").write_text("# Modified Claude", encoding="utf-8")
    (prompts_dir / "system_gemini_v7.md").write_text("# Modified Gemini", encoding="utf-8")

    result = monitor.check_watched_files()

    assert len(result) == 2
    assert "CLAUDE.md" in result
    assert "prompts/system_gemini_v7.md" in result


def test_check_watched_files_ignores_protected_files(tmp_path):
    """check_watched_files only checks watched files, not protected"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    result = monitor.check_watched_files()

    # KERNEL.py is protected, not watched
    assert "KERNEL.py" not in result


def test_check_watched_files_does_not_report_deleted(tmp_path):
    """check_watched_files does not report deleted watched files"""
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "CLAUDE.md").unlink()

    result = monitor.check_watched_files()

    # Only reports modifications, not deletions
    assert result == []


def test_check_watched_files_does_not_report_new(tmp_path):
    """check_watched_files does not report new watched files"""
    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline (empty)

    # Add watched file after baseline
    (tmp_path / "CLAUDE.md").write_text("# New", encoding="utf-8")

    result = monitor.check_watched_files()

    assert result == []


def test_check_watched_files_validator_py(tmp_path):
    """check_watched_files detects validator.py modification"""
    validator_dir = tmp_path / "core" / "governance" / "red_team"
    validator_dir.mkdir(parents=True, exist_ok=True)
    validator_file = validator_dir / "validator.py"
    validator_file.write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    validator_file.write_text("# Modified", encoding="utf-8")

    result = monitor.check_watched_files()

    assert "core/governance/red_team/validator.py" in result


# ============================================================================
# 8. save_baseline Tests (~10 tests)
# ============================================================================


def test_save_baseline_creates_json_file(tmp_path):
    """save_baseline creates JSON file at specified path"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    assert baseline_path.exists()


def test_save_baseline_includes_version(tmp_path):
    """save_baseline includes version field"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "version" in data
    assert data["version"] == "1.0"


def test_save_baseline_includes_created_at(tmp_path):
    """save_baseline includes created_at timestamp"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "created_at" in data
    # Should be valid ISO format
    datetime.fromisoformat(data["created_at"])


def test_save_baseline_includes_project_root(tmp_path):
    """save_baseline includes project_root path"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "project_root" in data
    assert data["project_root"] == str(tmp_path)


def test_save_baseline_includes_protected_files_list(tmp_path):
    """save_baseline includes protected_files list"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "protected_files" in data
    assert data["protected_files"] == IntegrityMonitor.PROTECTED_FILES


def test_save_baseline_includes_watched_files_list(tmp_path):
    """save_baseline includes watched_files list"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "watched_files" in data
    assert data["watched_files"] == IntegrityMonitor.WATCHED_FILES


def test_save_baseline_includes_all_hashes(tmp_path):
    """save_baseline includes hashes dict"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "hashes" in data
    assert "KERNEL.py" in data["hashes"]
    assert "MISSION.md" in data["hashes"]


def test_save_baseline_computes_fresh_hashes(tmp_path):
    """save_baseline computes fresh hashes before saving"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.hashes = {}  # Empty

    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    # Should have computed hashes
    assert len(monitor.hashes) > 0
    assert "KERNEL.py" in monitor.hashes


def test_save_baseline_json_formatting(tmp_path):
    """save_baseline creates properly formatted JSON with indentation"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    content = baseline_path.read_text(encoding="utf-8")

    # Should be indented (not minified)
    assert "  " in content
    # Should be valid JSON
    json.loads(content)


def test_save_baseline_overwrites_existing(tmp_path):
    """save_baseline overwrites existing baseline file"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"

    monitor.save_baseline(baseline_path)

    # Modify file and save again
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")
    monitor.save_baseline(baseline_path)

    # Load and verify updated hash
    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)

    new_hash = monitor.compute_hash(tmp_path / "KERNEL.py")
    assert data["hashes"]["KERNEL.py"] == new_hash


# ============================================================================
# 9. load_baseline Tests (~10 tests)
# ============================================================================


def test_load_baseline_loads_hashes_from_json(tmp_path):
    """load_baseline loads hashes from JSON file"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    loaded_hashes = monitor2.load_baseline(baseline_path)

    assert "KERNEL.py" in loaded_hashes
    assert loaded_hashes == monitor.hashes


def test_load_baseline_sets_baseline_loaded_true(tmp_path):
    """load_baseline sets baseline_loaded = True"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    assert monitor2.baseline_loaded is False

    monitor2.load_baseline(baseline_path)

    assert monitor2.baseline_loaded is True


def test_load_baseline_returns_loaded_hashes(tmp_path):
    """load_baseline returns the loaded hashes dict"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    result = monitor2.load_baseline(baseline_path)

    assert isinstance(result, dict)
    assert "KERNEL.py" in result


def test_load_baseline_handles_corrupt_json_gracefully(tmp_path):
    """load_baseline handles corrupt JSON without crashing"""
    baseline_path = tmp_path / "corrupt.json"
    baseline_path.write_text("{ invalid json", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    result = monitor.load_baseline(baseline_path)

    assert result == {}
    assert monitor.baseline_loaded is False


def test_load_baseline_handles_missing_file_gracefully(tmp_path):
    """load_baseline handles missing file without crashing"""
    baseline_path = tmp_path / "nonexistent.json"

    monitor = IntegrityMonitor(tmp_path)
    result = monitor.load_baseline(baseline_path)

    assert result == {}
    assert monitor.baseline_loaded is False


def test_load_baseline_handles_empty_hashes(tmp_path):
    """load_baseline handles baseline with empty hashes"""
    baseline_data = {"version": "1.0", "created_at": datetime.now().isoformat(), "hashes": {}}
    baseline_path = tmp_path / "baseline.json"
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f)

    monitor = IntegrityMonitor(tmp_path)
    result = monitor.load_baseline(baseline_path)

    assert result == {}
    assert monitor.baseline_loaded is True


def test_load_baseline_handles_missing_hashes_key(tmp_path):
    """load_baseline handles baseline without 'hashes' key"""
    baseline_data = {"version": "1.0", "created_at": datetime.now().isoformat()}
    baseline_path = tmp_path / "baseline.json"
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f)

    monitor = IntegrityMonitor(tmp_path)
    result = monitor.load_baseline(baseline_path)

    assert result == {}
    assert monitor.baseline_loaded is True


def test_load_baseline_sets_self_baseline(tmp_path):
    """load_baseline updates self.baseline"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)

    assert "KERNEL.py" in monitor2.baseline


def test_load_baseline_preserves_hash_values(tmp_path):
    """load_baseline preserves exact hash values"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    original_hash = monitor.hashes["KERNEL.py"]

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)

    assert monitor2.baseline["KERNEL.py"] == original_hash


def test_load_baseline_works_with_pathlib_path(tmp_path):
    """load_baseline accepts pathlib.Path object"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    result = monitor2.load_baseline(baseline_path)  # Path object

    assert result == monitor.hashes


# ============================================================================
# 10. get_status_report Tests (~10 tests)
# ============================================================================


def test_get_status_report_returns_dict(tmp_path):
    """get_status_report returns a dictionary"""
    monitor = IntegrityMonitor(tmp_path)
    report = monitor.get_status_report()

    assert isinstance(report, dict)


def test_get_status_report_status_ok_when_all_clear(tmp_path):
    """get_status_report status is OK when all files valid"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    report = monitor.get_status_report()

    assert report["status"] == "OK"


def test_get_status_report_status_warning_when_watched_modified(tmp_path):
    """get_status_report status is WARNING when watched files modified"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "CLAUDE.md").write_text("# Modified", encoding="utf-8")

    report = monitor.get_status_report()

    assert report["status"] == "WARNING"


def test_get_status_report_status_critical_when_protected_modified(tmp_path):
    """get_status_report status is CRITICAL when protected files modified"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    report = monitor.get_status_report()

    assert report["status"] == "CRITICAL"


def test_get_status_report_contains_all_expected_fields(tmp_path):
    """get_status_report contains all required fields"""
    monitor = IntegrityMonitor(tmp_path)
    report = monitor.get_status_report()

    expected_fields = [
        "status",
        "timestamp",
        "project_root",
        "integrity_valid",
        "modified_protected",
        "modified_watched",
        "total_protected",
        "total_watched",
        "baseline_loaded",
        "recommendation",
    ]

    for field in expected_fields:
        assert field in report


def test_get_status_report_includes_timestamp(tmp_path):
    """get_status_report includes valid ISO timestamp"""
    monitor = IntegrityMonitor(tmp_path)
    report = monitor.get_status_report()

    # Should be valid ISO format
    datetime.fromisoformat(report["timestamp"])


def test_get_status_report_integrity_valid_field(tmp_path):
    """get_status_report integrity_valid matches verify_integrity result"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    report = monitor.get_status_report()
    assert report["integrity_valid"] is True

    # Modify file
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    report = monitor.get_status_report()
    assert report["integrity_valid"] is False


def test_get_status_report_modified_lists(tmp_path):
    """get_status_report includes modified_protected and modified_watched lists"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Modified", encoding="utf-8")

    report = monitor.get_status_report()

    assert "KERNEL.py" in report["modified_protected"]
    assert "CLAUDE.md" in report["modified_watched"]


def test_get_status_report_recommendation_matches_status(tmp_path):
    """get_status_report recommendation matches status"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # OK status
    report = monitor.get_status_report()
    assert "All clear" in report["recommendation"]

    # CRITICAL status
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")
    report = monitor.get_status_report()
    assert "CRITICAL" in report["recommendation"]


def test_get_status_report_totals(tmp_path):
    """get_status_report includes total_protected and total_watched counts"""
    monitor = IntegrityMonitor(tmp_path)
    report = monitor.get_status_report()

    assert report["total_protected"] == len(IntegrityMonitor.PROTECTED_FILES)
    assert report["total_watched"] == len(IntegrityMonitor.WATCHED_FILES)


# ============================================================================
# 11. Round-trip Tests (~10 tests)
# ============================================================================


def test_roundtrip_save_modify_verify(tmp_path):
    """Round-trip: save baseline -> modify file -> verify detects change"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py" in modified


def test_roundtrip_save_load_verify_matches(tmp_path):
    """Round-trip: save baseline -> load baseline -> verify matches"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_roundtrip_full_workflow(tmp_path):
    """Full workflow: create files -> save -> modify -> verify -> report"""
    # Create files
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    # Save baseline
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    # Modify both
    (tmp_path / "KERNEL.py").write_text("# Modified Kernel", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Modified Claude", encoding="utf-8")

    # Load and verify
    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)

    # Get report
    report = monitor2.get_status_report()

    assert report["status"] == "CRITICAL"  # Protected file modified
    assert "KERNEL.py" in report["modified_protected"]
    assert "CLAUDE.md" in report["modified_watched"]


def test_roundtrip_multiple_saves(tmp_path):
    """Round-trip: multiple save/load cycles"""
    (tmp_path / "KERNEL.py").write_text("# Version 1", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    # Modify and save again
    (tmp_path / "KERNEL.py").write_text("# Version 2", encoding="utf-8")
    monitor.save_baseline(baseline_path)

    # Verify against updated baseline
    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is True


def test_roundtrip_deleted_file_detected(tmp_path):
    """Round-trip: save -> delete file -> verify detects deletion"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    (tmp_path / "KERNEL.py").unlink()

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is False
    assert "KERNEL.py (DELETED)" in modified


def test_roundtrip_new_file_not_flagged(tmp_path):
    """Round-trip: save -> add new file -> verify ignores new file"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    (tmp_path / "MISSION.md").write_text("# New", encoding="utf-8")

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is True


def test_roundtrip_watched_files_separate_from_protected(tmp_path):
    """Round-trip: watched files don't affect verify_integrity"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    # Modify only watched file
    (tmp_path / "CLAUDE.md").write_text("# Modified", encoding="utf-8")

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    # Should still be valid (watched files don't fail verification)
    assert is_valid is True

    # But check_watched_files should detect it
    watched_modified = monitor2.check_watched_files()
    assert "CLAUDE.md" in watched_modified


def test_roundtrip_baseline_persistence(tmp_path):
    """Round-trip: baseline persists across program restarts"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")

    # Session 1: Create baseline
    monitor1 = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor1.save_baseline(baseline_path)
    hash1 = monitor1.hashes["KERNEL.py"]

    # Session 2: Load baseline (simulated restart)
    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    hash2 = monitor2.baseline["KERNEL.py"]

    assert hash1 == hash2


def test_roundtrip_status_report_integration(tmp_path):
    """Round-trip: status report correctly reflects all changes"""
    (tmp_path / "KERNEL.py").write_text("# Kernel", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    # Modify protected and watched
    (tmp_path / "KERNEL.py").write_text("# Modified", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Modified", encoding="utf-8")

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    report = monitor2.get_status_report()

    assert report["status"] == "CRITICAL"
    assert len(report["modified_protected"]) == 1
    assert len(report["modified_watched"]) == 1


def test_roundtrip_empty_project(tmp_path):
    """Round-trip: works with empty project (no files)"""
    monitor = IntegrityMonitor(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    monitor.save_baseline(baseline_path)

    monitor2 = IntegrityMonitor(tmp_path)
    monitor2.load_baseline(baseline_path)
    is_valid, modified = monitor2.verify_integrity()

    assert is_valid is True
    assert modified == []


# ============================================================================
# 12. Edge Cases (~5 tests)
# ============================================================================


def test_edge_case_project_root_doesnt_exist():
    """Edge case: project root doesn't exist (doesn't crash)"""
    nonexistent_root = Path("/tmp/nonexistent_nexus_project_xyz")

    monitor = IntegrityMonitor(nonexistent_root)
    hashes = monitor.compute_all_hashes()

    # Should return empty dict, not crash
    assert hashes == {}


def test_edge_case_all_files_missing(tmp_path):
    """Edge case: all protected/watched files missing"""
    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline (empty)

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True
    assert modified == []


def test_edge_case_special_characters_in_content(tmp_path):
    """Edge case: files with special characters in content"""
    special_content = "# Kernel\n\x00\x01\x02\xff\xfe\n🚀\n"
    (tmp_path / "KERNEL.py").write_bytes(special_content.encode("utf-8", errors="replace"))

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    is_valid, modified = monitor.verify_integrity()

    assert is_valid is True


def test_edge_case_very_long_file_path(tmp_path):
    """Edge case: very long nested file path"""
    # Create deeply nested structure; cap at 5 levels to stay within
    # Windows MAX_PATH (260 chars) even when tmp_path uses long usernames.
    deep_path = tmp_path
    for i in range(5):
        deep_path = deep_path / f"level{i}"
    deep_path.mkdir(parents=True, exist_ok=True)

    test_file = deep_path / "test.txt"
    test_file.write_text("# Test", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    hash_value = monitor.compute_hash(test_file)

    assert hash_value is not None


def test_edge_case_concurrent_modification(tmp_path):
    """Edge case: file modified between compute_all_hashes calls"""
    (tmp_path / "KERNEL.py").write_text("# Original", encoding="utf-8")

    monitor = IntegrityMonitor(tmp_path)
    monitor.verify_integrity()  # Set baseline

    # Simulate rapid modification
    (tmp_path / "KERNEL.py").write_text("# Modified 1", encoding="utf-8")
    hashes1 = monitor.compute_all_hashes()

    (tmp_path / "KERNEL.py").write_text("# Modified 2", encoding="utf-8")
    hashes2 = monitor.compute_all_hashes()

    assert hashes1["KERNEL.py"] != hashes2["KERNEL.py"]


# ============================================================================
# Summary
# ============================================================================

"""
Test Summary:
1. Constructor: 5 tests
2. compute_hash: 10 tests
3. compute_all_hashes: 10 tests
4. verify_integrity - No Baseline: 5 tests
5. verify_integrity - Files Match: 10 tests
6. verify_integrity - Modifications Detected: 15 tests
7. check_watched_files: 10 tests
8. save_baseline: 10 tests
9. load_baseline: 10 tests
10. get_status_report: 10 tests
11. Round-trip Tests: 10 tests
12. Edge Cases: 5 tests

Total: 100 tests
"""
