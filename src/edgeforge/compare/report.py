"""Plain-text rendering of a match comparison."""

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime

from edgeforge.compare.form import FormSummary, TeamMatch, Venue, summarize
from edgeforge.compare.service import FormWindow, MatchComparison

HEAD_TO_HEAD_SHOWN = 6
LABEL_WIDTH = 24
COLUMN_WIDTH = 22


def render(comparison: MatchComparison, names: Mapping[uuid.UUID, str]) -> str:
    home = names.get(comparison.home_team_id, "home")
    away = names.get(comparison.away_team_id, "away")
    lines = [f"{home} vs {away}", ""]
    lines.append(_row("", home, away))
    lines.append(
        _row(
            "last match in data",
            _date(comparison.home_last_played),
            _date(comparison.away_last_played),
        )
    )
    lines.append("(results newest first)")
    for home_window, away_window in zip(comparison.home_form, comparison.away_form, strict=True):
        lines += _window(home_window, away_window, overall=True)
        lines += _window(home_window, away_window, overall=False)
    lines += ["", *_head_to_head(comparison, home, away)]
    lines += ["", *_estimate(comparison, home, away)]
    return "\n".join(lines)


def _window(home: FormWindow, away: FormWindow, *, overall: bool) -> list[str]:
    title = f"last {home.last}" if overall else f"last {home.last} at venue"
    h = home.overall if overall else home.at_venue
    a = away.overall if overall else away.at_venue
    lines = ["", _row(title, _results(h), _results(a))]
    fields: list[tuple[str, Callable[[FormSummary], str]]] = [
        ("  points per game", lambda s: f"{s.points_per_game:.2f}"),
        ("  goals for / against", lambda s: f"{s.goals_for:.2f} / {s.goals_against:.2f}"),
        ("  xG for / against", _xg),
        ("  both teams scored", lambda s: f"{s.both_scored}/{s.matches}"),
        ("  over 2.5 goals", lambda s: f"{s.over_2_5}/{s.matches}"),
    ]
    for label, fmt in fields:
        lines.append(_row(label, fmt(h) if h else "-", fmt(a) if a else "-"))
    return lines


def _date(value: datetime | None) -> str:
    return value.date().isoformat() if value else "-"


def _results(summary: FormSummary | None) -> str:
    if summary is None:
        return "no matches"
    return " ".join(summary.results)


def _xg(summary: FormSummary) -> str:
    if summary.xg_for is None or summary.xg_against is None:
        return "n/a"
    text = f"{summary.xg_for:.2f} / {summary.xg_against:.2f}"
    if summary.xg_matches < summary.matches:
        text += f" ({summary.xg_matches} m)"
    return text


def _head_to_head(comparison: MatchComparison, home: str, away: str) -> list[str]:
    meetings = comparison.head_to_head
    if not meetings:
        return ["Head to head: no earlier meetings in the data"]
    shown = meetings[:HEAD_TO_HEAD_SHOWN]
    lines = [f"Head to head (last {len(shown)} of {len(meetings)})"]
    lines += [f"  {_meeting(m, home, away)}" for m in shown]
    summary = summarize(meetings)
    if summary is not None:
        lines.append(
            f"  all {summary.matches}: {home} {summary.wins} wins, {summary.draws} draws, "
            f"{away} {summary.losses} wins"
        )
    return lines


def _meeting(m: TeamMatch, home: str, away: str) -> str:
    """One meeting in the actual home-away order; ``m`` is from ``home``'s side."""
    date = m.kickoff_at.date().isoformat()
    if m.venue is Venue.HOME:
        score = f"{home} {m.goals_for}-{m.goals_against} {away}"
        xg = (m.xg_for, m.xg_against)
    else:
        score = f"{away} {m.goals_against}-{m.goals_for} {home}"
        xg = (m.xg_against, m.xg_for)
    if xg[0] is not None and xg[1] is not None:
        score += f"   xG {xg[0]:.2f}-{xg[1]:.2f}"
    return f"{date}  {score}"


def _estimate(comparison: MatchComparison, home: str, away: str) -> list[str]:
    e = comparison.estimate
    if e is None:
        return ["Estimated probabilities: not available (too little data for one of the teams)"]
    return [
        "Estimated probabilities (goal model; an estimate, not a certainty)",
        f"  expected goals      {home} {e.expected_home_goals:.2f} - "
        f"{e.expected_away_goals:.2f} {away}",
        f"  {home} win {e.home_win:.0%}   draw {e.draw:.0%}   {away} win {e.away_win:.0%}",
        f"  both teams score    {e.both_score:.0%}",
        f"  over 2.5 goals      {e.over_2_5:.0%}",
        f"  most likely score   {e.likely_score[0]}-{e.likely_score[1]} "
        f"({e.likely_score_probability:.0%})",
    ]


def _row(label: str, home: str, away: str) -> str:
    return f"{label:<{LABEL_WIDTH}}{home:<{COLUMN_WIDTH}}{away}".rstrip()
