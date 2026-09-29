"""Idempotent setup of reference rows the pipeline depends on."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import (
    Competition,
    CompetitionKind,
    DataProvider,
    ProviderKind,
    Season,
    Sport,
)


@dataclass(frozen=True, slots=True)
class CompetitionSpec:
    code: str
    name: str
    country: str


FOOTBALL = "football"
UNDERSTAT_COMPETITIONS = {
    "EPL": CompetitionSpec("EPL", "Premier League", "England"),
    "La_liga": CompetitionSpec("LA_LIGA", "La Liga", "Spain"),
    "Bundesliga": CompetitionSpec("BUNDESLIGA", "Bundesliga", "Germany"),
    "Serie_A": CompetitionSpec("SERIE_A", "Serie A", "Italy"),
    "Ligue_1": CompetitionSpec("LIGUE_1", "Ligue 1", "France"),
    "RFPL": CompetitionSpec("RPL", "Russian Premier League", "Russia"),
}


def ensure_sport(session: Session, code: str = FOOTBALL, name: str = "Football") -> Sport:
    sport = session.scalar(select(Sport).where(Sport.code == code))
    if sport is None:
        sport = Sport(code=code, name=name, enabled=True)
        session.add(sport)
        session.flush()
    return sport


def ensure_provider(session: Session, code: str, kind: ProviderKind) -> DataProvider:
    provider = session.scalar(select(DataProvider).where(DataProvider.code == code))
    if provider is None:
        provider = DataProvider(code=code, kind=kind, enabled=True)
        session.add(provider)
        session.flush()
    return provider


def ensure_competition(session: Session, sport: Sport, spec: CompetitionSpec) -> Competition:
    competition = session.scalar(
        select(Competition).where(Competition.sport_id == sport.id, Competition.code == spec.code)
    )
    if competition is None:
        competition = Competition(
            sport_id=sport.id,
            code=spec.code,
            name=spec.name,
            country=spec.country,
            tier=1,
            kind=CompetitionKind.LEAGUE,
            enabled=True,
        )
        session.add(competition)
        session.flush()
    return competition


def season_label(start_year: int) -> str:
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def ensure_season(
    session: Session, competition: Competition, start_year: int, first: date, last: date
) -> Season:
    """Create the season, or widen its dates to cover ``first``..``last``."""
    label = season_label(start_year)
    season = session.scalar(
        select(Season).where(Season.competition_id == competition.id, Season.label == label)
    )
    if season is None:
        season = Season(competition_id=competition.id, label=label, start_date=first, end_date=last)
        session.add(season)
    else:
        season.start_date = min(season.start_date, first)
        season.end_date = max(season.end_date, last)
    session.flush()
    return season
