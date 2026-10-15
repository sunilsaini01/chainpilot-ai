"""Core inventory tables: products, warehouses, inventory, inventory_movements.

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_products_unit_cost_non_negative"),
        sa.CheckConstraint("unit_price >= 0", name="ck_products_unit_price_non_negative"),
    )

    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("capacity_units", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouses"),
        sa.UniqueConstraint("code", name="uq_warehouses_code"),
        sa.CheckConstraint("capacity_units > 0", name="ck_warehouses_capacity_positive"),
    )

    op.create_table(
        "inventory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("on_hand", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inventory"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_inventory_product_id_products",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_inventory_warehouse_id_warehouses",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        sa.CheckConstraint("on_hand >= 0", name="ck_inventory_on_hand_non_negative"),
    )
    op.create_index("ix_inventory_warehouse_id", "inventory", ["warehouse_id"])

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("quantity_change", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_movements"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_inventory_movements_product_id_products",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_inventory_movements_warehouse_id_warehouses",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "quantity_change <> 0", name="ck_inventory_movements_quantity_change_non_zero"
        ),
        sa.CheckConstraint(
            "balance_after >= 0", name="ck_inventory_movements_balance_after_non_negative"
        ),
        sa.CheckConstraint(
            "reason IN ('receipt', 'sale', 'transfer_in', 'transfer_out', 'adjustment')",
            name="ck_inventory_movements_reason_allowed",
        ),
    )
    op.create_index("ix_inventory_movements_warehouse_id", "inventory_movements", ["warehouse_id"])
    op.create_index(
        "ix_inventory_movements_product_warehouse_time",
        "inventory_movements",
        ["product_id", "warehouse_id", "created_at"],
    )


def downgrade() -> None:
    # Reverse order of creation, because of the foreign keys.
    op.drop_table("inventory_movements")
    op.drop_table("inventory")
    op.drop_table("warehouses")
    op.drop_table("products")
