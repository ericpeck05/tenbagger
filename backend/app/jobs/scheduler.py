"""Background jobs that run inside the API process.

- Quote loop: every minute, refresh the stalest warm quotes, leaving a little of the rate
  limit free for stocks opened on request. During market hours that cycles the whole warm
  tier (about 500 names at 45 a minute, roughly 11 minutes a pass). Outside market hours it
  only refreshes quotes from before the latest close, so one pass after the close, then idle.
- Daily bars: shortly after startup, then at 4:30 p.m. New York time on weekdays, top up
  every warm ticker's bars. The first run backfills history since 2016.

Set RUN_JOBS=false in the environment to turn them off (the tests do).
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app import market
from app.config import get_settings
from app.db.models import Quote
from app.db.session import session_scope
from app.pipeline import pricing

log = logging.getLogger(__name__)

QUOTE_HEADROOM = 5  # calls per minute kept free for on-request quotes
BARS_BATCH = 100  # tickers per Alpaca request


def quotes_pass() -> int:
    client = pricing.finnhub()
    if client is None:
        return 0
    budget = max(get_settings().finnhub_per_minute - QUOTE_HEADROOM, 1)
    with session_scope() as session:
        tickers = pricing.warm_tickers(session)
        quotes = {q.ticker: q for q in session.scalars(select(Quote)).all()}
        stale = [t for t in tickers if pricing.quote_is_stale(quotes.get(t))]
        if market.is_open():
            # Cycle continuously: stale names first, then the oldest of the rest.
            fresh = sorted(
                (t for t in tickers if t not in stale), key=lambda t: quotes[t].fetched_at
            )
            due = stale + fresh
        else:
            due = stale
        done = 0
        for ticker in due[:budget]:
            if pricing.refresh_quote(session, ticker, background=True) is not None:
                done += 1
    if done:
        log.info("quote loop: refreshed %d quotes", done)
    return done


def bars_job() -> int:
    if pricing.alpaca() is None:
        return 0
    total = 0
    with session_scope() as session:
        tickers = [t for t in pricing.warm_tickers(session) if pricing.bars_needed(session, t)]
        for i in range(0, len(tickers), BARS_BATCH):
            total += pricing.update_bars(session, tickers[i : i + BARS_BATCH])
    if tickers:
        log.info("daily bars: %d tickers topped up, %d bars stored", len(tickers), total)
    return total


def start() -> BackgroundScheduler | None:
    if not get_settings().run_jobs:
        return None
    now = datetime.now(market.NY)
    scheduler = BackgroundScheduler(timezone=market.NY)
    common = {"max_instances": 1, "coalesce": True}
    # First runs come shortly after startup, so a fresh install fills in without waiting.
    scheduler.add_job(
        quotes_pass,
        "interval",
        seconds=60,
        id="quotes",
        next_run_time=now + timedelta(seconds=5),
        **common,
    )
    scheduler.add_job(bars_job, "date", run_date=now + timedelta(seconds=10), id="bars-startup")
    scheduler.add_job(
        bars_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=market.NY),
        id="bars",
        **common,
    )
    scheduler.start()
    return scheduler
