"""Attach football-data.co.uk odds to our matches.

Team names differ between providers ("Man City" vs "Manchester City", "Wolves" vs
"Wolverhampton Wanderers"), so names are resolved by fixture voting rather than a hand-kept
alias list: each CSV row is compared with the few matches our database has for that
competition around the same date, the best-fitting fixture votes for a name-to-team pairing,
and a name is mapped once a clear majority of its rows agree. Mappings are stored in
``ref.provider_entity_map`` and reused afterwards; rows that cannot be placed are counted,
never guessed.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from edgeforge.catalog.entity_map import find_internal_id
from edgeforge.catalog.models import Competition, MappingMethod, ProviderEntityMap
from edgeforge.football.models import Match, Team
from edgeforge.football.upsert import upsert_many_if_changed
from edgeforge.marketdata.models import HistoricalOdds
from edgeforge.providers.football_data_uk.client import RESOURCE, season_ref_from_key
from edgeforge.providers.football_data_uk.parser import SeasonRow, parse_season_csv
from edgeforge.raw.blobstore import BlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import load_body

PARSER_VERSION = "football-data-uk-v1"
DATE_TOLERANCE = timedelta(days=1)
MIN_VOTE_SHARE = 0.8
MIN_MARGIN = 0.15
# A name needs this many agreeing fixtures, unless its spelling also resembles the team.
MIN_VOTES = 3
SIMILAR_NAME = 0.6
ODDS_KEY = ("match_id", "provider_id", "bookmaker", "market_code", "params_key", "outcome")


@dataclass(frozen=True, slots=True)
class Candidate:
    match_id: uuid.UUID
    match_date: date
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    home_names: tuple[str, ...]
    away_names: tuple[str, ...]


@dataclass(slots=True)
class OddsNormalizeStats:
    rows: int = 0
    matched: int = 0
    unmatched: int = 0
    teams_mapped: int = 0
    unresolved_names: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "teams_mapped": self.teams_mapped,
            "unresolved_names": list(self.unresolved_names),
        }


def normalize_season_payload(
    session: Session, store: BlobStore, payload: RawPayload
) -> OddsNormalizeStats:
    if payload.resource != RESOURCE:
        raise ValueError(f"payload {payload.id} is a {payload.resource!r} payload")
    ref = season_ref_from_key(payload.key)
    rows = parse_season_csv(load_body(store, payload))
    stats = OddsNormalizeStats(rows=len(rows))
    if not rows:
        return stats

    competition_id = session.scalars(
        select(Competition.id).where(Competition.code == ref.competition_code)
    ).one_or_none()
    if competition_id is None:
        raise LookupError(f"competition {ref.competition_code} has no matches loaded yet")

    candidates = _candidates(session, competition_id, rows)
    names, created, unresolved = resolve_team_names(session, payload.provider_id, rows, candidates)
    stats.teams_mapped = created
    stats.unresolved_names = tuple(sorted(unresolved))

    by_teams: dict[tuple[uuid.UUID, uuid.UUID], list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_teams[(c.home_team_id, c.away_team_id)].append(c)

    quotes: list[dict[str, object]] = []
    for row in rows:
        home, away = names.get(row.home_team), names.get(row.away_team)
        pool = by_teams.get((home, away), []) if home and away else []
        match = next(
            (c for c in pool if abs(c.match_date - row.match_date) <= DATE_TOLERANCE), None
        )
        if match is None:
            stats.unmatched += 1
            continue
        stats.matched += 1
        quotes.extend(
            {
                "match_id": match.match_id,
                "provider_id": payload.provider_id,
                "bookmaker": q.bookmaker,
                "market_code": q.market_code,
                "params_key": q.params_key,
                "outcome": q.outcome,
                "opening": q.opening,
                "closing": q.closing,
            }
            for q in row.quotes
        )

    upsert_many_if_changed(
        session,
        HistoricalOdds,
        ODDS_KEY,
        ("opening", "closing"),
        quotes,
        {"source_raw_id": payload.id, "observed_at": payload.fetched_at},
    )
    payload.parser_version = PARSER_VERSION
    session.flush()
    return stats


def resolve_team_names(
    session: Session,
    provider_id: uuid.UUID,
    rows: list[SeasonRow],
    candidates: list[Candidate],
) -> tuple[dict[str, uuid.UUID], int, set[str]]:
    """Map provider team names to internal team ids. Returns (mapping, created, unresolved)."""
    all_names = {r.home_team for r in rows} | {r.away_team for r in rows}
    mapping: dict[str, uuid.UUID] = {}
    for name in all_names:
        known = find_internal_id(session, provider_id, "team", name)
        if known is not None:
            mapping[name] = known

    team_names: dict[uuid.UUID, tuple[str, ...]] = {}
    for c in candidates:
        team_names[c.home_team_id] = c.home_names
        team_names[c.away_team_id] = c.away_names
    votes: dict[str, Counter[uuid.UUID]] = defaultdict(Counter)
    for row in rows:
        if row.home_team in mapping and row.away_team in mapping:
            continue
        nearby = [c for c in candidates if abs(c.match_date - row.match_date) <= DATE_TOLERANCE]
        scored = sorted(
            (
                (
                    _name_score(row.home_team, c.home_team_id, c.home_names, mapping)
                    + _name_score(row.away_team, c.away_team_id, c.away_names, mapping),
                    c,
                )
                for c in nearby
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored:
            continue
        if len(scored) > 1 and scored[0][0] - scored[1][0] < MIN_MARGIN:
            continue
        best = scored[0][1]
        votes[row.home_team][best.home_team_id] += 1
        votes[row.away_team][best.away_team_id] += 1

    created = 0
    for name, counter in votes.items():
        if name in mapping:
            continue
        team_id, count = counter.most_common(1)[0]
        share = count / counter.total()
        if share < MIN_VOTE_SHARE:
            continue
        if count < MIN_VOTES and _similarity(name, team_names.get(team_id, ())) < SIMILAR_NAME:
            continue
        mapping[name] = team_id
        session.add(
            ProviderEntityMap(
                provider_id=provider_id,
                entity_type="team",
                external_id=name,
                internal_id=team_id,
                method=MappingMethod.AUTO,
                confidence=round(share, 3),
            )
        )
        created += 1
    session.flush()
    return mapping, created, all_names - set(mapping)


def _name_score(
    name: str, team_id: uuid.UUID, team_names: tuple[str, ...], mapping: dict[str, uuid.UUID]
) -> float:
    if name in mapping:
        return 1.0 if mapping[name] == team_id else 0.0
    return _similarity(name, team_names)


def _similarity(name: str, team_names: tuple[str, ...]) -> float:
    wanted = _normalize(name)
    return max(
        (SequenceMatcher(None, wanted, _normalize(t)).ratio() for t in team_names), default=0.0
    )


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch == " ").strip()


def _candidates(
    session: Session, competition_id: uuid.UUID, rows: list[SeasonRow]
) -> list[Candidate]:
    first = min(r.match_date for r in rows) - timedelta(days=2)
    last = max(r.match_date for r in rows) + timedelta(days=3)
    home, away = aliased(Team), aliased(Team)
    query = (
        select(
            Match.id,
            Match.kickoff_at,
            home.id,
            home.name,
            home.short_name,
            away.id,
            away.name,
            away.short_name,
        )
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .where(
            Match.competition_id == competition_id,
            Match.kickoff_at >= datetime.combine(first, time(), tzinfo=UTC),
            Match.kickoff_at < datetime.combine(last, time(), tzinfo=UTC),
        )
    )
    return [
        Candidate(
            match_id=mid,
            match_date=kickoff.date(),
            home_team_id=hid,
            away_team_id=aid,
            home_names=tuple(n for n in (hname, hshort) if n),
            away_names=tuple(n for n in (aname, ashort) if n),
        )
        for mid, kickoff, hid, hname, hshort, aid, aname, ashort in session.execute(query)
    ]
