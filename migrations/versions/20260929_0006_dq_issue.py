"""data-quality issues

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dq_issue",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("check_code", sa.String(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dq_issue"),
        sa.CheckConstraint(
            "severity IN ('warning', 'error')", name=op.f("ck_dq_issue_dq_severity")
        ),
        schema="ops",
    )
    op.create_index(
        "uq_dq_issue_open",
        "dq_issue",
        ["check_code", "entity_type", "entity_id"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("dq_issue", schema="ops")
