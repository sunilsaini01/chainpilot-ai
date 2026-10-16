"""Stock-out risks and reorder/transfer recommendations (simulated SYN- data).

Every response carries an `X-Dataset` header: stock and suppliers are simulated
and demand is borrowed from linked M5 forecasts (see app/replenishment_service.py).
Recommendations are proposals; approving and executing them is P7.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, require_role
from app.models import Recommendation, Role, User
from app.pagination import TOTAL_COUNT_HEADER, fetch_page
from app.replenishment_service import (
    DATA_LABEL,
    DEFAULT_SERVICE_LEVEL,
    STATUS_ORDER,
    NoForecastRunError,
    assess_all,
    create_recommendations,
)
from app.schemas import RecommendationOut, RecommendationRequest, RiskOut

router = APIRouter(prefix="/inventory", tags=["replenishment"])
DATASET_HEADER = "X-Dataset"
UNASSESSED_HEADER = "X-Unassessed-Count"
NO_FORECAST = {409: {"description": "No forecast run imported yet"}}


def _no_forecast(error: NoForecastRunError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get("/risks", response_model=list[RiskOut], responses=NO_FORECAST)
def list_risks(
    warehouse_id: int | None = None,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(" + "|".join(STATUS_ORDER) + ")$"
    ),
    service_level: float = Query(default=DEFAULT_SERVICE_LEVEL, ge=0.5, lt=1),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """Every linked product at every linked warehouse, most urgent first.

    Computed live from current stock, open orders and the newest forecast run.
    """
    try:
        _, assessments, unassessed = assess_all(session, service_level, warehouse_id)
    except NoForecastRunError as error:
        raise _no_forecast(error) from error
    if status_filter is not None:
        assessments = [item for item in assessments if item.status == status_filter]
    response.headers[TOTAL_COUNT_HEADER] = str(len(assessments))
    response.headers[UNASSESSED_HEADER] = str(unassessed)
    response.headers[DATASET_HEADER] = DATA_LABEL
    return [item.as_dict() for item in assessments[offset : offset + limit]]


@router.post(
    "/recommendations",
    response_model=list[RecommendationOut],
    status_code=status.HTTP_201_CREATED,
    responses=NO_FORECAST,
)
def generate_recommendations(
    body: RecommendationRequest,
    response: Response,
    manager: User = Depends(require_role(Role.MANAGER)),
    session: Session = Depends(get_db_session),
) -> list[Recommendation]:
    """Replace the pending recommendations with a fresh set (proposals only).

    Nothing is ordered or moved: each recommendation waits for approval (P7).
    """
    try:
        created, _ = create_recommendations(session, body.service_level, manager)
    except NoForecastRunError as error:
        raise _no_forecast(error) from error
    session.commit()
    response.headers[DATASET_HEADER] = DATA_LABEL
    return created


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(
    status_filter: str = Query(default="pending", alias="status", pattern="^(pending|superseded)$"),
    kind: str | None = Query(default=None, pattern="^(reorder|transfer)$"),
    warehouse_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[Recommendation]:
    query = select(Recommendation).where(Recommendation.status == status_filter)
    if kind is not None:
        query = query.where(Recommendation.kind == kind)
    if warehouse_id is not None:
        query = query.where(Recommendation.warehouse_id == warehouse_id)
    query = query.order_by(Recommendation.id)
    response.headers[DATASET_HEADER] = DATA_LABEL
    return list(fetch_page(session, query, limit, offset, response).scalars())
