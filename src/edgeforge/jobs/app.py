"""Procrastinate application factory. Tasks are registered from module blueprints."""

import procrastinate
from sqlalchemy.engine import make_url

from edgeforge.core.config import Settings
from edgeforge.ops import tasks as ops_tasks

# Procrastinate's schema is applied by our Alembic migrations from a vendored copy of this
# exact version. Upgrading the package requires a migration; see tests/db/test_jobs.py.
PROCRASTINATE_SCHEMA_VERSION = "3.10.0"


def libpq_url(sqlalchemy_url: str) -> str:
    """Convert ``postgresql+psycopg://...`` to a plain libpq connection string."""
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


def create_app(settings: Settings) -> procrastinate.App:
    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=libpq_url(settings.database_url))
    )
    app.add_tasks_from(ops_tasks.blueprint, namespace="ops")
    return app
