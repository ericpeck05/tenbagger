"""Build the demo database: real EDGAR fundamentals for ten companies, made-up prices, and a
made-up portfolio. Needs no keys and makes no network calls.

    python -m app.demo.build            # rebuild data/demo/tenbagger.db
    python -m app.demo.build --if-missing

Fundamentals and filings are EDGAR JSON from the repo (free to reuse). Every price is
invented: a seeded random walk per ticker since 2016, scaled so each stock ends at a
believable P/E. Nothing here comes from Finnhub or Alpaca.
"""

import argparse
import gzip
import json
import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from app import market
from app.config import get_settings
from app.db.models import PriceDaily, PriceFetch, Ratio, Ticker, Transaction, WatchItem
from app.db.session import get_engine, migrate, session_scope
from app.jobs.bulk_load import tidy_name
from app.jobs.load_sp500 import read_sp500
from app.pipeline import holdings, pricing
from app.pipeline.company import process_company
from app.pipeline.sector_medians import recompute
from app.providers.finnhub import QuoteData

HERE = Path(__file__).parent
FACTS = HERE.parents[1] / "tests" / "fixtures" / "edgar"
SUBMISSIONS = HERE / "submissions"
START = date(2016, 1, 4)
BENCHMARK = "SPY"
WATCHLIST = ["NVDA", "KO", "MSFT", "WMT"]


def trading_days(end: date) -> list[date]:
    days, d = [], START
    while d <= end:
        if market.is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def random_walk(ticker: str, days: list[date], last_close: float) -> list[PriceDaily]:
    """Daily bars from a seeded random walk that ends at `last_close`.

    The noise is pinned to a steady trend (a total gain of 30% to 200% since 2016), so every
    made-up chart rises over the decade with ordinary ups and downs along the way.
    """
    rng = random.Random(ticker)
    vol = rng.uniform(0.16, 0.30) / math.sqrt(252)
    noise, path = 0.0, []
    for _ in days:
        noise += vol * rng.gauss(0, 1)
        path.append(noise)
    total = math.log(1 + rng.uniform(0.3, 2.0))
    n = len(path) - 1
    path = [p - path[-1] * i / n + total * i / n for i, p in enumerate(path)]
    scale = math.log(last_close) - path[-1]
    bars, prev = [], math.exp(path[0] + scale)
    for d, lp in zip(days, path, strict=True):
        close = math.exp(lp + scale)
        open_ = prev * (1 + rng.gauss(0, vol / 3))
        spread = abs(rng.gauss(0, vol)) * close
        bars.append(
            PriceDaily(
                ticker=ticker,
                date=d,
                open=round(open_, 2),
                high=round(max(open_, close) + spread, 2),
                low=round(min(open_, close) - spread, 2),
                close=round(close, 2),
            )
        )
        prev = close
    return bars


def build() -> Path:
    settings = get_settings()
    db_path = settings.db_path
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    migrate(get_engine())
    last_day = market.latest_complete_session()
    days = trading_days(last_day)

    with session_scope() as session:
        tickers = []
        names = {cik: e["name"] for cik, e in read_sp500().items()}
        for path in sorted(SUBMISSIONS.glob("*.json.gz")):
            ticker = path.name.removesuffix(".json.gz")
            sub = json.loads(gzip.decompress(path.read_bytes()))
            facts = json.loads(gzip.decompress((FACTS / path.name).read_bytes()))
            process_company(
                session,
                int(sub["cik"]),
                sub,
                facts,
                tickers=[ticker],
                name=names.get(int(sub["cik"])) or tidy_name(sub["name"]),
                in_sp500=True,
            )
            tickers.append(ticker)
        session.commit()

        # Made-up prices: end each stock at a P/E between 14 and 34 so ratios look ordinary.
        for ticker in tickers:
            row = session.get(Ratio, session.get(Ticker, ticker).cik)
            eps = row.eps_ttm if row and row.eps_ttm and row.eps_ttm > 0 else 2.0
            rng = random.Random(f"{ticker}-pe")
            _store_prices(session, ticker, days, round(eps * rng.uniform(14, 34), 2))
        _store_prices(session, BENCHMARK, days, 640.0)

        for i, t in enumerate(WATCHLIST, 1):
            session.add(WatchItem(ticker=t, added_at=pricing.utcnow(), position=i))
        _portfolio(session, days)
        session.commit()
        holdings.rebuild_daily(session, fetch=False)
        recompute(session)
    return db_path


def _store_prices(session, ticker: str, days: list[date], last_close: float) -> None:
    bars = random_walk(ticker, days, last_close)
    session.add_all(bars)
    session.add(
        PriceFetch(
            ticker=ticker, fetched_at=pricing.utcnow(), first_date=days[0], last_date=days[-1]
        )
    )
    # The quote is the last made-up close, so the header and the chart agree.
    last, prev = bars[-1], bars[-2]
    quote = QuoteData(
        ticker=ticker,
        price=last.close,
        change=round(last.close - prev.close, 2),
        change_pct=round((last.close / prev.close - 1) * 100, 2),
        prev_close=prev.close,
        open=last.open,
        high=last.high,
        low=last.low,
        quote_time=datetime.combine(days[-1], datetime.min.time()),
    )
    pricing.store_quote(session, quote)
    session.commit()


def _close_on(session, ticker: str, day: date) -> float:
    return holdings.Closes(session, [ticker], day - timedelta(days=10))(ticker, day)


def _portfolio(session, days: list[date]) -> None:
    """A made-up account: one deposit, buys sized in dollars over two years, a trim, a
    dividend. The deposit covers every buy, so no implicit deposits are needed."""

    def on(offset: int) -> date:
        return days[-offset]

    # (type, ticker, dollars or shares, trading days ago)
    plan = [
        ("deposit", None, 80_000.0, 500),
        ("buy", "MSFT", 14_000.0, 495),
        ("buy", "KO", 9_000.0, 480),
        ("buy", BENCHMARK, 15_000.0, 470),
        ("buy", "NVDA", 12_000.0, 400),
        ("buy", "WMT", 10_000.0, 300),
        ("sell", "NVDA", 0.35, 150),  # a third of the position
        ("dividend", "KO", 58.80, 120),
        ("buy", "JPM", 8_000.0, 60),
    ]
    held: dict[str, int] = {}
    for kind, ticker, size, ago in plan:
        day = on(ago)
        if kind in ("buy", "sell"):
            price = _close_on(session, ticker, day)
            if kind == "buy":
                shares = max(int(size / price), 1)
                held[ticker] = held.get(ticker, 0) + shares
            else:
                shares = max(int(held[ticker] * size), 1)
                held[ticker] -= shares
            row = Transaction(
                date=day,
                type=kind,
                ticker=ticker,
                shares=shares,
                price=price,
                amount=round(shares * price, 2),
            )
        else:
            row = Transaction(date=day, type=kind, ticker=ticker, amount=size)
        row.note, row.created_at = "Demo trade", pricing.utcnow()
        session.add(row)
    session.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--if-missing", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.demo:
        print("Refusing to build: DEMO=true is not set, so this would overwrite real data.")
        return 1
    if args.if_missing and settings.db_path.exists():
        print(f"Demo database already built at {settings.db_path}")
        return 0
    print(f"Built the demo database at {build()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
