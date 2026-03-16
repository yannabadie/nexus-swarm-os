"""
Encryption at Rest - AES-256-GCM for sensitive workspace files.

V12.4 COGNITIVE BOOST - Task #33

Provides transparent encryption/decryption for sensitive workspace files
such as blackboard.json, birth certificates, and DyLAN score persistence.

Uses AES-256-GCM (authenticated encryption) with PBKDF2 key derivation
from the NEXUS_ENCRYPTION_KEY environment variable.

Usage:
    from core.security_pkg.security.encryption import FileEncryptor, EncryptionConfig

    encryptor = FileEncryptor()  # Uses NEXUS_ENCRYPTION_KEY env var
    encryptor.encrypt_file(Path("workspace/.nexus/blackboard.json"))
    data = encryptor.decrypt_file(Path("workspace/.nexus/blackboard.json.enc"))

    # Or encrypt/decrypt raw bytes
    encrypted = encryptor.encrypt(b"sensitive data")
    decrypted = encryptor.decrypt(encrypted)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# Sentinel to detect missing key vs empty key
_UNSET = object()

# =============================================================================
# Configuration
# =============================================================================

ENV_KEY_NAME = "NEXUS_ENCRYPTION_KEY"
DEFAULT_SALT_LENGTH = 16
DEFAULT_IV_LENGTH = 12  # 96-bit IV for GCM
DEFAULT_TAG_LENGTH = 16  # 128-bit auth tag
DEFAULT_KDF_ITERATIONS = 100_000
ENCRYPTED_EXTENSION = ".enc"
MAGIC_HEADER = b"NEXUS_ENC_V1"


@dataclass
class EncryptionConfig:
    """
    Configuration for file encryption.

    Attributes:
        kdf_iterations: PBKDF2 iteration count (default 100,000)
        salt_length: Salt length in bytes (default 16)
        encrypted_extension: File extension for encrypted files
        remove_original: Whether to remove plaintext after encryption
    """

    kdf_iterations: int = DEFAULT_KDF_ITERATIONS
    salt_length: int = DEFAULT_SALT_LENGTH
    encrypted_extension: str = ENCRYPTED_EXTENSION
    remove_original: bool = True


# =============================================================================
# Encryption Primitives
# =============================================================================


def derive_key(
    password: str | bytes,
    salt: bytes,
    iterations: int = DEFAULT_KDF_ITERATIONS,
) -> bytes:
    """
    Derive a 256-bit encryption key from a password using PBKDF2-SHA256.

    Args:
        password: Password or passphrase
        salt: Random salt bytes
        iterations: PBKDF2 iteration count

    Returns:
        32-byte derived key
    """
    if isinstance(password, str):
        password = password.encode("utf-8")

    return hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password,
        salt=salt,
        iterations=iterations,
        dklen=32,
    )


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """
    Encrypt data with AES-256-GCM.

    Format: MAGIC_HEADER + salt(16) + iv(12) + tag(16) + ciphertext

    Args:
        data: Plaintext bytes
        key: 32-byte encryption key (from derive_key)

    Returns:
        Encrypted bytes with embedded IV and auth tag
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    iv = secrets.token_bytes(DEFAULT_IV_LENGTH)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, data, associated_data=MAGIC_HEADER)

    # ciphertext includes the 16-byte GCM tag appended by cryptography lib
    return iv + ciphertext


def decrypt_bytes(encrypted: bytes, key: bytes) -> bytes:
    """
    Decrypt AES-256-GCM encrypted data.

    Args:
        encrypted: iv(12) + ciphertext_with_tag
        key: 32-byte encryption key

    Returns:
        Decrypted plaintext bytes

    Raises:
        ValueError: If decryption fails (wrong key or tampered data)
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(encrypted) < DEFAULT_IV_LENGTH + DEFAULT_TAG_LENGTH:
        raise ValueError("Encrypted data too short")

    iv = encrypted[:DEFAULT_IV_LENGTH]
    ciphertext_with_tag = encrypted[DEFAULT_IV_LENGTH:]

    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(iv, ciphertext_with_tag, associated_data=MAGIC_HEADER)
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}") from e


# =============================================================================
# File Encryptor
# =============================================================================


class FileEncryptor:
    """
    Encrypts and decrypts workspace files using AES-256-GCM.

    The encryption key is derived from the NEXUS_ENCRYPTION_KEY
    environment variable using PBKDF2-SHA256.

    Encrypted file format:
        MAGIC_HEADER (12 bytes) + salt (16 bytes) + iv (12 bytes)
        + ciphertext + GCM tag (16 bytes)
    """

    def __init__(
        self,
        key: str | None = None,
        config: EncryptionConfig | None = None,
    ):
        """
        Initialize file encryptor.

        Args:
            key: Encryption key (defaults to NEXUS_ENCRYPTION_KEY env var)
            config: Encryption configuration

        Raises:
            ValueError: If no encryption key is available
        """
        self.config = config or EncryptionConfig()

        resolved_key = key or os.getenv(ENV_KEY_NAME)
        if not resolved_key:
            raise ValueError(
                f"No encryption key provided. Set {ENV_KEY_NAME} environment variable or pass key parameter."
            )

        self._password = resolved_key

    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypt raw bytes.

        Args:
            data: Plaintext bytes

        Returns:
            Encrypted bytes with header, salt, IV, ciphertext, and tag
        """
        salt = secrets.token_bytes(self.config.salt_length)
        key = derive_key(self._password, salt, self.config.kdf_iterations)
        encrypted = encrypt_bytes(data, key)

        # Prepend magic header and salt
        return MAGIC_HEADER + salt + encrypted

    def decrypt(self, data: bytes) -> bytes:
        """
        Decrypt raw bytes.

        Args:
            data: Encrypted bytes (with header and salt)

        Returns:
            Decrypted plaintext bytes

        Raises:
            ValueError: If data is not a valid NEXUS encrypted payload
        """
        header_len = len(MAGIC_HEADER)
        min_len = header_len + self.config.salt_length + DEFAULT_IV_LENGTH + DEFAULT_TAG_LENGTH

        if len(data) < min_len:
            raise ValueError("Data too short to be a valid encrypted payload")

        header = data[:header_len]
        if header != MAGIC_HEADER:
            raise ValueError("Invalid encryption header (not a NEXUS encrypted file)")

        salt = data[header_len : header_len + self.config.salt_length]
        encrypted = data[header_len + self.config.salt_length :]

        key = derive_key(self._password, salt, self.config.kdf_iterations)
        return decrypt_bytes(encrypted, key)

    def encrypt_file(self, filepath: Path) -> Path:
        """
        Encrypt a file on disk.

        Args:
            filepath: Path to plaintext file

        Returns:
            Path to encrypted file

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        plaintext = filepath.read_bytes()
        encrypted = self.encrypt(plaintext)

        enc_path = filepath.parent / (filepath.name + self.config.encrypted_extension)
        enc_path.write_bytes(encrypted)

        if self.config.remove_original:
            filepath.unlink()

        _logger.info(f"Encrypted: {filepath} -> {enc_path}")
        return enc_path

    def decrypt_file(self, filepath: Path) -> Path:
        """
        Decrypt an encrypted file on disk.

        Args:
            filepath: Path to encrypted file (.enc)

        Returns:
            Path to decrypted file (original name without .enc)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If decryption fails
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        encrypted = filepath.read_bytes()
        plaintext = self.decrypt(encrypted)

        # Remove .enc extension
        if filepath.name.endswith(self.config.encrypted_extension):
            original_name = filepath.name[: -len(self.config.encrypted_extension)]
        else:
            original_name = filepath.name + ".dec"

        dec_path = filepath.parent / original_name
        dec_path.write_bytes(plaintext)

        _logger.info(f"Decrypted: {filepath} -> {dec_path}")
        return dec_path

    def encrypt_json(self, data: Any) -> bytes:
        """
        Encrypt a JSON-serializable object.

        Args:
            data: JSON-serializable Python object

        Returns:
            Encrypted bytes
        """
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return self.encrypt(plaintext)

    def decrypt_json(self, data: bytes) -> Any:
        """
        Decrypt bytes to a JSON object.

        Args:
            data: Encrypted bytes

        Returns:
            Parsed JSON object
        """
        plaintext = self.decrypt(data)
        return json.loads(plaintext.decode("utf-8"))

    def is_encrypted(self, filepath: Path) -> bool:
        """
        Check if a file appears to be encrypted.

        Args:
            filepath: Path to check

        Returns:
            True if file has the NEXUS encryption header
        """
        filepath = Path(filepath)
        if not filepath.exists():
            return False

        try:
            with open(filepath, "rb") as f:
                header = f.read(len(MAGIC_HEADER))
                return header == MAGIC_HEADER
        except OSError:
            return False

    @staticmethod
    def is_available() -> bool:
        """Check if encryption key is configured."""
        return bool(os.getenv(ENV_KEY_NAME))

    def to_dict(self) -> dict[str, Any]:
        """Export encryptor state (without key)."""
        return {
            "key_configured": True,
            "kdf_iterations": self.config.kdf_iterations,
            "salt_length": self.config.salt_length,
            "encrypted_extension": self.config.encrypted_extension,
            "remove_original": self.config.remove_original,
        }
