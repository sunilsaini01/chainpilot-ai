"""Delivery-risk scores (Olist public data), for analysts and up.

Imported with `python -m app.cli import-delivery-risk <folder>`. Every response
carries an `X-Dataset` header: these are historical Olist marketplace orders,
not ChainPilot's simulated suppliers (spec section 4.D).

How to read a score: `tier` and `day_percentile` (rank among the same day's
dispatches) are the reliable signal; `probability` is approximate because the
late rate changes from month to month. `alert` marks the riskiest 10% of each day.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, require_role
from app.models import DeliveryRiskRun, DeliveryRiskScore, Role, User
from app.pagination import fetch_page
from app.schemas import DeliveryRiskRunOut, DeliveryRiskScoreOut

router = APIRouter(prefix="/delivery-risk", tags=["delivery risk"])
DATASET_HEADER = "X-Dataset"


def get_run(session: Session, run_id: int | None) -> DeliveryRiskRun:
    """The requested run, or the newest one. 404 if there is none."""
    if run_id is None:
        run = session.execute(
            select(DeliveryRiskRun).order_by(DeliveryRiskRun.id.desc()).limit(1)
        ).scalar_one_or_none()
    else:
        run = session.get(DeliveryRiskRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Delivery-risk run not found"
        )
    return run


@router.get("/runs", response_model=list[DeliveryRiskRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[DeliveryRiskRun]:
    query = select(DeliveryRiskRun).order_by(DeliveryRiskRun.id.desc())
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get(
    "/scores",
    response_model=list[DeliveryRiskScoreOut],
    responses={404: {"description": "No delivery-risk run (or not that run)"}},
)
def list_scores(
    run_id: int | None = Query(default=None, description="Default: the newest run"),
    dispatch_date: date | None = None,
    tier: str | None = Query(default=None, pattern="^(high|medium|low)$"),
    alert: bool | None = None,
    order_id: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[DeliveryRiskScore]:
    """Scored orders, newest dispatch day first, riskiest first within a day."""
    run = get_run(session, run_id)
    query = select(DeliveryRiskScore).where(DeliveryRiskScore.run_id == run.id)
    if dispatch_date is not None:
        query = query.where(DeliveryRiskScore.dispatch_date == dispatch_date)
    if tier is not None:
        query = query.where(DeliveryRiskScore.tier == tier)
    if alert is not None:
        query = query.where(DeliveryRiskScore.alert.is_(alert))
    if order_id is not None:
        query = query.where(DeliveryRiskScore.order_id == order_id)
    query = query.order_by(
        DeliveryRiskScore.dispatch_date.desc(), DeliveryRiskScore.probability.desc()
    )
    response.headers[DATASET_HEADER] = run.dataset
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get(
    "/alerts",
    response_model=list[DeliveryRiskScoreOut],
    responses={404: {"description": "No delivery-risk run (or not that run)"}},
)
def list_alerts(
    day: date = Query(alias="date", description="Dispatch day, e.g. 2018-05-03"),
    run_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[DeliveryRiskScore]:
    """The day's alerts: the riskiest 10% of that day's dispatched orders, riskiest first."""
    run = get_run(session, run_id)
    query = (
        select(DeliveryRiskScore)
        .where(
            DeliveryRiskScore.run_id == run.id,
            DeliveryRiskScore.dispatch_date == day,
            DeliveryRiskScore.alert.is_(True),
        )
        .order_by(DeliveryRiskScore.probability.desc())
    )
    response.headers[DATASET_HEADER] = run.dataset
    return list(fetch_page(session, query, limit, offset, response).scalars())
