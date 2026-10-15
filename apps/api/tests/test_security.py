"""Unit tests for password hashing, tokens and roles. No database needed."""

import pytest

from app.models import Role
from app.security import (
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_correct_password_verifies() -> None:
    stored = hash_password("correct-horse-battery")

    assert verify_password("correct-horse-battery", stored)


def test_wrong_password_does_not_verify() -> None:
    stored = hash_password("correct-horse-battery")

    assert not verify_password("correct-horse-batterY", stored)


def test_hash_contains_parameters_and_never_the_password() -> None:
    stored = hash_password("correct-horse-battery")

    assert stored.startswith("scrypt$16384$8$5$")
    assert "correct-horse-battery" not in stored


def test_same_password_gets_different_hashes_because_of_random_salt() -> None:
    assert hash_password("correct-horse-battery") != hash_password("correct-horse-battery")


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "plain-text-password",
        "bcrypt$12$abc$def$ghi$jkl",  # unknown algorithm
        "scrypt$16384$8$5$not-base64!$AAAA",
        "scrypt$notanumber$8$5$AAAA$AAAA",
        "scrypt$3$8$5$AAAA$AAAA",  # N must be a power of two
    ],
)
def test_malformed_hash_is_rejected_not_crashed(malformed: str) -> None:
    assert verify_password("anything", malformed) is False


def test_tokens_are_long_random_and_unique() -> None:
    tokens = {generate_token() for _ in range(100)}

    assert len(tokens) == 100
    assert all(len(token) >= 43 for token in tokens)  # 32 random bytes in base64


def test_token_hash_is_stable_and_differs_from_token() -> None:
    token = generate_token()

    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token
    assert len(hash_token(token)) == 64  # SHA-256 in hex


@pytest.mark.parametrize(
    ("role", "minimum", "allowed"),
    [
        (Role.ANALYST, Role.ANALYST, True),
        (Role.ANALYST, Role.MANAGER, False),
        (Role.ANALYST, Role.ADMIN, False),
        (Role.MANAGER, Role.ANALYST, True),
        (Role.MANAGER, Role.MANAGER, True),
        (Role.MANAGER, Role.ADMIN, False),
        (Role.ADMIN, Role.ANALYST, True),
        (Role.ADMIN, Role.MANAGER, True),
        (Role.ADMIN, Role.ADMIN, True),
    ],
)
def test_role_hierarchy(role: Role, minimum: Role, allowed: bool) -> None:
    assert role.at_least(minimum) is allowed
