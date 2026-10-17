"""Approval workflow: decisions on recommendations and their outcome (P7-T1).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_recommendations_status_allowed", "recommendations", type_="check")
    op.create_check_constraint(
        "ck_recommendations_status_allowed",
        "recommendations",
        "status IN ('pending', 'superseded', 'rejected', 'executed', 'failed')",
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column(
            "outcome_details", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
        sa.UniqueConstraint("recommendation_id", name="uq_approvals_recommendation_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_approvals_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            name="fk_approvals_recommendation_id_recommendations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name="fk_approvals_decided_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name="fk_approvals_purchase_order_id_purchase_orders",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_approvals_decision_allowed"
        ),
        sa.CheckConstraint(
            "outcome IN ('executed', 'failed')", name="ck_approvals_outcome_allowed"
        ),
        sa.CheckConstraint(
            "(decision = 'approved' AND outcome IS NOT NULL) OR "
            "(decision = 'rejected' AND outcome IS NULL AND comment IS NOT NULL)",
            name="ck_approvals_decision_fields",
        ),
        sa.CheckConstraint(
            "purchase_order_id IS NULL OR outcome = 'executed'",
            name="ck_approvals_order_only_if_executed",
        ),
    )
    op.create_index("ix_approvals_created_at", "approvals", ["created_at"])


def downgrade() -> None:
    op.drop_table("approvals")
    # Decided recommendations cannot be expressed in the old schema; keep them as
    # superseded (no longer pending) rather than losing the rows.
    op.execute(
        "UPDATE recommendations SET status = 'superseded' "
        "WHERE status IN ('rejected', 'executed', 'failed')"
    )
    op.drop_constraint("ck_recommendations_status_allowed", "recommendations", type_="check")
    op.create_check_constraint(
        "ck_recommendations_status_allowed",
        "recommendations",
        "status IN ('pending', 'superseded')",
    )
