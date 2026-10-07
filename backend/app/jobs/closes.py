"""Nightly: the latest close for every company, so the whole market has a market cap, P/E,
and Lynch score, and sector medians can be computed across it.

Cold companies keep no price history; only their price-based ratios are updated. A company
with a quote newer than the close is left alone, since its ratios already follow the quote.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Company, Quote, Ratio
from app.jobs.runs import recorded
from app.pipeline import pricing
from app.pipeline.sector_medians import recompute
from app.providers.base import ProviderError

log = logging.getLogger(__name__)
BATCH = 200


def _bars(client, tickers: list[str]) -> dict:
    """Recent bars for a batch, splitting it when Alpaca rejects a symbol in it."""
    start = (datetime.now(UTC) - timedelta(days=10)).date()
    try:
        return client.daily_bars(tickers, start=start)
    except ProviderError:
        if len(tickers) == 1:
            return {}
        mid = len(tickers) // 2
        return {**_bars(client, tickers[:mid]), **_bars(client, tickers[mid:])}


def run(session) -> dict:
    client = pricing.alpaca()
    if client is None:
        return {"skipped": "no Alpaca keys"}
    rows = session.execute(
        select(Company.cik, Company.ticker).join(Ratio, Ratio.cik == Company.cik)
    ).all()
    quotes = {q.ticker: q.fetched_at for q in session.scalars(select(Quote)).all()}
    priced = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        bars = _bars(client, [t for _, t in batch])
        for cik, ticker in batch:
            series = bars.get(ticker)
            if not series:
                continue
            last = series[-1]
            fetched = quotes.get(ticker)
            if fetched is not None and fetched.date() >= last.date:
                continue
            pricing.apply_price(session, cik, last.close)
            priced += 1
        session.commit()
    medians = recompute(session)
    return {"companies": len(rows), "priced_from_close": priced, "sector_medians": medians}


def closes_job() -> dict:
    from app.db.session import session_scope

    with session_scope() as session, recorded(session, "closes") as detail:
        detail.update(run(session))
        return detail
