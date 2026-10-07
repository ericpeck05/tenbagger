"""Unit tests for tag mapping, TTM, and ratio formulas, on small hand-built inputs."""

from datetime import date

import pytest

from app.pipeline import ttm as T
from app.pipeline.ratios import Fundamentals, cagr, filing_ratios, growth, price_ratios
from app.pipeline.sector import is_financial, sector_for_sic
from app.pipeline.tags import METRICS, Fact, extract, resolve


def entry(start, end, val, filed, form="10-K", accn=None):
    e = {"end": end, "val": val, "filed": filed, "form": form, "accn": accn or f"a-{filed}"}
    if start:
        e["start"] = start
    return e


def cf(tags: dict[str, list[dict]], unit="USD") -> dict:
    """A minimal companyfacts document. Keys are "Tag" (us-gaap) or "dei:Tag"."""
    facts: dict = {}
    for key, entries in tags.items():
        taxonomy, tag = key.split(":") if ":" in key else ("us-gaap", key)
        u = "USD/shares" if "PerShare" in tag else ("shares" if "Shares" in tag else unit)
        facts.setdefault(taxonomy, {})[tag] = {"units": {u: entries}}
    return {"facts": facts}


def fact(start, end, value, filed="2026-01-01", metric="m"):
    return Fact(
        metric,
        date.fromisoformat(start) if start else None,
        date.fromisoformat(end),
        value,
        "10-K",
        date.fromisoformat(filed),
        f"a-{filed}",
        "Tag",
    )


# ---------------------------------------------------------------- tag mapping


def test_first_tag_with_data_wins_per_period():
    doc = cf(
        {
            "NetIncomeLoss": [entry("2025-01-01", "2025-12-31", 100, "2026-02-01")],
            "ProfitLoss": [
                entry("2025-01-01", "2025-12-31", 110, "2026-02-01"),
                entry("2024-01-01", "2024-12-31", 90, "2025-02-01"),
            ],
        }
    )
    got = resolve(doc, METRICS["net_income"])
    assert got[(date(2025, 1, 1), date(2025, 12, 31))].value == 100
    assert got[(date(2024, 1, 1), date(2024, 12, 31))].value == 90  # older period, only tag 2


def test_revenue_is_the_largest_total_tag_so_partial_contract_revenue_never_wins():
    # A REIT: contract revenue (ASC 606) excludes rent, so it is a small slice of the total.
    doc = cf(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry("2025-01-01", "2025-12-31", 10, "2026-02-01")
            ],
            "Revenues": [entry("2025-01-01", "2025-12-31", 1000, "2026-02-01")],
        }
    )
    assert extract(doc)["revenue"][(date(2025, 1, 1), date(2025, 12, 31))].value == 1000


def test_reit_revenue_is_contract_revenue_plus_lease_income():
    doc = cf(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry("2025-01-01", "2025-12-31", 5, "2026-02-01")
            ],
            "OperatingLeaseLeaseIncome": [entry("2025-01-01", "2025-12-31", 780, "2026-02-01")],
        }
    )
    assert extract(doc)["revenue"][(date(2025, 1, 1), date(2025, 12, 31))].value == 785


def test_lease_income_alone_is_never_revenue():
    doc = cf({"OperatingLeaseLeaseIncome": [entry("2025-01-01", "2025-12-31", 12, "2026-02-01")]})
    assert extract(doc)["revenue"] == {}


def test_bank_revenue_prefers_net_of_interest_expense():
    doc = cf(
        {
            "Revenues": [entry("2025-01-01", "2025-12-31", 300, "2026-02-01")],
            "RevenuesNetOfInterestExpense": [entry("2025-01-01", "2025-12-31", 180, "2026-02-01")],
        }
    )
    assert extract(doc)["revenue"][(date(2025, 1, 1), date(2025, 12, 31))].value == 180


def test_bank_revenue_falls_back_to_net_interest_plus_noninterest_income():
    doc = cf(
        {
            "InterestIncomeExpenseNet": [entry("2025-01-01", "2025-12-31", 60, "2026-02-01")],
            "NoninterestIncome": [entry("2025-01-01", "2025-12-31", 40, "2026-02-01")],
        }
    )
    assert extract(doc)["revenue"][(date(2025, 1, 1), date(2025, 12, 31))].value == 100


def test_latest_filing_wins_for_restatements():
    doc = cf(
        {
            "Revenues": [
                entry("2024-01-01", "2024-12-31", 90, "2025-02-01"),
                entry("2024-01-01", "2024-12-31", 95, "2026-02-01"),  # restated next year
            ]
        }
    )
    got = resolve(doc, METRICS["revenue"])
    assert got[(date(2024, 1, 1), date(2024, 12, 31))].value == 95


def test_8k_and_registration_facts_are_ignored():
    doc = cf({"Revenues": [entry("2024-01-01", "2024-12-31", 1, "2025-02-01", form="S-1")]})
    assert resolve(doc, METRICS["revenue"]) == {}


def test_eps_history_is_restated_for_a_split():
    # FY2023 is only in the old 10-K. The new 10-K, filed after a 4-for-1 split, restates FY2024.
    doc = cf(
        {
            "EarningsPerShareDiluted": [
                entry("2023-01-01", "2023-12-31", 8.0, "2024-02-01", accn="old"),
                entry("2024-01-01", "2024-12-31", 12.0, "2025-02-01", accn="mid"),
                entry("2024-01-01", "2024-12-31", 3.0, "2026-02-01", accn="new"),
                entry("2025-01-01", "2025-12-31", 4.0, "2026-02-01", accn="new"),
            ]
        }
    )
    got = {p[1].year: f.value for p, f in resolve(doc, METRICS["eps_diluted"]).items()}
    assert got == {2023: 2.0, 2024: 3.0, 2025: 4.0}


def test_ordinary_restatement_is_not_mistaken_for_a_split():
    doc = cf(
        {
            "EarningsPerShareDiluted": [
                entry("2023-01-01", "2023-12-31", 5.0, "2024-02-01", accn="old"),
                entry("2024-01-01", "2024-12-31", 6.0, "2025-02-01", accn="mid"),
                entry("2024-01-01", "2024-12-31", 5.5, "2026-02-01", accn="new"),
            ]
        }
    )
    got = {p[1].year: f.value for p, f in resolve(doc, METRICS["eps_diluted"]).items()}
    assert got[2023] == 5.0


def test_cash_adds_short_term_investments_on_the_same_date():
    doc = cf(
        {
            "CashAndCashEquivalentsAtCarryingValue": [entry(None, "2025-12-31", 10, "2026-02-01")],
            "ShortTermInvestments": [entry(None, "2025-12-31", 5, "2026-02-01")],
        }
    )
    assert extract(doc)["cash"][(None, date(2025, 12, 31))].value == 15


def test_debt_sums_parts_and_falls_back_to_totals():
    parts = cf(
        {
            "LongTermDebtNoncurrent": [entry(None, "2025-12-31", 100, "2026-02-01")],
            "LongTermDebtCurrent": [entry(None, "2025-12-31", 10, "2026-02-01")],
            "CommercialPaper": [entry(None, "2025-12-31", 5, "2026-02-01")],
        }
    )
    assert extract(parts)["debt"][(None, date(2025, 12, 31))].value == 115

    total = cf({"LongTermDebt": [entry(None, "2025-12-31", 80, "2026-02-01")]})
    assert extract(total)["debt"][(None, date(2025, 12, 31))].value == 80

    none = cf({"Assets": [entry(None, "2025-12-31", 1000, "2026-02-01")]})
    assert extract(none)["debt"] == {}  # missing stays missing, never zero


def test_gross_profit_derived_from_revenue_minus_cost():
    doc = cf(
        {
            "Revenues": [entry("2025-01-01", "2025-12-31", 100, "2026-02-01")],
            "CostOfRevenue": [entry("2025-01-01", "2025-12-31", 60, "2026-02-01")],
        }
    )
    gp = extract(doc)["gross_profit"][(date(2025, 1, 1), date(2025, 12, 31))]
    assert gp.value == 40 and gp.tag == "derived"


def test_eps_derived_when_only_per_class_eps_exists():
    doc = cf(
        {
            "NetIncomeLoss": [entry("2025-01-01", "2025-12-31", 100, "2026-02-01")],
            "WeightedAverageNumberOfDilutedSharesOutstanding": [
                entry("2025-01-01", "2025-12-31", 50, "2026-02-01")
            ],
        }
    )
    eps = extract(doc)["eps_diluted"][(date(2025, 1, 1), date(2025, 12, 31))]
    assert eps.value == 2.0 and eps.tag == "derived"


# ---------------------------------------------------------------- TTM


def periods(*facts: Fact) -> dict:
    return {f.period: f for f in facts}


def test_ttm_is_fiscal_year_when_latest_filing_is_a_10k():
    t = T.ttm(periods(fact("2025-01-01", "2025-12-31", 100)))
    assert t.value == 100 and t.basis == "FY"


def test_ttm_adds_ytd_and_subtracts_prior_ytd():
    t = T.ttm(
        periods(
            fact("2025-01-01", "2025-12-31", 100),
            fact("2026-01-01", "2026-09-30", 90),
            fact("2025-01-01", "2025-09-30", 70),
        )
    )
    assert t.value == 120 and t.end == date(2026, 9, 30) and t.basis == "FY+9M"


def test_ttm_ignores_standalone_quarters():
    t = T.ttm(
        periods(
            fact("2025-01-01", "2025-12-31", 100),
            fact("2026-01-01", "2026-06-30", 60),
            fact("2025-01-01", "2025-06-30", 45),
            fact("2026-04-01", "2026-06-30", 31),  # Q2 alone
            fact("2025-04-01", "2025-06-30", 23),
        )
    )
    assert t.value == 115


def test_ttm_handles_52_53_week_years_and_16_week_quarters():
    # Fiscal year ends 2026-01-31; first quarter is 16 weeks (112 days).
    t = T.ttm(
        periods(
            fact("2025-02-02", "2026-01-31", 1000),
            fact("2026-02-01", "2026-05-23", 330),
            fact("2025-02-02", "2025-05-24", 300),
        )
    )
    assert t.value == 1030


def test_ttm_missing_prior_year_ytd_is_none_not_a_guess():
    t = T.ttm(periods(fact("2025-01-01", "2025-12-31", 100), fact("2026-01-01", "2026-03-31", 30)))
    assert t is None


def test_fiscal_year_naming():
    assert T.fiscal_year(date(2025, 9, 27)) == 2025
    assert T.fiscal_year(date(2026, 1, 25)) == 2026
    assert T.fiscal_year(date(2026, 1, 3)) == 2025  # 52/53-week year ending early January


# ---------------------------------------------------------------- formulas


def test_cagr_blank_when_either_end_is_not_positive():
    assert cagr(1.0, 2.0, 1) == pytest.approx(1.0)
    assert cagr(-1.0, 2.0, 5) is None
    assert cagr(1.0, 0.0, 5) is None
    assert cagr(None, 2.0, 5) is None


def test_growth_uses_fiscal_years_n_apart():
    series = {2020: 1.0, 2021: 1.1, 2025: 2.0}
    assert growth(series, 5) == pytest.approx(2 ** (1 / 5) - 1)
    assert growth(series, 3) is None  # no 2022


def base() -> Fundamentals:
    return Fundamentals(
        revenue=1000.0,
        cost_of_revenue=600.0,
        gross_profit=400.0,
        operating_income=200.0,
        pretax_income=180.0,
        income_tax=36.0,
        net_income=144.0,
        eps=1.44,
        depreciation_amortization=50.0,
        interest_expense=20.0,
        operating_cash_flow=220.0,
        capex=70.0,
        dividends_per_share=0.5,
        cash=100.0,
        debt=300.0,
        equity=700.0,
        equity_year_ago=500.0,
        current_assets=400.0,
        current_liabilities=200.0,
        inventory=120.0,
        inventory_year_ago=80.0,
        shares_outstanding=100.0,
    )


def test_filing_ratios():
    r = filing_ratios(base())
    assert r["gross_margin"] == pytest.approx(0.4)
    assert r["operating_margin"] == pytest.approx(0.2)
    assert r["net_margin"] == pytest.approx(0.144)
    assert r["ebitda_ttm"] == 250
    assert r["fcf_ttm"] == 150
    assert r["roe"] == pytest.approx(144 / 600)
    assert r["roic"] == pytest.approx(200 * 0.8 / 900)  # tax rate 20%
    assert r["cash_conversion"] == pytest.approx(150 / 144)
    assert r["debt_to_equity"] == pytest.approx(300 / 700)
    assert r["net_cash_per_share"] == pytest.approx(-2.0)
    assert r["net_debt_ebitda"] == pytest.approx(200 / 250)
    assert r["current_ratio"] == pytest.approx(2.0)
    assert r["interest_coverage"] == pytest.approx(10.0)
    assert r["inventory_turnover"] == pytest.approx(600 / 100)


def test_tax_rate_is_clamped():
    f = base()
    f.income_tax = 90.0  # 50% on 180 pretax, clamped to 35%
    assert filing_ratios(f)["roic"] == pytest.approx(200 * 0.65 / 900)


def test_missing_inputs_give_none_never_zero():
    f = base()
    f.debt = None
    f.interest_expense = None
    r = filing_ratios(f)
    for key in (
        "debt_to_equity",
        "net_cash_per_share",
        "net_debt_ebitda",
        "roic",
        "interest_coverage",
    ):
        assert r[key] is None, key


def test_negative_equity_blanks_equity_ratios():
    f = base()
    f.equity = -50.0
    r = filing_ratios(f)
    assert r["debt_to_equity"] is None and r["roe"] is None


def test_banks_have_no_gross_margin_ebitda_or_current_ratio():
    r = filing_ratios(base(), financial=True)
    assert r["gross_margin"] is None and r["ebitda_ttm"] is None and r["current_ratio"] is None
    assert r["net_margin"] is not None


def test_price_ratios():
    r = filing_ratios(base())
    r["eps_growth_5y"] = 0.20
    p = price_ratios(20.0, r, shares=100.0, equity=700.0, debt=300.0, cash=100.0)
    assert p["market_cap"] == 2000
    assert p["pe"] == pytest.approx(20 / 1.44)
    assert p["peg"] == pytest.approx((20 / 1.44) / 20)
    assert p["price_to_sales"] == pytest.approx(2.0)
    assert p["price_to_book"] == pytest.approx(2000 / 700)
    assert p["enterprise_value"] == 2200
    assert p["ev_ebitda"] == pytest.approx(2200 / 250)
    assert p["fcf_yield"] == pytest.approx(150 / 2000)
    assert p["dividend_yield"] == pytest.approx(0.5 / 20)


def test_peg_falls_back_to_three_year_growth_and_blanks_on_losses():
    r = filing_ratios(base())
    r["eps_growth_5y"], r["eps_growth_3y"] = None, 0.10
    assert price_ratios(20.0, r, 100.0, 700.0, 300.0, 100.0)["peg"] == pytest.approx(
        (20 / 1.44) / 10
    )
    r["eps_ttm"] = -1.0
    p = price_ratios(20.0, r, 100.0, 700.0, 300.0, 100.0)
    assert p["pe"] is None and p["peg"] is None


# ---------------------------------------------------------------- sectors


@pytest.mark.parametrize(
    "sic, sector",
    [
        (3674, "Semiconductors"),
        (2834, "Pharma and biotech"),
        (7372, "Software and IT services"),
        (6021, "Banks"),
        (5961, "Retail"),
        (1311, "Oil and gas"),
        (6798, "Real estate"),
        (3711, "Autos"),
        (4911, "Utilities"),
        (None, None),
    ],
)
def test_sector_for_sic(sic, sector):
    assert sector_for_sic(sic) == sector


def test_is_financial():
    assert is_financial(6022) and is_financial(6311) and not is_financial(6798)


def test_trailing_eps_falls_back_when_a_split_mixes_share_bases():
    from app.pipeline.ratios import fundamentals

    # FY2025 EPS on the old basis (-1.0, net income -1,000 over 1,000 shares). A 1-for-100
    # reverse split, then the Q1 10-Q reports both Q1s on the new basis (10 shares).
    # Reported TTM = -1 + (-25) - (-25) = -1, on the wrong basis. Net income TTM is -1,000;
    # the 10-Q's own figures give -25 EPS on -250 net income, so 10 shares: -100 a share.
    def f(metric, start, end, value):
        return fact(start, end, value, metric=metric)

    facts = {
        "eps_diluted": periods(
            f("eps_diluted", "2025-01-01", "2025-12-31", -1.0),
            f("eps_diluted", "2026-01-01", "2026-03-31", -25.0),
            f("eps_diluted", "2025-01-01", "2025-03-31", -25.0),
        ),
        "net_income": periods(
            f("net_income", "2025-01-01", "2025-12-31", -1_000.0),
            f("net_income", "2026-01-01", "2026-03-31", -250.0),
            f("net_income", "2025-01-01", "2025-03-31", -250.0),
        ),
    }
    assert fundamentals(facts).eps == pytest.approx(-100.0)


def test_trailing_eps_kept_when_it_agrees():
    from app.pipeline.ratios import fundamentals

    def f(metric, start, end, value):
        return fact(start, end, value, metric=metric)

    facts = {
        "eps_diluted": periods(
            f("eps_diluted", "2025-01-01", "2025-12-31", 8.0),
            f("eps_diluted", "2026-01-01", "2026-03-31", 2.1),
            f("eps_diluted", "2025-01-01", "2025-03-31", 2.0),
        ),
        "net_income": periods(
            f("net_income", "2025-01-01", "2025-12-31", 800.0),
            f("net_income", "2026-01-01", "2026-03-31", 210.0),
            f("net_income", "2025-01-01", "2025-03-31", 200.0),
        ),
    }
    assert fundamentals(facts).eps == pytest.approx(8.1)


def test_implausible_pe_is_left_blank():
    r = filing_ratios(base())
    r["eps_ttm"] = 50.0  # above the 20 price
    p = price_ratios(20.0, r, 100.0, 700.0, 300.0, 100.0)
    assert p["pe"] is None and p["peg"] is None
