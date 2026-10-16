"""Demand-profile links for the demo data, and reorder/transfer recommendations (P4-T4).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("demand_profile_item_id", sa.String(32), nullable=True))
    op.add_column("warehouses", sa.Column("demand_profile_store_id", sa.String(16), nullable=True))
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("source_warehouse_id", sa.Integer(), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("forecast_run_id", sa.Integer(), nullable=False),
        sa.Column("service_level", sa.Numeric(4, 3), nullable=False),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendations"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_recommendations_product_id_products",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_recommendations_warehouse_id_warehouses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_warehouse_id"],
            ["warehouses.id"],
            name="fk_recommendations_source_warehouse_id_warehouses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_recommendations_supplier_id_suppliers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            ["forecast_runs.id"],
            name="fk_recommendations_forecast_run_id_forecast_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_recommendations_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "kind IN ('reorder', 'transfer')", name="ck_recommendations_kind_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'superseded')", name="ck_recommendations_status_allowed"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_recommendations_quantity_positive"),
        sa.CheckConstraint(
            "(kind = 'reorder' AND supplier_id IS NOT NULL AND source_warehouse_id IS NULL) OR "
            "(kind = 'transfer' AND supplier_id IS NULL AND source_warehouse_id IS NOT NULL "
            "AND source_warehouse_id <> warehouse_id)",
            name="ck_recommendations_kind_fields",
        ),
    )
    op.create_index(
        "ix_recommendations_status_created", "recommendations", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_column("warehouses", "demand_profile_store_id")
    op.drop_column("products", "demand_profile_item_id")
