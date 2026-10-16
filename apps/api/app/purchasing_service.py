"""Purchase orders: what is on order, and receiving an order into stock.

Inventory position (app/inventory_policy.py) = on hand + on order, where "on
order" is the quantity on open purchase orders. Receiving an order books every
line into stock through `record_movement`, so the ledger and the warehouse
capacity check apply, and marks the order received, all in one transaction.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.inventory_service import record_movement
from app.models import MovementReason, PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus


class PurchaseOrderNotOpenError(Exception):
    """Raised when receiving an order that is already received or cancelled."""


def on_order_quantities(
    session: Session, warehouse_id: int | None = None
) -> dict[tuple[int, int], int]:
    """Units on open purchase orders per (product_id, warehouse_id)."""
    query = (
        select(
            PurchaseOrderLine.product_id,
            PurchaseOrder.warehouse_id,
            func.sum(PurchaseOrderLine.quantity),
        )
        .join(PurchaseOrder)
        .where(PurchaseOrder.status == PurchaseOrderStatus.OPEN)
        .group_by(PurchaseOrderLine.product_id, PurchaseOrder.warehouse_id)
    )
    if warehouse_id is not None:
        query = query.where(PurchaseOrder.warehouse_id == warehouse_id)
    return {
        (product, warehouse): int(units) for product, warehouse, units in session.execute(query)
    }


def receive_purchase_order(
    session: Session, order_id: int, received_on: date, actor_user_id: int | None
) -> PurchaseOrder | None:
    """Book all lines of an open order into stock. Returns None if the order does not exist.

    The order row is locked first (FOR UPDATE), so two managers receiving the
    same order at the same time cannot both book the goods: the second waits,
    then sees "received" and gets PurchaseOrderNotOpenError. A capacity error
    from `record_movement` leaves the transaction for the caller to roll back.
    Does not commit.
    """
    order = session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == order_id).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        return None
    if order.status != PurchaseOrderStatus.OPEN:
        raise PurchaseOrderNotOpenError(f"{order.po_number} is {order.status}, not open")

    for line in order.lines:
        record_movement(
            session,
            line.product_id,
            order.warehouse_id,
            line.quantity,
            MovementReason.RECEIPT,
            reference=order.po_number,
            actor_user_id=actor_user_id,
        )
    order.status = PurchaseOrderStatus.RECEIVED
    order.received_date = received_on
    order.received_by_user_id = actor_user_id
    session.flush()
    return order
