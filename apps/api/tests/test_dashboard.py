"""Dashboard KPIs and CORS for the web app (P6-T1). Needs RUN_DB_TESTS=1."""

import os
from collections.abc import Callable
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.inventory_service import record_movement
from app.models import MovementReason, Role, User
from app.replenishment_service import create_recommendations, link_demand_profiles
from tests.conftest import TODAY, login
from tests.test_replenishment import add_forecast_run

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)
WEB = "http://localhost:5173"


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


def test_kpis_need_login(api_client: TestClient) -> None:
    assert api_client.get("/dashboard/kpis").status_code == 401


def test_kpis_on_an_empty_database(api_client: TestClient, analyst_headers: dict[str, str]) -> None:
    body = api_client.get("/dashboard/kpis", headers=analyst_headers).json()

    assert body["inventory"] == {
        "products": 0,
        "warehouses": 0,
        "units_on_hand": 0,
        "stock_value": 0,
    }
    assert body["stock_status"] is None
    assert "import-forecasts" in body["stock_status_note"]
    assert body["pending_recommendations"] == {"reorder": 0, "transfer": 0}
    assert body["purchase_orders"] == {"open": 0, "overdue": 0}
    assert "SIMULATED" in body["label"]


def test_kpis_match_the_detailed_services(
    api_client: TestClient, analyst_headers: dict[str, str], db_session: Session, world: dict
) -> None:
    # Move the hand-made order history to today, so "overdue" and the 90-day window match.
    shift = (date.today() - TODAY).days
    db_session.execute(
        text(
            "UPDATE purchase_orders SET ordered_date = ordered_date + :d, "
            "expected_date = expected_date + :d, received_date = received_date + :d"
        ),
        {"d": shift},
    )
    record_movement(db_session, world["rug"].id, world["site"].id, 4, MovementReason.RECEIPT)
    add_forecast_run(db_session, {("HOUSEHOLD_1_001", "CA_1", "HOUSEHOLD"): 2.0})
    link_demand_profiles(db_session)
    db_session.commit()
    create_recommendations(db_session, 0.95, actor=None)
    db_session.commit()

    body = api_client.get("/dashboard/kpis", headers=analyst_headers).json()

    # 4 rugs at 5.00 each. Position 4 on hand + 20 on order = 24, above the reorder point
    # (14) but below the target (32): status ok, and one order-up-to reorder is proposed.
    assert body["inventory"] == {
        "products": 1,
        "warehouses": 1,
        "units_on_hand": 4,
        "stock_value": 20.0,
    }
    assert body["stock_status"] == {
        "out_of_stock": 0,
        "at_risk": 0,
        "ok": 1,
        "excess": 0,
        "unassessed": 0,
    }
    assert body["forecast_run_id"] is not None
    assert body["purchase_orders"] == {"open": 2, "overdue": 1}
    assert body["supplier_ratings"] == {"good": 1, "watch": 1, "at_risk": 1, "not_rated": 1}
    assert sum(body["pending_recommendations"].values()) == 1


def test_cors_allows_only_the_web_app(
    api_client: TestClient, analyst_headers: dict[str, str]
) -> None:
    preflight = api_client.options(
        "/dashboard/kpis",
        headers={
            "Origin": WEB,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == WEB

    response = api_client.get("/products", headers={**analyst_headers, "Origin": WEB})
    assert response.headers["access-control-allow-origin"] == WEB
    assert "X-Total-Count" in response.headers["access-control-expose-headers"]

    other = api_client.get(
        "/products", headers={**analyst_headers, "Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in other.headers
