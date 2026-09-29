"""Operational tasks."""

from datetime import datetime
from typing import Any

import procrastinate
from sqlalchemy import text
from sqlalchemy.orm import Session

from edgeforge.core.db import default_session_factory
from edgeforge.ops.job_runs import run_tracked

blueprint = procrastinate.Blueprint()


@blueprint.task(name="heartbeat", queue="ops")
def heartbeat(note: str = "") -> dict[str, Any]:
    """Proves the queue, a worker and the database work end to end; recorded in ops.job_run."""

    def work(session: Session) -> dict[str, Any]:
        database_time: datetime = session.execute(text("SELECT now()")).scalar_one()
        return {"note": note, "database_time": database_time.isoformat()}

    return run_tracked(default_session_factory(), "ops:heartbeat", {"note": note}, work)
