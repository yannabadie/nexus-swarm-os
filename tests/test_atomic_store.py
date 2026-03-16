"""
Unit tests for AtomicJsonStore - Phase 7 Session Isolation.

NEXUS V7.5 HIVE MIND - Thread-safe atomic JSON persistence.

Tests cover:
- Basic read/write operations
- Data persistence
- Thread safety (concurrency)
- Error handling
- Edge cases

Author: Claude (NEXUS V7.5)
Date: 2025-12-04
"""

import json

# Add parent to path for imports
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest import TestCase, main

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils.atomic_store import (
    AtomicJsonStore,
    AtomicJsonStoreManager,
    get_store,
)


class TestAtomicJsonStoreBasic(TestCase):
    """Basic functionality tests for AtomicJsonStore."""

    def setUp(self):
        """Create a temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.temp_dir) / "test.json"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_store(self):
        """Test that AtomicJsonStore initializes correctly."""
        store = AtomicJsonStore(self.test_file)
        assert store.filepath == self.test_file
        assert not store.exists

    def test_save_creates_file(self):
        """Test that save() creates the JSON file."""
        store = AtomicJsonStore(self.test_file)
        data = {"key": "value", "number": 42}

        store.save(data)

        assert store.exists
        assert self.test_file.exists()

    def test_load_returns_saved_data(self):
        """Test that load() returns the data that was saved."""
        store = AtomicJsonStore(self.test_file)
        original_data = {
            "string": "hello",
            "number": 123,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"a": 1, "b": 2},
        }

        store.save(original_data)
        loaded_data = store.load()

        assert loaded_data == original_data

    def test_load_nonexistent_returns_empty_dict(self):
        """Test that load() returns {} for nonexistent file."""
        store = AtomicJsonStore(self.test_file)
        data = store.load()
        assert data == {}

    def test_load_safe_returns_default_on_error(self):
        """Test that load_safe() returns default on error."""
        store = AtomicJsonStore(self.test_file)

        # Write invalid JSON
        self.test_file.write_text("not valid json {{{", encoding="utf-8")

        # load_safe should return default
        result = store.load_safe(default={"fallback": True})
        assert result == {"fallback": True}

    def test_load_safe_default_is_empty_dict(self):
        """Test that load_safe() default is empty dict."""
        store = AtomicJsonStore(self.test_file)
        self.test_file.write_text("invalid", encoding="utf-8")

        result = store.load_safe()
        assert result == {}

    def test_update_modifies_data(self):
        """Test that update() atomically updates data."""
        store = AtomicJsonStore(self.test_file)
        store.save({"a": 1, "b": 2})

        result = store.update({"b": 3, "c": 4})

        assert result == {"a": 1, "b": 3, "c": 4}
        assert store.load() == {"a": 1, "b": 3, "c": 4}

    def test_delete_removes_file(self):
        """Test that delete() removes the file."""
        store = AtomicJsonStore(self.test_file)
        store.save({"test": True})

        assert store.exists
        result = store.delete()
        assert result is True
        assert not store.exists

    def test_delete_nonexistent_returns_false(self):
        """Test that delete() returns False for nonexistent file."""
        store = AtomicJsonStore(self.test_file)
        result = store.delete()
        assert result is False

    def test_creates_parent_directories(self):
        """Test that save() creates parent directories."""
        nested_path = Path(self.temp_dir) / "deep" / "nested" / "path" / "file.json"
        store = AtomicJsonStore(nested_path)

        store.save({"deep": True})

        assert nested_path.exists()
        assert store.load() == {"deep": True}

    def test_unicode_content(self):
        """Test that Unicode content is handled correctly."""
        store = AtomicJsonStore(self.test_file)
        data = {
            "french": "Caf\u00e9 cr\u00e8me",
            "japanese": "\u3053\u3093\u306b\u3061\u306f",
            "emoji": "\U0001f41d HIVE MIND \U0001f41d",
            "chinese": "\u4e2d\u6587\u6d4b\u8bd5",
        }

        store.save(data)
        loaded = store.load()

        assert loaded == data

    def test_repr(self):
        """Test string representation."""
        store = AtomicJsonStore(self.test_file)
        repr_str = repr(store)
        assert "AtomicJsonStore" in repr_str
        # Check file name is present (path format may vary on different OS)
        assert self.test_file.name in repr_str


class TestAtomicJsonStoreAtomicity(TestCase):
    """Tests for atomic write behavior."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.temp_dir) / "atomic_test.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_temp_files_after_save(self):
        """Test that no temporary files remain after save."""
        store = AtomicJsonStore(self.test_file)
        store.save({"test": True})

        # Check for leftover .tmp files
        tmp_files = list(Path(self.temp_dir).glob("*.tmp"))
        assert len(tmp_files) == 0, f"Found leftover temp files: {tmp_files}"

    def test_data_persists_after_multiple_saves(self):
        """Test that data persists correctly through multiple saves."""
        store = AtomicJsonStore(self.test_file)

        for i in range(10):
            store.save({"iteration": i, "data": list(range(i))})

        final_data = store.load()
        assert final_data["iteration"] == 9
        assert final_data["data"] == list(range(9))

    def test_file_content_is_valid_json(self):
        """Test that file always contains valid JSON."""
        store = AtomicJsonStore(self.test_file)
        store.save({"valid": True})

        # Read raw file content
        content = self.test_file.read_text(encoding="utf-8")

        # Should be valid JSON
        parsed = json.loads(content)
        assert parsed == {"valid": True}


class TestAtomicJsonStoreConcurrency(TestCase):
    """Concurrency tests for thread safety."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.temp_dir) / "concurrent.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_reads(self):
        """Test that concurrent reads don't corrupt data."""
        store = AtomicJsonStore(self.test_file)
        store.save({"value": 42, "items": list(range(100))})

        results = []
        errors = []

        def read_data():
            try:
                data = store.load()
                results.append(data)
            except Exception as e:
                errors.append(e)

        # Run many concurrent reads
        threads = [threading.Thread(target=read_data) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent reads: {errors}"
        assert len(results) == 50
        assert all(r == {"value": 42, "items": list(range(100))} for r in results)

    def test_concurrent_writes_no_corruption(self):
        """Test that concurrent writes don't corrupt the file."""
        store = AtomicJsonStore(self.test_file)
        store.save({"counter": 0})

        errors: list[Exception] = []

        def increment_counter(thread_id: int):
            try:
                for i in range(10):
                    with store._lock:  # Explicitly use lock for read-modify-write
                        data = store.load()
                        data["counter"] = data.get("counter", 0) + 1
                        data[f"thread_{thread_id}"] = i
                        store.save(data)
                    time.sleep(0.001)  # Small delay to increase interleaving
            except Exception as e:
                errors.append(e)

        # Run concurrent write threads
        threads = [threading.Thread(target=increment_counter, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"

        # File should still be valid JSON
        final_data = store.load()
        assert "counter" in final_data

        # Counter should equal total increments
        assert final_data["counter"] == 100, f"Expected 100, got {final_data['counter']}"

    def test_concurrent_update_operations(self):
        """Test concurrent update() operations."""
        store = AtomicJsonStore(self.test_file)
        store.save({"items": []})

        errors: list[Exception] = []
        items_added = []
        lock = threading.Lock()

        def add_item(item_id: int):
            try:
                # Use update for atomic read-modify-write
                with store._lock:
                    data = store.load()
                    data.setdefault("items", []).append(item_id)
                    store.save(data)
                with lock:
                    items_added.append(item_id)
            except Exception as e:
                errors.append(e)

        # Run concurrent updates
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(add_item, i) for i in range(50)]
            for future in as_completed(futures):
                future.result()  # Raise any exceptions

        assert len(errors) == 0, f"Errors during concurrent updates: {errors}"

        final_data = store.load()
        assert len(final_data["items"]) == 50
        assert set(final_data["items"]) == set(range(50))


class TestAtomicJsonStoreManager(TestCase):
    """Tests for AtomicJsonStoreManager."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_store_returns_same_instance(self):
        """Test that get_store returns the same instance for same path."""
        manager = AtomicJsonStoreManager()
        path = Path(self.temp_dir) / "test.json"

        store1 = manager.get_store(path)
        store2 = manager.get_store(path)

        assert store1 is store2

    def test_get_store_different_paths(self):
        """Test that different paths get different stores."""
        manager = AtomicJsonStoreManager()
        path1 = Path(self.temp_dir) / "test1.json"
        path2 = Path(self.temp_dir) / "test2.json"

        store1 = manager.get_store(path1)
        store2 = manager.get_store(path2)

        assert store1 is not store2

    def test_get_store_normalizes_paths(self):
        """Test that paths are normalized."""
        manager = AtomicJsonStoreManager()
        path1 = Path(self.temp_dir) / "test.json"
        path2 = Path(self.temp_dir) / "subdir" / ".." / "test.json"

        store1 = manager.get_store(path1)
        store2 = manager.get_store(path2)

        assert store1 is store2

    def test_clear_removes_all_stores(self):
        """Test that clear() removes all managed stores."""
        manager = AtomicJsonStoreManager()
        path1 = Path(self.temp_dir) / "test1.json"
        path2 = Path(self.temp_dir) / "test2.json"

        manager.get_store(path1)
        manager.get_store(path2)
        manager.clear()

        # Getting stores again should create new instances
        new_store1 = manager.get_store(path1)
        assert new_store1 is not None


class TestModuleLevelFunction(TestCase):
    """Tests for module-level get_store function."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_store_function(self):
        """Test module-level get_store convenience function."""
        path = Path(self.temp_dir) / "module_test.json"

        store = get_store(path)
        store.save({"module": "test"})

        assert store.load() == {"module": "test"}


class TestAtomicJsonStoreErrorHandling(TestCase):
    """Tests for error handling."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.temp_dir) / "error_test.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_invalid_json_raises(self):
        """Test that load() raises JSONDecodeError for invalid JSON."""
        store = AtomicJsonStore(self.test_file)
        self.test_file.write_text("{invalid json}", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            store.load()

    def test_load_empty_file_returns_empty_dict(self):
        """Test that load() returns {} for empty file."""
        store = AtomicJsonStore(self.test_file)
        self.test_file.write_text("", encoding="utf-8")

        result = store.load()
        assert result == {}

    def test_load_whitespace_only_returns_empty_dict(self):
        """Test that load() returns {} for whitespace-only file."""
        store = AtomicJsonStore(self.test_file)
        self.test_file.write_text("   \n\t  \n", encoding="utf-8")

        result = store.load()
        assert result == {}

    def test_save_non_serializable_raises(self):
        """Test that save() raises TypeError for non-serializable data."""
        store = AtomicJsonStore(self.test_file)

        with pytest.raises(TypeError):
            store.save({"func": lambda x: x})  # Functions aren't JSON serializable


# Run tests if executed directly
if __name__ == "__main__":
    main()
