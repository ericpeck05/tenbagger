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
    """A token bucket: at most `rate` calls per `per` seconds, with bursts up to `burst`.

    Thread-safe. Background work passes a `reserve`, which keeps that many tokens free for
    calls made while someone is waiting on a page. So a stock opened during the quote loop
    never queues behind it, and the total still stays within the limit.
    """

    def __init__(self, rate: float, per: float = 1.0, burst: int = 1):
        if rate <= 0 or per <= 0 or burst < 1:
            raise ValueError("rate, per, and burst must be positive")
        self.fill_rate = rate / per  # tokens per second
        self.capacity = float(burst)
        self._tokens = float(burst)
        self._stamp = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        self._tokens = min(self.capacity, self._tokens + (now - self._stamp) * self.fill_rate)
        self._stamp = now

    def wait(self, reserve: int = 0) -> None:
        reserve = min(reserve, int(self.capacity) - 1)
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(now)
                if self._tokens - reserve >= 1:
                    self._tokens -= 1
                    return
                delay = (1 + reserve - self._tokens) / self.fill_rate
            time.sleep(min(delay, 1.0))


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

    def get(
        self, url: str, params: Mapping[str, str] | None = None, reserve: int = 0
    ) -> httpx.Response:
        """GET through the rate limiter. Background callers pass a `reserve` (see RateLimiter)."""
        for attempt in range(1, self.max_attempts + 1):
            self.limiter.wait(reserve)
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
