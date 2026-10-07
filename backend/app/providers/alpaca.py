"""Alpaca adapter: split-adjusted daily bars.

The free Basic plan serves the consolidated SIP feed for history as long as a request ends
at least 15 minutes ago, and its history starts in January 2016. (The IEX feed, which has no
delay, only goes back to July 2020.) So every request asks for SIP and ends 16 minutes ago.
Closes from SIP are market-wide; volume is too, but the app does not show volume.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx

from app.config import get_settings
from app.providers.base import HttpProvider, ProviderError, RateLimiter

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
HISTORY_START = date(2016, 1, 1)
SIP_DELAY = timedelta(minutes=16)
PAGE_LIMIT = 10_000


@dataclass(frozen=True)
class Bar:
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float


class Alpaca(HttpProvider):
    name = "alpaca"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        settings = get_settings()
        key_id = settings.alpaca_key_id.get_secret_value().strip()
        secret = settings.alpaca_secret_key.get_secret_value().strip()
        if not key_id or not secret:
            raise ProviderError("ALPACA_KEY_ID and ALPACA_SECRET_KEY must be set in .env")
        super().__init__(
            RateLimiter(settings.alpaca_per_minute, 60.0),
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
            timeout=30.0,
            transport=transport,
        )

    def daily_bars(
        self, tickers: list[str], start: date = HISTORY_START, end: datetime | None = None
    ) -> dict[str, list[Bar]]:
        """Daily bars for up to a few hundred tickers in one paginated request."""
        if not tickers:
            return {}
        end = min(end or datetime.now(UTC), datetime.now(UTC) - SIP_DELAY)
        params = {
            "symbols": ",".join(tickers),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "feed": "sip",
            "adjustment": "split",
            "limit": str(PAGE_LIMIT),
        }
        out: dict[str, list[Bar]] = defaultdict(list)
        token = None
        while True:
            page = dict(params, page_token=token) if token else params
            res = self.get(BARS_URL, params=page)
            if res.status_code != 200:
                raise ProviderError(f"alpaca: HTTP {res.status_code}: {res.text[:200]}")
            body = res.json()
            for ticker, bars in (body.get("bars") or {}).items():
                for b in bars:
                    out[ticker].append(
                        Bar(
                            ticker=ticker,
                            # Daily bar timestamps are midnight New York time, in UTC.
                            date=datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date(),
                            open=float(b["o"]),
                            high=float(b["h"]),
                            low=float(b["l"]),
                            close=float(b["c"]),
                        )
                    )
            token = body.get("next_page_token")
            if not token:
                return dict(out)
