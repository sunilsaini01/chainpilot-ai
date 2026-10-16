"""Request and response bodies for the API (Pydantic models).

Kept separate from the database models so the API never exposes columns by
accident; for example, `password_hash` is not in UserOut.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import MovementReason, Role
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


# --- Products and warehouses -------------------------------------------------

# Letters, digits and dashes; stored upper-case (e.g. "SKU-001", "WH-NORTH").
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")


def normalize_code(value: str) -> str:
    """Trim and upper-case a SKU or warehouse code, then check its characters."""
    value = value.strip().upper()
    if not CODE_PATTERN.match(value):
        raise ValueError("must contain only letters, digits and dashes")
    return value


# Money: up to 10 digits before the point and exactly 2 after, never negative.
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    category: str
    unit_cost: Decimal
    unit_price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    unit_cost: Money
    unit_price: Money

    _normalize_sku = field_validator("sku")(normalize_code)


class ProductUpdate(BaseModel):
    """Only the fields that are sent are changed. The SKU cannot be changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    unit_cost: Money | None = None
    unit_price: Money | None = None
    is_active: bool | None = None


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    city: str
    capacity_units: int
    created_at: datetime
    updated_at: datetime


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    capacity_units: int = Field(gt=0, le=100_000_000)

    _normalize_code = field_validator("code")(normalize_code)


class WarehouseUpdate(BaseModel):
    """Only the fields that are sent are changed. The code cannot be changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    capacity_units: int | None = Field(default=None, gt=0, le=100_000_000)


# --- Inventory ---------------------------------------------------------------


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    sku: str
    product_name: str
    warehouse_id: int
    warehouse_code: str
    on_hand: int
    updated_at: datetime


class MovementCreate(BaseModel):
    product_id: int
    warehouse_id: int
    # Positive adds stock, negative removes it. The bound catches typos like 1000000.
    quantity_change: int = Field(ge=-1_000_000, le=1_000_000)
    reason: MovementReason
    reference: str | None = Field(default=None, max_length=100)


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse_id: int
    quantity_change: int
    balance_after: int
    reason: MovementReason
    reference: str | None
    created_by_user_id: int | None
    created_at: datetime


def sent_updates(body: BaseModel) -> dict[str, Any]:
    """The fields a PATCH request actually sent. Raises ValueError if any is null,
    because these columns cannot be empty (leave a field out to keep it unchanged)."""
    sent = body.model_dump(exclude_unset=True)
    nulls = sorted(field for field, value in sent.items() if value is None)
    if nulls:
        raise ValueError(f"These fields cannot be null: {', '.join(nulls)}")
    return sent


# --- Forecasts (M5 public data) ------------------------------------------------


class ForecastRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_key: str
    name: str
    dataset: str
    model: str
    trained_through: date
    forecast_start: date
    forecast_end: date
    horizon_days: int
    series_count: int
    row_count: int
    created_at: datetime


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    series_id: str
    store_id: str
    item_id: str
    dept_id: str
    cat_id: str
    forecast_date: date
    step: int
    forecast: float
    lower: float  # 80% interval
    upper: float
