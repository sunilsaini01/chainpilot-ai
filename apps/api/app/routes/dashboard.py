"""Overview numbers for the dashboard (spec section 5: GET /dashboard/kpis).

Every number comes from an existing service, so the dashboard shows exactly
what the detailed endpoints show. Stock, suppliers and orders are SIMULATED.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, require_role
from app.models import (
    Inventory,
    Product,
    PurchaseOrder,
    PurchaseOrderStatus,
    Recommendation,
    RecommendationStatus,
    Role,
    User,
    Warehouse,
)
from app.purchasing_service import supplier_performance
from app.replenishment_service import (
    DATA_LABEL,
    DEFAULT_SERVICE_LEVEL,
    STATUS_ORDER,
    NoForecastRunError,
    assess_all,
)
from app.schemas import DashboardKpisOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/kpis", response_model=DashboardKpisOut)
def kpis(
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> dict:
    today = datetime.now(UTC).date()

    def count(model, *conditions) -> int:
        return session.execute(
            select(func.count()).select_from(model).where(*conditions)
        ).scalar_one()

    units, value = session.execute(
        select(
            func.coalesce(func.sum(Inventory.on_hand), 0),
            func.coalesce(func.sum(Inventory.on_hand * Product.unit_cost), 0),
        ).join(Product, Inventory.product_id == Product.id)
    ).one()

    stock_status, stock_note, forecast_run_id = None, None, None
    try:
        run, assessments, unassessed = assess_all(session, DEFAULT_SERVICE_LEVEL)
        forecast_run_id = run.id
        stock_status = {status: 0 for status in STATUS_ORDER} | {"unassessed": unassessed}
        for item in assessments:
            stock_status[item.status] += 1
    except NoForecastRunError as error:
        stock_note = str(error)

    pending = dict(
        session.execute(
            select(Recommendation.kind, func.count())
            .where(Recommendation.status == RecommendationStatus.PENDING)
            .group_by(Recommendation.kind)
        ).all()
    )
    ratings = {"good": 0, "watch": 0, "at_risk": 0, "not_rated": 0}
    for row in supplier_performance(session, today):
        ratings[row.rating] += 1

    return {
        "label": DATA_LABEL,
        "inventory": {
            "products": count(Product, Product.is_active.is_(True)),
            "warehouses": count(Warehouse),
            "units_on_hand": int(units),
            "stock_value": round(float(value), 2),
        },
        "stock_status": stock_status,
        "stock_status_note": stock_note,
        "forecast_run_id": forecast_run_id,
        "pending_recommendations": {
            "reorder": pending.get("reorder", 0),
            "transfer": pending.get("transfer", 0),
        },
        "purchase_orders": {
            "open": count(PurchaseOrder, PurchaseOrder.status == PurchaseOrderStatus.OPEN),
            "overdue": count(
                PurchaseOrder,
                PurchaseOrder.status == PurchaseOrderStatus.OPEN,
                PurchaseOrder.expected_date < today,
            ),
        },
        "supplier_ratings": ratings,
    }
