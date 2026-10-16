"""AI copilot investigations (P5-T3), for analysts and up.

The copilot only reads (its tools run in read-only transactions) and cannot
approve or order anything. Each run is stored with its full trace. Starting a
run calls OpenAI, so it is limited per user and hour.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.copilot.model import ChatModel
from app.copilot.service import (
    CopilotNotConfiguredError,
    configured_model,
    run_and_save,
    runs_in_last_hour,
)
from app.dependencies import get_db_session, require_role
from app.models import AgentRun, Role, User
from app.pagination import fetch_page
from app.schemas import AgentRunOut, InvestigateRequest

router = APIRouter(prefix="/agents", tags=["ai copilot"])


def chat_model() -> ChatModel:
    """The model to use; tests replace this dependency with a scripted model."""
    try:
        return configured_model()
    except CopilotNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.post(
    "/investigate",
    response_model=AgentRunOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        429: {"description": "Hourly limit of investigations reached"},
        503: {"description": "Copilot not configured (no OpenAI key or model)"},
    },
)
def start_investigation(
    body: InvestigateRequest,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
    model: ChatModel = Depends(chat_model),
) -> AgentRun:
    """Ask the copilot a question. Answers cite the records and policies they use."""
    limit = get_settings().copilot_runs_per_hour
    if runs_in_last_hour(session, user.id) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"At most {limit} investigations per hour",
            headers={"Retry-After": "3600"},
        )
    run = run_and_save(session, model, body.question, user)
    session.commit()
    return run


@router.get("/runs", response_model=list[AgentRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[AgentRun]:
    query = select(AgentRun).order_by(AgentRun.id.desc())
    return list(fetch_page(session, query, limit, offset, response).scalars())


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_run(
    run_id: int,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> AgentRun:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run
