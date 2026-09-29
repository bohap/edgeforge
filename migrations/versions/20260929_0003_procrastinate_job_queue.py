"""procrastinate job queue

Applies Procrastinate's schema from the vendored copy in migrations/sql, pinned to the
package version in pyproject.toml. When upgrading Procrastinate, add a new migration that
applies the upstream migration scripts between the two versions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_SQL = Path(__file__).parents[1] / "sql" / "procrastinate_3.10.0_schema.sql"


def _execute_verbatim(sql: str) -> None:
    """Run SQL without any placeholder parsing (the plpgsql bodies contain % and :)."""
    if context.is_offline_mode():
        op.execute(sql)
        return
    cursor = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def upgrade() -> None:
    _execute_verbatim(SCHEMA_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    _execute_verbatim(
        """
        DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers,
            procrastinate_jobs, procrastinate_workers CASCADE;
        DO $$
        DECLARE fn regprocedure;
        BEGIN
            FOR fn IN
                SELECT p.oid::regprocedure FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate%'
            LOOP
                EXECUTE 'DROP FUNCTION ' || fn || ' CASCADE';
            END LOOP;
        END $$;
        DROP TYPE IF EXISTS procrastinate_job_to_defer_v1, procrastinate_job_event_type,
            procrastinate_job_status CASCADE;
        """
    )
