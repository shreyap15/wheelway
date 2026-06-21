"""Shared HTTP request helpers with retry logic for Google API calls.

Provides a tenacity-decorated request function that retries on transient
failures (HTTP 429, 5xx, connection errors, timeouts) with exponential
backoff. After exhausting retries, raises ServiceDegraded so the calling
agent can return a degraded verdict instead of crashing.
"""

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class ServiceDegraded(Exception):
    """Raised when an external API is unreachable after all retries."""
    pass


class _Retryable(Exception):
    """Internal: signals tenacity to retry the request."""
    pass


def get_session() -> requests.Session:
    """Return a shared requests.Session with sensible defaults."""
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    return session


_session = get_session()


@retry(
    retry=retry_if_exception_type(_Retryable),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _do_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json: dict | None = None,
    timeout: int = 60,
) -> requests.Response:
    """Execute the HTTP request, raising _Retryable on transient errors."""
    try:
        resp = _session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            timeout=timeout,
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise _Retryable(str(exc)) from exc

    if resp.status_code == 429 or resp.status_code >= 500:
        raise _Retryable(
            f"HTTP {resp.status_code} from {url}: {resp.text[:200]}"
        )

    return resp


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json: dict | None = None,
    timeout: int = 60,
) -> requests.Response:
    """Make an HTTP request with automatic retry on transient failures.

    Retries up to 5 times with exponential backoff (2s..30s) on:
      - HTTP 429 (rate limit)
      - HTTP 5xx (server error)
      - requests.ConnectionError
      - requests.Timeout

    Args:
        method: HTTP method (GET, POST, etc.).
        url: Full URL.
        headers: Optional request headers.
        params: Optional query parameters.
        json: Optional JSON body.
        timeout: Request timeout in seconds (default 60).

    Returns:
        requests.Response on success.

    Raises:
        ServiceDegraded: After all retries are exhausted.
    """
    try:
        return _do_request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            timeout=timeout,
        )
    except _Retryable as exc:
        raise ServiceDegraded(
            f"API unavailable after 5 retries: {url}"
        ) from exc
