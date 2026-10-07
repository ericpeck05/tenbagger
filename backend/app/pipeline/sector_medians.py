"""Sector medians: the median of each ratio across a sector's companies above $300M."""

from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Company, Ratio, SectorMedian
from app.pipeline.lynch_config import MEDIAN_MIN_MARKET_CAP
from app.pipeline.pricing import utcnow

METRICS = (
    "pe", "peg", "price_to_sales", "price_to_book", "ev_ebitda", "fcf_yield",
    "gross_margin", "operating_margin", "net_margin", "roe", "roic", "cash_conversion",
    "debt_to_equity", "net_cash_per_share", "net_debt_ebitda", "current_ratio",
    "interest_coverage", "inventory_turnover",
    *(f"{m}_growth_{y}y" for m in ("revenue", "eps", "fcf", "bvps", "inventory", "shares")
      for y in (1, 3, 5)),
)  # fmt: skip


def recompute(session: Session) -> int:
    """Rebuild the table. Returns the number of sectors."""
    rows = session.execute(
        select(Company.sector, Ratio)
        .join(Ratio, Ratio.cik == Company.cik)
        .where(Company.sector.is_not(None), Ratio.market_cap > MEDIAN_MIN_MARKET_CAP)
    ).all()
    by_sector: dict[str, list[Ratio]] = {}
    for sector, ratio in rows:
        by_sector.setdefault(sector, []).append(ratio)
    session.execute(delete(SectorMedian))
    now = utcnow()
    for sector, ratios in by_sector.items():
        for metric in METRICS:
            values = [v for r in ratios if (v := getattr(r, metric)) is not None]
            session.add(
                SectorMedian(
                    sector=sector,
                    metric=metric,
                    value=median(values) if values else None,
                    companies=len(values),
                    as_of=now,
                )
            )
    session.commit()
    return len(by_sector)


def for_sector(session: Session, sector: str | None) -> dict[str, dict] | None:
    if not sector:
        return None
    rows = session.scalars(select(SectorMedian).where(SectorMedian.sector == sector)).all()
    if not rows:
        return None
    return {r.metric: {"value": r.value, "companies": r.companies} for r in rows}
