"""Each ratio's 5-year range: its low and high across the last five fiscal year ends.

Ratios that use a price are computed from the closing price on each fiscal year end date, so
a company with no stored price history has ranges for its filing-based ratios only.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RatioHistory
from app.pipeline.holdings import Closes
from app.pipeline.lynch_config import RANGE_YEARS
from app.pipeline.ratios import price_ratios

METRICS = (
    "pe", "peg", "price_to_sales", "price_to_book", "ev_ebitda", "fcf_yield",
    "gross_margin", "operating_margin", "net_margin", "roe", "roic", "cash_conversion",
    "debt_to_equity", "net_cash_per_share", "net_debt_ebitda", "current_ratio",
    "interest_coverage", "inventory_turnover",
)  # fmt: skip
PRICE_METRICS = {"pe", "peg", "price_to_sales", "price_to_book", "ev_ebitda", "fcf_yield"}


def five_year(session: Session, cik: int, ticker: str) -> dict:
    rows = session.scalars(
        select(RatioHistory).where(RatioHistory.cik == cik).order_by(RatioHistory.fiscal_year)
    ).all()[-RANGE_YEARS:]
    if not rows:
        return {"years": [], "metrics": {}, "missing_prices": False}
    closes = Closes(session, [ticker], rows[0].period_end - timedelta(days=10))
    per_year: list[dict] = []
    missing_prices = False
    for row in rows:
        values = {m: getattr(row, m, None) for m in METRICS if m not in PRICE_METRICS}
        close = closes(ticker, row.period_end)
        if close is None:
            missing_prices = True
        inputs = {
            c: getattr(row, c)
            for c in (
                "eps_ttm",
                "eps_growth_5y",
                "eps_growth_3y",
                "revenue_ttm",
                "ebitda_ttm",
                "fcf_ttm",
                "dps_ttm",
            )
        }
        values.update(
            price_ratios(close, inputs, row.shares_outstanding, row.equity, row.debt, row.cash)
        )
        per_year.append({"fiscal_year": row.fiscal_year, "values": values})

    metrics = {}
    for m in METRICS:
        series = [y["values"].get(m) for y in per_year]
        present = [v for v in series if v is not None]
        metrics[m] = {
            "low": min(present) if present else None,
            "high": max(present) if present else None,
            "values": series,
        }
    return {
        "years": [y["fiscal_year"] for y in per_year],
        "metrics": metrics,
        "missing_prices": missing_prices,
    }
