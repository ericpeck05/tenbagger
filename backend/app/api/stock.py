"""Stock page endpoints. Fundamentals come from the database; only the quote and price bars
are ever fetched on request, and only when the stored ones are out of date."""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import market
from app.db.models import (
    RATIO_COLUMNS,
    Company,
    CompanyView,
    FactRow,
    Filing,
    PriceDaily,
    PriceFetch,
    Quote,
    Ratio,
    Ticker,
    WatchItem,
)
from app.db.session import DbSession
from app.pipeline import pricing

router = APIRouter()

TREND_YEARS = 10
RANGES = {"1M": 31, "6M": 183, "1Y": 366, "5Y": 5 * 366}
WEEKLY_AFTER_DAYS = 190  # daily candles up to 6 months, weekly beyond


def find_company(session: Session, ticker: str) -> tuple[str, Company]:
    symbol = ticker.upper().replace("-", ".")
    row = session.get(Ticker, symbol)
    company = session.get(Company, row.cik) if row else None
    if company is None:
        raise HTTPException(404, f"No company with ticker {symbol}")
    return symbol, company


def quote_json(q: Quote | None) -> dict | None:
    if q is None:
        return None
    return {
        "price": q.price,
        "change": q.change,
        "change_pct": q.change_pct,
        "prev_close": q.prev_close,
        "open": q.open,
        "high": q.high,
        "low": q.low,
        "quote_time": q.quote_time.isoformat() + "Z" if q.quote_time else None,
        "fetched_at": q.fetched_at.isoformat() + "Z",
    }


def range_52w(session: Session, ticker: str) -> dict | None:
    since = date.today() - timedelta(days=365)
    low, high = session.execute(
        select(func.min(PriceDaily.low), func.max(PriceDaily.high)).where(
            PriceDaily.ticker == ticker, PriceDaily.date >= since
        )
    ).one()
    return {"low": low, "high": high} if low is not None else None


def annual_series(session: Session, cik: int) -> dict:
    rows = session.execute(
        select(FactRow.metric, FactRow.period_end, FactRow.value).where(
            FactRow.cik == cik,
            FactRow.fiscal_period == "FY",
            FactRow.period_start.is_not(None),
            FactRow.metric.in_(("revenue", "eps_diluted")),
        )
    ).all()
    from app.pipeline.ttm import fiscal_year

    series: dict[str, dict[int, float]] = {"revenue": {}, "eps_diluted": {}}
    for metric, end, value in sorted(rows, key=lambda r: r[1]):
        series[metric][fiscal_year(end)] = value
    years = sorted(set(series["revenue"]) | set(series["eps_diluted"]))[-TREND_YEARS:]
    return {
        "years": years,
        "revenue": [series["revenue"].get(y) for y in years],
        "eps": [series["eps_diluted"].get(y) for y in years],
    }


# How many of each kind the filings panel shows: the latest annual and quarterly report,
# then the newest current reports and insider filings.
FILING_MIX = (("10-K", 1), ("10-Q", 1), ("8-K", 2), ("4", 2))


def recent_filings(session: Session, cik: int) -> list[dict]:
    picked: list[Filing] = []
    for form, count in FILING_MIX:
        picked += session.scalars(
            select(Filing)
            .where(Filing.cik == cik, Filing.form.in_((form, f"{form}/A")))
            .order_by(Filing.filed_at.desc(), Filing.accession.desc())
            .limit(count)
        ).all()
    picked.sort(key=lambda f: f.filed_at, reverse=True)
    return [
        {"form": f.form, "title": f.title, "filed_at": f.filed_at.isoformat(), "url": f.url}
        for f in picked
    ]


@router.get("/stock/{ticker}")
def stock(ticker: str, session: DbSession) -> dict:
    symbol, company = find_company(session, ticker)
    ratios = session.get(Ratio, company.cik)

    # The page never waits on Finnhub: a missing or stale quote is served as it is (with its
    # age) and refreshed in the background. The page polls until the fresh one lands.
    quote = session.get(Quote, symbol)
    refreshing = pricing.quote_is_stale(quote) and pricing.refresh_quote_soon(symbol)

    company.view_count = (company.view_count or 0) + 1
    company.last_viewed_at = pricing.utcnow()
    session.add(CompanyView(cik=company.cik, viewed_at=company.last_viewed_at))
    session.commit()

    fetch = session.get(PriceFetch, symbol)
    tickers = session.scalars(select(Ticker.ticker).where(Ticker.cik == company.cik)).all()
    return {
        "ticker": symbol,
        "tickers": sorted(tickers),
        "cik": company.cik,
        "name": company.name,
        "exchange": company.exchange,
        "sector": company.sector,
        "industry": company.sic_description,
        "tier": company.tier,
        "supported": company.supported,
        "watching": session.get(WatchItem, symbol) is not None,
        "quote": quote_json(quote),
        "quote_refreshing": refreshing,
        "ratios": ({c: getattr(ratios, c) for c in RATIO_COLUMNS} if ratios is not None else None),
        "range_52w": range_52w(session, symbol),
        "annual": annual_series(session, company.cik),
        "filings": recent_filings(session, company.cik),
        "lynch": None,  # phase 5
        "sector_medians": None,  # phase 5
        "ranges_5y": None,  # phase 5
        "market_open": market.is_open(),
        "sources": {
            "fundamentals": {
                "provider": "SEC EDGAR",
                "through": ratios.fundamentals_through.isoformat()
                if ratios and ratios.fundamentals_through
                else None,
                "form": ratios.fundamentals_form if ratios else None,
                "period_end": ratios.as_of.isoformat() if ratios and ratios.as_of else None,
            },
            "quote": {
                "provider": "Finnhub",
                "fetched_at": quote_json(quote)["fetched_at"] if quote else None,
            },
            "prices": {
                "provider": "Alpaca, SIP feed",
                "last_date": fetch.last_date.isoformat() if fetch and fetch.last_date else None,
            },
        },
    }


def _range_start(range_: str, last: date) -> date | None:
    if range_ == "MAX":
        return None
    if range_ == "YTD":
        return date(last.year, 1, 1)
    return last - timedelta(days=RANGES[range_])


def _weekly(bars: list[PriceDaily]) -> list[dict]:
    out: list[dict] = []
    week = None
    for b in bars:
        key = b.date.isocalendar()[:2]
        if key != week:
            week = key
            out.append(
                {
                    "time": b.date.isoformat(),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                }
            )
        else:
            w = out[-1]
            w["high"], w["low"] = max(w["high"], b.high), min(w["low"], b.low)
            w["close"] = b.close
    return out


@router.get("/stock/{ticker}/prices")
def prices(
    ticker: str,
    session: DbSession,
    range_: Annotated[str, Query(alias="range", pattern="^(1M|6M|YTD|1Y|5Y|MAX)$")] = "1Y",
) -> dict:
    symbol, _company = find_company(session, ticker)
    pricing.ensure_bars(session, symbol)

    last = session.scalar(select(func.max(PriceDaily.date)).where(PriceDaily.ticker == symbol))
    if last is None:
        return {
            "ticker": symbol,
            "range": range_,
            "interval": "1d",
            "bars": [],
            "change_pct": None,
            "range_52w": None,
            "last_date": None,
        }
    start = _range_start(range_, last)
    query = select(PriceDaily).where(PriceDaily.ticker == symbol)
    if start:
        query = query.where(PriceDaily.date >= start)
    bars = session.scalars(query.order_by(PriceDaily.date)).all()

    # Change over the range: last close against the close just before the range began.
    base = None
    if start:
        base = session.scalar(
            select(PriceDaily.close)
            .where(PriceDaily.ticker == symbol, PriceDaily.date < start)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )
    base = base or bars[0].open
    span = (bars[-1].date - bars[0].date).days
    weekly = span > WEEKLY_AFTER_DAYS
    series = (
        _weekly(bars)
        if weekly
        else [
            {
                "time": b.date.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
            }
            for b in bars
        ]
    )
    return {
        "ticker": symbol,
        "range": range_,
        "interval": "1w" if weekly else "1d",
        "bars": series,
        "change_pct": (bars[-1].close / base - 1) * 100 if base else None,
        "range_52w": range_52w(session, symbol),
        "last_date": last.isoformat(),
        "fetched_at": (lambda f: f.fetched_at.isoformat() + "Z" if f else None)(
            session.get(PriceFetch, symbol)
        ),
        "today": datetime.now(market.NY).date().isoformat(),
    }
