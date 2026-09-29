"""Enqueue jobs inside the caller's SQLAlchemy transaction.

Calling Procrastinate's versioned SQL function from the same connection means the job is
committed or rolled back together with the data change that caused it.
"""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_QUEUE = "default"

_DEFER_SQL = text(
    """
    SELECT (procrastinate_defer_jobs_v1(ARRAY[
        ROW(:queue, :task_name, :priority, :lock, :queueing_lock,
            CAST(:args AS jsonb), :scheduled_at)::procrastinate_job_to_defer_v1
    ]))[1]
    """
)


def enqueue_in_session(
    session: Session,
    task_name: str,
    *,
    args: dict[str, Any] | None = None,
    queue: str = DEFAULT_QUEUE,
    priority: int = 0,
    lock: str | None = None,
    queueing_lock: str | None = None,
    scheduled_at: datetime | None = None,
) -> int:
    """Insert a job and return its id. It becomes visible to workers on commit."""
    if scheduled_at is not None and scheduled_at.tzinfo is None:
        raise ValueError("scheduled_at must be timezone-aware")
    job_id: int = session.execute(
        _DEFER_SQL,
        {
            "queue": queue,
            "task_name": task_name,
            "priority": priority,
            "lock": lock,
            "queueing_lock": queueing_lock,
            "args": json.dumps(args or {}),
            "scheduled_at": scheduled_at,
        },
    ).scalar_one()
    return job_id
