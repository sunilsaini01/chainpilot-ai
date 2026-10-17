"""FastAPI dependencies shared by routes: database sessions, login and role checks.

Two ways to log in to the API:
- Browsers (the dashboard) get an httpOnly cookie at login, which page scripts
  cannot read. A browser sends cookies by itself, so every request that changes
  data must also carry the session's CSRF token in `X-CSRF-Token` (decision D-061).
- Scripts and API clients send `Authorization: Bearer <token>`. Browsers never add
  that header by themselves, so it needs no CSRF token. It wins if both are present.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Role, User
from app.security import csrf_token_matches
from app.users_service import user_for_token

SESSION_COOKIE = "chainpilot_session"
CSRF_HEADER = "X-CSRF-Token"
# Methods that only read; anything else changes data and needs the CSRF token.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# auto_error=False so we return our own 401 (with a consistent message) instead of FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False)


def get_db_session() -> Iterator[Session]:
    """One database session per request, always closed afterwards."""
    session = Session(get_engine())
    try:
        yield session
    finally:
        session.close()


@dataclass(frozen=True)
class SessionToken:
    value: str
    from_cookie: bool  # True: the browser's cookie; False: an Authorization header


def get_session_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> SessionToken:
    """The raw login token of this request, or 401.

    From the Bearer header if there is one, otherwise from the session cookie. A
    cookie request that changes data without the right CSRF token gets 403.
    """
    if credentials is not None:
        return SessionToken(credentials.credentials, from_cookie=False)
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise _not_authenticated()
    if request.method not in SAFE_METHODS and not csrf_token_matches(
        cookie, request.headers.get(CSRF_HEADER)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing or invalid CSRF token"
        )
    return SessionToken(cookie, from_cookie=True)


def get_current_user(
    token: SessionToken = Depends(get_session_token), session: Session = Depends(get_db_session)
) -> User:
    """The logged-in user.

    401 if the token is unknown, expired or revoked, or if the user is inactive.
    """
    user = user_for_token(session, token.value)
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
