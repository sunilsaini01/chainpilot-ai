"""Creating users, checking passwords, and managing login tokens.

Functions here never commit; the caller (an API route or the CLI) decides when.
"""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuthToken, Role, User
from app.security import (
    DUMMY_PASSWORD_HASH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)

# Deliberately simple: one "@", something on both sides, a dot in the domain.
# Full email validation is famously complex and not needed for an internal tool.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254


class UserAlreadyExistsError(Exception):
    """Raised when creating a user whose email is already registered."""


def normalize_email(email: str) -> str:
    """Trim and lower-case an email, and check its basic shape. Raises ValueError."""
    normalized = email.strip().lower()
    if len(normalized) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(normalized):
        raise ValueError("Invalid email address")
    return normalized


def validate_password(password: str) -> None:
    """Enforce the password length policy. Raises ValueError."""
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters long"
        )


def create_user(session: Session, email: str, full_name: str, role: Role, password: str) -> User:
    """Create a user with a hashed password.

    Raises ValueError for invalid input and UserAlreadyExistsError for a taken email.
    """
    email = normalize_email(email)
    full_name = full_name.strip()
    if not full_name:
        raise ValueError("Full name must not be empty")
    role = Role(role)  # raises ValueError for an unknown role
    validate_password(password)

    user = User(
        email=email, full_name=full_name, role=role.value, password_hash=hash_password(password)
    )
    try:
        # A savepoint, so a duplicate email only undoes this insert, not the caller's
        # whole transaction. The unique constraint also covers two requests racing.
        with session.begin_nested():
            session.add(user)
    except IntegrityError as error:
        raise UserAlreadyExistsError(f"A user with email {email} already exists") from error
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    """Return the user if the email and password are correct and the account is active.

    Every failure path runs one password hash, so response time does not reveal
    whether an email is registered.
    """
    try:
        email = normalize_email(email)
    except ValueError:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None

    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def issue_token(session: Session, user: User, ttl_minutes: int) -> tuple[str, AuthToken]:
    """Create a login token. Returns (raw token for the client, stored record)."""
    raw_token = generate_token()
    record = AuthToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    )
    session.add(record)
    session.flush()
    return raw_token, record


def user_for_token(session: Session, raw_token: str) -> User | None:
    """Return the active user who owns a valid (not expired, not revoked) token."""
    return session.execute(
        select(User)
        .join(AuthToken, AuthToken.user_id == User.id)
        .where(
            AuthToken.token_hash == hash_token(raw_token),
            AuthToken.revoked_at.is_(None),
            AuthToken.expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
    ).scalar_one_or_none()


def revoke_token(session: Session, raw_token: str) -> None:
    """Log out: mark the token revoked so it stops working immediately."""
    session.execute(
        update(AuthToken)
        .where(AuthToken.token_hash == hash_token(raw_token), AuthToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


class LastAdminError(Exception):
    """Raised when a change would leave no active admin (nobody could manage users)."""


def update_user(
    session: Session,
    user: User,
    role: Role | None = None,
    is_active: bool | None = None,
    full_name: str | None = None,
) -> dict[str, list]:
    """Change a user's role, active flag or name. Returns {field: [old, new]} for what changed.

    Raises LastAdminError if the change would remove the last active admin.
    """
    changes: dict[str, list] = {}
    if role is not None and Role(role).value != user.role:
        changes["role"] = [user.role, Role(role).value]
    if is_active is not None and is_active != user.is_active:
        changes["is_active"] = [user.is_active, is_active]
    if full_name is not None:
        full_name = full_name.strip()
        if not full_name:
            raise ValueError("Full name must not be empty")
        if full_name != user.full_name:
            changes["full_name"] = [user.full_name, full_name]

    # An active admin who is demoted or deactivated stops being an active admin.
    loses_admin = (
        user.role == Role.ADMIN.value
        and user.is_active
        and ("role" in changes or "is_active" in changes)
    )
    if loses_admin:
        # Lock every active admin row first, so two admins demoting each other at the
        # same moment cannot both pass this check and leave zero admins.
        active_admin_ids = (
            session.execute(
                select(User.id)
                .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
                .with_for_update()
            )
            .scalars()
            .all()
        )
        if set(active_admin_ids) <= {user.id}:
            raise LastAdminError("Cannot remove the last active admin")

    if "role" in changes:
        user.role = changes["role"][1]
    if "is_active" in changes:
        user.is_active = changes["is_active"][1]
    if "full_name" in changes:
        user.full_name = changes["full_name"][1]
    session.flush()
    return changes


def delete_stale_tokens(session: Session, older_than: timedelta) -> int:
    """Delete tokens that expired or were revoked more than `older_than` ago. Returns count."""
    cutoff = datetime.now(UTC) - older_than
    result = session.execute(
        delete(AuthToken).where(or_(AuthToken.expires_at < cutoff, AuthToken.revoked_at < cutoff))
    )
    return result.rowcount
