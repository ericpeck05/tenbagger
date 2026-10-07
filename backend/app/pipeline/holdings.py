"""The portfolio on top of the database: load the trade log, rebuild the daily series.

Trades never leave the local database.
"""

from bisect import bisect_right
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import market
from app.db.models import PortfolioDaily, PriceDaily, Transaction
from app.pipeline import pricing
from app.pipeline.portfolio import Book, Trade, daily, replay

BENCHMARK = "SPY"


def to_trade(row: Transaction) -> Trade:
    return Trade(
        date=row.date,
        type=row.type,
        ticker=row.ticker,
        shares=row.shares,
        price=row.price,
        amount=row.amount,
        id=row.id or 0,
    )


def load_trades(session: Session) -> list[Trade]:
    return [to_trade(r) for r in session.scalars(select(Transaction)).all()]


def book(session: Session) -> Book:
    return replay(load_trades(session))


def held_tickers(session: Session) -> list[str]:
    return sorted(book(session).held())


def traded_tickers(trades: list[Trade]) -> list[str]:
    return sorted({t.ticker for t in trades if t.ticker})


class Closes:
    """Latest close on or before a day, from prices_daily, loaded once per ticker."""

    def __init__(self, session: Session, tickers: list[str], since: date):
        self.series: dict[str, tuple[list[date], list[float]]] = {}
        for t in tickers:
            rows = session.execute(
                select(PriceDaily.date, PriceDaily.close)
                .where(PriceDaily.ticker == t, PriceDaily.date >= since)
                .order_by(PriceDaily.date)
            ).all()
            self.series[t] = ([r[0] for r in rows], [r[1] for r in rows])

    def __call__(self, ticker: str, day: date) -> float | None:
        dates, closes = self.series.get(ticker, ([], []))
        i = bisect_right(dates, day)
        return closes[i - 1] if i else None

    def dates(self, ticker: str) -> list[date]:
        return self.series.get(ticker, ([], []))[0]


def rebuild_daily(session: Session, fetch: bool = True) -> int:
    """Rebuild portfolio_daily from the first trade. Returns the number of days."""
    trades = load_trades(session)
    session.execute(delete(PortfolioDaily))
    if not trades:
        session.commit()
        return 0
    tickers = traded_tickers(trades)
    if fetch:
        for t in [*tickers, BENCHMARK]:
            pricing.ensure_bars(session, t)
    start = min(t.date for t in trades)
    closes = Closes(session, [*tickers, BENCHMARK], start)

    # Trading days come from the benchmark; fall back to the holdings' own bar dates.
    days = closes.dates(BENCHMARK) or sorted({d for t in tickers for d in closes.dates(t)})
    last = market.latest_complete_session()
    days = [d for d in days if d <= last]
    # Trades after the last close (today, a weekend) still need a day to land on.
    newest_trade = max(t.date for t in trades)
    if not days or newest_trade > days[-1]:
        days.append(max(newest_trade, days[-1]) if days else newest_trade)

    for d in daily(trades, days, closes):
        session.add(
            PortfolioDaily(
                date=d.date,
                value=d.value,
                cash=d.cash,
                net_deposits=d.net_deposits,
                return_index=d.return_index,
            )
        )
    session.commit()
    return len(days)


def daily_is_stale(session: Session) -> bool:
    has_trades = session.scalar(select(Transaction.id).limit(1)) is not None
    if not has_trades:
        return False
    last = session.scalar(select(PortfolioDaily.date).order_by(PortfolioDaily.date.desc()))
    return last is None or last < market.latest_complete_session()
