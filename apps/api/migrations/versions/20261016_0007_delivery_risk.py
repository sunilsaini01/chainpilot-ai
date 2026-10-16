"""Delivery-risk runs and scores (Olist public data, imported from the ML pipeline).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delivery_risk_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("dataset", sa.String(200), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_delivery_risk_runs"),
        sa.UniqueConstraint("run_key", name="uq_delivery_risk_runs_run_key"),
    )
    op.create_table(
        "delivery_risk_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(32), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("dispatch_date", sa.Date(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("day_percentile", sa.Float(), nullable=False),
        sa.Column("tier", sa.String(10), nullable=False),
        sa.Column("alert", sa.Boolean(), nullable=False),
        sa.Column("reasons", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_delivery_risk_scores"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["delivery_risk_runs.id"],
            name="fk_delivery_risk_scores_run_id_delivery_risk_runs",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "order_id", name="uq_delivery_risk_scores_run_order"),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name="ck_delivery_risk_scores_probability_range",
        ),
        sa.CheckConstraint(
            "day_percentile > 0 AND day_percentile <= 1",
            name="ck_delivery_risk_scores_percentile_range",
        ),
        sa.CheckConstraint(
            "tier IN ('high', 'medium', 'low')", name="ck_delivery_risk_scores_tier_allowed"
        ),
        sa.CheckConstraint(
            "alert = (tier = 'high')", name="ck_delivery_risk_scores_alert_means_high"
        ),
    )
    op.create_index(
        "ix_delivery_risk_scores_run_day_tier",
        "delivery_risk_scores",
        ["run_id", "dispatch_date", "tier"],
    )


def downgrade() -> None:
    op.drop_table("delivery_risk_scores")
    op.drop_table("delivery_risk_runs")
