import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.catalog.models import DataProvider
from edgeforge.cli import main as cli_main
from edgeforge.cli import parse_leagues, parse_seasons
from edgeforge.core.config import get_settings
from edgeforge.football.models import PlayerMatchStats
from edgeforge.ingestion import tasks as ingestion_tasks
from edgeforge.ingestion.understat import (
    LEAGUE_TASK,
    MATCH_TASK,
    PROVIDER_LOCK,
    QUEUE,
    enqueue_league,
    ingest_league,
    ingest_match,
    matches_missing_details,
)
from edgeforge.jobs.app import create_app
from edgeforge.ops.models import JobRun, JobStatus
from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.client import League

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
LEAGUE_2025 = (FIXTURES / "league_EPL_2025.json").read_bytes()
MATCH_28778 = (FIXTURES / "match_28778.json").read_bytes()


def _fetcher(league_body: bytes = LEAGUE_2025) -> tuple[HttpFetcher, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/getLeagueData/EPL/2025":
            return httpx.Response(200, content=league_body)
        if request.url.path == "/getMatchData/28778":
            return httpx.Response(200, content=MATCH_28778)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://understat.com")
    return HttpFetcher(client, RateLimiter(1000, burst=1000), sleep=lambda _: None), requested


def _jobs(session: Session, task: str) -> int:
    return session.execute(
        text("SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t"), {"t": task}
    ).scalar_one()


def _one_match_league() -> bytes:
    """The EPL 2025 payload trimmed to the Liverpool v Bournemouth fixture."""
    raw = json.loads(LEAGUE_2025)
    raw["dates"] = [d for d in raw["dates"] if d["id"] == "28778"]
    return json.dumps(raw).encode()


def test_league_job_normalizes_and_fans_out_match_jobs(
    committed: sessionmaker[Session],
) -> None:
    fetcher, _ = _fetcher()

    with committed.begin() as session:
        result = ingest_league(session, fetcher, League.EPL, 2025)

    with committed() as session:
        match_jobs = _jobs(session, MATCH_TASK)
        locks = session.execute(
            text("SELECT DISTINCT lock, queue_name FROM procrastinate_jobs")
        ).all()
    assert result.payload_changed
    assert result.normalized
    assert result.normalize["matches_created"] == 380
    assert result.match_jobs_enqueued == 380
    assert match_jobs == 380
    assert locks == [(PROVIDER_LOCK, QUEUE)]


def test_unchanged_league_is_not_renormalized_or_requeued(
    committed: sessionmaker[Session],
) -> None:
    fetcher, _ = _fetcher()
    with committed.begin() as session:
        ingest_league(session, fetcher, League.EPL, 2025)

    with committed.begin() as session:
        again = ingest_league(session, fetcher, League.EPL, 2025)

    with committed() as session:
        match_jobs = _jobs(session, MATCH_TASK)
    assert (again.payload_changed, again.normalized, again.match_jobs_enqueued) == (False, False, 0)
    assert match_jobs == 380


def test_match_job_fills_details_once(committed: sessionmaker[Session]) -> None:
    fetcher, requested = _fetcher()
    with committed.begin() as session:
        ingest_league(session, fetcher, League.EPL, 2025)

    with committed.begin() as session:
        first = ingest_match(session, fetcher, 28778)
    with committed.begin() as session:
        second = ingest_match(session, fetcher, 28778)
        provider_id = session.scalars(select(DataProvider.id)).one()
        missing = matches_missing_details(session, provider_id, "EPL/2025")

    assert first["normalized"] is True
    assert first["appearances"] == 31
    assert second == {"payload_changed": False, "normalized": False}
    assert len(missing) == 379
    assert 28778 not in missing
    assert requested.count("/getMatchData/28778") == 2


def test_enqueue_is_skipped_while_the_same_job_waits(committed: sessionmaker[Session]) -> None:
    with committed.begin() as session:
        first = enqueue_league(session, League.EPL, 2025)
        duplicate = enqueue_league(session, League.EPL, 2025)
        other = enqueue_league(session, League.EPL, 2024)
        session.execute(text("SELECT 1"))  # the transaction is still usable

    assert first is not None
    assert duplicate is None
    assert other is not None


def test_worker_runs_league_then_match_jobs(
    committed: sessionmaker[Session],
    worker_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher, _ = _fetcher(_one_match_league())
    monkeypatch.setattr(ingestion_tasks, "understat_fetcher", lambda: fetcher)
    with committed.begin() as session:
        enqueue_league(session, League.EPL, 2025)

    create_app(get_settings()).run_worker(
        queues=[QUEUE], wait=False, install_signal_handlers=False, listen_notify=False
    )

    with committed() as session:
        runs = session.scalars(select(JobRun).order_by(JobRun.started_at)).all()
        appearances = session.scalar(select(func.count()).select_from(PlayerMatchStats))
    assert [(r.job_name, r.status) for r in runs] == [
        (LEAGUE_TASK, JobStatus.SUCCEEDED),
        (MATCH_TASK, JobStatus.SUCCEEDED),
    ]
    assert runs[0].stats["match_jobs_enqueued"] == 1
    assert appearances == 31


def test_backfill_command_queues_each_league_season_once(
    committed: sessionmaker[Session], worker_settings: None
) -> None:
    argv = ["backfill", "understat", "--seasons", "2024-2025", "--leagues", "EPL,Serie_A"]

    assert cli_main(argv) == 0
    assert cli_main(argv) == 0

    with committed() as session:
        assert _jobs(session, LEAGUE_TASK) == 4


def test_season_and_league_arguments() -> None:
    assert parse_seasons("2021-2026") == [2021, 2022, 2023, 2024, 2025, 2026]
    assert parse_seasons("2025") == [2025]
    assert parse_leagues("EPL, La_liga") == [League.EPL, League.LA_LIGA]


@pytest.mark.parametrize(
    ("parser", "value"),
    [(parse_seasons, "2026-2021"), (parse_leagues, "EPL,MLS")],
)
def test_invalid_arguments_are_rejected(parser: Callable[[str], object], value: str) -> None:
    with pytest.raises(Exception, match=r"reversed|valid leagues"):
        parser(value)
