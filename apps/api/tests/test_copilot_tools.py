"""Copilot tools: supplier ratings, read-only execution, every tool, citations.

Pure tests need no database; the rest need RUN_DB_TESTS=1.
"""

import os
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.copilot import tools
from app.copilot.tools import TOOLS, Tool, ToolResult, resolve_citation, run_tool, tool_specs
from app.inventory_service import record_movement
from app.models import (
    MovementReason,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Supplier,
    User,
    Warehouse,
)
from app.policies_service import sync_policies
from app.purchasing_service import rating_for, supplier_performance
from app.replenishment_service import create_recommendations, link_demand_profiles
from tests.conftest import login
from tests.test_replenishment import add_forecast_run

needs_db = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)
TODAY = date(2026, 10, 17)


# --- Pure rules ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("on_time", "received", "expected"),
    [
        (9, 10, "good"),  # exactly 90%
        (8, 10, "watch"),
        (6, 8, "watch"),  # exactly 75%
        (7, 10, "at_risk"),
        (4, 4, "not_rated"),  # fewer than 5 orders
        (0, 0, "not_rated"),
        (5, 5, "good"),
    ],
)
def test_rating_rules_follow_the_supplier_policy(
    on_time: int, received: int, expected: str
) -> None:
    assert rating_for(on_time, received) == expected


def test_every_tool_has_a_strict_schema() -> None:
    specs = tool_specs()
    assert [spec["name"] for spec in specs] == list(TOOLS)
    for spec in specs:
        assert spec["parameters"]["additionalProperties"] is False, spec["name"]
        assert spec["description"]


def test_unknown_tool_and_bad_arguments_are_messages_not_crashes() -> None:
    # No database is touched: validation happens first.
    unknown = run_tool(None, "place_order", {})
    assert not unknown.ok and "Unknown tool" in unknown.message

    for arguments, problem in [
        ({"query": "mug", "approve": True}, "approve: Extra inputs are not permitted"),
        ({"query": ""}, "query"),
        ({"query": "mug", "limit": 500}, "limit"),
    ]:
        result = run_tool(None, "find_products", arguments)
        assert not result.ok and problem in result.message
    bad_status = run_tool(None, "stock_risks", {"status": "fine"})
    assert not bad_status.ok and "status" in bad_status.message


# --- Database scenario -------------------------------------------------------------


def add_order(
    session: Session,
    number: str,
    supplier: Supplier,
    site: Warehouse,
    product: Product,
    ordered: date,
    expected: date,
    received: date | None,
) -> None:
    session.add(
        PurchaseOrder(
            po_number=number,
            supplier_id=supplier.id,
            warehouse_id=site.id,
            status="received" if received else "open",
            ordered_date=ordered,
            expected_date=expected,
            received_date=received,
            lines=[PurchaseOrderLine(product_id=product.id, quantity=10, unit_cost=Decimal(5))],
        )
    )


@pytest.fixture
def world(db_session: Session) -> dict:
    """Four suppliers with hand-made histories, one site, one product; dates near TODAY."""
    suppliers = {
        code: Supplier(
            code=code,
            name=f"Supplier {code[-1]}",
            country="X",
            lead_time_days=7,
            lead_time_std_days=Decimal("1.00"),
        )
        for code in ["SYN-SUP01", "SYN-SUP02", "SYN-SUP03", "SYN-SUP04"]
    }
    site = Warehouse(code="SYN-WH1", name="Site", city="C", capacity_units=10_000)
    db_session.add_all([*suppliers.values(), site])
    db_session.flush()
    rug = Product(
        sku="SYN-0001",
        name="Classic Rug",
        category="kitchen",
        unit_cost=Decimal(5),
        unit_price=Decimal(9),
        supplier_id=suppliers["SYN-SUP01"].id,
    )
    db_session.add(rug)
    db_session.flush()

    number = 0

    def history(code: str, on_time: int, late: int, days_late: int = 3) -> None:
        nonlocal number
        for index in range(on_time + late):
            number += 1
            ordered = TODAY - timedelta(days=60 - index)
            expected = ordered + timedelta(days=7)
            arrived = expected + timedelta(days=days_late if index >= on_time else 0)
            if code == "SYN-SUP01" and index == 0:
                arrived = expected - timedelta(days=2)  # early: on time, 0 days late (not -2)
            add_order(
                db_session,
                f"SYN-PO-{number:06d}",
                suppliers[code],
                site,
                rug,
                ordered,
                expected,
                arrived,
            )

    history("SYN-SUP01", on_time=9, late=1)  # 90% -> good, 0.3 days late on average
    history("SYN-SUP02", on_time=4, late=0)  # 4 orders -> not rated
    history("SYN-SUP03", on_time=6, late=2)  # 75% -> watch
    history("SYN-SUP04", on_time=3, late=2, days_late=10)  # 60% -> at risk
    old = TODAY - timedelta(days=120)  # outside the 90-day window: ignored
    add_order(
        db_session,
        "SYN-PO-000900",
        suppliers["SYN-SUP01"],
        site,
        rug,
        old,
        old + timedelta(7),
        old + timedelta(10),  # received 110 days ago
    )
    add_order(
        db_session,
        "SYN-PO-000901",
        suppliers["SYN-SUP04"],
        site,
        rug,
        TODAY - timedelta(10),
        TODAY - timedelta(3),
        None,
    )  # overdue
    add_order(
        db_session,
        "SYN-PO-000902",
        suppliers["SYN-SUP04"],
        site,
        rug,
        TODAY - timedelta(2),
        TODAY + timedelta(5),
        None,
    )  # not yet due
    db_session.commit()
    return {"suppliers": suppliers, "site": site, "rug": rug}


@needs_db
def test_supplier_performance_numbers(db_session: Session, world: dict) -> None:
    rows = {row.code: row for row in supplier_performance(db_session, TODAY)}

    assert (rows["SYN-SUP01"].rating, rows["SYN-SUP01"].on_time_rate) == ("good", 0.9)
    assert rows["SYN-SUP01"].received_orders == 10  # the 120-day-old order is not counted
    assert rows["SYN-SUP01"].average_days_late == 0.3
    assert rows["SYN-SUP02"].rating == "not_rated"
    assert (rows["SYN-SUP03"].rating, rows["SYN-SUP03"].on_time_rate) == ("watch", 0.75)
    assert (rows["SYN-SUP04"].rating, rows["SYN-SUP04"].average_days_late) == ("at_risk", 4.0)
    assert (rows["SYN-SUP04"].open_orders, rows["SYN-SUP04"].overdue_orders) == (
        2,
        ["SYN-PO-000901"],
    )


@needs_db
def test_tools_run_read_only_and_time_limited(
    db_engine: Engine, db_session: Session, world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def writes(session: Session, args, today: date) -> ToolResult:
        session.add(
            Supplier(
                code="SYN-HACK",
                name="x",
                country="x",
                lead_time_days=1,
                lead_time_std_days=Decimal(0),
            )
        )
        session.flush()
        return ToolResult(tool="writes", ok=True)

    def sleeps(session: Session, args, today: date) -> ToolResult:
        session.execute(text("SELECT pg_sleep(2)"))
        return ToolResult(tool="sleeps", ok=True)

    monkeypatch.setitem(
        TOOLS, "writes", Tool("writes", "x", tools.SupplierPerformanceInput, writes)
    )
    monkeypatch.setitem(
        TOOLS, "sleeps", Tool("sleeps", "x", tools.SupplierPerformanceInput, sleeps)
    )
    monkeypatch.setattr(tools, "STATEMENT_TIMEOUT", "200ms")

    with pytest.raises(DBAPIError, match="read-only transaction"):
        run_tool(db_engine, "writes", {})
    with pytest.raises(DBAPIError, match="statement timeout"):
        run_tool(db_engine, "sleeps", {})
    count = db_session.execute(
        select(func.count()).select_from(Supplier).where(Supplier.code == "SYN-HACK")
    ).scalar_one()
    assert count == 0


@needs_db
def test_every_tool_on_the_scenario_and_all_citations_resolve(
    db_engine: Engine, db_session: Session, world: dict
) -> None:
    add_forecast_run(db_session, {("HOUSEHOLD_1_001", "CA_1", "HOUSEHOLD"): 2.0})
    link_demand_profiles(db_session)
    sync_policies(db_session)
    db_session.commit()
    create_recommendations(db_session, 0.95, actor=None)
    db_session.commit()

    def call(name: str, **arguments) -> ToolResult:
        result = run_tool(db_engine, name, arguments, today=TODAY)
        assert result.ok, result.message
        return result

    products = call("find_products", query="rug")
    assert [row["sku"] for row in products.data] == ["SYN-0001"]

    risks = call("stock_risks", warehouse_code="syn-wh1")  # codes are case-insensitive
    # 2/day for 14 days = 28, plus safety stock for the 1-day lead-time spread:
    # 1.645 x 2/day x 1 day = 3.3 -> target 31.3, rounded up to 32.
    assert (risks.data[0]["status"], risks.data[0]["target_level"]) == ("out_of_stock", 32)
    assert "SIMULATED" in risks.label

    # Two open orders of 10 units are on order: 32 - 20 = 12 to order.
    recs = call("recommendations", kind="reorder")
    assert (recs.data[0]["sku"], recs.data[0]["quantity"], recs.data[0]["supplier_code"]) == (
        "SYN-0001",
        12,
        "SYN-SUP01",
    )
    assert "nothing is ordered" in recs.label

    overdue = call("purchase_orders", overdue_only=True)
    assert [row["po_number"] for row in overdue.data] == ["SYN-PO-000901"]

    suppliers = call("supplier_performance", supplier_code="SYN-SUP04")
    assert suppliers.data[0]["rating"] == "at_risk"
    assert "purchase_order:SYN-PO-000901" in suppliers.citations

    forecast = call("demand_forecast", sku="SYN-0001", warehouse_code="SYN-WH1")
    row = forecast.data[0]
    assert (row["expected_units_next_7_days"], row["expected_units_next_28_days"]) == (14.0, 56.0)
    assert len(row["daily"]) == 28
    assert not any(
        "low" in key or "high" in key for key in row if key != "daily"
    )  # no summed bounds

    policies = call("search_policies", query="supplier on-time rate")
    assert policies.citations[0] == "policy:supplier-performance#measuring-delivery-performance"

    every_citation = [
        c
        for r in [products, risks, recs, overdue, suppliers, forecast, policies]
        for c in r.citations
    ]
    assert every_citation
    unresolved = [c for c in every_citation if not resolve_citation(db_session, c)]
    assert unresolved == []


@needs_db
def test_tools_report_what_is_missing(db_engine: Engine, db_session: Session, world: dict) -> None:
    assert run_tool(db_engine, "stock_risks", {}).message.startswith("No forecast run imported")
    assert (
        run_tool(db_engine, "stock_risks", {"warehouse_code": "NOPE"}).message
        == "Unknown warehouse 'NOPE'"
    )
    assert (
        run_tool(db_engine, "find_products", {"query": "zebra"}).message
        == "No product matches 'zebra'"
    )
    assert not run_tool(db_engine, "supplier_performance", {"supplier_code": "X"}).ok
    assert (
        "link-demand-profiles"
        in run_tool(
            db_engine, "demand_forecast", {"sku": "SYN-0001", "warehouse_code": "SYN-WH1"}
        ).message
    )
    assert not run_tool(db_engine, "recommendations", {"sku": "SYN-9999"}).ok


@needs_db
@pytest.mark.parametrize(
    "citation",
    [
        "product:SYN-9999",
        "warehouse:NOPE",
        "inventory:SYN-0001@NOPE",
        "supplier:SYN-SUP99",
        "purchase_order:SYN-PO-999999",
        "recommendation:abc",
        "recommendation:999",
        "forecast_run:1",
        "policy:replenishment#no-such-section",
        "policy:replenishment",
        "made_up:thing",
        "no colon at all",
    ],
)
def test_bad_citations_do_not_resolve(db_session: Session, world: dict, citation: str) -> None:
    sync_policies(db_session)  # so a wrong section fails because of the section
    assert resolve_citation(db_session, citation) is False


@needs_db
def test_good_citations_resolve(db_session: Session, world: dict) -> None:
    sync_policies(db_session)
    for citation in [
        "product:SYN-0001",
        "warehouse:SYN-WH1",
        "inventory:SYN-0001@SYN-WH1",
        "supplier:SYN-SUP04",
        "purchase_order:SYN-PO-000901",
        "policy:replenishment#stock-status",
    ]:
        assert resolve_citation(db_session, citation), citation


# --- API -------------------------------------------------------------------------


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


@needs_db
def test_supplier_risks_api_worst_first(
    api_client: TestClient, analyst_headers: dict[str, str], db_session: Session, world: dict
) -> None:
    assert api_client.get("/suppliers/risks").status_code == 401
    # The endpoint rates the 90 days before the real today; move the history there.
    shift = (date.today() - TODAY).days
    db_session.execute(
        text(
            "UPDATE purchase_orders SET ordered_date = ordered_date + :d, "
            "expected_date = expected_date + :d, received_date = received_date + :d"
        ),
        {"d": shift},
    )
    db_session.commit()

    rows = api_client.get("/suppliers/risks", headers=analyst_headers).json()

    assert [(row["code"], row["rating"]) for row in rows] == [
        ("SYN-SUP04", "at_risk"),
        ("SYN-SUP03", "watch"),
        ("SYN-SUP01", "good"),
        ("SYN-SUP02", "not_rated"),
    ]
    assert rows[0]["overdue_orders"] == ["SYN-PO-000901"]


@needs_db
def test_record_movement_still_works_outside_tools(db_session: Session, world: dict) -> None:
    # The read-only setting belongs to the tool's own transaction only.
    record_movement(db_session, world["rug"].id, world["site"].id, 5, MovementReason.RECEIPT)
    db_session.commit()
