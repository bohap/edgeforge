"""core football schema: teams, team seasons, matches, results, team match stats

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _provenance(table: str) -> list[sa.SchemaItem]:
    return [
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("source_raw_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ref.data_provider.id"],
            name=f"fk_{table}_provider_id_data_provider",
        ),
        sa.ForeignKeyConstraint(
            ["source_raw_id"],
            ["raw.raw_payload.id"],
            name=f"fk_{table}_source_raw_id_raw_payload",
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    op.create_table(
        "team",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("short_name", sa.String(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_team"),
        sa.ForeignKeyConstraint(["sport_id"], ["ref.sport.id"], name="fk_team_sport_id_sport"),
        schema="core",
    )

    op.create_table(
        "team_season",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("team_id", "season_id", name="pk_team_season"),
        sa.ForeignKeyConstraint(["team_id"], ["core.team.id"], name="fk_team_season_team_id_team"),
        sa.ForeignKeyConstraint(
            ["season_id"], ["ref.season.id"], name="fk_team_season_season_id_season"
        ),
        schema="core",
    )

    op.create_table(
        "match",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("home_team_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_id", sa.Uuid(), nullable=False),
        sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
        *_provenance("match"),
        sa.PrimaryKeyConstraint("id", name="pk_match"),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["ref.competition.id"], name="fk_match_competition_id_competition"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["ref.season.id"], name="fk_match_season_id_season"),
        sa.ForeignKeyConstraint(
            ["home_team_id"], ["core.team.id"], name="fk_match_home_team_id_team"
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"], ["core.team.id"], name="fk_match_away_team_id_team"
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'finished')", name=op.f("ck_match_match_status")
        ),
        schema="core",
    )
    op.create_index("ix_match_season_id", "match", ["season_id"], schema="core")
    op.create_index("ix_match_kickoff_at", "match", ["kickoff_at"], schema="core")

    op.create_table(
        "match_result",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("home_goals", sa.SmallInteger(), nullable=False),
        sa.Column("away_goals", sa.SmallInteger(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        *_provenance("match_result"),
        sa.PrimaryKeyConstraint("match_id", name="pk_match_result"),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.match.id"], name="fk_match_result_match_id_match"
        ),
        schema="core",
    )

    op.create_table(
        "match_team_stats",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=False),
        sa.Column("goals", sa.SmallInteger(), nullable=False),
        sa.Column("xg", sa.Double(), nullable=True),
        sa.Column("npxg", sa.Double(), nullable=True),
        sa.Column("ppda_passes", sa.Integer(), nullable=True),
        sa.Column("ppda_defensive_actions", sa.Integer(), nullable=True),
        sa.Column("deep_completions", sa.Integer(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        *_provenance("match_team_stats"),
        sa.PrimaryKeyConstraint("match_id", "team_id", name="pk_match_team_stats"),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.match.id"], name="fk_match_team_stats_match_id_match"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["core.team.id"], name="fk_match_team_stats_team_id_team"
        ),
        sa.UniqueConstraint("match_id", "is_home", name="uq_match_team_stats_match_id_is_home"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("match_team_stats", schema="core")
    op.drop_table("match_result", schema="core")
    op.drop_table("match", schema="core")
    op.drop_table("team_season", schema="core")
    op.drop_table("team", schema="core")
    op.execute("DROP SCHEMA IF EXISTS core")
