"""The only place where stock levels change.

Each call locks the inventory row, checks the new balance, updates `on_hand`
and appends a movement, all inside the caller's transaction. The caller decides
when to commit, so several movements (for example, both sides of a transfer)
can succeed or fail together.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Inventory, InventoryMovement, MovementReason


class InsufficientStockError(Exception):
    """Raised when a movement would make stock negative."""

    def __init__(self, available: int, requested_change: int) -> None:
        self.available = available
        self.requested_change = requested_change
        super().__init__(
            f"Insufficient stock: {available} on hand, change of {requested_change} requested"
        )


def record_movement(
    session: Session,
    product_id: int,
    warehouse_id: int,
    quantity_change: int,
    reason: MovementReason,
    reference: str | None = None,
    actor_user_id: int | None = None,
) -> InventoryMovement:
    """Apply one stock change and record it in the ledger.

    `actor_user_id` is the user making the change. API routes must always pass it;
    None is only for system processes such as the synthetic data seed.

    Example: 10 on hand, `quantity_change=-3` (a sale) gives on_hand 7 and a
    movement with `balance_after=7`. A change of -11 raises
    InsufficientStockError and changes nothing.

    Does not commit. Raises ValueError for invalid input, and the database
    raises IntegrityError for an unknown product or warehouse.
    """
    if quantity_change == 0:
        raise ValueError("quantity_change must not be zero")
    reason = MovementReason(reason)  # raises ValueError for an unknown reason

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
