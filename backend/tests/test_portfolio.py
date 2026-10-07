"""Portfolio math, checked against numbers worked out by hand. All holdings are made up."""

from datetime import date

import pytest

from app.pipeline.portfolio import Book, Trade, TradeError, daily, replay

D = date


def buy(day, ticker, shares, price, id=0):
    return Trade(day, "buy", ticker, shares, price, shares * price, id)


def sell(day, ticker, shares, price, id=0):
    return Trade(day, "sell", ticker, shares, price, shares * price, id)


def cash(day, kind, amount, id=0):
    return Trade(day, kind, amount=amount, id=id)


def test_average_cost_and_realized_gain():
    # Deposit 10,000. Buy 100 @ 20 (2,000) and 50 @ 26 (1,300): 150 shares, cost 3,300,
    # average 22. Sell 60 @ 30: realized 60 x (30 - 22) = 480; 90 shares remain at cost
    # 90 x 22 = 1,980. Cash: 10,000 - 2,000 - 1,300 + 1,800 = 8,500.
    book = replay(
        [
            cash(D(2026, 1, 2), "deposit", 10_000),
            buy(D(2026, 1, 5), "ACME", 100, 20),
            buy(D(2026, 2, 3), "ACME", 50, 26),
            sell(D(2026, 3, 2), "ACME", 60, 30),
        ]
    )
    pos = book.positions["ACME"]
    assert pos.shares == 90
    assert pos.avg_cost == pytest.approx(22.0)
    assert pos.cost == pytest.approx(1_980.0)
    assert book.realized == pytest.approx(480.0)
    assert book.cash == pytest.approx(8_500.0)
    assert book.net_deposits == 10_000


def test_selling_everything_clears_the_position():
    book = replay([buy(D(2026, 1, 5), "ACME", 10, 50), sell(D(2026, 1, 6), "ACME", 10, 55)])
    assert book.held() == {}
    assert book.realized == pytest.approx(50.0)


def test_buy_without_cash_is_an_implicit_deposit():
    book = replay([cash(D(2026, 1, 2), "deposit", 500), buy(D(2026, 1, 5), "ACME", 10, 80)])
    assert book.cash == 0
    assert book.net_deposits == 800  # 500 deposited + 300 brought in for the buy


def test_cannot_sell_more_than_held_or_withdraw_more_than_cash():
    with pytest.raises(TradeError, match="only 5 held"):
        replay([buy(D(2026, 1, 5), "ACME", 5, 10), sell(D(2026, 1, 6), "ACME", 6, 10)])
    with pytest.raises(TradeError, match="only 100.00 in cash"):
        replay([cash(D(2026, 1, 2), "deposit", 100), cash(D(2026, 1, 3), "withdrawal", 101)])


def test_same_day_deposit_funds_a_buy():
    # The buy has a lower id than the deposit but still comes after it.
    book = replay(
        [buy(D(2026, 1, 5), "ACME", 10, 10, id=1), cash(D(2026, 1, 5), "deposit", 100, id=2)]
    )
    assert book.net_deposits == 100 and book.cash == 0


def test_dividend_is_return_not_a_deposit():
    book = replay([cash(D(2026, 1, 2), "deposit", 100), cash(D(2026, 3, 1), "dividend", 5)])
    assert book.cash == 105 and book.net_deposits == 100 and book.dividends == 5


def test_time_weighted_return_ignores_deposits():
    # Day 1: deposit 1,000, buy 10 @ 100; close 100 -> V 1,000.
    # Day 2: close 110 -> V 1,100, r = +10%.
    # Day 3: deposit 1,100 (cash); close 110 -> V 2,200, F 1,100, r = (2,200 - 1,100)/1,100 - 1 = 0.
    # Day 4: close 99 -> V = 990 + 1,100 = 2,090, r = 2,090/2,200 - 1 = -5%.
    # Index: 1.0, 1.1, 1.1, 1.045. A money-weighted view would wrongly call the deposit a gain.
    closes = {D(2026, 1, 5): 100, D(2026, 1, 6): 110, D(2026, 1, 7): 110, D(2026, 1, 8): 99}
    trades = [
        cash(D(2026, 1, 5), "deposit", 1_000),
        buy(D(2026, 1, 5), "ACME", 10, 100),
        cash(D(2026, 1, 7), "deposit", 1_100),
    ]
    days = daily(trades, sorted(closes), lambda t, d: closes[d])
    assert [round(x.value, 2) for x in days] == [1_000, 1_100, 2_200, 2_090]
    assert [round(x.return_index, 4) for x in days] == [1.0, 1.1, 1.1, 1.045]
    assert days[-1].net_deposits == 2_100


def test_withdrawal_is_not_a_loss():
    closes = {D(2026, 1, 5): 100, D(2026, 1, 6): 100}
    trades = [
        cash(D(2026, 1, 5), "deposit", 2_000),
        buy(D(2026, 1, 5), "ACME", 10, 100),
        cash(D(2026, 1, 6), "withdrawal", 500),
    ]
    days = daily(trades, sorted(closes), lambda t, d: closes[d])
    assert days[1].value == 1_500
    assert days[1].return_index == pytest.approx(1.0)


def test_holding_without_a_close_is_valued_at_its_trade_price():
    days = daily([buy(D(2026, 1, 5), "NEWCO", 4, 25)], [D(2026, 1, 5)], lambda t, d: None)
    assert days[0].value == 100


def test_empty_log():
    assert daily([], [D(2026, 1, 5)], lambda t, d: 1.0) == []
    assert replay([]).cash == 0 and isinstance(replay([]), Book)
