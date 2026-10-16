"""Suppliers and purchase orders: reading, on-order totals, receiving (RUN_DB_TESTS=1)."""

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import purchasing_service
from app.models import (
    AuditEvent,
    Inventory,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Supplier,
    User,
    Warehouse,
)
from app.purchasing_service import (
    PurchaseOrderNotOpenError,
    on_order_quantities,
    receive_purchase_order,
)
from tests.conftest import login


@pytest.fixture
def supplier(db_session: Session) -> Supplier:
    item = Supplier(
        code="SUP-TEST",
        name="Test Supplier",
        country="Testland",
        lead_time_days=7,
        lead_time_std_days=Decimal("1.50"),
    )
    db_session.add(item)
    db_session.commit()
    return item


@pytest.fixture
def second_product(db_session: Session) -> Product:
    item = Product(
        sku="SKU-002",
        name="Other Widget",
        category="hardware",
        unit_cost=Decimal("1.00"),
        unit_price=Decimal("2.00"),
    )
    db_session.add(item)
    db_session.commit()
    return item


def make_order(
    session: Session,
    number: str,
    supplier: Supplier,
    warehouse: Warehouse,
    lines: list[tuple[Product, int]],
    status: str = "open",
    ordered: date = date(2026, 10, 1),
) -> PurchaseOrder:
    order = PurchaseOrder(
        po_number=number,
        supplier_id=supplier.id,
        warehouse_id=warehouse.id,
        status=status,
        ordered_date=ordered,
        expected_date=date(2026, 10, 8),
        received_date=date(2026, 10, 9) if status == "received" else None,
        lines=[
            PurchaseOrderLine(product_id=product.id, quantity=quantity, unit_cost=Decimal("2.50"))
            for product, quantity in lines
        ],
    )
    session.add(order)
    session.commit()
    return order


@pytest.fixture
def open_order(
    db_session: Session,
    supplier: Supplier,
    warehouse: Warehouse,
    product: Product,
    second_product: Product,
) -> PurchaseOrder:
    return make_order(
        db_session, "PO-1", supplier, warehouse, [(product, 40), (second_product, 25)]
    )


def on_hand(session: Session, product: Product, warehouse: Warehouse) -> int:
    session.expire_all()
    row = session.execute(
        select(Inventory.on_hand).where(
            Inventory.product_id == product.id, Inventory.warehouse_id == warehouse.id
        )
    ).scalar_one_or_none()
    return row or 0


# --- On order ------------------------------------------------------------------


def test_on_order_counts_only_open_orders(
    db_session: Session,
    supplier: Supplier,
    warehouse: Warehouse,
    product: Product,
    second_product: Product,
) -> None:
    other_site = Warehouse(code="WH-TWO", name="Second", city="Elsewhere", capacity_units=1000)
    db_session.add(other_site)
    db_session.commit()
    make_order(db_session, "PO-1", supplier, warehouse, [(product, 40), (second_product, 25)])
    make_order(db_session, "PO-2", supplier, warehouse, [(product, 10)])
    make_order(db_session, "PO-3", supplier, other_site, [(product, 7)])
    make_order(db_session, "PO-4", supplier, warehouse, [(product, 99)], status="received")
    make_order(db_session, "PO-5", supplier, warehouse, [(product, 99)], status="cancelled")

    assert on_order_quantities(db_session) == {
        (product.id, warehouse.id): 50,
        (second_product.id, warehouse.id): 25,
        (product.id, other_site.id): 7,
    }
    assert on_order_quantities(db_session, warehouse_id=other_site.id) == {
        (product.id, other_site.id): 7
    }


# --- Receiving -----------------------------------------------------------------


def test_receiving_books_every_line_through_the_ledger(
    db_session: Session,
    open_order: PurchaseOrder,
    product: Product,
    second_product: Product,
    warehouse: Warehouse,
    make_user: Callable[..., User],
) -> None:
    manager = make_user(Role.MANAGER)

    order = receive_purchase_order(db_session, open_order.id, date(2026, 10, 9), manager.id)
    db_session.commit()

    assert (order.status, order.received_date, order.received_by_user_id) == (
        "received",
        date(2026, 10, 9),
        manager.id,
    )
    assert on_hand(db_session, product, warehouse) == 40
    assert on_hand(db_session, second_product, warehouse) == 25
    movements = db_session.execute(select(InventoryMovement)).scalars().all()
    assert sorted((m.quantity_change, m.reason, m.reference) for m in movements) == [
        (25, "receipt", "PO-1"),
        (40, "receipt", "PO-1"),
    ]
    assert all(m.created_by_user_id == manager.id for m in movements)
    assert on_order_quantities(db_session) == {}


def test_an_order_cannot_be_received_twice(
    db_session: Session, open_order: PurchaseOrder, product: Product, warehouse: Warehouse
) -> None:
    receive_purchase_order(db_session, open_order.id, date(2026, 10, 9), None)
    db_session.commit()

    with pytest.raises(PurchaseOrderNotOpenError, match="PO-1 is received"):
        receive_purchase_order(db_session, open_order.id, date(2026, 10, 10), None)
    db_session.rollback()
    assert on_hand(db_session, product, warehouse) == 40


def test_unknown_order_returns_none(db_session: Session) -> None:
    assert receive_purchase_order(db_session, 999, date(2026, 10, 9), None) is None


def test_two_managers_receiving_at_once_book_the_goods_once(
    db_engine: Engine,
    db_session: Session,
    open_order: PurchaseOrder,
    product: Product,
    warehouse: Warehouse,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each thread pauses (up to 1 s) before booking, waiting for the other to get
    there too. Without the order-row lock both would see "open" and both would book;
    with it, the second waits for the first to commit, then sees "received"."""
    original_record = purchasing_service.record_movement
    arrived: set[int] = set()
    both_arrived = threading.Event()
    lock = threading.Lock()

    def record_then_pause(*args, **kwargs):
        with lock:
            arrived.add(threading.get_ident())
            if len(arrived) == 2:
                both_arrived.set()
        both_arrived.wait(timeout=1.0)
        return original_record(*args, **kwargs)

    monkeypatch.setattr(purchasing_service, "record_movement", record_then_pause)
    outcomes: list[str] = []
    errors: list[Exception] = []

    def receive() -> None:
        try:
            with Session(db_engine) as session:
                receive_purchase_order(session, open_order.id, date(2026, 10, 9), None)
                session.commit()
                outcomes.append("received")
        except PurchaseOrderNotOpenError:
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
    assert on_hand(db_session, product, warehouse) == 40


# --- API -------------------------------------------------------------------------


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


@pytest.fixture
def manager_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.MANAGER)
    return login(api_client, "manager@example.com")


def test_purchasing_endpoints_need_login(api_client: TestClient) -> None:
    for path in ["/suppliers", "/purchase-orders", "/purchase-orders/1"]:
        assert api_client.get(path).status_code == 401
    assert api_client.post("/purchase-orders/1/receive").status_code == 401


def test_suppliers_and_orders_can_be_read_and_filtered(
    api_client: TestClient,
    analyst_headers: dict[str, str],
    db_session: Session,
    supplier: Supplier,
    warehouse: Warehouse,
    product: Product,
    second_product: Product,
) -> None:
    make_order(
        db_session, "PO-OLD", supplier, warehouse, [(product, 5)], "received", date(2026, 9, 1)
    )
    make_order(db_session, "PO-NEW", supplier, warehouse, [(second_product, 6)])

    suppliers = api_client.get("/suppliers", headers=analyst_headers)
    assert suppliers.status_code == 200
    assert suppliers.json()[0]["code"] == "SUP-TEST"
    assert suppliers.json()[0]["lead_time_std_days"] == "1.50"

    def numbers(**params) -> list[str]:
        response = api_client.get("/purchase-orders", params=params, headers=analyst_headers)
        assert response.status_code == 200, response.text
        return [order["po_number"] for order in response.json()]

    assert numbers() == ["PO-NEW", "PO-OLD"]  # newest first
    assert numbers(status="open") == ["PO-NEW"]
    assert numbers(product_id=product.id) == ["PO-OLD"]
    assert numbers(supplier_id=supplier.id, warehouse_id=warehouse.id) == ["PO-NEW", "PO-OLD"]
    assert numbers(warehouse_id=warehouse.id + 1) == []

    order = api_client.get("/purchase-orders", headers=analyst_headers).json()[0]
    assert order["lines"] == [{"product_id": second_product.id, "quantity": 6, "unit_cost": "2.50"}]
    assert (
        api_client.get("/purchase-orders?status=lost", headers=analyst_headers).status_code == 422
    )
    assert api_client.get("/purchase-orders/999", headers=analyst_headers).status_code == 404


def test_manager_receives_an_order_through_the_api(
    api_client: TestClient,
    manager_headers: dict[str, str],
    db_session: Session,
    open_order: PurchaseOrder,
    product: Product,
    warehouse: Warehouse,
) -> None:
    response = api_client.post(f"/purchase-orders/{open_order.id}/receive", headers=manager_headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received"
    assert response.json()["received_date"] == datetime.now(UTC).date().isoformat()
    assert on_hand(db_session, product, warehouse) == 40
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "purchase_order.received")
    ).scalar_one()
    assert event.details == {
        "po_number": "PO-1",
        "warehouse_id": warehouse.id,
        "lines": 2,
        "units": 65,
    }

    again = api_client.post(f"/purchase-orders/{open_order.id}/receive", headers=manager_headers)
    assert again.status_code == 409
    assert "not open" in again.json()["detail"]


def test_analyst_cannot_receive(
    api_client: TestClient, analyst_headers: dict[str, str], open_order: PurchaseOrder
) -> None:
    response = api_client.post(f"/purchase-orders/{open_order.id}/receive", headers=analyst_headers)
    assert response.status_code == 403


def test_receive_unknown_order_is_404(
    api_client: TestClient, manager_headers: dict[str, str]
) -> None:
    assert (
        api_client.post("/purchase-orders/999/receive", headers=manager_headers).status_code == 404
    )


def test_a_delivery_that_does_not_fit_books_nothing(
    api_client: TestClient,
    manager_headers: dict[str, str],
    db_session: Session,
    open_order: PurchaseOrder,
    product: Product,
    second_product: Product,
    warehouse: Warehouse,
) -> None:
    # 1000-unit warehouse; 960 already stored leaves room for the first line (40) but
    # not the second (25): the whole delivery must be refused, the first line included.
    filler = Product(
        sku="SKU-FILL", name="Filler", category="x", unit_cost=Decimal(1), unit_price=Decimal(1)
    )
    db_session.add(filler)
    db_session.commit()
    purchasing_service.record_movement(db_session, filler.id, warehouse.id, 960, "adjustment")
    db_session.commit()

    response = api_client.post(f"/purchase-orders/{open_order.id}/receive", headers=manager_headers)

    assert response.status_code == 409
    assert "capacity" in response.json()["detail"]
    assert on_hand(db_session, product, warehouse) == 0
    assert on_hand(db_session, second_product, warehouse) == 0
    db_session.expire_all()
    assert db_session.get(PurchaseOrder, open_order.id).status == "open"
    receipts = db_session.execute(
        select(func.count())
        .select_from(InventoryMovement)
        .where(InventoryMovement.reason == "receipt")
    ).scalar_one()
    assert receipts == 0


def test_products_show_their_purchasing_rules(
    api_client: TestClient, analyst_headers: dict[str, str], product: Product
) -> None:
    body = api_client.get(f"/products/{product.id}", headers=analyst_headers).json()
    assert (body["supplier_id"], body["min_order_qty"], body["pack_size"]) == (None, 1, 1)
