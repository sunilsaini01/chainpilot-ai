"""Stock levels and stock movements.

Reading is open to every logged-in user; recording a movement needs a manager
(or admin). All stock changes go through inventory_service, never a direct update.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.audit import record_event
from app.dependencies import get_db_session, require_role
from app.inventory_service import (
    IdempotencyConflictError,
    InsufficientStockError,
    WarehouseCapacityError,
    inventory_query,
    movement_history,
    record_movement,
    record_movement_once,
)
from app.models import InventoryMovement, Role, User
from app.pagination import fetch_page
from app.routes.products import get_product_or_404
from app.routes.warehouses import get_warehouse_or_404
from app.schemas import InventoryOut, MovementCreate, MovementOut

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[InventoryOut])
def get_inventory(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    max_on_hand: int | None = Query(
        default=None, ge=0, description="Only rows with at most this many units (low stock)"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list:
    query = inventory_query(warehouse_id, product_id, max_on_hand)
    return list(fetch_page(session, query, limit, offset, response).all())


@router.get("/movements", response_model=list[MovementOut])
def get_movements(
    product_id: int,
    warehouse_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[InventoryMovement]:
    """Movement history for one product at one warehouse, newest first."""
    return movement_history(session, product_id, warehouse_id, limit)


@router.post(
    "/movements",
    response_model=MovementOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Repeated request: the movement already recorded for this key"},
        404: {"description": "Product or warehouse not found"},
        409: {
            "description": "Insufficient stock, warehouse full, or Idempotency-Key reused "
            "for another change"
        },
    },
)
def add_movement(
    body: MovementCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=100),
    manager: User = Depends(require_role(Role.MANAGER)),
    session: Session = Depends(get_db_session),
) -> InventoryMovement:
    """Record a receipt, sale, transfer leg or adjustment.

    Send an `Idempotency-Key` header (any unique string, e.g. a UUID) to make
    retries safe: repeating the same request with the same key returns the
    original movement (HTTP 200) instead of changing stock twice.
    """
    get_product_or_404(session, body.product_id)
    get_warehouse_or_404(session, body.warehouse_id)
    request = (
        body.product_id,
        body.warehouse_id,
        body.quantity_change,
        body.reason,
        body.reference,
    )

    try:
        if idempotency_key is None:
            movement, created = record_movement(session, *request, actor_user_id=manager.id), True
        else:
            movement, created = record_movement_once(
                session, idempotency_key, *request, actor_user_id=manager.id
            )
    except InsufficientStockError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (IdempotencyConflictError, WarehouseCapacityError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:  # e.g. quantity_change of 0
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    if not created:
        response.status_code = status.HTTP_200_OK  # nothing new happened
        return movement

    record_event(
        session,
        "inventory.movement_recorded",
        "inventory_movement",
        movement.id,
        actor=manager,
        details={
            "product_id": movement.product_id,
            "warehouse_id": movement.warehouse_id,
            "quantity_change": movement.quantity_change,
            "reason": movement.reason,
            "balance_after": movement.balance_after,
            "reference": movement.reference,
        },
    )
    session.commit()
    return movement
