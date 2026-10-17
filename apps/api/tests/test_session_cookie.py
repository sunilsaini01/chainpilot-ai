"""The browser's login cookie and its CSRF protection (RUN_DB_TESTS=1)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import SESSION_COOKIE
from app.models import Role, User
from app.security import csrf_token_for
from tests.conftest import TEST_PASSWORD

NEW_PASSWORD = "a-brand-new-password"


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user(Role.MANAGER)


def cookie_login(client: TestClient, user: User) -> dict:
    """Log in like the dashboard: keep the cookie the API sets."""
    response = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def change_password(client: TestClient, headers: dict[str, str] | None = None):
    """A request that changes data (and works for every role)."""
    return client.post(
        "/auth/password",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers or {},
    )


def test_login_sets_an_httponly_strict_cookie(api_client: TestClient, manager: User) -> None:
    response = api_client.post(
        "/auth/login", json={"email": manager.email, "password": TEST_PASSWORD}
    )

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}={response.json()['access_token']};")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert f"Max-Age={get_settings().access_token_ttl_minutes * 60}" in cookie
    assert "Secure" not in cookie  # ENVIRONMENT=local in tests: plain http
    body = response.json()
    assert body["csrf_token"] == csrf_token_for(body["access_token"])


def test_the_cookie_is_secure_outside_local_development() -> None:
    assert Settings(environment="production").cookie_secure is True
    assert Settings(environment="local").cookie_secure is False
    assert Settings(environment="local", session_cookie_secure=True).cookie_secure is True


def test_a_wildcard_cors_origin_is_refused() -> None:
    with pytest.raises(ValueError, match="explicitly"):
        Settings(cors_origins="*")


def test_the_cookie_alone_is_enough_to_read(api_client: TestClient, manager: User) -> None:
    body = cookie_login(api_client, manager)

    me = api_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == manager.email
    # The dashboard keeps the CSRF token in memory and gets it back after a reload.
    assert me.json()["csrf_token"] == body["csrf_token"]


def test_with_the_cookie_a_change_needs_the_right_csrf_token(
    api_client: TestClient, manager: User
) -> None:
    body = cookie_login(api_client, manager)

    assert change_password(api_client).status_code == 403
    wrong = change_password(api_client, {"X-CSRF-Token": "0" * 64})
    assert wrong.status_code == 403
    assert wrong.json()["detail"] == "Missing or invalid CSRF token"
    assert change_password(api_client, {"X-CSRF-Token": body["csrf_token"]}).status_code == 204


def test_a_csrf_token_from_another_session_does_not_work(
    api_client: TestClient, manager: User, make_user: Callable[..., User]
) -> None:
    other = make_user(Role.ANALYST)
    stolen = cookie_login(api_client, other)["csrf_token"]
    cookie_login(api_client, manager)  # the browser now holds the manager's cookie

    assert change_password(api_client, {"X-CSRF-Token": stolen}).status_code == 403


def test_bearer_requests_need_no_csrf_token(api_client: TestClient, manager: User) -> None:
    token = cookie_login(api_client, manager)["access_token"]
    api_client.cookies.clear()  # a script: no cookie, only the header
    headers = {"Authorization": f"Bearer {token}"}

    assert api_client.get("/auth/me", headers=headers).json()["csrf_token"] is None
    assert change_password(api_client, headers).status_code == 204


def test_logout_revokes_the_session_and_deletes_the_cookie(
    api_client: TestClient, manager: User
) -> None:
    body = cookie_login(api_client, manager)
    old_cookie = api_client.cookies.get(SESSION_COOKIE)

    response = api_client.post("/auth/logout", headers={"X-CSRF-Token": body["csrf_token"]})

    assert response.status_code == 204
    deleted = response.headers["set-cookie"]
    assert deleted.startswith(f"{SESSION_COOKIE}=") and "Max-Age=0" in deleted
    assert api_client.cookies.get(SESSION_COOKIE) is None
    # Even if a copy of the old cookie is sent again, the session is over.
    api_client.cookies.set(SESSION_COOKIE, old_cookie)
    assert api_client.get("/auth/me").status_code == 401


def test_logout_through_the_cookie_also_needs_the_csrf_token(
    api_client: TestClient, manager: User
) -> None:
    """Otherwise another page could log a user out (a small but real CSRF)."""
    cookie_login(api_client, manager)

    assert api_client.post("/auth/logout").status_code == 403
    assert api_client.get("/auth/me").status_code == 200


def test_cors_allows_credentials_only_for_listed_origins(api_client: TestClient) -> None:
    allowed = get_settings().cors_origin_list[0]
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-CSRF-Token, Content-Type",
    }

    ok = api_client.options("/auth/logout", headers={"Origin": allowed, **preflight})
    assert ok.headers["access-control-allow-origin"] == allowed
    assert ok.headers["access-control-allow-credentials"] == "true"
    assert "x-csrf-token" in ok.headers["access-control-allow-headers"].lower()

    other = api_client.options(
        "/auth/logout", headers={"Origin": "http://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in other.headers
