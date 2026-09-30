"""Procrastinate tasks for ingestion."""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import httpx
import procrastinate
from sqlalchemy.orm import Session

from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
from edgeforge.ingestion import football_data, understat
from edgeforge.ops.job_runs import run_tracked
from edgeforge.providers.http import FetchPolicy, HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.client import League

blueprint = procrastinate.Blueprint()


@lru_cache(maxsize=1)
def understat_fetcher() -> HttpFetcher:
    settings = get_settings()
    return HttpFetcher(
        httpx.Client(timeout=30), RateLimiter(settings.understat_requests_per_second)
    )


@lru_cache(maxsize=1)
def football_data_fetcher() -> HttpFetcher:
    return HttpFetcher(httpx.Client(timeout=60), RateLimiter(1.0), FetchPolicy(expect_json=False))


@blueprint.task(name="football_data_season", queue=football_data.QUEUE)
def football_data_season(competition: str, season: int) -> dict[str, Any]:
    def work(session: Session) -> dict[str, Any]:
        return football_data.ingest_season(session, football_data_fetcher(), competition, season)

    return run_tracked(
        default_session_factory(),
        football_data.SEASON_TASK,
        {"competition": competition, "season": season},
        work,
    )


@blueprint.task(name="understat_league", queue=understat.QUEUE)
def understat_league(league: str, season: int) -> dict[str, Any]:
    def work(session: Session) -> dict[str, Any]:
        return understat.ingest_league(
            session, understat_fetcher(), League(league), season
        ).as_dict()

    return run_tracked(
        default_session_factory(),
        understat.LEAGUE_TASK,
        {"league": league, "season": season},
        work,
    )


@blueprint.task(name="understat_match", queue=understat.QUEUE)
def understat_match(match_id: int) -> dict[str, Any]:
    def work(session: Session) -> dict[str, Any]:
        return understat.ingest_match(session, understat_fetcher(), match_id)

    return run_tracked(
        default_session_factory(), understat.MATCH_TASK, {"match_id": match_id}, work
    )


@blueprint.periodic(cron="17 */6 * * *")
@blueprint.task(name="understat_refresh_current_season", queue="ops")
def understat_refresh_current_season(timestamp: int) -> dict[str, Any]:
    """Every 6 hours: queue league jobs for the current season of every Understat league.

    League jobs then queue match jobs for newly finished matches, so this is the only schedule
    needed for Understat. Unchanged league responses cost one request and no writes.
    """
    now = datetime.fromtimestamp(timestamp, UTC)

    def work(session: Session) -> dict[str, Any]:
        return {"queued": understat.queue_current_season_refresh(session, now)}

    return run_tracked(
        default_session_factory(),
        "ingest:understat_refresh_current_season",
        {"timestamp": timestamp},
        work,
    )
