"""Procrastinate application factory. Tasks are registered from module blueprints."""

import procrastinate
from sqlalchemy.engine import make_url

from edgeforge.core.config import Settings
from edgeforge.ingestion import tasks as ingestion_tasks
from edgeforge.ops import tasks as ops_tasks

# Procrastinate's schema is applied by our Alembic migrations from a vendored copy of this
# exact version. Upgrading the package requires a migration; see tests/db/test_jobs.py.
PROCRASTINATE_SCHEMA_VERSION = "3.10.0"


def libpq_url(sqlalchemy_url: str) -> str:
    """Convert ``postgresql+psycopg://...`` to a plain libpq connection string."""
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


# One app per process. Tasks keep a reference to the app they were registered on, and the
# periodic deferrer defers through it, so the app is bound to the database in place rather
# than copied (Procrastinate's deprecated with_connector copies break periodic tasks: the
# deferrer used the copy's never-opened source app and stopped the worker at every tick).
_app = procrastinate.App(connector=procrastinate.PsycopgConnector())
_app.add_tasks_from(ops_tasks.blueprint, namespace="ops")
_app.add_tasks_from(ingestion_tasks.blueprint, namespace="ingest")


def create_app(settings: Settings) -> procrastinate.App:
    """The process-wide app, bound to the configured database."""
    connector = procrastinate.PsycopgConnector(conninfo=libpq_url(settings.database_url))
    _app.connector = connector
    _app.job_manager.connector = connector
    return _app
