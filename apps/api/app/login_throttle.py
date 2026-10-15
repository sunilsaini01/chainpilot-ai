"""Slowing down password guessing.

Rules, checked before the (deliberately slow) password hash runs:
- one email: at most 5 failed logins in 15 minutes, counted since its last success;
- one client IP: at most 20 failed logins in 15 minutes, across all emails.

Blocks expire on their own after the window, so an attacker can only lock a
real user out for 15 minutes at a time, never permanently.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import LoginAttempt

MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 20
WINDOW = timedelta(minutes=15)
RETRY_AFTER_SECONDS = int(WINDOW.total_seconds())


def normalize_attempt_email(email: str) -> str:
    """Lower-case and trim, so "A@x.com" and "a@x.com" count together. Never fails."""
    return email.strip().lower()[:254]


def _failures_since(session: Session, condition, since: datetime) -> int:
    return session.execute(
        select(func.count())
        .select_from(LoginAttempt)
        .where(condition, LoginAttempt.succeeded.is_(False), LoginAttempt.created_at > since)
    ).scalar_one()


def is_login_blocked(session: Session, email: str, client_ip: str | None) -> bool:
    """True if this email or IP has had too many recent failed logins."""
    email = normalize_attempt_email(email)
    window_start = datetime.now(UTC) - WINDOW

    # A successful login resets the email's count, so a user who mistyped a few
    # times and then got in is not blocked later.
    last_success = session.execute(
        select(func.max(LoginAttempt.created_at)).where(
            LoginAttempt.email == email, LoginAttempt.succeeded.is_(True)
        )
    ).scalar_one()
    email_since = max(window_start, last_success) if last_success else window_start
    if _failures_since(session, LoginAttempt.email == email, email_since) >= MAX_FAILURES_PER_EMAIL:
        return True

    if client_ip is not None:
        ip_failures = _failures_since(session, LoginAttempt.client_ip == client_ip, window_start)
        if ip_failures >= MAX_FAILURES_PER_IP:
            return True
    return False


def record_attempt(session: Session, email: str, client_ip: str | None, succeeded: bool) -> None:
    """Remember an attempt. The caller commits."""
    session.add(
        LoginAttempt(email=normalize_attempt_email(email), client_ip=client_ip, succeeded=succeeded)
    )


def delete_old_attempts(session: Session, older_than: timedelta) -> int:
    """Delete attempts older than `older_than` (they no longer affect blocking). Returns count."""
    cutoff = datetime.now(UTC) - older_than
    result = session.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    return result.rowcount
