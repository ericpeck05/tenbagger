"""Whole-market pieces: daily index parsing, tier promotion and demotion, name tidying."""

from datetime import date, timedelta

from app.db.models import Company, CompanyView, WatchItem
from app.jobs import tiers
from app.jobs.bulk_load import tidy_name
from app.jobs.refresh_filings import parse_index
from app.pipeline.pricing import utcnow

INDEX = """Description:           Daily Index of EDGAR Dissemination Feed by Company Name
Last Data Received:    October 6, 2026

CIK|Company Name|Form Type|Date Filed|Filename
--------------------------------------------------------------------------------
320193|Apple Inc.|4|20261006|edgar/data/320193/0000320193-26-000101.txt
1000045|NICHOLAS FINANCIAL INC|10-Q|20261006|edgar/data/1000045/0001000045-26-000020.txt
"""


def test_parse_master_index():
    assert parse_index(INDEX) == [
        (320193, "4", date(2026, 10, 6)),
        (1000045, "10-Q", date(2026, 10, 6)),
    ]


def test_tidy_name():
    assert tidy_name("ACME UNITED CORP") == "Acme United Corp"
    assert tidy_name("ENERGY TRANSFER LP") == "Energy Transfer LP"
    assert tidy_name("Apple Inc.") == "Apple Inc."
    assert tidy_name("SPDR S&P 500 ETF TRUST") == "SPDR S&P 500 ETF Trust"
    assert tidy_name("AGNICO EAGLE MINES LTD") == "Agnico Eagle Mines Ltd"
    assert tidy_name("H&R BLOCK INC") == "H&R Block Inc"


def _company(session, cik, ticker, tier, in_sp500=False, last_viewed=None):
    session.add(
        Company(
            cik=cik,
            ticker=ticker,
            name=ticker,
            tier=tier,
            in_sp500=in_sp500,
            view_count=0,
            last_viewed_at=last_viewed,
        )
    )


def test_promotion_and_demotion(db):
    now = utcnow()
    _company(db, 1, "BIG", "warm", in_sp500=True)  # S&P: always warm
    _company(db, 2, "HOT", "cold", last_viewed=now)  # opened 3 times this month
    _company(db, 3, "MEH", "cold", last_viewed=now)  # opened twice
    _company(db, 4, "OLD", "warm", last_viewed=now - timedelta(days=120))  # unopened 90+ days
    _company(db, 5, "WAT", "warm", last_viewed=now - timedelta(days=120))  # but on the watchlist
    _company(db, 6, "FRESH", "warm", last_viewed=now - timedelta(days=10))
    from app.db.models import Ticker

    for cik, t in [(1, "BIG"), (2, "HOT"), (3, "MEH"), (4, "OLD"), (5, "WAT"), (6, "FRESH")]:
        db.add(Ticker(ticker=t, cik=cik, is_primary=True))
    db.add(WatchItem(ticker="WAT", added_at=now, position=1))
    for _ in range(3):
        db.add(CompanyView(cik=2, viewed_at=now - timedelta(days=2)))
    for _ in range(2):
        db.add(CompanyView(cik=3, viewed_at=now - timedelta(days=2)))
    db.add(CompanyView(cik=3, viewed_at=now - timedelta(days=40)))  # outside the window
    db.commit()

    result = tiers.run(db)

    tier = {c.ticker: c.tier for c in db.query(Company).all()}
    assert tier == {
        "BIG": "warm",
        "HOT": "warm",
        "MEH": "cold",
        "OLD": "cold",
        "WAT": "warm",
        "FRESH": "warm",
    }
    assert result == {"promoted": 1, "demoted": 1}
    assert db.query(CompanyView).filter(CompanyView.cik == 3).count() == 2  # old view pruned
