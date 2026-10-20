"""Job-run ledger: every tracked job leaves a row in ``ops.job_run`` with its outcome."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.core.logging import get_logger
from edgeforge.core.time import utcnow
from edgeforge.ops.models import JobRun, JobStatus

log = get_logger(__name__)


def run_tracked[T: dict[str, Any]](
    session_factory: sessionmaker[Session],
    job_name: str,
    params: dict[str, Any],
    work: Callable[[Session], T],
) -> T:
    """Run ``work`` in its own transaction and record the run.

    ``work`` returns a stats dict that is stored on the run. If it raises, its transaction is
    rolled back, the failure is recorded in a separate transaction, and the error re-raised.
    """
    with session_factory.begin() as session:
        run = JobRun(
            job_name=job_name, params=params, status=JobStatus.RUNNING, started_at=utcnow()
        )
        session.add(run)
    run_id = run.id
    log.info("job_started", job_name=job_name, job_run_id=str(run_id))

    try:
        with session_factory.begin() as session:
            stats = work(session)
    except Exception as exc:
        with session_factory.begin() as session:
            failed = session.get_one(JobRun, run_id)
            failed.status = JobStatus.FAILED
            failed.finished_at = utcnow()
            failed.error = f"{type(exc).__name__}: {exc}"
        log.exception("job_failed", job_name=job_name, job_run_id=str(run_id))
        raise

    with session_factory.begin() as session:
        done = session.get_one(JobRun, run_id)
        done.status = JobStatus.SUCCEEDED
        done.finished_at = utcnow()
        done.stats = stats
    log.info("job_succeeded", job_name=job_name, job_run_id=str(run_id), **stats)
    return stats


def last_finished(
    session: Session, job_name: str, params: dict[str, Any]
) -> tuple[datetime, JobStatus] | None:
    """When the latest finished run of ``job_name`` with exactly these params ended, and how."""
    row = session.execute(
        select(JobRun.finished_at, JobRun.status)
        .where(
            JobRun.job_name == job_name,
            JobRun.params == params,
            JobRun.finished_at.is_not(None),
        )
        .order_by(JobRun.finished_at.desc())
        .limit(1)
    ).first()
    if row is None or row.finished_at is None:
        return None
    return row.finished_at, row.status
