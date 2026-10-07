"""API tests on made-up data: stock page, prices, search, watchlist."""

from datetime import date

import pytest

from app import market
from app.db.models import Company, Ratio
from app.pipeline import pricing
from tests.conftest import add_bars, add_company, add_quote


def test_stock_page_reads_from_the_database(client, db):
    add_company(
        db,
        eps_ttm=2.0,
        eps_growth_5y=0.2,
        revenue_ttm=1e9,
        shares_outstanding=1e8,
        equity=5e8,
        debt=1e8,
        cash=5e7,
        net_margin=0.1,
    )
    add_quote(db, "ACME", 40.0)
    res = client.get("/api/stock/acme")
    assert res.status_code == 200
    body = res.json()
    assert body["ticker"] == "ACME" and body["name"] == "Acme Widgets"
    assert body["quote"]["price"] == 40.0
    assert body["ratios"]["net_margin"] == 0.1
    assert body["lynch"] is None  # phase 5
    assert db.get(Company, 1).view_count == 1


def test_unknown_ticker_is_404(client):
    assert client.get("/api/stock/NOPE").status_code == 404


def test_missing_quote_never_blocks_the_page(client, db):
    add_company(db)
    body = client.get("/api/stock/ACME").json()
    assert body["quote"] is None
    assert body["quote_refreshing"] is False  # no Finnhub key in tests, so nothing to wait for


def test_price_ratios_follow_the_quote(db):
    add_company(
        db,
        eps_ttm=2.0,
        eps_growth_5y=0.2,
        revenue_ttm=1e9,
        shares_outstanding=1e8,
        equity=5e8,
        debt=1e8,
        cash=5e7,
    )
    pricing.apply_price(db, 1, 40.0)
    r = db.get(Ratio, 1)
    assert r.market_cap == 4e9
    assert r.pe == pytest.approx(20.0)
    assert r.peg == pytest.approx(1.0)
    assert r.enterprise_value == pytest.approx(4.05e9)


def test_prices_daily_for_short_ranges_weekly_for_long(client, db, monkeypatch):
    add_company(db)
    monkeypatch.setattr(pricing, "bars_needed", lambda s, t: None)
    add_bars(db, "ACME", date(2025, 9, 1), [100 + i for i in range(280)])

    short = client.get("/api/stock/ACME/prices?range=1M").json()
    assert short["interval"] == "1d"
    assert 18 <= len(short["bars"]) <= 24

    year = client.get("/api/stock/ACME/prices?range=1Y").json()
    assert year["interval"] == "1w"
    week = year["bars"][1]
    assert week["close"] - week["open"] == pytest.approx(5)  # Monday open to Friday close
    assert year["change_pct"] > 0
    assert year["range_52w"]["high"] == 100 + 279 + 2


def test_prices_with_no_history_is_empty_not_an_error(client, db, monkeypatch):
    add_company(db)
    monkeypatch.setattr(pricing, "bars_needed", lambda s, t: None)
    body = client.get("/api/stock/ACME/prices?range=1Y").json()
    assert body["bars"] == [] and body["change_pct"] is None


def test_search_ranks_exact_ticker_then_prefix_then_name(client, db):
    add_company(db, ticker="MA", cik=1, name="Mastercard")
    add_company(db, ticker="MAA", cik=2, name="Mid-America Apartment")
    add_company(db, ticker="XYZ", cik=3, name="Main Street Bank", tier="cold")
    body = client.get("/api/search?q=ma").json()
    assert [h["ticker"] for h in body["warm"]] == ["MA", "MAA"]
    assert [h["ticker"] for h in body["other"]] == ["XYZ"]
    assert body["other"][0]["cached_at"] is None


def test_watchlist_add_and_remove(client, db):
    add_company(db, tier="cold")
    body = client.post("/api/watchlist", json={"ticker": "acme"}).json()
    assert [w["ticker"] for w in body["watch"]] == ["ACME"]
    db.expire_all()
    assert db.get(Company, 1).tier == "warm"  # watched names keep a fresh quote
    assert client.get("/api/stock/ACME").json()["watching"] is True
    assert client.delete("/api/watchlist/ACME").json()["watch"] == []
    assert client.delete("/api/watchlist/ACME").status_code == 404


def test_market_hours():
    ny = market.NY
    from datetime import datetime

    assert market.is_open(datetime(2026, 10, 7, 10, 0, tzinfo=ny))  # Wednesday morning
    assert not market.is_open(datetime(2026, 10, 7, 9, 29, tzinfo=ny))
    assert not market.is_open(datetime(2026, 10, 7, 16, 0, tzinfo=ny))
    assert not market.is_open(datetime(2026, 10, 10, 12, 0, tzinfo=ny))  # Saturday
    assert not market.is_open(datetime(2026, 11, 26, 12, 0, tzinfo=ny))  # Thanksgiving
    assert not market.is_open(datetime(2026, 11, 27, 13, 30, tzinfo=ny))  # early close
    # Bars for a session are complete 20 minutes after the close.
    assert market.latest_complete_session(datetime(2026, 10, 7, 12, 0, tzinfo=ny)) == date(
        2026, 10, 6
    )
    assert market.latest_complete_session(datetime(2026, 10, 7, 16, 30, tzinfo=ny)) == date(
        2026, 10, 7
    )
    assert market.latest_complete_session(datetime(2026, 10, 12, 8, 0, tzinfo=ny)) == date(
        2026, 10, 9
    )
