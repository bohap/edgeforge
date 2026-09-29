"""Understat endpoints and request conventions.

Since 2025 the site loads data from JSON endpoints that require an XHR-style request:
``X-Requested-With``, a browser ``User-Agent`` and an understat.com ``Referer``.
"""

from dataclasses import dataclass
from enum import StrEnum

from edgeforge.core.logging import get_logger
from edgeforge.providers.http import FetchResult, HttpFetcher
from edgeforge.providers.understat.schemas import (
    LeaguePayload,
    MatchPayload,
    unknown_fields,
)

log = get_logger(__name__)

BASE_URL = "https://understat.com"
PROVIDER_CODE = "understat"
HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
}
# Fields we know about and intentionally ignore: running totals in team history, and match
# context repeated on every shot.
_SHOT_CONTEXT = ("season", "date", "h_team", "a_team", "h_goals", "a_goals")
EXPECTED_UNMODELLED = frozenset(
    {f"teams.{{}}.history.[].{name}" for name in ("wins", "draws", "loses", "npxGD")}
    | {f"shots.{side}.[].{name}" for side in ("h", "a") for name in _SHOT_CONTEXT}
    | {"tmpl"}
)


class League(StrEnum):
    EPL = "EPL"
    LA_LIGA = "La_liga"
    BUNDESLIGA = "Bundesliga"
    SERIE_A = "Serie_A"
    LIGUE_1 = "Ligue_1"
    RFPL = "RFPL"


class Resource(StrEnum):
    LEAGUE = "league"
    MATCH = "match"


@dataclass(frozen=True, slots=True)
class ResourceRef:
    resource: Resource
    key: str
    url: str


def league_ref(league: League, season: int) -> ResourceRef:
    """``season`` is the starting year: 2026 means 2026/27."""
    return ResourceRef(
        Resource.LEAGUE, f"{league.value}/{season}", f"{BASE_URL}/getLeagueData/{league}/{season}"
    )


def match_ref(match_id: int) -> ResourceRef:
    return ResourceRef(Resource.MATCH, str(match_id), f"{BASE_URL}/getMatchData/{match_id}")


def parse_league(body: bytes) -> LeaguePayload:
    payload = LeaguePayload.model_validate_json(body)
    _report_unknown("league", unknown_fields(payload))
    return payload


def parse_match(body: bytes) -> MatchPayload:
    payload = MatchPayload.model_validate_json(body)
    _report_unknown("match", unknown_fields(payload))
    return payload


def fetch(fetcher: HttpFetcher, ref: ResourceRef) -> FetchResult:
    return fetcher.get(ref.url, headers=HEADERS)


def _report_unknown(resource: str, fields: set[str]) -> None:
    unexpected = sorted(fields - EXPECTED_UNMODELLED)
    if unexpected:
        log.warning("understat_unknown_fields", resource=resource, fields=unexpected)
