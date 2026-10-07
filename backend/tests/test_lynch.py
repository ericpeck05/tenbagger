"""The Lynch check on made-up inputs: categories, each test's bands, and score rescaling."""

import pytest

from app.pipeline.lynch import category, checks, evaluate, history_flags, score

GOOD = {
    "peg": 0.91, "eps_growth_5y": 0.22, "pe": 20.0, "revenue_growth_1y": 0.18,
    "revenue_growth_5y": 0.21, "debt_to_equity": 0.21, "inventory_growth_1y": 0.11,
    "insider_buys_6m": 3, "insider_sells_6m": 0, "market_cap": 6.03e9, "cash": 2e8,
    "debt": 1e8, "ebitda_ttm": 5e8, "net_cash_per_share": 0.88, "eps_ttm": 2.4,
    "net_income_ttm": 3e8, "price": 48.2, "price_to_book": 4.0,
}  # fmt: skip


def by_key(results):
    return {t.key: t for t in results}


def test_the_mockup_stock_passes_eight_and_watches_one():
    t = by_key(checks(GOOD))
    assert [t[k].status for k in t] == ["pass"] * 3 + ["watch"] + ["pass"] * 5
    assert t["revenue_holding"].value == "21% to 18%"  # 18/21 = 0.86: watch
    assert t["insiders"].value == "3 buys, 0 sells"
    assert t["market_cap"].value == "6.03B"
    # 95 points of 100: the watch earns half of its 10.
    assert score(list(t.values())) == 95.0


@pytest.mark.parametrize(
    "key, field, value, status",
    [
        ("peg", "peg", 1.2, "watch"), ("peg", "peg", 1.6, "fail"),
        ("pe", "pe", 4.0, "fail"), ("pe", "pe", 30.0, "watch"), ("pe", "pe", 40.0, "fail"),
        ("eps_growth", "eps_growth_5y", 0.12, "watch"),
        ("eps_growth", "eps_growth_5y", 0.05, "fail"),
        ("debt_to_equity", "debt_to_equity", 0.7, "watch"),
        ("debt_to_equity", "debt_to_equity", 1.5, "fail"),
        ("inventory", "inventory_growth_1y", 0.21, "watch"),  # 3 points faster than sales
        ("inventory", "inventory_growth_1y", 0.30, "fail"),
        ("market_cap", "market_cap", 20e9, "watch"), ("market_cap", "market_cap", 1e8, "fail"),
    ],
)  # fmt: skip
def test_bands(key, field, value, status):
    assert by_key(checks({**GOOD, field: value}))[key].status == status


def test_insider_activity():
    assert (
        by_key(checks({**GOOD, "insider_buys_6m": 0, "insider_sells_6m": 0}))["insiders"].status
        == "watch"
    )
    assert (
        by_key(checks({**GOOD, "insider_buys_6m": 1, "insider_sells_6m": 4}))["insiders"].status
        == "fail"
    )


def test_net_cash_watch_when_net_debt_is_under_one_ebitda():
    r = {**GOOD, "cash": 1e8, "debt": 3e8, "ebitda_ttm": 5e8}
    assert by_key(checks(r))["net_cash"].status == "watch"
    r["ebitda_ttm"] = 1e8
    assert by_key(checks(r))["net_cash"].status == "fail"


def test_missing_tests_are_left_out_and_weights_rescaled():
    r = {**GOOD, "insider_buys_6m": None, "peg": None}
    results = checks(r)
    assert by_key(results)["insiders"].status == "missing"
    # Available: 100 - 10 - 20 = 70. Earned: 70 - 5 (revenue watch) = 65. 65/70 = 92.9.
    assert score(results) == pytest.approx(92.9)


def test_banks_skip_the_inventory_test():
    assert by_key(checks(GOOD, sic=6022))["inventory"].status == "missing"


def test_all_missing_gives_no_score():
    assert score(checks({})) is None


def test_categories_first_match_wins():
    assert category(GOOD, "Retail") == "Fast grower"
    assert category({**GOOD, "eps_growth_5y": 0.15}, "Retail") == "Stalwart"
    assert category({**GOOD, "eps_growth_5y": 0.04}, "Retail") == "Slow grower"
    assert category({**GOOD, "eps_growth_5y": None}, "Semiconductors") == "Cyclical"
    assert category({**GOOD, "eps_drops_10y": 2}, "Retail") == "Cyclical"
    assert category({**GOOD, "price_to_book": 0.8}, "Semiconductors") == "Asset play"
    assert category({**GOOD, "net_cash_per_share": 20.0}, "Retail") == "Asset play"
    assert (
        category({**GOOD, "loss_recent": 1, "loss_shrinking": 0}, "Semiconductors") == "Turnaround"
    )
    assert (
        category({**GOOD, "eps_ttm": -1.0, "eps_growth_5y": None, "price_to_book": 2}, "Retail")
        is None
    )


def test_history_flags():
    ni = {2022: 5.0, 2023: -3.0, 2024: -1.0}
    eps = {2015: 1.0, 2016: 0.6, 2017: 0.65, 2018: 0.3, 2019: 0.4}
    f = history_flags(ni, eps, ni_ttm=-0.5)
    assert f == {"loss_recent": 1.0, "loss_shrinking": 1.0, "eps_drops_10y": 2.0}
    assert history_flags({2023: 1.0, 2024: 2.0}, {}, 2.5)["loss_recent"] == 0.0


def test_evaluate_shape():
    out = evaluate(GOOD, "Retail", None)
    assert out["category"] == "Fast grower" and out["score"] == 95.0
    assert len(out["tests"]) == 9 and {
        "label",
        "value",
        "status",
        "weight",
        "points",
        "rule",
    } <= set(out["tests"][0])
