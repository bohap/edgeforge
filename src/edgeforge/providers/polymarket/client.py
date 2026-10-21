"""Polymarket's public Gamma API: no account or key is needed to read prices.

A league refresh lists the open events of the league's series without their markets (light),
then fetches the full main event and its "More Markets" companion for each upcoming game in
one request per batch of slugs.
"""

from collections.abc import Sequence
from urllib.parse import urlencode

PROVIDER_CODE = "polymarket"
GAMMA_URL = "https://gamma-api.polymarket.com"
SITE_URL = "https://polymarket.com"

PAGE_SIZE = 100
SLUGS_PER_REQUEST = 20
MORE_MARKETS_SUFFIX = "-more-markets"

# Our competition code -> Polymarket series id (``GET /sports``).
SERIES = {
    "EPL": 10188,
    "LA_LIGA": 10193,
    "BUNDESLIGA": 10194,
    "SERIE_A": 10203,
    "LIGUE_1": 10195,
    "RPL": 10313,
}


def listing_url(series_id: int, offset: int) -> str:
    query = {
        "series_id": series_id,
        "closed": "false",
        "include_markets": "false",
        "limit": PAGE_SIZE,
        "offset": offset,
    }
    return f"{GAMMA_URL}/events?{urlencode(query)}"


def events_url(slugs: Sequence[str]) -> str:
    return f"{GAMMA_URL}/events?{urlencode([('slug', s) for s in slugs])}"


def event_page_url(slug: str) -> str:
    """The event's page on polymarket.com."""
    return f"{SITE_URL}/event/{slug}"
