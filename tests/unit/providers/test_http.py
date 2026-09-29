import gzip
from collections.abc import Callable, Iterator

import httpx
import pytest

from edgeforge.providers.errors import (
    ProviderBlockedError,
    ProviderHTTPError,
    RetryExhaustedError,
)
from edgeforge.providers.http import FetchPolicy, HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter

URL = "https://understat.com/getLeagueData/EPL/2026"
Responder = Callable[[httpx.Request], httpx.Response]


def _fetcher(
    responses: list[httpx.Response | Exception],
    sleeps: list[float],
    policy: FetchPolicy | None = None,
) -> tuple[HttpFetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue: Iterator[httpx.Response | Exception] = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = next(queue)
        if isinstance(item, Exception):
            raise item
        return item

    client = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = RateLimiter(1000, burst=1000)
    fetcher = HttpFetcher(client, limiter, policy, sleep=sleeps.append, jitter=lambda: 0.0)
    return fetcher, seen


def test_returns_json_body_and_sends_headers() -> None:
    sleeps: list[float] = []
    fetcher, seen = _fetcher([httpx.Response(200, json={"dates": []})], sleeps)

    result = fetcher.get(URL, headers={"X-Requested-With": "XMLHttpRequest"})

    assert result.status == 200
    assert result.body == b'{"dates":[]}'
    assert result.fetched_at.tzinfo is not None
    assert seen[0].headers["X-Requested-With"] == "XMLHttpRequest"
    assert sleeps == []


def test_retries_server_errors_with_exponential_backoff() -> None:
    sleeps: list[float] = []
    fetcher, seen = _fetcher(
        [httpx.Response(503), httpx.Response(502), httpx.Response(200, json={})], sleeps
    )

    fetcher.get(URL)

    assert len(seen) == 3
    assert sleeps == [2.0, 4.0]


def test_retries_network_errors() -> None:
    sleeps: list[float] = []
    fetcher, seen = _fetcher([httpx.ConnectError("reset"), httpx.Response(200, json={})], sleeps)

    fetcher.get(URL)

    assert len(seen) == 2


def test_honours_retry_after_on_429() -> None:
    sleeps: list[float] = []
    fetcher, _ = _fetcher(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})], sleeps
    )

    fetcher.get(URL)

    assert sleeps == [7.0]


def test_backoff_is_capped() -> None:
    sleeps: list[float] = []
    policy = FetchPolicy(max_attempts=4, backoff_base_seconds=50, backoff_max_seconds=60)
    fetcher, _ = _fetcher(
        [httpx.Response(500)] * 3 + [httpx.Response(200, json={})], sleeps, policy
    )

    fetcher.get(URL)

    assert sleeps == [50.0, 60.0, 60.0]


def test_gives_up_after_max_attempts() -> None:
    sleeps: list[float] = []
    fetcher, seen = _fetcher([httpx.Response(503)] * 3, sleeps, FetchPolicy(max_attempts=3))

    with pytest.raises(RetryExhaustedError, match="HTTP 503 after 3 attempts"):
        fetcher.get(URL)

    assert len(seen) == 3
    assert len(sleeps) == 2


def test_client_errors_are_not_retried() -> None:
    sleeps: list[float] = []
    fetcher, seen = _fetcher([httpx.Response(404)], sleeps)

    with pytest.raises(ProviderHTTPError) as excinfo:
        fetcher.get(URL)

    assert excinfo.value.status == 404
    assert len(seen) == 1


def test_html_instead_of_json_is_a_block_not_data() -> None:
    sleeps: list[float] = []
    page = httpx.Response(200, text="<html><title>Just a moment...</title></html>")
    fetcher, seen = _fetcher([page], sleeps)

    with pytest.raises(ProviderBlockedError, match="did not return JSON"):
        fetcher.get(URL)

    assert len(seen) == 1


def test_undeclared_gzip_body_is_decompressed() -> None:
    sleeps: list[float] = []
    fetcher, _ = _fetcher([httpx.Response(200, content=gzip.compress(b'{"a": 1}'))], sleeps)

    assert fetcher.get(URL).body == b'{"a": 1}'


def test_non_json_allowed_when_policy_says_so() -> None:
    sleeps: list[float] = []
    policy = FetchPolicy(expect_json=False)
    fetcher, _ = _fetcher([httpx.Response(200, text="Div,Date,HomeTeam\nE0,...")], sleeps, policy)

    assert fetcher.get(URL).body.startswith(b"Div,Date")
