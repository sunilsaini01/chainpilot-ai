"""User management endpoints (admin only)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.dependencies import get_db_session, require_role
from app.models import Role, User
from app.schemas import CreateUserRequest, UpdateUserRequest, UserOut
from app.users_service import LastAdminError, UserAlreadyExistsError, create_user, update_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> list[User]:
    """List users, oldest first, one page at a time."""
    return list(
        session.execute(select(User).order_by(User.id).limit(limit).offset(offset)).scalars()
    )


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Email already registered"}},
)
def add_user(
    body: CreateUserRequest,
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> User:
    """Create a user account."""
    try:
        user = create_user(session, body.email, body.full_name, body.role, body.password)
    except UserAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    record_event(
        session,
        "user.created",
        "user",
        user.id,
        actor=admin,
        details={"email": user.email, "role": user.role},
    )
    session.commit()
    logger.info("Admin %s created user %s with role %s", admin.id, user.id, user.role)
    return user


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    responses={404: {"description": "User not found"}, 409: {"description": "Last active admin"}},
)
def change_user(
    user_id: int,
    body: UpdateUserRequest,
    admin: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db_session),
) -> User:
    """Change a user's role, name, or active flag. Deactivated users cannot log in,
    and their existing tokens stop working immediately."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        changes = update_user(
            session, user, role=body.role, is_active=body.is_active, full_name=body.full_name
        )
    except LastAdminError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    if changes:  # nothing to audit if the request changed nothing
        record_event(
            session, "user.updated", "user", user.id, actor=admin, details={"changes": changes}
        )
    session.commit()
    logger.info("Admin %s updated user %s: %s", admin.id, user.id, sorted(changes))
    return user
