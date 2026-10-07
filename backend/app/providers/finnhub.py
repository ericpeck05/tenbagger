"""Finnhub adapter: current quotes only.

The free key allows 60 calls per minute (confirmed from the x-ratelimit-limit header on
2026-10-07); the limiter runs at the configured rate, 50 by default. Finnhub is not used for
price history: free keys have been reported as denied on the candles endpoint.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.providers.base import HttpProvider, ProviderError, RateLimiter

BASE_URL = "https://finnhub.io/api/v1"
BURST = 5  # tokens the bucket can hold; the quote loop leaves BACKGROUND_RESERVE of them
BACKGROUND_RESERVE = 3


@dataclass(frozen=True)
class QuoteData:
    ticker: str
    price: float
    change: float | None
    change_pct: float | None  # percent, e.g. 1.3 for +1.3%
    prev_close: float | None
    open: float | None
    high: float | None
    low: float | None
    quote_time: datetime | None


def _num(v) -> float | None:
    return float(v) if v is not None else None


class Finnhub(HttpProvider):
    name = "finnhub"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        settings = get_settings()
        key = settings.finnhub_api_key.get_secret_value().strip()
        if not key:
            raise ProviderError("FINNHUB_API_KEY is not set in .env")
        super().__init__(
            RateLimiter(settings.finnhub_per_minute, 60.0, burst=BURST),
            headers={"X-Finnhub-Token": key},
            timeout=10.0,
            max_attempts=3,
            transport=transport,
        )

    def quote(self, ticker: str, background: bool = False) -> QuoteData | None:
        """Latest quote, or None if Finnhub has no price for the symbol."""
        reserve = BACKGROUND_RESERVE if background else 0
        res = self.get(f"{BASE_URL}/quote", params={"symbol": ticker}, reserve=reserve)
        if res.status_code != 200:
            raise ProviderError(f"finnhub: HTTP {res.status_code} for {ticker}")
        d = res.json()
        # Unknown symbols come back as all zeros.
        if not d or not d.get("c") or not d.get("t"):
            return None
        return QuoteData(
            ticker=ticker,
            price=float(d["c"]),
            change=_num(d.get("d")),
            change_pct=_num(d.get("dp")),
            prev_close=_num(d.get("pc")),
            open=_num(d.get("o")),
            high=_num(d.get("h")),
            low=_num(d.get("l")),
            quote_time=datetime.fromtimestamp(d["t"], UTC).replace(tzinfo=None),
        )
