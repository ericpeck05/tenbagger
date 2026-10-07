"""The watchlist (warm names with quotes) and recently viewed cold names."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.stock import find_company, quote_json
from app.db.models import Company, PriceFetch, Quote, Ticker, WatchItem
from app.db.session import DbSession
from app.pipeline import pricing

router = APIRouter()

RECENT_LIMIT = 5


class WatchRequest(BaseModel):
    ticker: str


def watchlist_json(session: Session) -> dict:
    items = session.scalars(select(WatchItem).order_by(WatchItem.position, WatchItem.added_at))
    watch = []
    for item in items:
        cik = session.scalar(select(Ticker.cik).where(Ticker.ticker == item.ticker))
        company = session.get(Company, cik) if cik else None
        watch.append(
            {
                "ticker": item.ticker,
                "name": company.name if company else item.ticker,
                "quote": quote_json(session.get(Quote, item.ticker)),
            }
        )
    watched = {w["ticker"] for w in watch}
    recent_rows = session.scalars(
        select(Company)
        .where(Company.tier == "cold", Company.last_viewed_at.is_not(None))
        .order_by(Company.last_viewed_at.desc())
        .limit(RECENT_LIMIT + len(watched))
    ).all()
    recent = []
    for c in recent_rows:
        if c.ticker in watched or len(recent) >= RECENT_LIMIT:
            continue
        fetch = session.get(PriceFetch, c.ticker)
        recent.append(
            {
                "ticker": c.ticker,
                "name": c.name,
                "cached_at": fetch.fetched_at.isoformat() + "Z" if fetch else None,
            }
        )
    return {"watch": watch, "recent": recent}


@router.get("/watchlist")
def get_watchlist(session: DbSession) -> dict:
    return watchlist_json(session)


@router.post("/watchlist", status_code=201)
def add(req: WatchRequest, session: DbSession) -> dict:
    symbol, company = find_company(session, req.ticker)
    if session.get(WatchItem, symbol) is None:
        last = session.scalar(select(func.max(WatchItem.position))) or 0
        session.add(WatchItem(ticker=symbol, added_at=pricing.utcnow(), position=last + 1))
        company.tier = "warm"  # watched names keep a fresh quote
        session.commit()
    return watchlist_json(session)


@router.delete("/watchlist/{ticker}")
def remove(ticker: str, session: DbSession) -> dict:
    item = session.get(WatchItem, ticker.upper())
    if item is None:
        raise HTTPException(404, f"{ticker.upper()} is not on the watchlist")
    session.delete(item)
    session.commit()
    return watchlist_json(session)
