"""Request and response bodies for the API (Pydantic models).

Kept separate from the database models so the API never exposes columns by
accident; for example, `password_hash` is not in UserOut.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Role
from app.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.users_service import MAX_EMAIL_LENGTH


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    # No minimum here: a short wrong password should get the normal 401, not a 422.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


class CreateUserRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UpdateUserRequest(BaseModel):
    """Only the fields that are sent are changed."""

    role: Role | None = None
    is_active: bool | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any]
    created_at: datetime
