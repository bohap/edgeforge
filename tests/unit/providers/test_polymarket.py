import json
from pathlib import Path

import pytest

from edgeforge.markets.football import MARKET_TYPES
from edgeforge.providers.polymarket.client import event_page_url, events_url, listing_url
from edgeforge.providers.polymarket.parse import (
    GameTeams,
    game_quotes,
    game_teams,
    params_key,
)
from edgeforge.providers.polymarket.schemas import (
    PRICED_TYPES,
    Event,
    Team,
    parse_events,
    project_events,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "polymarket"
EVENTS = (FIXTURES / "events_EPL.json").read_bytes()


def _events() -> dict[str, Event]:
    return {e.slug: e for e in parse_events(EVENTS)}


def _ips_not() -> tuple[list[Event], GameTeams]:
    events = _events()
    game = events["epl-ips-not-2026-10-23"]
    teams = game_teams(game)
    assert teams is not None
    return [game, events["epl-ips-not-2026-10-23-more-markets"]], teams


def test_urls() -> None:
    assert listing_url(10188, 100) == (
        "https://gamma-api.polymarket.com/events?series_id=10188&closed=false"
        "&include_markets=false&limit=100&offset=100"
    )
    assert events_url(["a", "b"]) == "https://gamma-api.polymarket.com/events?slug=a&slug=b"
    assert event_page_url("epl-ips-not-2026-10-23") == (
        "https://polymarket.com/event/epl-ips-not-2026-10-23"
    )


def test_projection_keeps_only_priced_markets_and_round_trips() -> None:
    projected = project_events(EVENTS)

    assert len(projected) < len(EVENTS) / 2
    events = parse_events(projected)
    assert {e.slug for e in events} == set(_events())
    kept = {m.market_type for e in events for m in e.markets}
    assert kept <= PRICED_TYPES
    assert {"moneyline", "totals", "spreads", "both_teams_to_score"} <= kept
    assert project_events(projected) == projected


def test_game_events_and_teams() -> None:
    events = _events()
    game = events["epl-ips-not-2026-10-23"]
    more = events["epl-ips-not-2026-10-23-more-markets"]

    assert game.is_game
    assert not more.is_game
    teams = game_teams(game)
    assert teams is not None
    assert (teams.home.name, teams.away.name) == ("Ipswich Town FC", "Nottingham Forest FC")


def test_team_order_falls_back_to_the_title() -> None:
    event = Event(
        slug="x",
        title="Away Town vs. Home City",
        gameId="1",
        teams=[Team(name="Home City"), Team(name="Away Town")],
    )
    teams = game_teams(event)
    assert teams is not None
    assert (teams.home.name, teams.away.name) == ("Away Town", "Home City")


def test_quotes_map_onto_our_markets() -> None:
    events, teams = _ips_not()
    quotes, skipped = game_quotes(events, teams)
    by_key = {(q.market_code, q.params_key, q.outcome): q for q in quotes}

    assert skipped == 0
    assert {q.market_code for q in quotes} == {
        "MATCH_RESULT",
        "WIN_MARGIN",
        "TOTAL_GOALS",
        "BTTS",
        "TEAM_TOTAL",
    }
    for outcome in ("HOME", "DRAW", "AWAY"):
        assert ("MATCH_RESULT", "", outcome) in by_key
    over = by_key[("TOTAL_GOALS", "line=2.5", "OVER")]
    assert (over.best_bid, over.best_ask) == (0.54, 0.55)
    assert over.event_slug == "epl-ips-not-2026-10-23-more-markets"
    assert over.fee_rate == pytest.approx(0.05)
    forest = by_key[("WIN_MARGIN", "min_margin=2;side=away", "YES")]
    assert forest.params == {"side": "away", "min_margin": 2}
    ipswich_goals = by_key[("TEAM_TOTAL", "line=1.5;side=home", "OVER")]
    assert ipswich_goals.params == {"side": "home", "line": 1.5}
    assert ("BTTS", "", "YES") in by_key
    for q in quotes:
        assert q.outcome in MARKET_TYPES[q.market_code].outcomes
        assert set(q.params) == set(MARKET_TYPES[q.market_code].params)


def test_closed_and_unmappable_markets_are_left_out() -> None:
    events, teams = _ips_not()
    game = events[0]
    closed = game.markets[0].model_copy(update={"closed": True})
    odd_line = events[1].markets[0].model_copy(update={"market_type": "totals", "line": 2.0})
    unknown = game.markets[1].model_copy(update={"market_type": "corners"})
    edited = game.model_copy(update={"markets": [closed, odd_line, unknown]})

    quotes, skipped = game_quotes([edited], teams)

    assert quotes == []
    assert skipped == 1  # the whole-number line; unpriced types are not counted


def test_params_key_is_sorted() -> None:
    assert params_key({"side": "home", "line": 1.5}) == "line=1.5;side=home"
    assert params_key({}) == ""


def test_fixture_is_valid_json() -> None:
    assert isinstance(json.loads(EVENTS), list)
