import uuid
from datetime import UTC, datetime, timedelta

import pytest

from edgeforge.compare.form import Venue, head_to_head, summarize, team_matches
from edgeforge.features.gateway import PlayedMatch

A, B, C = (uuid.UUID(int=i) for i in (1, 2, 3))
START = datetime(2026, 8, 1, tzinfo=UTC)


def _match(
    day: int,
    home: uuid.UUID,
    away: uuid.UUID,
    goals: tuple[int, int],
    xg: tuple[float, float] | None = None,
) -> PlayedMatch:
    return PlayedMatch(
        match_id=uuid.uuid4(),
        competition_id=uuid.UUID(int=99),
        season_id=uuid.UUID(int=98),
        kickoff_at=START + timedelta(days=day),
        home_team_id=home,
        away_team_id=away,
        home_goals=goals[0],
        away_goals=goals[1],
        home_xg=xg[0] if xg else None,
        away_xg=xg[1] if xg else None,
        home_npxg=None,
        away_npxg=None,
    )


MATCHES = [
    _match(0, A, B, (2, 1), (1.8, 0.9)),
    _match(7, C, A, (0, 0), (0.7, 1.1)),
    _match(14, B, A, (3, 1), (2.2, 1.0)),
    _match(21, A, C, (4, 2)),  # no xG
    _match(28, B, C, (1, 1), (1.0, 1.0)),
]


def test_team_matches_are_from_the_team_side_newest_first() -> None:
    rows = team_matches(MATCHES, A)

    assert [r.kickoff_at.day for r in rows] == [22, 15, 8, 1]
    assert [r.result for r in rows] == ["W", "L", "D", "W"]
    away_loss = rows[1]
    assert away_loss.venue is Venue.AWAY
    assert (away_loss.goals_for, away_loss.goals_against) == (1, 3)
    assert (away_loss.xg_for, away_loss.xg_against) == (1.0, 2.2)
    assert away_loss.opponent_id == B


def test_venue_filter() -> None:
    assert [r.venue for r in team_matches(MATCHES, A, venue=Venue.HOME)] == [Venue.HOME] * 2
    assert len(team_matches(MATCHES, A, venue=Venue.AWAY)) == 2


def test_summary_counts_and_averages() -> None:
    summary = summarize(team_matches(MATCHES, A))

    assert summary is not None
    assert summary.results == "WLDW"
    assert (summary.wins, summary.draws, summary.losses) == (2, 1, 1)
    assert summary.points_per_game == pytest.approx(7 / 4)
    assert summary.goals_for == pytest.approx(7 / 4)
    assert summary.goals_against == pytest.approx(6 / 4)
    assert summary.both_scored == 3
    assert summary.over_2_5 == 3


def test_xg_averages_skip_matches_without_xg_and_never_become_zero() -> None:
    summary = summarize(team_matches(MATCHES, A))
    assert summary is not None
    assert summary.xg_matches == 3
    assert summary.xg_for == pytest.approx((1.8 + 1.1 + 1.0) / 3)
    assert summary.xg_against == pytest.approx((0.9 + 0.7 + 2.2) / 3)

    no_xg = summarize(team_matches([_match(0, A, C, (1, 0))], A))
    assert no_xg is not None
    assert no_xg.xg_for is None
    assert no_xg.xg_against is None
    assert no_xg.xg_matches == 0


def test_empty_run_has_no_summary() -> None:
    assert summarize([]) is None


def test_head_to_head_covers_both_venues() -> None:
    meetings = head_to_head(MATCHES, A, B)

    assert [(m.venue, m.result) for m in meetings] == [(Venue.AWAY, "L"), (Venue.HOME, "W")]
    assert head_to_head(MATCHES, B, A)[0].result == "W"
