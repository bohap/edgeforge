"""Procrastinate tasks for ingestion."""

from functools import lru_cache
from typing import Any

import httpx
import procrastinate
from sqlalchemy.orm import Session

from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
from edgeforge.ingestion import understat
from edgeforge.ops.job_runs import run_tracked
from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.client import League

blueprint = procrastinate.Blueprint()


@lru_cache(maxsize=1)
def understat_fetcher() -> HttpFetcher:
    settings = get_settings()
    return HttpFetcher(
        httpx.Client(timeout=30), RateLimiter(settings.understat_requests_per_second)
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
