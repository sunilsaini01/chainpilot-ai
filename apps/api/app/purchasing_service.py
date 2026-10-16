"""Purchase orders: what is on order, and receiving an order into stock.

Inventory position (app/inventory_policy.py) = on hand + on order, where "on
order" is the quantity on open purchase orders. Receiving an order books every
line into stock through `record_movement`, so the ledger and the warehouse
capacity check apply, and marks the order received, all in one transaction.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.inventory_service import record_movement
from app.models import (
    MovementReason,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Supplier,
)


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


# --- Supplier performance (rules from policies/supplier-performance.md) ----------

WINDOW_DAYS = 90  # received orders of the last 90 days are rated
MIN_ORDERS = 5  # fewer received orders than this: not rated
GOOD_SHARE, WATCH_SHARE = 0.90, 0.75  # on-time share: good >= 90%, watch >= 75%, else at risk


@dataclass(frozen=True)
class SupplierPerformance:
    supplier_id: int
    code: str
    name: str
    received_orders: int  # in the window
    on_time_orders: int  # received on or before the expected date
    on_time_rate: float | None  # None when there is nothing to rate
    average_days_late: float | None  # over received orders, on-time ones count as 0
    rating: str  # good, watch, at_risk or not_rated
    open_orders: int
    overdue_orders: list[str]  # PO numbers: open and past the expected date


def rating_for(on_time: int, received: int) -> str:
    if received < MIN_ORDERS:
        return "not_rated"
    share = on_time / received
    if share >= GOOD_SHARE:
        return "good"
    return "watch" if share >= WATCH_SHARE else "at_risk"


def supplier_performance(
    session: Session, as_of: date, supplier_id: int | None = None
) -> list[SupplierPerformance]:
    """On-time delivery per supplier, by supplier code.

    Rated: orders received from `as_of` minus WINDOW_DAYS up to `as_of` (both included).
    """
    supplier_query = select(Supplier).order_by(Supplier.code)
    if supplier_id is not None:
        supplier_query = supplier_query.where(Supplier.id == supplier_id)
    suppliers = session.execute(supplier_query).scalars().all()

    orders = session.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.supplier_id.in_([supplier.id for supplier in suppliers]),
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
        )
    ).scalars()
    received: dict[int, list[PurchaseOrder]] = defaultdict(list)
    still_open: dict[int, list[PurchaseOrder]] = defaultdict(list)
    window_start = as_of - timedelta(days=WINDOW_DAYS)
    for order in orders:
        if order.status == PurchaseOrderStatus.OPEN:
            still_open[order.supplier_id].append(order)
        elif window_start <= order.received_date <= as_of:
            received[order.supplier_id].append(order)

    results = []
    for supplier in suppliers:
        done = received[supplier.id]
        on_time = sum(order.received_date <= order.expected_date for order in done)
        days_late = [max((o.received_date - o.expected_date).days, 0) for o in done]
        overdue = sorted(o.po_number for o in still_open[supplier.id] if o.expected_date < as_of)
        results.append(
            SupplierPerformance(
                supplier_id=supplier.id,
                code=supplier.code,
                name=supplier.name,
                received_orders=len(done),
                on_time_orders=on_time,
                on_time_rate=round(on_time / len(done), 4) if done else None,
                average_days_late=round(sum(days_late) / len(done), 2) if done else None,
                rating=rating_for(on_time, len(done)),
                open_orders=len(still_open[supplier.id]),
                overdue_orders=overdue,
            )
        )
    return results
