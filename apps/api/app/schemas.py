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


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class SetPasswordRequest(BaseModel):
    """An admin sets a temporary password for a user."""

    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UpdateUserRequest(BaseModel):
    """Only the fields that are sent are changed."""

    role: Role | None = None
    is_active: bool | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    actor_email: str | None  # None for system actions (seed, imports)
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
    supplier_id: int | None
    min_order_qty: int
    pack_size: int
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


# --- Suppliers and purchase orders ------------------------------------------


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    country: str
    lead_time_days: int
    lead_time_std_days: Decimal


class SupplierRiskOut(BaseModel):
    """Delivery performance per supplier (see policies/supplier-performance.md)."""

    model_config = ConfigDict(from_attributes=True)

    supplier_id: int
    code: str
    name: str
    rating: Literal["good", "watch", "at_risk", "not_rated"]
    on_time_rate: float | None
    received_orders: int  # received in the last 90 days
    on_time_orders: int
    average_days_late: float | None
    open_orders: int
    overdue_orders: list[str]  # purchase order numbers


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: int
    unit_cost: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    supplier_id: int
    warehouse_id: int
    status: Literal["open", "received", "cancelled"]
    ordered_date: date
    expected_date: date
    received_date: date | None
    received_by_user_id: int | None
    lines: list[PurchaseOrderLineOut]


# --- Stock-out risks and recommendations (P4-T4) ----------------------------


class RiskOut(BaseModel):
    """One product at one warehouse; see app/replenishment_service.py for the rules."""

    product_id: int
    sku: str
    warehouse_id: int
    warehouse_code: str
    status: Literal["out_of_stock", "at_risk", "ok", "excess"]
    on_hand: int
    on_order: int
    position: int  # on hand + on order
    daily_mean: float  # forecast demand per day (borrowed profile)
    daily_std: float
    lead_time_days: int
    lead_time_std: float
    reorder_point: float
    safety_stock: float
    target_level: int  # order-up-to level
    shortfall: int
    days_of_cover: float | None  # None = no demand expected
    supplier_id: int | None
    min_order_qty: int
    pack_size: int
    demand_profile: str  # M5 item and store whose forecast is borrowed


class RecommendationRequest(BaseModel):
    service_level: float = Field(default=0.95, ge=0.5, lt=1)


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Literal["reorder", "transfer"]
    status: Literal["pending", "superseded", "rejected", "executed", "failed"]
    product_id: int
    warehouse_id: int
    source_warehouse_id: int | None
    supplier_id: int | None
    quantity: int
    reason: str
    forecast_run_id: int
    service_level: Decimal
    details: dict[str, Any]
    created_by_user_id: int | None
    created_at: datetime


# --- Approval workflow (P7) ------------------------------------------------------


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    # Required to reject (checked in the service); optional note when approving.
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, value: str | None) -> str | None:
        # "   " is no reason: treat blank text as no comment.
        if value is None or not value.strip():
            return None
        return value.strip()


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int
    decision: Literal["approved", "rejected"]
    comment: str | None
    decided_by_user_id: int
    decided_by_email: str
    outcome: Literal["executed", "failed"] | None
    outcome_details: dict[str, Any]
    purchase_order_id: int | None
    created_at: datetime


# --- Dashboard (P6) ------------------------------------------------------------


class InventoryKpis(BaseModel):
    products: int
    warehouses: int
    units_on_hand: int
    stock_value: float  # units on hand x unit cost


class DashboardKpisOut(BaseModel):
    label: str  # data label: simulated operations, borrowed demand
    inventory: InventoryKpis
    # Counts per status (out_of_stock, at_risk, ok, excess, unassessed);
    # None when no forecast run is imported (see stock_status_note).
    stock_status: dict[str, int] | None
    stock_status_note: str | None
    forecast_run_id: int | None
    pending_recommendations: dict[str, int]  # reorder, transfer
    purchase_orders: dict[str, int]  # open, overdue
    supplier_ratings: dict[str, int]  # good, watch, at_risk, not_rated


# --- AI copilot (P5) -----------------------------------------------------------


class InvestigateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    status: Literal["completed", "limit_reached", "failed"]
    # {answer, citations, limitations, grounded, unsupported_citations}
    answer: dict[str, Any] | None
    trace: list[dict[str, Any]]
    model: str
    model_calls: int
    tool_calls: int
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int
    error: str | None
    created_by_user_id: int | None
    created_at: datetime


# --- Policies (P5) ------------------------------------------------------------


class PolicyDocumentOut(BaseModel):
    document: str
    title: str
    chunks: int
    sha256: str
    loaded_at: datetime


class PolicyHitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    citation: str  # policy:<document>#<section_slug>
    document: str
    title: str
    section: str
    rank: float
    snippet: str  # matching words marked with <b>...</b>
    content: str


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


# --- Delivery risk (Olist public data) -----------------------------------------


class DeliveryRiskRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_key: str
    name: str
    dataset: str
    model: str
    period_start: date
    period_end: date
    row_count: int
    created_at: datetime


class DeliveryRiskScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    order_id: str
    purchased_at: datetime
    dispatched_at: datetime
    dispatch_date: date
    probability: float  # approximate; tier and day_percentile are the reliable signal
    day_percentile: float
    tier: Literal["high", "medium", "low"]
    alert: bool
    reasons: list[dict[str, Any]]
