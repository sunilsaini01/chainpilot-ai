"""Suppliers, purchasing rules on products, purchase orders and their lines (P4-T3).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same trigger as migration 0002: updated_at changes on every UPDATE.
TABLES_WITH_UPDATED_AT = ("suppliers", "purchase_orders")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("lead_time_std_days", sa.Numeric(5, 2), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_suppliers"),
        sa.UniqueConstraint("code", name="uq_suppliers_code"),
        sa.CheckConstraint("code = upper(code)", name="ck_suppliers_code_uppercase"),
        sa.CheckConstraint("lead_time_days >= 1", name="ck_suppliers_lead_time_positive"),
        sa.CheckConstraint(
            "lead_time_std_days >= 0", name="ck_suppliers_lead_time_std_non_negative"
        ),
    )

    op.add_column("products", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.add_column(
        "products",
        sa.Column("min_order_qty", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "products", sa.Column("pack_size", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_foreign_key(
        "fk_products_supplier_id_suppliers",
        "products",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_products_supplier_id", "products", ["supplier_id"])
    op.create_check_constraint("min_order_qty_positive", "products", "min_order_qty >= 1")
    op.create_check_constraint("pack_size_positive", "products", "pack_size >= 1")

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("po_number", sa.String(32), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("ordered_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=True),
        sa.Column("received_by_user_id", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_orders"),
        sa.UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_purchase_orders_supplier_id_suppliers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_purchase_orders_warehouse_id_warehouses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_user_id"],
            ["users.id"],
            name="fk_purchase_orders_received_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "po_number = upper(po_number)", name="ck_purchase_orders_po_number_uppercase"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'received', 'cancelled')", name="ck_purchase_orders_status_allowed"
        ),
        sa.CheckConstraint(
            "expected_date >= ordered_date", name="ck_purchase_orders_expected_after_ordered"
        ),
        sa.CheckConstraint(
            "(status = 'received') = (received_date IS NOT NULL)",
            name="ck_purchase_orders_received_date_set",
        ),
        sa.CheckConstraint(
            "received_date >= ordered_date", name="ck_purchase_orders_received_after_ordered"
        ),
    )
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index(
        "ix_purchase_orders_status_warehouse", "purchase_orders", ["status", "warehouse_id"]
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_order_lines"),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name="fk_purchase_order_lines_purchase_order_id_purchase_orders",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_purchase_order_lines_product_id_products",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "purchase_order_id", "product_id", name="uq_purchase_order_lines_po_product"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_order_lines_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_purchase_order_lines_unit_cost_non_negative"),
    )
    op.create_index("ix_purchase_order_lines_product", "purchase_order_lines", ["product_id"])

    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER trg_{table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
    op.drop_constraint("pack_size_positive", "products", type_="check")
    op.drop_constraint("min_order_qty_positive", "products", type_="check")
    op.drop_index("ix_products_supplier_id", table_name="products")
    op.drop_constraint("fk_products_supplier_id_suppliers", "products", type_="foreignkey")
    op.drop_column("products", "pack_size")
    op.drop_column("products", "min_order_qty")
    op.drop_column("products", "supplier_id")
    op.drop_table("suppliers")
