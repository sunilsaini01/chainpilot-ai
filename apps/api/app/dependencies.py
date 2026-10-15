"""FastAPI dependencies shared by routes: database sessions, login and role checks."""

from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Role, User
from app.users_service import user_for_token

# auto_error=False so we return our own 401 (with a consistent message) instead of FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False)


def get_db_session() -> Iterator[Session]:
    """One database session per request, always closed afterwards."""
    session = Session(get_engine())
    try:
        yield session
    finally:
        session.close()


def get_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """The raw token from an ``Authorization: Bearer <token>`` header, or 401."""
    if credentials is None:
        raise _not_authenticated()
    return credentials.credentials


def get_current_user(
    token: str = Depends(get_bearer_token), session: Session = Depends(get_db_session)
) -> User:
    """The logged-in user.

    401 if the token is unknown, expired or revoked, or if the user is inactive.
    """
    user = user_for_token(session, token)
    if user is None:
        raise _not_authenticated()
    return user


def require_role(minimum: Role) -> Callable[[User], User]:
    """Dependency factory: allow the request only if the user's role is at least `minimum`.

    Usage: ``user: User = Depends(require_role(Role.ADMIN))``.
    The check runs on the server, so a client cannot skip it.
    """

    def check_role(user: User = Depends(get_current_user)) -> User:
        if not Role(user.role).at_least(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {minimum.value} role or higher",
            )
        return user

    return check_role


def _not_authenticated() -> HTTPException:
    # Same message for every cause, so callers learn nothing about why a token failed.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
