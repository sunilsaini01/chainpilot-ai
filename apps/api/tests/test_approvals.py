"""Approval workflow: decisions, execution, idempotency and concurrency (RUN_DB_TESTS=1)."""

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import approval_service
from app.approval_service import AlreadyDecidedError, decide
from app.inventory_service import record_movement
from app.models import (
    Approval,
    ApprovalDecision,
    AuditEvent,
    ForecastRun,
    Inventory,
    InventoryMovement,
    MovementReason,
    Product,
    PurchaseOrder,
    Recommendation,
    Role,
    Supplier,
    User,
    Warehouse,
)
from app.purchasing_service import on_order_quantities
from app.replenishment_service import create_recommendations
from tests.conftest import login

TODAY = date(2026, 10, 17)


@pytest.fixture
def world(db_session: Session) -> dict:
    """A supplier (7 days), one product, site A with 50 units, site B (room for 100),
    and two pending recommendations for site B: reorder 20, transfer 30 from A."""
    supplier = Supplier(
        code="SUP-A", name="S", country="X", lead_time_days=7, lead_time_std_days=Decimal(0)
    )
    db_session.add(supplier)
    db_session.flush()
    product = Product(
        sku="SKU-A",
        name="Widget",
        category="hardware",
        unit_cost=Decimal("2.50"),
        unit_price=Decimal("4.00"),
        supplier_id=supplier.id,
    )
    site_a = Warehouse(code="WH-A", name="A", city="C", capacity_units=1000)
    site_b = Warehouse(code="WH-B", name="B", city="C", capacity_units=100)
    run = ForecastRun(
        run_key="r",
        name="r",
        dataset="test",
        model="test",
        trained_through=date(2016, 4, 24),
        forecast_start=date(2016, 4, 25),
        forecast_end=date(2016, 5, 22),
        horizon_days=28,
        series_count=0,
        row_count=0,
        manifest={},
    )
    db_session.add_all([product, site_a, site_b, run])
    db_session.flush()
    record_movement(db_session, product.id, site_a.id, 50, MovementReason.RECEIPT)
    common = {
        "product_id": product.id,
        "warehouse_id": site_b.id,
        "forecast_run_id": run.id,
        "service_level": Decimal("0.95"),
        "reason": "test",
        "details": {},
    }
    reorder = Recommendation(kind="reorder", supplier_id=supplier.id, quantity=20, **common)
    transfer = Recommendation(kind="transfer", source_warehouse_id=site_a.id, quantity=30, **common)
    db_session.add_all([reorder, transfer])
    db_session.commit()
    return {
        "product": product,
        "site_a": site_a,
        "site_b": site_b,
        "reorder": reorder,
        "transfer": transfer,
    }


def on_hand(session: Session, product: Product, site: Warehouse) -> int:
    """Read straight from the database (other sessions may have changed it)."""
    session.expire_all()
    units = session.execute(
        select(Inventory.on_hand).where(
            Inventory.product_id == product.id, Inventory.warehouse_id == site.id
        )
    ).scalar_one_or_none()
    return units or 0


def count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user(Role.MANAGER)


# --- Service ---------------------------------------------------------------------


def test_approving_a_reorder_places_an_open_order(
    db_session: Session, world: dict, manager: User
) -> None:
    result = decide(
        db_session, world["reorder"].id, ApprovalDecision.APPROVED, None, manager, "k1", TODAY
    )
    db_session.commit()

    order = db_session.get(PurchaseOrder, result.approval.purchase_order_id)
    assert order.po_number == f"PO-REC-{world['reorder'].id:06d}"
    assert (order.status, order.warehouse_id) == ("open", world["site_b"].id)
    assert (order.ordered_date, order.expected_date) == (TODAY, TODAY + timedelta(days=7))
    assert [(line.product_id, line.quantity, line.unit_cost) for line in order.lines] == [
        (world["product"].id, 20, Decimal("2.50"))
    ]
    # Counts as "on order" for the next risk assessment.
    assert on_order_quantities(db_session)[(world["product"].id, world["site_b"].id)] == 20
    assert world["reorder"].status == "executed"
    assert (result.approval.outcome, result.approval.decided_by_user_id) == ("executed", manager.id)
    actions = db_session.execute(select(AuditEvent.action)).scalars().all()
    assert sorted(actions) == ["purchase_order.created", "recommendation.approved"]


def test_approving_a_transfer_moves_the_stock(
    db_session: Session, world: dict, manager: User
) -> None:
    result = decide(
        db_session, world["transfer"].id, ApprovalDecision.APPROVED, None, manager, "k1", TODAY
    )
    db_session.commit()

    assert on_hand(db_session, world["product"], world["site_a"]) == 20
    assert on_hand(db_session, world["product"], world["site_b"]) == 30
    moves = db_session.execute(
        select(InventoryMovement).where(InventoryMovement.reason != "receipt")
    ).scalars()
    legs = sorted((m.reason, m.quantity_change, m.reference, m.created_by_user_id) for m in moves)
    assert legs == [
        ("transfer_in", 30, f"REC-{world['transfer'].id}", manager.id),
        ("transfer_out", -30, f"REC-{world['transfer'].id}", manager.id),
    ]
    assert result.approval.outcome == "executed"
    assert result.approval.purchase_order_id is None
    assert world["transfer"].status == "executed"


def test_a_transfer_without_the_stock_fails_and_changes_nothing(
    db_session: Session, world: dict, manager: User
) -> None:
    # Since the recommendation was made, site A sold 40 of its 50 units.
    record_movement(db_session, world["product"].id, world["site_a"].id, -40, MovementReason.SALE)
    db_session.commit()

    result = decide(
        db_session, world["transfer"].id, ApprovalDecision.APPROVED, None, manager, "k1", TODAY
    )
    db_session.commit()

    assert result.approval.outcome == "failed"
    assert "Insufficient stock: 10 on hand" in result.approval.outcome_details["error"]
    assert world["transfer"].status == "failed"
    assert on_hand(db_session, world["product"], world["site_a"]) == 10
    assert on_hand(db_session, world["product"], world["site_b"]) == 0


def test_a_transfer_into_a_full_site_fails_and_changes_nothing(
    db_session: Session, world: dict, manager: User
) -> None:
    world["site_b"].capacity_units = 20  # room for 20, transfer of 30
    db_session.commit()

    result = decide(
        db_session, world["transfer"].id, ApprovalDecision.APPROVED, None, manager, "k1", TODAY
    )
    db_session.commit()

    assert result.approval.outcome == "failed"
    assert "capacity exceeded" in result.approval.outcome_details["error"]
    # The first leg (out of site A) was undone with the second.
    assert on_hand(db_session, world["product"], world["site_a"]) == 50
    assert count(db_session, InventoryMovement) == 1  # only the opening receipt


def test_rejecting_needs_a_reason_and_creates_nothing(
    db_session: Session, world: dict, manager: User
) -> None:
    with pytest.raises(approval_service.ReasonRequiredError):
        decide(
            db_session, world["reorder"].id, ApprovalDecision.REJECTED, None, manager, "k1", TODAY
        )
    result = decide(
        db_session,
        world["reorder"].id,
        ApprovalDecision.REJECTED,
        "Supplier is on hold",
        manager,
        "k2",
        TODAY,
    )
    db_session.commit()

    assert (result.approval.decision, result.approval.outcome) == ("rejected", None)
    assert world["reorder"].status == "rejected"
    assert count(db_session, PurchaseOrder) == 0


def test_a_new_recommendation_run_replaces_only_pending_ones(
    db_session: Session, world: dict, manager: User
) -> None:
    decide(db_session, world["reorder"].id, ApprovalDecision.APPROVED, None, manager, "k1", TODAY)
    db_session.commit()

    create_recommendations(db_session, 0.95, manager)
    db_session.commit()

    db_session.refresh(world["reorder"])
    db_session.refresh(world["transfer"])
    assert (world["reorder"].status, world["transfer"].status) == ("executed", "superseded")


def test_two_managers_approving_at_once_act_once(
    db_engine: Engine,
    db_session: Session,
    world: dict,
    make_user: Callable[..., User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each request pauses (up to 1 s) after taking the row lock, waiting for the
    other to get there too. Without the lock both would see "pending" and act;
    with it, the second waits for the first to commit, then sees "executed"."""
    users = [make_user(Role.MANAGER), make_user(Role.ADMIN)]
    original_find = approval_service.find_approval
    arrived: set[int] = set()
    both_arrived = threading.Event()
    lock = threading.Lock()

    def find_then_pause(*args, **kwargs):
        with lock:
            arrived.add(threading.get_ident())
            if len(arrived) == 2:
                both_arrived.set()
        both_arrived.wait(timeout=1.0)
        return original_find(*args, **kwargs)

    monkeypatch.setattr(approval_service, "find_approval", find_then_pause)
    outcomes: list[str] = []
    errors: list[Exception] = []

    def approve(user_id: int, key: str) -> None:
        try:
            with Session(db_engine) as session:
                actor = session.get(User, user_id)
                decide(
                    session,
                    world["transfer"].id,
                    ApprovalDecision.APPROVED,
                    None,
                    actor,
                    key,
                    TODAY,
                )
                session.commit()
                outcomes.append("approved")
        except AlreadyDecidedError:
            outcomes.append("refused")
        except Exception as error:  # surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=approve, args=(user.id, f"key-{user.id}")) for user in users]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(outcomes) == ["approved", "refused"]
    assert on_hand(db_session, world["product"], world["site_b"]) == 30  # moved once
    assert count(db_session, Approval) == 1


# --- API -------------------------------------------------------------------------


@pytest.fixture
def manager_headers(api_client: TestClient, manager: User) -> dict[str, str]:
    return login(api_client, manager.email)


def decision_url(recommendation: Recommendation) -> str:
    return f"/inventory/recommendations/{recommendation.id}/decision"


def post_decision(
    client: TestClient,
    recommendation: Recommendation,
    headers: dict[str, str],
    key: str = "key-1",
    **body: str,
):
    return client.post(
        decision_url(recommendation),
        json=body or {"decision": "approve"},
        headers={**headers, "Idempotency-Key": key},
    )


def test_deciding_needs_a_manager_and_a_key(
    api_client: TestClient,
    world: dict,
    make_user: Callable[..., User],
    manager_headers: dict[str, str],
) -> None:
    url = decision_url(world["reorder"])
    approve = {"decision": "approve"}
    assert api_client.post(url, json=approve, headers={"Idempotency-Key": "k"}).status_code == 401

    make_user(Role.ANALYST)
    analyst = {**login(api_client, "analyst@example.com"), "Idempotency-Key": "k"}
    assert api_client.post(url, json=approve, headers=analyst).status_code == 403

    assert api_client.post(url, json=approve, headers=manager_headers).status_code == 422
    missing = api_client.post(
        "/inventory/recommendations/9999/decision",
        json=approve,
        headers={**manager_headers, "Idempotency-Key": "k"},
    )
    assert missing.status_code == 404
    assert api_client.get("/approvals").status_code == 401


def test_approve_through_the_api_and_list_the_decision(
    api_client: TestClient, world: dict, manager: User, manager_headers: dict[str, str]
) -> None:
    response = post_decision(api_client, world["reorder"], manager_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["decision"], body["outcome"]) == ("approved", "executed")
    assert body["decided_by_email"] == manager.email
    assert body["outcome_details"]["po_number"] == f"PO-REC-{world['reorder'].id:06d}"
    today = datetime.now(UTC).date()
    assert body["outcome_details"]["expected_date"] == (today + timedelta(days=7)).isoformat()

    listed = api_client.get("/approvals", headers=manager_headers)
    assert listed.headers["X-Total-Count"] == "1"
    assert listed.json()[0]["decided_by_email"] == manager.email
    executed = api_client.get(
        "/inventory/recommendations", params={"status": "executed"}, headers=manager_headers
    )
    assert [r["id"] for r in executed.json()] == [world["reorder"].id]


def test_a_retry_with_the_same_key_returns_the_stored_decision(
    api_client: TestClient, db_session: Session, world: dict, manager_headers: dict[str, str]
) -> None:
    first = post_decision(api_client, world["reorder"], manager_headers)
    retry = post_decision(api_client, world["reorder"], manager_headers)

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json() == first.json()
    assert count(db_session, PurchaseOrder) == 1


def test_a_key_used_for_another_decision_is_refused(
    api_client: TestClient, db_session: Session, world: dict, manager_headers: dict[str, str]
) -> None:
    assert post_decision(api_client, world["reorder"], manager_headers).status_code == 201

    other = post_decision(api_client, world["transfer"], manager_headers)
    assert other.status_code == 409
    assert "Idempotency-Key" in other.json()["detail"]
    db_session.refresh(world["transfer"])
    assert world["transfer"].status == "pending"


def test_a_decided_or_superseded_recommendation_cannot_be_decided_again(
    api_client: TestClient, db_session: Session, world: dict, manager_headers: dict[str, str]
) -> None:
    assert post_decision(api_client, world["reorder"], manager_headers).status_code == 201

    again = post_decision(
        api_client, world["reorder"], manager_headers, key="key-2", decision="reject", comment="x"
    )
    assert again.status_code == 409
    assert "is executed, not pending" in again.json()["detail"]

    world["transfer"].status = "superseded"
    db_session.commit()
    late = post_decision(api_client, world["transfer"], manager_headers, key="key-3")
    assert late.status_code == 409
    assert count(db_session, Approval) == 1


def test_rejecting_through_the_api_needs_a_real_reason(
    api_client: TestClient, world: dict, manager_headers: dict[str, str]
) -> None:
    blank = post_decision(
        api_client, world["reorder"], manager_headers, decision="reject", comment="   "
    )
    assert blank.status_code == 422

    rejected = post_decision(
        api_client,
        world["reorder"],
        manager_headers,
        key="key-2",
        decision="reject",
        comment="  Too expensive  ",
    )
    assert rejected.status_code == 201
    assert (rejected.json()["comment"], rejected.json()["outcome"]) == ("Too expensive", None)
