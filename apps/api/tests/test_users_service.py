"""User service tests against a throwaway PostgreSQL database (RUN_DB_TESTS=1)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuthToken, Role, User
from app.security import hash_token
from app.users_service import (
    UserAlreadyExistsError,
    authenticate,
    create_user,
    issue_token,
    revoke_token,
    user_for_token,
)
from tests.conftest import TEST_PASSWORD


def test_create_user_normalizes_email_and_hashes_password(db_session: Session) -> None:
    user = create_user(
        db_session, "  Ana.Lyst@Example.COM ", "Ana Lyst", Role.ANALYST, TEST_PASSWORD
    )
    db_session.commit()

    assert user.email == "ana.lyst@example.com"
    assert user.password_hash.startswith("scrypt$")
    assert TEST_PASSWORD not in user.password_hash


def test_duplicate_email_is_rejected_case_insensitively(
    db_session: Session, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST, email="dup@example.com")

    with pytest.raises(UserAlreadyExistsError):
        create_user(db_session, "DUP@example.com", "Other", Role.MANAGER, TEST_PASSWORD)

    # The savepoint kept the session usable: the first user is still there.
    assert db_session.execute(select(User.email)).scalars().all() == ["dup@example.com"]


@pytest.mark.parametrize(
    ("email", "full_name", "role", "password", "message"),
    [
        ("not-an-email", "Name", "analyst", TEST_PASSWORD, "Invalid email"),
        ("a@example.com", "   ", "analyst", TEST_PASSWORD, "Full name"),
        ("a@example.com", "Name", "superuser", TEST_PASSWORD, "superuser"),
        ("a@example.com", "Name", "analyst", "short", "12 to 128"),
        ("a@example.com", "Name", "analyst", "x" * 129, "12 to 128"),
    ],
)
def test_invalid_user_input_is_rejected(
    db_session: Session, email: str, full_name: str, role: str, password: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_user(db_session, email, full_name, role, password)  # type: ignore[arg-type]


def test_database_rejects_unknown_role_and_uppercase_email(db_session: Session) -> None:
    # Second safety net: CHECK constraints, even if the service is bypassed.
    for bad_user, constraint in [
        (User(email="x@example.com", full_name="X", role="root", password_hash="h"), "role"),
        (User(email="X@example.com", full_name="X", role="analyst", password_hash="h"), "email"),
    ]:
        db_session.add(bad_user)
        with pytest.raises(IntegrityError, match=f"ck_users_{constraint}"):
            db_session.flush()
        db_session.rollback()


def test_authenticate_accepts_correct_credentials_any_email_case(
    db_session: Session, make_user: Callable[..., User]
) -> None:
    user = make_user(Role.MANAGER)

    assert authenticate(db_session, "MANAGER@example.com", TEST_PASSWORD) == user


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("manager@example.com", "wrong-password-123"),
        ("nobody@example.com", TEST_PASSWORD),
        ("not-an-email", TEST_PASSWORD),
    ],
)
def test_authenticate_rejects_bad_credentials(
    db_session: Session, make_user: Callable[..., User], email: str, password: str
) -> None:
    make_user(Role.MANAGER)

    assert authenticate(db_session, email, password) is None


def test_authenticate_rejects_inactive_user(
    db_session: Session, make_user: Callable[..., User]
) -> None:
    user = make_user(Role.ANALYST)
    user.is_active = False
    db_session.commit()

    assert authenticate(db_session, user.email, TEST_PASSWORD) is None


def test_token_lifecycle_issue_use_revoke(
    db_session: Session, make_user: Callable[..., User]
) -> None:
    user = make_user(Role.ANALYST)
    raw_token, record = issue_token(db_session, user, ttl_minutes=60)
    db_session.commit()

    # Only the hash is stored.
    assert record.token_hash == hash_token(raw_token)
    assert db_session.execute(select(AuthToken.token_hash)).scalar_one() != raw_token
    assert user_for_token(db_session, raw_token) == user

    revoke_token(db_session, raw_token)
    db_session.commit()
    assert user_for_token(db_session, raw_token) is None


def test_expired_token_is_rejected(db_session: Session, make_user: Callable[..., User]) -> None:
    user = make_user(Role.ANALYST)
    raw_token, _ = issue_token(db_session, user, ttl_minutes=60)
    db_session.execute(
        update(AuthToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()

    assert user_for_token(db_session, raw_token) is None


def test_token_stops_working_when_user_is_deactivated(
    db_session: Session, make_user: Callable[..., User]
) -> None:
    user = make_user(Role.ANALYST)
    raw_token, _ = issue_token(db_session, user, ttl_minutes=60)
    user.is_active = False
    db_session.commit()

    assert user_for_token(db_session, raw_token) is None


def test_unknown_token_is_rejected(db_session: Session) -> None:
    assert user_for_token(db_session, "made-up-token") is None
