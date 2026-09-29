class ProviderError(Exception):
    """Base class for provider access failures."""


class ProviderHTTPError(ProviderError):
    """Non-retryable HTTP status (for example 404)."""

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.url = url
        self.status = status


class ProviderBlockedError(ProviderError):
    """The provider answered with something other than the expected data (e.g. an HTML
    challenge page). Never stored as data; retrying immediately will not help."""


class RetryExhaustedError(ProviderError):
    """Retryable failures (429, 5xx, network errors) persisted past the attempt limit."""
