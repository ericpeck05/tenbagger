"""Shared plumbing for provider adapters: a rate limiter and a retrying HTTP client."""

import logging
import threading
import time
from collections.abc import Mapping

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ProviderError(Exception):
    """A provider call failed after retries, or returned something unusable."""


class RateLimiter:
    """Spaces calls evenly so a provider never sees more than `rate` calls per `per` seconds.

    Thread-safe. Callers block in `wait()` until their slot comes up.
    """

    def __init__(self, rate: float, per: float = 1.0):
        if rate <= 0 or per <= 0:
            raise ValueError("rate and per must be positive")
        self.interval = per / rate
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


class HttpProvider:
    """An httpx client where every request goes through the limiter and retries on 429 and 5xx."""

    name = "provider"

    def __init__(
        self,
        limiter: RateLimiter,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        max_attempts: int = 4,
        transport: httpx.BaseTransport | None = None,
    ):
        self.limiter = limiter
        self.max_attempts = max_attempts
        self.client = httpx.Client(
            headers=dict(headers or {}),
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def get(self, url: str, params: Mapping[str, str] | None = None) -> httpx.Response:
        for attempt in range(1, self.max_attempts + 1):
            self.limiter.wait()
            try:
                res = self.client.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == self.max_attempts:
                    raise ProviderError(f"{self.name}: {exc.__class__.__name__} on {url}") from exc
                self._backoff(attempt, None)
                continue
            if res.status_code in RETRY_STATUSES and attempt < self.max_attempts:
                log.warning("%s: HTTP %s on %s, retrying", self.name, res.status_code, url)
                self._backoff(attempt, res)
                continue
            return res
        raise AssertionError("unreachable")

    @staticmethod
    def _backoff(attempt: int, res: httpx.Response | None) -> None:
        retry_after = res.headers.get("retry-after") if res is not None else None
        if retry_after and retry_after.isdigit():
            delay = min(float(retry_after), 60.0)
        else:
            delay = min(2.0 ** (attempt - 1), 30.0)
        time.sleep(delay)

    def close(self) -> None:
        self.client.close()
