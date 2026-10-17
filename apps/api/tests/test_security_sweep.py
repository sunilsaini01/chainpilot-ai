"""Every API operation against no login, a too-low role, and a cookie without CSRF token.

The table below lists who may call each operation. The first test fails when an
operation exists that the table does not know, so a new endpoint has to be
classified (and so gets these checks) before the suite passes again.
Needs RUN_DB_TESTS=1 for the users; the operations are called with dummy ids and
empty bodies, because the login and role checks run before anything else.
"""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import Role, User
from app.security_headers import API_CONTENT_POLICY, security_headers_middleware
from tests.conftest import TEST_PASSWORD, login

PUBLIC = "public"
LOGGED_IN = "logged in"  # any role
ANALYST, MANAGER, ADMIN = Role.ANALYST, Role.MANAGER, Role.ADMIN

WHO_MAY_CALL: dict[str, str | Role] = {
    "GET /health": PUBLIC,
    "GET /ready": PUBLIC,
    "POST /auth/login": PUBLIC,
    "POST /auth/logout": LOGGED_IN,
    "POST /auth/password": LOGGED_IN,
    "GET /auth/me": LOGGED_IN,
    "GET /dashboard/kpis": ANALYST,
    "GET /users": ADMIN,
    "POST /users": ADMIN,
    "PATCH /users/{user_id}": ADMIN,
    "POST /users/{user_id}/password": ADMIN,
    "GET /products": ANALYST,
    "POST /products": ADMIN,
    "GET /products/{product_id}": ANALYST,
    "PATCH /products/{product_id}": ADMIN,
    "GET /warehouses": ANALYST,
    "POST /warehouses": ADMIN,
    "GET /warehouses/{warehouse_id}": ANALYST,
    "PATCH /warehouses/{warehouse_id}": ADMIN,
    "GET /inventory": ANALYST,
    "GET /inventory/movements": ANALYST,
    "POST /inventory/movements": MANAGER,
    "GET /suppliers": ANALYST,
    "GET /suppliers/risks": ANALYST,
    "GET /purchase-orders": ANALYST,
    "GET /purchase-orders/{order_id}": ANALYST,
    "POST /purchase-orders/{order_id}/receive": MANAGER,
    "GET /inventory/risks": ANALYST,
    "POST /inventory/recommendations": MANAGER,
    "GET /inventory/recommendations": ANALYST,
    "POST /inventory/recommendations/{recommendation_id}/decision": MANAGER,
    "GET /approvals": ANALYST,
    "GET /policies": ANALYST,
    "GET /policies/search": ANALYST,
    "POST /agents/investigate": ANALYST,
    "GET /agents/runs": ANALYST,
    "GET /agents/runs/{run_id}": ANALYST,
    "GET /forecasts/runs": ANALYST,
    "GET /forecasts": ANALYST,
    "GET /delivery-risk/runs": ANALYST,
    "GET /delivery-risk/scores": ANALYST,
    "GET /delivery-risk/alerts": ANALYST,
    "GET /audit-events": MANAGER,
}
ROLE_BELOW = {MANAGER: ANALYST, ADMIN: MANAGER}


def operations() -> list[str]:
    """Every operation the API offers, from its OpenAPI schema."""
    schema = app.openapi()
    return [f"{method.upper()} {path}" for path, item in schema["paths"].items() for method in item]


def call(client: TestClient, operation: str, headers: dict[str, str] | None = None):
    method, path = operation.split(" ", 1)
    # Dummy ids: the login and role checks answer before any lookup.
    url = path.replace("{user_id}", "1").replace("{product_id}", "1")
    for name in ("{warehouse_id}", "{order_id}", "{recommendation_id}", "{run_id}"):
        url = url.replace(name, "1")
    body = None if method == "GET" else {}
    return client.request(method, url, json=body, headers=headers or {})


def test_the_table_covers_every_operation() -> None:
    assert sorted(operations()) == sorted(WHO_MAY_CALL)


@pytest.mark.parametrize("operation", [op for op, who in WHO_MAY_CALL.items() if who != PUBLIC])
def test_without_a_login_every_protected_operation_is_refused(
    api_client: TestClient, operation: str
) -> None:
    assert call(api_client, operation).status_code == 401


@pytest.fixture
def role_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[Role, dict]:
    headers = {}
    for role in (ANALYST, MANAGER):
        make_user(role)
        headers[role] = login(api_client, f"{role.value}@example.com")
    return headers


@pytest.mark.parametrize("operation", [op for op, who in WHO_MAY_CALL.items() if who in ROLE_BELOW])
def test_the_role_just_below_is_refused(
    api_client: TestClient, role_headers: dict[Role, dict], operation: str
) -> None:
    too_low = ROLE_BELOW[WHO_MAY_CALL[operation]]
    response = call(api_client, operation, role_headers[too_low])
    assert response.status_code == 403, response.text


@pytest.fixture
def admin_cookie_client(api_client: TestClient, make_user: Callable[..., User]) -> TestClient:
    """A browser-like client: logged in as admin by the cookie, no Authorization header."""
    admin = make_user(ADMIN)
    response = api_client.post(
        "/auth/login", json={"email": admin.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    return api_client


@pytest.mark.parametrize(
    "operation",
    [op for op, who in WHO_MAY_CALL.items() if who != PUBLIC and not op.startswith("GET ")],
)
def test_changes_by_cookie_without_csrf_token_are_refused(
    admin_cookie_client: TestClient, operation: str
) -> None:
    response = call(admin_cookie_client, operation)
    assert response.status_code == 403
    assert response.json()["detail"] == "Missing or invalid CSRF token"


# --- Security headers (app/security_headers.py) -------------------------------------


def test_api_answers_carry_the_security_headers(api_client: TestClient) -> None:
    for response in (api_client.get("/health"), api_client.get("/auth/me")):  # 200 and 401
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Content-Security-Policy"] == API_CONTENT_POLICY
        assert "Strict-Transport-Security" not in response.headers  # plain http locally


def test_cors_preflights_get_them_too(api_client: TestClient) -> None:
    response = api_client.options(
        "/auth/login",
        headers={
            "Origin": get_settings().cors_origin_list[0],
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_docs_pages_keep_working(api_client: TestClient) -> None:
    """Swagger UI loads scripts from a CDN, which the strict API policy would block."""
    response = api_client.get("/docs")
    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"


def test_https_deployments_also_get_strict_transport_security() -> None:
    small = FastAPI()
    small.middleware("http")(security_headers_middleware(https_only=True))
    small.get("/x")(lambda: {"ok": True})

    response = TestClient(small).get("/x")
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
