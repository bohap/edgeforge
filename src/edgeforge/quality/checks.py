"""Data-quality checks. Each check is one SQL query returning failing matches.

Running the checks opens an issue for each new failure, refreshes issues that still fail,
and resolves issues that no longer fail. Issues are keyed per match so a check reports a
match once, with per-team details in ``details``.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edgeforge.core.time import utcnow
from edgeforge.ops.models import DqIssue, Severity


@dataclass(frozen=True, slots=True)
class Check:
    code: str
    severity: Severity
    description: str
    sql: str


CHECKS: tuple[Check, ...] = (
    Check(
        "result_missing",
        Severity.ERROR,
        "Finished match without a result",
        """
        SELECT m.id, jsonb_build_object('kickoff_at', m.kickoff_at)
        FROM core.match m
        WHERE m.status = 'finished'
          AND NOT EXISTS (SELECT 1 FROM core.match_result r WHERE r.match_id = m.id)
        """,
    ),
    Check(
        "team_stats_incomplete",
        Severity.ERROR,
        "Finished match without exactly two team-stat rows",
        """
        SELECT m.id, jsonb_build_object('rows', count(s.team_id))
        FROM core.match m
        LEFT JOIN core.match_team_stats s ON s.match_id = m.id
        WHERE m.status = 'finished'
        GROUP BY m.id
        HAVING count(s.team_id) <> 2
        """,
    ),
    Check(
        "xg_missing",
        Severity.WARNING,
        "Finished match with a team missing xG",
        """
        SELECT m.id, jsonb_build_object('teams', jsonb_agg(s.team_id))
        FROM core.match m
        JOIN core.match_team_stats s ON s.match_id = m.id
        WHERE m.status = 'finished' AND s.xg IS NULL
        GROUP BY m.id
        """,
    ),
    Check(
        "details_missing",
        Severity.WARNING,
        "Finished more than 24 hours ago but no player or shot data",
        """
        SELECT m.id, jsonb_build_object('kickoff_at', m.kickoff_at)
        FROM core.match m
        WHERE m.status = 'finished'
          AND m.kickoff_at < :now - interval '24 hours'
          AND NOT EXISTS (SELECT 1 FROM core.player_match_stats p WHERE p.match_id = m.id)
        """,
    ),
    Check(
        "goals_mismatch",
        Severity.ERROR,
        "Team goals differ from its players' goals plus the opponent's own goals",
        """
        WITH player_goals AS (
            SELECT s.match_id, s.team_id, s.goals AS team_goals,
                   (SELECT coalesce(sum(p.goals), 0) FROM core.player_match_stats p
                     WHERE p.match_id = s.match_id AND p.team_id = s.team_id)
                 + (SELECT coalesce(sum(p.own_goals), 0) FROM core.player_match_stats p
                     WHERE p.match_id = s.match_id AND p.team_id <> s.team_id) AS from_players
            FROM core.match_team_stats s
            WHERE EXISTS (SELECT 1 FROM core.player_match_stats p WHERE p.match_id = s.match_id)
        )
        SELECT match_id, jsonb_build_object('teams', jsonb_agg(jsonb_build_object(
            'team_id', team_id, 'team_goals', team_goals, 'from_players', from_players)))
        FROM player_goals
        WHERE team_goals <> from_players
        GROUP BY match_id
        """,
    ),
    Check(
        "shot_xg_below_team_xg",
        Severity.WARNING,
        "Sum of shot xG is below team xG (team xG can only combine shots, never add)",
        """
        WITH shots AS (
            SELECT match_id, team_id, sum(xg) AS shot_xg FROM core.shot GROUP BY 1, 2
        )
        SELECT s.match_id, jsonb_build_object('teams', jsonb_agg(jsonb_build_object(
            'team_id', s.team_id, 'team_xg', s.xg, 'shot_xg', sh.shot_xg)))
        FROM core.match_team_stats s
        JOIN shots sh USING (match_id, team_id)
        WHERE sh.shot_xg < s.xg - 0.01
        GROUP BY s.match_id
        """,
    ),
    Check(
        "result_overdue",
        Severity.WARNING,
        "Still scheduled 36 hours after kickoff (postponed, or result not ingested)",
        """
        SELECT m.id, jsonb_build_object('kickoff_at', m.kickoff_at)
        FROM core.match m
        WHERE m.status = 'scheduled' AND m.kickoff_at < :now - interval '36 hours'
        """,
    ),
)


def run_checks(
    session: Session, now: datetime | None = None, checks: tuple[Check, ...] = CHECKS
) -> dict[str, int]:
    """Run every check and sync ``ops.dq_issue``. Returns open issues per check code."""
    now = now or utcnow()
    summary: dict[str, int] = {}
    for check in checks:
        failing: dict[uuid.UUID, dict[str, Any]] = {
            row[0]: row[1] for row in session.execute(text(check.sql), {"now": now})
        }
        for entity_id, details in failing.items():
            stmt = insert(DqIssue).values(
                check_code=check.code,
                severity=check.severity,
                entity_type="match",
                entity_id=entity_id,
                details=details,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[DqIssue.check_code, DqIssue.entity_type, DqIssue.entity_id],
                    index_where=DqIssue.resolved_at.is_(None),
                    set_={"last_seen_at": now, "details": stmt.excluded.details},
                )
            )
        session.execute(
            update(DqIssue)
            .where(
                DqIssue.check_code == check.code,
                DqIssue.resolved_at.is_(None),
                DqIssue.entity_id.not_in(list(failing)) if failing else DqIssue.id.is_not(None),
            )
            .values(resolved_at=now)
        )
        summary[check.code] = len(failing)
    session.flush()
    return summary
