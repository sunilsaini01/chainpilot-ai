"""Database triggers that keep updated_at current on every UPDATE.

Without these, updated_at only changed when SQLAlchemy's ORM did the update;
a raw SQL or bulk update would leave it stale (review item P1-T1-R3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES_WITH_UPDATED_AT = ("products", "warehouses", "inventory")


def upgrade() -> None:
    # One shared function: before each row update, stamp the current time.
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
        """
    )
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER trg_{table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"DROP TRIGGER trg_{table}_set_updated_at ON {table}")
    op.execute("DROP FUNCTION set_updated_at()")
