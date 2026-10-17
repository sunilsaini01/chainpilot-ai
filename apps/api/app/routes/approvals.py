"""Approval workflow: managers approve or reject recommendations (see app/approval_service.py)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.approval_service import (
    AlreadyDecidedError,
    IdempotencyKeyReusedError,
    ReasonRequiredError,
    RecommendationNotFoundError,
    decide,
    find_approval,
)
from app.dependencies import get_db_session, require_role
from app.models import Approval, ApprovalDecision, Role, User
from app.pagination import fetch_page
from app.schemas import ApprovalOut, DecisionRequest

router = APIRouter(tags=["approvals"])

DECISIONS = {"approve": ApprovalDecision.APPROVED, "reject": ApprovalDecision.REJECTED}


@router.post(
    "/inventory/recommendations/{recommendation_id}/decision",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Repeated request: the decision already stored for this key"},
        404: {"description": "Recommendation not found"},
        409: {
            "description": "Not pending any more (already decided or replaced), or the "
            "Idempotency-Key was used for a different decision"
        },
        422: {
            "description": "Invalid body, missing Idempotency-Key, or a rejection without reason"
        },
    },
)
def decide_recommendation(
    recommendation_id: int,
    body: DecisionRequest,
    response: Response,
    idempotency_key: str = Header(min_length=1, max_length=100),
    manager: User = Depends(require_role(Role.MANAGER)),
    session: Session = Depends(get_db_session),
) -> Approval:
    """Approve or reject a pending recommendation. Approving carries it out at once
    (simulated): a reorder becomes an open purchase order, a transfer moves the stock.

    If an approved transfer cannot be carried out now, the decision is stored with
    `outcome: "failed"` and the reason, and no stock changes. Send a unique
    `Idempotency-Key` header (e.g. a UUID) with each decision: retrying with the
    same key returns the stored decision (HTTP 200) instead of acting twice.
    """
    try:
        result = decide(
            session,
            recommendation_id,
            DECISIONS[body.decision],
            body.comment,
            manager,
            idempotency_key,
            datetime.now(UTC).date(),
        )
    except RecommendationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (AlreadyDecidedError, IdempotencyKeyReusedError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ReasonRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except IntegrityError as error:
        # The same key, sent at the same moment for another recommendation, was
        # stored first (the unique key index). Nothing of this request is kept.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Idempotency-Key was already used for a different decision",
        ) from error

    if not result.created:
        response.status_code = status.HTTP_200_OK
        return result.approval
    session.commit()
    # Committing expires the loaded rows; read the decision back with its decider.
    return find_approval(session, id=result.approval.id)


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(
    decision: str | None = Query(default=None, pattern="^(approved|rejected)$"),
    outcome: str | None = Query(default=None, pattern="^(executed|failed)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[Approval]:
    """Decisions, newest first, with who decided and what happened."""
    query = select(Approval).options(selectinload(Approval.decided_by))
    if decision is not None:
        query = query.where(Approval.decision == decision)
    if outcome is not None:
        query = query.where(Approval.outcome == outcome)
    query = query.order_by(Approval.created_at.desc(), Approval.id.desc())
    return list(fetch_page(session, query, limit, offset, response).scalars())
