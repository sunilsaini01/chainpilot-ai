"""Inventory API tests: stock levels, movements, roles, idempotency (RUN_DB_TESTS=1)."""

import threading
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import inventory_service
from app.inventory_service import IdempotencyConflictError, record_movement_once
from app.models import AuditEvent, InventoryMovement, MovementReason, Product, Role, User, Warehouse
from tests.conftest import login


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user(Role.MANAGER)


@pytest.fixture
def manager_headers(api_client: TestClient, manager: User) -> dict[str, str]:
    return login(api_client, manager.email)


def movement(product: Product, warehouse: Warehouse, quantity: int, reason: str = "receipt"):
    return {
        "product_id": product.id,
        "warehouse_id": warehouse.id,
        "quantity_change": quantity,
        "reason": reason,
        "reference": "PO-1",
    }


def count_movements(session: Session) -> int:
    return session.execute(select(func.count()).select_from(InventoryMovement)).scalar_one()


def test_manager_records_movement_with_actor_and_audit(
    api_client: TestClient,
    db_session: Session,
    manager: User,
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    response = api_client.post(
        "/inventory/movements", json=movement(product, warehouse, 40), headers=manager_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["balance_after"], body["created_by_user_id"]) == (40, manager.id)
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "inventory.movement_recorded")
    ).scalar_one()
    assert event.actor_user_id == manager.id
    assert event.details["quantity_change"] == 40


def test_analyst_cannot_record_movements(
    api_client: TestClient,
    make_user: Callable[..., User],
    product: Product,
    warehouse: Warehouse,
) -> None:
    make_user(Role.ANALYST)
    headers = login(api_client, "analyst@example.com")

    response = api_client.post(
        "/inventory/movements", json=movement(product, warehouse, 5), headers=headers
    )

    assert response.status_code == 403


def test_overselling_is_409_and_changes_nothing(
    api_client: TestClient,
    db_session: Session,
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    api_client.post(
        "/inventory/movements", json=movement(product, warehouse, 3), headers=manager_headers
    )

    response = api_client.post(
        "/inventory/movements",
        json=movement(product, warehouse, -4, "sale"),
        headers=manager_headers,
    )

    assert response.status_code == 409
    assert "Insufficient stock: 3 on hand" in response.json()["detail"]
    assert count_movements(db_session) == 1


@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ({"product_id": 999_999}, 404),
        ({"warehouse_id": 999_999}, 404),
        ({"quantity_change": 0}, 422),
        ({"quantity_change": 2_000_000}, 422),
        ({"reason": "gift"}, 422),
    ],
)
def test_invalid_movements(
    api_client: TestClient,
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
    change: dict,
    expected_status: int,
) -> None:
    body = {**movement(product, warehouse, 5), **change}

    response = api_client.post("/inventory/movements", json=body, headers=manager_headers)

    assert response.status_code == expected_status


def test_retry_with_same_idempotency_key_applies_stock_once(
    api_client: TestClient,
    db_session: Session,
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    headers = {**manager_headers, "Idempotency-Key": "order-42"}
    body = movement(product, warehouse, 10)

    first = api_client.post("/inventory/movements", json=body, headers=headers)
    retry = api_client.post("/inventory/movements", json=body, headers=headers)

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json()["id"] == first.json()["id"]
    assert count_movements(db_session) == 1
    stock = api_client.get("/inventory", headers=manager_headers).json()
    assert stock[0]["on_hand"] == 10


def test_same_key_for_a_different_change_is_409(
    api_client: TestClient,
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    headers = {**manager_headers, "Idempotency-Key": "order-43"}
    api_client.post("/inventory/movements", json=movement(product, warehouse, 10), headers=headers)

    response = api_client.post(
        "/inventory/movements", json=movement(product, warehouse, 11), headers=headers
    )

    assert response.status_code == 409
    assert "different stock change" in response.json()["detail"]


def test_concurrent_requests_with_same_key_apply_once(
    db_engine: Engine,
    db_session: Session,
    manager: User,
    product: Product,
    warehouse: Warehouse,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two retries arrive together and both see "key not used yet".

    The first lookup in each thread waits until both threads have done it, so
    both really try to insert and the unique constraint decides. Without the
    race handling in record_movement_once, the losing thread would crash.
    """
    both_looked_up = threading.Barrier(2, timeout=10)
    per_thread = threading.local()
    original_find = inventory_service._find_by_key

    def find_then_wait(session: Session, key: str):
        found = original_find(session, key)
        if not getattr(per_thread, "waited", False):
            per_thread.waited = True
            both_looked_up.wait()
        return found

    monkeypatch.setattr(inventory_service, "_find_by_key", find_then_wait)
    results: list[tuple[int, bool]] = []
    errors: list[Exception] = []

    def send() -> None:
        try:
            with Session(db_engine) as session:
                created_movement, created = record_movement_once(
                    session,
                    "race-key",
                    product.id,
                    warehouse.id,
                    7,
                    MovementReason.RECEIPT,
                    "PO-9",
                    manager.id,
                )
                session.commit()
                results.append((created_movement.id, created))
        except Exception as error:  # surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]  # both got the same movement
    assert count_movements(db_session) == 1


def test_idempotency_conflict_at_service_level(
    db_session: Session, manager: User, product: Product, warehouse: Warehouse
) -> None:
    record_movement_once(
        db_session, "k1", product.id, warehouse.id, 5, MovementReason.RECEIPT, None, manager.id
    )
    db_session.commit()

    with pytest.raises(IdempotencyConflictError):
        record_movement_once(
            db_session,
            "k1",
            product.id,
            warehouse.id,
            5,
            MovementReason.RECEIPT,
            "other",
            manager.id,
        )


def test_inventory_listing_filters_and_low_stock(
    api_client: TestClient,
    db_session: Session,
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    other = Warehouse(code="WH-B", name="B", city="B", capacity_units=100)
    db_session.add(other)
    db_session.commit()
    api_client.post(
        "/inventory/movements", json=movement(product, warehouse, 50), headers=manager_headers
    )
    api_client.post(
        "/inventory/movements", json=movement(product, other, 3), headers=manager_headers
    )

    def rows(**params) -> list[tuple[str, int]]:
        response = api_client.get("/inventory", params=params, headers=manager_headers)
        assert response.status_code == 200
        return [(row["warehouse_code"], row["on_hand"]) for row in response.json()]

    assert rows() == [("WH-B", 3), ("WH-TEST", 50)]  # ordered by warehouse code
    assert rows(warehouse_id=warehouse.id) == [("WH-TEST", 50)]
    assert rows(max_on_hand=5) == [("WH-B", 3)]  # low stock
    assert rows(product_id=999_999) == []


def test_movement_history_endpoint_newest_first(
    api_client: TestClient,
    make_user: Callable[..., User],
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    for quantity, reason in [(10, "receipt"), (-3, "sale"), (-2, "adjustment")]:
        api_client.post(
            "/inventory/movements",
            json=movement(product, warehouse, quantity, reason),
            headers=manager_headers,
        )
    make_user(Role.ANALYST)
    analyst = login(api_client, "analyst@example.com")

    response = api_client.get(
        "/inventory/movements",
        params={"product_id": product.id, "warehouse_id": warehouse.id},
        headers=analyst,
    )

    assert response.status_code == 200
    assert [m["balance_after"] for m in response.json()] == [5, 7, 10]


def test_same_key_from_another_user_is_409(
    api_client: TestClient,
    make_user: Callable[..., User],
    manager_headers: dict[str, str],
    product: Product,
    warehouse: Warehouse,
) -> None:
    body = movement(product, warehouse, 10)
    first = api_client.post(
        "/inventory/movements", json=body, headers={**manager_headers, "Idempotency-Key": "k-9"}
    )
    other = make_user(Role.MANAGER, email="other.manager@example.com")
    other_headers = {**login(api_client, other.email), "Idempotency-Key": "k-9"}

    second = api_client.post("/inventory/movements", json=body, headers=other_headers)

    assert first.status_code == 201
    assert second.status_code == 409  # not someone else's movement handed back
