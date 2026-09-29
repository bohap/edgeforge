"""Live checks against understat.com. Run manually: ``uv run pytest -m network``."""

from collections.abc import Iterator

import httpx
import pytest

from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.client import (
    EXPECTED_UNMODELLED,
    League,
    fetch,
    league_ref,
    match_ref,
    parse_league,
    parse_match,
)
from edgeforge.providers.understat.schemas import unknown_fields

pytestmark = pytest.mark.network

SEASON = 2025


@pytest.fixture(scope="module")
def fetcher() -> Iterator[HttpFetcher]:
    with httpx.Client(timeout=30) as client:
        yield HttpFetcher(client, RateLimiter(0.4))


@pytest.mark.parametrize("league", list(League))
def test_league_and_one_match_parse(fetcher: HttpFetcher, league: League) -> None:
    payload = parse_league(fetch(fetcher, league_ref(league, SEASON)).body)
    played = [f for f in payload.dates if f.is_result]
    match = parse_match(fetch(fetcher, match_ref(played[0].id)).body)

    assert played
    assert unknown_fields(payload) - EXPECTED_UNMODELLED == set()
    assert unknown_fields(match) - EXPECTED_UNMODELLED == set()
    # Shot xG sums can differ from the match total by a few thousandths (observed in the
    # Bundesliga and Ligue 1), so consistency checks use a 0.01 tolerance.
    assert sum(s.xg for s in match.shots.h) == pytest.approx(played[0].xg.h, abs=0.01)
