"""Forecast runs and forecasts (M5 public data, imported from the ML pipeline).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("dataset", sa.String(200), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("trained_through", sa.Date(), nullable=False),
        sa.Column("forecast_start", sa.Date(), nullable=False),
        sa.Column("forecast_end", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("series_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_forecast_runs"),
        sa.UniqueConstraint("run_key", name="uq_forecast_runs_run_key"),
    )
    op.create_table(
        "forecasts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(16), nullable=False),
        sa.Column("item_id", sa.String(32), nullable=False),
        sa.Column("dept_id", sa.String(32), nullable=False),
        sa.Column("cat_id", sa.String(32), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("forecast", sa.Float(), nullable=False),
        sa.Column("lower", sa.Float(), nullable=False),
        sa.Column("upper", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_forecasts"),
        # Deleting a run deletes its forecasts.
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["forecast_runs.id"],
            name="fk_forecasts_run_id_forecast_runs",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id", "series_id", "forecast_date", name="uq_forecasts_run_series_date"
        ),
        sa.CheckConstraint(
            "lower >= 0 AND lower <= forecast AND forecast <= upper",
            name="ck_forecasts_interval_ordered",
        ),
        sa.CheckConstraint("step BETWEEN 1 AND 28", name="ck_forecasts_step_range"),
    )
    op.create_index("ix_forecasts_run_store_item", "forecasts", ["run_id", "store_id", "item_id"])


def downgrade() -> None:
    op.drop_table("forecasts")
    op.drop_table("forecast_runs")
