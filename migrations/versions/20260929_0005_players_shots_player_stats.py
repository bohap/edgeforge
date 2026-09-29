"""players, shots and player match stats

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
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
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
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


def _small(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.SmallInteger(), nullable=False)


def _float(name: str, *, nullable: bool = True) -> sa.Column[object]:
    return sa.Column(name, sa.Double(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "player",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_player"),
        sa.ForeignKeyConstraint(["sport_id"], ["ref.sport.id"], name="fk_player_sport_id_sport"),
        schema="core",
    )

    op.create_table(
        "player_match_stats",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(), nullable=False),
        sa.Column("started", sa.Boolean(), nullable=False),
        _small("minutes"),
        _small("goals"),
        _small("own_goals"),
        _small("shots"),
        _float("xg"),
        _small("assists"),
        _float("xa"),
        _small("key_passes"),
        _small("yellow_cards"),
        _small("red_cards"),
        _float("xg_chain"),
        _float("xg_buildup"),
        *_timestamps(),
        *_provenance("player_match_stats"),
        sa.PrimaryKeyConstraint("match_id", "player_id", name="pk_player_match_stats"),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.match.id"], name="fk_player_match_stats_match_id_match"
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["core.player.id"], name="fk_player_match_stats_player_id_player"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["core.team.id"], name="fk_player_match_stats_team_id_team"
        ),
        schema="core",
    )
    op.create_index(
        "ix_player_match_stats_player_id", "player_match_stats", ["player_id"], schema="core"
    )

    op.create_table(
        "shot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("assister_name", sa.String(), nullable=True),
        _small("minute"),
        _float("x", nullable=False),
        _float("y", nullable=False),
        _float("xg", nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("situation", sa.String(), nullable=False),
        sa.Column("shot_type", sa.String(), nullable=False),
        sa.Column("last_action", sa.String(), nullable=True),
        sa.Column("is_goal", sa.Boolean(), nullable=False),
        sa.Column("is_penalty", sa.Boolean(), nullable=False),
        *_timestamps(),
        *_provenance("shot"),
        sa.PrimaryKeyConstraint("id", name="pk_shot"),
        sa.ForeignKeyConstraint(["match_id"], ["core.match.id"], name="fk_shot_match_id_match"),
        sa.ForeignKeyConstraint(["team_id"], ["core.team.id"], name="fk_shot_team_id_team"),
        sa.ForeignKeyConstraint(["player_id"], ["core.player.id"], name="fk_shot_player_id_player"),
        sa.UniqueConstraint("provider_id", "external_id", name="uq_shot_provider_id_external_id"),
        schema="core",
    )
    op.create_index("ix_shot_match_id", "shot", ["match_id"], schema="core")
    op.create_index("ix_shot_player_id", "shot", ["player_id"], schema="core")


def downgrade() -> None:
    op.drop_table("shot", schema="core")
    op.drop_table("player_match_stats", schema="core")
    op.drop_table("player", schema="core")
