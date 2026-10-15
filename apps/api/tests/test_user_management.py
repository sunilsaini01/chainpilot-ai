"""Tests for changing users (PATCH /users/{id}) and the audit trail (RUN_DB_TESTS=1)."""

import threading
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Role, User
from app.users_service import LastAdminError, update_user
from tests.conftest import TEST_PASSWORD, login


def audit_actions(session: Session) -> list[str]:
    return list(session.execute(select(AuditEvent.action).order_by(AuditEvent.id)).scalars())


def test_admin_can_promote_a_user_and_it_is_audited(
    api_client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    analyst = make_user(Role.ANALYST)
    headers = login(api_client, admin.email)

    response = api_client.patch(f"/users/{analyst.id}", json={"role": "manager"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["role"] == "manager"
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "user.updated")
    ).scalar_one()
    assert event.actor_user_id == admin.id
    assert event.entity_type == "user"
    assert event.entity_id == str(analyst.id)
    assert event.details == {"changes": {"role": ["analyst", "manager"]}}


def test_unchanged_patch_writes_no_audit_event(
    api_client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    analyst = make_user(Role.ANALYST)
    headers = login(api_client, admin.email)

    response = api_client.patch(f"/users/{analyst.id}", json={"role": "analyst"}, headers=headers)

    assert response.status_code == 200
    assert "user.updated" not in audit_actions(db_session)


def test_deactivated_user_is_locked_out_immediately(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    analyst = make_user(Role.ANALYST)
    admin_headers = login(api_client, admin.email)
    analyst_headers = login(api_client, analyst.email)

    response = api_client.patch(
        f"/users/{analyst.id}", json={"is_active": False}, headers=admin_headers
    )

    assert response.status_code == 200
    assert api_client.get("/auth/me", headers=analyst_headers).status_code == 401
    failed = api_client.post(
        "/auth/login", json={"email": analyst.email, "password": TEST_PASSWORD}
    )
    assert failed.status_code == 401


@pytest.mark.parametrize("change", [{"role": "manager"}, {"is_active": False}])
def test_last_admin_cannot_demote_or_deactivate_themselves(
    api_client: TestClient, make_user: Callable[..., User], change: dict
) -> None:
    admin = make_user(Role.ADMIN)
    headers = login(api_client, admin.email)

    response = api_client.patch(f"/users/{admin.id}", json=change, headers=headers)

    assert response.status_code == 409
    assert response.json() == {"detail": "Cannot remove the last active admin"}


def test_admin_can_be_demoted_when_another_admin_exists(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    other_admin = make_user(Role.ADMIN, email="admin2@example.com")
    headers = login(api_client, admin.email)

    response = api_client.patch(
        f"/users/{other_admin.id}", json={"role": "analyst"}, headers=headers
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("path_user", "body", "expected_status"),
    [("missing", {"role": "manager"}, 404), ("analyst", {"full_name": "   "}, 422)],
)
def test_patch_errors(
    api_client: TestClient,
    make_user: Callable[..., User],
    path_user: str,
    body: dict,
    expected_status: int,
) -> None:
    admin = make_user(Role.ADMIN)
    analyst = make_user(Role.ANALYST)
    user_id = 999_999 if path_user == "missing" else analyst.id
    headers = login(api_client, admin.email)

    assert api_client.patch(f"/users/{user_id}", json=body, headers=headers).status_code == (
        expected_status
    )


def test_non_admin_cannot_change_users(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    manager = make_user(Role.MANAGER)
    headers = login(api_client, manager.email)

    response = api_client.patch(f"/users/{manager.id}", json={"role": "admin"}, headers=headers)

    assert response.status_code == 403  # no self-promotion


def test_two_admins_demoting_each_other_at_once_leaves_one_admin(
    db_engine: Engine, db_session: Session, make_user: Callable[..., User]
) -> None:
    """Without the row lock both demotions could pass the check, leaving zero admins."""
    first = make_user(Role.ADMIN, email="first@example.com")
    second = make_user(Role.ADMIN, email="second@example.com")
    start_together = threading.Barrier(2)
    outcomes: list[str] = []

    def demote(target_id: int) -> None:
        with Session(db_engine) as session:
            target = session.get(User, target_id)
            start_together.wait()
            try:
                update_user(session, target, role=Role.ANALYST)
                session.commit()
                outcomes.append("demoted")
            except LastAdminError:
                session.rollback()
                outcomes.append("refused")

    threads = [threading.Thread(target=demote, args=(user.id,)) for user in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["demoted", "refused"]
    admins = db_session.execute(select(User).where(User.role == "admin")).scalars().all()
    assert len(admins) == 1


def test_login_logout_and_user_creation_are_audited_without_secrets(
    api_client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    headers = login(api_client, admin.email)
    api_client.post(
        "/users",
        json={
            "email": "new@example.com",
            "full_name": "New",
            "role": "analyst",
            "password": "brand-new-password",
        },
        headers=headers,
    )
    api_client.post("/auth/logout", headers=headers)

    assert audit_actions(db_session) == ["user.login", "user.created", "user.logout"]
    created = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "user.created")
    ).scalar_one()
    assert created.details == {"email": "new@example.com", "role": "analyst"}
    all_details = str(db_session.execute(select(AuditEvent.details)).scalars().all())
    assert "password" not in all_details
    assert headers["Authorization"].split()[1] not in all_details


@pytest.mark.parametrize(("role", "expected_status"), [(Role.ANALYST, 403), (Role.MANAGER, 200)])
def test_audit_events_are_visible_to_managers_and_up(
    api_client: TestClient, make_user: Callable[..., User], role: Role, expected_status: int
) -> None:
    user = make_user(role)
    headers = login(api_client, user.email)

    assert api_client.get("/audit-events", headers=headers).status_code == expected_status


def test_audit_events_can_be_filtered_and_are_newest_first(
    api_client: TestClient, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    analyst = make_user(Role.ANALYST)
    headers = login(api_client, admin.email)
    api_client.patch(f"/users/{analyst.id}", json={"role": "manager"}, headers=headers)
    api_client.patch(f"/users/{analyst.id}", json={"full_name": "Renamed"}, headers=headers)

    response = api_client.get(
        "/audit-events",
        params={"entity_type": "user", "entity_id": str(analyst.id)},
        headers=headers,
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["action"] for event in events] == ["user.updated", "user.updated"]
    assert "full_name" in events[0]["details"]["changes"]  # newest first
    assert "role" in events[1]["details"]["changes"]
