"""Unit tests for /health and /ready. These do not need a running database."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.database import get_engine
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_database_answers(client: TestClient) -> None:
    # An in-memory SQLite engine stands in for Postgres: it answers SELECT 1.
    app.dependency_overrides[get_engine] = lambda: create_engine("sqlite://")

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_ready_returns_503_when_database_is_unreachable(client: TestClient) -> None:
    # Port 1 on localhost refuses connections, simulating Postgres being down.
    unreachable = URL.create(
        "postgresql+psycopg",
        username="nobody",
        password="secret-value",
        host="127.0.0.1",
        port=1,
        database="missing",
    )
    app.dependency_overrides[get_engine] = lambda: create_engine(
        unreachable, connect_args={"connect_timeout": 1}
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    # Connection details must not leak to API clients.
    assert "secret-value" not in response.text
    assert "nobody" not in response.text


def test_openapi_docs_list_health_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/health" in paths
    assert "/ready" in paths
