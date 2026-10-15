"""Read-only audit trail (managers and admins)."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.audit import events_query
from app.dependencies import get_db_session, require_role
from app.models import AuditEvent, Role, User
from app.pagination import fetch_page
from app.schemas import AuditEventOut

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
def get_audit_events(
    entity_type: str | None = Query(default=None, max_length=50),
    entity_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    response: Response,
    user: User = Depends(require_role(Role.MANAGER)),
    session: Session = Depends(get_db_session),
) -> list[AuditEvent]:
    """Newest events first. Filter with e.g. `?entity_type=user&entity_id=3`."""
    query = events_query(entity_type, entity_id)
    return list(fetch_page(session, query, limit, offset, response).scalars())
