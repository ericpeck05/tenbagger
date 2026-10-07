"""Test setup: a throwaway database per test and no background jobs or provider calls.

Tests use made-up companies and prices only. Nothing fetched from Finnhub or Alpaca is ever
saved in the repo.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import session as db_session
from app.db.models import Base, Company, PriceDaily, Quote, Ratio, Ticker
from app.pipeline import pricing


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_JOBS", "false")
    for key in ("FINNHUB_API_KEY", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY"):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(pricing, "_providers", {"finnhub": None, "alpaca": None})
    Base.metadata.create_all(db_session.get_engine())
    with db_session.session_scope() as session:
        yield session
    get_settings.cache_clear()


@pytest.fixture
def client(db):
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def add_company(session, ticker="ACME", cik=1, name="Acme Widgets", tier="warm", **ratios):
    session.add(
        Company(
            cik=cik,
            ticker=ticker,
            name=name,
            tier=tier,
            sector="Industrial machinery",
            exchange="NYSE",
            view_count=0,
        )
    )
    session.add(Ticker(ticker=ticker, cik=cik, is_primary=True))
    session.add(Ratio(cik=cik, computed_at=datetime(2026, 1, 1), **ratios))
    session.commit()


def add_bars(session, ticker, start: date, closes: list[float]):
    """Weekday bars with the given closes, starting at `start`."""
    d, i = start, 0
    while i < len(closes):
        if d.weekday() < 5:
            c = closes[i]
            session.add(
                PriceDaily(ticker=ticker, date=d, open=c - 1, high=c + 2, low=c - 2, close=c)
            )
            i += 1
        d += timedelta(days=1)
    session.commit()


def add_quote(session, ticker, price, fetched_at=None):
    session.add(
        Quote(
            ticker=ticker,
            price=price,
            change=1.0,
            change_pct=1.0,
            prev_close=price - 1,
            open=price - 0.5,
            high=price + 1,
            low=price - 1,
            quote_time=datetime(2026, 10, 6, 20, 0),
            fetched_at=fetched_at or pricing.utcnow(),
        )
    )
    session.commit()
