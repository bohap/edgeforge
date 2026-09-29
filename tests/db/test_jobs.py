from collections.abc import Iterator
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.core.config import get_settings
from edgeforge.core.db import create_session_factory, default_session_factory
from edgeforge.jobs.app import PROCRASTINATE_SCHEMA_VERSION, create_app, libpq_url
from edgeforge.jobs.enqueue import enqueue_in_session
from edgeforge.ops.job_runs import run_tracked
from edgeforge.ops.models import JobRun, JobStatus

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]


def _clear_jobs(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM procrastinate_events"))
        conn.execute(text("DELETE FROM procrastinate_jobs"))
        conn.execute(delete(JobRun))


@pytest.fixture
def committed(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Session factory whose commits are real; cleans up jobs and runs afterwards."""
    _clear_jobs(migrated_engine)
    yield create_session_factory(migrated_engine)
    _clear_jobs(migrated_engine)


@pytest.fixture
def worker_settings(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("EDGEFORGE_DATABASE_URL", database_url)
    get_settings.cache_clear()
    default_session_factory.cache_clear()
    yield
    if default_session_factory.cache_info().currsize:
        bind = default_session_factory().kw["bind"]
        bind.dispose()
    get_settings.cache_clear()
    default_session_factory.cache_clear()


def test_vendored_schema_matches_pinned_package_version() -> None:
    vendored = (
        REPO_ROOT
        / "migrations"
        / "sql"
        / f"procrastinate_{PROCRASTINATE_SCHEMA_VERSION}_schema.sql"
    )
    packaged = files("procrastinate").joinpath("sql/schema.sql").read_text(encoding="utf-8")

    assert version("procrastinate") == PROCRASTINATE_SCHEMA_VERSION, (
        "Procrastinate was upgraded: add a migration applying its upstream migration scripts, "
        "vendor the new schema.sql and update PROCRASTINATE_SCHEMA_VERSION."
    )
    assert vendored.read_text(encoding="utf-8") == packaged


def test_libpq_url_drops_the_sqlalchemy_driver() -> None:
    assert libpq_url("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_rolled_back_transaction_discards_its_job(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        job_id = enqueue_in_session(session, "ops:heartbeat", args={"note": "x"}, queue="ops")
        visible_inside = session.execute(
            text("SELECT count(*) FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
        ).scalar_one()
        session.rollback()

    with migrated_engine.connect() as conn:
        after = conn.execute(
            text("SELECT count(*) FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
        ).scalar_one()
    assert (visible_inside, after) == (1, 0)


def test_queueing_lock_prevents_duplicate_pending_jobs(db_session: Session) -> None:
    enqueue_in_session(db_session, "ops:heartbeat", queueing_lock="fixtures:EPL")

    with pytest.raises(Exception, match="procrastinate_jobs_queueing_lock_idx"):
        enqueue_in_session(db_session, "ops:heartbeat", queueing_lock="fixtures:EPL")


def test_worker_runs_committed_job_and_records_it(
    committed: sessionmaker[Session], worker_settings: None
) -> None:
    with committed.begin() as session:
        job_id = enqueue_in_session(session, "ops:heartbeat", args={"note": "ci"}, queue="ops")

    create_app(get_settings()).run_worker(
        queues=["ops"], wait=False, install_signal_handlers=False, listen_notify=False
    )

    with committed() as session:
        status = session.execute(
            text("SELECT status::text FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
        ).scalar_one()
        run = session.scalars(select(JobRun)).one()
    assert status == "succeeded"
    assert run.job_name == "ops:heartbeat"
    assert run.status is JobStatus.SUCCEEDED
    assert run.stats["note"] == "ci"
    assert run.finished_at is not None


def test_run_tracked_records_failure_and_reraises(committed: sessionmaker[Session]) -> None:
    def work(session: Session) -> dict[str, Any]:
        session.execute(text("SELECT 1"))
        raise RuntimeError("provider returned HTML")

    with pytest.raises(RuntimeError, match="provider returned HTML"):
        run_tracked(committed, "test:failing", {"league": "EPL"}, work)

    with committed() as session:
        run = session.scalars(select(JobRun)).one()
    assert run.status is JobStatus.FAILED
    assert run.error == "RuntimeError: provider returned HTML"
    assert run.params == {"league": "EPL"}
    assert run.finished_at is not None


def test_run_tracked_rolls_back_work_on_failure(committed: sessionmaker[Session]) -> None:
    def work(session: Session) -> dict[str, Any]:
        enqueue_in_session(session, "ops:heartbeat")
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_tracked(committed, "test:rollback", {}, work)

    with committed() as session:
        jobs = session.execute(text("SELECT count(*) FROM procrastinate_jobs")).scalar_one()
    assert jobs == 0
