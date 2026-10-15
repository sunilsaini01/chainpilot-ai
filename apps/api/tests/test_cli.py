"""Tests for the command-line tools (RUN_DB_TESTS=1)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import cli
from app.models import AuthToken, LoginAttempt, Role, User
from app.users_service import authenticate


@pytest.fixture
def cli_uses_test_db(monkeypatch: pytest.MonkeyPatch, db_engine: Engine) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: db_engine)


ADMIN_ARGS = [
    "create-user",
    "--email",
    "Boss@Example.com",
    "--full-name",
    "Boss",
    "--role",
    "admin",
]


def test_create_admin_with_password_from_environment(
    cli_uses_test_db: None,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(cli.PASSWORD_ENV_VAR, "a-very-long-password")

    exit_code = cli.main(ADMIN_ARGS)

    assert exit_code == 0
    assert "email=boss@example.com role=admin" in capsys.readouterr().out
    assert authenticate(db_session, "boss@example.com", "a-very-long-password") is not None


def test_prompted_passwords_must_match(
    cli_uses_test_db: None,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(cli.PASSWORD_ENV_VAR, raising=False)
    answers = iter(["a-very-long-password", "a-different-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))

    exit_code = cli.main(ADMIN_ARGS)

    assert exit_code == 1
    assert "Passwords do not match" in capsys.readouterr().err
    assert db_session.execute(select(User)).first() is None


def test_short_password_is_refused(
    cli_uses_test_db: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(cli.PASSWORD_ENV_VAR, "short")

    assert cli.main(ADMIN_ARGS) == 1
    assert "12 to 128" in capsys.readouterr().err


def test_cleanup_deletes_only_old_tokens_and_attempts(
    cli_uses_test_db: None,
    db_session: Session,
    make_user,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = make_user(Role.ANALYST)
    long_ago = datetime.now(UTC) - timedelta(days=40)
    db_session.add_all(
        [
            AuthToken(user_id=user.id, token_hash="a" * 64, expires_at=long_ago),  # expired
            AuthToken(  # revoked long ago
                user_id=user.id,
                token_hash="b" * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                revoked_at=long_ago,
            ),
            AuthToken(  # still valid: must survive
                user_id=user.id,
                token_hash="c" * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            LoginAttempt(email="x@example.com", succeeded=False, created_at=long_ago),
            LoginAttempt(email="x@example.com", succeeded=False),  # recent: must survive
        ]
    )
    db_session.commit()

    assert cli.main(["cleanup", "--days", "30"]) == 0

    assert "Deleted 2 stale tokens and 1 old login attempts" in capsys.readouterr().out
    assert db_session.execute(select(AuthToken.token_hash)).scalars().all() == ["c" * 64]
    assert len(db_session.execute(select(LoginAttempt)).all()) == 1


def test_cleanup_rejects_zero_days(
    cli_uses_test_db: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["cleanup", "--days", "0"]) == 1
    assert "at least 1" in capsys.readouterr().err
