"""Trade log and portfolio endpoints, on made-up holdings and prices."""

from datetime import date

import pytest

from app.pipeline import pricing
from tests.conftest import add_bars, add_company, add_quote


@pytest.fixture
def acme(db, monkeypatch):
    add_company(
        db, eps_ttm=2.0, eps_growth_5y=0.2, shares_outstanding=1e8, equity=5e8, debt=1e8, cash=5e7
    )
    monkeypatch.setattr(pricing, "bars_needed", lambda s, t: None)
    return db


def post(client, **trade):
    return client.post("/api/transactions", json=trade)


def test_trades_build_positions_and_summary(client, acme):
    assert post(client, date="2026-01-02", type="deposit", amount=10_000).status_code == 201
    assert (
        post(client, date="2026-01-05", type="buy", ticker="acme", shares=100, price=20).status_code
        == 201
    )
    assert (
        post(client, date="2026-02-03", type="buy", ticker="ACME", shares=50, price=26).status_code
        == 201
    )
    assert (
        post(client, date="2026-03-02", type="sell", ticker="ACME", shares=60, price=30).status_code
        == 201
    )
    add_quote(acme, "ACME", 25.0)

    body = client.get("/api/portfolio").json()
    s, [h] = body["summary"], body["holdings"]
    # 90 shares at average cost 22 (cost 1,980), worth 90 x 25 = 2,250, gain 270.
    assert h["ticker"] == "ACME" and h["shares"] == 90
    assert h["avg_cost"] == pytest.approx(22.0)
    assert h["value"] == pytest.approx(2_250.0)
    assert h["gain"] == pytest.approx(270.0)
    assert h["gain_pct"] == pytest.approx(270 / 1_980)
    # Cash 8,500; total 10,750; realized 60 x (30 - 22) = 480.
    assert s["cash"] == pytest.approx(8_500.0)
    assert s["value"] == pytest.approx(10_750.0)
    assert s["realized"] == pytest.approx(480.0)
    assert s["cost_basis"] == pytest.approx(1_980.0)
    assert h["weight"] == pytest.approx(2_250 / 10_750)
    assert [a["type"] for a in body["activity"]] == ["sell", "buy", "buy", "deposit"]


def test_rejects_impossible_trades(client, acme):
    post(client, date="2026-01-05", type="buy", ticker="ACME", shares=10, price=20)
    res = post(client, date="2026-01-06", type="sell", ticker="ACME", shares=11, price=20)
    assert res.status_code == 400 and "only 10 held" in res.json()["detail"]
    assert (
        post(client, date="2026-01-06", type="buy", ticker="NOPE", shares=1, price=1).status_code
        == 400
    )
    assert post(client, date="2999-01-01", type="deposit", amount=5).status_code == 400
    assert (
        post(client, date="2026-01-06", type="buy", ticker="ACME", shares=0, price=1).status_code
        == 422
    )


def test_cannot_delete_a_buy_that_a_later_sell_depends_on(client, acme):
    buy_id = post(client, date="2026-01-05", type="buy", ticker="ACME", shares=10, price=20).json()[
        "id"
    ]
    post(client, date="2026-01-06", type="sell", ticker="ACME", shares=10, price=21)
    assert client.delete(f"/api/transactions/{buy_id}").status_code == 400


def test_edit_and_delete(client, acme):
    tx = post(client, date="2026-01-05", type="buy", ticker="ACME", shares=10, price=20).json()
    edited = client.put(
        f"/api/transactions/{tx['id']}",
        json={"date": "2026-01-05", "type": "buy", "ticker": "ACME", "shares": 12, "price": 20},
    ).json()
    assert edited["shares"] == 12 and edited["amount"] == 240
    assert client.delete(f"/api/transactions/{tx['id']}").json() == {"deleted": tx["id"]}
    assert client.get("/api/transactions").json() == []


def test_performance_draws_portfolio_and_benchmark(client, acme):
    add_bars(acme, "ACME", date(2026, 1, 5), [20, 22, 24, 23, 25])
    add_bars(acme, "SPY", date(2026, 1, 5), [500, 505, 510, 505, 520])
    post(client, date="2026-01-05", type="deposit", amount=1_000)
    post(client, date="2026-01-05", type="buy", ticker="ACME", shares=50, price=20)

    body = client.get("/api/portfolio/performance?range=ALL").json()
    pts = body["points"]
    assert [p["time"] for p in pts][:2] == ["2026-01-05", "2026-01-06"]
    assert pts[0]["portfolio"] == 0 and pts[0]["benchmark"] == 0
    # 50 shares from 20 to 25: +25%. SPY from 500 to 520: +4%.
    assert body["portfolio_return"] == pytest.approx(0.25)
    assert body["benchmark_return"] == pytest.approx(0.04)


def test_lookthrough_treats_stocks_as_one_company():
    from app.api.portfolio import lookthrough

    rows = [
        # 100 shares at 20 (value 2,000), EPS 2: earnings 200.
        {"ticker": "A", "is_company": True, "is_fund": False,
         "shares": 100, "value": 2_000, "eps_ttm": 2.0,
         "eps_growth": 0.20, "lynch_score": 80, "weight": 0.4, "gain": 100},
        # 50 shares at 60 (value 3,000), EPS 1: earnings 50.
        {"ticker": "B", "is_company": True, "is_fund": False,
         "shares": 50, "value": 3_000, "eps_ttm": 1.0,
         "eps_growth": 0.10, "lynch_score": 40, "weight": 0.6, "gain": -50},
        {"ticker": "FUND", "is_company": False, "is_fund": True,
         "shares": 10, "value": 9_999, "eps_ttm": None,
         "eps_growth": None, "lynch_score": None, "weight": 0.5, "gain": 0},
    ]  # fmt: skip
    lt = lookthrough(rows)
    # P/E = 5,000 / 250 = 20, not the average of 10 and 60.
    assert lt["pe"] == pytest.approx(20.0)
    # Growth and score weighted by value: (0.2 x 2,000 + 0.1 x 3,000) / 5,000 = 0.14; 56.
    assert lt["eps_growth"] == pytest.approx(0.14)
    assert lt["lynch_score"] == pytest.approx(56.0)
    assert lt["peg"] == pytest.approx(20 / 14)
    assert lt["largest"] == "B" and lt["below_cost"] == 1 and lt["stocks"] == 2
