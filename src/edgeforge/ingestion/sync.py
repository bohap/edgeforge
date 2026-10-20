"""On-demand Understat syncing for the web app: status per league, refresh, history load.

Everything here only queues jobs; a worker (``edgeforge serve`` runs one) does the fetching.
League jobs have a higher priority than match-detail jobs, so a refresh runs next even while
a long history load is in progress.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from edgeforge.catalog.reference import UNDERSTAT_COMPETITIONS, competition_by_code
from edgeforge.football.status import latest_results
from edgeforge.ingestion.understat import (
    LEAGUE_TASK,
    QUEUE,
    current_season,
    enqueue_league,
)
from edgeforge.jobs.status import (
    QueueSummary,
    pending_queueing_locks,
    queue_summary,
    workers_online,
)
from edgeforge.ops.job_runs import last_finished
from edgeforge.ops.models import JobStatus
from edgeforge.providers.understat.client import League

# Understat has data from 2014/15.
FIRST_SEASON = 2014


@dataclass(frozen=True, slots=True)
class LeagueSync:
    league: League
    code: str
    name: str
    has_data: bool
    latest_result_at: datetime | None
    last_checked_at: datetime | None
    last_check_failed: bool
    queued: bool


@dataclass(frozen=True, slots=True)
class SyncStatus:
    current_season: int
    workers_online: int
    queue: QueueSummary
    match_details_queued: int
    leagues: list[LeagueSync]


def sync_status(session: Session, now: datetime) -> SyncStatus:
    season = current_season(now)
    latest = latest_results(session)
    pending = pending_queueing_locks(session, "understat:")
    leagues = []
    for league in League:
        spec = UNDERSTAT_COMPETITIONS[league.value]
        competition = competition_by_code(session, spec.code)
        checked = last_finished(session, LEAGUE_TASK, {"league": league.value, "season": season})
        leagues.append(
            LeagueSync(
                league=league,
                code=spec.code,
                name=spec.name,
                has_data=competition is not None and competition.id in latest,
                latest_result_at=latest.get(competition.id) if competition else None,
                last_checked_at=checked[0] if checked else None,
                last_check_failed=checked is not None and checked[1] is JobStatus.FAILED,
                queued=any(
                    lock.startswith(f"understat:league:{league.value}/") for lock in pending
                ),
            )
        )
    return SyncStatus(
        current_season=season,
        workers_online=workers_online(session),
        queue=queue_summary(session, QUEUE),
        match_details_queued=sum(lock.startswith("understat:match:") for lock in pending),
        leagues=leagues,
    )


def refresh(session: Session, now: datetime, leagues: Sequence[League]) -> int:
    """Queue the current season of each league. Returns how many jobs were queued."""
    season = current_season(now)
    return sum(enqueue_league(session, league, season) is not None for league in leagues)


def load_history(
    session: Session, now: datetime, leagues: Sequence[League], from_season: int
) -> int:
    """Queue every season from ``from_season`` to the current one."""
    last = current_season(now)
    if not FIRST_SEASON <= from_season <= last:
        raise ValueError(f"from_season must be between {FIRST_SEASON} and {last}")
    return sum(
        enqueue_league(session, league, season) is not None
        for league in leagues
        for season in range(from_season, last + 1)
    )
