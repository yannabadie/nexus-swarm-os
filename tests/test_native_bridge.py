"""
Tests for core.native bridge (Rust/Python fallback).

These tests run against whichever backend is active.
They validate correctness of RRF scoring, SHA-256 hashing,
and batch TF-IDF scoring.
"""

from core.native import batch_tfidf_score, compute_rrf, get_backend_info, sha256_hex, verify_kernel_hash


class TestBackendInfo:
    """Verify the native bridge loads correctly."""

    def test_backend_info_has_fields(self):
        info = get_backend_info()
        assert "backend" in info
        assert "rust_available" in info
        assert info["backend"] in ("python", "rust")


class TestComputeRRF:
    """Test Reciprocal Rank Fusion scoring."""

    def test_basic_rrf(self):
        """Two lists with overlapping chunks."""
        dense = ["a", "b", "c"]
        sparse = ["b", "d", "a"]

        results = compute_rrf(dense, sparse, k=60, dense_weight=0.6, sparse_weight=0.4)

        # Should return list of (chunk_id, score) tuples
        assert isinstance(results, list)
        assert len(results) == 4  # a, b, c, d

        # Results should be sorted by score descending
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

        # 'b' should be highest (appears in both lists)
        assert results[0][0] == "b"

    def test_rrf_single_list(self):
        """Only one list has results."""
        results = compute_rrf(["x", "y"], [], k=60)
        assert len(results) == 2
        assert results[0][0] == "x"

    def test_rrf_empty_lists(self):
        """Both lists empty."""
        results = compute_rrf([], [])
        assert results == []

    def test_rrf_weights(self):
        """Different weights should affect scores."""
        # Dense-heavy weights
        r1 = compute_rrf(["a"], ["b"], dense_weight=0.9, sparse_weight=0.1)
        # Sparse-heavy weights
        r2 = compute_rrf(["a"], ["b"], dense_weight=0.1, sparse_weight=0.9)

        # In r1, 'a' (dense) should score higher than 'b' (sparse)
        r1_dict = dict(r1)
        assert r1_dict["a"] > r1_dict["b"]

        # In r2, 'b' (sparse) should score higher than 'a' (dense)
        r2_dict = dict(r2)
        assert r2_dict["b"] > r2_dict["a"]

    def test_rrf_k_parameter(self):
        """Higher k should produce more equal scores."""
        r_low_k = compute_rrf(["a", "b"], ["a", "b"], k=1)
        r_high_k = compute_rrf(["a", "b"], ["a", "b"], k=1000)

        # With high k, rank differences matter less
        low_k_scores = [s for _, s in r_low_k]
        high_k_scores = [s for _, s in r_high_k]

        low_k_diff = low_k_scores[0] - low_k_scores[1]
        high_k_diff = high_k_scores[0] - high_k_scores[1]

        assert high_k_diff < low_k_diff  # High k = more equal


class TestSHA256:
    """Test SHA-256 hashing."""

    def test_known_hash(self):
        """Test against known SHA-256 value."""
        result = sha256_hex(b"hello")
        assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_empty_input(self):
        result = sha256_hex(b"")
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_deterministic(self):
        """Same input always produces same hash."""
        h1 = sha256_hex(b"test content")
        h2 = sha256_hex(b"test content")
        assert h1 == h2


class TestVerifyKernelHash:
    """Test KERNEL integrity verification."""

    def test_matching_hash(self):
        content = b"KERNEL content"
        expected = sha256_hex(content)
        assert verify_kernel_hash(content, expected) is True

    def test_mismatching_hash(self):
        content = b"KERNEL content"
        assert verify_kernel_hash(content, "0" * 64) is False

    def test_modified_content(self):
        original = b"original"
        modified = b"modified"
        expected = sha256_hex(original)
        assert verify_kernel_hash(modified, expected) is False


class TestBatchTfidfScore:
    """Test batch TF-IDF scoring."""

    def test_basic_scoring(self):
        query = ["python", "class"]
        chunks = [
            ["python", "function", "class"],  # matches both
            ["javascript", "module"],  # no match
            ["python", "import"],  # partial match
        ]
        idf = {"python": 1.5, "class": 2.0, "function": 1.0, "javascript": 1.2, "module": 0.8, "import": 1.1}

        scores = batch_tfidf_score(query, chunks, idf)

        assert len(scores) == 3
        assert scores[0] > scores[2] > scores[1]  # best match > partial > no match
        assert scores[1] == 0.0  # no terms in common

    def test_empty_query(self):
        scores = batch_tfidf_score([], [["a", "b"]], {"a": 1.0})
        assert scores == [0.0]

    def test_empty_chunks(self):
        scores = batch_tfidf_score(["a"], [], {"a": 1.0})
        assert scores == []

    def test_missing_idf(self):
        """Terms not in IDF dict should get weight 0."""
        scores = batch_tfidf_score(
            ["unknown_term"],
            [["unknown_term"]],
            {},  # empty IDF
        )
        assert scores == [0.0]
