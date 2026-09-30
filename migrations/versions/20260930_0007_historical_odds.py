"""mkt.historical_odds

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mkt")
    op.create_table(
        "historical_odds",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("bookmaker", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("params_key", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("opening", sa.Double(), nullable=True),
        sa.Column("closing", sa.Double(), nullable=True),
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
            "bookmaker",
            "market_code",
            "params_key",
            "outcome",
            name="pk_historical_odds",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.match.id"], name="fk_historical_odds_match_id_match"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ref.data_provider.id"],
            name="fk_historical_odds_provider_id_data_provider",
        ),
        sa.ForeignKeyConstraint(
            ["source_raw_id"],
            ["raw.raw_payload.id"],
            name="fk_historical_odds_source_raw_id_raw_payload",
        ),
        schema="mkt",
    )


def downgrade() -> None:
    op.drop_table("historical_odds", schema="mkt")
    op.execute("DROP SCHEMA IF EXISTS mkt")
