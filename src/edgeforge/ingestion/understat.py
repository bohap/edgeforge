"""Understat ingestion: league jobs fan out to match jobs.

All Understat jobs share one Procrastinate ``lock``, so only one runs at a time across all
workers and the per-process rate limiter is the effective global limit.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import Competition, ProviderEntityMap, ProviderKind, Season
from edgeforge.catalog.reference import UNDERSTAT_COMPETITIONS, ensure_provider, season_label
from edgeforge.football.models import Match, MatchStatus, PlayerMatchStats
from edgeforge.ingestion.fetch import fetch_and_record
from edgeforge.jobs.enqueue import enqueue_unless_queued
from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.understat.client import (
    HEADERS,
    PROVIDER_CODE,
    League,
    league_ref,
    match_ref,
)
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.providers.understat.normalize_match import normalize_match_payload
from edgeforge.providers.understat.schemas import PARSER_VERSION
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload

QUEUE = "ingest-understat"
PROVIDER_LOCK = "provider:understat"
LEAGUE_TASK = "ingest:understat_league"
MATCH_TASK = "ingest:understat_match"


@dataclass(frozen=True, slots=True)
class LeagueJobResult:
    payload_changed: bool
    normalized: bool
    match_jobs_enqueued: int
    normalize: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "payload_changed": self.payload_changed,
            "normalized": self.normalized,
            "match_jobs_enqueued": self.match_jobs_enqueued,
            **self.normalize,
        }


def enqueue_league(session: Session, league: League, season: int) -> int | None:
    return enqueue_unless_queued(
        session,
        LEAGUE_TASK,
        args={"league": league.value, "season": season},
        queue=QUEUE,
        lock=PROVIDER_LOCK,
        queueing_lock=f"understat:league:{league.value}/{season}",
        priority=10,
    )


def enqueue_match(session: Session, understat_match_id: int) -> int | None:
    return enqueue_unless_queued(
        session,
        MATCH_TASK,
        args={"match_id": understat_match_id},
        queue=QUEUE,
        lock=PROVIDER_LOCK,
        queueing_lock=f"understat:match:{understat_match_id}",
    )


def ingest_league(
    session: Session, fetcher: HttpFetcher, league: League, season: int
) -> LeagueJobResult:
    provider = ensure_provider(session, PROVIDER_CODE, ProviderKind.STATS)
    store = PostgresBlobStore(session)
    ref = league_ref(league, season)
    recorded = fetch_and_record(
        session,
        store,
        fetcher,
        provider_id=provider.id,
        resource=ref.resource,
        key=ref.key,
        url=ref.url,
        headers=HEADERS,
    )
    payload = session.get_one(RawPayload, recorded.payload_id)

    normalize_stats: dict[str, int] = {}
    must_normalize = recorded.changed or payload.parser_version != PARSER_VERSION
    if must_normalize:
        normalize_stats = normalize_league_payload(session, store, payload).as_dict()

    enqueued = 0
    for understat_id in matches_missing_details(session, provider.id, payload.key):
        enqueued += enqueue_match(session, understat_id) is not None
    return LeagueJobResult(recorded.changed, must_normalize, enqueued, normalize_stats)


def ingest_match(session: Session, fetcher: HttpFetcher, understat_match_id: int) -> dict[str, Any]:
    provider = ensure_provider(session, PROVIDER_CODE, ProviderKind.STATS)
    store = PostgresBlobStore(session)
    ref = match_ref(understat_match_id)
    recorded = fetch_and_record(
        session,
        store,
        fetcher,
        provider_id=provider.id,
        resource=ref.resource,
        key=ref.key,
        url=ref.url,
        headers=HEADERS,
    )
    payload = session.get_one(RawPayload, recorded.payload_id)
    if not recorded.changed and payload.parser_version == PARSER_VERSION:
        return {"payload_changed": False, "normalized": False}
    stats = normalize_match_payload(session, store, payload)
    return {"payload_changed": recorded.changed, "normalized": True, **stats.as_dict()}


def matches_missing_details(session: Session, provider_id: uuid.UUID, league_key: str) -> list[int]:
    """Understat ids of finished matches in this league-season with no player data yet."""
    league_code, season = league_key.split("/")
    season_id = (
        select(Season.id)
        .join(Competition, Competition.id == Season.competition_id)
        .where(
            Competition.code == UNDERSTAT_COMPETITIONS[league_code].code,
            Season.label == season_label(int(season)),
        )
        .scalar_subquery()
    )
    rows = session.scalars(
        select(ProviderEntityMap.external_id)
        .join(Match, Match.id == ProviderEntityMap.internal_id)
        .where(
            ProviderEntityMap.provider_id == provider_id,
            ProviderEntityMap.entity_type == "match",
            Match.season_id == season_id,
            Match.status == MatchStatus.FINISHED,
            ~exists().where(PlayerMatchStats.match_id == Match.id),
        )
        .order_by(Match.kickoff_at)
    ).all()
    return [int(external_id) for external_id in rows]
