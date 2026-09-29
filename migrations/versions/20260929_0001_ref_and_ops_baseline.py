"""ref and ops baseline

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def _jsonb(name: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
    )


def _flag(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.Boolean(), server_default=sa.text("false"), nullable=False)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ref")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        "sport",
        _id(),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        _flag("enabled"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_sport"),
        sa.UniqueConstraint("code", name="uq_sport_code"),
        schema="ref",
    )

    op.create_table(
        "competition",
        _id(),
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("tier", sa.SmallInteger(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        _flag("enabled"),
        _flag("recommendations_enabled"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_competition"),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["ref.sport.id"], name="fk_competition_sport_id_sport"
        ),
        sa.UniqueConstraint("sport_id", "code", name="uq_competition_sport_id_code"),
        sa.CheckConstraint(
            "kind IN ('league', 'cup')", name=op.f("ck_competition_competition_kind")
        ),
        schema="ref",
    )

    op.create_table(
        "season",
        _id(),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        _flag("is_current"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_season"),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["ref.competition.id"], name="fk_season_competition_id_competition"
        ),
        sa.UniqueConstraint("competition_id", "label", name="uq_season_competition_id_label"),
        sa.CheckConstraint("end_date >= start_date", name=op.f("ck_season_dates_ordered")),
        schema="ref",
    )

    op.create_table(
        "data_provider",
        _id(),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        _flag("enabled"),
        sa.Column("reliability_score", sa.Double(), nullable=True),
        _jsonb("config"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_data_provider"),
        sa.UniqueConstraint("code", name="uq_data_provider_code"),
        sa.CheckConstraint(
            "kind IN ('stats', 'odds', 'lineups', 'market')",
            name=op.f("ck_data_provider_provider_kind"),
        ),
        schema="ref",
    )

    op.create_table(
        "provider_entity_map",
        _id(),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("internal_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_provider_entity_map"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ref.data_provider.id"],
            name="fk_provider_entity_map_provider_id_data_provider",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "entity_type",
            "external_id",
            name="uq_provider_entity_map_provider_id_entity_type_external_id",
        ),
        sa.CheckConstraint(
            "method IN ('auto', 'manual')", name=op.f("ck_provider_entity_map_mapping_method")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_provider_entity_map_confidence_range"),
        ),
        schema="ref",
    )
    op.create_index(
        "ix_provider_entity_map_internal_id",
        "provider_entity_map",
        ["internal_id"],
        schema="ref",
    )

    op.create_table(
        "job_run",
        _id(),
        sa.Column("job_name", sa.String(), nullable=False),
        _jsonb("params"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("stats"),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_job_run"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name=op.f("ck_job_run_job_status")
        ),
        schema="ops",
    )
    op.create_index("ix_job_run_job_name", "job_run", ["job_name"], schema="ops")


def downgrade() -> None:
    op.drop_table("job_run", schema="ops")
    op.drop_table("provider_entity_map", schema="ref")
    op.drop_table("data_provider", schema="ref")
    op.drop_table("season", schema="ref")
    op.drop_table("competition", schema="ref")
    op.drop_table("sport", schema="ref")
    op.execute("DROP SCHEMA IF EXISTS ops")
    op.execute("DROP SCHEMA IF EXISTS ref")
