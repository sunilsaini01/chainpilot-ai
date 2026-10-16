"""Policy documents (simulated company policies written for the demo), for analysts and up.

Loaded with `python -m app.cli load-policies`. The AI copilot uses the same
search to ground its answers; every hit carries a citation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, require_role
from app.models import DocumentChunk, Role, User
from app.policies_service import MAX_QUERY_CHARS, PolicyError, search_policies
from app.schemas import PolicyDocumentOut, PolicyHitOut

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=list[PolicyDocumentOut])
def list_policies(
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list[dict]:
    rows = session.execute(
        select(
            DocumentChunk.document,
            func.min(DocumentChunk.title),
            func.count(),
            func.min(DocumentChunk.document_sha256),
            func.max(DocumentChunk.created_at),
        )
        .group_by(DocumentChunk.document)
        .order_by(DocumentChunk.document)
    ).all()
    return [
        {"document": d, "title": t, "chunks": n, "sha256": sha, "loaded_at": loaded}
        for d, t, n, sha, loaded in rows
    ]


@router.get("/search", response_model=list[PolicyHitOut])
def search(
    q: str = Query(min_length=1, max_length=MAX_QUERY_CHARS, description="A question or keywords"),
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(require_role(Role.ANALYST)),
    session: Session = Depends(get_db_session),
) -> list:
    """Best-matching policy sections, best first (keyword search with stemming)."""
    try:
        return search_policies(session, q, limit)
    except PolicyError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
