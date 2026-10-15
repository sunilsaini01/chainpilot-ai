"""Read-only audit trail (managers and admins)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.audit import list_events
from app.dependencies import get_db_session, require_role
from app.models import AuditEvent, Role, User
from app.schemas import AuditEventOut

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
def get_audit_events(
    entity_type: str | None = Query(default=None, max_length=50),
    entity_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_role(Role.MANAGER)),
    session: Session = Depends(get_db_session),
) -> list[AuditEvent]:
    """Newest events first. Filter with e.g. `?entity_type=user&entity_id=3`."""
    return list_events(session, entity_type, entity_id, limit, offset)
