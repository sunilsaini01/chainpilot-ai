"""Database tables (SQLAlchemy 2.0 declarative models): inventory data, users and logins.

Stock rule: `Inventory.on_hand` is never written directly by application code.
Every change goes through `app.inventory_service.record_movement`, which also
appends a row to `inventory_movements`, so the stock level can always be
explained (and re-computed) from the movement history.
"""

from datetime import datetime
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        # SKUs are stored upper-case so "sku-1" and "SKU-1" cannot both exist.
        CheckConstraint("sku = upper(sku)", name="sku_uppercase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    # Numeric (not float) so money values are exact.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
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
