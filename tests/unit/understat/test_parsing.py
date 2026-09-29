import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.client import (
    EXPECTED_UNMODELLED,
    HEADERS,
    League,
    fetch,
    league_ref,
    match_ref,
    parse_league,
    parse_match,
)
from edgeforge.providers.understat.schemas import unknown_fields

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "understat"


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_completed_season_has_full_fixture_list() -> None:
    league = parse_league(_bytes("league_EPL_2025.json"))

    assert len(league.dates) == 380
    assert all(f.is_result for f in league.dates)
    assert len(league.teams) == 20
    assert all(len(team.history) == 38 for team in league.teams.values())
    assert len({f.id for f in league.dates}) == 380


def test_kickoff_times_are_utc() -> None:
    first = parse_league(_bytes("league_EPL_2025.json")).dates[0]

    # Liverpool v Bournemouth kicked off at 20:00 BST on 15 Aug 2025.
    assert (first.home.title, first.away.title) == ("Liverpool", "Bournemouth")
    assert first.kickoff_at == datetime(2025, 8, 15, 19, 0, tzinfo=UTC)


def test_forecast_is_dropped_to_prevent_leakage() -> None:
    raw = json.loads(_bytes("league_EPL_2025.json"))
    assert "forecast" in raw["dates"][0]

    fixture = parse_league(_bytes("league_EPL_2025.json")).dates[0]

    assert not hasattr(fixture, "forecast")
    assert "forecast" not in (fixture.model_extra or {})


def test_future_fixtures_have_no_goals_or_xg() -> None:
    league = parse_league(_bytes("league_EPL_2026.json"))
    upcoming = [f for f in league.dates if not f.is_result]

    assert upcoming
    assert all(f.goals.h is None and f.goals.a is None for f in upcoming)
    assert all(f.xg.h is None and f.xg.a is None for f in upcoming)


def test_match_shots_add_up_to_league_xg_and_score() -> None:
    fixture = next(f for f in parse_league(_bytes("league_EPL_2025.json")).dates if f.id == 28778)
    match = parse_match(_bytes("match_28778.json"))

    home_goals = sum(s.result == "Goal" for s in match.shots.h) + sum(
        r.own_goals for r in match.rosters.a.values()
    )
    away_goals = sum(s.result == "Goal" for s in match.shots.a) + sum(
        r.own_goals for r in match.rosters.h.values()
    )
    assert sum(s.xg for s in match.shots.h) == pytest.approx(fixture.xg.h, abs=1e-4)
    assert sum(s.xg for s in match.shots.a) == pytest.approx(fixture.xg.a, abs=1e-4)
    assert (home_goals, away_goals) == (fixture.goals.h, fixture.goals.a)
    assert {r.team_id for r in match.rosters.h.values()} == {fixture.home.id}
    assert {r.team_id for r in match.rosters.a.values()} == {fixture.away.id}


def test_recorded_payloads_have_no_unexpected_fields() -> None:
    league = parse_league(_bytes("league_EPL_2025.json"))
    match = parse_match(_bytes("match_28778.json"))

    assert unknown_fields(league) - EXPECTED_UNMODELLED == set()
    assert unknown_fields(match) - EXPECTED_UNMODELLED == set()


def test_new_provider_field_is_reported_not_fatal() -> None:
    raw = json.loads(_bytes("match_28778.json"))
    raw["shots"]["h"][0]["bodyPart"] = "Head"

    with capture_logs() as logs:
        parse_match(json.dumps(raw).encode())

    warning = next(entry for entry in logs if entry["event"] == "understat_unknown_fields")
    assert warning["fields"] == ["shots.h.[].bodyPart"]


def test_missing_required_field_fails() -> None:
    raw = json.loads(_bytes("match_28778.json"))
    del raw["shots"]["h"][0]["xG"]

    with pytest.raises(ValidationError, match="xG"):
        parse_match(json.dumps(raw).encode())


def test_resource_refs() -> None:
    league = league_ref(League.LA_LIGA, 2026)
    match = match_ref(28778)

    assert (league.key, league.url) == (
        "La_liga/2026",
        "https://understat.com/getLeagueData/La_liga/2026",
    )
    assert (match.key, match.url) == ("28778", "https://understat.com/getMatchData/28778")


def test_fetch_sends_xhr_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_bytes("match_28778.json"))

    fetcher = HttpFetcher(
        httpx.Client(transport=httpx.MockTransport(handler)), RateLimiter(1000, burst=1000)
    )

    fetch(fetcher, match_ref(28778))

    for name, value in HEADERS.items():
        assert seen[0].headers[name] == value
