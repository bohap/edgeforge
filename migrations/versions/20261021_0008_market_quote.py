"""mkt.market_quote

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_quote",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("params_key", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("best_bid", sa.Double(), nullable=True),
        sa.Column("best_ask", sa.Double(), nullable=True),
        sa.Column("last_price", sa.Double(), nullable=True),
        sa.Column("liquidity", sa.Double(), nullable=True),
        sa.Column("fee_rate", sa.Double(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("event_slug", sa.String(), nullable=False),
        sa.Column("source_raw_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "match_id",
            "provider_id",
            "market_code",
            "params_key",
            "outcome",
            name="pk_market_quote",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.match.id"], name="fk_market_quote_match_id_match"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ref.data_provider.id"],
            name="fk_market_quote_provider_id_data_provider",
        ),
        sa.ForeignKeyConstraint(
            ["source_raw_id"],
            ["raw.raw_payload.id"],
            name="fk_market_quote_source_raw_id_raw_payload",
        ),
        schema="mkt",
    )


def downgrade() -> None:
    op.drop_table("market_quote", schema="mkt")
