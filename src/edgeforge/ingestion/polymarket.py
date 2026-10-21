"""Polymarket ingestion: one job per league refreshes quotes for its games in the next week.

Each game is matched to one of our fixtures by kickoff and team names; the match and team
names are remembered in ``ref.provider_entity_map`` so later runs skip the matching. Quotes
are only written before our kickoff, so after a match they hold the last pre-match prices.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from edgeforge.catalog.entity_map import find_internal_id
from edgeforge.catalog.models import MappingMethod, ProviderEntityMap, ProviderKind
from edgeforge.catalog.names import name_similarity
from edgeforge.catalog.reference import competition_by_code, ensure_provider
from edgeforge.features.gateway import Fixture, upcoming_fixtures
from edgeforge.football.teams import team_names
from edgeforge.football.upsert import upsert_many_if_changed
from edgeforge.jobs.enqueue import enqueue_unless_queued
from edgeforge.marketdata.models import MarketQuote
from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.polymarket.client import (
    MORE_MARKETS_SUFFIX,
    PAGE_SIZE,
    PROVIDER_CODE,
    SERIES,
    SLUGS_PER_REQUEST,
    events_url,
    listing_url,
)
from edgeforge.providers.polymarket.parse import GameTeams, Quote, game_quotes, game_teams
from edgeforge.providers.polymarket.schemas import Event, Team, parse_events, project_events
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.service import record_payload

QUEUE = "ingest-polymarket"
PROVIDER_LOCK = "provider:polymarket"
LEAGUE_TASK = "ingest:polymarket_league"

HORIZON = timedelta(days=7)
KICKOFF_TOLERANCE = timedelta(days=1)
# Two team-name similarities (0-1 each) plus a bonus for the exact kickoff.
MIN_GAME_SCORE = 1.5
MIN_GAME_MARGIN = 0.3
EXACT_KICKOFF_BONUS = 0.2

QUOTE_KEY = ("match_id", "provider_id", "market_code", "params_key", "outcome")
QUOTE_VALUES = (
    "params",
    "best_bid",
    "best_ask",
    "last_price",
    "liquidity",
    "fee_rate",
    "external_id",
    "event_slug",
)


def enqueue_league(session: Session, competition_code: str) -> int | None:
    if competition_code not in SERIES:
        return None
    return enqueue_unless_queued(
        session,
        LEAGUE_TASK,
        args={"competition": competition_code},
        queue=QUEUE,
        lock=PROVIDER_LOCK,
        queueing_lock=f"polymarket:league:{competition_code}",
        priority=10,
    )


def leagues_with_data(session: Session) -> list[str]:
    """Competition codes on Polymarket that exist in our data."""
    return [code for code in SERIES if competition_by_code(session, code) is not None]


@dataclass
class LeagueResult:
    games: int = 0
    matched: int = 0
    quotes: int = 0
    skipped_markets: int = 0
    unmatched: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "games": self.games,
            "matched": self.matched,
            "quotes": self.quotes,
            "skipped_markets": self.skipped_markets,
            "unmatched": self.unmatched,
        }


def ingest_league(
    session: Session, fetcher: HttpFetcher, competition_code: str, now: datetime
) -> LeagueResult:
    result = LeagueResult()
    competition = competition_by_code(session, competition_code)
    if competition is None or competition_code not in SERIES:
        return result
    provider = ensure_provider(session, PROVIDER_CODE, ProviderKind.MARKET)
    store = PostgresBlobStore(session)

    def fetch(url: str, key: str, project: bool) -> tuple[list[Event], uuid.UUID]:
        response = fetcher.get(url)
        body = project_events(response.body) if project else response.body
        recorded = record_payload(
            session,
            store,
            provider_id=provider.id,
            resource="events",
            key=key,
            url=response.url,
            http_status=response.status,
            body=body,
            fetched_at=response.fetched_at,
        )
        return parse_events(body), recorded.payload_id

    listed: list[Event] = []
    offset = 0
    while True:
        page, _ = fetch(
            listing_url(SERIES[competition_code], offset),
            f"listing/{competition_code}/{offset}",
            project=False,
        )
        listed += page
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    games = [
        e
        for e in listed
        if e.is_game
        and not e.closed
        and e.start_time is not None
        and now < e.start_time <= now + HORIZON
    ]
    result.games = len(games)
    slugs = [g.slug for g in games] + [g.slug + MORE_MARKETS_SUFFIX for g in games]
    events: dict[str, tuple[Event, uuid.UUID]] = {}
    for start in range(0, len(slugs), SLUGS_PER_REQUEST):
        batch = slugs[start : start + SLUGS_PER_REQUEST]
        fetched, payload_id = fetch(
            events_url(batch), f"games/{competition_code}/{start}", project=True
        )
        events |= {e.slug: (e, payload_id) for e in fetched}

    fixtures = {
        f.match_id: f
        for f in upcoming_fixtures(
            session,
            now - KICKOFF_TOLERANCE,
            now + HORIZON + KICKOFF_TOLERANCE,
            competition_id=competition.id,
        )
    }
    names = team_names(session, {t for f in fixtures.values() for t in _teams_of(f)})
    for listed_game in games:
        main = events.get(listed_game.slug)
        if main is None:
            continue
        game, payload_id = main
        teams = game_teams(game)
        if teams is None or game.start_time is None:
            continue
        fixture = _match_game(session, provider.id, game, teams, fixtures, names)
        if fixture is None:
            result.unmatched.append(game.title)
            continue
        result.matched += 1
        if now >= fixture.kickoff_at:
            continue
        parts = [main]
        if (more := events.get(game.slug + MORE_MARKETS_SUFFIX)) is not None:
            parts.append(more)
        quotes, skipped = game_quotes([e for e, _ in parts], teams)
        result.skipped_markets += skipped
        result.quotes += len(quotes)
        source = {e.slug: pid for e, pid in parts}
        _store_quotes(session, provider.id, fixture.match_id, quotes, source, now)
    session.flush()
    return result


def _store_quotes(
    session: Session,
    provider_id: uuid.UUID,
    match_id: uuid.UUID,
    quotes: Iterable[Quote],
    source: dict[str, uuid.UUID],
    now: datetime,
) -> None:
    by_payload: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for q in quotes:
        by_payload[source[q.event_slug]].append(
            {
                "match_id": match_id,
                "market_code": q.market_code,
                "params_key": q.params_key,
                "outcome": q.outcome,
                "params": q.params,
                "best_bid": q.best_bid,
                "best_ask": q.best_ask,
                "last_price": q.last_price,
                "liquidity": q.liquidity,
                "fee_rate": q.fee_rate,
                "external_id": q.condition_id,
                "event_slug": q.event_slug,
            }
        )
    for payload_id, rows in by_payload.items():
        upsert_many_if_changed(
            session,
            MarketQuote,
            QUOTE_KEY,
            QUOTE_VALUES,
            rows,
            {"provider_id": provider_id, "source_raw_id": payload_id, "observed_at": now},
        )


def _teams_of(fixture: Fixture) -> tuple[uuid.UUID, uuid.UUID]:
    return fixture.home_team_id, fixture.away_team_id


def _match_game(
    session: Session,
    provider_id: uuid.UUID,
    game: Event,
    teams: GameTeams,
    fixtures: dict[uuid.UUID, Fixture],
    names: dict[uuid.UUID, str],
) -> Fixture | None:
    """Our fixture for a Polymarket game: remembered, or the best clear match by kickoff and
    team names (then remembered)."""
    known = find_internal_id(session, provider_id, "event", game.slug)
    if known is not None:
        return fixtures.get(known)
    if game.start_time is None:
        return None
    scored: list[tuple[float, Fixture]] = []
    for fixture in fixtures.values():
        if abs(fixture.kickoff_at - game.start_time) > KICKOFF_TOLERANCE:
            continue
        score = _team_score(session, provider_id, teams.home, fixture.home_team_id, names)
        score += _team_score(session, provider_id, teams.away, fixture.away_team_id, names)
        if fixture.kickoff_at == game.start_time:
            score += EXACT_KICKOFF_BONUS
        scored.append((score, fixture))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < MIN_GAME_SCORE:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MIN_GAME_MARGIN:
        return None
    score, fixture = scored[0]
    confidence = round(min(score / 2, 1.0), 3)
    _remember(session, provider_id, "event", game.slug, fixture.match_id, confidence)
    for team, team_id in ((teams.home, fixture.home_team_id), (teams.away, fixture.away_team_id)):
        if find_internal_id(session, provider_id, "team", team.name) is None:
            _remember(session, provider_id, "team", team.name, team_id, confidence)
    return fixture


def _team_score(
    session: Session,
    provider_id: uuid.UUID,
    team: Team,
    team_id: uuid.UUID,
    names: dict[uuid.UUID, str],
) -> float:
    mapped = find_internal_id(session, provider_id, "team", team.name)
    if mapped is not None:
        return 1.0 if mapped == team_id else 0.0
    ours = names.get(team_id, "")
    candidates = [team.name] + ([team.alias] if team.alias else [])
    return max(name_similarity(name, ours) for name in candidates)


def _remember(
    session: Session,
    provider_id: uuid.UUID,
    entity_type: str,
    external_id: str,
    internal_id: uuid.UUID,
    confidence: float,
) -> None:
    session.add(
        ProviderEntityMap(
            provider_id=provider_id,
            entity_type=entity_type,
            external_id=external_id,
            internal_id=internal_id,
            method=MappingMethod.AUTO,
            confidence=confidence,
        )
    )
    session.flush()
