import re
import uuid
from datetime import UTC, datetime

import pytest

from edgeforge.compare.form import Venue, head_to_head, summarize, team_matches
from edgeforge.compare.report import render
from edgeforge.compare.service import FormWindow, MatchComparison, estimate, form_windows
from edgeforge.models.football_goals.model import GoalModelConfig, GoalRatings
from tests.unit.compare.test_form import MATCHES, A, B

AS_OF = datetime(2026, 9, 30, tzinfo=UTC)
NAMES = {A: "Arsenal", B: "Brentford"}
BANNED = ("guaranteed", "safe bet", "lock", "can't lose", "100%")


def _ratings() -> GoalRatings:
    return GoalRatings(
        as_of=AS_OF,
        config=GoalModelConfig(),
        mu=0.25,
        home_advantage=0.2,
        rho=-0.05,
        attack={A: 0.3, B: -0.1},
        defence={A: 0.2, B: -0.2},
    )


def _comparison(ratings: GoalRatings | None) -> MatchComparison:
    return MatchComparison(
        as_of=AS_OF,
        home_team_id=A,
        away_team_id=B,
        home_form=form_windows(team_matches(MATCHES, A), [3, 10], Venue.HOME),
        away_form=form_windows(team_matches(MATCHES, B), [3, 10], Venue.AWAY),
        head_to_head=head_to_head(MATCHES, A, B),
        estimate=estimate(ratings, A, B) if ratings else None,
        home_last_played=team_matches(MATCHES, A)[0].kickoff_at,
    )


def test_estimate_is_a_consistent_distribution() -> None:
    e = estimate(_ratings(), A, B)

    assert e is not None
    assert e.home_win + e.draw + e.away_win == pytest.approx(1.0)
    assert e.home_win > e.away_win
    assert 0 < e.both_score < 1
    assert 0 < e.over_2_5 < 1
    assert e.expected_home_goals > e.expected_away_goals


def test_no_estimate_for_a_team_the_model_has_not_seen() -> None:
    assert estimate(_ratings(), A, uuid.UUID(int=77)) is None


def test_windows_cover_overall_and_venue() -> None:
    window = _comparison(None).home_form[0]

    assert window == FormWindow(
        3,
        summarize(team_matches(MATCHES, A)[:3]),
        summarize(team_matches(MATCHES, A, venue=Venue.HOME)[:3]),
    )


def test_report_shows_form_head_to_head_and_estimate() -> None:
    text = render(_comparison(_ratings()), NAMES)

    assert text.startswith("Arsenal vs Brentford")
    assert re.search(r"^last 3\s+W L D\s+D W L$", text, re.MULTILINE)
    assert "last match in data      2026-08-22            -" in text
    assert "xG for / against" in text
    assert "(2 m)" in text  # Arsenal's last 3: one match without xG
    assert "2026-08-15  Brentford 3-1 Arsenal   xG 2.20-1.00" in text
    assert "2026-08-01  Arsenal 2-1 Brentford   xG 1.80-0.90" in text
    assert "all 2: Arsenal 1 wins, 0 draws, Brentford 1 wins" in text
    assert "Estimated probabilities" in text
    assert "an estimate, not a certainty" in text
    assert not any(word in text.lower() for word in BANNED)


def test_report_without_estimate_or_meetings() -> None:
    text = render(
        MatchComparison(
            as_of=AS_OF,
            home_team_id=A,
            away_team_id=B,
            home_form=[FormWindow(5, None, None)],
            away_form=[FormWindow(5, None, None)],
            head_to_head=[],
            estimate=None,
        ),
        NAMES,
    )

    assert "no matches" in text
    assert "no earlier meetings" in text
    assert "not available" in text
