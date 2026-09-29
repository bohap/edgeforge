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


# Tasks are registered exactly once, on a module-level app without a database. Registering
# blueprints again would rename their tasks a second time (add_tasks_from mutates them).
_registry = procrastinate.App(connector=procrastinate.PsycopgConnector())
_registry.add_tasks_from(ops_tasks.blueprint, namespace="ops")
_registry.add_tasks_from(ingestion_tasks.blueprint, namespace="ingest")


def create_app(settings: Settings) -> procrastinate.App:
    """The task registry bound to the configured database."""
    return _registry.with_connector(
        procrastinate.PsycopgConnector(conninfo=libpq_url(settings.database_url))
    )
