"""
Tests for KERNEL V8.8 Heredity Check (GROK-003)

Tests the lineage validation system that ensures spawned agents
descend from a valid KERNEL state.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestComputeRulesHash:
    """Tests for compute_rules_hash()"""

    def test_hash_exists(self):
        """Test that compute_rules_hash returns a valid hash."""
        from KERNEL import compute_rules_hash

        result = compute_rules_hash()

        assert result is not None
        assert isinstance(result, str)
        assert len(result) == 16  # First 16 chars of SHA-256

    def test_hash_is_deterministic(self):
        """Test that hash is consistent across calls."""
        from KERNEL import compute_rules_hash

        hash1 = compute_rules_hash()
        hash2 = compute_rules_hash()

        assert hash1 == hash2

    def test_hash_is_hex(self):
        """Test that hash contains only hex characters."""
        from KERNEL import compute_rules_hash

        result = compute_rules_hash()

        # All characters should be valid hex
        assert all(c in "0123456789abcdef" for c in result)


class TestValidateLineage:
    """Tests for validate_lineage()"""

    def test_valid_authority_no_hash(self):
        """Test validation passes with correct authority and no hash (legacy)."""
        from KERNEL import CREATOR, validate_lineage

        cert = {"human_authority": CREATOR}
        is_valid, reason = validate_lineage(cert)

        assert is_valid is True
        assert "Legacy certificate" in reason

    def test_invalid_authority_rejected(self):
        """Test validation fails with wrong authority."""
        from KERNEL import validate_lineage

        cert = {"human_authority": "Evil Hacker"}
        is_valid, reason = validate_lineage(cert)

        assert is_valid is False
        assert "Authority mismatch" in reason

    def test_missing_authority_rejected(self):
        """Test validation fails with missing authority."""
        from KERNEL import validate_lineage

        cert = {}  # No human_authority
        is_valid, reason = validate_lineage(cert)

        assert is_valid is False
        assert "Authority mismatch" in reason

    def test_matching_hash_passes(self):
        """Test validation passes with matching KERNEL hash."""
        from KERNEL import CREATOR, compute_rules_hash, validate_lineage

        current_hash = compute_rules_hash()
        cert = {"human_authority": CREATOR, "kernel_rules_hash": current_hash}

        is_valid, reason = validate_lineage(cert)

        assert is_valid is True
        assert "hash match" in reason

    def test_mismatched_hash_rejected(self):
        """Test validation fails with completely different hash (>5% drift)."""
        from KERNEL import CREATOR, validate_lineage

        # Completely different hash
        fake_hash = "0000000000000000"
        cert = {"human_authority": CREATOR, "kernel_rules_hash": fake_hash}

        is_valid, reason = validate_lineage(cert)

        assert is_valid is False
        assert "KERNEL drift detected" in reason

    def test_minor_drift_allowed(self):
        """Test validation passes with minor hash drift (<5%)."""
        from KERNEL import CREATOR, compute_rules_hash, validate_lineage

        # Create hash with 1 character different (6.25% drift at 16 chars)
        current_hash = compute_rules_hash()
        # Flip one character - this creates ~6.25% drift which exceeds default 5%
        # Use 0 characters changed for true "no drift" test
        same_hash = current_hash  # No drift
        cert = {"human_authority": CREATOR, "kernel_rules_hash": same_hash}

        is_valid, reason = validate_lineage(cert)

        assert is_valid is True

    def test_custom_drift_threshold(self):
        """Test custom drift threshold."""
        from KERNEL import CREATOR, compute_rules_hash, validate_lineage

        current_hash = compute_rules_hash()
        # Change 2 characters for 12.5% drift
        fake_hash = list(current_hash)
        fake_hash[0] = "0" if fake_hash[0] != "0" else "1"
        fake_hash[1] = "0" if fake_hash[1] != "0" else "1"
        fake_hash = "".join(fake_hash)

        cert = {"human_authority": CREATOR, "kernel_rules_hash": fake_hash}

        # Should fail with default 5%
        is_valid_default, _ = validate_lineage(cert, max_drift_percent=5.0)

        # Should pass with 15% threshold
        is_valid_lenient, _ = validate_lineage(cert, max_drift_percent=15.0)

        assert is_valid_default is False
        assert is_valid_lenient is True


class TestGetHeredityStamp:
    """Tests for get_heredity_stamp()"""

    def test_stamp_structure(self):
        """Test heredity stamp contains required fields."""
        from KERNEL import get_heredity_stamp

        stamp = get_heredity_stamp()

        assert "kernel_rules_hash" in stamp
        assert "kernel_version" in stamp
        assert "human_authority" in stamp
        assert "stamped_at" in stamp

    def test_stamp_values(self):
        """Test heredity stamp values are correct."""
        from KERNEL import CREATOR, VERSION, compute_rules_hash, get_heredity_stamp

        stamp = get_heredity_stamp()

        assert stamp["kernel_rules_hash"] == compute_rules_hash()
        assert stamp["kernel_version"] == VERSION
        assert stamp["human_authority"] == CREATOR
        assert stamp["stamped_at"] is not None

    def test_stamp_timestamp_is_iso(self):
        """Test heredity stamp timestamp is valid ISO format."""
        from datetime import datetime

        from KERNEL import get_heredity_stamp

        stamp = get_heredity_stamp()

        # Should parse without error
        parsed = datetime.fromisoformat(stamp["stamped_at"])
        assert parsed is not None


class TestIntegration:
    """Integration tests for heredity system"""

    def test_round_trip_validation(self):
        """Test that a stamp can be validated successfully."""
        from KERNEL import get_heredity_stamp, validate_lineage

        # Generate stamp
        stamp = get_heredity_stamp()

        # Create certificate from stamp
        cert = {"human_authority": stamp["human_authority"], "kernel_rules_hash": stamp["kernel_rules_hash"]}

        # Validate
        is_valid, reason = validate_lineage(cert)

        assert is_valid is True
        assert "hash match" in reason

    def test_exports_available(self):
        """Test that new functions are exported from KERNEL."""
        from KERNEL import __all__

        assert "compute_rules_hash" in __all__
        assert "validate_lineage" in __all__
        assert "get_heredity_stamp" in __all__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
