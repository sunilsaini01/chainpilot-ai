"""Stock movement tests against a throwaway PostgreSQL database (RUN_DB_TESTS=1)."""

import random
import threading
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.inventory_service import InsufficientStockError, movement_history, record_movement
from app.models import Inventory, InventoryMovement, MovementReason, Product, Role, Warehouse


def on_hand(session: Session, product: Product, warehouse: Warehouse) -> int:
    return session.execute(
        select(Inventory.on_hand).where(
            Inventory.product_id == product.id, Inventory.warehouse_id == warehouse.id
        )
    ).scalar_one()


def movement_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(InventoryMovement)).scalar_one()


def test_first_receipt_creates_inventory_row_and_ledger_entry(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    movement = record_movement(
        db_session, product.id, warehouse.id, 50, MovementReason.RECEIPT, reference="PO-1001"
    )
    db_session.commit()

    assert on_hand(db_session, product, warehouse) == 50
    assert movement.balance_after == 50
    assert movement.reason == "receipt"
    assert movement.reference == "PO-1001"
    assert movement.created_at is not None


def test_sale_reduces_stock(db_session: Session, product: Product, warehouse: Warehouse) -> None:
    record_movement(db_session, product.id, warehouse.id, 10, MovementReason.RECEIPT)
    movement = record_movement(db_session, product.id, warehouse.id, -3, MovementReason.SALE)
    db_session.commit()

    assert on_hand(db_session, product, warehouse) == 7
    assert movement.balance_after == 7


def test_overselling_is_rejected_and_changes_nothing(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    record_movement(db_session, product.id, warehouse.id, 5, MovementReason.RECEIPT)
    db_session.commit()

    with pytest.raises(InsufficientStockError) as error:
        record_movement(db_session, product.id, warehouse.id, -6, MovementReason.SALE)
    db_session.rollback()

    assert error.value.available == 5
    assert error.value.requested_change == -6
    assert on_hand(db_session, product, warehouse) == 5
    assert movement_count(db_session) == 1  # only the receipt


def test_ledger_always_adds_up_to_on_hand(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    changes = [
        (100, MovementReason.RECEIPT),
        (-30, MovementReason.SALE),
        (-20, MovementReason.TRANSFER_OUT),
        (15, MovementReason.TRANSFER_IN),
        (-2, MovementReason.ADJUSTMENT),
    ]
    for quantity_change, reason in changes:
        record_movement(db_session, product.id, warehouse.id, quantity_change, reason)
    db_session.commit()

    ledger_total = db_session.execute(
        select(func.sum(InventoryMovement.quantity_change))
    ).scalar_one()
    assert ledger_total == on_hand(db_session, product, warehouse) == 63


def test_zero_quantity_is_rejected(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    with pytest.raises(ValueError, match="must not be zero"):
        record_movement(db_session, product.id, warehouse.id, 0, MovementReason.ADJUSTMENT)


def test_unknown_reason_is_rejected(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    with pytest.raises(ValueError):
        record_movement(db_session, product.id, warehouse.id, 5, "gift")  # type: ignore[arg-type]


def test_unknown_product_is_rejected_by_foreign_key(
    db_session: Session, warehouse: Warehouse
) -> None:
    with pytest.raises(IntegrityError):
        record_movement(db_session, 999_999, warehouse.id, 5, MovementReason.RECEIPT)


def test_database_refuses_negative_stock_even_without_the_service(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    record_movement(db_session, product.id, warehouse.id, 1, MovementReason.RECEIPT)
    db_session.commit()

    with pytest.raises(IntegrityError, match="ck_inventory_on_hand_non_negative"):
        db_session.execute(text("UPDATE inventory SET on_hand = -1"))


def test_duplicate_sku_is_rejected(db_session: Session, product: Product) -> None:
    db_session.add(
        Product(
            sku=product.sku,
            name="Copy",
            category="hardware",
            unit_cost=Decimal("1.00"),
            unit_price=Decimal("2.00"),
        )
    )
    with pytest.raises(IntegrityError, match="uq_products_sku"):
        db_session.commit()


def test_concurrent_sales_cannot_oversell_the_last_unit(
    db_engine: Engine, db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    """Two checkouts race for the last unit: exactly one must win."""
    record_movement(db_session, product.id, warehouse.id, 1, MovementReason.RECEIPT)
    db_session.commit()

    start_together = threading.Barrier(2)
    outcomes: list[str] = []

    def try_to_sell() -> None:
        with Session(db_engine) as session:
            start_together.wait()
            try:
                record_movement(session, product.id, warehouse.id, -1, MovementReason.SALE)
                session.commit()
                outcomes.append("sold")
            except InsufficientStockError:
                session.rollback()
                outcomes.append("out_of_stock")

    threads = [threading.Thread(target=try_to_sell) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["out_of_stock", "sold"]
    assert on_hand(db_session, product, warehouse) == 0


def test_history_is_newest_first_even_within_one_transaction(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    # All three movements share one transaction, so they get the same created_at.
    record_movement(db_session, product.id, warehouse.id, 10, MovementReason.RECEIPT)
    record_movement(db_session, product.id, warehouse.id, -4, MovementReason.SALE)
    record_movement(db_session, product.id, warehouse.id, 1, MovementReason.ADJUSTMENT)
    db_session.commit()

    history = movement_history(db_session, product.id, warehouse.id)

    assert len({movement.created_at for movement in history}) == 1  # same timestamp
    assert [movement.balance_after for movement in history] == [7, 6, 10]


def test_history_tie_break_uses_id_not_storage_order(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    # 20 movements with one identical timestamp, physically stored in shuffled id
    # order. Without the `id` tie-breaker PostgreSQL may return ties in any order,
    # so a lucky pass is practically impossible. Fixed seed keeps it repeatable.
    ids = list(range(1, 21))
    random.Random(42).shuffle(ids)
    for movement_id in ids:
        db_session.execute(
            text(
                "INSERT INTO inventory_movements (id, product_id, warehouse_id, quantity_change,"
                " balance_after, reason, created_at)"
                " VALUES (:id, :product_id, :warehouse_id, 1, 1, 'adjustment', '2026-01-01')"
            ),
            {"id": movement_id, "product_id": product.id, "warehouse_id": warehouse.id},
        )
    db_session.commit()

    history = movement_history(db_session, product.id, warehouse.id)

    assert [movement.id for movement in history] == list(range(20, 0, -1))


def test_history_respects_limit_and_rejects_bad_limit(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    for _ in range(3):
        record_movement(db_session, product.id, warehouse.id, 1, MovementReason.RECEIPT)
    db_session.commit()

    latest_two = movement_history(db_session, product.id, warehouse.id, limit=2)

    assert [movement.balance_after for movement in latest_two] == [3, 2]
    with pytest.raises(ValueError, match="at least 1"):
        movement_history(db_session, product.id, warehouse.id, limit=0)


def test_updated_at_changes_on_raw_sql_update(db_session: Session, product: Product) -> None:
    # Even if an UPDATE tries to set an old timestamp, the trigger replaces it with now().
    db_session.execute(
        text("UPDATE products SET name = 'Renamed', updated_at = '2000-01-01' WHERE id = :id"),
        {"id": product.id},
    )
    db_session.commit()

    updated_at = db_session.execute(
        text("SELECT updated_at FROM products WHERE id = :id"), {"id": product.id}
    ).scalar_one()
    assert updated_at.year > 2000
    assert updated_at >= product.created_at


def test_orm_sees_database_updated_at_after_update(
    db_session: Session, warehouse: Warehouse
) -> None:
    before = warehouse.updated_at
    warehouse.name = "Renamed Warehouse"
    db_session.commit()

    # FetchedValue makes the ORM reload updated_at, which the trigger set.
    assert warehouse.updated_at > before


def test_movement_records_the_acting_user(
    db_session: Session, product: Product, warehouse: Warehouse, make_user
) -> None:
    manager = make_user(Role.MANAGER)

    movement = record_movement(
        db_session, product.id, warehouse.id, 5, MovementReason.RECEIPT, actor_user_id=manager.id
    )
    db_session.commit()

    assert movement.created_by_user_id == manager.id


def test_movement_with_unknown_actor_is_rejected(
    db_session: Session, product: Product, warehouse: Warehouse
) -> None:
    with pytest.raises(IntegrityError, match="fk_inventory_movements_created_by_user_id_users"):
        record_movement(
            db_session, product.id, warehouse.id, 5, MovementReason.RECEIPT, actor_user_id=999_999
        )
