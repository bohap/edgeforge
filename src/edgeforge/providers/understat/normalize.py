"""Understat league payload → ``core`` tables (teams, seasons, matches, results, team stats)."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.orm import Session

from edgeforge.catalog.entity_map import resolve_or_create
from edgeforge.catalog.reference import (
    UNDERSTAT_COMPETITIONS,
    ensure_competition,
    ensure_season,
    ensure_sport,
)
from edgeforge.football.models import (
    Match,
    MatchResult,
    MatchStatus,
    MatchTeamStats,
    Team,
    TeamSeason,
)
from edgeforge.providers.understat.client import League, Resource, parse_league
from edgeforge.providers.understat.schemas import (
    PARSER_VERSION,
    Fixture,
    LeaguePayload,
    TeamMatchHistory,
    TeamRef,
)
from edgeforge.raw.blobstore import BlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import load_body

# Backfilled results are treated as public this long after kickoff (see core models).
RESULT_AVAILABILITY_LAG = timedelta(hours=6)


def available_at(kickoff_at: datetime, observed_at: datetime) -> datetime:
    return min(observed_at, kickoff_at + RESULT_AVAILABILITY_LAG)


@dataclass(slots=True)
class LeagueNormalizeStats:
    teams_created: int = 0
    matches_created: int = 0
    matches_updated: int = 0
    results_written: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "teams_created": self.teams_created,
            "matches_created": self.matches_created,
            "matches_updated": self.matches_updated,
            "results_written": self.results_written,
        }


def league_and_season(payload: RawPayload) -> tuple[League, int]:
    if payload.resource != Resource.LEAGUE:
        raise ValueError(f"payload {payload.id} is a {payload.resource!r} payload")
    league_code, season = payload.key.split("/")
    return League(league_code), int(season)


def normalize_league_payload(
    session: Session, store: BlobStore, payload: RawPayload
) -> LeagueNormalizeStats:
    league, season_year = league_and_season(payload)
    parsed = parse_league(load_body(store, payload))
    stats = normalize_league(session, payload, parsed, league, season_year)
    payload.parser_version = PARSER_VERSION
    return stats


def normalize_league(
    session: Session,
    payload: RawPayload,
    parsed: LeaguePayload,
    league: League,
    season_year: int,
) -> LeagueNormalizeStats:
    stats = LeagueNormalizeStats()
    if not parsed.dates:
        return stats

    sport = ensure_sport(session)
    competition = ensure_competition(session, sport, UNDERSTAT_COMPETITIONS[league.value])
    kickoff_dates = [f.kickoff_at.date() for f in parsed.dates]
    season = ensure_season(
        session, competition, season_year, min(kickoff_dates), max(kickoff_dates)
    )

    team_ids: dict[int, uuid.UUID] = {}
    for ref in _team_refs(parsed.dates):
        team_id, created = resolve_or_create(
            session,
            payload.provider_id,
            "team",
            str(ref.id),
            partial(_create_team, session, sport.id, ref),
        )
        stats.teams_created += created
        team_ids[ref.id] = team_id
        session.execute(
            insert(TeamSeason).values(team_id=team_id, season_id=season.id).on_conflict_do_nothing()
        )

    history = {
        (int(team_key), entry.date): entry
        for team_key, team in parsed.teams.items()
        for entry in team.history
    }

    for fixture in parsed.dates:
        match_id = _upsert_match(
            session, payload, fixture, competition.id, season.id, team_ids, stats
        )
        if fixture.is_result:
            _upsert_result(session, payload, fixture, match_id, team_ids, history)
            stats.results_written += 1

    session.flush()
    return stats


def _team_refs(fixtures: list[Fixture]) -> list[TeamRef]:
    refs: dict[int, TeamRef] = {}
    for fixture in fixtures:
        refs.setdefault(fixture.home.id, fixture.home)
        refs.setdefault(fixture.away.id, fixture.away)
    return list(refs.values())


def _create_team(session: Session, sport_id: uuid.UUID, ref: TeamRef) -> uuid.UUID:
    team = Team(sport_id=sport_id, name=ref.title, short_name=ref.short_title)
    session.add(team)
    session.flush()
    return team.id


def _upsert_match(
    session: Session,
    payload: RawPayload,
    fixture: Fixture,
    competition_id: uuid.UUID,
    season_id: uuid.UUID,
    team_ids: dict[int, uuid.UUID],
    stats: LeagueNormalizeStats,
) -> uuid.UUID:
    status = MatchStatus.FINISHED if fixture.is_result else MatchStatus.SCHEDULED

    def create() -> uuid.UUID:
        match = Match(
            competition_id=competition_id,
            season_id=season_id,
            home_team_id=team_ids[fixture.home.id],
            away_team_id=team_ids[fixture.away.id],
            kickoff_at=fixture.kickoff_at,
            status=status,
            provider_id=payload.provider_id,
            source_raw_id=payload.id,
            observed_at=payload.fetched_at,
        )
        session.add(match)
        session.flush()
        return match.id

    match_id, created = resolve_or_create(
        session, payload.provider_id, "match", str(fixture.id), create
    )
    if created:
        stats.matches_created += 1
        return match_id

    match = session.get_one(Match, match_id)
    if match.kickoff_at != fixture.kickoff_at or match.status != status:
        match.kickoff_at = fixture.kickoff_at
        match.status = status
        match.source_raw_id = payload.id
        match.observed_at = payload.fetched_at
        stats.matches_updated += 1
    return match_id


def _upsert_result(
    session: Session,
    payload: RawPayload,
    fixture: Fixture,
    match_id: uuid.UUID,
    team_ids: dict[int, uuid.UUID],
    history: dict[tuple[int, datetime], TeamMatchHistory],
) -> None:
    home_goals, away_goals = fixture.goals.h, fixture.goals.a
    if home_goals is None or away_goals is None:
        raise ValueError(f"Understat match {fixture.id} is marked played but has no score")

    provenance = {
        "provider_id": payload.provider_id,
        "source_raw_id": payload.id,
        "observed_at": payload.fetched_at,
        "available_at": available_at(fixture.kickoff_at, payload.fetched_at),
    }
    result = insert(MatchResult).values(
        match_id=match_id, home_goals=home_goals, away_goals=away_goals, **provenance
    )
    session.execute(
        result.on_conflict_do_update(
            index_elements=[MatchResult.match_id],
            set_={
                **{k: result.excluded[k] for k in ("home_goals", "away_goals")},
                **_touch(result),
            },
            where=(MatchResult.home_goals.is_distinct_from(result.excluded.home_goals))
            | (MatchResult.away_goals.is_distinct_from(result.excluded.away_goals)),
        )
    )

    sides = (
        (fixture.home, True, home_goals, fixture.xg.h),
        (fixture.away, False, away_goals, fixture.xg.a),
    )
    for ref, is_home, goals, xg in sides:
        entry = history.get((ref.id, fixture.kickoff_at))
        values = {
            "goals": goals,
            "xg": xg,
            "npxg": entry.npxg if entry else None,
            "ppda_passes": entry.ppda.att if entry else None,
            "ppda_defensive_actions": entry.ppda.defence if entry else None,
            "deep_completions": entry.deep if entry else None,
        }
        stmt = insert(MatchTeamStats).values(
            match_id=match_id, team_id=team_ids[ref.id], is_home=is_home, **values, **provenance
        )
        changed = None
        for column in values:
            clause = getattr(MatchTeamStats, column).is_distinct_from(stmt.excluded[column])
            changed = clause if changed is None else changed | clause
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[MatchTeamStats.match_id, MatchTeamStats.team_id],
                set_={**{k: stmt.excluded[k] for k in values}, **_touch(stmt)},
                where=changed,
            )
        )


def _touch(stmt: Insert) -> dict[str, Any]:
    """Provenance columns to refresh when a row's values change."""
    return {name: stmt.excluded[name] for name in ("source_raw_id", "observed_at", "available_at")}
