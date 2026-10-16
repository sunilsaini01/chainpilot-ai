"""Stock-out risks and recommendations. Pure planning tests need no database;
the scenario tests need RUN_DB_TESTS=1. Expected numbers are worked out by hand."""

import hashlib
import os
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory_service import record_movement
from app.models import (
    AuditEvent,
    Forecast,
    ForecastRun,
    MovementReason,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Recommendation,
    Role,
    Supplier,
    User,
    Warehouse,
)
from app.replenishment_service import (
    ItemInputs,
    NoForecastRunError,
    assess,
    assess_all,
    create_recommendations,
    daily_demand,
    free_space,
    link_demand_profiles,
    plan_replenishment,
    protection_days,
)
from tests.conftest import login

needs_db = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)
WIDTH_FOR_STD_1 = 2 * 1.2815516  # an 80% interval this wide means a daily std of 1


def item(
    product: int = 1,
    site: int = 1,
    on_hand: int = 0,
    on_order: int = 0,
    mean: float = 2.0,
    std: float = 0.0,
    lead: int = 7,
    lead_std: float = 0.0,
    supplier: int | None = 1,
    moq: int = 1,
    pack: int = 1,
) -> ItemInputs:
    return ItemInputs(
        product_id=product,
        sku=f"SYN-{product:04d}",
        warehouse_id=site,
        warehouse_code=f"SYN-WH{site}",
        supplier_id=supplier,
        on_hand=on_hand,
        on_order=on_order,
        daily_mean=mean,
        daily_std=std,
        lead_time_days=lead,
        lead_time_std=lead_std,
        min_order_qty=moq,
        pack_size=pack,
        demand_profile="X at Y",
    )


# --- Pure rules ------------------------------------------------------------------


def test_daily_demand_from_the_forecast_rows() -> None:
    rows = [(step, 2.0, 0.0, WIDTH_FOR_STD_1) for step in range(1, 29)]
    mean, std = daily_demand(rows, 14)
    assert mean == 2 and std == pytest.approx(1, abs=1e-4)

    # Std 1 for 7 days, std 2 for 7 days -> root mean square sqrt(2.5); later steps ignored.
    rows = [(s, 1.0, 0.0, WIDTH_FOR_STD_1 * (1 if s <= 7 else 2)) for s in range(1, 15)]
    rows.append((15, 999.0, 0.0, 999.0))
    assert daily_demand(rows, 14) == (1.0, pytest.approx(2.5**0.5, abs=1e-4))

    with pytest.raises(ValueError, match="steps 1 to 14"):
        daily_demand(rows[1:], 14)


def test_protection_days_must_fit_in_the_forecast() -> None:
    assert (protection_days(7), protection_days(21)) == (14, 28)
    with pytest.raises(ValueError, match="forecasts cover 28"):
        protection_days(22)


def test_assessment_worked_example() -> None:
    # Same numbers as the P4-T1 example: 10/day (std 3), lead 7 days (std 2), 95%.
    result = assess(item(on_hand=40, on_order=60, mean=10, std=3, lead_std=2), 0.95)

    assert result.position == 100
    assert result.reorder_point == pytest.approx(105.39, abs=0.01)
    assert (result.target_level, result.shortfall, result.status) == (178, 78, "at_risk")
    assert result.days_of_cover == 4


@pytest.mark.parametrize(
    ("on_hand", "on_order", "mean", "expected"),
    [
        (0, 200, 2.0, "out_of_stock"),  # nothing on the shelf, whatever is on order
        (13, 0, 2.0, "at_risk"),  # reorder point 2 x 7 = 14
        (14, 0, 2.0, "ok"),
        (148, 0, 2.0, "ok"),  # target 28 + 60 days x 2 = 148
        (149, 0, 2.0, "excess"),
        (0, 0, 0.0, "ok"),  # no stock and no demand
        (5, 0, 0.0, "excess"),  # stock that is not expected to sell
    ],
)
def test_status_rules(on_hand: int, on_order: int, mean: float, expected: str) -> None:
    assert assess(item(on_hand=on_hand, on_order=on_order, mean=mean), 0.95).status == expected


def test_no_demand_means_no_days_of_cover() -> None:
    assert assess(item(on_hand=5, mean=0.0), 0.95).days_of_cover is None


def test_spare_stock_is_transferred_before_ordering() -> None:
    # Product 1: site 1 is empty (target 28), site 2 holds 100 (target 28, spare 72).
    short = assess(item(site=1, on_hand=0), 0.95)
    donor = assess(item(site=2, on_hand=100), 0.95)

    plan = plan_replenishment([donor, short], {1: 1000, 2: 1000})

    assert [
        (d.inputs.warehouse_id, r.inputs.warehouse_id, units) for d, r, units in plan.transfers
    ] == [(2, 1, 28)]
    assert plan.reorders == []


def test_partial_transfer_then_order_with_supplier_rules() -> None:
    # Spare stock covers 10 of 28; the remaining 18 is raised to whole packs of 12 -> 24.
    short = assess(item(site=1, on_hand=0, pack=12), 0.95)
    donor = assess(item(site=2, on_hand=38, pack=12), 0.95)

    plan = plan_replenishment([short, donor], {1: 1000, 2: 1000})

    assert [units for _, _, units in plan.transfers] == [10]
    assert [(r.inputs.warehouse_id, units, why) for r, units, why in plan.reorders] == [
        (1, 24, "ordered")
    ]


def test_a_short_site_never_gives_stock_away() -> None:
    first = assess(item(site=1, on_hand=0), 0.95)
    second = assess(item(site=2, on_hand=10), 0.95)  # at risk itself (10 < 14)

    plan = plan_replenishment([first, second], {1: 1000, 2: 1000})

    assert plan.transfers == []
    assert sorted((r.inputs.warehouse_id, units) for r, units, _ in plan.reorders) == [
        (1, 28),
        (2, 18),
    ]


def test_tiny_shortfall_is_raised_to_the_minimum_order() -> None:
    # Position 25 is above the reorder point (14) but below the target (28): the
    # order-up-to rule orders 3, raised to the supplier's minimum of 24 (P4-T2-R3).
    plan = plan_replenishment([assess(item(on_hand=25, moq=24), 0.95)], {1: 1000})
    assert [(units, why) for _, units, why in plan.reorders] == [(24, "raised_to_moq")]


def test_free_space_is_shared_most_urgent_first() -> None:
    urgent = assess(item(product=1, on_hand=0), 0.95)  # out of stock, needs 28
    later = assess(item(product=2, on_hand=10), 0.95)  # at risk, needs 18

    plan = plan_replenishment([later, urgent], {1: 40})

    assert [(r.inputs.product_id, units, why) for r, units, why in plan.reorders] == [
        (1, 28, "ordered"),
        (2, 12, "limited"),
    ]


def test_a_transfer_is_limited_by_space_at_the_receiving_site() -> None:
    short = assess(item(site=1, on_hand=0), 0.95)
    donor = assess(item(site=2, on_hand=100), 0.95)

    plan = plan_replenishment([short, donor], {1: 10, 2: 1000})

    assert [units for _, _, units in plan.transfers] == [10]
    assert [b.inputs.warehouse_id for b in plan.blocked] == [1]  # no room left to order


def test_status_ranks_before_days_of_cover() -> None:
    # 1 on hand + 20 on order is "ok" (position 21, reorder point 14) with only 0.5 days
    # of cover, and wants 7 more to reach 28. 10 on hand is "at risk" (5 days of cover)
    # and wants 18. With room for 18 units, the at-risk item must be served first.
    covered = assess(item(product=1, on_hand=1, on_order=20), 0.95)
    exposed = assess(item(product=2, on_hand=10), 0.95)
    assert (covered.status, exposed.status) == ("ok", "at_risk")
    assert covered.days_of_cover < exposed.days_of_cover

    plan = plan_replenishment([covered, exposed], {1: 18})

    assert [(r.inputs.product_id, units) for r, units, _ in plan.reorders] == [(2, 18)]
    assert [b.inputs.product_id for b in plan.blocked] == [1]


def test_items_without_supplier_or_space_are_blocked() -> None:
    no_supplier = assess(item(product=1, on_hand=0, supplier=None), 0.95)
    no_room = assess(item(product=2, on_hand=0, pack=12), 0.95)

    plan = plan_replenishment([no_supplier, no_room], {1: 11})

    assert plan.reorders == []
    assert [b.inputs.product_id for b in plan.blocked] == [1, 2]


# --- Database scenario -------------------------------------------------------------


def add_forecast_run(
    session: Session, series: dict[tuple[str, str, str], float], run_key: str = "testrun"
) -> ForecastRun:
    """A forecast run with 28 flat steps per (item, store, category): forecast = interval."""
    run = ForecastRun(
        run_key=run_key,
        name="test",
        dataset="M5 test rows",
        model="test",
        trained_through=date(2016, 4, 24),
        forecast_start=date(2016, 4, 25),
        forecast_end=date(2016, 5, 22),
        horizon_days=28,
        series_count=len(series),
        row_count=28 * len(series),
        manifest={},
    )
    session.add(run)
    session.flush()
    for (item_id, store, category), level in series.items():
        for step in range(1, 29):
            session.add(
                Forecast(
                    run_id=run.id,
                    series_id=f"{item_id}_{store}_validation",
                    store_id=store,
                    item_id=item_id,
                    dept_id=item_id.rsplit("_", 1)[0],
                    cat_id=category,
                    forecast_date=date(2016, 4, 24) + timedelta(days=step),
                    step=step,
                    forecast=level,
                    lower=level,
                    upper=level,
                )
            )
    session.commit()
    return run


@pytest.fixture
def scenario(db_session: Session) -> dict:
    """Two SYN- sites; SYN-0001 empty at WH1 with spare at WH2; SYN-0002 short at both;
    one unlinked non-SYN product. Lead time 7 days, no variation; flat forecasts."""
    supplier = Supplier(
        code="SYN-SUP01", name="S", country="X", lead_time_days=7, lead_time_std_days=Decimal(0)
    )
    db_session.add(supplier)
    db_session.flush()
    sites = [
        Warehouse(code=f"SYN-WH{n}", name=f"Site {n}", city="C", capacity_units=10_000)
        for n in (1, 2)
    ]
    rug = Product(
        sku="SYN-0001",
        name="Rug",
        category="kitchen",
        unit_cost=Decimal(5),
        unit_price=Decimal(9),
        supplier_id=supplier.id,
    )
    kite = Product(
        sku="SYN-0002",
        name="Kite",
        category="office",
        unit_cost=Decimal(3),
        unit_price=Decimal(6),
        supplier_id=supplier.id,
        min_order_qty=12,
        pack_size=6,
    )
    # Not a SYN- product, although its category is mapped: must never be linked.
    other = Product(
        sku="SKU-X", name="X", category="kitchen", unit_cost=Decimal(1), unit_price=Decimal(2)
    )
    db_session.add_all([*sites, rug, kite, other])
    db_session.flush()
    record_movement(db_session, rug.id, sites[1].id, 100, MovementReason.RECEIPT)
    record_movement(db_session, kite.id, sites[0].id, 5, MovementReason.RECEIPT)
    db_session.add(
        PurchaseOrder(
            po_number="PO-OPEN",
            supplier_id=supplier.id,
            warehouse_id=sites[0].id,
            status="open",
            ordered_date=date(2026, 10, 10),
            expected_date=date(2026, 10, 17),
            lines=[PurchaseOrderLine(product_id=kite.id, quantity=1, unit_cost=Decimal(3))],
        )
    )
    db_session.commit()
    run = add_forecast_run(
        db_session,
        {
            ("HOUSEHOLD_1_001", "CA_1", "HOUSEHOLD"): 2.0,
            ("HOUSEHOLD_1_001", "TX_1", "HOUSEHOLD"): 2.0,
            ("HOBBIES_1_001", "CA_1", "HOBBIES"): 1.0,
            ("HOBBIES_1_001", "TX_1", "HOBBIES"): 1.0,
        },
    )
    return {"sites": sites, "rug": rug, "kite": kite, "other": other, "run": run}


@needs_db
def test_no_forecast_run_is_a_clear_error(db_session: Session) -> None:
    with pytest.raises(NoForecastRunError):
        link_demand_profiles(db_session)
    with pytest.raises(NoForecastRunError):
        assess_all(db_session, 0.95)


@needs_db
def test_demand_profiles_are_linked_deterministically_and_never_overwritten(
    db_session: Session, scenario: dict
) -> None:
    other_household = ("HOUSEHOLD_2_005", "CA_1", "HOUSEHOLD")
    add_forecast_run(
        db_session,
        {other_household: 1.0, ("HOUSEHOLD_1_001", "CA_1", "HOUSEHOLD"): 1.0},
        run_key="newer",
    )

    summary = link_demand_profiles(db_session)
    db_session.commit()

    candidates = sorted(["HOUSEHOLD_1_001", "HOUSEHOLD_2_005"])  # from the newest run
    digest = int(hashlib.sha256(b"SYN-0001").hexdigest(), 16)
    assert scenario["rug"].demand_profile_item_id == candidates[digest % 2]
    assert scenario["kite"].demand_profile_item_id is None  # no HOBBIES item in the newest run
    assert scenario["other"].demand_profile_item_id is None  # not a SYN- product
    assert [site.demand_profile_store_id for site in scenario["sites"]] == ["CA_1", None]
    assert summary["products"] == 1 and summary["warehouses"] == 1

    scenario["rug"].demand_profile_item_id = "MY_CHOICE"
    scenario["sites"][0].demand_profile_store_id = "MY_STORE"
    db_session.commit()
    link_demand_profiles(db_session)
    assert scenario["rug"].demand_profile_item_id == "MY_CHOICE"
    assert scenario["sites"][0].demand_profile_store_id == "MY_STORE"


@needs_db
def test_scenario_risks_and_recommendations(db_session: Session, scenario: dict) -> None:
    link_demand_profiles(db_session)
    db_session.commit()
    wh1, wh2 = (site.id for site in scenario["sites"])
    rug, kite = scenario["rug"].id, scenario["kite"].id

    _, assessments, unassessed = assess_all(db_session, 0.95)

    # Rug 2/day: reorder point 14, target 28. Kite 1/day: reorder point 7, target 14.
    assert [
        (a.inputs.product_id, a.inputs.warehouse_id, a.status, a.position) for a in assessments
    ] == [
        (rug, wh1, "out_of_stock", 0),
        (kite, wh2, "out_of_stock", 0),
        (kite, wh1, "at_risk", 6),  # 5 on hand + 1 on order
        (rug, wh2, "ok", 100),
    ]
    assert unassessed == 2  # SKU-X at both sites

    created, summary = create_recommendations(db_session, 0.95, actor=None)
    db_session.commit()

    assert [
        (r.kind, r.product_id, r.source_warehouse_id, r.warehouse_id, r.quantity, r.reason)
        for r in created
    ] == [
        ("transfer", rug, wh2, wh1, 28, "transfer_spare_stock"),
        ("reorder", kite, None, wh2, 18, "ordered"),  # 14 -> 3 packs of 6
        ("reorder", kite, None, wh1, 12, "raised_to_moq"),  # 8 -> minimum 12
    ]
    assert created[1].details["item"]["target_level"] == 14
    assert summary == {
        "assessed": 4,
        "unassessed": 2,
        "transfers": 1,
        "reorders": 2,
        "blocked": 0,
        "superseded": 0,
    }
    event = db_session.execute(select(AuditEvent)).scalar_one()
    assert (event.action, event.details["reorders"]) == ("recommendations.generated", 2)

    # A second run replaces the pending set.
    _, second = create_recommendations(db_session, 0.95, actor=None)
    db_session.commit()
    statuses = db_session.execute(select(Recommendation.status)).scalars().all()
    assert second["superseded"] == 3 and sorted(statuses).count("pending") == 3
    # Only pending ones are superseded; older superseded ones are left alone.
    _, third = create_recommendations(db_session, 0.95, actor=None)
    assert third["superseded"] == 3


@needs_db
def test_free_space_subtracts_stock_and_open_orders(db_session: Session, scenario: dict) -> None:
    wh1, wh2 = (site.id for site in scenario["sites"])
    # WH1: 10,000 - 5 on hand - 1 on order; WH2: 10,000 - 100 on hand.
    assert free_space(db_session) == {wh1: 9994, wh2: 9900}


# --- API -------------------------------------------------------------------------


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


@pytest.fixture
def manager_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.MANAGER)
    return login(api_client, "manager@example.com")


@needs_db
def test_endpoints_need_login(api_client: TestClient) -> None:
    assert api_client.get("/inventory/risks").status_code == 401
    assert api_client.get("/inventory/recommendations").status_code == 401
    assert api_client.post("/inventory/recommendations", json={}).status_code == 401


@needs_db
def test_risks_without_a_forecast_run_is_409(
    api_client: TestClient, analyst_headers: dict[str, str]
) -> None:
    response = api_client.get("/inventory/risks", headers=analyst_headers)
    assert response.status_code == 409
    assert "import-forecasts" in response.json()["detail"]


@needs_db
def test_risks_api_is_labelled_filtered_and_paged(
    api_client: TestClient, analyst_headers: dict[str, str], db_session: Session, scenario: dict
) -> None:
    link_demand_profiles(db_session)
    db_session.commit()

    response = api_client.get("/inventory/risks", headers=analyst_headers)
    assert response.status_code == 200, response.text
    assert response.headers["X-Total-Count"] == "4"
    assert response.headers["X-Unassessed-Count"] == "2"
    assert "SIMULATED" in response.headers["X-Dataset"]
    first = response.json()[0]
    assert (first["sku"], first["status"], first["target_level"]) == (
        "SYN-0001",
        "out_of_stock",
        28,
    )
    assert first["demand_profile"] == "HOUSEHOLD_1_001 at CA_1"

    at_risk = api_client.get("/inventory/risks?status=at_risk", headers=analyst_headers).json()
    assert [row["sku"] for row in at_risk] == ["SYN-0002"]
    page = api_client.get("/inventory/risks?limit=1&offset=1", headers=analyst_headers)
    assert [row["sku"] for row in page.json()] == ["SYN-0002"] and page.headers[
        "X-Total-Count"
    ] == "4"
    assert api_client.get("/inventory/risks?status=bad", headers=analyst_headers).status_code == 422
    assert (
        api_client.get("/inventory/risks?service_level=1", headers=analyst_headers).status_code
        == 422
    )


@needs_db
def test_only_managers_generate_recommendations(
    api_client: TestClient,
    analyst_headers: dict[str, str],
    manager_headers: dict[str, str],
    db_session: Session,
    scenario: dict,
) -> None:
    link_demand_profiles(db_session)
    db_session.commit()

    assert (
        api_client.post("/inventory/recommendations", json={}, headers=analyst_headers).status_code
        == 403
    )
    response = api_client.post(
        "/inventory/recommendations", json={"service_level": 0.95}, headers=manager_headers
    )
    assert response.status_code == 201, response.text
    assert [(r["kind"], r["quantity"], r["status"]) for r in response.json()] == [
        ("transfer", 28, "pending"),
        ("reorder", 18, "pending"),
        ("reorder", 12, "pending"),
    ]
    listed = api_client.get("/inventory/recommendations?kind=reorder", headers=analyst_headers)
    assert [r["quantity"] for r in listed.json()] == [18, 12]
    assert listed.headers["X-Total-Count"] == "2"
    # Proposals only: no purchase order was created and no stock moved.
    assert len(db_session.execute(select(PurchaseOrder)).scalars().all()) == 1
