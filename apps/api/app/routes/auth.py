"""Login, logout and "who am I" endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.audit import record_event
from app.config import get_settings
from app.dependencies import get_bearer_token, get_current_user, get_db_session
from app.login_throttle import RETRY_AFTER_SECONDS, is_login_blocked, record_attempt
from app.models import User
from app.schemas import ChangePasswordRequest, LoginRequest, TokenResponse, UserOut
from app.users_service import (
    WrongPasswordError,
    authenticate,
    change_own_password,
    issue_token,
    revoke_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"description": "Incorrect email or password"},
        429: {"description": "Too many failed attempts; try again later"},
    },
)
def login(
    body: LoginRequest, request: Request, session: Session = Depends(get_db_session)
) -> TokenResponse:
    """Exchange email + password for a bearer token."""
    # Behind a load balancer this is the balancer's address until proxy headers
    # are configured for deployment (P8).
    client_ip = request.client.host if request.client else None

    # Checked before the slow password hash, so a flood of guesses costs little CPU.
    if is_login_blocked(session, body.email, client_ip):
        logger.warning("Login blocked: too many failed attempts")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )

    user = authenticate(session, body.email, body.password)
    if user is None:
        record_attempt(session, body.email, client_ip, succeeded=False)
        session.commit()
        # The email is left out of the log because it is personal data.
        logger.warning("Failed login attempt")
        # One message for every cause, so attackers cannot probe which emails exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    record_attempt(session, body.email, client_ip, succeeded=True)
    raw_token, record = issue_token(session, user, get_settings().access_token_ttl_minutes)
    record_event(session, "user.login", "user", user.id, actor=user)
    session.commit()
    logger.info("User %s logged in", user.id)
    return TokenResponse(
        access_token=raw_token, expires_at=record.expires_at, user=UserOut.model_validate(user)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    token: str = Depends(get_bearer_token),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    """Revoke the token used for this request."""
    revoke_token(session, token)
    record_event(session, "user.logout", "user", user.id, actor=user)
    session.commit()
    logger.info("User %s logged out", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"description": "Current password is incorrect"},
        429: {"description": "Too many failed attempts; try again later"},
    },
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    token: str = Depends(get_bearer_token),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    """Change your own password. Your other sessions are signed out; this one stays."""
    client_ip = request.client.host if request.client else None
    # A wrong current password counts as a failed login, so a stolen session cannot
    # be used to guess the password faster than the login page allows.
    if is_login_blocked(session, user.email, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )
    try:
        signed_out = change_own_password(
            session, user, body.current_password, body.new_password, token
        )
    except WrongPasswordError as error:
        record_attempt(session, user.email, client_ip, succeeded=False)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    record_event(
        session,
        "user.password_changed",
        "user",
        user.id,
        actor=user,
        details={"other_sessions_signed_out": signed_out},
    )
    session.commit()
    logger.info("User %s changed their password", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    """The currently logged-in user."""
    return user
