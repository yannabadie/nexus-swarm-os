"""
Tests for V12.4 Encryption at Rest - AES-256-GCM file encryption.

Validates:
- Key derivation (PBKDF2-SHA256)
- Encrypt/decrypt round-trip for raw bytes
- Encrypt/decrypt round-trip for JSON data
- File encryption and decryption
- Encrypted file detection (magic header)
- Error handling (wrong key, tampered data, missing key)
- Configuration defaults and customization
- Module exports
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.security_pkg.security.encryption import (
    DEFAULT_KDF_ITERATIONS,
    ENV_KEY_NAME,
    MAGIC_HEADER,
    EncryptionConfig,
    FileEncryptor,
    decrypt_bytes,
    derive_key,
    encrypt_bytes,
)

# =============================================================================
# Key Derivation Tests
# =============================================================================


class TestKeyDerivation:
    """Test PBKDF2 key derivation."""

    def test_derives_32_byte_key(self):
        key = derive_key("test_password", b"saltsaltsaltsalt")
        assert len(key) == 32

    def test_deterministic(self):
        salt = b"fixed_salt_12345"
        k1 = derive_key("password", salt)
        k2 = derive_key("password", salt)
        assert k1 == k2

    def test_different_passwords_different_keys(self):
        salt = b"fixed_salt_12345"
        k1 = derive_key("password1", salt)
        k2 = derive_key("password2", salt)
        assert k1 != k2

    def test_different_salts_different_keys(self):
        k1 = derive_key("password", b"salt_one_1234567")
        k2 = derive_key("password", b"salt_two_1234567")
        assert k1 != k2

    def test_accepts_bytes_password(self):
        key = derive_key(b"binary_password", b"saltsaltsaltsalt")
        assert len(key) == 32

    def test_custom_iterations(self):
        key = derive_key("pwd", b"saltsaltsaltsalt", iterations=1000)
        assert len(key) == 32


# =============================================================================
# Low-Level Encrypt/Decrypt Tests
# =============================================================================


class TestEncryptDecryptBytes:
    """Test AES-256-GCM encrypt/decrypt primitives."""

    def test_roundtrip(self):
        key = derive_key("test", b"saltsaltsaltsalt")
        plaintext = b"Hello, NEXUS!"
        encrypted = encrypt_bytes(plaintext, key)
        decrypted = decrypt_bytes(encrypted, key)
        assert decrypted == plaintext

    def test_encrypted_differs_from_plaintext(self):
        key = derive_key("test", b"saltsaltsaltsalt")
        plaintext = b"Secret data"
        encrypted = encrypt_bytes(plaintext, key)
        assert encrypted != plaintext

    def test_different_ciphertext_each_time(self):
        """Random IV should produce different ciphertext."""
        key = derive_key("test", b"saltsaltsaltsalt")
        plaintext = b"Same data"
        enc1 = encrypt_bytes(plaintext, key)
        enc2 = encrypt_bytes(plaintext, key)
        assert enc1 != enc2  # Different IV

    def test_wrong_key_fails(self):
        key1 = derive_key("key1", b"saltsaltsaltsalt")
        key2 = derive_key("key2", b"saltsaltsaltsalt")
        encrypted = encrypt_bytes(b"data", key1)
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_bytes(encrypted, key2)

    def test_tampered_data_fails(self):
        key = derive_key("test", b"saltsaltsaltsalt")
        encrypted = encrypt_bytes(b"data", key)
        # Flip a bit in the ciphertext
        tampered = bytearray(encrypted)
        tampered[-5] ^= 0xFF
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_bytes(bytes(tampered), key)

    def test_too_short_data(self):
        key = derive_key("test", b"saltsaltsaltsalt")
        with pytest.raises(ValueError, match="too short"):
            decrypt_bytes(b"short", key)

    def test_empty_plaintext(self):
        key = derive_key("test", b"saltsaltsaltsalt")
        encrypted = encrypt_bytes(b"", key)
        decrypted = decrypt_bytes(encrypted, key)
        assert decrypted == b""

    def test_large_plaintext(self):
        key = derive_key("test", b"saltsaltsaltsalt")
        plaintext = b"x" * 1_000_000  # 1MB
        encrypted = encrypt_bytes(plaintext, key)
        decrypted = decrypt_bytes(encrypted, key)
        assert decrypted == plaintext


# =============================================================================
# FileEncryptor - Initialization Tests
# =============================================================================


class TestFileEncryptorInit:
    """Test encryptor initialization."""

    def test_with_explicit_key(self):
        enc = FileEncryptor(key="my_secret_key")
        assert enc.config.kdf_iterations == DEFAULT_KDF_ITERATIONS

    def test_with_env_var(self):
        with patch.dict(os.environ, {ENV_KEY_NAME: "env_key"}):
            enc = FileEncryptor()
            assert enc._password == "env_key"

    def test_no_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure env var is not set
            os.environ.pop(ENV_KEY_NAME, None)
            with pytest.raises(ValueError, match="No encryption key"):
                FileEncryptor()

    def test_custom_config(self):
        cfg = EncryptionConfig(kdf_iterations=50_000, remove_original=False)
        enc = FileEncryptor(key="test", config=cfg)
        assert enc.config.kdf_iterations == 50_000
        assert enc.config.remove_original is False


# =============================================================================
# FileEncryptor - Encrypt/Decrypt Tests
# =============================================================================


class TestFileEncryptorRoundTrip:
    """Test high-level encrypt/decrypt."""

    def test_bytes_roundtrip(self):
        enc = FileEncryptor(key="test_key")
        plaintext = b"Sensitive NEXUS data"
        encrypted = enc.encrypt(plaintext)
        decrypted = enc.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypted_has_header(self):
        enc = FileEncryptor(key="test_key")
        encrypted = enc.encrypt(b"data")
        assert encrypted[: len(MAGIC_HEADER)] == MAGIC_HEADER

    def test_wrong_key_fails(self):
        enc1 = FileEncryptor(key="key_one")
        enc2 = FileEncryptor(key="key_two")
        encrypted = enc1.encrypt(b"secret")
        with pytest.raises(ValueError):
            enc2.decrypt(encrypted)

    def test_invalid_header_fails(self):
        enc = FileEncryptor(key="test_key")
        with pytest.raises(ValueError, match="Invalid encryption header"):
            enc.decrypt(b"NOT_NEXUS_HEADER" + b"\x00" * 100)

    def test_too_short_fails(self):
        enc = FileEncryptor(key="test_key")
        with pytest.raises(ValueError, match="too short"):
            enc.decrypt(b"short")


# =============================================================================
# FileEncryptor - JSON Tests
# =============================================================================


class TestJsonEncryption:
    """Test JSON encrypt/decrypt."""

    def test_json_roundtrip(self):
        enc = FileEncryptor(key="test_key")
        data = {"blackboard": {"objective": "test"}, "scores": [1.0, 2.5, 3.7]}
        encrypted = enc.encrypt_json(data)
        decrypted = enc.decrypt_json(encrypted)
        assert decrypted == data

    def test_json_unicode(self):
        enc = FileEncryptor(key="test_key")
        data = {"message": "Bonjour le monde! 🌍"}
        encrypted = enc.encrypt_json(data)
        decrypted = enc.decrypt_json(encrypted)
        assert decrypted == data

    def test_json_nested(self):
        enc = FileEncryptor(key="test_key")
        data = {
            "agents": {
                "gemini": {"score": 0.85, "tasks": ["coding", "research"]},
                "claude": {"score": 0.92, "tasks": ["creative", "analysis"]},
            }
        }
        encrypted = enc.encrypt_json(data)
        decrypted = enc.decrypt_json(encrypted)
        assert decrypted == data


# =============================================================================
# FileEncryptor - File Operations Tests
# =============================================================================


class TestFileOperations:
    """Test file encryption/decryption on disk."""

    def test_encrypt_file(self, tmp_path):
        original = tmp_path / "blackboard.json"
        original.write_text('{"objective": "test"}')

        enc = FileEncryptor(key="file_key")
        enc_path = enc.encrypt_file(original)

        assert enc_path.exists()
        assert enc_path.name == "blackboard.json.enc"
        assert not original.exists()  # Original removed by default

    def test_encrypt_file_keep_original(self, tmp_path):
        original = tmp_path / "data.json"
        original.write_text('{"key": "value"}')

        cfg = EncryptionConfig(remove_original=False)
        enc = FileEncryptor(key="file_key", config=cfg)
        enc_path = enc.encrypt_file(original)

        assert enc_path.exists()
        assert original.exists()  # Not removed

    def test_decrypt_file(self, tmp_path):
        original = tmp_path / "secret.json"
        content = '{"sensitive": true}'
        original.write_text(content)

        enc = FileEncryptor(key="file_key")
        enc_path = enc.encrypt_file(original)

        # Decrypt
        dec_path = enc.decrypt_file(enc_path)
        assert dec_path.exists()
        assert dec_path.name == "secret.json"
        assert dec_path.read_text() == content

    def test_encrypt_file_not_found(self):
        enc = FileEncryptor(key="test")
        with pytest.raises(FileNotFoundError):
            enc.encrypt_file(Path("/nonexistent/file.json"))

    def test_decrypt_file_not_found(self):
        enc = FileEncryptor(key="test")
        with pytest.raises(FileNotFoundError):
            enc.decrypt_file(Path("/nonexistent/file.enc"))

    def test_file_roundtrip_binary(self, tmp_path):
        """Test with binary content."""
        original = tmp_path / "scores.bin"
        binary_data = bytes(range(256)) * 100  # 25.6KB binary
        original.write_bytes(binary_data)

        cfg = EncryptionConfig(remove_original=False)
        enc = FileEncryptor(key="binary_key", config=cfg)
        enc_path = enc.encrypt_file(original)
        dec_path = enc.decrypt_file(enc_path)

        assert dec_path.read_bytes() == binary_data


# =============================================================================
# FileEncryptor - Detection Tests
# =============================================================================


class TestEncryptedDetection:
    """Test encrypted file detection."""

    def test_detect_encrypted(self, tmp_path):
        original = tmp_path / "test.json"
        original.write_text("{}")

        enc = FileEncryptor(key="test")
        enc_path = enc.encrypt_file(original)

        assert enc.is_encrypted(enc_path) is True

    def test_detect_plaintext(self, tmp_path):
        plain = tmp_path / "plain.json"
        plain.write_text('{"not": "encrypted"}')

        enc = FileEncryptor(key="test")
        assert enc.is_encrypted(plain) is False

    def test_detect_nonexistent(self):
        enc = FileEncryptor(key="test")
        assert enc.is_encrypted(Path("/nonexistent")) is False

    def test_is_available_with_env(self):
        with patch.dict(os.environ, {ENV_KEY_NAME: "key"}):
            assert FileEncryptor.is_available() is True

    def test_is_available_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_KEY_NAME, None)
            assert FileEncryptor.is_available() is False


# =============================================================================
# EncryptionConfig Tests
# =============================================================================


class TestEncryptionConfig:
    """Test configuration defaults."""

    def test_defaults(self):
        cfg = EncryptionConfig()
        assert cfg.kdf_iterations == 100_000
        assert cfg.salt_length == 16
        assert cfg.encrypted_extension == ".enc"
        assert cfg.remove_original is True

    def test_custom(self):
        cfg = EncryptionConfig(
            kdf_iterations=200_000,
            salt_length=32,
            encrypted_extension=".encrypted",
            remove_original=False,
        )
        assert cfg.kdf_iterations == 200_000
        assert cfg.salt_length == 32


# =============================================================================
# State Export Tests
# =============================================================================


class TestStateExport:
    """Test encryptor state export."""

    def test_to_dict_no_key_leak(self):
        enc = FileEncryptor(key="super_secret")
        d = enc.to_dict()
        assert d["key_configured"] is True
        assert "super_secret" not in str(d)
        assert "kdf_iterations" in d


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that encryption types are importable."""

    def test_from_security_package(self):
        from core.security_pkg.security import EncryptionConfig, FileEncryptor, derive_key

        assert FileEncryptor is not None
        assert EncryptionConfig is not None
        assert derive_key is not None

    def test_from_module(self):
        from core.security_pkg.security.encryption import (
            MAGIC_HEADER,
            EncryptionConfig,
            FileEncryptor,
            decrypt_bytes,
            derive_key,
            encrypt_bytes,
        )

        assert all([FileEncryptor, EncryptionConfig, derive_key, encrypt_bytes, decrypt_bytes])
        assert MAGIC_HEADER == b"NEXUS_ENC_V1"
