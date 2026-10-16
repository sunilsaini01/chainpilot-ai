"""Suppliers and purchase orders (simulated SYN- data from the seed).

Reading is open to every logged-in user. Receiving an order changes stock, so it
needs a manager (or admin). New orders will come from approved recommendations
(P4-T4), not from a free-form endpoint.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import record_event
from app.dependencies import get_db_session, require_role
from app.inventory_service import WarehouseCapacityError
from app.models import PurchaseOrder, PurchaseOrderLine, Role, Supplier, User
from app.pagination import fetch_page
from app.purchasing_service import (
    PurchaseOrderNotOpenError,
    SupplierPerformance,
    receive_purchase_order,
    supplier_performance,
)
from app.schemas import PurchaseOrderOut, SupplierOut, SupplierRiskOut

router = APIRouter(tags=["purchasing"])


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[Supplier]:
    query = select(Supplier).order_by(Supplier.code)
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get("/suppliers/risks", response_model=list[SupplierRiskOut])
def supplier_risks(
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[SupplierPerformance]:
    """On-time delivery over the last 90 days and a rating per supplier, worst first.

    Rules from policies/supplier-performance.md: good at 90% on time or more,
    watch from 75%, at risk below 75%, not rated with fewer than 5 received orders.
    """
    rows = supplier_performance(session, datetime.now(UTC).date())
    order = {"at_risk": 0, "watch": 1, "good": 2, "not_rated": 3}
    return sorted(rows, key=lambda row: (order[row.rating], row.code))


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(open|received|cancelled)$"
    ),
    warehouse_id: int | None = None,
    supplier_id: int | None = None,
    product_id: int | None = Query(default=None, description="Orders with a line for it"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[PurchaseOrder]:
    """Purchase orders with their lines, newest first."""
    query = select(PurchaseOrder).options(selectinload(PurchaseOrder.lines))
    if status_filter is not None:
        query = query.where(PurchaseOrder.status == status_filter)
    if warehouse_id is not None:
        query = query.where(PurchaseOrder.warehouse_id == warehouse_id)
    if supplier_id is not None:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if product_id is not None:
        has_line = select(PurchaseOrderLine.id).where(
            PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
            PurchaseOrderLine.product_id == product_id,
        )
        query = query.where(has_line.exists())
    query = query.order_by(PurchaseOrder.ordered_date.desc(), PurchaseOrder.id.desc())
    return list(fetch_page(session, query, limit, offset, response).scalars())


def get_order_or_404(session: Session, order_id: int) -> PurchaseOrder:
    order = session.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found"
        )
    return order


@router.get("/purchase-orders/{order_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    order_id: int,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> PurchaseOrder:
    return get_order_or_404(session, order_id)


@router.post(
    "/purchase-orders/{order_id}/receive",
    response_model=PurchaseOrderOut,
    responses={
        404: {"description": "Purchase order not found"},
        409: {"description": "Order is not open, or the warehouse has no room for it"},
    },
)
def receive_order(
    order_id: int,
    manager: User = Depends(require_role(Role.MANAGER)),
    session: Session = Depends(get_db_session),
) -> PurchaseOrder:
    """Book every line of an open order into stock (one receipt movement per line).

    All or nothing: if the warehouse cannot hold the whole delivery, nothing is
    booked and the order stays open.
    """
    try:
        order = receive_purchase_order(
            session, order_id, datetime.now(UTC).date(), actor_user_id=manager.id
        )
    except (PurchaseOrderNotOpenError, WarehouseCapacityError) as error:
        # Nothing is committed: closing the request's session rolls the bookings back.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found"
        )
    record_event(
        session,
        "purchase_order.received",
        "purchase_order",
        order.id,
        actor=manager,
        details={
            "po_number": order.po_number,
            "warehouse_id": order.warehouse_id,
            "lines": len(order.lines),
            "units": sum(line.quantity for line in order.lines),
        },
    )
    session.commit()
    return order
