"""Product catalogue: anyone logged in can read; only admins can change it."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.catalog_service import DuplicateCodeError, apply_changes, create_product
from app.dependencies import get_db_session, require_role
from app.models import Product, Role, User
from app.pagination import fetch_page
from app.schemas import ProductCreate, ProductOut, ProductUpdate, sent_updates

router = APIRouter(prefix="/products", tags=["products"])


def get_product_or_404(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("", response_model=list[ProductOut])
def list_products(
    search: str | None = Query(default=None, max_length=100, description="Part of SKU or name"),
    category: str | None = Query(default=None, max_length=100),
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[Product]:
    """List products ordered by SKU, with optional filters."""
    query = select(Product)
    if search:
        # Bound parameter, so the search text is never interpreted as SQL. % and _
        # are escaped so that searching for "100%" means the literal text.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            or_(
                Product.sku.ilike(pattern, escape="\\"),
                Product.name.ilike(pattern, escape="\\"),
            )
        )
    if category is not None:
        query = query.where(Product.category == category)
    if is_active is not None:
        query = query.where(Product.is_active.is_(is_active))
    query = query.order_by(Product.sku)
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> Product:
    return get_product_or_404(session, product_id)


@router.post(
    "",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "SKU already exists"}},
)
def add_product(
    body: ProductCreate,
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> Product:
    try:
        product = create_product(
            session, body.sku, body.name, body.category, body.unit_cost, body.unit_price
        )
    except DuplicateCodeError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_event(
        session, "product.created", "product", product.id, actor=admin, details={"sku": product.sku}
    )
    session.commit()
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def change_product(
    product_id: int,
    body: ProductUpdate,
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> Product:
    """Change name, category, prices or active flag. Deactivate instead of deleting,
    because stock history refers to the product."""
    product = get_product_or_404(session, product_id)
    try:
        updates = sent_updates(body)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    changes = apply_changes(product, updates)
    if changes:
        record_event(
            session,
            "product.updated",
            "product",
            product.id,
            actor=admin,
            details={"changes": changes},
        )
    session.commit()
    return product
