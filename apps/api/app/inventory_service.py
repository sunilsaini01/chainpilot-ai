"""The only place where stock levels change.

Each call locks the inventory row, checks the new balance, updates `on_hand`
and appends a movement, all inside the caller's transaction. The caller decides
when to commit, so several movements (for example, both sides of a transfer)
can succeed or fail together.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Inventory, InventoryMovement, MovementReason, Product, Warehouse


class InsufficientStockError(Exception):
    """Raised when a movement would make stock negative."""

    def __init__(self, available: int, requested_change: int) -> None:
        self.available = available
        self.requested_change = requested_change
        super().__init__(
            f"Insufficient stock: {available} on hand, change of {requested_change} requested"
        )


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused for a different stock change."""


class WarehouseCapacityError(Exception):
    """Raised when a receipt or incoming transfer would overfill a warehouse."""

    def __init__(self, capacity: int, current_total: int, requested_change: int) -> None:
        self.capacity = capacity
        self.current_total = current_total
        self.requested_change = requested_change
        super().__init__(
            f"Warehouse capacity exceeded: {current_total} of {capacity} units used, "
            f"{requested_change} more requested"
        )


# Movements that bring goods in through the door and so must fit in the building.
# Positive adjustments are exempt: a stock count records what is physically there.
CAPACITY_CHECKED_REASONS = {MovementReason.RECEIPT, MovementReason.TRANSFER_IN}


def warehouse_stock_total(session: Session, warehouse_id: int) -> int:
    """Total units on hand across all products in one warehouse."""
    return session.execute(
        select(func.coalesce(func.sum(Inventory.on_hand), 0)).where(
            Inventory.warehouse_id == warehouse_id
        )
    ).scalar_one()


def check_capacity(session: Session, warehouse_id: int, quantity_change: int) -> None:
    """Raise WarehouseCapacityError if adding `quantity_change` units would overfill the site.

    Locks the warehouse row first, so two receipts into the same warehouse are
    checked one after the other and cannot both fit "the last free space".
    """
    warehouse = session.execute(
        select(Warehouse).where(Warehouse.id == warehouse_id).with_for_update()
    ).scalar_one_or_none()
    if warehouse is None:
        return  # the foreign key reports the unknown warehouse
    current_total = warehouse_stock_total(session, warehouse_id)
    if current_total + quantity_change > warehouse.capacity_units:
        raise WarehouseCapacityError(warehouse.capacity_units, current_total, quantity_change)


def record_movement(
    session: Session,
    product_id: int,
    warehouse_id: int,
    quantity_change: int,
    reason: MovementReason,
    reference: str | None = None,
    actor_user_id: int | None = None,
    idempotency_key: str | None = None,
) -> InventoryMovement:
    """Apply one stock change and record it in the ledger.

    `actor_user_id` is the user making the change. API routes must always pass it;
    None is only for system processes such as the synthetic data seed.

    Example: 10 on hand, `quantity_change=-3` (a sale) gives on_hand 7 and a
    movement with `balance_after=7`. A change of -11 raises
    InsufficientStockError and changes nothing. A receipt or incoming transfer
    that would overfill the warehouse raises WarehouseCapacityError.

    Does not commit. Raises ValueError for invalid input, and the database
    raises IntegrityError for an unknown product or warehouse.
    """
    if quantity_change == 0:
        raise ValueError("quantity_change must not be zero")
    reason = MovementReason(reason)  # raises ValueError for an unknown reason
    if quantity_change > 0 and reason in CAPACITY_CHECKED_REASONS:
        check_capacity(session, warehouse_id, quantity_change)

    # Make sure the inventory row exists. ON CONFLICT DO NOTHING avoids a
    # duplicate-key error if two requests create the same row at the same time.
    session.execute(
        insert(Inventory)
        .values(product_id=product_id, warehouse_id=warehouse_id, on_hand=0)
        .on_conflict_do_nothing(index_elements=["product_id", "warehouse_id"])
    )

    # FOR UPDATE locks the row until our transaction ends, so two concurrent
    # sales cannot both read "1 left" and both succeed.
    inventory = session.execute(
        select(Inventory)
        .where(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id)
        .with_for_update()
    ).scalar_one()

    new_balance = inventory.on_hand + quantity_change
    if new_balance < 0:
        raise InsufficientStockError(inventory.on_hand, quantity_change)

    inventory.on_hand = new_balance
    movement = InventoryMovement(
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_change=quantity_change,
        balance_after=new_balance,
        reason=reason.value,
        reference=reference,
        created_by_user_id=actor_user_id,
        idempotency_key=idempotency_key,
    )
    session.add(movement)
    session.flush()  # send to the database now so constraint errors surface here
    return movement


def movement_history(
    session: Session, product_id: int, warehouse_id: int, limit: int = 100
) -> list[InventoryMovement]:
    """Return the most recent movements for one product at one warehouse, newest first.

    `created_at` is the transaction start time, so movements recorded in the same
    transaction share a timestamp. `id` always increases, so it breaks those ties
    and keeps the order stable.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return list(
        session.execute(
            select(InventoryMovement)
            .where(
                InventoryMovement.product_id == product_id,
                InventoryMovement.warehouse_id == warehouse_id,
            )
            .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .limit(limit)
        ).scalars()
    )


def _find_by_key(session: Session, idempotency_key: str) -> InventoryMovement | None:
    return session.execute(
        select(InventoryMovement).where(InventoryMovement.idempotency_key == idempotency_key)
    ).scalar_one_or_none()


def _same_request(
    movement: InventoryMovement,
    product_id: int,
    warehouse_id: int,
    quantity_change: int,
    reason: MovementReason,
    reference: str | None,
    actor_user_id: int | None,
) -> bool:
    # The actor is part of "the same request": a key reused by another user must
    # not silently hand them someone else's movement.
    return (
        movement.created_by_user_id == actor_user_id
        and movement.product_id == product_id
        and movement.warehouse_id == warehouse_id
        and movement.quantity_change == quantity_change
        and movement.reason == MovementReason(reason).value
        and movement.reference == reference
    )


def record_movement_once(
    session: Session,
    idempotency_key: str,
    product_id: int,
    warehouse_id: int,
    quantity_change: int,
    reason: MovementReason,
    reference: str | None,
    actor_user_id: int | None,
) -> tuple[InventoryMovement, bool]:
    """Like record_movement, but a retry with the same key returns the first result.

    Returns (movement, created). `created` is False when the same user already used
    the key for the same change. Raises IdempotencyConflictError if the key was
    used for a different change or by a different user.
    """
    request = (product_id, warehouse_id, quantity_change, reason, reference)

    existing = _find_by_key(session, idempotency_key)
    if existing is None:
        try:
            # Savepoint: if another request with the same key commits first, the
            # unique constraint fails here and only this attempt is undone.
            with session.begin_nested():
                movement = record_movement(
                    session, *request, actor_user_id=actor_user_id, idempotency_key=idempotency_key
                )
            return movement, True
        except IntegrityError as error:
            if "uq_inventory_movements_idempotency_key" not in str(error.orig):
                raise
            existing = _find_by_key(session, idempotency_key)

    if not _same_request(existing, *request, actor_user_id):
        raise IdempotencyConflictError(
            "This Idempotency-Key was already used for a different stock change"
        )
    return existing, False


def inventory_query(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    max_on_hand: int | None = None,
) -> Select:
    """Query for stock levels with product and warehouse names, by warehouse code then SKU.

    `max_on_hand` finds low stock, e.g. 10 returns rows with 10 units or fewer.
    """
    query = (
        select(
            Inventory.product_id,
            Product.sku,
            Product.name.label("product_name"),
            Inventory.warehouse_id,
            Warehouse.code.label("warehouse_code"),
            Inventory.on_hand,
            Inventory.updated_at,
        )
        .join(Product, Product.id == Inventory.product_id)
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
    )
    if warehouse_id is not None:
        query = query.where(Inventory.warehouse_id == warehouse_id)
    if product_id is not None:
        query = query.where(Inventory.product_id == product_id)
    if max_on_hand is not None:
        query = query.where(Inventory.on_hand <= max_on_hand)
    return query.order_by(Warehouse.code, Product.sku)
