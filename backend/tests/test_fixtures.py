"""Acceptance gate for the fundamentals pipeline.

For 10 well-known companies, the pipeline's figures for the latest fiscal year in the saved
EDGAR data must match the 10-K within 1%. Expected values were read from the financial
statements printed in each 10-K (in millions of dollars, EPS in dollars), cited by accession
number. Revenue is the top line, net income is attributable to the company's shareholders,
and equity is shareholders' equity excluding noncontrolling interests where the 10-K shows both.
"""

import gzip
import json
from pathlib import Path

import pytest

from app.pipeline import ttm as T
from app.pipeline.tags import extract

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
M = 1e6

# ticker: (fiscal year, 10-K accession, revenue, net income, diluted EPS, equity)
EXPECTED = {
    "AAPL": (2025, "0000320193-25-000079", 416_161, 112_010, 7.46, 73_733),
    "MSFT": (2026, "0001193125-26-323660", 331_839, 133_749, 17.95, 442_387),
    "NVDA": (2026, "0001045810-26-000021", 215_938, 120_067, 4.90, 157_293),
    "AMZN": (2025, "0001018724-26-000004", 716_924, 77_670, 7.17, 411_065),
    "GOOGL": (2025, "0001652044-26-000018", 402_836, 132_170, 10.81, 415_265),
    "JPM": (2025, "0001628280-26-008131", 182_447, 57_048, 20.02, 362_438),
    "WMT": (2026, "0000104169-26-000055", 713_163, 21_893, 2.73, 99_617),
    "JNJ": (2025, "0000200406-26-000016", 94_193, 26_804, 11.03, 81_544),
    "KO": (2025, "0001628280-26-010047", 47_941, 13_107, 3.04, 32_169),
    "PG": (2026, "0000080424-26-000103", 87_032, 16_046, 6.62, 54_311),
}


def load(ticker: str) -> dict:
    return json.loads(gzip.decompress((FIXTURES / f"{ticker}.json.gz").read_bytes()))


def close(actual: float | None, expected: float, tolerance: float = 0.01) -> bool:
    return actual is not None and abs(actual - expected) <= tolerance * abs(expected)


@pytest.fixture(scope="module", params=sorted(EXPECTED))
def company(request):
    ticker = request.param
    return ticker, extract(load(ticker)), EXPECTED[ticker]


def test_latest_fiscal_year_is_the_10k_year(company):
    ticker, facts, (year, accession, *_) = company
    annual = T.annual(facts["revenue"])
    assert max(annual) == year, f"{ticker}: latest fiscal year {max(annual)}, expected {year}"
    assert annual[year].accession == accession


@pytest.mark.parametrize(
    "metric, index, scale",
    [("revenue", 2, M), ("net_income", 3, M), ("eps_diluted", 4, 1.0)],
)
def test_annual_figures_match_10k(company, metric, index, scale):
    ticker, facts, expected = company
    year = expected[0]
    value = T.annual(facts[metric]).get(year)
    want = expected[index] * scale
    got = value.value if value else None
    assert close(got, want), f"{ticker} FY{year} {metric}: got {got}, 10-K says {want}"


def test_equity_matches_10k(company):
    ticker, facts, expected = company
    year, equity = expected[0], expected[5] * M
    fy_end = T.annual(facts["revenue"])[year].end
    value = T.at(facts["equity"], fy_end)
    got = value.value if value else None
    assert close(got, equity), f"{ticker} FY{year} equity: got {got}, 10-K says {equity}"
