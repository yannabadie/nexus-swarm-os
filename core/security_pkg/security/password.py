"""
NEXUS V12.4 COGNITIVE BOOST - Password Hashing Utilities

Provides secure password hashing using Argon2id via argon2-cffi.
Migrated from passlib/bcrypt (deprecated in Python 3.13+).

Follows OWASP recommendations and RFC 9106:
- Algorithm: Argon2id (hybrid, resistant to side-channel + GPU attacks)
- Time cost: 2 iterations minimum
- Memory cost: 19456 KiB (~19 MiB)
- Parallelism: 1

Usage:
    from core.security_pkg.security.password import hash_password, verify_password

    hashed = hash_password("mypassword")
    if verify_password("mypassword", hashed):
        print("Valid!")

Security Notes:
    - Argon2id is the OWASP-recommended algorithm (2024+)
    - Automatically generates random salt (16 bytes)
    - Constant-time comparison (safe against timing attacks)
    - Falls back to bcrypt verification for legacy hashes

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-15
"""

# Lazy import: argon2-cffi calls platform.machine() at import time,
# which uses _wmi on Python 3.12+ Windows. If WMI is unresponsive
# this hangs indefinitely. Deferring the import to first use avoids
# blocking the entire module tree at import time.
_hasher = None


def _get_hasher():
    """Lazily initialize the Argon2id hasher on first use."""
    global _hasher
    if _hasher is None:
        from argon2 import PasswordHasher, Type

        _hasher = PasswordHasher(
            time_cost=2,  # 2 iterations (OWASP minimum)
            memory_cost=19456,  # ~19 MiB (OWASP first recommendation)
            parallelism=1,  # Single-threaded (safe default)
            hash_len=32,  # 32-byte output hash
            salt_len=16,  # 16-byte random salt
            type=Type.ID,  # Argon2id
        )
    return _hasher


# =============================================================================
# Public API
# =============================================================================


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using Argon2id.

    Args:
        plain_password: The plaintext password to hash

    Returns:
        Argon2id hash string (starts with $argon2id$)

    Example:
        >>> hashed = hash_password("nexus123")
        >>> hashed.startswith("$argon2id$")
        True
    """
    return _get_hasher().hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a hash.

    Supports both Argon2id (new) and bcrypt (legacy) hashes.

    Args:
        plain_password: The plaintext password to verify
        hashed_password: The hash to check against

    Returns:
        True if password matches, False otherwise

    Note:
        This function is safe against timing attacks as argon2-cffi
        uses constant-time comparison internally.
    """
    # Argon2id hash
    if hashed_password.startswith("$argon2"):
        try:
            from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

            return _get_hasher().verify(hashed_password, plain_password)
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHashError):
            return False

    # Legacy bcrypt hash ($2b$ prefix) - graceful migration
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
        try:
            import bcrypt

            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except ImportError:
            # bcrypt not installed - can't verify legacy hashes
            return False
        except Exception:
            return False

    # Unknown hash format
    return False


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if a password hash needs to be rehashed.

    Returns True for:
    - Legacy bcrypt hashes (should migrate to Argon2id)
    - Argon2id hashes with outdated parameters

    Args:
        hashed_password: The current hash to check

    Returns:
        True if the password should be rehashed
    """
    # Any non-argon2 hash needs rehashing
    if not hashed_password.startswith("$argon2"):
        return True

    # Check if Argon2 parameters are current
    return _get_hasher().check_needs_rehash(hashed_password)
