"""Database tables (SQLAlchemy 2.0 declarative models): inventory data, users and logins.

Stock rule: `Inventory.on_hand` is never written directly by application code.
Every change goes through `app.inventory_service.record_movement`, which also
appends a row to `inventory_movements`, so the stock level can always be
explained (and re-computed) from the movement history.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Predictable constraint names, so migrations can refer to them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def updated_at_column() -> Mapped[datetime]:
    """An `updated_at` column maintained by the database.

    A trigger (migration 0002) sets it to now() on every UPDATE, including raw
    SQL and bulk updates that bypass the ORM. FetchedValue tells SQLAlchemy the
    database changes it, so the ORM reloads it instead of keeping a stale value.
    """
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )


class MovementReason(StrEnum):
    """Why stock changed. Stored as text + CHECK constraint (easier to extend than a PG enum)."""

    RECEIPT = "receipt"  # goods arrived from a supplier
    SALE = "sale"  # goods left to a customer
    TRANSFER_IN = "transfer_in"  # arrived from another warehouse
    TRANSFER_OUT = "transfer_out"  # sent to another warehouse
    ADJUSTMENT = "adjustment"  # stock count correction, damage, etc.


def _allowed_reasons_sql() -> str:
    return ", ".join(f"'{reason.value}'" for reason in MovementReason)


class Supplier(Base):
    """A (simulated) supplier and its delivery lead time.

    Lead time = days from placing an order to the goods arriving. The average and
    its standard deviation feed the safety-stock formula (app/inventory_policy.py).
    """

    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint("code = upper(code)", name="code_uppercase"),
        CheckConstraint("lead_time_days >= 1", name="lead_time_positive"),
        CheckConstraint("lead_time_std_days >= 0", name="lead_time_std_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(100))
    lead_time_days: Mapped[int]  # promised / typical lead time
    lead_time_std_days: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = updated_at_column()


class PurchaseOrderStatus(StrEnum):
    OPEN = "open"  # ordered, not yet received: counts as "on order"
    RECEIVED = "received"  # goods booked into stock through the ledger
    CANCELLED = "cancelled"


class PurchaseOrder(Base):
    """An order to one supplier for delivery to one warehouse. Received in full, once."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint("po_number = upper(po_number)", name="po_number_uppercase"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in PurchaseOrderStatus) + ")",
            name="status_allowed",
        ),
        CheckConstraint("expected_date >= ordered_date", name="expected_after_ordered"),
        # received_date is set exactly when the order is received, never before ordering.
        CheckConstraint(
            "(status = 'received') = (received_date IS NOT NULL)", name="received_date_set"
        ),
        CheckConstraint("received_date >= ordered_date", name="received_after_ordered"),
        Index("ix_purchase_orders_status_warehouse", "status", "warehouse_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(32), unique=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20))
    ordered_date: Mapped[date]
    expected_date: Mapped[date]  # ordered_date + the supplier's lead time
    received_date: Mapped[date | None]
    # NULL for system processes (seed); the manager who received it otherwise.
    received_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = updated_at_column()

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", order_by="PurchaseOrderLine.id"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id", "product_id", name="uq_purchase_order_lines_po_product"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
        # "How much of this product is on order?" scans lines by product.
        Index("ix_purchase_order_lines_product", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[int]
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class RecommendationKind(StrEnum):
    REORDER = "reorder"  # buy from the product's supplier
    TRANSFER = "transfer"  # move stock from another warehouse


class RecommendationStatus(StrEnum):
    PENDING = "pending"  # waiting for a manager (approval workflow: P7)
    SUPERSEDED = "superseded"  # replaced by a newer recommendation run


class Recommendation(Base):
    """A proposed reorder or transfer, with the numbers it was based on.

    Only a proposal: nothing changes stock or creates an order until it is
    approved and executed (P7). `details` keeps the inputs (stock, forecast,
    lead time, target level) so every recommendation can be explained.
    """

    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{k.value}'" for k in RecommendationKind) + ")",
            name="kind_allowed",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in RecommendationStatus) + ")",
            name="status_allowed",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        # A reorder names a supplier and no source site; a transfer the opposite.
        CheckConstraint(
            "(kind = 'reorder' AND supplier_id IS NOT NULL AND source_warehouse_id IS NULL) OR "
            "(kind = 'transfer' AND supplier_id IS NULL AND source_warehouse_id IS NOT NULL "
            "AND source_warehouse_id <> warehouse_id)",
            name="kind_fields",
        ),
        Index("ix_recommendations_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=RecommendationStatus.PENDING)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[int] = mapped_column(  # where the stock is needed
        ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    source_warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    quantity: Mapped[int]
    reason: Mapped[str] = mapped_column(String(30))  # e.g. "ordered", "raised_to_moq"
    forecast_run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="RESTRICT")
    )
    service_level: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    details: Mapped[dict] = mapped_column(JSONB)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        # SKUs are stored upper-case so "sku-1" and "SKU-1" cannot both exist.
        CheckConstraint("sku = upper(sku)", name="sku_uppercase"),
        CheckConstraint("min_order_qty >= 1", name="min_order_qty_positive"),
        CheckConstraint("pack_size >= 1", name="pack_size_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    # Numeric (not float) so money values are exact.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    # Purchasing rules (P4): who supplies it and in what quantities it can be ordered.
    # A product without a supplier cannot be reordered automatically.
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    min_order_qty: Mapped[int] = mapped_column(default=1, server_default="1")
    pack_size: Mapped[int] = mapped_column(default=1, server_default="1")
    # DEMO LINK (D-044): the M5 item whose forecast stands in for this simulated
    # product's demand. Not the same product or company; always shown as borrowed.
    demand_profile_item_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = updated_at_column()


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        CheckConstraint("capacity_units > 0", name="capacity_positive"),
        CheckConstraint("code = upper(code)", name="code_uppercase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    # Total units the site can hold; used later for capacity-aware reorder decisions.
    capacity_units: Mapped[int]
    # DEMO LINK (D-044): the M5 store whose forecasts stand in for this site's demand.
    demand_profile_store_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = updated_at_column()


class Inventory(Base):
    """Current stock of one product in one warehouse."""

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        # Last line of defence: the database itself refuses negative stock.
        CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    on_hand: Mapped[int] = mapped_column(default=0, server_default="0")
    updated_at: Mapped[datetime] = updated_at_column()


class InventoryMovement(Base):
    """Append-only ledger entry: one change to one product's stock in one warehouse."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="quantity_change_non_zero"),
        CheckConstraint("balance_after >= 0", name="balance_after_non_negative"),
        CheckConstraint(f"reason IN ({_allowed_reasons_sql()})", name="reason_allowed"),
        # Speeds up "history of this product at this warehouse, newest first".
        Index(
            "ix_inventory_movements_product_warehouse_time",
            "product_id",
            "warehouse_id",
            "created_at",
        ),
    )

    # BigInteger: the ledger grows much faster than the other tables.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    quantity_change: Mapped[int]  # positive = stock in, negative = stock out
    balance_after: Mapped[int]  # on_hand right after this movement, for easy auditing
    reason: Mapped[str] = mapped_column(String(20))
    # Optional link to the business document, e.g. a purchase order or sales order number.
    reference: Mapped[str | None] = mapped_column(String(100))
    # Who made the change. NULL only for system processes (e.g. synthetic seed data).
    # RESTRICT: a user with stock history cannot be deleted (deactivate them instead).
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # Optional client-supplied key: retrying a request with the same key does not
    # apply the stock change twice (see inventory_service.record_movement_once).
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(StrEnum):
    """User roles, lowest to highest privilege. Each role can do everything the roles below it can.

    analyst: read data.  manager: also approve actions.  admin: also manage users.
    """

    ANALYST = "analyst"
    MANAGER = "manager"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return list(Role).index(self)

    def at_least(self, minimum: "Role") -> bool:
        return self.rank >= minimum.rank


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN (" + ", ".join(f"'{role.value}'" for role in Role) + ")",
            name="role_allowed",
        ),
        # Emails are stored lower-case so "A@x.com" and "a@x.com" are one account.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    # scrypt hash from app.security.hash_password; never the password itself.
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = updated_at_column()


class AuthToken(Base):
    """A login session. Only the SHA-256 hash of the token is stored."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set on logout; a revoked token is rejected even before it expires.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    """One login attempt, used to slow down password guessing (see app/login_throttle.py)."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_created_at", "email", "created_at"),
        Index("ix_login_attempts_client_ip_created_at", "client_ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The email as typed (normalized); it may not belong to any account.
    email: Mapped[str] = mapped_column(String(254))
    client_ip: Mapped[str | None] = mapped_column(String(45))  # 45 fits any IPv6 address
    succeeded: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """Append-only record of who did what, when. Written in the same transaction as the change."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL for system actions. RESTRICT keeps the history of users who acted.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(50))  # e.g. "user.created"
    entity_type: Mapped[str] = mapped_column(String(50))  # e.g. "user"
    entity_id: Mapped[str | None] = mapped_column(String(64))
    # Extra facts, e.g. {"changes": {"role": ["analyst", "manager"]}}. Never secrets.
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForecastRun(Base):
    """One imported forecast file (see ml/demand_forecasting/publish.py).

    DATA LABEL: forecasts are for the public M5 (Walmart) dataset, identified by
    M5 series ids. They are never joined to the simulated SYN- products.
    """

    __tablename__ = "forecast_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # From the file's manifest; importing the same file twice is refused.
    run_key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    dataset: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(50))
    trained_through: Mapped[date]
    forecast_start: Mapped[date]
    forecast_end: Mapped[date]
    horizon_days: Mapped[int]
    series_count: Mapped[int]
    row_count: Mapped[int]
    manifest: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Forecast(Base):
    """Forecast for one M5 series on one future day, with an 80% interval."""

    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "series_id", "forecast_date", name="uq_forecasts_run_series_date"
        ),
        CheckConstraint(
            "lower >= 0 AND lower <= forecast AND forecast <= upper", name="interval_ordered"
        ),
        CheckConstraint("step BETWEEN 1 AND 28", name="step_range"),
        # The common query: one run, one store (and maybe one item).
        Index("ix_forecasts_run_store_item", "run_id", "store_id", "item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    series_id: Mapped[str] = mapped_column(String(64))  # e.g. FOODS_3_090_CA_1_validation
    store_id: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(32))
    dept_id: Mapped[str] = mapped_column(String(32))
    cat_id: Mapped[str] = mapped_column(String(32))
    forecast_date: Mapped[date]
    step: Mapped[int]  # days after the last known day (1 = next day)
    forecast: Mapped[float]
    lower: Mapped[float]
    upper: Mapped[float]


class DeliveryRiskRun(Base):
    """One imported delivery-risk scoring file (ml/delivery_risk/scoring.py).

    DATA LABEL: Olist public marketplace orders, not ChainPilot's simulated suppliers.
    """

    __tablename__ = "delivery_risk_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    dataset: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(100))
    period_start: Mapped[date]
    period_end: Mapped[date]
    row_count: Mapped[int]
    manifest: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryRiskScore(Base):
    """Late-delivery risk of one dispatched order, as known at dispatch."""

    __tablename__ = "delivery_risk_scores"
    __table_args__ = (
        UniqueConstraint("run_id", "order_id", name="uq_delivery_risk_scores_run_order"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="probability_range"),
        CheckConstraint("day_percentile > 0 AND day_percentile <= 1", name="percentile_range"),
        CheckConstraint("tier IN ('high', 'medium', 'low')", name="tier_allowed"),
        CheckConstraint("alert = (tier = 'high')", name="alert_means_high"),
        # The common query: one run, one dispatch day, maybe one tier.
        Index("ix_delivery_risk_scores_run_day_tier", "run_id", "dispatch_date", "tier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("delivery_risk_runs.id", ondelete="CASCADE"))
    order_id: Mapped[str] = mapped_column(String(32))  # Olist order id
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    dispatch_date: Mapped[date]
    probability: Mapped[float]  # approximate (see docs/MODEL_RESULTS.md)
    day_percentile: Mapped[float]  # rank among the same day's dispatches
    tier: Mapped[str] = mapped_column(String(10))
    alert: Mapped[bool]
    # Top 3 reasons from the model, e.g.
    # [{"feature": "distance_km", "value": 2808.4, "effect": 1.27}]
    reasons: Mapped[list] = mapped_column(JSONB)
