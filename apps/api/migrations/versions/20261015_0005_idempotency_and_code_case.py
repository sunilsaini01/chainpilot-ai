"""Idempotency key on stock movements; upper-case SKUs and warehouse codes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements", sa.Column("idempotency_key", sa.String(100), nullable=True)
    )
    # Unique, but NULLs do not clash in PostgreSQL, so movements without a key are fine.
    op.create_unique_constraint(
        "uq_inventory_movements_idempotency_key", "inventory_movements", ["idempotency_key"]
    )

    # Existing rows are upper-cased first so the new CHECK constraints hold.
    op.execute("UPDATE products SET sku = upper(sku) WHERE sku <> upper(sku)")
    op.execute("UPDATE warehouses SET code = upper(code) WHERE code <> upper(code)")
    op.create_check_constraint("ck_products_sku_uppercase", "products", "sku = upper(sku)")
    op.create_check_constraint("ck_warehouses_code_uppercase", "warehouses", "code = upper(code)")


def downgrade() -> None:
    op.drop_constraint("ck_warehouses_code_uppercase", "warehouses", type_="check")
    op.drop_constraint("ck_products_sku_uppercase", "products", type_="check")
    op.drop_constraint(
        "uq_inventory_movements_idempotency_key", "inventory_movements", type_="unique"
    )
    op.drop_column("inventory_movements", "idempotency_key")
