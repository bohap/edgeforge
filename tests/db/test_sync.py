import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.app import create_app
from edgeforge.catalog.models import ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.core.schema_check import schema_state
from edgeforge.ingestion import sync
from edgeforge.ingestion.understat import LEAGUE_TASK, enqueue_match
from edgeforge.jobs.status import pending_queueing_locks, queue_summary
from edgeforge.ops.job_runs import last_finished
from edgeforge.ops.models import JobRun, JobStatus
from edgeforge.providers.understat.client import League
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _load_epl_2025(session: Session) -> None:
    provider = ensure_provider(session, "understat", ProviderKind.STATS)
    store = PostgresBlobStore(session)
    recorded = record_payload(
        session,
        store,
        provider_id=provider.id,
        resource="league",
        key="EPL/2025",
        url="https://understat.com/getLeagueData/EPL/2025",
        http_status=200,
        body=(FIXTURES / "league_EPL_2025.json").read_bytes(),
        fetched_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    normalize_league_payload(session, store, session.get_one(RawPayload, recorded.payload_id))


def _run(session: Session, finished: datetime, status: JobStatus, season: int = 2026) -> None:
    session.add(
        JobRun(
            job_name=LEAGUE_TASK,
            params={"league": "EPL", "season": season},
            status=status,
            started_at=finished - timedelta(seconds=5),
            finished_at=finished,
        )
    )
    session.flush()


def test_status_of_an_empty_database(db_session: Session) -> None:
    status = sync.sync_status(db_session, NOW)

    assert status.current_season == 2026
    assert [s.league for s in status.leagues] == list(League)
    assert not any(s.has_data or s.queued for s in status.leagues)
    assert all(s.latest_result_at is None and s.last_checked_at is None for s in status.leagues)
    assert all(s.odds_checked_at is None for s in status.leagues)
    assert (status.queue.todo, status.queue.doing, status.queue.failed) == (0, 0, 0)
    assert status.match_details_queued == 0


def test_status_reports_data_checks_and_queued_jobs(db_session: Session) -> None:
    _load_epl_2025(db_session)
    _run(db_session, NOW - timedelta(hours=3), JobStatus.SUCCEEDED)
    _run(db_session, NOW - timedelta(hours=1), JobStatus.FAILED)
    _run(db_session, NOW, JobStatus.SUCCEEDED, season=2025)  # other season: ignored
    sync.refresh(db_session, NOW, [League.SERIE_A])
    enqueue_match(db_session, 28778)

    status = {s.league: s for s in sync.sync_status(db_session, NOW).leagues}

    epl = status[League.EPL]
    assert epl.has_data
    assert epl.latest_result_at is not None
    assert epl.latest_result_at.date().isoformat() == "2026-05-24"
    assert epl.last_checked_at == NOW - timedelta(hours=1)
    assert epl.last_check_failed
    assert status[League.SERIE_A].queued
    assert not status[League.SERIE_A].has_data
    summary = sync.sync_status(db_session, NOW)
    assert summary.queue.todo == 3  # Serie A league + its Polymarket prices + one match
    assert summary.match_details_queued == 1


def test_refresh_queues_current_season_once(db_session: Session) -> None:
    # One Understat job and one Polymarket job per league.
    assert sync.refresh(db_session, NOW, list(League)) == 2 * len(League)
    assert sync.refresh(db_session, NOW, [League.EPL]) == 0

    locks = pending_queueing_locks(db_session, "understat:league:")
    assert f"understat:league:EPL/{2026}" in locks
    assert queue_summary(db_session, "ingest-understat").todo == len(League)


def test_load_history_queues_every_season_up_to_now(db_session: Session) -> None:
    assert sync.load_history(db_session, NOW, [League.EPL, League.LA_LIGA], 2023) == 8
    locks = pending_queueing_locks(db_session, "understat:league:EPL/")
    assert locks == {f"understat:league:EPL/{season}" for season in range(2023, 2027)}

    with pytest.raises(ValueError, match="between 2014 and 2026"):
        sync.load_history(db_session, NOW, [League.EPL], 2027)
    with pytest.raises(ValueError, match="between 2014 and 2026"):
        sync.load_history(db_session, NOW, [League.EPL], 2010)


def test_pending_locks_treat_like_wildcards_literally(db_session: Session) -> None:
    sync.refresh(db_session, NOW, [League.LA_LIGA])
    assert pending_queueing_locks(db_session, "understat:league:La_") == {
        "understat:league:La_liga/2026"
    }
    assert pending_queueing_locks(db_session, "understat:league:La%") == set()


def test_last_finished_ignores_running_jobs(db_session: Session) -> None:
    _run(db_session, NOW - timedelta(hours=2), JobStatus.SUCCEEDED)
    db_session.add(
        JobRun(
            job_name=LEAGUE_TASK,
            params={"league": "EPL", "season": 2026},
            status=JobStatus.RUNNING,
            started_at=NOW,
        )
    )
    db_session.flush()

    assert last_finished(db_session, LEAGUE_TASK, {"league": "EPL", "season": 2026}) == (
        NOW - timedelta(hours=2),
        JobStatus.SUCCEEDED,
    )
    assert last_finished(db_session, LEAGUE_TASK, {"league": "Serie_A", "season": 2026}) is None


def test_schema_state_of_migrated_database(migrated_engine: Engine) -> None:
    state = schema_state(migrated_engine)
    assert state.up_to_date
    assert state.current == state.head


@pytest.fixture
def client(db_connection: Connection) -> Iterator[TestClient]:
    factory = sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")
    with TestClient(create_app(factory, web_dir=None)) as test_client:
        yield test_client


def test_sync_endpoints(client: TestClient) -> None:
    status = client.get("/api/sync").json()
    assert status["first_season"] == 2014
    assert len(status["leagues"]) == len(League)

    assert client.post("/api/sync/refresh", json={"leagues": ["EPL"]}).json() == {"queued": 2}
    rest = client.post("/api/sync/refresh", json={}).json()
    assert rest == {"queued": 2 * (len(League) - 1)}
    queued = client.post("/api/sync/history", json={"leagues": ["EPL"], "from_season": 2014})
    current = status["current_season"]
    assert queued.json() == {"queued": current - 2014}  # the current season is already queued

    assert client.post("/api/sync/history", json={"from_season": 1999}).status_code == 422
    assert client.post("/api/sync/refresh", json={"leagues": ["NOPE"]}).status_code == 422
    after = client.get("/api/sync").json()
    assert all(league["queued"] for league in after["leagues"])


def test_serve_runs_a_worker_while_the_app_is_up(
    committed: sessionmaker[Session], worker_settings: None
) -> None:
    def online() -> int:
        with committed() as session:
            return int(
                session.execute(
                    text(
                        "SELECT count(*) FROM procrastinate_workers "
                        "WHERE last_heartbeat > now() - interval '1 minute'"
                    )
                ).scalar_one()
            )

    before = online()
    # Only an unused queue: periodic tasks that ticked in the last minutes are deferred at
    # startup, and running them for real would fetch from Understat during the test run.
    app = create_app(committed, web_dir=None, run_worker=True, worker_queues=["test-idle"])
    with TestClient(app) as client:
        deadline = time.monotonic() + 10
        while client.get("/api/sync").json()["workers_online"] <= before:
            assert time.monotonic() < deadline, "embedded worker never came online"
            time.sleep(0.2)
    assert online() == before
