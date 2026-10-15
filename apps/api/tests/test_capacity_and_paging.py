"""Warehouse capacity rules and X-Total-Count paging (RUN_DB_TESTS=1)."""

import threading
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import inventory_service
from app.inventory_service import WarehouseCapacityError, record_movement, warehouse_stock_total
from app.models import MovementReason, Product, Role, User, Warehouse
from tests.conftest import login


@pytest.fixture
def small_warehouse(db_session: Session) -> Warehouse:
    site = Warehouse(code="WH-SMALL", name="Small", city="Hull", capacity_units=100)
    db_session.add(site)
    db_session.commit()
    return site


@pytest.fixture
def manager_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.MANAGER)
    return login(api_client, "manager@example.com")


def post_movement(
    client: TestClient,
    headers: dict[str, str],
    product: Product,
    site: Warehouse,
    quantity: int,
    reason: str,
) -> int:
    body = {
        "product_id": product.id,
        "warehouse_id": site.id,
        "quantity_change": quantity,
        "reason": reason,
    }
    return client.post("/inventory/movements", json=body, headers=headers).status_code


def test_receipt_up_to_capacity_is_allowed_and_beyond_is_409(
    api_client: TestClient,
    db_session: Session,
    manager_headers: dict[str, str],
    product: Product,
    small_warehouse: Warehouse,
) -> None:
    assert (
        post_movement(api_client, manager_headers, product, small_warehouse, 100, "receipt") == 201
    )

    response = api_client.post(
        "/inventory/movements",
        json={
            "product_id": product.id,
            "warehouse_id": small_warehouse.id,
            "quantity_change": 1,
            "reason": "receipt",
        },
        headers=manager_headers,
    )

    assert response.status_code == 409
    assert "100 of 100 units used, 1 more requested" in response.json()["detail"]
    assert warehouse_stock_total(db_session, small_warehouse.id) == 100


def test_capacity_counts_all_products_and_selling_frees_space(
    db_session: Session, product: Product, small_warehouse: Warehouse
) -> None:
    other = Product(sku="OTHER-1", name="Other", category="x", unit_cost=1, unit_price=2)
    db_session.add(other)
    db_session.commit()
    record_movement(db_session, product.id, small_warehouse.id, 70, MovementReason.RECEIPT)

    with pytest.raises(WarehouseCapacityError):
        record_movement(db_session, other.id, small_warehouse.id, 31, MovementReason.TRANSFER_IN)

    record_movement(db_session, product.id, small_warehouse.id, -10, MovementReason.SALE)
    record_movement(db_session, other.id, small_warehouse.id, 40, MovementReason.TRANSFER_IN)
    assert warehouse_stock_total(db_session, small_warehouse.id) == 100


def test_positive_adjustment_may_exceed_capacity(
    db_session: Session, product: Product, small_warehouse: Warehouse
) -> None:
    # A stock count found more units than expected: the ledger must record reality.
    record_movement(db_session, product.id, small_warehouse.id, 100, MovementReason.RECEIPT)
    record_movement(db_session, product.id, small_warehouse.id, 5, MovementReason.ADJUSTMENT)

    assert warehouse_stock_total(db_session, small_warehouse.id) == 105


def test_concurrent_receipts_cannot_overfill_together(
    db_engine: Engine,
    db_session: Session,
    product: Product,
    small_warehouse: Warehouse,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two receipts of 60 into a 100-unit warehouse: exactly one may succeed.

    After reading the current total, each thread pauses (up to 1 s) for the other
    to read it too. Without the warehouse row lock both would read 0 and both
    succeed; with the lock the second thread cannot read until the first commits.
    """
    original_total = inventory_service.warehouse_stock_total
    arrivals = []
    both_read = threading.Event()
    arrivals_lock = threading.Lock()

    def total_then_pause(session: Session, warehouse_id: int) -> int:
        total = original_total(session, warehouse_id)
        with arrivals_lock:
            arrivals.append(total)
            if len(arrivals) == 2:
                both_read.set()
        both_read.wait(timeout=1.0)
        return total

    monkeypatch.setattr(inventory_service, "warehouse_stock_total", total_then_pause)
    outcomes: list[str] = []
    errors: list[Exception] = []

    def receive() -> None:
        try:
            with Session(db_engine) as session:
                record_movement(session, product.id, small_warehouse.id, 60, MovementReason.RECEIPT)
                session.commit()
                outcomes.append("received")
        except WarehouseCapacityError:
            outcomes.append("refused")
        except Exception as error:  # surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=receive) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(outcomes) == ["received", "refused"]
    assert original_total(db_session, small_warehouse.id) == 60


def test_capacity_cannot_be_lowered_below_current_stock(
    api_client: TestClient,
    db_session: Session,
    make_user: Callable[..., User],
    product: Product,
    small_warehouse: Warehouse,
) -> None:
    record_movement(db_session, product.id, small_warehouse.id, 80, MovementReason.RECEIPT)
    db_session.commit()
    make_user(Role.ADMIN)
    headers = login(api_client, "admin@example.com")
    url = f"/warehouses/{small_warehouse.id}"

    too_small = api_client.patch(url, json={"capacity_units": 79}, headers=headers)
    just_enough = api_client.patch(url, json={"capacity_units": 80}, headers=headers)

    assert too_small.status_code == 409
    assert "80 units currently stored" in too_small.json()["detail"]
    assert just_enough.status_code == 200


def test_list_endpoints_report_total_count(
    api_client: TestClient,
    db_session: Session,
    make_user: Callable[..., User],
    product: Product,
    small_warehouse: Warehouse,
) -> None:
    make_user(Role.ADMIN)
    make_user(Role.ANALYST)
    headers = login(api_client, "admin@example.com")
    for number in range(3):
        db_session.add(
            Product(sku=f"EXTRA-{number}", name="Extra", category="x", unit_cost=1, unit_price=2)
        )
    db_session.commit()
    record_movement(db_session, product.id, small_warehouse.id, 5, MovementReason.RECEIPT)
    db_session.commit()

    def total(path: str, **params) -> str:
        response = api_client.get(path, params={"limit": 1, **params}, headers=headers)
        assert response.status_code == 200
        assert len(response.json()) <= 1  # the page is limited, the total is not
        return response.headers["X-Total-Count"]

    assert total("/products") == "4"
    assert total("/products", search="extra") == "3"  # filters apply to the count
    assert total("/warehouses") == "1"  # only WH-SMALL exists in this test
    assert total("/inventory") == "1"
    assert total("/users") == "2"
    assert int(total("/audit-events")) >= 1  # at least the admin's login
