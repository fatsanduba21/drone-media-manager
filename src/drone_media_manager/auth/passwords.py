"""Argon2id password hashing with OWASP minimum memory and work factors."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)


def hash_password(password: str) -> str:
    """Hash a nonempty password with a random salt."""
    if not password:
        raise ValueError("Password must not be empty")
    return _HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    """Return false for mismatches and malformed stored hashes."""
    try:
        return _HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False
