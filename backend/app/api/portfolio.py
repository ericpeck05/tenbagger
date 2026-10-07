"""Portfolio endpoints: the summary page, performance against the benchmark, and the trade log.

Everything here reads and writes the local database only. Trades never leave this machine.
"""

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import market
from app.api.stock import quote_json
from app.db.models import (
    Company,
    Filing,
    PortfolioDaily,
    PriceDaily,
    Quote,
    Ratio,
    Ticker,
    Transaction,
)
from app.db.session import DbSession
from app.pipeline import holdings, pricing
from app.pipeline.portfolio import Trade, TradeError, replay

router = APIRouter()

REPORT_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A")
RANGE_DAYS = {"1M": 31, "6M": 183, "1Y": 366}


# ---------------------------------------------------------------- trade log


class TradeIn(BaseModel):
    date: date
    type: Literal["buy", "sell", "deposit", "withdrawal", "dividend"]
    ticker: str | None = Field(default=None, max_length=12)
    shares: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)


def tx_json(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.date.isoformat(),
        "type": t.type,
        "ticker": t.ticker,
        "shares": t.shares,
        "price": t.price,
        "amount": t.amount,
        "note": t.note,
    }


def _normalize(session: Session, body: TradeIn) -> dict:
    """Validate one trade on its own and return the column values to store."""
    if body.date > market.now_ny().date():
        raise HTTPException(400, "The date is in the future")
    ticker = body.ticker.strip().upper().replace("-", ".") if body.ticker else None
    if body.type in ("buy", "sell"):
        if not ticker:
            raise HTTPException(400, "A buy or sell needs a ticker")
        if body.shares is None or body.price is None:
            raise HTTPException(400, "A buy or sell needs shares and a price")
        _check_ticker(session, ticker)
        return {
            "ticker": ticker,
            "shares": body.shares,
            "price": body.price,
            "amount": body.shares * body.price,
        }
    if body.amount is None:
        raise HTTPException(400, f"A {body.type} needs an amount")
    if ticker:
        _check_ticker(session, ticker)
    return {
        "ticker": ticker if body.type == "dividend" else None,
        "shares": None,
        "price": None,
        "amount": body.amount,
    }


def _check_ticker(session: Session, ticker: str) -> None:
    """Known companies are fine. Anything else (a fund, an ETF) must have a quote."""
    if session.get(Ticker, ticker) is not None or session.get(Quote, ticker) is not None:
        return
    q = pricing.refresh_quote(session, ticker)
    if q is None:
        raise HTTPException(400, f"Unknown ticker {ticker}: no company or quote found")


def _check_log(session: Session, changed: Trade | None, drop_id: int | None = None) -> None:
    """Replay the whole log with the change applied; reject it if any step fails."""
    trades = [t for t in holdings.load_trades(session) if t.id != drop_id]
    if changed is not None:
        trades.append(changed)
    try:
        replay(trades)
    except TradeError as exc:
        raise HTTPException(400, str(exc)) from exc


def _after_change(session: Session, tickers: list[str]) -> None:
    for t in tickers:
        cik = session.scalar(select(Ticker.cik).where(Ticker.ticker == t))
        company = session.get(Company, cik) if cik else None
        if company is not None:
            company.tier = "warm"  # holdings keep a fresh quote
    session.commit()
    holdings.rebuild_daily(session)


@router.get("/transactions")
def list_transactions(session: DbSession) -> list[dict]:
    rows = session.scalars(
        select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc())
    ).all()
    return [tx_json(t) for t in rows]


@router.post("/transactions", status_code=201)
def add_transaction(body: TradeIn, session: DbSession) -> dict:
    values = _normalize(session, body)
    candidate = Trade(date=body.date, type=body.type, id=10**12, **values)
    _check_log(session, candidate)
    row = Transaction(
        date=body.date, type=body.type, note=body.note, created_at=pricing.utcnow(), **values
    )
    session.add(row)
    session.flush()
    _after_change(session, [values["ticker"]] if values["ticker"] else [])
    return tx_json(row)


@router.put("/transactions/{tx_id}")
def edit_transaction(tx_id: int, body: TradeIn, session: DbSession) -> dict:
    row = session.get(Transaction, tx_id)
    if row is None:
        raise HTTPException(404, "No such trade")
    values = _normalize(session, body)
    _check_log(session, Trade(date=body.date, type=body.type, id=tx_id, **values), drop_id=tx_id)
    row.date, row.type, row.note = body.date, body.type, body.note
    for k, v in values.items():
        setattr(row, k, v)
    _after_change(session, [values["ticker"]] if values["ticker"] else [])
    return tx_json(row)


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int, session: DbSession) -> dict:
    row = session.get(Transaction, tx_id)
    if row is None:
        raise HTTPException(404, "No such trade")
    _check_log(session, None, drop_id=tx_id)
    session.delete(row)
    _after_change(session, [])
    return {"deleted": tx_id}


@router.get("/quote/{ticker}")
def quote(ticker: str, session: DbSession) -> dict:
    """A quote for any ticker, company or fund. Used to prefill the add-trade form."""
    symbol = ticker.strip().upper().replace("-", ".")
    q = session.get(Quote, symbol)
    if pricing.quote_is_stale(q):
        q = pricing.refresh_quote(session, symbol) or q
    cik = session.scalar(select(Ticker.cik).where(Ticker.ticker == symbol))
    company = session.get(Company, cik) if cik else None
    if q is None and company is None:
        raise HTTPException(404, f"Unknown ticker {symbol}")
    return {"ticker": symbol, "name": company.name if company else None, "quote": quote_json(q)}


# ---------------------------------------------------------------- portfolio page


def _cik(session: Session, ticker: str) -> int | None:
    return session.scalar(select(Ticker.cik).where(Ticker.ticker == ticker))


def _last_close(session: Session, ticker: str) -> float | None:
    return session.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


def _returns_since(session: Session, since: date) -> tuple[float | None, float | None, date | None]:
    """Portfolio and benchmark return from the last day on or before `since` to now."""
    rows = session.scalars(select(PortfolioDaily).order_by(PortfolioDaily.date)).all()
    if len(rows) < 2:
        return None, None, None
    base = next((r for r in reversed(rows) if r.date <= since), rows[0])
    last = rows[-1]
    port = last.return_index / base.return_index - 1
    closes = holdings.Closes(session, [holdings.BENCHMARK], base.date - timedelta(days=10))
    b0, b1 = closes(holdings.BENCHMARK, base.date), closes(holdings.BENCHMARK, last.date)
    bench = b1 / b0 - 1 if b0 and b1 else None
    return port, bench, base.date


CATEGORY_ORDER = ("Fast grower", "Stalwart", "Slow grower", "Cyclical", "Turnaround", "Asset play")


def _by_category(rows: list[dict], cash: float, total: float) -> list[dict]:
    """Stocks by Lynch category, then funds and cash, as shares of the whole portfolio."""
    sums: dict[str, float] = {}
    for r in rows:
        name = "Index funds and ETFs" if r["is_fund"] else r["category"]
        sums[name or "Not categorized"] = sums.get(name or "Not categorized", 0.0) + r["value"]
    order = [*CATEGORY_ORDER, "Not categorized", "Index funds and ETFs"]
    out = [
        {"name": n, "value": sums[n], "weight": sums[n] / total if total else 0}
        for n in order
        if n in sums
    ]
    out.append({"name": "Cash", "value": cash, "weight": cash / total if total else 0})
    return out


def lookthrough(rows: list[dict]) -> dict | None:
    """The stocks treated as one company, weighted by value. Funds and cash are left out.

    P/E is total stock value over the holdings' share of earnings (shares x EPS), not an
    average of P/Es. EPS growth and Lynch score are averages weighted by value. PEG is that
    P/E over that growth.
    """
    stocks = [r for r in rows if not r["is_fund"]]
    if not stocks:
        return None
    value = sum(r["value"] for r in stocks)
    with_eps = [r for r in stocks if r["eps_ttm"] is not None]
    earnings = sum(r["shares"] * r["eps_ttm"] for r in with_eps)
    covered = sum(r["value"] for r in with_eps)
    pe = covered / earnings if earnings > 0 else None

    def weighted(key: str) -> float | None:
        have = [r for r in stocks if r[key] is not None]
        weight = sum(r["value"] for r in have)
        return sum(r[key] * r["value"] for r in have) / weight if weight else None

    growth = weighted("eps_growth")
    return {
        "pe": pe,
        "eps_growth": growth,
        "peg": pe / (growth * 100) if pe and growth and growth > 0 else None,
        "lynch_score": weighted("lynch_score"),
        "largest_weight": max((r["weight"] or 0) for r in stocks),
        "largest": max(stocks, key=lambda r: r["value"])["ticker"],
        "below_cost": sum(1 for r in stocks if r["gain"] < 0),
        "stocks": len(stocks),
        "earnings_coverage": covered / value if value else None,
    }


@router.get("/portfolio")
def portfolio(session: DbSession) -> dict:
    if holdings.daily_is_stale(session):
        holdings.rebuild_daily(session)
    trades = holdings.load_trades(session)
    book = replay(trades)
    held = book.held()

    rows = []
    for ticker, pos in held.items():
        q = session.get(Quote, ticker)
        if pricing.quote_is_stale(q):
            pricing.refresh_quote_soon(ticker)
        price = q.price if q else (_last_close(session, ticker) or pos.avg_cost or 0.0)
        cik = _cik(session, ticker)
        company = session.get(Company, cik) if cik else None
        ratios = session.get(Ratio, cik) if cik else None
        value = pos.shares * price
        rows.append(
            {
                "ticker": ticker,
                "name": company.name if company else ticker,
                "is_company": company is not None,  # has a stock page
                # No reported fundamentals: index funds and ETFs (some file with the SEC too).
                "is_fund": ratios is None,
                "sector": company.sector if company else None,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "cost": pos.cost,
                "price": price,
                "day_change": (q.change or 0.0) * pos.shares
                if q and q.change is not None
                else None,
                "day_change_pct": q.change_pct if q else None,
                "value": value,
                "gain": value - pos.cost,
                "gain_pct": (value / pos.cost - 1) if pos.cost > 0 else None,
                "category": ratios.lynch_category if ratios else "Fund",
                "lynch_score": ratios.lynch_score if ratios else None,
                "eps_ttm": ratios.eps_ttm if ratios else None,
                "eps_growth": (
                    ratios.eps_growth_5y
                    if ratios and ratios.eps_growth_5y is not None
                    else ratios.eps_growth_3y
                    if ratios
                    else None
                ),
                "pe": ratios.pe if ratios else None,
                "peg": ratios.peg if ratios else None,
                "quote": quote_json(q),
            }
        )

    invested = sum(r["value"] for r in rows)
    total = invested + book.cash
    for r in rows:
        r["weight"] = r["value"] / total if total else None
    rows.sort(key=lambda r: r["value"], reverse=True)

    day_change = sum(r["day_change"] or 0.0 for r in rows)
    cost = book.cost_basis
    one_year, bench_1y, since = _returns_since(
        session, market.now_ny().date() - timedelta(days=365)
    )

    # Allocation: stocks by sector now; Lynch categories arrive in phase 5.
    sectors: dict[str, float] = {}
    funds = 0.0
    for r in rows:
        if not r["is_fund"]:
            sectors[r["sector"] or "Other"] = sectors.get(r["sector"] or "Other", 0.0) + r["value"]
        else:
            funds += r["value"]
    by_sector = sorted(
        ({"name": k, "value": v, "weight": v / total if total else 0} for k, v in sectors.items()),
        key=lambda x: x["value"],
        reverse=True,
    )
    stocks = invested - funds

    ticker_of = {_cik(session, t): t for t in held}
    ticker_of.pop(None, None)
    # Reports first (10-K, 10-Q, 8-K), then at most two insider filings, newest first.
    filings: list[Filing] = []
    for forms, limit in ((REPORT_FORMS, 4), (("4", "4/A"), 2)):
        filings += session.scalars(
            select(Filing)
            .where(Filing.cik.in_(list(ticker_of)), Filing.form.in_(forms))
            .order_by(Filing.filed_at.desc(), Filing.accession.desc())
            .limit(limit)
        ).all()
    filings.sort(key=lambda f: f.filed_at, reverse=True)

    activity = session.scalars(
        select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc()).limit(6)
    ).all()

    return {
        "summary": {
            "value": total,
            "invested": invested,
            "cash": book.cash,
            "cost_basis": cost,
            "gain": invested - cost,
            "gain_pct": (invested / cost - 1) if cost > 0 else None,
            "realized": book.realized,
            "dividends": book.dividends,
            "net_deposits": book.net_deposits,
            "day_change": day_change,
            "day_change_pct": day_change / (total - day_change) if total - day_change else None,
            "return_1y": one_year,
            "benchmark_1y": bench_1y,
            "return_since": since.isoformat() if since else None,
            "positions": len(rows),
            "trades": len(trades),
        },
        "holdings": rows,
        "allocation": {
            "by_category": _by_category(rows, book.cash, total),
            "kinds": [
                {"name": "Stocks", "value": stocks, "weight": stocks / total if total else 0},
                {
                    "name": "Index funds and ETFs",
                    "value": funds,
                    "weight": funds / total if total else 0,
                },
                {"name": "Cash", "value": book.cash, "weight": book.cash / total if total else 0},
            ],
            "by_sector": by_sector,
        },
        "lookthrough": lookthrough(rows),
        "activity": [tx_json(t) for t in activity],
        "filings": [
            {
                "ticker": ticker_of.get(f.cik),
                "form": f.form,
                "title": f.title,
                "filed_at": f.filed_at.isoformat(),
                "url": f.url,
            }
            for f in filings
        ],
        "market_open": market.is_open(),
    }


@router.get("/portfolio/performance")
def performance(
    session: DbSession,
    range_: Annotated[str, Query(alias="range", pattern="^(1M|6M|YTD|1Y|ALL)$")] = "1Y",
) -> dict:
    if holdings.daily_is_stale(session):
        holdings.rebuild_daily(session)
    rows = session.scalars(select(PortfolioDaily).order_by(PortfolioDaily.date)).all()
    if not rows:
        return {"range": range_, "points": [], "portfolio_return": None, "benchmark_return": None}
    last = rows[-1].date
    if range_ == "ALL":
        start = rows[0].date
    elif range_ == "YTD":
        start = date(last.year, 1, 1)
    else:
        start = last - timedelta(days=RANGE_DAYS[range_])
    # Rebase at the last day on or before the range start, so the first point is 0%.
    base = next((r for r in reversed(rows) if r.date <= start), rows[0])
    shown = [r for r in rows if r.date >= base.date]
    closes = holdings.Closes(session, [holdings.BENCHMARK], base.date - timedelta(days=10))
    b0 = closes(holdings.BENCHMARK, base.date)
    points = []
    for r in shown:
        b = closes(holdings.BENCHMARK, r.date)
        points.append(
            {
                "time": r.date.isoformat(),
                "portfolio": r.return_index / base.return_index - 1,
                "benchmark": (b / b0 - 1) if b and b0 else None,
                "value": r.value,
            }
        )
    return {
        "range": range_,
        "points": points,
        "portfolio_return": points[-1]["portfolio"],
        "benchmark_return": points[-1]["benchmark"],
        "benchmark": holdings.BENCHMARK,
    }
