"""HTTP fetching for providers: rate limiting, retries with backoff, and response checks."""

import gzip
import json
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from edgeforge.core.logging import get_logger
from edgeforge.core.time import utcnow
from edgeforge.providers.errors import (
    ProviderBlockedError,
    ProviderHTTPError,
    RetryExhaustedError,
)
from edgeforge.providers.ratelimit import RateLimiter

log = get_logger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
GZIP_MAGIC = b"\x1f\x8b"


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    max_attempts: int = 5
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 120.0
    expect_json: bool = True


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status: int
    body: bytes
    fetched_at: datetime
    headers: Mapping[str, str] = field(default_factory=dict)


class HttpFetcher:
    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter,
        policy: FetchPolicy | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._policy = policy or FetchPolicy()
        self._sleep = sleep
        self._jitter = jitter

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> FetchResult:
        policy = self._policy
        last_problem = ""
        for attempt in range(1, policy.max_attempts + 1):
            self._limiter.acquire()
            try:
                response = self._client.get(url, headers=headers)
            except httpx.TransportError as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
                retry_after = None
            else:
                if response.status_code in RETRYABLE_STATUS:
                    last_problem = f"HTTP {response.status_code}"
                    retry_after = _retry_after_seconds(response)
                elif response.status_code >= 400:
                    raise ProviderHTTPError(url, response.status_code)
                else:
                    body = _decoded_body(response.content)
                    if policy.expect_json:
                        _ensure_json(url, body)
                    return FetchResult(
                        url=url,
                        status=response.status_code,
                        body=body,
                        fetched_at=utcnow(),
                        headers=dict(response.headers),
                    )

            if attempt == policy.max_attempts:
                break
            delay = self._backoff(attempt, retry_after)
            log.warning(
                "provider_fetch_retry", url=url, attempt=attempt, problem=last_problem, delay=delay
            )
            self._sleep(delay)

        raise RetryExhaustedError(f"{url}: {last_problem} after {policy.max_attempts} attempts")

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        policy = self._policy
        if retry_after is not None:
            return min(retry_after, policy.backoff_max_seconds)
        exponential = policy.backoff_base_seconds * 2.0 ** (attempt - 1)
        return min(exponential * (1 + self._jitter()), policy.backoff_max_seconds)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _decoded_body(content: bytes) -> bytes:
    """Some providers gzip bodies without a Content-Encoding header; undo that."""
    if content.startswith(GZIP_MAGIC):
        return gzip.decompress(content)
    return content


def _ensure_json(url: str, body: bytes) -> None:
    try:
        json.loads(body)
    except ValueError:
        preview = body[:200].decode("utf-8", errors="replace")
        raise ProviderBlockedError(f"{url} did not return JSON: {preview!r}") from None
