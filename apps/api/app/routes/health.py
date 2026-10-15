"""Liveness and readiness endpoints used by Docker, load balancers and humans."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import check_database, get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is up. Deliberately does not touch the database."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "Database unavailable"}},
)
def ready(response: Response, engine: Engine = Depends(get_engine)) -> ReadyResponse:
    """Readiness: the API can serve traffic because Postgres answers a query."""
    try:
        check_database(engine)
    except SQLAlchemyError as error:
        # Log only the error type: driver messages can include host/user details.
        logger.warning("Readiness check failed: database unavailable (%s)", type(error).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="not_ready", database="unavailable")
    return ReadyResponse(status="ready", database="ok")
