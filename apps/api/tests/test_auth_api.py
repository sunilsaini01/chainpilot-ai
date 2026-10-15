"""API tests for login, logout and role checks (RUN_DB_TESTS=1)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import AuthToken, Role, User
from tests.conftest import TEST_PASSWORD, login

NEW_USER = {
    "email": "new.person@example.com",
    "full_name": "New Person",
    "role": "analyst",
    "password": "another-long-password",
}


def test_login_returns_token_and_user_without_password_hash(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.MANAGER)

    response = api_client.post(
        "/auth/login", json={"email": "manager@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) >= 43
    assert body["user"]["role"] == "manager"
    assert "password" not in response.text  # neither the password nor its hash


@pytest.mark.parametrize(
    ("email", "password"),
    [("manager@example.com", "wrong-password-123"), ("nobody@example.com", TEST_PASSWORD)],
)
def test_failed_login_gives_the_same_401_for_every_cause(
    api_client: TestClient, make_user: Callable[..., User], email: str, password: str
) -> None:
    make_user(Role.MANAGER)

    response = api_client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}


def test_me_returns_the_logged_in_user(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    headers = login(api_client, "analyst@example.com")

    response = api_client.get("/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["email"] == "analyst@example.com"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer made-up-token"}, {"Authorization": "Basic abc"}],
)
def test_protected_endpoint_without_valid_token_is_401(
    api_client: TestClient, headers: dict[str, str]
) -> None:
    response = api_client.get("/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_logout_revokes_the_token(api_client: TestClient, make_user: Callable[..., User]) -> None:
    make_user(Role.ANALYST)
    headers = login(api_client, "analyst@example.com")

    assert api_client.post("/auth/logout", headers=headers).status_code == 204
    assert api_client.get("/auth/me", headers=headers).status_code == 401


def test_expired_token_is_401(
    api_client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    headers = login(api_client, "analyst@example.com")
    db_session.execute(update(AuthToken).values(expires_at=AuthToken.created_at))
    db_session.commit()

    assert api_client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [(Role.ANALYST, 403), (Role.MANAGER, 403), (Role.ADMIN, 200)],
)
def test_only_admins_can_list_users(
    api_client: TestClient, make_user: Callable[..., User], role: Role, expected_status: int
) -> None:
    user = make_user(role)
    headers = login(api_client, user.email)

    response = api_client.get("/users", headers=headers)

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json() == {"detail": "This action requires the admin role or higher"}


def test_admin_can_create_user_who_can_then_log_in(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ADMIN)
    admin_headers = login(api_client, "admin@example.com")

    response = api_client.post("/users", json=NEW_USER, headers=admin_headers)

    assert response.status_code == 201
    assert response.json()["email"] == NEW_USER["email"]
    assert "password" not in response.text
    login(api_client, NEW_USER["email"], NEW_USER["password"])  # asserts 200


def test_non_admin_cannot_create_users(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.MANAGER)
    headers = login(api_client, "manager@example.com")

    response = api_client.post("/users", json=NEW_USER, headers=headers)

    assert response.status_code == 403
    # And nothing was created: the new user cannot log in.
    failed = api_client.post(
        "/auth/login", json={"email": NEW_USER["email"], "password": NEW_USER["password"]}
    )
    assert failed.status_code == 401


def test_creating_duplicate_user_is_409(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ADMIN)
    headers = login(api_client, "admin@example.com")
    api_client.post("/users", json=NEW_USER, headers=headers)

    response = api_client.post("/users", json=NEW_USER, headers=headers)

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [("password", "short"), ("role", "superuser"), ("email", "not-an-email")],
)
def test_invalid_new_user_is_422(
    api_client: TestClient, make_user: Callable[..., User], field: str, value: str
) -> None:
    make_user(Role.ADMIN)
    headers = login(api_client, "admin@example.com")

    response = api_client.post("/users", json={**NEW_USER, field: value}, headers=headers)

    assert response.status_code == 422


def test_users_list_is_paginated(api_client: TestClient, make_user: Callable[..., User]) -> None:
    make_user(Role.ADMIN)
    make_user(Role.ANALYST)
    make_user(Role.MANAGER)
    headers = login(api_client, "admin@example.com")

    page = api_client.get("/users", params={"limit": 2, "offset": 1}, headers=headers)

    assert page.status_code == 200
    assert [user["role"] for user in page.json()] == ["analyst", "manager"]
    assert api_client.get("/users", params={"limit": 0}, headers=headers).status_code == 422
