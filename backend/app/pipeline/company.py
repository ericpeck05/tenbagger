"""Turn one company's EDGAR JSON into rows: company, tickers, filings, facts, and ratios."""

from datetime import UTC, date, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Company, FactRow, Filing, Ratio, Ticker
from app.pipeline import ttm as T
from app.pipeline.ratios import filing_ratios, fundamentals
from app.pipeline.sector import is_financial, sector_for_sic
from app.pipeline.tags import ALLOWED_FORMS, extract, is_foreign_filer
from app.providers.edgar import filing_url

FILING_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "4", "4/A"}

# 8-K item numbers, in the words the filings list shows. 9.01 (exhibits) is never the headline.
EIGHT_K_ITEMS = {
    "1.01": "Material agreement",
    "1.02": "Agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "1.05": "Cybersecurity incident",
    "2.01": "Acquisition or disposal completed",
    "2.02": "Results of operations",
    "2.03": "New debt obligation",
    "2.04": "Debt obligation accelerated",
    "2.05": "Restructuring costs",
    "2.06": "Impairment",
    "3.01": "Listing notice",
    "3.02": "Unregistered share sale",
    "3.03": "Change to shareholder rights",
    "4.01": "Auditor change",
    "4.02": "Prior financials no longer reliable",
    "5.01": "Change in control",
    "5.02": "Officer or director change",
    "5.03": "Charter or bylaw amendment",
    "5.07": "Shareholder vote results",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fmt_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def filing_title(form: str, report_date: date | None, items: str) -> str:
    base = form.removesuffix("/A")
    amended = " (amended)" if form.endswith("/A") else ""
    if base == "10-K":
        return (
            f"Fiscal year {T.fiscal_year(report_date)}" if report_date else "Annual report"
        ) + amended
    if base == "10-Q":
        return (
            f"Quarter ended {_fmt_date(report_date)}" if report_date else "Quarterly report"
        ) + amended
    if base == "8-K":
        names = [EIGHT_K_ITEMS[i] for i in items.split(",") if i.strip() in EIGHT_K_ITEMS]
        return (", ".join(names[:2]) or "Current report") + amended
    if base == "4":
        return "Insider transaction" + amended
    return form


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def upsert_company(
    session: Session,
    cik: int,
    submissions: dict,
    *,
    tickers: list[str],
    name: str | None = None,
    in_sp500: bool = False,
) -> Company:
    company = session.get(Company, cik) or Company(cik=cik, tier="cold", view_count=0)
    sub_tickers = submissions.get("tickers") or []
    exchanges = submissions.get("exchanges") or []
    primary = tickers[0] if tickers else (sub_tickers[0] if sub_tickers else str(cik))
    sec_form = primary.replace(".", "-")
    exchange = None
    if sec_form in sub_tickers and sub_tickers.index(sec_form) < len(exchanges):
        exchange = exchanges[sub_tickers.index(sec_form)]
    elif exchanges:
        exchange = exchanges[0]

    sic = submissions.get("sic")
    company.ticker = primary
    company.name = name or submissions.get("name") or primary
    company.exchange = (exchange or "").upper() or None
    company.sic_code = int(sic) if sic else None
    company.sic_description = submissions.get("sicDescription")
    company.sector = sector_for_sic(sic)
    company.fiscal_year_end = submissions.get("fiscalYearEnd")
    company.in_sp500 = in_sp500 or company.in_sp500
    if in_sp500:
        company.tier = "warm"
    company.submissions_fetched_at = _now()
    session.add(company)
    session.flush()

    for i, t in enumerate(tickers):
        row = session.get(Ticker, t) or Ticker(ticker=t)
        row.cik, row.is_primary = cik, i == 0
        session.add(row)
    return company


def store_filings(session: Session, cik: int, submissions: dict) -> int:
    recent = submissions.get("filings", {}).get("recent", {})
    keys = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")
    columns = [recent.get(k, []) for k in keys]
    session.execute(delete(Filing).where(Filing.cik == cik))
    count = 0
    for accession, form, filed, report, doc, items in zip(*columns, strict=False):
        if form not in FILING_FORMS:
            continue
        period = _parse_date(report)
        session.add(
            Filing(
                accession=accession,
                cik=cik,
                form=form,
                period=period,
                filed_at=date.fromisoformat(filed),
                title=filing_title(form, period, items or ""),
                url=filing_url(cik, accession, doc) if doc else filing_url(cik, accession, ""),
            )
        )
        count += 1
    return count


def store_facts_and_ratios(session: Session, company: Company, companyfacts: dict) -> dict:
    """Replace a company's facts and recompute its filing-based ratios. Returns the ratios."""
    cik = company.cik
    session.execute(delete(FactRow).where(FactRow.cik == cik))
    if is_foreign_filer(companyfacts):
        company.supported = False
        session.execute(delete(Ratio).where(Ratio.cik == cik))
        return {}
    company.supported = True

    facts = extract(companyfacts)
    fy_ends = sorted(
        {
            f.end
            for name in ("revenue", "net_income")
            for f in facts.get(name, {}).values()
            if T.is_annual(f)
        }
    )
    latest_filing: tuple[date, str] | None = None
    for metric, periods in facts.items():
        for f in periods.values():
            label = T.fiscal_period_label(f, fy_ends)
            if f.start is not None and label is None:
                continue  # standalone quarters; the pipeline works from year-to-date figures
            session.add(
                FactRow(
                    cik=cik,
                    metric=metric,
                    period_start=f.start,
                    period_end=f.end,
                    fiscal_period=label,
                    value=f.value,
                    form=f.form,
                    filed_at=f.filed,
                    accession=f.accession,
                    source_tag=f.tag,
                )
            )
            if f.form in ALLOWED_FORMS and (latest_filing is None or f.filed > latest_filing[0]):
                latest_filing = (f.filed, f.form)

    fund = fundamentals(facts)
    ratios = filing_ratios(fund, financial=is_financial(company.sic_code))
    row = session.get(Ratio, cik) or Ratio(cik=cik)
    row.as_of = fund.as_of
    row.ttm_basis = fund.ttm_basis
    row.fundamentals_through = latest_filing[0] if latest_filing else None
    row.fundamentals_form = latest_filing[1] if latest_filing else None
    row.computed_at = _now()
    for key, value in ratios.items():
        setattr(row, key, value)
    row.shares_outstanding = fund.shares_outstanding
    row.equity, row.debt, row.cash = fund.equity, fund.debt, fund.cash
    session.add(row)
    company.facts_fetched_at = _now()
    return ratios


def process_company(
    session: Session,
    cik: int,
    submissions: dict,
    companyfacts: dict | None,
    *,
    tickers: list[str],
    name: str | None = None,
    in_sp500: bool = False,
) -> Company:
    """Load one company from its EDGAR JSON: company row, tickers, filings, facts, ratios.

    `companyfacts` is None for filers with no XBRL facts; they keep their filings only.
    """
    company = upsert_company(
        session, cik, submissions, tickers=tickers, name=name, in_sp500=in_sp500
    )
    store_filings(session, cik, submissions)
    if companyfacts is not None:
        store_facts_and_ratios(session, company, companyfacts)
    return company
