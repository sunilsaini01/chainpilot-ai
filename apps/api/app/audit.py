"""Writing and reading audit events.

`record_event` only adds the row to the session; it is committed together with
the change it describes, so a change and its audit record succeed or fail together.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record_event(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: int | str | None,
    actor: User | None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event. Never put passwords, tokens or hashes in `details`."""
    event = AuditEvent(
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        actor_user_id=actor.id if actor is not None else None,
        details=details or {},
    )
    session.add(event)
    return event


def list_events(
    session: Session,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Newest events first, optionally only those about one entity type or entity."""
    query = select(AuditEvent)
    if entity_type is not None:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditEvent.entity_id == entity_id)
    # id breaks ties between events from the same transaction (same created_at).
    query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    return list(session.execute(query.limit(limit).offset(offset)).scalars())
