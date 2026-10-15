"""Warehouses: anyone logged in can read; only admins can change them."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.catalog_service import DuplicateCodeError, apply_changes, create_warehouse
from app.dependencies import get_db_session, require_role
from app.inventory_service import warehouse_stock_total
from app.models import Role, User, Warehouse
from app.pagination import fetch_page
from app.schemas import WarehouseCreate, WarehouseOut, WarehouseUpdate, sent_updates

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


def get_warehouse_or_404(session: Session, warehouse_id: int) -> Warehouse:
    warehouse = session.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found")
    return warehouse


@router.get("", response_model=list[WarehouseOut])
def list_warehouses(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[Warehouse]:
    query = select(Warehouse).order_by(Warehouse.code)
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get("/{warehouse_id}", response_model=WarehouseOut)
def get_warehouse(
    warehouse_id: int,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> Warehouse:
    return get_warehouse_or_404(session, warehouse_id)


@router.post(
    "",
    response_model=WarehouseOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Code already exists"}},
)
def add_warehouse(
    body: WarehouseCreate,
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> Warehouse:
    try:
        warehouse = create_warehouse(session, body.code, body.name, body.city, body.capacity_units)
    except DuplicateCodeError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_event(
        session,
        "warehouse.created",
        "warehouse",
        warehouse.id,
        actor=admin,
        details={"code": warehouse.code},
    )
    session.commit()
    return warehouse


@router.patch("/{warehouse_id}", response_model=WarehouseOut)
def change_warehouse(
    warehouse_id: int,
    body: WarehouseUpdate,
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> Warehouse:
    warehouse = get_warehouse_or_404(session, warehouse_id)
    try:
        updates = sent_updates(body)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    if "capacity_units" in updates:
        # Lock the warehouse (the same lock receipts take) so stock cannot arrive
        # between this check and the commit.
        session.refresh(warehouse, with_for_update=True)
        current_total = warehouse_stock_total(session, warehouse.id)
        if updates["capacity_units"] < current_total:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Capacity cannot be below the {current_total} units currently stored",
            )
    changes = apply_changes(warehouse, updates)
    if changes:
        record_event(
            session,
            "warehouse.updated",
            "warehouse",
            warehouse.id,
            actor=admin,
            details={"changes": changes},
        )
    session.commit()
    return warehouse
