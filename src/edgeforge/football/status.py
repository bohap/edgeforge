"""Data freshness per competition, for status pages."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgeforge.football.models import Match, MatchResult


def latest_results(session: Session) -> dict[uuid.UUID, datetime]:
    """Kickoff of the most recent match with a result, per competition."""
    rows = session.execute(
        select(Match.competition_id, func.max(Match.kickoff_at).label("latest"))
        .join(MatchResult, MatchResult.match_id == Match.id)
        .group_by(Match.competition_id)
    )
    return {row.competition_id: row.latest for row in rows}
