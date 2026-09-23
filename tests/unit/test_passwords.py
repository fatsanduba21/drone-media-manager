"""Password storage contract for gallery users."""

from __future__ import annotations


def test_argon2id_hash_is_salted_and_verifies_unicode_password() -> None:
    from drone_media_manager.auth.passwords import hash_password, verify_password

    password = "Viagem segura 🔒"
    first = hash_password(password)
    second = hash_password(password)
    assert first.startswith("$argon2id$")
    assert first != second
    assert password not in first
    assert verify_password(password, first)
    assert not verify_password("wrong", first)
    assert not verify_password(password, "not-a-valid-hash")
