"""Data page endpoints: sync status and on-demand Understat refreshes."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from edgeforge.api.routes import SessionDep
from edgeforge.api.schemas import Model
from edgeforge.ingestion import sync
from edgeforge.providers.understat.client import League

router = APIRouter(prefix="/api/sync")


class LeagueSyncOut(Model):
    league: League
    code: str
    name: str
    has_data: bool
    latest_result_at: datetime | None
    last_checked_at: datetime | None
    last_check_failed: bool
    queued: bool
    odds_checked_at: datetime | None


class QueueOut(Model):
    todo: int
    doing: int
    failed: int


class SyncStatusOut(Model):
    current_season: int
    first_season: int
    workers_online: int
    queue: QueueOut
    match_details_queued: int
    leagues: list[LeagueSyncOut]


class RefreshIn(BaseModel):
    leagues: list[League] = Field(default_factory=lambda: list(League))


class HistoryIn(RefreshIn):
    from_season: int


class QueuedOut(BaseModel):
    queued: int


@router.get("")
def status(session: SessionDep) -> SyncStatusOut:
    s = sync.sync_status(session, datetime.now(UTC))
    return SyncStatusOut(
        current_season=s.current_season,
        first_season=sync.FIRST_SEASON,
        workers_online=s.workers_online,
        queue=QueueOut.model_validate(s.queue),
        match_details_queued=s.match_details_queued,
        leagues=[LeagueSyncOut.model_validate(league) for league in s.leagues],
    )


@router.post("/refresh")
def refresh(session: SessionDep, body: RefreshIn) -> QueuedOut:
    queued = sync.refresh(session, datetime.now(UTC), body.leagues)
    session.commit()
    return QueuedOut(queued=queued)


@router.post("/history")
def history(session: SessionDep, body: HistoryIn) -> QueuedOut:
    try:
        queued = sync.load_history(session, datetime.now(UTC), body.leagues, body.from_season)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return QueuedOut(queued=queued)
