"""Changing your own password, and admins setting a temporary one (RUN_DB_TESTS=1)."""

import json
import os
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Role, User
from tests.conftest import TEST_PASSWORD, login

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)
NEW_PASSWORD = "a-brand-new-password"


def change(client: TestClient, headers: dict[str, str], current: str, new: str):
    return client.post(
        "/auth/password", json={"current_password": current, "new_password": new}, headers=headers
    )


def test_change_own_password_signs_out_other_sessions_only(
    api_client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    make_user(Role.ANALYST)
    laptop = login(api_client, "analyst@example.com")
    phone = login(api_client, "analyst@example.com")

    assert change(api_client, laptop, TEST_PASSWORD, NEW_PASSWORD).status_code == 204

    assert api_client.get("/auth/me", headers=laptop).status_code == 200  # this session stays
    assert api_client.get("/auth/me", headers=phone).status_code == 401  # others are signed out
    old = api_client.post(
        "/auth/login", json={"email": "analyst@example.com", "password": TEST_PASSWORD}
    )
    assert old.status_code == 401
    login(api_client, "analyst@example.com", NEW_PASSWORD)
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "user.password_changed")
    ).scalar_one()
    assert event.details == {"other_sessions_signed_out": 1}
    assert NEW_PASSWORD not in json.dumps(event.details)


def test_wrong_current_password_counts_as_a_failed_login(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(Role.ANALYST)
    headers = login(api_client, "analyst@example.com")

    for _ in range(5):
        wrong = change(api_client, headers, "not-my-password", NEW_PASSWORD)
        assert wrong.status_code == 400
        assert wrong.json()["detail"] == "The current password is incorrect"

    blocked = change(api_client, headers, TEST_PASSWORD, NEW_PASSWORD)
    assert (blocked.status_code, blocked.headers["Retry-After"]) == (429, "900")
    login_now = api_client.post(
        "/auth/login", json={"email": "analyst@example.com", "password": TEST_PASSWORD}
    )
    assert login_now.status_code == 429  # the same lock as the login page


@pytest.mark.parametrize(
    ("current", "new", "status"),
    [
        (TEST_PASSWORD, TEST_PASSWORD, 422),  # must differ from the current one
        (TEST_PASSWORD, "short", 422),  # under 12 characters
    ],
)
def test_new_password_rules(
    api_client: TestClient, make_user: Callable[..., User], current: str, new: str, status: int
) -> None:
    make_user(Role.ANALYST)
    headers = login(api_client, "analyst@example.com")
    assert change(api_client, headers, current, new).status_code == status


def test_change_password_needs_login(api_client: TestClient) -> None:
    assert change(api_client, {}, TEST_PASSWORD, NEW_PASSWORD).status_code == 401


def test_admin_sets_a_temporary_password_and_signs_the_user_out(
    api_client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    admin_user = make_user(Role.ADMIN)
    priya = make_user(Role.ANALYST)
    admin = login(api_client, "admin@example.com")
    priya_session = login(api_client, "analyst@example.com")

    response = api_client.post(
        f"/users/{priya.id}/password", json={"new_password": "temporary-password-1"}, headers=admin
    )

    assert response.status_code == 204
    assert api_client.get("/auth/me", headers=priya_session).status_code == 401
    login(api_client, "analyst@example.com", "temporary-password-1")
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "user.password_reset")
    ).scalar_one()
    assert (event.actor_user_id, event.entity_id, event.details) == (
        admin_user.id,
        str(priya.id),
        {"sessions_signed_out": 1},
    )


def test_only_admins_set_passwords(api_client: TestClient, make_user: Callable[..., User]) -> None:
    make_user(Role.ADMIN)
    manager = make_user(Role.MANAGER)
    manager_headers = login(api_client, "manager@example.com")
    admin = login(api_client, "admin@example.com")

    body = {"new_password": "temporary-password-1"}
    assert (
        api_client.post(
            f"/users/{manager.id}/password", json=body, headers=manager_headers
        ).status_code
        == 403
    )
    assert api_client.post("/users/999/password", json=body, headers=admin).status_code == 404
    short = api_client.post(
        f"/users/{manager.id}/password", json={"new_password": "short"}, headers=admin
    )
    assert short.status_code == 422
