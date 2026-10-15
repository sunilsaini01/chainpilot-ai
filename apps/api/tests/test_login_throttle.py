"""Login rate-limiting tests (RUN_DB_TESTS=1)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import login_throttle
from app.models import LoginAttempt, Role, User
from app.routes import auth as auth_routes
from tests.conftest import TEST_PASSWORD

EMAIL = "analyst@example.com"


def attempt(client: TestClient, email: str = EMAIL, password: str = "wrong-password-xx") -> int:
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.status_code


def test_five_failures_block_the_account_even_with_the_right_password(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    assert [attempt(api_client) for _ in range(5)] == [401] * 5

    response = api_client.post("/auth/login", json={"email": EMAIL, "password": TEST_PASSWORD})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"
    assert "Too many failed login attempts" in response.json()["detail"]


def test_email_case_does_not_bypass_the_limit(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    for email in ["analyst@example.com", "ANALYST@example.com", " Analyst@Example.com "] * 2:
        attempt(api_client, email)

    assert attempt(api_client, EMAIL, TEST_PASSWORD) == 429


def test_blocked_login_skips_the_password_check(
    api_client: TestClient, make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user(Role.ANALYST)
    for _ in range(5):
        attempt(api_client)

    def must_not_run(*args: object) -> None:
        raise AssertionError("authenticate() ran while the login was blocked")

    monkeypatch.setattr(auth_routes, "authenticate", must_not_run)
    assert attempt(api_client) == 429  # answered without the slow scrypt hash


def test_successful_login_resets_the_account_count(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    for _ in range(4):
        attempt(api_client)
    assert attempt(api_client, password=TEST_PASSWORD) == 200
    for _ in range(4):
        attempt(api_client)

    assert attempt(api_client, password=TEST_PASSWORD) == 200


def test_block_expires_after_the_window(
    api_client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    for _ in range(5):
        attempt(api_client)
    # Move the failures 16 minutes into the past.
    db_session.execute(
        update(LoginAttempt).values(created_at=datetime.now(UTC) - timedelta(minutes=16))
    )
    db_session.commit()

    assert attempt(api_client, password=TEST_PASSWORD) == 200


def test_other_accounts_are_not_blocked_by_one_account(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    make_user(Role.MANAGER)
    for _ in range(5):
        attempt(api_client)

    assert attempt(api_client, "manager@example.com", TEST_PASSWORD) == 200


def test_one_ip_is_limited_across_many_emails(
    api_client: TestClient, make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(login_throttle, "MAX_FAILURES_PER_IP", 3)
    make_user(Role.MANAGER)
    for number in range(3):
        attempt(api_client, f"guess{number}@example.com")

    # A fresh email from the same client is now blocked too.
    assert attempt(api_client, "manager@example.com", TEST_PASSWORD) == 429


def test_attempts_are_recorded_with_normalized_email(
    api_client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    attempt(api_client, " Analyst@Example.com ")
    attempt(api_client, EMAIL, TEST_PASSWORD)

    rows = db_session.execute(
        select(LoginAttempt.email, LoginAttempt.succeeded).order_by(LoginAttempt.id)
    ).all()
    assert rows == [(EMAIL, False), (EMAIL, True)]
