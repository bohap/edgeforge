"""Job-run ledger: every tracked job leaves a row in ``ops.job_run`` with its outcome."""

from collections.abc import Callable
from typing import Any

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
