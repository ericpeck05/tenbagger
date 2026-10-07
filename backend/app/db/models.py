"""Database tables. See the data model in SPEC.md."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.pipeline.ratios import PRICE_RATIOS


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    cik: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    name: Mapped[str] = mapped_column(String(200))
    exchange: Mapped[str | None] = mapped_column(String(20))
    sic_code: Mapped[int | None] = mapped_column(Integer)
    sic_description: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(60), index=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(4))  # MMDD
    tier: Mapped[str] = mapped_column(String(8), default="cold")
    in_sp500: Mapped[bool] = mapped_column(default=False)
    supported: Mapped[bool] = mapped_column(default=True)  # False for 20-F/40-F filers
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    facts_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    submissions_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)


class Ticker(Base):
    """Every ticker that maps to a company. Multi-class companies have more than one."""

    __tablename__ = "tickers"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"), index=True)
    is_primary: Mapped[bool] = mapped_column(default=True)


class FactRow(Base):
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    metric: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[date | None] = mapped_column(Date)  # null for balance sheet items
    period_end: Mapped[date] = mapped_column(Date)
    fiscal_period: Mapped[str | None] = mapped_column(String(4))  # FY, Q1, Q2, Q3
    value: Mapped[float] = mapped_column(Float)
    form: Mapped[str] = mapped_column(String(10))
    filed_at: Mapped[date] = mapped_column(Date)
    accession: Mapped[str] = mapped_column(String(25))
    source_tag: Mapped[str] = mapped_column(String(120))

    __table_args__ = (Index("ix_facts_cik_metric", "cik", "metric", "period_end"),)


class Filing(Base):
    __tablename__ = "filings"

    # One filing can be listed under several companies (joint filings, parent and subsidiary).
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"), primary_key=True)
    accession: Mapped[str] = mapped_column(String(25), primary_key=True)
    form: Mapped[str] = mapped_column(String(12))
    period: Mapped[date | None] = mapped_column(Date)
    filed_at: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(Text)


RATIO_COLUMNS = (
    "revenue_ttm",
    "net_income_ttm",
    "eps_ttm",
    "ebitda_ttm",
    "fcf_ttm",
    "dps_ttm",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roic",
    "cash_conversion",
    "debt_to_equity",
    "net_cash",
    "net_cash_per_share",
    "net_debt_ebitda",
    "current_ratio",
    "interest_coverage",
    "inventory_turnover",
    *(
        f"{name}_growth_{y}y"
        for name in ("revenue", "eps", "fcf", "bvps", "inventory", "shares")
        for y in (1, 3, 5)
    ),
    # Inputs kept so price-based ratios can be recomputed from this row alone
    "shares_outstanding",
    "equity",
    "debt",
    "cash",
    # Price-based, filled once a quote is known
    "price",
    *PRICE_RATIOS,
)


class Ratio(Base):
    """One row per company: every ratio on the stock page, as of its latest filing."""

    __tablename__ = "ratios"

    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"), primary_key=True)
    as_of: Mapped[date | None] = mapped_column(Date)  # end of the latest period with data
    ttm_basis: Mapped[str | None] = mapped_column(String(10))
    fundamentals_through: Mapped[date | None] = mapped_column(Date)  # filing date
    fundamentals_form: Mapped[str | None] = mapped_column(String(10))
    computed_at: Mapped[datetime] = mapped_column(DateTime)
    price_at: Mapped[datetime | None] = mapped_column(DateTime)
    lynch_category: Mapped[str | None] = mapped_column(String(20))
    lynch_score: Mapped[float | None] = mapped_column(Float)


# Declarative mapping accepts columns added after the class body; this keeps the long list
# of ratio columns in one place.
for _col in RATIO_COLUMNS:
    setattr(Ratio, _col, mapped_column(_col, Float, nullable=True))
