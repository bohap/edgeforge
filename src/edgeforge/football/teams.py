"""Team lookups for other modules (CLI, reports)."""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.football.models import Match, Team

# Common short names that are not word prefixes of the full name.
ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "spurs": "tottenham",
    "wolves": "wolverhampton wanderers",
    "psg": "paris saint germain",
    "barca": "barcelona",
}


class TeamLookupError(LookupError):
    pass


def find_team(session: Session, query: str) -> uuid.UUID:
    """Resolve a team by name, ignoring case: an exact match, otherwise the one team whose
    name has a word starting with each word of the query ("man city" → Manchester City)."""
    needle = query.strip().lower()
    needle = ALIASES.get(needle, needle)
    teams: list[tuple[uuid.UUID, str]] = [
        (row.id, row.name) for row in session.execute(select(Team.id, Team.name))
    ]
    exact = [team_id for team_id, name in teams if name.lower() == needle]
    if len(exact) == 1:
        return exact[0]
    words = needle.split()
    partial = sorted(
        ((team_id, name) for team_id, name in teams if words and _matches_words(name, words)),
        key=lambda t: t[1],
    )
    if len(partial) == 1:
        return partial[0][0]
    if not partial:
        raise TeamLookupError(f"no team matches {query!r}")
    names = ", ".join(name for _, name in partial)
    raise TeamLookupError(f"{query!r} matches several teams: {names}")


def _matches_words(name: str, words: list[str]) -> bool:
    name_words = name.lower().split()
    return all(any(w.startswith(q) for w in name_words) for q in words)


def competition_teams(
    session: Session, competition_id: uuid.UUID, since: datetime
) -> dict[uuid.UUID, str]:
    """Teams with a match in the competition kicking off at or after ``since``, by name."""
    played = (
        select(Match.home_team_id.label("team_id"))
        .where(Match.competition_id == competition_id, Match.kickoff_at >= since)
        .union(
            select(Match.away_team_id).where(
                Match.competition_id == competition_id, Match.kickoff_at >= since
            )
        )
        .subquery()
    )
    rows = session.execute(
        select(Team.id, Team.name).join(played, played.c.team_id == Team.id).order_by(Team.name)
    )
    return {row.id: row.name for row in rows}


def team_names(session: Session, team_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = set(team_ids)
    if not ids:
        return {}
    rows = session.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))
    return {row.id: row.name for row in rows}
