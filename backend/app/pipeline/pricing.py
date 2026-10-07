"""Quotes and daily bars: fetch, store, and recompute the ratios that move with price.

Providers are created once per process and shared, so every caller goes through the same
rate limiter. A provider that fails never fails the caller: the cached value is served.
"""

import logging
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app import market
from app.db.models import Company, PriceDaily, PriceFetch, Quote, Ratio, Ticker
from app.pipeline.ratios import price_ratios
from app.providers.alpaca import HISTORY_START, Alpaca, Bar
from app.providers.base import ProviderError
from app.providers.finnhub import Finnhub, QuoteData

log = logging.getLogger(__name__)

_lock = threading.Lock()
_providers: dict[str, object] = {}

# A cold stock's bars are not re-requested more often than this, even if a session is missing.
BARS_RETRY = timedelta(minutes=30)


def _provider(name: str, factory):
    with _lock:
        if name not in _providers:
            try:
                _providers[name] = factory()
            except ProviderError as exc:
                log.warning("%s unavailable: %s", name, exc)
                _providers[name] = None
        return _providers[name]


def finnhub() -> Finnhub | None:
    return _provider("finnhub", Finnhub)  # type: ignore[return-value]


def alpaca() -> Alpaca | None:
    return _provider("alpaca", Alpaca)  # type: ignore[return-value]


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------- quotes


def store_quote(session: Session, q: QuoteData) -> Quote:
    row = session.get(Quote, q.ticker) or Quote(ticker=q.ticker)
    row.price, row.change, row.change_pct = q.price, q.change, q.change_pct
    row.prev_close, row.open, row.high, row.low = q.prev_close, q.open, q.high, q.low
    row.quote_time, row.fetched_at = q.quote_time, utcnow()
    session.add(row)
    cik = session.scalar(
        select(Ticker.cik).where(Ticker.ticker == q.ticker, Ticker.is_primary.is_(True))
    )
    if cik is not None:
        apply_price(session, cik, q.price)
    return row


def refresh_quote(session: Session, ticker: str, background: bool = False) -> Quote | None:
    """Fetch and store a fresh quote. On any provider failure, return the cached one.
    `background` is for the quote loop, which must leave room for pages being opened."""
    client = finnhub()
    if client is not None:
        try:
            q = client.quote(ticker, background=background)
            if q is not None:
                row = store_quote(session, q)
                session.commit()
                return row
        except ProviderError as exc:
            log.warning("quote for %s failed: %s", ticker, exc)
            session.rollback()
    return session.get(Quote, ticker)


_refresher = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quote")
_in_flight: set[str] = set()


def refresh_quote_soon(ticker: str) -> bool:
    """Refresh a quote in the background, so a page never waits on Finnhub.
    Returns True if a refresh is now running for the ticker."""
    from app.db.session import session_scope

    if finnhub() is None:
        return False
    with _lock:
        if ticker in _in_flight:
            return True
        _in_flight.add(ticker)

    def run() -> None:
        try:
            with session_scope() as session:
                refresh_quote(session, ticker)
        finally:
            with _lock:
                _in_flight.discard(ticker)

    _refresher.submit(run)
    return True


def quote_is_stale(q: Quote | None, now: datetime | None = None) -> bool:
    """A quote needs refreshing if it is missing, older than 15 minutes while the market is
    open, or from before the latest close while it is shut."""
    if q is None:
        return True
    now = now or utcnow()
    if market.is_open():
        return now - q.fetched_at > timedelta(minutes=15)
    last_close = market.last_close_at().astimezone(UTC).replace(tzinfo=None)
    return q.fetched_at < last_close


def apply_price(session: Session, cik: int, price: float) -> None:
    """Recompute the price-based ratios for one company."""
    row = session.get(Ratio, cik)
    if row is None:
        return
    inputs = {
        c: getattr(row, c)
        for c in (
            "eps_ttm",
            "eps_growth_5y",
            "eps_growth_3y",
            "revenue_ttm",
            "ebitda_ttm",
            "fcf_ttm",
            "dps_ttm",
        )
    }
    for key, value in price_ratios(
        price, inputs, row.shares_outstanding, row.equity, row.debt, row.cash
    ).items():
        setattr(row, key, value)
    row.price, row.price_at = price, utcnow()


# ---------------------------------------------------------------- daily bars


def store_bars(session: Session, bars: Iterable[Bar]) -> int:
    rows = [
        {
            "ticker": b.ticker,
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
        }
        for b in bars
    ]
    for i in range(0, len(rows), 5000):
        stmt = insert(PriceDaily).values(rows[i : i + 5000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "date"],
            set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close")},
        )
        session.execute(stmt)
    return len(rows)


def _record_fetch(session: Session, ticker: str) -> None:
    first, last = session.execute(
        select(func.min(PriceDaily.date), func.max(PriceDaily.date)).where(
            PriceDaily.ticker == ticker
        )
    ).one()
    row = session.get(PriceFetch, ticker) or PriceFetch(ticker=ticker)
    row.fetched_at, row.first_date, row.last_date = utcnow(), first, last
    session.add(row)


def bars_needed(session: Session, ticker: str) -> date | None:
    """The start date to fetch from, or None if the stored bars are current."""
    fetch = session.get(PriceFetch, ticker)
    if fetch is None or fetch.last_date is None:
        if fetch is not None and utcnow() - fetch.fetched_at < BARS_RETRY:
            return None  # tried recently and Alpaca had nothing
        return HISTORY_START
    if fetch.last_date >= market.latest_complete_session():
        return None
    if utcnow() - fetch.fetched_at < BARS_RETRY:
        return None
    return fetch.last_date + timedelta(days=1)


def update_bars(session: Session, tickers: list[str], start: date | None = None) -> int:
    """Fetch and store bars for several tickers. Each starts where its stored bars end,
    unless `start` is given. Returns the number of bars stored."""
    client = alpaca()
    if client is None or not tickers:
        return 0
    starts = {t: start or bars_needed(session, t) or HISTORY_START for t in tickers}
    stored = 0
    # One request per distinct start date, so a batch of fresh tickers shares a request.
    by_start: dict[date, list[str]] = {}
    for t, s in starts.items():
        by_start.setdefault(s, []).append(t)
    # Stop at the latest finished session: a partial bar for today would be stored as if
    # it were the close. Today's price comes from the live quote instead.
    session_day = market.latest_complete_session()
    end = datetime.combine(session_day, time(20, 0), market.NY).astimezone(UTC)
    for s, group in by_start.items():
        if s > session_day:
            continue
        try:
            bars = client.daily_bars(group, start=s, end=end)
        except ProviderError as exc:
            log.warning("bars for %s failed: %s", ",".join(group[:5]), exc)
            continue
        for t in group:
            stored += store_bars(session, bars.get(t, []))
            _record_fetch(session, t)
        session.commit()
    return stored


def ensure_bars(session: Session, ticker: str) -> None:
    """Top up one ticker's bars if they are behind. Used on the request path."""
    start = bars_needed(session, ticker)
    if start is not None:
        update_bars(session, [ticker], start)


def warm_tickers(session: Session) -> list[str]:
    """Primary tickers of warm companies plus anything on the watchlist."""
    from app.db.models import WatchItem

    rows = session.scalars(
        select(Company.ticker).where(Company.tier == "warm").order_by(Company.ticker)
    ).all()
    watch = session.scalars(select(WatchItem.ticker)).all()
    return sorted(set(rows) | set(watch))
