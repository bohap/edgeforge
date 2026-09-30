"""football-data.co.uk ingestion: one job per competition-season CSV.

Matches must already exist (from Understat); odds rows are attached to them.
"""

from typing import Any

from sqlalchemy.orm import Session

from edgeforge.catalog.models import ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.ingestion.fetch import fetch_and_record
from edgeforge.jobs.enqueue import enqueue_unless_queued
from edgeforge.providers.football_data_uk.client import PROVIDER_CODE, RESOURCE, SeasonRef
from edgeforge.providers.football_data_uk.normalize import (
    PARSER_VERSION,
    normalize_season_payload,
)
from edgeforge.providers.http import HttpFetcher
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload

QUEUE = "ingest-football-data"
PROVIDER_LOCK = "provider:football_data_uk"
SEASON_TASK = "ingest:football_data_season"


def enqueue_season(session: Session, competition_code: str, season: int) -> int | None:
    ref = SeasonRef(competition_code, season)  # validates the competition
    return enqueue_unless_queued(
        session,
        SEASON_TASK,
        args={"competition": ref.competition_code, "season": season},
        queue=QUEUE,
        lock=PROVIDER_LOCK,
        queueing_lock=f"football_data:{ref.key}",
    )


def ingest_season(
    session: Session, fetcher: HttpFetcher, competition_code: str, season: int
) -> dict[str, Any]:
    provider = ensure_provider(session, PROVIDER_CODE, ProviderKind.ODDS)
    store = PostgresBlobStore(session)
    ref = SeasonRef(competition_code, season)
    recorded = fetch_and_record(
        session,
        store,
        fetcher,
        provider_id=provider.id,
        resource=RESOURCE,
        key=ref.key,
        url=ref.url,
    )
    payload = session.get_one(RawPayload, recorded.payload_id)
    if not recorded.changed and payload.parser_version == PARSER_VERSION:
        return {"payload_changed": False, "normalized": False}
    stats = normalize_season_payload(session, store, payload)
    return {"payload_changed": recorded.changed, "normalized": True, **stats.as_dict()}
