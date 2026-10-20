"""Read-only view of the job queue for status pages."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# Workers update their heartbeat every 10 seconds by default.
WORKER_ONLINE_WITHIN = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class QueueSummary:
    todo: int
    doing: int
    failed: int


def queue_summary(session: Session, queue: str) -> QueueSummary:
    rows = session.execute(
        text(
            "SELECT status::text AS status, count(*) AS n FROM procrastinate_jobs "
            "WHERE queue_name = :queue AND status IN ('todo', 'doing', 'failed') "
            "GROUP BY status"
        ),
        {"queue": queue},
    ).mappings()
    counts: dict[str, int] = {str(row["status"]): int(row["n"]) for row in rows}
    return QueueSummary(
        todo=counts.get("todo", 0), doing=counts.get("doing", 0), failed=counts.get("failed", 0)
    )


def pending_queueing_locks(session: Session, prefix: str) -> set[str]:
    """Queueing locks of jobs waiting or running whose lock starts with ``prefix``."""
    rows: Sequence[str] = (
        session.execute(
            text(
                "SELECT queueing_lock FROM procrastinate_jobs "
                "WHERE status IN ('todo', 'doing') AND queueing_lock LIKE :pattern"
            ),
            {"pattern": prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"},
        )
        .scalars()
        .all()
    )
    return set(rows)


def workers_online(session: Session) -> int:
    count: int = session.execute(
        text(
            "SELECT count(*) FROM procrastinate_workers "
            "WHERE last_heartbeat > now() - make_interval(secs => :seconds)"
        ),
        {"seconds": WORKER_ONLINE_WITHIN.total_seconds()},
    ).scalar_one()
    return count
