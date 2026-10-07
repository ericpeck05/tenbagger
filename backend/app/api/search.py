"""Search the local companies table: ticker prefix first, then company name."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from app.db.models import Company, PriceFetch, Quote, Ticker
from app.db.session import DbSession

router = APIRouter()

LIMIT = 8


@router.get("/search")
def search(session: DbSession, q: Annotated[str, Query(max_length=60)] = "") -> dict:
    text = q.strip()
    if not text:
        return {"query": q, "warm": [], "other": []}
    symbol = text.upper().replace("-", ".")
    name = text.lower()

    rank = case(
        (Ticker.ticker == symbol, 0),
        (Ticker.ticker.startswith(symbol), 1),
        (func.lower(Company.name).startswith(name), 2),
        else_=3,
    )
    rows = session.execute(
        select(Ticker.ticker, Company, rank.label("rank"))
        .join(Company, Company.cik == Ticker.cik)
        .where(
            or_(
                Ticker.ticker.startswith(symbol),
                func.lower(Company.name).contains(name),
            )
        )
        .order_by(rank, func.length(Ticker.ticker), Ticker.ticker)
        .limit(LIMIT * 3)
    ).all()

    seen: set[str] = set()
    warm, other = [], []
    for ticker, company, _rank in rows:
        if ticker in seen or len(seen) >= LIMIT:
            continue
        seen.add(ticker)
        item = {"ticker": ticker, "name": company.name, "sector": company.sector}
        if company.tier == "warm":
            quote = session.get(Quote, ticker)
            item["price"] = quote.price if quote else None
            item["change_pct"] = quote.change_pct if quote else None
            warm.append(item)
        else:
            fetch = session.get(PriceFetch, ticker)
            item["cached_at"] = fetch.fetched_at.isoformat() + "Z" if fetch else None
            other.append(item)
    return {"query": q, "warm": warm, "other": other}
