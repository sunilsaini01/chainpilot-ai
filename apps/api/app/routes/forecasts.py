"""Read-only demand forecasts (M5 public data), for analysts and up.

Forecasts are imported with `python -m app.cli import-forecasts <folder>`.
Every response carries an `X-Dataset` header naming the data source, because
these are forecasts for the public M5 (Walmart) data, not for the simulated
SYN- products in this application.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, require_role
from app.models import Forecast, ForecastRun, Role, User
from app.pagination import fetch_page
from app.schemas import ForecastOut, ForecastRunOut

router = APIRouter(prefix="/forecasts", tags=["forecasts"])
DATASET_HEADER = "X-Dataset"


@router.get("/runs", response_model=list[ForecastRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[ForecastRun]:
    """Imported forecast runs, newest first."""
    query = select(ForecastRun).order_by(ForecastRun.id.desc())
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get(
    "",
    response_model=list[ForecastOut],
    responses={404: {"description": "No forecast run (or not that run)"}},
)
def list_forecasts(
    run_id: int | None = Query(default=None, description="Default: the newest run"),
    store_id: str | None = Query(default=None, max_length=16),
    item_id: str | None = Query(default=None, max_length=32),
    series_id: str | None = Query(default=None, max_length=64),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[Forecast]:
    """Forecasts with 80% intervals, ordered by series and date."""
    if run_id is None:
        run = session.execute(
            select(ForecastRun).order_by(ForecastRun.id.desc()).limit(1)
        ).scalar_one_or_none()
    else:
        run = session.get(ForecastRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forecast run not found")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )

    query = select(Forecast).where(Forecast.run_id == run.id)
    for column, value in [
        (Forecast.store_id, store_id),
        (Forecast.item_id, item_id),
        (Forecast.series_id, series_id),
    ]:
        if value is not None:
            query = query.where(column == value)
    if date_from is not None:
        query = query.where(Forecast.forecast_date >= date_from)
    if date_to is not None:
        query = query.where(Forecast.forecast_date <= date_to)
    query = query.order_by(Forecast.series_id, Forecast.forecast_date)

    response.headers[DATASET_HEADER] = run.dataset
    return list(fetch_page(session, query, limit, offset, response).scalars())
