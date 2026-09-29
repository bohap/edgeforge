"""raw payload storage

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")

    op.create_table(
        "raw_blob",
        sa.Column("blob_key", sa.String(80), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("blob_key", name="pk_raw_blob"),
        schema="raw",
    )

    op.create_table(
        "raw_payload",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("blob_key", sa.String(80), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_raw_payload"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ref.data_provider.id"],
            name="fk_raw_payload_provider_id_data_provider",
        ),
        sa.ForeignKeyConstraint(
            ["blob_key"], ["raw.raw_blob.blob_key"], name="fk_raw_payload_blob_key_raw_blob"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["raw.raw_payload.id"],
            name="fk_raw_payload_superseded_by_raw_payload",
        ),
        schema="raw",
    )
    op.create_index(
        "ix_raw_payload_provider_resource_key",
        "raw_payload",
        ["provider_id", "resource", "key", "fetched_at"],
        schema="raw",
    )


def downgrade() -> None:
    op.drop_table("raw_payload", schema="raw")
    op.drop_table("raw_blob", schema="raw")
    op.execute("DROP SCHEMA IF EXISTS raw")
